#!/usr/bin/env python3
"""Control tests for #1899: javascript_doctype_field_validator must actually load DocTypes.

It derived its bench as the bench's `apps/` dir (one `.parent` too shallow), so the loader
scanned `apps/apps`, loaded ZERO DocTypes, and every reference passed. A validator that cannot
fail is the thing under test, so these plant a bad reference and require it to be flagged.

Runs the script as the hook does (a subprocess), against a directory passed as argv[1].
    python -m unittest scripts.validation.tests.test_javascript_doctype_field_validator
"""
import json
import re
import shutil
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
_COPY_PROBE = """// probe
frappe.ui.form.on('Zz Probe 1899', {
    refresh(frm) {
        frm.set_value('not_in_this_copy_1899', 1);
        frm.set_value('only_in_this_copy', 1);
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
        match = re.search(r"Loaded (\d+) DocTypes", out)
        self.assertIsNotNone(match, f"no 'Loaded N DocTypes' line in output: {out[:500]}")
        loaded = int(match.group(1))
        self.assertGreater(loaded, 0, "validator loaded no DocTypes, so it can flag nothing")

    def test_planted_bad_field_is_flagged_and_good_field_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "probe.js").write_text(_PROBE)
            result = _run(tmp)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("zzz_not_a_member_field_1899", result.stdout)
        self.assertNotIn("'first_name' not found", result.stdout)

    def test_reads_doctypes_from_the_checkout_it_lives_in(self):
        """A copy of the validator in a throwaway bench sees a DocType that exists only there.

        Guards against pointing the loader at a fixed path (e.g. this bench's installed app):
        that would keep the tests above green while ignoring the checkout under validation.
        """
        with tempfile.TemporaryDirectory() as tmp:
            bench = Path(tmp) / "bench"
            app = bench / "apps" / "verenigingen"
            (bench / "sites").mkdir(parents=True)
            validation = app / "scripts" / "validation"
            (validation / "production").mkdir(parents=True)
            src = _SCRIPT.parents[1]
            for name in ("doctype_loader.py", "bench_resolution.py"):
                shutil.copy(src / name, validation / name)
            shutil.copy(_SCRIPT, validation / "production" / _SCRIPT.name)
            (app / "pyproject.toml").write_text('[project]\nname = "verenigingen"\n')
            dt_dir = app / "verenigingen" / "verenigingen" / "doctype" / "zz_probe_1899"
            dt_dir.mkdir(parents=True)
            (dt_dir / "zz_probe_1899.json").write_text(json.dumps({
                "name": "Zz Probe 1899", "module": "Verenigingen",
                "fields": [{"fieldname": "only_in_this_copy", "fieldtype": "Data"}],
            }))
            js = Path(tmp) / "js"
            js.mkdir()
            (js / "probe.js").write_text(_COPY_PROBE)
            result = subprocess.run(
                [sys.executable, str(validation / "production" / _SCRIPT.name), str(js)],
                capture_output=True, text=True, timeout=300,
            )
        self.assertIn("not_in_this_copy_1899", result.stdout, result.stdout)
        self.assertNotIn("'only_in_this_copy' not found", result.stdout)


if __name__ == "__main__":
    unittest.main()
