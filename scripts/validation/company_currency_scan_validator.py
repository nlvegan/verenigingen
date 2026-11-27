#!/usr/bin/env python3
"""Standalone scan: no code may resolve a ``Company`` by scanning for a currency (#394).

Extracted from ``verenigingen/tests/test_no_company_scan_by_currency.py`` (#1193, the #1189
recipe). That bench test is now a thin wrapper importing THIS module, so the pre-commit hook
and the named CI job run the SAME scan rather than a copy. Stdlib-only: no bench, no site, no
``import verenigingen`` (which pulls frappe in through ``verenigingen/tests/__init__.py``).

The bug class and the shapes this does NOT see are documented in the bench test's docstring;
nothing about WHAT is checked changed here.

    python scripts/validation/company_currency_scan_validator.py [files ...]
"""

import ast
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(REPO_ROOT, "verenigingen")

# Paths are relative to the `verenigingen` package root. Each entry needs a reason, and the
# reason has to be about why the scan is CORRECT there -- not about it being inconvenient
# to change.
ALLOWED = {
    # The defect itself, isolated in one place so the pins above can name what they pin.
    # Called by nothing except those pins.
    "tests/support/eur_company_decoy.py": "the defect under test, quarantined for pins",
}


# The keyword arguments that carry a filter. `fields=` and `pluck=` are deliberately NOT
# here: `get_all("Company", fields=["name", "default_currency"])` READS the currency, it
# does not constrain on it, and treating any list containing the string as a filter turns
# that into a false positive.
_FILTER_KEYWORDS = frozenset({"filters", "or_filters"})


def _is_currency_condition(node) -> bool:
    """A single list/tuple filter condition constraining ``default_currency``.

    Covers ``["default_currency", "=", "EUR"]`` and the four-element
    ``["Company", "default_currency", "=", "EUR"]``, in list or tuple form. Checks the
    node's own elements only -- never a recursive walk for the bare string, which would
    also match ``get_value("Company", name, "default_currency")`` (a read, not a filter):
    measured over the app, a recursive walk adds **58** such false positives while this
    adds **zero**.
    """
    return isinstance(node, (ast.List, ast.Tuple)) and any(
        isinstance(element, ast.Constant) and element.value == "default_currency" for element in node.elts
    )


def _mentions_currency(node) -> bool:
    """Does this filter argument constrain ``default_currency``, in any of its shapes?

    ``{"default_currency": "EUR"}``, ``[["default_currency", "=", "EUR"]]`` and
    ``[{"default_currency": "EUR"}]`` are all the same query to Frappe, and the list form
    is the one a future author reaches for first. The original guard understood only the
    dict, so it would have gone quietly green on either list shape.
    """
    if isinstance(node, ast.Dict):
        return any(isinstance(key, ast.Constant) and key.value == "default_currency" for key in node.keys)
    if isinstance(node, (ast.List, ast.Tuple)):
        return _is_currency_condition(node) or any(_mentions_currency(el) for el in node.elts)
    return False


def _first_arg_is_company(call: ast.Call) -> bool:
    return bool(call.args) and isinstance(call.args[0], ast.Constant) and call.args[0].value == "Company"


def _currency_scans(tree: ast.AST):
    """Yield line numbers of calls that resolve a Company from a currency filter.

    AST rather than a text search on purpose: several of the fixes in this change quote the
    defective expression verbatim in a docstring or comment, to say what was wrong and what
    it resolved to. A regex over source would flag that prose and push the next author into
    deleting the explanation to appease the guard.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _first_arg_is_company(node):
            continue
        # Only the filter POSITIONS, not every argument. In `get_value`/`get_all`/`exists`
        # the second positional argument is the name-or-filters slot and the third is the
        # fieldname, so widening past `args[1]` only buys false positives once lists are
        # in scope. Measured: this loses none of the sites the dict-only guard found.
        candidates = list(node.args[1:2]) + [kw.value for kw in node.keywords if kw.arg in _FILTER_KEYWORDS]
        if any(_mentions_currency(arg) for arg in candidates):
            yield node.lineno


def walk_app(root=APP_ROOT):
    """Yield ``(path relative to root, absolute path)`` for every .py file under root."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {"node_modules", "__pycache__"}]
        for filename in filenames:
            if filename.endswith(".py"):
                path = os.path.join(dirpath, filename)
                yield os.path.relpath(path, root), path


def scan_company_currency_scans(paths=None, root=APP_ROOT):
    """Return ``{relative path: [lines]}``; ``paths`` limits it to those files."""
    wanted = None if paths is None else {os.path.abspath(p) for p in paths}
    found = {}
    for rel, path in walk_app(root):
        if wanted is not None and os.path.abspath(path) not in wanted:
            continue
        with open(path, encoding="utf-8") as handle:
            try:
                tree = ast.parse(handle.read(), filename=path)
            except SyntaxError:
                continue  # not this guard's job to police parse errors
        lines = sorted(set(_currency_scans(tree)))
        if lines and rel not in ALLOWED:
            found[rel] = lines
    return found


def main(argv):
    found = scan_company_currency_scans(argv[1:] or None)
    if found:
        print("\n\U0001f6d1 Company resolved by scanning for a currency (#394)\n")
        for rel, lines in sorted(found.items()):
            print(f"  {rel}: {lines}")
        print(
            "\n  `db.get_value` orders by `creation DESC`, so the winner is whatever EUR company a"
            "\n  co-tenant suite created last. Own the fixture by name instead:"
            "\n  verenigingen.tests.support.sepa_test_company.get_eur_test_company()."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
