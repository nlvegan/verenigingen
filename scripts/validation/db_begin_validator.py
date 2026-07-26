#!/usr/bin/env python3
"""
Implicit-Commit Guard Validator (frappe.db.begin / raw TRUNCATE)
================================================================

Catches the transaction anti-pattern that silently broke four call sites in this
codebase (see docs/audits/2026-07-26-known-test-failures-baseline-triage.md):

    frappe.db.begin()   # -> START TRANSACTION

Frappe refuses START TRANSACTION whenever the current transaction already has
pending writes:

    frappe.exceptions.ImplicitCommitError:
        ('This statement can cause implicit commit', 'START TRANSACTION')

`transaction_writes` reaches 1 after ANY write in the request -- a doc.save()/
insert(), a frappe.db.set_value(), a File attachment, even a frappe.log_error().
Since whether a write happened depends on the CALLER, a begin() call site cannot
be proven safe by reading it: it is safe only while every caller happens to
arrive with a clean transaction, and one upstream save arms it. Callers that
swallow exceptions (a generic "operation failed" response) turn this into a
silent, permanent failure rather than a visible error.

What flags:
  1. `frappe.db.begin()` (any `<x>.db.begin()` attribute chain).
  2. `frappe.db.sql("TRUNCATE ...")` -- a raw TRUNCATE is DDL and trips the same
     guard independently. Use `frappe.db.sql_ddl()`.

The fix is almost never a savepoint
-----------------------------------
These call sites overwhelmingly bracket a `SELECT ... FOR UPDATE`, where the
explicit commit() on an early return is what RELEASES the row lock. Releasing a
savepoint does NOT free row locks -- converting would silently hold them until
request end. The correct fix, applied five times in this repo, is to DELETE the
begin() and keep the FOR UPDATE plus the existing commit()/rollback(): the lock
is taken inside the ambient request transaction and released by the same commit
as before. See api/sepa_phantom_hash_admin.py and api/schedule_maintenance.py.

Suppression
-----------
A justified call site opts out with a trailing comment on any of its physical
lines:

    frappe.db.begin()  # db-begin-ok: own-connection

Reason MUST be one of:
    own-connection        -- runs on its own fresh connection (a thread or job
                             that called frappe.connect() itself), so
                             transaction_writes is 0 by construction.
    patch-context         -- runs under `bench migrate` / a patch, outside any
                             request transaction.
    verified-clean-caller -- EVERY caller provably reaches here with no pending
                             writes. Name them in an adjacent comment; this
                             claim rots the moment a caller adds a save().
    false-positive        -- the analyzer is wrong here; please also report it.

An unknown reason is itself reported.

Usage
-----
    python scripts/validation/db_begin_validator.py FILE [FILE ...]
    python scripts/validation/db_begin_validator.py --all verenigingen

Advisory by default (prints findings, exits 0). Pass --strict (or set
DB_BEGIN_STRICT=1) to exit non-zero on any unsuppressed finding -- flip that on
once the inventory is annotated.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

VALID_REASONS = {
    "own-connection",
    "patch-context",
    "verified-clean-caller",
    "false-positive",
}
_MARKER = re.compile(r"#\s*db-begin-ok\s*:\s*([a-z-]+)?")

KIND_BEGIN = "begin"
KIND_TRUNCATE = "truncate"

# Trees that are not production request code: tests legitimately provoke the
# guard, and archived code is not shipped.
_SKIP_PARTS = ("tests", "test")
_SKIP_PREFIXES = ("archived_", "archived_unused", "archived_deleted")


@dataclass
class Finding:
    file: str
    line: int
    func: str
    kind: str
    suppressed: bool
    bad_reason: str | None = None


def _is_db_begin(node: ast.Call) -> bool:
    """Match <anything>.db.begin() -- frappe.db.begin(), frappe.local.db.begin()."""
    f = node.func
    return (
        isinstance(f, ast.Attribute)
        and f.attr == "begin"
        and isinstance(f.value, ast.Attribute)
        and f.value.attr == "db"
    )


def _is_raw_truncate(node: ast.Call) -> bool:
    """Match <anything>.db.sql("TRUNCATE ...") with a literal first argument.

    Only literals: a TRUNCATE assembled at runtime cannot be recognised here, and
    guessing would trade this validator's precision for very little reach.
    """
    f = node.func
    if not (
        isinstance(f, ast.Attribute)
        and f.attr == "sql"
        and isinstance(f.value, ast.Attribute)
        and f.value.attr == "db"
    ):
        return False
    if not node.args:
        return False
    first = node.args[0]
    return (
        isinstance(first, ast.Constant)
        and isinstance(first.value, str)
        and first.value.lstrip().upper().startswith("TRUNCATE")
    )


def _enclosing_func(tree: ast.AST, line: int) -> str:
    """Innermost function containing `line`, for the message. '<module>' if none."""
    best, best_start = "<module>", -1
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            if node.lineno <= line <= end and node.lineno > best_start:
                best, best_start = node.name, node.lineno
    return best


def _stmt_span(tree: ast.AST, line: int) -> tuple[int, int]:
    """Smallest statement span containing `line`, for scanning the suppression
    comment. A call split across lines carries its marker on any of them."""
    best, best_size = (line, line), 10**9
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        start = node.lineno
        end = getattr(node, "end_lineno", start) or start
        if start <= line <= end and (end - start) < best_size:
            best, best_size = (start, end), end - start
    return best


def _suppression(span: tuple[int, int], src_lines: list[str]) -> tuple[bool, str | None]:
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
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_db_begin(node):
            kind = KIND_BEGIN
        elif _is_raw_truncate(node):
            kind = KIND_TRUNCATE
        else:
            continue
        suppressed, bad = _suppression(_stmt_span(tree, node.lineno), src_lines)
        findings.append(
            Finding(str(path), node.lineno, _enclosing_func(tree, node.lineno), kind, suppressed, bad)
        )
    return sorted(findings, key=lambda f: f.line)


def is_production_file(path: Path) -> bool:
    """Production Python: not a test module, not inside a tests/ tree, not archived."""
    if path.suffix != ".py":
        return False
    name = path.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return False
    parts = path.parts
    if any(p in _SKIP_PARTS for p in parts):
        return False
    return not any(p.startswith(_SKIP_PREFIXES) for p in parts)


_MESSAGES = {
    KIND_BEGIN: (
        "frappe.db.begin() raises ImplicitCommitError whenever the request has already "
        "written anything (a save, a set_value, a File insert, even frappe.log_error). "
        "Whether that holds depends on the CALLER, so this cannot be proven safe here. "
        "Delete it and keep the SELECT ... FOR UPDATE plus the existing commit()/rollback() "
        "-- do NOT convert to a savepoint, which does not release row locks."
    ),
    KIND_TRUNCATE: (
        "a raw TRUNCATE through frappe.db.sql() is DDL and trips the same implicit-commit "
        "guard when writes are pending. Use frappe.db.sql_ddl(), and commit() first if a "
        "record must survive the truncate."
    ),
}


def main(argv: list[str]) -> int:
    flags = [a for a in argv[1:] if a.startswith("-")]
    args = [a for a in argv[1:] if not a.startswith("-")]
    strict = "--strict" in flags or os.environ.get("DB_BEGIN_STRICT") == "1"
    scan_all = "--all" in flags

    if not args:
        print(
            "usage: db_begin_validator.py FILE [FILE ...]\n" "       db_begin_validator.py --all DIR",
            file=sys.stderr,
        )
        return 2

    if scan_all:
        paths = [p for root in args for p in sorted(Path(root).rglob("*.py"))]
    else:
        paths = [Path(p) for p in args]

    active = 0
    bad_reasons = 0
    suppressed = 0
    for path in paths:
        if not path.is_file() or not is_production_file(path):
            continue
        for f in check_file(path):
            if f.bad_reason is not None:
                bad_reasons += 1
                print(
                    f"{f.file}:{f.line}: db-begin-ok reason {f.bad_reason!r} is not valid; "
                    f"use one of {sorted(VALID_REASONS)}"
                )
                continue
            if f.suppressed:
                suppressed += 1
                continue
            active += 1
            print(
                f"{f.file}:{f.line}: in {f.func}(): {_MESSAGES[f.kind]} "
                f"If this site is genuinely safe, annotate '# db-begin-ok: <reason>'."
            )

    problems = active + bad_reasons
    if problems:
        mode = "STRICT" if strict else "advisory"
        print(
            f"\n{active} implicit-commit finding(s), {bad_reasons} invalid suppression "
            f"reason(s), {suppressed} suppressed [{mode}].",
            file=sys.stderr,
        )
        return 1 if strict else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
