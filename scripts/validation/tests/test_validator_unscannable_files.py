#!/usr/bin/env python3
"""A tree-scan validator must FAIL on a file it cannot examine (#2815).

The shape, as #944 fixed it in scan_order_dependence: `except SyntaxError: return []`
made a file the scanner never examined count as clean, so a ratchet gating CI
understated the tree and new findings in that file went unseen.

Each CI-gating tree scan below is run as a subprocess (the way CI runs it) over a temp
tree. Per validator: a CONTROL (clean tree, exit 0) and the RED case (one unparseable
or undecodable file, non-zero exit that names the file).
"""
import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
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


class FactoryShadowOwnHandlersTest(unittest.TestCase):
    """find_violations() also fills the sink through harness_super_skip._collect_classes,
    so the find_violations-level test cannot tell whether factory_shadow's OWN two
    handlers report. Call each directly."""

    def _sink_of(self, func_name):
        module = _load_validator_module("harness_factory_shadow_validator.py")
        sink = []
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unscannable_tree(tmp, "test_broken_harness.py", UNPARSEABLE_SRC)
            getattr(module, func_name)(root, sink)
        return sink

    def test_root_shadowed_attrs_reports_unparseable_file(self):
        sink = self._sink_of("_root_shadowed_attrs")
        self.assertEqual(len(sink), 1, sink)
        self.assertIn("test_broken_harness.py", sink[0])

    def test_collect_reports_unparseable_file(self):
        sink = self._sink_of("_collect")
        self.assertEqual(len(sink), 1, sink)
        self.assertIn("test_broken_harness.py", sink[0])


class HarnessMainFailsClosedTest(unittest.TestCase):
    """main() must turn a non-empty sink into a non-zero exit."""

    def test_main_exits_nonzero_when_find_violations_reports_a_file(self):
        for filename in ("harness_super_skip_validator.py", "harness_factory_shadow_validator.py"):
            module = _load_validator_module(filename)

            def _report_one(root=None, unscannable=None):
                unscannable.append("somewhere/broken.py: SyntaxError: x")
                return []

            with mock.patch.object(module, "find_violations", _report_one), mock.patch.object(
                sys, "argv", [filename]
            ):
                self.assertEqual(module.main(), 1, filename)


SENTINEL_BASELINE = b"# sentinel baseline: must survive a refused --update-baseline\n"


class _UpdateBaselineRefusalMixin:
    """--update-baseline over a tree holding an unscannable file must refuse (non-zero,
    names the file) and leave the baseline BYTE-IDENTICAL. The scan roots are module
    globals, so they are pointed at a temp tree in-process; the real baseline is never
    opened because --baseline names a temp file."""

    script = None
    filename = "target_module.py"
    bad_payload = UNPARSEABLE_SRC

    def _run_update(self, module, root, baseline):
        patches = [
            mock.patch.object(module, "REPO_ROOT", root),
            mock.patch.object(module, "SCAN_ROOTS", ("pkg",)),
        ]
        argv = [self.script, "--update-baseline", "--baseline", str(baseline)]
        with patches[0], patches[1], mock.patch.object(sys, "argv", argv):
            err, out = io.StringIO(), io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                rc = module.main(argv)
        return rc, out.getvalue() + err.getvalue()

    def test_update_baseline_refuses_and_leaves_baseline_untouched(self):
        module = _load_validator_module(self.script)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "pkg").mkdir()
            (root / "pkg" / self.filename).write_bytes(self.bad_payload)
            baseline = root / "baseline.txt"
            baseline.write_bytes(SENTINEL_BASELINE)
            rc, output = self._run_update(module, root, baseline)
            self.assertEqual(baseline.read_bytes(), SENTINEL_BASELINE)
        self.assertNotEqual(rc, 0, output)
        self.assertIn(self.filename, output)


class ErrorSwallowUpdateBaselineRefusalTest(_UpdateBaselineRefusalMixin, unittest.TestCase):
    script = "error_swallow_validator.py"


class LogErrorArgOrderUpdateBaselineRefusalTest(_UpdateBaselineRefusalMixin, unittest.TestCase):
    script = "log_error_arg_order_validator.py"


class FailedWriteUpdateBaselineRefusalTest(_UpdateBaselineRefusalMixin, unittest.TestCase):
    script = "failed_write_validator.py"


class DbClockUpdateBaselineRefusalTest(_UpdateBaselineRefusalMixin, unittest.TestCase):
    script = "db_clock_date_window_validator.py"
    bad_payload = UNDECODABLE_SRC


