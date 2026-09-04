"""Tests for scan_order_dependence.py's baseline writer (#815).

Scope: the `--update-baseline` writer added with the ratchet. The detector's own
REUSE/COMMIT visitors predate it and are exercised by the census itself; what had zero
coverage was the new output path, and its format is what CI's gate parses.
"""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCANNER = os.path.normpath(os.path.join(HERE, "..", "scan_order_dependence.py"))


def run_scanner(root, baseline):
    return subprocess.run(
        [sys.executable, SCANNER, root, "--update-baseline", baseline],
        capture_output=True, text=True,
    )


def data_lines(path):
    with open(path) as fh:
        return [ln for ln in fh.read().splitlines() if ln and not ln.startswith("#")]


class BaselineWriterTest(unittest.TestCase):
    def _write(self, tmp, name, body):
        path = os.path.join(tmp, name)
        with open(path, "w") as fh:
            fh.write(body)
        return path

    def test_counts_are_aggregated_per_file(self):
        # Two offending sites in one file must produce ONE key with ::2, not two keys.
        # The gate sums the ::N field, so per-site lines would double-count on every read.
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "test_two.py", "import frappe\n\n\ndef test_a():\n"
                                            "    frappe.db.commit()\n    frappe.db.commit()\n")
            baseline = os.path.join(tmp, "baseline.txt")
            run_scanner(tmp, baseline)
            lines = data_lines(baseline)
            self.assertEqual(len(lines), 1, lines)
            self.assertTrue(lines[0].startswith("COMMIT test_two.py::2"), lines[0])

    def test_line_format_is_what_the_gate_parses(self):
        # baseline_shrink_gate.py splits on '::' and the CI step greps the marker, so both
        # must be present on every data line or the gate silently totals zero.
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "test_one.py", "import frappe\n\n\ndef test_a():\n    frappe.db.commit()\n")
            baseline = os.path.join(tmp, "baseline.txt")
            run_scanner(tmp, baseline)
            line = data_lines(baseline)[0]
            self.assertIn("::", line)
            self.assertIn("# order-dependence", line)
            self.assertEqual(line.split("::")[1].split()[0], "1")

    def test_empty_census_still_writes_a_parseable_header_only_file(self):
        # A clean tree must not produce an absent or dataless-but-malformed baseline: the
        # gate refuses an unparseable file, which would read as a failure of the tree.
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "test_clean.py", "def test_a():\n    assert True\n")
            baseline = os.path.join(tmp, "baseline.txt")
            run_scanner(tmp, baseline)
            self.assertTrue(os.path.exists(baseline))
            self.assertEqual(data_lines(baseline), [])
            with open(baseline) as fh:
                self.assertTrue(fh.readline().startswith("#"))

    def test_non_test_files_are_not_scanned(self):
        # The scanner only walks test_*.py; a commit in production code is not an
        # order-dependence finding and must not enter the census.
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "service.py", "import frappe\n\n\ndef go():\n    frappe.db.commit()\n")
            baseline = os.path.join(tmp, "baseline.txt")
            run_scanner(tmp, baseline)
            self.assertEqual(data_lines(baseline), [])

    def test_exit_code_stays_zero(self):
        # Documented contract: this tool reports, it does not gate. CI's gating lives in
        # baseline_shrink_gate.py, and a nonzero exit here would fail the regenerate step
        # before the gate ever ran.
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "test_one.py", "import frappe\n\n\ndef test_a():\n    frappe.db.commit()\n")
            result = run_scanner(tmp, os.path.join(tmp, "baseline.txt"))
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
