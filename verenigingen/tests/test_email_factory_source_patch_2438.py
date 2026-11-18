"""#2438: a source patch of ``get_email_service`` must not poison a module first imported under it.

Order dependence is proved in a FRESH interpreter, so it does not depend on which modules the shard
happened to import first. In-process the binders are usually loaded already and the bug cannot show.
"""

import json
import os
import re
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

import frappe

import verenigingen
from verenigingen.tests.utils.email_factory_binders import find_email_factory_binders

APP_ROOT = Path(verenigingen.__file__).resolve().parent
FACTORY = "verenigingen.services.communication.email_service"
# Column-0 `from ...email_service import ... get_email_service`: an import-time binder, found by regex
# so the AST discovery under test is cross-checked by a method that shares none of its code.
_TOP_LEVEL_BINDER = re.compile(r"^from (?:\.|verenigingen\.services\.communication\.)email_service import .*get_email_service", re.M)

# Runs in a child interpreter: import the tests package (as `bench run-tests` does first), THEN patch
# the factory at its source and import every binder for the first time under that patch.
_CHILD = textwrap.dedent(
    """
    import importlib, json, sys
    from unittest.mock import MagicMock, patch
    import frappe
    frappe.init(site=sys.argv[1])
    frappe.connect()
    frappe.flags.in_test = sys.argv[5] == "1"  # what `bench run-tests` sets before importing the tests
    import verenigingen
    assert verenigingen.__file__ == sys.argv[2], (verenigingen.__file__, sys.argv[2])
    import verenigingen.tests
    loaded = sorted(n for n in json.loads(sys.argv[4]) if n in sys.modules)  # right after the package import
    with patch(sys.argv[3] + ".get_email_service"):
        for name in json.loads(sys.argv[4]):
            importlib.import_module(name)
    print("LOADED=" + json.dumps(loaded))
    print("LEAKED=" + json.dumps(sorted(
        n for n, m in list(sys.modules.items())
        if m is not None and isinstance(getattr(m, "__dict__", {}).get("get_email_service"), MagicMock)
    )))
    """
)


def _regex_binders():
    found = []
    for path in APP_ROOT.rglob("*.py"):
        rel = path.relative_to(APP_ROOT)
        if "tests" in rel.parts or path.name.startswith("test_"):
            continue
        if _TOP_LEVEL_BINDER.search(path.read_text(encoding="utf-8")):
            found.append(".".join(("verenigingen", *rel.with_suffix("").parts)))
    return sorted(found)


class TestEmailFactorySourcePatch2438(unittest.TestCase):
    def _child_report(self, binders, in_test):
        sites_dir = os.path.dirname(os.path.abspath(frappe.get_site_path()))
        out = subprocess.run(
            [
                sys.executable,
                "-c",
                _CHILD,
                frappe.local.site,
                verenigingen.__file__,
                FACTORY,
                json.dumps(binders),
                "1" if in_test else "0",
            ],
            cwd=sites_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
        report = {}
        for key in ("LOADED", "LEAKED"):
            line = next((x for x in out.stdout.splitlines() if x.startswith(key + "=")), None)
            self.assertIsNotNone(line, out.stderr[-2000:])
            report[key] = json.loads(line[len(key) + 1 :])
        return report

    def test_binders_first_imported_under_a_source_patch_are_not_poisoned(self):
        binders = _regex_binders()
        self.assertGreaterEqual(len(binders), 18)  # control: the sweep has something to import
        report = self._child_report(binders, in_test=True)
        self.assertEqual(report["LOADED"], binders)  # the package import preloaded them
        self.assertEqual(report["LEAKED"], [])

    def test_a_plain_connected_import_does_not_preload(self):
        """Control: production lazily imports verenigingen.tests (monitoring_dashboard); no preload there."""
        binders = _regex_binders()
        report = self._child_report(binders, in_test=False)
        self.assertEqual(report["LOADED"], [])
        # and the poisoning this guards against is real when nothing preloaded: the control can fail
        self.assertEqual(report["LEAKED"], binders)

    def test_discovery_matches_an_independent_regex_scan(self):
        found = find_email_factory_binders()
        self.assertEqual(found, _regex_binders())
        self.assertIn("verenigingen.utils.alert_manager", found)  # absolute import
        self.assertIn("verenigingen.services.communication.compatibility", found)  # relative import

    def test_a_function_local_import_is_not_a_binder(self):
        # termination_approval_service imports the factory inside functions only: late-bound, so safe.
        self.assertNotIn("verenigingen.services.approval.termination_approval_service", find_email_factory_binders())
