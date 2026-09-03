#!/usr/bin/env python3
"""Unit tests for scripts/validation/test_quality_enforcer.py.

Pure-Python (no bench/site needed): each case is a source snippet written to a temp
file and run through the enforcer. Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_test_quality_enforcer.py

The cases here are deliberately split into two halves:

* **detection** -- the enforcer still finds what it is supposed to find. These exist
  because the false-positive fixes below are the kind that quietly delete a rule
  rather than narrow it: 14 of the enforcer's 18 patterns REQUIRE a quote, so any
  "ignore matches inside strings" implementation silences most of the gate while
  every false-positive test still passes. A ratchet cannot notice -- a shrinking
  baseline is the celebrated direction.
* **keying** -- the baseline key is stable and correct. A key that rots (line
  numbers) or lies (wrong enclosing function) makes the ratchet report noise on
  untouched code, which is how a gate stops being run.
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "test_quality_enforcer.py"
_spec = importlib.util.spec_from_file_location("test_quality_enforcer", _MOD_PATH)
tqe = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = tqe
_spec.loader.exec_module(tqe)


# Assembled rather than written out. This originally dodged
# `scripts/validation/archived/block_inappropriate_mocks.py`, which was wired live in
# .pre-commit-config.yaml and matched the pattern anywhere on a line, including inside
# a string. That hook was deleted in #793 (it detected 1 of 225 prohibited-target
# mocks app-wide), so the dodge is no longer required -- kept because the enforcer's
# own containment logic is what these tests exercise, and the snippets handed to it
# are byte-identical either way.
_PATCH_DB = 'patch("frappe.db.get_value")'


def _findings(src: str, name: str = "test_snippet.py"):
    """Return the enforcer's structured findings for a snippet."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / name
        p.write_text(src)
        enforcer = tqe.TestQualityEnforcer()
        enforcer.validate_file(str(p))
        return list(enforcer.findings)


def _kinds(src: str, name: str = "test_snippet.py"):
    return sorted(f.kind for f in _findings(src, name))


def _qualnames(src: str, name: str = "test_snippet.py"):
    return sorted(f.qualname for f in _findings(src, name))


# --------------------------------------------------------------------------
# Detection must survive the false-positive fixes
# --------------------------------------------------------------------------


class DetectionSurvivesTest(unittest.TestCase):
    def test_set_user_administrator_is_still_detected(self):
        """The single most important control in this file.

        This pattern REQUIRES the quotes:
            r"frappe\\.set_user\\s*\\(\\s*['\\\"]Administrator['\\\"]"
        so it only ever matches text that ``tokenize`` sees inside a STRING token.
        A string-blanking false-positive fix silences it -- along with all 9
        database_mock_targets and all 3 never_mock_targets -- and every other test in
        this file still passes.
        """
        src = (
            "class TestThing:\n"
            "    def test_it(self):\n"
            "        frappe.set_user('Administrator')\n"
        )
        self.assertEqual(["PERMISSION BYPASS"], _kinds(src))

    def test_database_mock_is_still_detected(self):
        src = (
            "class TestThing:\n"
            "    def test_it(self):\n"
            f"        with {_PATCH_DB}:\n"
            "            pass\n"
        )
        self.assertIn("DATABASE MOCK", _kinds(src))

    def test_bypass_on_a_line_that_also_carries_a_comment_is_detected(self):
        """A trailing comment must not launder the line."""
        src = (
            "class TestThing:\n"
            "    def test_it(self):\n"
            "        doc.insert(ignore_permissions=True)  # arrangement: foreign donor\n"
        )
        self.assertEqual(["PERMISSION BYPASS"], _kinds(src))

    def test_bypass_on_a_line_that_also_carries_a_string_is_detected(self):
        src = (
            "class TestThing:\n"
            "    def test_it(self):\n"
            '        doc.insert(ignore_permissions=True, comment="why")\n'
        )
        self.assertEqual(["PERMISSION BYPASS"], _kinds(src))


