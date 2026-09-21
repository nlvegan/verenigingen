#!/usr/bin/env python3
"""Unit tests for scripts/validation/savepoint_rollback_validator.py (#1189).

Pure-Python (no bench/site needed): loads the module by file path exactly the way
`production_divergence_scanner.py` loads `duplicate_helper_validator.py`, so this works
regardless of sys.path/cwd and needs no `scripts.validation` package resolution. Run with:

    python -m unittest discover -s scripts/validation/tests \
        -p 'test_savepoint_rollback_validator.py' -v

The bug this closes: `verenigingen/tests/unit/test_savepoint_rollback_cannot_mask_the_error.py`
holds the #561 AST ratchet, but until #1189 it was reachable ONLY from inside the full bench
test suite -- no pre-commit hook, no pre-push hook, no named CI job. PR #1171 tripped it twice
with pre-commit/pre-push both green. This module is the standalone entry point that closes
that gap, and this file is its unit test.

`test_offenders_matches_the_shared_fixtures` and `test_accepted_shapes_produce_no_offenders`
run the SAME `PLANTED_OFFENDING_SHAPES`/`ACCEPTED_SHAPES` dictionaries the bench test's
`test_the_ratchet_sees_the_shapes_the_app_no_longer_contains` checks -- not a second, drifting
copy -- because both entry points import them from this module.
"""

import ast
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "savepoint_rollback_validator.py"
_spec = importlib.util.spec_from_file_location("savepoint_rollback_validator", _MOD_PATH)
v = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v
_spec.loader.exec_module(v)


class TestSavepointRollbackValidator(unittest.TestCase):
    def test_offenders_matches_the_shared_fixtures(self):
        """Every planted offending shape is caught, with the exact count the bench test
        expects -- the same fixture dict both entry points import."""
        for label, (snippet, expected) in v.PLANTED_OFFENDING_SHAPES.items():
            with self.subTest(label):
                found = list(v.offenders(snippet, ast.parse(snippet)))
                self.assertEqual(len(found), expected, f"{label}: expected {expected}, got {found}")

    def test_accepted_shapes_produce_no_offenders(self):
        for label, snippet in v.ACCEPTED_SHAPES.items():
            with self.subTest(label):
                self.assertEqual(list(v.offenders(snippet, ast.parse(snippet))), [], f"{label} must be accepted")

    def test_the_repository_is_clean(self):
        """The control the task asks for: the CURRENT tree must report zero offenders. If
        this ever goes red on an unmodified tree, the extraction changed what the check
        finds, which is exactly the risk #1189 warns against."""
        self.assertEqual(v.scan(None), [])

    def test_main_reports_nonzero_exit_and_the_offending_line_for_a_planted_file(self):
        """RED: a real file on disk with a hand-written savepoint rollback in a swallowing
        except, run through main() the way pre-commit invokes it (explicit file paths)."""
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "offender.py"
            bad.write_text(
                "def f():\n"
                "    try:\n"
                "        g()\n"
                "    except Exception:\n"
                "        frappe.db.rollback(save_point=sp)\n"
                "        return None\n"
            )
            # A bare rollback in a swallowing catch-all breaks BOTH rules -- the same shape
            # as PLANTED_OFFENDING_SHAPES["a catch-all that swallows breaks both rules"],
            # which expects 2 findings, not 1.
            findings = v.scan([str(bad)])
            self.assertEqual(len(findings), 2, findings)
            self.assertTrue(all("offender.py" in f for f in findings), findings)
            self.assertTrue(any("swallowing catch-all" in f for f in findings), findings)
            self.assertTrue(any("instead of rollback_to_savepoint()" in f for f in findings), findings)

            rc = v.main(["prog", str(bad)])
            self.assertEqual(rc, 1)

    def test_main_reports_clean_exit_once_the_offender_is_fixed(self):
        """GREEN: the same file, with the offending handler replaced by the sanctioned
        helper and a guard -- same command, same file, no offenders."""
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "fixed.py"
            good.write_text(
                "def f():\n"
                "    try:\n"
                "        g()\n"
                "    except NON_RESUMABLE_DB_ERRORS:\n"
                "        raise\n"
                "    except Exception:\n"
                "        rollback_to_savepoint(sp)\n"
                "        return None\n"
            )
            self.assertEqual(v.scan([str(good)]), [])
            rc = v.main(["prog", str(good)])
            self.assertEqual(rc, 0)

    def test_production_files_excludes_tests_and_test_prefixed_files(self):
        """Scope must match the original test's SKIP_DIRS/`test_` filter exactly, or the two
        entry points scan different trees."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "not_scanned.py").write_text("x = 1\n")
            (root / "test_also_not_scanned.py").write_text("x = 1\n")
            (root / "scanned.py").write_text("x = 1\n")
            found = {p.name for p in v.production_files(root)}
            self.assertEqual(found, {"scanned.py"})


if __name__ == "__main__":
    unittest.main()
