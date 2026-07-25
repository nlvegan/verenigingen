#!/usr/bin/env python3
"""One-shot AUDIT detector for the test-isolation cache-guard anti-pattern.

Recall-favoring: surfaces CANDIDATES for human/subagent triage. False positives
are expected and acceptable -- every row is triaged by hand. See the design spec
docs/superpowers/specs/2026-07-25-test-isolation-cache-guard-design.md.

Three rules:
  A (pre-switch guard, highest precision -- the #182 shape): a reader call
    appears in a function BEFORE the first switch-point (frappe.set_user / a
    `with as_user/as_role/set_user(...)` block) in that same function.
  B (cross-function setUp grant->method read): the class's setUp performs a
    grant or switch; a test method reads permission/role state without a
    preceding reset in that method.
  C (intra-function grant->read without reset): a grant precedes a reader in the
    same function with no full cache reset in between.

Usage: python audit_detector.py [path ...]   (defaults to verenigingen/tests)
       python audit_detector.py --json report.json <paths>
"""
from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# --- idiom vocabularies (configurable) --------------------------------------

# Calls that switch user (each also RESETS the request-local perm caches).
SWITCH_NAMES = {"set_user", "as_user", "as_role"}
# Calls/statements that RESET the specific fragile layer. clear_cache() with NO
# args is a full reset; clear_cache(doctype=..)/(user=..) is NOT (does not bust
# the role_permissions memo -- see MEMORY.md / commit 5caed9e8 history).
RESET_NAMES = {"set_user", "as_user", "as_role"}  # full switches reset too
# Calls that GRANT permission/role (may populate a stale-cacheable state).
GRANT_NAMES = {
    "add_permission",
    "update_permission_property",
    "add_roles",
    "as_role",
    "_ensure_board_member_role",
    "grant_matching_role_profiles",
}
# Calls that READ permission/role/cache state (bare or doc-bound or app wrapper).
READER_NAMES = {
    "has_permission",
    "get_roles",
    "get_doc_permissions",
    "has_perm",
    "get_all_perms",
    "check_permission",
    "has_donor_permission",
    "get_donor_permission_query",
    "get_permitted_documents",
}
# Attribute reads of the request-local cache layers themselves.
CACHE_ATTRS = {"role_permissions", "user_perms"}


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _is_full_reset_call(node: ast.Call) -> bool:
    name = _call_name(node)
    if name in RESET_NAMES:
        return True
    # frappe.clear_cache() with NO arguments == full reset; with args it is NOT.
    if name == "clear_cache" and not node.args and not node.keywords:
        return True
    return False


@dataclass
class Event:
    line: int
    kind: str  # switch | reset | grant | reader
    detail: str


@dataclass
class Finding:
    file: str
    line: int
    cls: str
    func: str
    reader: str
    rule: str
    note: str


def _switch_line_of_with(node: ast.With) -> int | None:
    """If a `with` statement enters via a switch idiom, return the with's line."""
    for item in node.items:
        ce = item.context_expr
        if isinstance(ce, ast.Call) and _call_name(ce) in SWITCH_NAMES:
            return node.lineno
    return None


def _iter_own_nodes(fn: ast.FunctionDef):
    """Walk fn's body but DO NOT descend into nested function/class scopes.

    A closure defined inside a test (e.g. an @critical_api-decorated function that
    is the code-under-test) executes at call time -- often inside a `with as_user()`
    block -- so its statements are NOT part of the outer test's linear control flow.
    Descending into it conflated the nested body's line numbers with the outer
    function, producing false 'reader before switch' hits.
    """
    SCOPE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, SCOPE):
            continue  # nested scope -- skip it and its body entirely
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _collect_events(fn: ast.FunctionDef) -> list[Event]:
    events: list[Event] = []
    for node in _iter_own_nodes(fn):
        if isinstance(node, ast.With):
            sl = _switch_line_of_with(node)
            if sl is not None:
                events.append(Event(sl, "switch", "with as_user/as_role"))
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            if name is None:
                continue
            # a plain frappe.set_user(...) statement (not the with-form)
            if name in SWITCH_NAMES:
                events.append(Event(node.lineno, "switch", name))
            if _is_full_reset_call(node):
                events.append(Event(node.lineno, "reset", name or "reset"))
            if name in GRANT_NAMES:
                events.append(Event(node.lineno, "grant", name))
            if name in READER_NAMES:
                events.append(Event(node.lineno, "reader", name))
        elif isinstance(node, ast.Assign):
            # explicit `frappe.local.role_permissions = {}` style reset
            for tgt in node.targets:
                if isinstance(tgt, ast.Attribute) and tgt.attr in CACHE_ATTRS:
                    events.append(Event(node.lineno, "reset", tgt.attr))
        elif isinstance(node, ast.Attribute) and node.attr in CACHE_ATTRS:
            # a READ of frappe.local.role_permissions / user_perms
            events.append(Event(node.lineno, "reader", node.attr))
    events.sort(key=lambda e: (e.line, e.kind))
    return events


