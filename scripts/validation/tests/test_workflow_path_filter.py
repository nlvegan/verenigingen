#!/usr/bin/env python3
"""Regression guard for #1113: server-tests.yml must trigger on the
scripts/ files verenigingen's own test suite imports.

Pure-Python (no bench, no site, no PyYAML) -- runs in the Code Validation
workflow's stdlib-only job alongside its siblings. Run with:
    python -m unittest scripts.validation.tests.test_workflow_path_filter
or plain:
    python scripts/validation/tests/test_workflow_path_filter.py

Evidence for the specific paths asserted below (see #1113's PR body for the
full account): `verenigingen/tests/test_member_import_cleanup_engine.py`,
`verenigingen/tests/financial/test_create_period_closing_vouchers_pl_scan.py`
and `verenigingen/tests/payment/test_fee_override_migration.py` each import
a module directly from `scripts/migration/`. Those test files live under
`verenigingen/**/*.py`, which the filter already covers, but the modules
they import do not -- so a trunk push touching only
`scripts/migration/member_import_cleanup.py` can silently break
`test_member_import_cleanup_engine.py` without the server suite ever
running to catch it. A fourth `scripts/` import
(`scripts/workspace_debugging_toolkit.py`, from
`verenigingen/commands/workspace.py`) is deliberately NOT asserted here: it
is reached only from a bench CLI command, which no test in this suite
calls, so running the suite on a change to that file would verify nothing.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "workflow_path_filter.py"
_spec = importlib.util.spec_from_file_location("workflow_path_filter", _MOD_PATH)
wpf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = wpf
_spec.loader.exec_module(wpf)

_WORKFLOW_PATH = wpf.REPO_ROOT / ".github" / "workflows" / "server-tests.yml"

# The three scripts/migration/ files that verenigingen/tests/ actually
# imports and exercises (see module docstring for the evidence).
_IMPORTED_AND_TESTED = [
    "scripts/migration/member_import_cleanup.py",
    "scripts/migration/create_period_closing_vouchers.py",
    "scripts/migration/migrate_fee_overrides_to_dues_schedules.py",
]


class TestGlobMatching(unittest.TestCase):
    """Sanity-check the matcher itself before trusting it on the real file."""

    def test_double_star_matches_zero_middle_segments(self):
        self.assertTrue(wpf.path_matches_any("verenigingen/foo.py", ["verenigingen/**/*.py"]))

    def test_double_star_matches_nested_segments(self):
        self.assertTrue(
            wpf.path_matches_any("verenigingen/a/b/foo.py", ["verenigingen/**/*.py"])
        )

    def test_trailing_double_star_matches_direct_child(self):
        self.assertTrue(
            wpf.path_matches_any(".github/actions/setup/action.yml", [".github/actions/setup/**"])
        )

    def test_control_unrelated_path_does_not_match(self):
        """A path with no relation to any pattern must NOT match -- otherwise
        the matcher could be trivially permissive and every assertion below
        would pass for the wrong reason."""
        self.assertFalse(
            wpf.path_matches_any("scripts/analysis/unrelated_scanner.py", ["verenigingen/**/*.py"])
        )


class TestExtractTriggerPaths(unittest.TestCase):
    def test_comment_lines_inside_a_paths_list_do_not_truncate_it(self):
        """A `#`-comment between two `- pattern` list items must not look
        like a dedent that ends the list -- server-tests.yml's push.paths
        has exactly this shape (a multi-line comment sits between the `.js`
        pattern and the scripts/migration/ pattern added for #1113)."""
        text = (
            "on:\n"
            "  push:\n"
            "    paths:\n"
            "      - 'verenigingen/**/*.py'\n"
            "      # a comment explaining the next line\n"
            "      - 'scripts/migration/**/*.py'\n"
            "  pull_request:\n"
            "    paths:\n"
            "      - 'verenigingen/**/*.py'\n"
        )
        self.assertEqual(
            wpf.extract_trigger_paths(text, "push"),
            ["verenigingen/**/*.py", "scripts/migration/**/*.py"],
        )


class TestServerTestsWorkflowCoversScriptsMigrationImports(unittest.TestCase):
    def setUp(self):
        self.text = _WORKFLOW_PATH.read_text()

    def test_push_paths_cover_every_imported_scripts_migration_file(self):
        paths = wpf.extract_trigger_paths(self.text, "push")
        for target in _IMPORTED_AND_TESTED:
            with self.subTest(target=target):
                self.assertTrue(
                    wpf.path_matches_any(target, paths),
                    f"push.paths does not cover {target!r} -- a trunk push touching only "
                    f"this file would not run the server suite that tests it",
                )

    def test_pull_request_paths_cover_every_imported_scripts_migration_file(self):
        paths = wpf.extract_trigger_paths(self.text, "pull_request")
        for target in _IMPORTED_AND_TESTED:
            with self.subTest(target=target):
                self.assertTrue(
                    wpf.path_matches_any(target, paths),
                    f"pull_request.paths does not cover {target!r}",
                )

    def test_control_unimported_scripts_file_is_not_asserted_covered(self):
        """Companion to the module docstring's fourth import: this is not a
        claim that ALL of scripts/ should be covered, only the files that are
        actually imported and exercised by the app's own test suite. This
        control just confirms the extraction found a real, non-empty list
        (i.e. the two tests above are not vacuously true against an
        accidentally-empty patterns list)."""
        paths = wpf.extract_trigger_paths(self.text, "push")
        self.assertTrue(paths, "expected a non-empty push.paths list")
        self.assertIn("verenigingen/**/*.py", paths)


if __name__ == "__main__":
    unittest.main()
