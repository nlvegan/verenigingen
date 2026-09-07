#!/usr/bin/env python3
"""Unit tests for scripts_dir_baseline.py, the shrink-only baseline helper
introduced by #1069/#1075 so widening api_security_validator.py /
insecure_api_detector.py onto `scripts/` does not turn every pre-existing,
untriaged finding there into a blocking failure while leaving
`verenigingen/api/` at zero tolerance (the baseline never applies to it, even
if a `verenigingen/api/` key is somehow present in the file).

Pure-Python, no bench/site needed. Run with:
    python -m unittest scripts.validation.tests.test_scripts_dir_baseline
or: python scripts/validation/tests/test_scripts_dir_baseline.py
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_SECURITY_DIR = Path(__file__).resolve().parents[1] / "security"


def _load(module_name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(module_name, _SECURITY_DIR / file_name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


baseline_mod = _load("scripts_dir_baseline_1069", "scripts_dir_baseline.py")


class PartitionByBaselineTest(unittest.TestCase):
    def test_scripts_finding_in_baseline_is_known_not_blocking(self):
        baseline = {("scripts/debug/foo.py", "bar", "security_decorator_required")}
        findings = [("scripts/debug/foo.py", "bar", "security_decorator_required")]

        blocking, known = baseline_mod.partition_by_baseline(findings, baseline)

        self.assertEqual(blocking, [])
        self.assertEqual(known, findings)

    def test_scripts_finding_not_in_baseline_is_blocking(self):
        """The load-bearing case: a NEW scripts/ finding must never be
        silently absorbed just because scripts/ has a baseline at all."""
        baseline = {("scripts/debug/foo.py", "bar", "security_decorator_required")}
        new_finding = [("scripts/debug/other.py", "baz", "security_decorator_required")]

        blocking, known = baseline_mod.partition_by_baseline(new_finding, baseline)

        self.assertEqual(blocking, new_finding)
        self.assertEqual(known, [])

    def test_verenigingen_api_finding_always_blocks_even_if_key_present_in_baseline(self):
        """verenigingen/api/ must stay zero-tolerance: even a key that
        happens to collide with something in the scripts/ baseline file
        must not be excused, because is_scripts_path() gates eligibility,
        not baseline membership alone."""
        key = ("verenigingen/api/member_management.py", "leak", "security_decorator_required")
        baseline = {key}

        blocking, known = baseline_mod.partition_by_baseline([key], baseline)

        self.assertEqual(blocking, [key])
        self.assertEqual(known, [])

    def test_empty_baseline_blocks_every_scripts_finding(self):
        findings = [
            ("scripts/a.py", "f1", "check"),
            ("scripts/b.py", "f2", "check"),
        ]
        blocking, known = baseline_mod.partition_by_baseline(findings, set())
        self.assertEqual(sorted(blocking), sorted(findings))
        self.assertEqual(known, [])


class LoadWriteBaselineRoundTripTest(unittest.TestCase):
    def test_write_then_load_round_trips(self):
        keys = {
            ("scripts/a.py", "f1", "security_decorator_required"),
            ("scripts/b/c.py", "f2", "sql_injection_risk"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.txt"
            baseline_mod.write_baseline(path, keys, "# header")

            loaded = baseline_mod.load_baseline(path)

        self.assertEqual(loaded, keys)

    def test_missing_file_loads_as_empty_set(self):
        path = Path(tempfile.gettempdir()) / "does-not-exist-1069-baseline.txt"
        self.assertFalse(path.exists())
        self.assertEqual(baseline_mod.load_baseline(path), set())

    def test_blank_and_comment_lines_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.txt"
            path.write_text(
                "# a comment\n\nscripts/a.py::f1::check\n   \n",
                encoding="utf-8",
            )
            loaded = baseline_mod.load_baseline(path)
        self.assertEqual(loaded, {("scripts/a.py", "f1", "check")})


class IsScriptsPathTest(unittest.TestCase):
    def test_scripts_prefix_is_true(self):
        self.assertTrue(baseline_mod.is_scripts_path("scripts/foo/bar.py"))

    def test_verenigingen_api_is_false(self):
        self.assertFalse(baseline_mod.is_scripts_path("verenigingen/api/foo.py"))

    def test_lookalike_prefix_is_false(self):
        # "scripts_extra/" starts with "scripts" but not with "scripts/" --
        # must not be treated as the scan root by a loose startswith("scripts").
        self.assertFalse(baseline_mod.is_scripts_path("scripts_extra/foo.py"))


if __name__ == "__main__":
    unittest.main()
