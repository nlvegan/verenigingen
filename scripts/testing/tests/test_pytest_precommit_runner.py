#!/usr/bin/env python3
"""Unit tests for scripts/testing/pytest_precommit_runner.py.

Pure-Python (no bench/site needed). What is under test is a refusal, not a
feature: this hook runs the test suite, and it used to resolve its target site by
reading a file this bench never writes and then falling through to a hardcoded
`veg11.veganisme.org`. Every `git push` from the installed checkout ran the suite
against the LIVE site (#313).

So the tests that matter are the ones that pin the refusal. Each of them fails if
the `TEST_SITE` guard is deleted -- verified by deleting it.

Run with:  python -m pytest this_file.py
or plain:  python scripts/testing/tests/test_pytest_precommit_runner.py
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS_TESTING = Path(__file__).resolve().parents[1]
# The runner imports its sibling show_test_shards the way `python <script>` sets
# things up; replicate that here rather than duplicating the helpers.
sys.path.insert(0, str(_SCRIPTS_TESTING))

_MOD_PATH = _SCRIPTS_TESTING / "pytest_precommit_runner.py"
_spec = importlib.util.spec_from_file_location("pytest_precommit_runner", _MOD_PATH)
runner = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = runner
_spec.loader.exec_module(runner)


def _make_bench(root: Path, config: dict | None = None, currentsite: str | None = None) -> Path:
    bench = root / "frappe-bench"
    (bench / "apps" / "verenigingen").mkdir(parents=True)
    (bench / "sites").mkdir()
    if config is not None:
        (bench / "sites" / "common_site_config.json").write_text(json.dumps(config))
    if currentsite is not None:
        (bench / "sites" / "currentsite.txt").write_text(currentsite)
    return bench


class ResolveTargetSiteTest(unittest.TestCase):
    """The hook may target test_site_1..5 and nothing else."""

    def test_reads_default_site_from_common_site_config(self):
        with tempfile.TemporaryDirectory() as d:
            bench = _make_bench(Path(d), config={"default_site": "test_site_1"})
            site, refusal = runner.resolve_target_site(str(bench))
            self.assertEqual(site, "test_site_1")
            self.assertEqual(refusal, "")

    def test_refuses_the_live_site_from_default_site(self):
        """The exact shape of #313: bench pointed at the live site."""
        with tempfile.TemporaryDirectory() as d:
            bench = _make_bench(Path(d), config={"default_site": "veg11.veganisme.org"})
            site, refusal = runner.resolve_target_site(str(bench))
            self.assertIsNone(site)
            self.assertIn("veg11.veganisme.org", refusal)

    def test_refuses_the_live_site_from_currentsite_txt(self):
        """The fallback path must be gated by the same rule as the primary one."""
        with tempfile.TemporaryDirectory() as d:
            bench = _make_bench(Path(d), config={}, currentsite="veg11.veganisme.org")
            site, refusal = runner.resolve_target_site(str(bench))
            self.assertIsNone(site)
            self.assertIn("veg11.veganisme.org", refusal)

    def test_refuses_rather_than_defaulting_when_nothing_is_configured(self):
        """The old code answered `veg11.veganisme.org` here. There is no default now."""
        with tempfile.TemporaryDirectory() as d:
            bench = _make_bench(Path(d), config={})
            site, refusal = runner.resolve_target_site(str(bench))
            self.assertIsNone(site)
            self.assertNotIn("veg11", refusal.replace("live", ""))

    def test_default_site_wins_over_currentsite_txt(self):
        with tempfile.TemporaryDirectory() as d:
            bench = _make_bench(
                Path(d), config={"default_site": "test_site_2"}, currentsite="test_site_5"
            )
            site, _ = runner.resolve_target_site(str(bench))
            self.assertEqual(site, "test_site_2")

    def test_currentsite_txt_is_used_when_default_site_is_absent(self):
        with tempfile.TemporaryDirectory() as d:
            bench = _make_bench(Path(d), config={}, currentsite="test_site_3")
            site, _ = runner.resolve_target_site(str(bench))
            self.assertEqual(site, "test_site_3")

    def test_a_site_merely_starting_with_test_site_is_not_enough(self):
        """`test_site_1.example.com` is not test_site_1; the match is anchored."""
        with tempfile.TemporaryDirectory() as d:
            bench = _make_bench(Path(d), config={"default_site": "test_site_1.example.com"})
            site, _ = runner.resolve_target_site(str(bench))
            self.assertIsNone(site)


class LinkedWorktreeTest(unittest.TestCase):
    """Detecting a linked worktree, against real git rather than a stub."""

    def _git(self, cwd, *args):
        subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
        )

    def test_main_checkout_is_not_a_linked_worktree(self):
        with tempfile.TemporaryDirectory() as d:
            main = Path(d) / "main"
            main.mkdir()
            self._git(main, "init", "-q", "-b", "main")
            (main / "f").write_text("x")
            self._git(main, "add", "f")
            self._git(main, "commit", "-qm", "init")

            cwd = os.getcwd()
            try:
                os.chdir(main)
                self.assertFalse(runner.in_linked_worktree())
            finally:
                os.chdir(cwd)

    def test_linked_worktree_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            main = Path(d) / "main"
            main.mkdir()
            self._git(main, "init", "-q", "-b", "main")
            (main / "f").write_text("x")
            self._git(main, "add", "f")
            self._git(main, "commit", "-qm", "init")
            wt = Path(d) / "wt"
            self._git(main, "worktree", "add", "-q", "-b", "side", str(wt))

            cwd = os.getcwd()
            try:
                os.chdir(wt)
                self.assertTrue(runner.in_linked_worktree())
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
