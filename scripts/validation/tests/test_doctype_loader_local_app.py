#!/usr/bin/env python3
"""Tests for #1839: the field validators read THIS app's DocTypes from the checkout they
run in (a git worktree), not from the bench's installed copy of the app.

Before the fix `get_unified_doctype_loader` derived the bench as `app_path.parent.parent`:
  * worktree outside the bench -> a directory with no apps/ -> ZERO DocTypes, so every
    check silently passed (false negative);
  * worktree inside the bench  -> the bench's installed `apps/verenigingen`, which lacks
    the branch's new fields (false positive on any field a branch adds).

Pure Python, builds a throwaway bench and a throwaway worktree. Run with:
    python -m unittest scripts.validation.tests.test_doctype_loader_local_app
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_VALIDATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VALIDATION))
sys.path.insert(0, str(_VALIDATION / "framework"))

from doctype_loader import DocTypeLoader, get_unified_doctype_loader  # noqa: E402


def _write_app(root: Path, member_fields, with_pyproject=True):
    """An app checkout with one `Member` DocType whose fields are `member_fields`."""
    doctype_dir = root / "verenigingen" / "verenigingen" / "doctype" / "member"
    doctype_dir.mkdir(parents=True)
    fields = [{"fieldname": f, "fieldtype": "Data", "label": f} for f in member_fields]
    (doctype_dir / "member.json").write_text(
        json.dumps({"name": "Member", "module": "Verenigingen", "fields": fields})
    )
    if with_pyproject:
        (root / "pyproject.toml").write_text('[project]\nname = "verenigingen"\n')


def _make_bench(tmp: Path) -> Path:
    """A bench whose INSTALLED verenigingen has `installed_only` but not `branch_only`,
    plus a frappe app with a `User` DocType."""
    bench = tmp / "bench"
    (bench / "sites").mkdir(parents=True)
    _write_app(bench / "apps" / "verenigingen", ["first_name", "installed_only"])
    user_dir = bench / "apps" / "frappe" / "frappe" / "core" / "doctype" / "user"
    user_dir.mkdir(parents=True)
    (user_dir / "user.json").write_text(
        json.dumps({"name": "User", "fields": [{"fieldname": "email", "fieldtype": "Data"}]})
    )
    (bench / "apps" / "frappe" / "pyproject.toml").write_text('[project]\nname = "frappe"\n')
    return bench


def _git(*args, cwd):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), check=True, capture_output=True, timeout=60,
    )


def _git_worktree(bench: Path, tmp: Path, member_fields) -> Path:
    """A real linked git worktree of the bench's app, OUTSIDE the bench (as agents create
    them), whose Member has `member_fields`. A filesystem walk-up cannot find the bench from
    here; only git can, which is the shape #1839 is about."""
    installed = bench / "apps" / "verenigingen"
    _git("init", "-q", cwd=installed)
    _git("add", "-A", cwd=installed)
    _git("commit", "-q", "-m", "init", cwd=installed)
    worktree = tmp / "worktree"
    _git("worktree", "add", "-q", "--detach", str(worktree), cwd=installed)
    member_json = worktree / "verenigingen" / "verenigingen" / "doctype" / "member" / "member.json"
    member_json.write_text(json.dumps({"name": "Member", "fields": [
        {"fieldname": f, "fieldtype": "Data"} for f in member_fields]}))
    return worktree


class TestLocalAppResolution(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.bench = _make_bench(self.tmp)
        # A real git worktree: has `branch_only`, dropped `installed_only`.
        self.worktree = _git_worktree(self.bench, self.tmp, ["first_name", "branch_only"])
        self.addCleanup(self._tmp.cleanup)

    def test_branch_field_is_visible_to_a_loader_for_the_worktree(self):
        loader = DocTypeLoader(
            str(self.bench), local_app_path=str(self.worktree)
        )
        self.assertTrue(loader.has_field("Member", "branch_only"))

    def test_worktree_wins_over_the_installed_copy(self):
        """Control: a field only the INSTALLED copy has must not leak in."""
        loader = DocTypeLoader(str(self.bench), local_app_path=str(self.worktree))
        self.assertFalse(loader.has_field("Member", "installed_only"))

    def test_other_apps_still_load_from_the_bench(self):
        loader = DocTypeLoader(str(self.bench), local_app_path=str(self.worktree))
        self.assertTrue(loader.has_field("User", "email"))

    def test_without_a_local_app_the_installed_copy_is_used(self):
        """Control: the new argument is what changes the answer, not a side effect."""
        loader = DocTypeLoader(str(self.bench))
        self.assertTrue(loader.has_field("Member", "installed_only"))
        self.assertFalse(loader.has_field("Member", "branch_only"))

    def test_factory_finds_the_bench_for_a_worktree_outside_it(self):
        """The old `app_path.parent.parent` is tmp/, which has no apps/: zero DocTypes."""
        self.assertFalse((self.worktree.parent.parent / "apps").exists())
        loader = get_unified_doctype_loader(str(self.worktree))
        self.assertEqual(loader.bench_path.resolve(), self.bench.resolve())
        self.assertTrue(loader.has_field("User", "email"))
        self.assertTrue(loader.has_field("Member", "branch_only"))

    def test_factory_for_a_worktree_inside_the_bench(self):
        """Old behaviour: parent.parent == bench, so the INSTALLED copy hid `branch_only`."""
        inside = self.bench / "worktrees" / "wt"
        inside.parent.mkdir()
        _git("worktree", "add", "-q", "--detach", str(inside), cwd=self.bench / "apps" / "verenigingen")
        (inside / "verenigingen" / "verenigingen" / "doctype" / "member" / "member.json").write_text(
            json.dumps({"name": "Member", "fields": [{"fieldname": "branch_only", "fieldtype": "Data"}]})
        )
        loader = get_unified_doctype_loader(str(inside))
        self.assertTrue(loader.has_field("Member", "branch_only"))
        self.assertFalse(loader.has_field("Member", "installed_only"))

    def test_factory_for_the_installed_app_itself_is_unchanged(self):
        loader = get_unified_doctype_loader(str(self.bench / "apps" / "verenigingen"))
        self.assertTrue(loader.has_field("Member", "installed_only"))


class TestAnalyzerEndToEnd(unittest.TestCase):
    """The hook itself: a field added in a worktree is not flagged; a typo still is."""

    def test_new_field_passes_and_unknown_field_is_flagged(self):
        from ast_field_analyzer_core import ASTFieldAnalyzer

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            bench = _make_bench(tmp)
            worktree = _git_worktree(bench, tmp, ["first_name", "branch_only"])
            source = worktree / "verenigingen" / "uses_fields.py"
            source.write_text(
                "import frappe\n\n\n"
                "def uses(name):\n"
                '    member = frappe.get_doc("Member", name)\n'
                "    return member.branch_only, member.no_such_field_1839\n"
            )
            analyzer = ASTFieldAnalyzer(str(worktree))
            flagged = {i.field for i in analyzer.validate_file(source)}
            self.assertIn("no_such_field_1839", flagged)  # control: the check still fires
            self.assertNotIn("branch_only", flagged)


if __name__ == "__main__":
    unittest.main()