# --------------------------------------------------------------------------
# False positives
# --------------------------------------------------------------------------


class FalsePositiveTest(unittest.TestCase):
    def test_a_whole_line_comment_is_not_a_finding(self):
        """Two of the four checks skipped only docstrings, not comments."""
        src = (
            "class TestThing:\n"
            "    def test_it(self):\n"
            f"        # This replaces multiple @{_PATCH_DB} with real queries\n"
            "        pass\n"
        )
        self.assertEqual([], _kinds(src))

    def test_a_single_line_string_literal_is_not_a_finding(self):
        """``_docstring_line_numbers`` only ever tracked triple-quoted blocks."""
        src = (
            "class TestThing:\n"
            "    def test_it(self):\n"
            '        banned = ["NO ignore_permissions=True"]\n'
        )
        self.assertEqual([], _kinds(src))

    def test_a_docstring_is_not_a_finding(self):
        src = (
            "class TestThing:\n"
            "    def test_it(self):\n"
            '        """Do not write doc.insert(ignore_permissions=True) here."""\n'
        )
        self.assertEqual([], _kinds(src))


# --------------------------------------------------------------------------
# Duplicates
# --------------------------------------------------------------------------


class DuplicateTest(unittest.TestCase):
    def test_one_site_matched_by_subset_patterns_is_reported_once(self):
        """``.insert(ignore_permissions=True)`` matched 2 of 4 overlapping regexes.

        ``ignore_permissions\\s*=\\s*True`` is a strict superset of the
        ``.insert``/``.save``/``.delete`` variants, and the match loop had no
        ``break``.
        """
        src = (
            "class TestThing:\n"
            "    def test_it(self):\n"
            "        doc.insert(ignore_permissions=True)\n"
        )
        self.assertEqual(1, len(_findings(src)))

    def test_a_line_matched_by_two_different_checks_is_reported_twice(self):
        """Collapsing per line would silently drop one of two real findings.

        A Tier 3 file mocking a `validate_*` target trips both the security-tier
        rule and the never-mock rule on the same line. This is not hypothetical:
        `verenigingen/tests/security/test_security_setup.py:651` is exactly this.
        The `break` that de-duplicates overlapping *permission* patterns must not
        be generalised into a per-line cap.

        The filename matters -- Tier 3 is what enables the security check.
        """
        src = (
            "class TestSecurity:\n"
            "    def test_it(self):\n"
            '        with patch("verenigingen.utils.validate_thing"):\n'
            "            pass\n"
        )
        self.assertEqual(
            ["BUSINESS LOGIC MOCK PROHIBITED", "MOCK"],
            _kinds(src, "test_permission_thing.py"),
        )


# --------------------------------------------------------------------------
# The baseline key
# --------------------------------------------------------------------------


class QualnameKeyTest(unittest.TestCase):
    def test_a_method_is_qualified_by_its_class(self):
        src = (
            "class TestThing:\n"
            "    def test_it(self):\n"
            "        frappe.set_user('Administrator')\n"
        )
        self.assertEqual(["TestThing.test_it"], _qualnames(src))

    def test_a_finding_on_a_decorator_belongs_to_the_function_it_decorates(self):
        """The backward ``def`` scan attributed decorators to the PREVIOUS function.

        Mock findings land on decorator lines by construction, so this was
        systematic, not an edge case.
        """
        src = (
            "class TestThing:\n"
            "    def helper(self):\n"
            "        pass\n"
            "\n"
            f"    @{_PATCH_DB}\n"
            "    def test_it(self, m):\n"
            "        pass\n"
        )
        self.assertEqual(["TestThing.test_it"], _qualnames(src))

    def test_module_level_code_is_not_attributed_to_the_last_function(self):
        """Otherwise adding any function above it silently changes the key.

        That is precisely the key-rot that dropping line numbers was meant to
        avoid.
        """
        src = (
            "class TestThing:\n"
            "    def test_it(self):\n"
            "        pass\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    frappe.set_user('Administrator')\n"
        )
        self.assertEqual(["<module>"], _qualnames(src))

    def test_a_nested_function_is_qualified_by_its_parent(self):
        """The bleed here manufactures a violation.

        ``_ensure_user`` is allowlisted; a nested ``_apply_role_profile`` is not, so
        a bypass written in the OUTER function was reported against the inner one.
        """
        src = (
            "class TestThing:\n"
            "    def _ensure_user(self):\n"
            "        def _apply_role_profile():\n"
            "            pass\n"
            "        frappe.set_user('Administrator')\n"
        )
        self.assertEqual([], _kinds(src))

    def test_an_async_function_is_keyed(self):
        src = (
            "class TestThing:\n"
            "    async def test_it(self):\n"
            "        frappe.set_user('Administrator')\n"
        )
        self.assertEqual(["TestThing.test_it"], _qualnames(src))


