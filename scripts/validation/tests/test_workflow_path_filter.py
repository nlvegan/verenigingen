#!/usr/bin/env python3
"""Regression guard for #1113: server-tests.yml must trigger on the
scripts/ files verenigingen's own test suite imports.

Pure-Python (no bench, no site, no PyYAML) -- runs in the Code Validation
workflow's stdlib-only job alongside its siblings. Run with:
    python -m unittest scripts.validation.tests.test_workflow_path_filter
or plain:
    python scripts/validation/tests/test_workflow_path_filter.py

The coverage assertions below do NOT hardcode the files verenigingen/tests/
imports from scripts/ -- an earlier version of this guard did, and a
reviewer correctly flagged that a hardcoded list only closes today's 3
instances, not the class: a future `from scripts.<new_module> import x`
added under verenigingen/tests/ would (a) not be in the workflow filter --
today's bug again -- and (b) not be caught by a guard that only checks the
names it already knows. `_scripts_files_imported_under_tests` instead
AST-walks every file under `verenigingen/tests/` for `from scripts...`/
`import scripts...` and resolves each to the `.py` file(s) it actually
names, so a new import shows up here automatically the next time this test
runs.

Scoped to `verenigingen/tests/`, not all of `verenigingen/`: any import in a
file under `verenigingen/tests/` -- module-level or inside a test method --
is reachable by `bench run-parallel-tests` merely by that file/method being
collected and run, so a break in the imported `scripts/` code is guaranteed
to surface there. `verenigingen/commands/workspace.py`'s import of
`scripts/workspace_debugging_toolkit.py` (the fourth `scripts/` import in
the app, found while investigating #1113) is deliberately outside that
scope: it is a deferred import inside a bench CLI command body that no test
calls, so including `scripts/workspace_debugging_toolkit.py` in the
workflow filter would run the suite on a change to it and verify nothing.
That is a judgment call this scan cannot make for a future case either --
if `verenigingen/`'s non-test code grows a new `scripts/` import that IS
reachable by some test indirectly (without the test file itself naming
`scripts` in an import statement), this scan will not see it. It catches
the class of bug #1113 was actually filed for: a test file that itself
imports scripts/ code.
"""
import ast
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
_TESTS_DIR = wpf.REPO_ROOT / "verenigingen" / "tests"

# Known-good set as of 2026-09-21 (see module docstring). This is a CONTROL,
# not the source of truth for the coverage assertions below -- if the dynamic
# scan ever finds something different, this test fails and forces a human to
# look at *why* (a new import needing a filter entry, or a scan bug), rather
# than the coverage tests silently starting to check a different set with no
# visible diff.
#
# #1189 added the last two entries: this guard caught them for real, a few
# hours after #1184 merged -- PR #1189 added
# `verenigingen/tests/unit/test_savepoint_rollback_cannot_mask_the_error.py`
# imports of two new scripts/validation/ modules, and this test's dynamic
# scan found them where the workflow's paths filter did not cover them yet.
# That is the exact mechanism this guard exists for: a hardcoded list would
# have stayed green and let the gap through.
_KNOWN_SCRIPTS_FILES_IMPORTED_UNDER_TESTS = {
    "scripts/migration/member_import_cleanup.py",
    "scripts/migration/create_period_closing_vouchers.py",
    "scripts/migration/migrate_fee_overrides_to_dues_schedules.py",
    "scripts/validation/non_resumable_ast.py",
    "scripts/validation/savepoint_rollback_validator.py",
}


def _module_to_path(dotted: str) -> Path:
    return wpf.REPO_ROOT / Path(*dotted.split(".")).with_suffix(".py")


def _scripts_files_imported_by(py_file: Path) -> set[str]:
    """Dotted-module -> `.py` file resolution for `scripts` imports in one file.

    `from scripts.migration import member_import_cleanup` names a package
    (`scripts.migration`) and a NAME imported from it, which is ambiguous
    from syntax alone: `member_import_cleanup` could be a submodule
    (`scripts/migration/member_import_cleanup.py`) or an attribute defined
    inside `scripts/migration/__init__.py`. Resolved against the real
    filesystem rather than guessed, preferring the deeper (submodule) path
    when it exists.
    """
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module != "scripts" and not node.module.startswith("scripts."):
                continue
            for alias in node.names:
                submodule = f"{node.module}.{alias.name}"
                if _module_to_path(submodule).is_file():
                    found.add(submodule)
                elif _module_to_path(node.module).is_file():
                    found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "scripts" or alias.name.startswith("scripts."):
                    if _module_to_path(alias.name).is_file():
                        found.add(alias.name)

    return found


def _scripts_files_imported_under_tests() -> list[str]:
    modules: set[str] = set()
    for py_file in _TESTS_DIR.rglob("*.py"):
        modules |= _scripts_files_imported_by(py_file)
    return sorted(str(_module_to_path(m).relative_to(wpf.REPO_ROOT)) for m in modules)


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

    def test_double_star_glued_to_a_suffix_raises(self):
        """`**.js` is a documented GitHub shape this module does not
        implement (see UnsupportedGlobPattern) -- it must fail loudly, not
        silently fall back to the plain, non-cross-`/` `*` rule."""
        with self.assertRaises(wpf.UnsupportedGlobPattern):
            wpf.path_matches_any("src/js/app.js", ["**.js"])


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


class TestServerTestsWorkflowCoversScriptsImportedByTests(unittest.TestCase):
    def setUp(self):
        self.text = _WORKFLOW_PATH.read_text()
        self.targets = _scripts_files_imported_under_tests()

    def test_control_known_import_set_has_not_silently_changed(self):
        """Guards the scan itself: if this ever fails, either a new
        scripts/ import needs a filter entry (update the known set once
        you've added it below AND to the workflow), or the AST scan broke
        and is no longer finding the real imports -- either way, a human
        needs to look, not have the coverage tests below start silently
        checking a different (possibly empty) set."""
        self.assertEqual(
            set(self.targets), _KNOWN_SCRIPTS_FILES_IMPORTED_UNDER_TESTS
        )

    def test_push_paths_cover_every_scripts_file_tests_import(self):
        paths = wpf.extract_trigger_paths(self.text, "push")
        for target in self.targets:
            with self.subTest(target=target):
                self.assertTrue(
                    wpf.path_matches_any(target, paths),
                    f"push.paths does not cover {target!r} -- a trunk push touching only "
                    f"this file would not run the server suite that tests it",
                )

    def test_pull_request_paths_cover_every_scripts_file_tests_import(self):
        paths = wpf.extract_trigger_paths(self.text, "pull_request")
        for target in self.targets:
            with self.subTest(target=target):
                self.assertTrue(
                    wpf.path_matches_any(target, paths),
                    f"pull_request.paths does not cover {target!r}",
                )


if __name__ == "__main__":
    unittest.main()
