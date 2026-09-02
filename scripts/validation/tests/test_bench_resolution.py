#!/usr/bin/env python3
"""Unit tests for scripts/validation/bench_resolution.py.

Pure-Python plus a handful of real `git` invocations against throwaway temp
repos -- no bench or site needed. Run with:
    python -m unittest scripts.validation.tests.test_bench_resolution
or plain:
    python scripts/validation/tests/test_bench_resolution.py

Every positive case here pairs with a control: a walk-up that finds nothing
and a git resolution that finds nothing are both exercised, not just the
happy path.
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "bench_resolution.py"
_spec = importlib.util.spec_from_file_location("bench_resolution", _MOD_PATH)
br = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = br
_spec.loader.exec_module(br)

_DNV_PATH = Path(__file__).resolve().parents[1] / "doctype_name_validator.py"


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30
    )


class TestWalkUp(unittest.TestCase):
    def test_finds_a_bench_ancestor(self):
        with tempfile.TemporaryDirectory() as tmp:
            bench = Path(tmp) / "bench"
            (bench / "apps" / "someapp").mkdir(parents=True)
            (bench / "sites").mkdir()
            start = bench / "apps" / "someapp" / "deeply" / "nested"
            start.mkdir(parents=True)
            self.assertEqual(br.find_bench_root(start), bench)

    def test_control_no_bench_ancestor_and_no_git_returns_none(self):
        """A plain non-git tree with no apps/+sites/ ancestor must refuse, not guess."""
        with tempfile.TemporaryDirectory() as tmp:
            start = Path(tmp) / "just" / "some" / "dirs"
            start.mkdir(parents=True)
            self.assertIsNone(br.find_bench_root(start))


class TestGitFallback(unittest.TestCase):
    """The regression guard for #752: a worktree with no bench ancestor of its own."""

    def _make_bench_with_repo(self, tmp: Path) -> tuple[Path, Path]:
        """A fake bench (apps/+sites/) whose apps/fakeapp/ is a real git repo.

        Returns (bench_root, repo_dir).
        """
        bench = tmp / "bench"
        repo = bench / "apps" / "fakeapp"
        repo.mkdir(parents=True)
        (bench / "sites").mkdir()
        _git("init", "-q", cwd=repo)
        _git("config", "user.email", "test@example.com", cwd=repo)
        _git("config", "user.name", "Test", cwd=repo)
        (repo / "README.md").write_text("fake app\n")
        _git("add", "README.md", cwd=repo)
        _git("commit", "-q", "-m", "initial", cwd=repo)
        return bench, repo

    def test_resolves_the_bench_from_a_worktree_outside_it(self):
        """The exact shape of #752: a linked worktree living outside the bench tree."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bench, repo = self._make_bench_with_repo(tmp)
            outside_worktree = tmp / "elsewhere" / "outside-worktree"
            outside_worktree.parent.mkdir(parents=True)
            result = _git(
                "worktree", "add", "--detach", str(outside_worktree), "HEAD", cwd=repo
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            # Control: the plain walk-up from the outside worktree finds nothing --
            # it has no bench ancestor at all -- so any success below comes from
            # the git-based fallback, not a lucky filesystem coincidence.
            self.assertIsNone(br._walk_up(outside_worktree, br.has_apps_and_sites))

            self.assertEqual(br.find_bench_root(outside_worktree), bench)

    def test_control_a_git_repo_with_no_bench_ancestor_still_returns_none(self):
        """A real git repo is not enough by itself -- its own tree must be under a bench."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = tmp / "standalone-repo"
            repo.mkdir()
            _git("init", "-q", cwd=repo)
            _git("config", "user.email", "test@example.com", cwd=repo)
            _git("config", "user.name", "Test", cwd=repo)
            (repo / "f.txt").write_text("x\n")
            _git("add", "f.txt", cwd=repo)
            _git("commit", "-q", "-m", "initial", cwd=repo)

            self.assertIsNone(br.find_bench_root(repo))

    def test_custom_marker_is_honoured_by_both_walks(self):
        """import_path_validator.py needs a stricter marker than has_apps_and_sites."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bench, repo = self._make_bench_with_repo(tmp)
            # No sites/common_site_config.json yet -- the stricter marker fails.
            marker = lambda c: (c / "sites" / "common_site_config.json").exists()
            outside_worktree = tmp / "elsewhere" / "outside-worktree"
            outside_worktree.parent.mkdir(parents=True)
            _git("worktree", "add", "--detach", str(outside_worktree), "HEAD", cwd=repo)
            self.assertIsNone(br.find_bench_root(outside_worktree, marker=marker))

            (bench / "sites" / "common_site_config.json").write_text("{}\n")
            self.assertEqual(br.find_bench_root(outside_worktree, marker=marker), bench)


class TestDoctypeNameValidatorIntegration(unittest.TestCase):
    """End-to-end: the actual validator script, run as a subprocess from a
    worktree outside the bench -- the precise reproduction in #752."""

    def test_self_check_resolves_from_a_worktree_outside_the_bench(self):
        repo_root = Path(__file__).resolve().parents[3]  # the checkout under test
        with tempfile.TemporaryDirectory() as tmp:
            outside_worktree = Path(tmp) / "outside-worktree"
            add = _git(
                "worktree", "add", "--detach", str(outside_worktree), "HEAD",
                cwd=repo_root,
            )
            self.assertEqual(add.returncode, 0, add.stderr)
            try:
                script = outside_worktree / "scripts" / "validation" / "doctype_name_validator.py"
                check = subprocess.run(
                    [sys.executable, str(script), "--self-check"],
                    capture_output=True, text=True, timeout=60,
                )
                self.assertEqual(
                    check.returncode, 0,
                    f"self-check failed from an out-of-bench worktree:\n"
                    f"{check.stdout}\n{check.stderr}",
                )
            finally:
                _git("worktree", "remove", "--force", str(outside_worktree), cwd=repo_root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
