#!/usr/bin/env python3
"""
Test-Isolation Cache-Guard Validator
====================================

Catches the shard-order-fragile test-isolation anti-pattern that flaked CI twice
(commits 5caed9e8, and the Bank Transaction reconciliation permission tests):

    a test asserts a permission/role READ (frappe.has_permission, get_roles,
    doc.has_permission, ...) as a pre-check GUARD *before* switching user with
    frappe.set_user()/self.as_user()/self.as_role().

That guard resolves the permission through the request-local role_permissions/meta
cache of the CURRENT (Administrator) context. In a shared-process parallel shard
that cache layer can hold a stale answer for a freshly-granted role/DocPerm, so the
guard flakes deterministically on certain shard compositions -- while the grant is
correct in the DB and the behaviour-under-test (after set_user() clears the caches)
resolves fine. See docs/superpowers/specs/2026-07-25-test-isolation-cache-guard-design.md.

Scope (intentionally NARROW / precision-favoring -- this is the recurring gate, not
the one-time audit): a reader that appears in a test/setUp function BEFORE the first
user-switch in that SAME function. It does NOT attempt the cross-function
setUp-grant -> test-read shape (that was covered by the one-time audit); a per-file
gate cannot detect that soundly without a high false-positive rate.

Nested function/lambda/class scopes are NOT descended into: a closure defined inside
a test (e.g. an @critical_api-decorated function that is the code-under-test) runs at
call time, often inside a `with as_user(...)` block, so its statements are not part of
the outer test's linear control flow.

Suppression
-----------
A flagged assertion opts out with a trailing comment on any of its physical lines:

    self.assertFalse(frappe.has_permission(...))  # cache-guard-ok: baseline-intentional

Reason MUST be one of:
    baseline-intentional  -- the pre-switch read deliberately tests the current
                             context (note: still somewhat cache-sensitive by nature).
    false-positive        -- the analyzer is wrong here; please also report so the
                             detector can be tightened.
    relocated-elsewhere   -- the meaningful check now lives after the switch.

An unknown reason is itself reported.

Usage
-----
    python scripts/validation/test_isolation_cache_guard_validator.py FILE [FILE ...]

Advisory by default (prints findings, exits 0). Pass --strict (or set
CACHE_GUARD_STRICT=1) to exit non-zero on any unsuppressed finding -- flip this on
only after the audit report is empty AND the false-positive rate is validated.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Calls that switch user (each also clears the request-local perm caches).
SWITCH_NAMES = {"set_user", "as_user", "as_role"}
# Calls that READ Frappe permission/role/cache state.
READER_NAMES = {
    "has_permission",
    "get_roles",
    "get_doc_permissions",
    "has_perm",
    "get_all_perms",
    "check_permission",
}
# Attribute reads of the request-local cache layers themselves.
CACHE_ATTRS = {"role_permissions", "user_perms"}

VALID_REASONS = {"baseline-intentional", "false-positive", "relocated-elsewhere"}
_MARKER = re.compile(r"#\s*cache-guard-ok\s*:\s*([a-z-]+)?")


@dataclass
class Finding:
    file: str
    line: int
    func: str
    reader: str
    switch_line: int
    suppressed: bool
    bad_reason: str | None = None


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _own_nodes(fn: ast.AST):
    """Walk fn's body without descending into nested function/lambda/class scopes."""
    SCOPE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    stack = list(getattr(fn, "body", []))
    while stack:
        node = stack.pop()
        if isinstance(node, SCOPE):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _first_switch_line(fn: ast.AST) -> int | None:
    lines = []
    for node in _own_nodes(fn):
        if isinstance(node, ast.With):
            for item in node.items:
                ce = item.context_expr
                if isinstance(ce, ast.Call) and _call_name(ce) in SWITCH_NAMES:
                    lines.append(node.lineno)
        elif isinstance(node, ast.Call) and _call_name(node) in SWITCH_NAMES:
            lines.append(node.lineno)
    return min(lines) if lines else None