def _iter_methods(cls: ast.ClassDef):
    for n in cls.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield n


def analyze_file(path: Path) -> list[Finding]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return []
    findings: list[Finding] = []
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        methods = {m.name: m for m in _iter_methods(cls)}
        setup = methods.get("setUp")
        setup_events = _collect_events(setup) if setup else []
        setup_has_grant_or_switch = any(e.kind in ("grant", "switch") for e in setup_events)
        setup_ends_reset = setup_events and setup_events[-1].kind in ("reset", "switch")

        for mname, m in methods.items():
            if mname != "setUp" and not mname.startswith("test"):
                continue
            events = _collect_events(m)
            first_switch = next((e.line for e in events if e.kind == "switch"), None)
            seen_reset = False
            seen_grant = False
            for e in events:
                if e.kind in ("reset", "switch"):
                    seen_reset = True
                if e.kind == "grant":
                    seen_grant = True
                if e.kind != "reader":
                    continue
                # Rule A: reader before the first switch in this function.
                if first_switch is not None and e.line < first_switch:
                    findings.append(Finding(str(path), e.line, cls.name, mname,
                                            e.detail, "A",
                                            f"reader precedes switch at L{first_switch}"))
                    continue
                # Rule C: grant earlier in this function, no reset since.
                if seen_grant and not seen_reset:
                    findings.append(Finding(str(path), e.line, cls.name, mname,
                                            e.detail, "C",
                                            "reader after in-function grant, no reset"))
                    continue
                # Rule B: setUp granted/switched; method reads with no prior reset
                # in the method (and setUp did not leave a clean reset at its end).
                if (mname.startswith("test") and setup_has_grant_or_switch
                        and not seen_reset and not setup_ends_reset):
                    findings.append(Finding(str(path), e.line, cls.name, mname,
                                            e.detail, "B",
                                            "reader in test; setUp grant/switch, no reset"))
    return findings


def main(argv: list[str]) -> int:
    args = argv[1:]
    json_out = None
    if "--json" in args:
        i = args.index("--json")
        json_out = args[i + 1]
        del args[i:i + 2]
    roots = [Path(a) for a in args] or [Path("verenigingen/tests")]
    files: list[Path] = []
    for r in roots:
        if r.is_dir():
            files.extend(sorted(r.rglob("test_*.py")))
        elif r.name.startswith("test_") and r.suffix == ".py":
            files.append(r)
        elif r.suffix == ".py":
            files.append(r)
    all_findings: list[Finding] = []
    for f in files:
        all_findings.extend(analyze_file(f))

    by_rule: dict[str, int] = {}
    by_file: dict[str, int] = {}
    for fd in all_findings:
        by_rule[fd.rule] = by_rule.get(fd.rule, 0) + 1
        by_file[fd.file] = by_file.get(fd.file, 0) + 1

    for fd in all_findings:
        print(f"[{fd.rule}] {fd.file}:{fd.line}  {fd.cls}.{fd.func}  "
              f"reader={fd.reader}  -- {fd.note}")
    print(f"\n{len(all_findings)} candidates across {len(by_file)} files "
          f"(scanned {len(files)} files). By rule: "
          + ", ".join(f"{k}={v}" for k, v in sorted(by_rule.items())))

    if json_out:
        Path(json_out).write_text(json.dumps(
            [fd.__dict__ for fd in all_findings], indent=2))
        print(f"wrote {json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
