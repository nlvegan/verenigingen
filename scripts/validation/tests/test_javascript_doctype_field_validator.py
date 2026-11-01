#!/usr/bin/env python3
"""Control tests for #1899: javascript_doctype_field_validator must actually load DocTypes.

It derived its bench as the bench's `apps/` dir (one `.parent` too shallow), so the loader
scanned `apps/apps`, loaded ZERO DocTypes, and every reference passed. A validator that cannot
fail is the thing under test, so these plant a bad reference and require it to be flagged.

Runs the script as the hook does (a subprocess), against a directory passed as argv[1].
    python -m unittest scripts.validation.tests.test_javascript_doctype_field_validator
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "production" / "javascript_doctype_field_validator.py"
# A line of padding first: a form.on() on line 1 is not seen by the validator's look-back.
_PROBE = """// probe
frappe.ui.form.on('Member', {
    refresh(frm) {
        frm.set_value('zzz_not_a_member_field_1899', 1);
        frm.set_value('first_name', 'x');
    }
});
"""


def _run(directory: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), directory], capture_output=True, text=True, timeout=300
    )


class TestJavascriptDoctypeFieldValidator(unittest.TestCase):
    def test_loads_doctypes_from_its_own_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = _run(tmp).stdout
        loaded = int(out.split("Loaded ")[1].split(" DocTypes")[0])
        self.assertGreater(loaded, 0, "validator loaded no DocTypes, so it can flag nothing")

    def test_planted_bad_field_is_flagged_and_good_field_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "probe.js").write_text(_PROBE)
            result = _run(tmp)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("zzz_not_a_member_field_1899", result.stdout)
        self.assertNotIn("'first_name' not found", result.stdout)


if __name__ == "__main__":
    unittest.main()
