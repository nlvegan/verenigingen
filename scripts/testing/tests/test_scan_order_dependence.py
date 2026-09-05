"""Tests for scan_order_dependence.py's baseline writer (#815) and the file-path /
exemption-visibility fixes (#851, #825).

Scope: the `--update-baseline` writer added with the ratchet. The detector's own
REUSE/COMMIT visitors predate it and are exercised by the census itself; what had zero
coverage was the new output path, and its format is what CI's gate parses.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCANNER = os.path.normpath(os.path.join(HERE, "..", "scan_order_dependence.py"))


def _load_scanner_module():
    """Import scan_order_dependence.py directly, bypassing sys.path/package concerns."""
    spec = importlib.util.spec_from_file_location("scan_order_dependence", SCANNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


class FilePathScanTest(unittest.TestCase):
    """#851: a FILE path used to silently report 0 findings via os.walk(). Reproduce
    the exact scenario -- same content, run once against the directory and once
    against the file -- and require identical findings, not a fake all-clear."""

    def _write(self, tmp, name, body):
        path = os.path.join(tmp, name)
        with open(path, "w") as fh:
            fh.write(body)
        return path

    def test_file_path_finds_what_the_directory_finds(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "test_probe.py",
                        "import frappe\n\n\ndef test_a():\n    frappe.db.commit()\n")
            dir_result = subprocess.run(
                [sys.executable, SCANNER, tmp], capture_output=True, text=True,
            )
            file_result = subprocess.run(
                [sys.executable, SCANNER, os.path.join(tmp, "test_probe.py")],
                capture_output=True, text=True,
            )
        self.assertIn("Total findings: 1", dir_result.stdout)
        # The bug: this used to print "Total findings: 0" for the file path, with
        # exit 0 in both cases -- a confident, silent, wrong all-clear.
        self.assertIn("Total findings: 1", file_result.stdout, file_result.stdout)

    def test_nonexistent_path_is_refused_not_silently_empty(self):
        result = subprocess.run(
            [sys.executable, SCANNER, "/no/such/path/at/all"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)


class CommitExemptionVisibilityTest(unittest.TestCase):
    """#825: a rename into a _create_*/_cleanup_*/tearDown-prefixed function used to
    erase a COMMIT finding with no trace anywhere. It must now surface as the
    non-blocking COMMIT_EXEMPT kind instead of vanishing."""

    def _write(self, tmp, name, body):
        path = os.path.join(tmp, name)
        with open(path, "w") as fh:
            fh.write(body)
        return path

    def test_renamed_helper_is_exempt_but_still_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(
                tmp, "test_probe.py",
                "import frappe\n\n\ndef _create_something():\n    frappe.db.commit()\n",
            )
            result = subprocess.run(
                [sys.executable, SCANNER, tmp], capture_output=True, text=True,
            )
        self.assertIn("COMMIT_EXEMPT=1", result.stdout, result.stdout)
        self.assertIn("COMMIT=0", result.stdout, result.stdout)
        self.assertIn("test_probe.py:5", result.stdout, result.stdout)

    def test_exempt_finding_uses_a_marker_the_ci_growth_grep_does_not_match(self):
        # .github/workflows/code-validation.yml sums lines matching '# order-dependence'
        # to gate growth. A COMMIT_EXEMPT entry must NOT match that grep, or every
        # legitimate fixture-builder commit would freeze against the no-growth gate --
        # defeating the exemption's whole purpose (see #825's comment thread).
        with tempfile.TemporaryDirectory() as tmp:
            self._write(
                tmp, "test_probe.py",
                "import frappe\n\n\ndef _create_something():\n    frappe.db.commit()\n",
            )
            baseline = os.path.join(tmp, "baseline.txt")
            run_scanner(tmp, baseline)
            line = data_lines(baseline)[0]
        self.assertTrue(line.startswith("COMMIT_EXEMPT"), line)
        self.assertNotIn("# order-dependence", line, line)


class SelfCheckControlTest(unittest.TestCase):
    """The mandatory control (#851/#825 aftermath): the scanner must never be able to
    silently report 0 findings again. Prove the self-check both passes against the
    real scanner and fails loudly when the scanner is broken."""

    def test_self_check_passes_against_the_real_scanner(self):
        module = _load_scanner_module()
        module.run_self_check()  # must not raise/exit

    def test_self_check_fails_when_a_kind_stops_firing(self):
        module = _load_scanner_module()
        # Simulate a future regression: the control's own snippet stops tripping REUSE
        # (a stand-in for any change that quietly breaks detection). A control that
        # cannot fail is not a control.
        module._CONTROL_SOURCE = (
            "import frappe\n\n\n"
            "class ControlProbeTest:\n"
            "    def test_control_probe(self):\n"
            "        frappe.db.commit()\n\n"
            "    def _create_control_fixture(self):\n"
            "        frappe.db.commit()\n"
        )
        with self.assertRaises(SystemExit):
            module.run_self_check()

    def test_main_refuses_to_scan_when_self_check_fails(self):
        # End-to-end: a scanner whose control no longer fires must exit non-zero and
        # print the self-check failure -- never fall through to "Total findings: 0".
        with open(SCANNER, encoding="utf-8") as fh:
            src = fh.read()
        broken = src.replace(
            '        if _is_get_all(node) and not _query_is_scoped(node):\n'
            '            in_setup = any(f in SETUP_FUNCS for f in self.func_stack)\n'
            '            if in_setup or _has_limit_one(node):\n'
            '                self._add("REUSE", node)\n',
            '        if False:  # deliberately broken for this test\n'
            '            pass\n',
        )
        self.assertNotEqual(broken, src, "expected source snippet not found -- scanner changed shape")
        with tempfile.TemporaryDirectory() as tmp:
            broken_path = os.path.join(tmp, "scan_order_dependence_broken.py")
            with open(broken_path, "w", encoding="utf-8") as fh:
                fh.write(broken)
            result = subprocess.run(
                [sys.executable, broken_path, tmp], capture_output=True, text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SELF-CHECK FAILED", result.stdout + result.stderr)
        self.assertNotIn("Total findings", result.stdout)


if __name__ == "__main__":
    unittest.main()
