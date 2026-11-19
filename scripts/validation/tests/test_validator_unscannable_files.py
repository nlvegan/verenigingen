#!/usr/bin/env python3
"""A tree-scan validator must FAIL on a file it cannot examine (#2815).

The shape, as #944 fixed it in scan_order_dependence: `except SyntaxError: return []`
made a file the scanner never examined count as clean, so a ratchet gating CI
understated the tree and new findings in that file went unseen.

Each CI-gating tree scan below is run as a subprocess (the way CI runs it) over a temp
tree. Per validator: a CONTROL (clean tree, exit 0) and the RED case (one unparseable
or undecodable file, non-zero exit that names the file).
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATION = REPO_ROOT / "scripts" / "validation"

CLEAN_SRC = b"VALUE = 1\n"
UNPARSEABLE_SRC = b"def (\n"
UNDECODABLE_SRC = b"\xff\xfe\x00not utf-8\n"


def _run_validator_cli(script, args):
    return subprocess.run(
        [sys.executable, str(VALIDATION / script), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def _write_unscannable_tree(tmp, name, payload):
    root = Path(tmp)
    (root / name).write_bytes(payload)
    return root


class _PathArgScanMixin:
    """Validators whose CLI takes the paths to scan as positional arguments."""

    script = None
    filename = "target_module.py"
    bad_payload = UNPARSEABLE_SRC

    def _cli_args(self, root):
        return [str(root)]

    def test_clean_tree_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unscannable_tree(tmp, self.filename, CLEAN_SRC)
            result = _run_validator_cli(self.script, self._cli_args(root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unscannable_file_fails_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unscannable_tree(tmp, self.filename, self.bad_payload)
            result = _run_validator_cli(self.script, self._cli_args(root))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(self.filename, result.stdout + result.stderr)


class ErrorSwallowUnscannableTest(_PathArgScanMixin, unittest.TestCase):
    script = "error_swallow_validator.py"


class LogErrorArgOrderUnscannableTest(_PathArgScanMixin, unittest.TestCase):
    script = "log_error_arg_order_validator.py"


class FailedWriteUnscannableTest(_PathArgScanMixin, unittest.TestCase):
    script = "failed_write_validator.py"


class DbClockDateWindowUnscannableTest(_PathArgScanMixin, unittest.TestCase):
    # Its scan is line-based, so a SyntaxError only degrades a qualname; an
    # undecodable file is the case that is genuinely never examined.
    script = "db_clock_date_window_validator.py"
    bad_payload = UNDECODABLE_SRC


class TestQualityEnforcerUnscannableTest(_PathArgScanMixin, unittest.TestCase):
    script = "test_quality_enforcer.py"
    filename = "test_target_module.py"

    def _cli_args(self, root):
        return [str(root / self.filename)]


class DuplicateHelperUnscannableTest(_PathArgScanMixin, unittest.TestCase):
    script = "duplicate_helper_validator.py"

    def _cli_args(self, root):
        return ["--root", str(root)]


def _load_validator_module(filename):
    path = VALIDATION / filename
    spec = importlib.util.spec_from_file_location(path.stem + "_2815", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class HarnessRegistryUnscannableTest(unittest.TestCase):
    """The two harness validators build a class registry; a skipped file drops classes
    (and inheritance links) from it, so find_violations() must report the file."""

    def _find(self, filename, payload):
        module = _load_validator_module(filename)
        sink = []
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unscannable_tree(tmp, "test_broken_harness.py", payload)
            module.find_violations(root=root, unscannable=sink)
        return sink

    def test_super_skip_reports_unparseable_file(self):
        sink = self._find("harness_super_skip_validator.py", UNPARSEABLE_SRC)
        self.assertEqual(len(sink), 1, sink)
        self.assertIn("test_broken_harness.py", sink[0])

    def test_super_skip_clean_tree_reports_nothing(self):
        self.assertEqual(self._find("harness_super_skip_validator.py", CLEAN_SRC), [])

    def test_factory_shadow_reports_unparseable_file(self):
        sink = self._find("harness_factory_shadow_validator.py", UNPARSEABLE_SRC)
        self.assertTrue(sink)
        self.assertTrue(all("test_broken_harness.py" in m for m in sink), sink)

    def test_factory_shadow_clean_tree_reports_nothing(self):
        self.assertEqual(self._find("harness_factory_shadow_validator.py", CLEAN_SRC), [])


class HarnessMainFailsClosedTest(unittest.TestCase):
    """main() must turn a non-empty sink into a non-zero exit."""

    def test_main_exits_nonzero_when_find_violations_reports_a_file(self):
        for filename in ("harness_super_skip_validator.py", "harness_factory_shadow_validator.py"):
            module = _load_validator_module(filename)

            def _report_one(root=None, unscannable=None):
                unscannable.append("somewhere/broken.py: SyntaxError: x")
                return []

            module.find_violations = _report_one
            sys.argv = [filename]
            self.assertEqual(module.main(), 1, filename)


if __name__ == "__main__":
    unittest.main()