def _reader_calls(fn: ast.AST):
    """Yield (call_lineno, reader_name) for every perm/role/cache READ, at call
    granularity.

    Call granularity (not enclosing-statement granularity) is essential: a reader
    nested inside a compound statement (``try:``/``if:``/``with:``) whose header line
    precedes a switch that is ALSO inside that compound would be a false positive if
    compared by the statement's header line. Comparing the reader call's own line
    against the switch call's own line matches execution order for the linear cases
    this gate targets.
    """
    for node in _own_nodes(fn):
        if isinstance(node, ast.Call) and _call_name(node) in READER_NAMES:
            yield node.lineno, _call_name(node)
        elif isinstance(node, ast.Attribute) and node.attr in CACHE_ATTRS:
            yield node.lineno, node.attr


def _enclosing_stmt_span(fn: ast.AST, line: int) -> tuple[int, int]:
    """Smallest own-statement span (lineno, end_lineno) containing `line`, for
    scanning the suppression comment. Falls back to the single line."""
    best = (line, line)
    best_size = 10**9
    for node in _own_nodes(fn):
        if not isinstance(node, ast.stmt):
            continue
        start = node.lineno
        end = getattr(node, "end_lineno", start) or start
        if start <= line <= end and (end - start) < best_size:
            best, best_size = (start, end), end - start
    return best


def _suppression(span: tuple[int, int], src_lines: list[str]) -> tuple[bool, str | None]:
    """Return (is_suppressed, bad_reason). Scans the given physical line span."""
    start, end = span
    for ln in range(start, end + 1):
        if ln - 1 >= len(src_lines):
            break
        m = _MARKER.search(src_lines[ln - 1])
        if m:
            reason = m.group(1)
            if reason in VALID_REASONS:
                return True, None
            return False, reason or "(missing)"
    return False, None


def _iter_functions(tree: ast.AST):
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        for m in cls.body:
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if m.name == "setUp" or m.name.startswith("test"):
                    yield m


def check_file(path: Path) -> list[Finding]:
    try:
        src = path.read_text()
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []
    src_lines = src.splitlines()
    findings: list[Finding] = []
    for fn in _iter_functions(tree):
        switch = _first_switch_line(fn)
        if switch is None:
            continue  # no user-switch in this function -> not the pre-switch-guard shape
        for line, reader in _reader_calls(fn):
            if line >= switch:
                continue  # reader is at/after the switch -> fresh resolution -> safe
            suppressed, bad = _suppression(_enclosing_stmt_span(fn, line), src_lines)
            findings.append(Finding(str(path), line, fn.name, reader,
                                    switch, suppressed, bad))
    return findings


def _is_test_file(path: Path) -> bool:
    return path.suffix == ".py" and path.name.startswith("test_")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    strict = "--strict" in argv[1:] or os.environ.get("CACHE_GUARD_STRICT") == "1"
    paths = [Path(p) for p in args]
    if not paths:
        print("usage: test_isolation_cache_guard_validator.py FILE [FILE ...]",
              file=sys.stderr)
        return 2

    active = 0        # unsuppressed real findings
    bad_reasons = 0   # suppression comments with an invalid reason
    for path in paths:
        if not path.is_file() or not _is_test_file(path):
            continue
        for f in check_file(path):
            if f.bad_reason is not None:
                bad_reasons += 1
                print(f"{f.file}:{f.line}: cache-guard-ok reason '{f.bad_reason}' is not "
                      f"valid; use one of {sorted(VALID_REASONS)}")
                continue
            if f.suppressed:
                continue
            active += 1
            print(f"{f.file}:{f.line}: {f.func}() reads {f.reader!r} BEFORE the user "
                  f"switch at line {f.switch_line}. This resolves permissions through "
                  f"the stale pre-set_user cache and is shard-order-fragile. Move the "
                  f"check after the switch, or delete it if a post-switch assertion "
                  f"already proves it (see 5caed9e8). If intentional, annotate "
                  f"'# cache-guard-ok: <reason>'.")

    problems = active + bad_reasons
    if problems:
        mode = "STRICT" if strict else "advisory"
        print(f"\n{active} cache-guard finding(s), {bad_reasons} invalid suppression "
              f"reason(s) [{mode}].", file=sys.stderr)
        return 1 if strict else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
