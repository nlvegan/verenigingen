#!/usr/bin/env python3
"""Unit tests for scripts/validation/enhanced_field_reference_validator.py (#2323).

The validator was blind: `child_table_patterns` / `property_patterns` were assigned after a
`return`, so every file that reached the child-table exclusion raised AttributeError, which
`validate_file` swallowed, and the run reported "No field reference issues found!".

Each case builds a small synthetic app under a temp dir and copies the real validator into
its `scripts/validation/`, so `main()` resolves the app root exactly as in CI. Stdlib only.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_VALIDATION = Path(__file__).resolve().parents[1]
_SCRIPTS = ("enhanced_field_reference_validator.py", "doctype_loader.py", "bench_resolution.py")

_MEMBER = {
    "doctype": "DocType",
    "name": "Member",
    "fields": [{"fieldname": "full_name", "fieldtype": "Data"}],
}
_MISSING = "def f():\n    member = frappe.get_doc('Member', 'x')\n    return member.zzz_no_such_field\n"
_VALID = "def f():\n    member = frappe.get_doc('Member', 'x')\n    return member.full_name\n"
# `member` here is a child row, not a Member: the child-table exclusion must keep it quiet.
_CHILD_ROW = (
    "def f(self):\n"
    "    for member in self.team_members:\n"
    "        print(member.team_role)\n"
)


def _build_app(root: Path, sources: dict, extra_doctypes: tuple = ()) -> None:
    (root / "pyproject.toml").write_text('[project]\nname = "verenigingen"\n')
    for doctype in (_MEMBER, *extra_doctypes):
        doctype_dir = (
            root / "verenigingen" / "verenigingen" / "doctype" / doctype["name"].lower().replace(" ", "_")
        )
        doctype_dir.mkdir(parents=True)
        (doctype_dir / f"{doctype_dir.name}.json").write_text(json.dumps(doctype))
    for rel, src in sources.items():
        path = root / "verenigingen" / "services" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src)
    tools = root / "scripts" / "validation"
    tools.mkdir(parents=True)
    for name in _SCRIPTS:
        shutil.copy(_VALIDATION / name, tools / name)


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    script = root / "scripts" / "validation" / "enhanced_field_reference_validator.py"
    return subprocess.run(
        [sys.executable, str(script), *args], cwd=root, capture_output=True, text=True, timeout=120
    )


class _AppCase(unittest.TestCase):
    sources: dict = {}
    extra_doctypes: tuple = ()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "app"
        self.root.mkdir()
        _build_app(self.root, self.sources, self.extra_doctypes)
        self.baseline = self.root / "scripts" / "validation" / "field_reference_baseline.txt"


class ValidatorSeesTests(_AppCase):
    sources = {"missing.py": _MISSING, "valid.py": _VALID, "child.py": _CHILD_ROW}

    def test_a_missing_field_is_reported(self):
        # RED on develop: AttributeError on child_table_patterns, swallowed, exit 0.
        result = _run(self.root, "--pre-commit", "--no-baseline")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("zzz_no_such_field not in Member", result.stdout)

    def test_a_valid_reference_and_a_child_row_are_not_reported(self):
        # Controls: the same run reports only the seeded finding, so a valid field and a
        # child-table iteration (the exclusion that used to crash) stay quiet.
        result = _run(self.root, "--pre-commit", "--no-baseline")
        self.assertIn("Found 1 field reference issues", result.stdout)
        self.assertNotIn("full_name not in", result.stdout)
        self.assertNotIn("team_role not in", result.stdout)

    def test_a_relative_file_argument_is_validated(self):
        # pre-commit passes repo-relative paths; relative_to() on one used to raise and be swallowed.
        result = _run(self.root, "--no-baseline", "verenigingen/services/missing.py")
        self.assertEqual(result.returncode, 1, result.stdout)


class RatchetTests(_AppCase):
    sources = {"missing.py": _MISSING, "valid.py": _VALID}

    def test_update_baseline_records_the_finding_without_a_line_number(self):
        result = _run(self.root, "--update-baseline")
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = [
            ln for ln in self.baseline.read_text().splitlines() if ln and not ln.startswith("#")
        ]
        self.assertEqual(entries, ["verenigingen/services/missing.py::Member::zzz_no_such_field::1"])

    def test_baselined_findings_pass(self):
        _run(self.root, "--update-baseline")
        result = _run(self.root, "--pre-commit")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 baselined finding(s) suppressed", result.stdout)

    def test_a_new_finding_fails(self):
        _run(self.root, "--update-baseline")
        extra = self.root / "verenigingen" / "services" / "added.py"
        extra.write_text(_MISSING)
        result = _run(self.root, "--pre-commit")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("added.py", result.stdout)

    def test_a_higher_count_for_a_baselined_key_fails(self):
        _run(self.root, "--update-baseline")
        path = self.root / "verenigingen" / "services" / "missing.py"
        path.write_text(_MISSING + "\n\ndef g():\n    member = frappe.get_doc('Member', 'y')\n    return member.zzz_no_such_field\n")
        result = _run(self.root, "--pre-commit")
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_a_missing_baseline_baselines_nothing(self):
        # Control: without the file, the same finding fails, so the passes above come from the baseline.
        result = _run(self.root, "--pre-commit")
        self.assertEqual(result.returncode, 1, result.stdout)


# #2925: a variable's doctype was guessed from its NAME (`member` -> Member, `mandate` ->
# SEPA Mandate) even where the function plainly binds it to something else. The doctypes
# below are the real shapes: Team.team_roster rows are Team Member, not Member.
_TEAM = {
    "doctype": "DocType",
    "name": "Team",
    "fields": [{"fieldname": "team_roster", "fieldtype": "Table", "options": "Team Member"}],
}
_TEAM_MEMBER = {
    "doctype": "DocType",
    "name": "Team Member",
    "istable": 1,
    "fields": [
        {"fieldname": name, "fieldtype": "Data"}
        for name in ("role_in_team", "role_in_sorted_team", "role_in_param_team")
    ],
}
_MANDATE = {
    "doctype": "DocType",
    "name": "SEPA Mandate",
    "fields": [{"fieldname": "iban", "fieldtype": "Data"}],
}
# The existing child-table exclusion is a 10-line text window, so a control needs the access
# further from its loop than that to be reported at all.
_GAP = "    pass\n" * 12
# The SQL exclusion looks 20 lines back for the query that produced the rows.
_SQL_GAP = "    pass\n" * 25
_REAL_MANDATE = "def f():\n    mandate = frappe.get_doc('SEPA Mandate', 'x')\n    return mandate.zzz_real_stale\n"


class VariableNameGuessTests(_AppCase):
    extra_doctypes = (_TEAM, _TEAM_MEMBER, _MANDATE)
    sources = {
        # --- shapes that used to be reported on the strength of the NAME alone ---
        "child_loop.py": (
            "def f(self):\n    for member in self.team_roster:\n        pass\n" + _GAP
            + "    return member.role_in_team\n"
        ),
        "child_loop_or_sorted.py": (
            "def f(self):\n"
            "    for member in sorted(self.team_roster or [], key=lambda m: m.role_in_team):\n"
            "        print(member.role_in_sorted_team)\n"
        ),
        "sql_rows.py": (
            "def f():\n"
            "    result = frappe.db.sql('select 1', as_dict=True)\n" + _SQL_GAP +
            "    for member in result:\n"
            "        print(member.overdue_amount)\n"
        ),
        "api_object.py": (
            "def f(customer_obj, mandate_id):\n"
            "    mandate = customer_obj.mandates.get(mandate_id)\n"
            "    return mandate.signature_method\n"
        ),
        "untyped_param.py": "def f(member):\n    return member.role_in_param_team\n",
        "dataclass_param.py": "def f(mandate: SEPAMandate):\n    return mandate.original_mandate_id\n",
        "suffix_hook.py": (
            "def sync(doc, method):\n"
            "    donor_doc = frappe.get_doc('Member', doc.donor)\n"
            "    return donor_doc.full_name, doc.customer_name_x\n"
        ),
        "suffix_module_level.py": (
            "donor_doc = frappe.get_doc('Member', 'x')\nprint(doc.customer_name_y)\n"
        ),
        # --- controls: real references that must still be reported ---
        "real_member.py": "def f():\n    member = frappe.get_doc('Member', 'x')\n    return member.zzz_real_member\n",
        "real_mandate.py": _REAL_MANDATE,
        "typed_child_loop.py": (
            "def f(self):\n"
            "    for member in self.team_roster:\n"
            "        pass\n" + _GAP +
            "    return member.zzz_real_row\n"
        ),
        # `x = None` before/around the get_doc (try/except init, ternary) still names Member.
        "none_init.py": (
            "def f(n):\n    member = None\n    try:\n        member = frappe.get_doc('Member', n)\n"
            "    except Exception:\n        pass\n    return member.zzz_none_init\n"
        ),
        "ternary.py": (
            "def f(n, flag):\n    member = frappe.get_doc('Member', n) if flag else None\n"
            "    return member.zzz_ternary\n"
        ),
        # One name bound to two doctypes: the access is attributed to neither.
        "mixed_binding.py": (
            "def f(n, flag):\n    member = frappe.get_doc('Member', n)\n"
            "    if flag:\n        member = frappe.get_doc('Volunteer', n)\n"
            "    return member.zzz_mixed_binding\n"
        ),
        # Parent KNOWN from a get_doc (the wrapper keeps the older child-table exclusions out):
        # rows are Team Member, not Team.
        "parent_known_loop.py": (
            "def f(n):\n    team = frappe.get_doc('Team', n)\n"
            "    for member in sorted(team.team_roster or [], key=len):\n        pass\n" + _GAP
            + "    return member.role_in_team, member.zzz_parent_known\n"
        ),
        # `member` is a child row in one function and a real Member in the next: scope matters.
        "two_scopes.py": (
            "def a(self):\n    for member in self.team_roster:\n        print(member.role_in_team)\n" + _GAP + "\n"
            "def b():\n    member = frappe.get_doc('Member', 'x')\n    return member.zzz_two_scopes\n"
        ),
    }

    def setUp(self):
        super().setUp()
        self.out = _run(self.root, "--pre-commit", "--no-baseline").stdout

    def test_name_guess_shapes_are_not_reported(self):
        for needle in (
            "role_in_team not in", "role_in_sorted_team not in", "role_in_param_team not in", "overdue_amount not in", "signature_method not in",
            "original_mandate_id not in", "customer_name_x not in", "customer_name_y not in",
            "zzz_mixed_binding not in",
        ):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.out)

    def test_real_references_are_still_reported(self):
        self.assertIn("zzz_real_member not in Member", self.out)
        self.assertIn("zzz_real_stale not in SEPA Mandate", self.out)
        self.assertIn("zzz_two_scopes not in Member", self.out)
        self.assertIn("zzz_none_init not in Member", self.out)
        self.assertIn("zzz_ternary not in Member", self.out)

    def test_a_loop_over_a_known_child_table_is_checked_against_the_child_doctype(self):
        self.assertIn("zzz_real_row not in Team Member", self.out)
        self.assertIn("zzz_parent_known not in Team Member", self.out)
        self.assertNotIn("role_in_team not in", self.out.replace("role_in_team not in Team", ""))

    def test_exactly_the_seven_controls_are_reported(self):
        self.assertIn("Found 7 field reference issues", self.out)


class NonPythonArgumentsTests(_AppCase):
    """#3115: the pre-push hook also passes .html/.js; a push with no .py file used to fall
    through to the un-ratcheted whole-tree scan and exit 1 on findings it never touched."""

    sources = {"missing.py": _MISSING}

    def test_only_non_python_arguments_check_nothing_and_pass(self):
        # RED on develop: the .html is dropped, the list is empty, the whole tree is scanned
        # and the seeded finding in missing.py (not in the pushed files) fails the run.
        result = _run(self.root, "verenigingen/templates/x.html", "verenigingen/public/js/y.js")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("nothing to check", result.stdout)
        self.assertNotIn("zzz_no_such_field", result.stdout)

    def test_a_python_argument_alongside_html_is_still_reported(self):
        result = _run(
            self.root, "--no-baseline", "verenigingen/templates/x.html", "verenigingen/services/missing.py"
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("zzz_no_such_field not in Member", result.stdout)

    def test_no_arguments_still_scans_the_whole_tree(self):
        # Control for the first test: the seeded finding is visible when nothing is passed.
        result = _run(self.root, "--no-baseline")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("zzz_no_such_field not in Member", result.stdout)

    def test_update_baseline_with_a_non_python_argument_still_writes_the_baseline(self):
        # Pins the `passed_files = []` line in the update branch: without it the html argument
        # would short-circuit to "nothing to check" and the baseline would never be written.
        result = _run(self.root, "--update-baseline", "verenigingen/templates/x.html")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("zzz_no_such_field", self.baseline.read_text())


if __name__ == "__main__":
    unittest.main()
