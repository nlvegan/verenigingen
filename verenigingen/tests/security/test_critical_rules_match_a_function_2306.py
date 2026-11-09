"""#2306: every shipped `security_level: critical` rule must be able to match a function.

#2295 refuses an endpoint whose lookup errored when one of its operation names is a
critical rule in the shipped fixtures. The names it tries are the bare function name,
`<module>_<name>` and `api_<name>` (`APISecurityFramework._potential_operation_names`).
A critical rule none of those can ever produce protects nothing, and a name two
functions produce refuses both.

Pure static scan: an ast walk of every decorated non-test `def` under `verenigingen/` and
`scripts/` (`scripts/` is live, importable code with its own whitelisted endpoints; the
first measurement of #2306 skipped it and counted three live rules as dead). The three
runtime forms are the ones `_potential_operation_names` builds, so a drift between the
two is caught by `test_the_name_forms_are_the_frameworks`.
"""

import ast
import json
from collections import defaultdict
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.security.api_security_framework import APISecurityFramework

APP_ROOT = Path(frappe.get_app_path("verenigingen"))
REPO_ROOT = APP_ROOT.parent

# Critical names that match two decorated functions: deciding which one is
# the intended target is a product call (#2306), so they are pinned, not silently allowed.
# A NEW collision fails the test; resolving one means removing it here.
KNOWN_COLLISIONS = {
    "process_payment",
    "api_cleanup_orphaned_schedules",
}


def _critical_rule_names():
    names = set()
    for path in (APP_ROOT / "fixtures").glob("critical_operation_rule*.json"):
        for row in json.loads(path.read_text()):
            if row.get("security_level") == "critical":
                names.add(row["operation_name"])
    return names


def _function_sites():
    """{runtime name form: {(file, function name)}} for every decorated non-test def."""
    sites = defaultdict(set)
    for root in (APP_ROOT, REPO_ROOT / "scripts"):
        for path in root.rglob("*.py"):
            if "tests" in path.parts or "node_modules" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text())
            except (SyntaxError, ValueError):
                continue
            module = path.stem
            for node in ast.walk(tree):
                # Only a decorated def can be an endpoint the framework wraps (module-level
                # or a whitelisted doc method); plain helpers and class methods that merely
                # share a name are not candidates.
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.decorator_list:
                    for form in (node.name, f"{module}_{node.name}", f"api_{node.name}"):
                        sites[form].add((str(path), node.name))
    return sites


class TestCriticalRulesMatchAFunction(FrappeTestCase):
    def test_every_critical_rule_matches_a_function(self):
        sites = _function_sites()
        dead = sorted(name for name in _critical_rule_names() if not sites.get(name))
        self.assertEqual(
            dead,
            [],
            "critical rules that no function can ever match (renamed? re-point the rule; "
            "deleted? remove the row and add a patch that deletes it on existing sites)",
        )

    def test_critical_names_matching_two_functions_are_the_known_ones(self):
        sites = _function_sites()
        collisions = {name for name in _critical_rule_names() if len(sites.get(name, ())) > 1}
        self.assertEqual(collisions, KNOWN_COLLISIONS)

    def test_the_scan_sees_live_and_dead_names(self):
        """Control: the scan resolves a rule that is live only through `scripts/`."""
        sites = _function_sites()
        self.assertTrue(sites.get("nuclear_cleanup_all_members"), "scripts/ must be scanned")
        self.assertTrue(sites.get("api_force_cleanup_orphaned_schedules_and_invoices"), "api_ form")
        self.assertFalse(sites.get("admin_tools_nuclear_cleanup_all_members"), "a dead name resolves to nothing")

    def test_the_name_forms_are_the_frameworks(self):
        def probe_fn():
            pass

        probe_fn.__module__ = "verenigingen.api.some_module"
        self.assertEqual(
            APISecurityFramework._potential_operation_names(probe_fn),
            ["probe_fn", "some_module_probe_fn", "api_probe_fn"],
        )