class PathKeyTest(unittest.TestCase):
    def test_the_key_path_is_repo_relative_however_the_file_was_passed(self):
        """``--update-baseline`` walked ``.`` and wrote ``./``-prefixed keys while
        pre-commit passed bare relative paths, so every key the hook computed was
        absent from the baseline."""
        repo_file = Path(tqe.REPO_ROOT) / "scripts" / "validation" / "test_quality_enforcer.py"
        self.assertEqual(
            "scripts/validation/test_quality_enforcer.py", tqe._rel(str(repo_file))
        )
        self.assertEqual(
            "scripts/validation/test_quality_enforcer.py",
            tqe._rel("./scripts/validation/test_quality_enforcer.py"),
        )


# --------------------------------------------------------------------------
# The ratchet itself
# --------------------------------------------------------------------------


class RatchetTest(unittest.TestCase):
    def test_a_violation_absent_from_the_baseline_fails(self):
        counts = {"a.py::T.test_it::PERMISSION BYPASS": 1}
        self.assertTrue(tqe.regressions(counts, {}))

    def test_a_violation_present_in_the_baseline_passes(self):
        key = "a.py::T.test_it::PERMISSION BYPASS"
        self.assertFalse(tqe.regressions({key: 1}, {key: 1}))

    def test_a_count_above_the_baseline_fails(self):
        key = "a.py::T.test_it::PERMISSION BYPASS"
        self.assertTrue(tqe.regressions({key: 2}, {key: 1}))

    def test_a_count_below_the_baseline_passes(self):
        """Fires upward only, so a partial pre-commit scan cannot produce a false
        'count decreased' verdict for files it never looked at."""
        key = "a.py::T.test_it::PERMISSION BYPASS"
        self.assertFalse(tqe.regressions({key: 1}, {key: 2}))

    def test_a_kind_swap_at_the_same_count_is_caught(self):
        """One mock removed and one bypass added leaves a kind-free count
        unchanged. The kind segment is what makes that visible."""
        base = {"a.py::T.test_it::DATABASE MOCK": 1}
        now = {"a.py::T.test_it::PERMISSION BYPASS": 1}
        self.assertTrue(tqe.regressions(now, base))