class TestQualityEnforcerUpdateBaselineRefusalTest(unittest.TestCase):
    """main() reads sys.argv and exits via sys.exit; REPO_ROOT is the full-scan root."""

    def test_update_baseline_refuses_and_leaves_baseline_untouched(self):
        module = _load_validator_module("test_quality_enforcer.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "test_target_module.py").write_bytes(UNPARSEABLE_SRC)
            baseline = root / "baseline.txt"
            baseline.write_bytes(SENTINEL_BASELINE)
            argv = ["test_quality_enforcer.py", "--update-baseline", "--baseline", str(baseline)]
            with mock.patch.object(module, "REPO_ROOT", root), mock.patch.object(sys, "argv", argv):
                with self.assertRaises(SystemExit) as ctx:
                    module.main()
            self.assertEqual(baseline.read_bytes(), SENTINEL_BASELINE)
        self.assertNotIn(ctx.exception.code, (0, None))


class VacuousErrorLogUnscannableTest(_PathArgScanMixin, unittest.TestCase):
    # Gates at 0 with NO baseline, so a skipped file hides a finding for good.
    script = "vacuous_error_log_test_validator.py"
    filename = "test_target_module.py"

    def test_undecodable_file_fails_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unscannable_tree(tmp, self.filename, UNDECODABLE_SRC)
            result = _run_validator_cli(self.script, [str(root)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(self.filename, result.stdout + result.stderr)

    def test_stats_mode_also_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unscannable_tree(tmp, self.filename, UNPARSEABLE_SRC)
            result = _run_validator_cli(self.script, ["--stats", str(root)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unparseable_file_outside_the_scan_is_not_reported(self):
        # Control for "fail on files the scan never selects": not a test_*.py file.
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unscannable_tree(tmp, "helper_module.py", UNPARSEABLE_SRC)
            result = _run_validator_cli(self.script, [str(root)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class ErrorLogFlagCiSetterUnscannableTest(_PathArgScanMixin, unittest.TestCase):
    script = "error_log_flag_ci_setter_validator.py"

    def test_undecodable_file_fails_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unscannable_tree(tmp, self.filename, UNDECODABLE_SRC)
            result = _run_validator_cli(self.script, [str(root)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(self.filename, result.stdout + result.stderr)

    def test_undecodable_text_file_fails_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unscannable_tree(tmp, "ci_step.sh", UNDECODABLE_SRC)
            result = _run_validator_cli(self.script, [str(root)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ci_step.sh", result.stdout + result.stderr)

    def test_stats_mode_also_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unscannable_tree(tmp, self.filename, UNPARSEABLE_SRC)
            result = _run_validator_cli(self.script, ["--stats", str(root)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unscannable_file_of_an_unscanned_type_is_not_reported(self):
        # Control: a binary blob the scan never opens (no .py / text suffix).
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unscannable_tree(tmp, "blob.bin", UNDECODABLE_SRC)
            result = _run_validator_cli(self.script, [str(root)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class SubmittabilityDriftUnscannableTest(unittest.TestCase):
    """The scan root is REPO_ROOT, so main() is driven in-process with it pointed at a
    synthetic tree shaped like the repo (a `verenigingen/` package with hooks)."""

    HOOKS = "doc_events = {}\n"

    def _tree(self, tmp, extra=None, hooks=None):
        root = Path(tmp).resolve()
        (root / "verenigingen" / "hooks").mkdir(parents=True)
        (root / "verenigingen" / "hooks" / "doc_events.py").write_text(hooks or self.HOOKS)
        for rel, payload in (extra or {}).items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        return root

    def _main(self, root, *flags):
        module = _load_validator_module("submittability_drift_validator.py")
        baseline = root / "baseline.txt"
        baseline.write_bytes(SENTINEL_BASELINE)
        out = io.StringIO()
        with mock.patch.object(module, "REPO_ROOT", root), mock.patch.object(
            module, "_find_bench_apps", lambda _start: None
        ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = module.main(["--baseline", str(baseline), *flags])
        self.assertEqual(baseline.read_bytes(), SENTINEL_BASELINE)
        return rc, out.getvalue()

    def test_clean_tree_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, output = self._main(self._tree(tmp, {"verenigingen/mod.py": CLEAN_SRC}))
        self.assertEqual(rc, 0, output)

    def test_unparseable_python_file_fails_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp, {"verenigingen/broken_mod.py": UNPARSEABLE_SRC})
            rc, output = self._main(root)
        self.assertNotEqual(rc, 0, output)
        self.assertIn("broken_mod.py", output)

    def test_unparseable_hooks_file_fails_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp, hooks="doc_events = {\n")
            rc, output = self._main(root)
        self.assertNotEqual(rc, 0, output)
        self.assertIn("doc_events.py", output)

    def test_unparseable_doctype_json_fails_and_names_it(self):
        rel = "verenigingen/verenigingen/doctype/widget/widget.json"
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp, {rel: b"{not json"})
            rc, output = self._main(root)
        self.assertNotEqual(rc, 0, output)
        self.assertIn("widget.json", output)

    def test_update_baseline_refuses_and_leaves_baseline_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp, {"verenigingen/broken_mod.py": UNPARSEABLE_SRC})
            rc, output = self._main(root, "--update-baseline")
        self.assertNotEqual(rc, 0, output)
        self.assertIn("broken_mod.py", output)

    def test_unparseable_file_outside_the_app_package_is_not_reported(self):
        # Control for "fail on files outside the scan root".
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp, {"elsewhere/broken_mod.py": UNPARSEABLE_SRC})
            rc, output = self._main(root)
        self.assertEqual(rc, 0, output)


if __name__ == "__main__":
    unittest.main()
