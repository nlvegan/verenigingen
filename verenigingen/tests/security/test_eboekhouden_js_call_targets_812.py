"""#812: every in-app frappe.call target in the e_boekhouden JS must resolve AND be whitelisted.

Whitelisting is only consulted at dispatch, so a dead or un-whitelisted target
keeps working for every internal caller and fails only in the browser.
"""

import re
from importlib import import_module
from pathlib import Path

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

EBOEKHOUDEN_DIR = Path(__file__).resolve().parents[2] / "e_boekhouden"
CALL_TARGET_RE = re.compile(
    r"""(?:method\s*:\s*|frappe\.xcall\(\s*)['"](verenigingen\.[A-Za-z0-9_.]+)['"]"""
)


def _eboekhouden_js_call_targets():
    found = {}
    for js_file in sorted(EBOEKHOUDEN_DIR.rglob("*.js")):
        for target in CALL_TARGET_RE.findall(js_file.read_text(encoding="utf-8")):
            found.setdefault(target, set()).add(js_file.name)
    return found


class TestEBoekhoudenJsCallTargets812(VereningingenTestCase):
    def test_every_js_call_target_resolves_to_a_whitelisted_function(self):
        targets = _eboekhouden_js_call_targets()
        # control: the scan must see the migration form's calls, else it proves nothing
        self.assertIn("e_boekhouden_migration.js", set().union(*targets.values()))
        self.assertGreater(len(targets), 10)

        broken = {}
        for target in sorted(targets):
            module_path, _, func_name = target.rpartition(".")
            try:
                func = getattr(import_module(module_path), func_name)
            except (ImportError, AttributeError) as exc:
                broken[target] = f"does not resolve: {exc}"
                continue
            if func not in frappe.whitelisted:
                broken[target] = "resolves but is not whitelisted"
        self.assertEqual(broken, {})
