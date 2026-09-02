"""Whole-tree gate for `scripts/validation/doctype_name_validator.py`.

The pre-commit hook sees only the files in the commit, and `git commit -n`
skips it entirely. Its siblings (`error_swallow`, `duplicate_helper`) close that
hole with a job in the Code Validation workflow, because they are stdlib-only
and need no bench. **This one is not**: its authority is the DocType JSONs of
every app on the bench, and that workflow checks out this app alone -- so there
the authority would silently contain only Verenigingen's own doctypes and the
gate would flag `frappe.get_doc("User", ...)`.

The app test suite already runs where a full bench exists (`.github/actions/setup`
clones frappe, erpnext, hrms and payments into `apps/`), so the whole-tree run
lives here instead. `test_the_authority_is_complete` refuses to let the ratchet
report a pass from a partial authority -- an authority missing half the bench
would make the census *grow*, not shrink, so the failure mode is loud rather
than silent, but the diagnosis would be wrong and this says so directly.

Why a ratchet and not a gate: 93 unknown-doctype call sites already exist, mostly
aspirational doctypes in tests. See the validator's docstring for the measured
behaviour of each frappe API on a missing doctype, and #677 / #491 for what it
cost.

`TestOutOfBenchWorktreeRegression` below is a different concern: not the
census, but whether the validator can find the bench AT ALL from a git
worktree created outside it (#752). That needs the same full bench as the
census above, so it lives here too rather than in
scripts/validation/tests/test_bench_resolution.py, which is stdlib-only and
runs in the Code Validation workflow where no bench exists.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT / "scripts" / "validation"))

import doctype_name_validator as v  # noqa: E402

# Doctypes from four different apps. If the authority cannot see all of these it
# is not looking at a bench, and any verdict it produces is about the wrong tree.
AUTHORITY_PROBES = {
    "frappe": "User",
    "erpnext": "Sales Invoice",
    "hrms": "Expense Claim",
    "verenigingen": "Chapter Board Member",
}


class TestDocTypeNameRatchet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.known = v.known_doctypes()

    def test_the_authority_is_complete(self):
        """Control: without this, a partial authority is indistinguishable from a regression."""
        missing = {app: dt for app, dt in AUTHORITY_PROBES.items() if dt not in self.known}
        self.assertEqual(
            missing, {},
            f"the DocType authority is incomplete ({len(self.known)} doctypes from "
            f"{v.BENCH_APPS}); every finding below would be an artefact of that, not a defect",
        )

    def test_the_role_names_behind_677_are_still_not_doctypes(self):
        """The premise of the fix, asserted rather than assumed.

        If any of these ever becomes a real DocType, the whole reasoning in
        `chapter_members._has_active_board_seat` and in the validator's docstring
        stops holding and both need re-reading -- so fail loudly rather than let
        the ratchet quietly agree.
        """
        for role_name in (
            "Verenigingen Chapter Board Member",
            "Verenigingen Volunteer",
            "Verenigingen Chapter",
            "Verenigingen Volunteer Team",
        ):
            self.assertNotIn(role_name, self.known, f"{role_name!r} is a Role, not a DocType")
        for doctype in ("Chapter Board Member", "Volunteer", "Chapter", "Team"):
            self.assertIn(doctype, self.known)

    def test_no_new_unknown_doctype_names(self):
        counts, detail = v.census(v.SCAN_ROOTS)
        baseline = v.load_baseline(v.DEFAULT_BASELINE)
        grown = {key: count for key, count in counts.items() if count > baseline.get(key, 0)}
        if not grown:
            return
        lines = []
        for key in sorted(grown):
            path, _, name = key.partition("::")
            for finding in detail[key]:
                lines.append(f"  {path}:{finding.lineno}  {finding.api}({name!r}, ...)")
        # Frappe's failure formatter prints every local in the frame. `counts` and
        # `detail` are the whole 93-entry census, which would bury the two lines
        # that matter under a screenful of object reprs.
        del counts, detail, baseline, grown
        self.fail(
            "String literals in a doctype-name position naming something that is not a "
            "DocType in any app on this bench:\n"
            + "\n".join(lines)
            + "\n\nNothing in the framework tells you: frappe.db.exists returns None (the "
            "same answer as 'no such row'), the rest raise into whatever broad `except` is "
            "nearest. Fix the name, or mark the line `# doctype-ok: <reason>` if the "
            "unknown name is the point.\n"
            "Full census: python scripts/validation/doctype_name_validator.py --report"
        )


class TestOutOfBenchWorktreeRegression(unittest.TestCase):
    """#752: a git worktree created OUTSIDE the bench (routinely done under
    /tmp in this project) has no `apps/`+`sites/` ancestor for a filesystem
    walk-up to find, so BENCH_APPS used to resolve wrongly, zero doctypes
    loaded, and the self-check correctly refused to run -- as a pre-commit
    gate with no override, the practical effect was `--no-verify`, which
    skips every hook, not just this one.

    This copies the CURRENT scripts/validation/*.py files (not just the last
    commit) into a real linked worktree placed outside the bench, so it also
    catches an uncommitted regression -- `git worktree add` alone checks out
    HEAD, which would miss a mutation to bench_resolution.py made but not yet
    committed.
    """

    def test_self_check_resolves_from_a_worktree_outside_the_bench(self):
        validation_dir = APP_ROOT / "scripts" / "validation"
        env = dict(os.environ)
        env.pop("BENCH_APPS", None)  # an ambient override would hide a real regression

        with tempfile.TemporaryDirectory() as tmp:
            outside_worktree = Path(tmp) / "outside-worktree"
            add = subprocess.run(
                ["git", "worktree", "add", "--detach", str(outside_worktree), "HEAD"],
                cwd=APP_ROOT, capture_output=True, text=True,
            )
            self.assertEqual(add.returncode, 0, add.stderr)
            try:
                outside_validation = outside_worktree / "scripts" / "validation"
                for py_file in validation_dir.glob("*.py"):
                    shutil.copy2(py_file, outside_validation / py_file.name)

                script = outside_validation / "doctype_name_validator.py"
                check = subprocess.run(
                    [sys.executable, str(script), "--self-check"],
                    capture_output=True, text=True, timeout=60, env=env,
                )
                self.assertEqual(
                    check.returncode, 0,
                    f"self-check failed from an out-of-bench worktree:\n"
                    f"{check.stdout}\n{check.stderr}",
                )
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(outside_worktree)],
                    cwd=APP_ROOT, capture_output=True, text=True,
                )