class ScanScopeTest(unittest.TestCase):
    def test_the_walk_prunes_worktrees_and_vendor_directories(self):
        """``--update-baseline`` walked '.' unpruned: 12,574 files against 1,398,
        the difference being agent worktrees under .claude/. A developer's
        regenerated baseline then differs from CI's, making the drift check
        unusable."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "verenigingen" / "tests").mkdir(parents=True)
            (root / "verenigingen" / "tests" / "test_real.py").write_text("x = 1\n")
            for pruned in (".claude", "node_modules", "__pycache__"):
                sub = root / pruned / "tests"
                sub.mkdir(parents=True)
                (sub / "test_copy.py").write_text("x = 1\n")

            found = sorted(Path(p).name for p in tqe.iter_test_files(str(root)))
            self.assertEqual(["test_real.py"], found)


class WholeTreeTotalsTest(unittest.TestCase):
    """The control that makes 'detection broke' visible.

    Every other test in this file is satisfied by an enforcer that finds NOTHING.
    That is not a theoretical worry: the first version of this change proposed
    blanking string contents before matching, which would have silenced 58 of 120
    findings while leaving all the false-positive tests green -- and a ratchet
    cannot notice, because a shrinking baseline is the direction it celebrates.

    These numbers are expected to DROP as the debt is paid. Update them
    deliberately, in the same commit as the fix that moved them, and never upward
    except when the enforcer's own rules change.
    """

    @classmethod
    def setUpClass(cls):
        enforcer = tqe.TestQualityEnforcer()
        enforcer.validate_files(sorted(tqe.iter_test_files(str(tqe.REPO_ROOT))))
        cls.findings = enforcer.findings

    def test_the_permission_bypass_family_is_still_detected(self):
        """`set_user("Administrator")` and friends require the quotes, so they match
        inside a STRING token by construction. If a false-positive fix ever
        suppresses matches that merely touch a string, this is what goes to zero."""
        hits = [
            f
            for f in self.findings
            if "set_user" in f.message and "Administrator" in f.message
        ]
        self.assertGreater(len(hits), 25, "the set_user family stopped being detected")

    def test_every_kind_is_still_detected(self):
        kinds = {f.kind for f in self.findings}
        self.assertEqual(
            {
                "PERMISSION BYPASS",
                "DATABASE MOCK",
                "BUSINESS LOGIC MOCK PROHIBITED",
                "MOCK",
            },
            kinds,
            "a whole check stopped producing findings",
        )

    def test_the_totals_are_what_the_baseline_was_generated_from(self):
        # Moved UPWARD by #793, which this docstring sanctions only when the
        # enforcer's own rules change -- they did. Three changes lifted it:
        #
        #   * mock targets are now resolved from the AST, so a Black-wrapped
        #     decorator, an f-string target and `patch.object` are all visible;
        #     none had a working rule before (patch.object never had one at all).
        #   * the database-mock targets are SUFFIX-anchored (with a left-hand
        #     `(?:^|\.)` guard), so the idiomatic module-qualified form
        #     patch("<module>.frappe.db.sql") is caught, not only a bare
        #     patch("frappe.db.sql").
        #   * the per-line dedup between the old line regexes and the AST pass was
        #     dropping a second prohibited target on the same line; there is now a
        #     single detector, so that cannot happen.
        #
        # 118 -> 201 findings, 107 -> 184 keys. 77 keys added, 0 removed, and
        # exactly ONE pre-existing key's count rose:
        # test_anbi_donation_summary_report.py::TestANBIDonationSummaryReport
        # .test_agreement_type_determination::DATABASE MOCK, 1 -> 2, because that
        # method holds both an already-caught `frappe.get_doc` and a
        # newly-caught module-qualified `frappe.db.sql`. An earlier revision of
        # this comment claimed no count rose; that was wrong, and measuring the
        # baselines key-by-key rather than line-by-line is what showed it.
        #
        # None of this is new debt -- it is debt that was always there and could
        # not be measured.
        self.assertEqual(201, len(self.findings), "finding count moved")
        self.assertEqual(184, len(tqe.counts_of(self.findings)), "key count moved")

    def test_findings_are_keyed_to_a_named_scope(self):
        """A key of '<module>' is legitimate but should stay rare; a flood of them
        means the AST scope map stopped resolving."""
        unnamed = [f for f in self.findings if f.qualname == "<module>"]
        self.assertLess(len(unnamed), 5)



# --------------------------------------------------------------------------
# #793: mock targets the LINE rules cannot see
# --------------------------------------------------------------------------


class StructuralMockDetectionTest(unittest.TestCase):
    """Every mock rule here is a line regex needing `patch(` and the quoted target
    on ONE line. Black wraps a long decorator onto two, and `patch.object` never
    carried a rule at all. Measured before the fix: 225 mocks in the app name a
    prohibited target, the line rules saw 167, and the deleted
    block_inappropriate_mocks.py -- the hook nominally responsible -- reported 1.
    """

    def test_a_wrapped_decorator_is_detected(self):
        src = (
            "from unittest.mock import patch\n"
            "@patch(\n"
            '    "frappe.db.get_value"\n'
            ")\n"
            "def test_x(m):\n"
            "    pass\n"
        )
        self.assertIn("DATABASE MOCK", _kinds(src))

    def test_a_module_qualified_target_is_detected(self):
        """The idiomatic form: patch where the name is looked up.

        The line patterns demand a quote immediately before `frappe`, so they only
        ever matched a bare patch("frappe.db.sql"). This shape was the one finding
        the deleted hook still reported, and anchoring the AST targets to the START
        of the string would have dropped it along with the hook.
        """
        src = (
            "from unittest.mock import patch\n"
            "@patch(\n"
            '    "verenigingen.some.module.frappe.db.sql"\n'
            ")\n"
            "def test_x(m):\n"
            "    pass\n"
        )
        self.assertIn("DATABASE MOCK", _kinds(src))

    def test_patch_object_is_detected(self):
        src = (
            "from unittest.mock import patch\n"
            "import frappe\n"
            "def test_x():\n"
            '    with patch.object(frappe, "new_doc"):\n'
            "        pass\n"
        )
        self.assertIn("DATABASE MOCK", _kinds(src))

    def test_a_lookalike_name_is_not_detected(self):
        """Suffix anchoring must not degrade into a substring match.

        The first case passes on a trailing suffix alone and so proves little; the
        other two end exactly at the method boundary and are what the left-hand
        `(?:^|\\.)` guard exists for. Without it, any identifier merely ENDING in
        "frappe" matched -- `wrap_frappe.get_doc` and `notfrappe.db.count` both did.
        """
        for target in (
            "some_vendor.client.my_frappe.get_doc_helper",
            "foo.wrap_frappe.get_doc",
            "notfrappe.db.count",
        ):
            src = (
                "from unittest.mock import patch\n"
                "@patch(\n"
                '    "' + target + '"\n'
                ")\n"
                "def test_x(m):\n"
                "    pass\n"
            )
            with self.subTest(target=target):
                self.assertNotIn("DATABASE MOCK", _kinds(src))

    def test_two_prohibited_targets_on_one_line_are_both_reported(self):
        """The defect that made keeping two detectors untenable.

        The old line loop reported only the FIRST pattern matching a line and then
        suppressed the AST pass for that whole line, so this recorded one finding
        and silently dropped the other. Chaining several patches per `with` is a
        common idiom here.
        """
        src = (
            "from unittest.mock import patch\n"
            "def test_x():\n"
            '    with patch("frappe.get_doc") as a, patch("frappe.get_all") as b:\n'
            "        pass\n"
        )
        self.assertEqual(["DATABASE MOCK", "DATABASE MOCK"], _kinds(src))

    def test_an_fstring_target_is_detected(self):
        """Live blind spot before the fix: two files patch f-string targets.

        Only the literal segments are resolvable, so f"{MODULE}.frappe.get_doc"
        yields ".frappe.get_doc" -- which is why the rules must stay SUFFIX-anchored.
        """
        src = (
            "from unittest.mock import patch\n"
            'M = "some.module"\n'
            '@patch(f"{M}.frappe.get_doc")\n'
            "def test_x(m):\n"
            "    pass\n"
        )
        self.assertIn("DATABASE MOCK", _kinds(src))

    def test_an_fstring_ending_in_a_placeholder_is_not_detected(self):
        """The false positive the literal-segment approach would otherwise cause.

        Every rule here is suffix-anchored, so f"frappe.get_doc{suffix}" would
        resolve to exactly "frappe.get_doc" and be flagged -- while at runtime the
        target may be frappe.get_doc_helper. Refusing to resolve a placeholder-
        terminated f-string is a false negative; resolving it fails an innocent PR.
        """
        src = (
            "from unittest.mock import patch\n"
            'suffix = "_helper"\n'
            '@patch(f"frappe.get_doc{suffix}")\n'
            "def test_x(m):\n"
            "    pass\n"
        )
        self.assertEqual([], _kinds(src))

    def test_an_aliased_patch_import_is_detected(self):
        src = (
            "from unittest.mock import patch as p\n"
            "@p(\n"
            '    "frappe.db.sql"\n'
            ")\n"
            "def test_x(m):\n"
            "    pass\n"
        )
        self.assertIn("DATABASE MOCK", _kinds(src))

    def test_the_known_gaps_are_still_gaps(self):
        """Pins what is NOT detected, so the limitation is visible rather than assumed.

        A target built from a variable is not statically knowable; `patch.multiple`
        takes its attributes as kwargs and `patch.dict` patches a mapping, so
        neither is a target-and-attribute patch. If any of these ever starts being
        detected, this test should be deleted in the same commit -- it exists to
        stop the docstring's disclosure list drifting away from the behaviour.
        """
        variable_target = (
            "from unittest.mock import patch\n"
            'TARGET = "frappe.get_doc"\n'
            "@patch(TARGET)\n"
            "def test_x(m):\n"
            "    pass\n"
        )
        multiple = (
            "from unittest.mock import patch\n"
            "def test_x():\n"
            '    with patch.multiple("frappe", get_doc=1):\n'
            "        pass\n"
        )
        concatenated = (
            "from unittest.mock import patch\n"
            '@patch("frappe." + "get_doc")\n'
            "def test_x(m):\n"
            "    pass\n"
        )
        self.assertEqual([], _kinds(variable_target))
        self.assertEqual([], _kinds(multiple))
        self.assertEqual([], _kinds(concatenated))

    def test_an_external_service_mock_is_not_detected(self):
        src = (
            "from unittest.mock import patch\n"
            "@patch(\n"
            '    "frappe.sendmail"\n'
            ")\n"
            "def test_x(m):\n"
            "    pass\n"
        )
        self.assertEqual([], _kinds(src))

    def test_a_single_line_target_is_reported_once(self):
        """One mock, one finding.

        This used to guard a per-line dedup between two detectors. There is now a
        single detector, so double counting is impossible by construction -- kept
        because a future second mechanism would break exactly here.
        """
        src = (
            "from unittest.mock import patch\n"
            '@patch("frappe.db.get_value")\n'
            "def test_x(m):\n"
            "    pass\n"
        )
        self.assertEqual(["DATABASE MOCK"], _kinds(src))


class BusinessWorkflowMockTierTest(unittest.TestCase):
    """The rules absorbed from the deleted hook are Tier 2+ only.

    Putting them in never_mock_targets (all tiers) was measured to flag 9
    legitimate mocks across TWO unit tests -- 7 in
    test_suspension_member_mixin_unit.py and 2 in
    test_termination_reporting_boundaries.py -- a policy change disguised as a
    detection fix. The hook they came from skipped Tier 1 outright.
    """

    SRC = (
        "from unittest.mock import patch\n"
        "@patch(\n"
        '    "verenigingen.utils.termination_integration.suspend_member_safe"\n'
        ")\n"
        "def test_x(m):\n"
        "    pass\n"
    )

    def test_flagged_in_an_integration_test(self):
        self.assertIn("BUSINESS WORKFLOW MOCK", _kinds(self.SRC, "test_thing.py"))

    def test_not_flagged_in_a_unit_test(self):
        self.assertNotIn(
            "BUSINESS WORKFLOW MOCK", _kinds(self.SRC, "test_thing_unit.py")
        )

if __name__ == "__main__":
    unittest.main()
