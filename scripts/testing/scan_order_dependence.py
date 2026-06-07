"""Static scanner for test order-dependence anti-patterns.

The dynamic detector (order_dependence_detector.py) proves order-dependence by
running files, but it can only flag tests that *currently* fail in some shard
layout. This scanner is the cheap, exhaustive complement: it AST-walks every
test file and flags the source patterns that CAUSE order-dependence, whether or
not the test happens to fail today. A different shard split tomorrow turns a
latent offender into a failure -- this finds them first.

Patterns flagged (each is a way a test's result can depend on its neighbours):

  REUSE   frappe.get_all(DT, limit=1) / get_all(DT)[0] in setUp/setUpClass.
          The test reuses *whatever record already exists*, so its behaviour
          depends on what preceding files in the shard left in the DB. This is
          the exact bug in test_team_assignment_history.

  COUNT   An assertion over len(frappe.get_all(DT)) or frappe.db.count(DT) with
          no test-scoped filter. Neighbours that add records of DT break it.

  COMMIT  A bare frappe.db.commit() in test code (outside a _cleanup_/_create_
          helper). Commits escape the per-test rollback, leaking state to later
          files in the same shard process.

Usage (from the app root or anywhere):
    python scripts/testing/scan_order_dependence.py [tests_root] [--json out.json]

Exit code is always 0; read stdout / the JSON for findings.
"""

import argparse
import ast
import json
import os

SETUP_FUNCS = {"setUp", "setUpClass", "setUpModule"}
SCOPING_KW = {"filters", "name", "or_filters"}  # presence => query is (likely) scoped


def _attr_chain(node):
    """Return dotted attribute chain for a Call's func, e.g. 'frappe.get_all'."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _is_get_all(call):
    chain = _attr_chain(call.func)
    return chain.endswith("get_all") or chain.endswith("get_list")


def _query_is_scoped(call):
    """True if a get_all/get_list call appears scoped to specific records."""
    for kw in call.keywords:
        if kw.arg in SCOPING_KW:
            return True
    # positional filters: get_all("DT", {...}) or get_all("DT", filters=...)
    if len(call.args) >= 2 and isinstance(call.args[1], (ast.Dict, ast.List)):
        return True
    return False


def _has_limit_one(call):
    for kw in call.keywords:
        if kw.arg in ("limit", "limit_page_length") and isinstance(kw.value, ast.Constant):
            if call.keywords and str(kw.value.value) in ("1",):
                return True
    return False


class Finding:
    __slots__ = ("kind", "file", "line", "snippet")

    def __init__(self, kind, file, line, snippet):
        self.kind, self.file, self.line, self.snippet = kind, file, line, snippet

    def as_dict(self):
        return {"kind": self.kind, "file": self.file, "line": self.line, "snippet": self.snippet}


class Visitor(ast.NodeVisitor):
    def __init__(self, relpath, source_lines):
        self.rel = relpath
        self.lines = source_lines
        self.func_stack = []
        self.findings = []

    def _snip(self, node):
        return self.lines[node.lineno - 1].strip() if 0 < node.lineno <= len(self.lines) else ""

    def _add(self, kind, node):
        self.findings.append(Finding(kind, self.rel, node.lineno, self._snip(node)))

    def visit_FunctionDef(self, node):
        self.func_stack.append(node.name)
        self.generic_visit(node)
        self.func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _in_helper(self):
        # _cleanup_* / _create_* helpers are exempt (see test-quality-enforcer convention)
        return any(f.startswith(("_cleanup", "_create", "tearDown")) for f in self.func_stack)

    def visit_Call(self, node):
        chain = _attr_chain(node.func)

        # COMMIT: bare frappe.db.commit() in test code (not in cleanup/create helpers)
        if chain.endswith("db.commit") and not self._in_helper():
            self._add("COMMIT", node)

        # REUSE: unscoped get_all/get_list in a setUp picking an arbitrary record
        if _is_get_all(node) and not _query_is_scoped(node):
            in_setup = any(f in SETUP_FUNCS for f in self.func_stack)
            if in_setup or _has_limit_one(node):
                self._add("REUSE", node)

        self.generic_visit(node)

    def visit_Compare(self, node):
        # COUNT: assert-style comparison whose operand is len(get_all(...)) / db.count(...)
        for operand in [node.left, *node.comparators]:
            if self._is_global_count(operand):
                self._add("COUNT", node)
                break
        self.generic_visit(node)

    def _is_global_count(self, node):
        # len(frappe.get_all("DT")) with no filters
        if isinstance(node, ast.Call) and _attr_chain(node.func) == "len":
            if node.args and isinstance(node.args[0], ast.Call) and _is_get_all(node.args[0]):
                return not _query_is_scoped(node.args[0])
        # frappe.db.count("DT") with no filter arg
        if isinstance(node, ast.Call) and _attr_chain(node.func).endswith("db.count"):
            scoped = any(kw.arg == "filters" for kw in node.keywords) or len(node.args) >= 2
            return not scoped
        return False


def scan_file(path, root):
    rel = os.path.relpath(path, root)
    try:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, filename=path)
    except (OSError, SyntaxError):
        return []
    v = Visitor(rel, src.splitlines())
    v.visit(tree)
    return v.findings


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    here = os.path.dirname(os.path.abspath(__file__))
    default_root = os.path.normpath(os.path.join(here, "..", "..", "verenigingen", "tests"))
    ap.add_argument("root", nargs="?", default=default_root, help="tests directory to scan")
    ap.add_argument("--json", help="write findings JSON to this path")
    args = ap.parse_args()

    findings = []
    for dirpath, dirs, files in os.walk(args.root):
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
        for fn in files:
            if fn.startswith("test_") and fn.endswith(".py"):
                findings.extend(scan_file(os.path.join(dirpath, fn), args.root))

    by_kind = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)

    order = ["REUSE", "COUNT", "COMMIT"]
    print(f"Scanned {args.root}")
    print(f"Total findings: {len(findings)}  "
          + "  ".join(f"{k}={len(by_kind.get(k, []))}" for k in order))
    files_with = {f.file for f in findings}
    print(f"Files implicated: {len(files_with)}\n")
    for kind in order:
        items = sorted(by_kind.get(kind, []), key=lambda f: (f.file, f.line))
        if not items:
            continue
        print(f"=== {kind} ({len(items)}) ===")
        for f in items:
            print(f"  {f.file}:{f.line}: {f.snippet}")
        print()

    if args.json:
        with open(args.json, "w") as fh:
            json.dump([f.as_dict() for f in findings], fh, indent=2)
        print(f"JSON written to {args.json}")


if __name__ == "__main__":
    main()
