#!/usr/bin/env python3
"""Standalone scan: no production SQL may hand-write ``modified`` from the DB clock (#453).

Extracted from ``verenigingen/tests/test_no_db_clock_modified_writes.py`` (#1193, the #1189
recipe). That bench test is now a thin wrapper importing THIS module, so the pre-commit hook
and the named CI job run the SAME scan rather than a copy. Stdlib-only: no bench, no site, no
``import verenigingen`` (which pulls frappe in through ``verenigingen/tests/__init__.py``).

The bug class and its limits (assignment form only, string literals only, via the AST) are
documented in the bench test's docstring; nothing about WHAT is checked changed here.

    python scripts/validation/db_clock_modified_write_validator.py [files ...]
"""

import argparse
import ast
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Paths are relative to the REPO root. Each entry needs a reason, and the reason has to
# say why a DB-clock stamp is right there -- or, for a test fixture, why it has to be
# written that way rather than with a Python-side now().
ALLOWED: dict[str, str] = {}

# Test code is excluded: hand-rolled fixture SQL is deliberate there, and no sensible
# ALLOWED reason exists for it. Excluded BOTH ways, because this app splits the
# difference: most tests live under `verenigingen/tests/`, but Frappe's own convention
# puts them next to the code (`verenigingen/verenigingen/doctype/volunteer/
# test_volunteer.py`, `verenigingen/services/billing/test_sales_invoice_hooks.py` --
# both real, both currently using the INSERT form this guard does not match anyway).
# A directory-only exclusion would redden on the first doctype-local fixture that uses
# the assignment form, with no honest ALLOWED entry available.
_EXCLUDED_DIRS = frozenset({"tests", "node_modules", "__pycache__", "env", "sites", "logs"})


def _is_test_module_name(filename: str) -> bool:
    return filename.startswith("test_") or filename.endswith("_test.py")

_DB_CLOCK = re.compile(
    r"\bmodified\s*=\s*(?:NOW|CURRENT_TIMESTAMP|LOCALTIME|LOCALTIMESTAMP|SYSDATE|UTC_TIMESTAMP)\s*\(",
    re.IGNORECASE,
)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Ids of the string Constants that are docstrings, so prose is not scanned."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _db_clock_writes(tree: ast.AST):
    """Yield line numbers of string literals assigning `modified` from the DB clock."""
    skip = _docstring_nodes(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip:
            continue
        if _DB_CLOCK.search(node.value):
            yield node.lineno


def walk_production_modules(root=REPO_ROOT):
    """Yield ``(path relative to root, absolute path)`` for every production module."""
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip dot-directories outright: .git, and .claude/worktrees, which holds
        # whole copies of this repo that would otherwise be scanned as if they were
        # the app.
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _EXCLUDED_DIRS]
        for filename in filenames:
            if not filename.endswith(".py") or _is_test_module_name(filename):
                continue
            path = os.path.join(dirpath, filename)
            yield os.path.relpath(path, root), path


def scan_db_clock_modified_writes(paths=None, root=REPO_ROOT):
    """Return sorted ``relative:line`` offenders; ``paths`` limits it to those files."""
    wanted = None if paths is None else {os.path.abspath(p) for p in paths}
    offenders = []
    for relative, path in walk_production_modules(root):
        if relative in ALLOWED or (wanted is not None and os.path.abspath(path) not in wanted):
            continue
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:  # a broken file is another check's problem
            continue
        offenders.extend(f"{relative}:{line}" for line in _db_clock_writes(tree))
    return sorted(offenders)  # os.walk order is not stable across machines


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("paths", nargs="*", help="files to check (default: whole tree)")
    ap.add_argument("--root", default=REPO_ROOT, help="tree to scan (default: this repo)")
    args = ap.parse_args(argv[1:])
    findings = scan_db_clock_modified_writes(args.paths or None, root=args.root)
    if findings:
        print("\n\U0001f6d1 Hand-written `modified` from the database clock (#453)\n")
        for f in findings:
            print(f"  {f}")
        print(
            "\n  Use frappe.db.set_value (or pass a Python-side frappe.utils.now()) instead:"
            "\n  NOW() is the DB server's clock at second precision."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
