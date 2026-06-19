# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""Integration tests for the Expulsion Report Entry controller.

These tests build real Member / Chapter documents and exercise the controller's
validation branches, the whitelisted reversal flow, and the module-level
reporting helpers (statistics, governance report, member history). They were
written to surface real production bugs (see test docstrings) and assert real
state changes / return values rather than merely exercising code paths.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry import (
    generate_expulsion_governance_report,
    get_expulsion_statistics,
    get_member_expulsion_history,
    reverse_expulsion_entry,
)


class TestExpulsionReportEntry(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Expulsion", last_name="Subject", email="expulsion.subject@test.invalid"
        )

    # ------------------------------------------------------------------ helpers
    def _make_expulsion_entry(self, **overrides):
        """Create and insert a real Expulsion Report Entry (privileged setup)."""
        defaults = {
            "doctype": "Expulsion Report Entry",
            "member_name": self.member.full_name,
            "member_id": self.member.name,
            "expulsion_date": today(),
            "expulsion_type": "Policy Violation",
            "status": "Active",
            "initiated_by": "Administrator",
            "approved_by": "Administrator",
            "documentation": "<p>Documented reason for expulsion.</p>",
        }
        defaults.update(overrides)
        doc = frappe.get_doc(defaults)
        doc.insert()
        self.track_doc("Expulsion Report Entry", doc.name)
        return doc

    def _make_chapter_with_member(self, member_name):
        """Create a chapter and enroll the member in it (privileged setup)."""
        chapter = self.create_test_chapter()
        chapter.append(
            "members",
            {"member": member_name, "enabled": 1, "chapter_join_date": today()},
        )
        chapter.save()
        return chapter

    # ------------------------------------------------------------ validate()
    def test_validate_rejects_nonexistent_member(self):
        """A non-existent member_id must be rejected at validate()."""
        doc = frappe.get_doc(
            {
                "doctype": "Expulsion Report Entry",
                "member_name": "Ghost Member",
                "member_id": "NON-EXISTENT-MEMBER-XYZ",
                "expulsion_date": today(),
                "expulsion_type": "Policy Violation",
                "status": "Active",
                "initiated_by": "Administrator",
                "approved_by": "Administrator",
                "documentation": "<p>doc</p>",
            }
        )
        with self.assertRaises(frappe.ValidationError):
            doc.insert()

    def test_validate_corrects_member_name_mismatch(self):
        """validate_member_details() overwrites a stale member_name."""
        doc = self._make_expulsion_entry(member_name="Wrong Stale Name")
        self.assertEqual(doc.member_name, self.member.full_name)

    def test_validate_rejects_future_expulsion_date(self):
        """An expulsion date in the future must be rejected."""
        doc = frappe.get_doc(
            {
                "doctype": "Expulsion Report Entry",
                "member_name": self.member.full_name,
                "member_id": self.member.name,
                "expulsion_date": add_days(today(), 5),
                "expulsion_type": "Policy Violation",
                "status": "Active",
                "initiated_by": "Administrator",
                "approved_by": "Administrator",
                "documentation": "<p>doc</p>",
            }
        )
        with self.assertRaises(frappe.ValidationError):
            doc.insert()

    def test_validate_rejects_reversal_before_expulsion(self):
        """A reversal date earlier than the expulsion date must be rejected."""
        doc = frappe.get_doc(
            {
                "doctype": "Expulsion Report Entry",
                "member_name": self.member.full_name,
                "member_id": self.member.name,
                "expulsion_date": today(),
                "reversal_date": add_days(today(), -3),
                "expulsion_type": "Policy Violation",
                "status": "Active",
                "initiated_by": "Administrator",
                "approved_by": "Administrator",
                "documentation": "<p>doc</p>",
            }
        )
        with self.assertRaises(frappe.ValidationError):
            doc.insert()

    # ------------------------------------------------- set_chapter_from_member
    def test_chapter_autoset_from_member_membership(self):
        """When chapter_involved is blank it is derived from the member's chapter."""
        chapter = self._make_chapter_with_member(self.member.name)
        # The derivation orders by chapter_join_date desc; assert against the set
        # of chapters the member is actually enrolled in so the test is robust to
        # any pre-existing enrollment, while still proving auto-derivation works.
        enrolled = {
            row.parent
            for row in frappe.get_all(
                "Chapter Member",
                filters={"member": self.member.name, "enabled": 1},
                fields=["parent"],
            )
        }
        self.assertIn(chapter.name, enrolled)
        doc = self._make_expulsion_entry()
        self.assertTrue(doc.chapter_involved)
        self.assertIn(doc.chapter_involved, enrolled)

    def test_explicit_chapter_is_not_overwritten(self):
        """An explicitly provided chapter is preserved (no auto-derivation)."""
        # Enroll the member in one chapter, but explicitly set a different one.
        self._make_chapter_with_member(self.member.name)
        explicit_chapter = self.create_test_chapter()
        doc = self._make_expulsion_entry(chapter_involved=explicit_chapter.name)
        self.assertEqual(doc.chapter_involved, explicit_chapter.name)

    # ------------------------------------------ before_save / appeals guard
    def test_save_existing_record_does_not_crash_without_appeals_doctype(self):
        """REGRESSION: before_save() queried the optional, unshipped
        'Termination Appeals Process' doctype unconditionally, raising
        DoesNotExistError on every save of an existing record. The controller
        must now guard the lookup and save cleanly."""
        doc = self._make_expulsion_entry()
        doc.notes = "Updated note triggering a re-save"
        doc.save()  # must not raise
        doc.reload()
        self.assertEqual(doc.notes, "Updated note triggering a re-save")

    # ------------------------------------------------------ reverse_expulsion
    def test_reverse_expulsion_sets_state(self):
        """reverse_expulsion() flips status, records date/reason and returns True."""
        doc = self._make_expulsion_entry()
        result = doc.reverse_expulsion("Procedural error discovered")
        self.assertTrue(result)
        doc.reload()
        self.assertEqual(doc.status, "Reversed")
        self.assertEqual(doc.reversal_reason, "Procedural error discovered")
        self.assertEqual(str(doc.reversal_date), str(today()))
        self.assertEqual(doc.under_appeal, 0)

    def test_reverse_expulsion_twice_is_blocked(self):
        """Reversing an already-reversed expulsion must be rejected."""
        doc = self._make_expulsion_entry()
        doc.reverse_expulsion("First reversal")
        doc.reload()
        with self.assertRaises(frappe.ValidationError):
            doc.reverse_expulsion("Second reversal attempt")

    def test_reverse_expulsion_entry_module_wrapper(self):
        """The module-level wrapper reverses by name and returns True."""
        doc = self._make_expulsion_entry()
        result = reverse_expulsion_entry(doc.name, "Wrapper reversal reason")
        self.assertTrue(result)
        reloaded = frappe.get_doc("Expulsion Report Entry", doc.name)
        self.assertEqual(reloaded.status, "Reversed")
        self.assertEqual(reloaded.reversal_reason, "Wrapper reversal reason")

    # -------------------------------------------------- get_expulsion_statistics
    def test_statistics_no_filters_counts_entries(self):
        """REGRESSION: get_expulsion_statistics() crashed with no filters because
        the chapter-breakdown query left a dangling 'AND' (no WHERE) and the
        monthly-trend query was a plain string with an un-interpolated
        placeholder. It must now run and count real entries."""
        chapter = self._make_chapter_with_member(self.member.name)
        self._make_expulsion_entry(chapter_involved=chapter.name)

        stats = get_expulsion_statistics()
        self.assertIn("summary", stats)
        self.assertIn("chapter_breakdown", stats)
        self.assertIn("monthly_trend", stats)
        self.assertGreaterEqual(stats["summary"]["total_expulsions"], 1)
        self.assertGreaterEqual(stats["summary"]["active_expulsions"], 1)
        # Our entry's chapter should appear in the breakdown.
        breakdown_chapters = {row["chapter_involved"] for row in stats["chapter_breakdown"]}
        self.assertIn(chapter.name, breakdown_chapters)

    def test_statistics_with_filters(self):
        """Statistics honor expulsion_type / chapter filters and count reversed."""
        chapter = self._make_chapter_with_member(self.member.name)
        doc = self._make_expulsion_entry(chapter_involved=chapter.name, expulsion_type="Disciplinary Action")
        doc.reverse_expulsion("Reversed for filter test")

        stats = get_expulsion_statistics({"chapter": chapter.name, "expulsion_type": "Disciplinary Action"})
        self.assertEqual(stats["summary"]["total_expulsions"], 1)
        self.assertEqual(stats["summary"]["reversed_expulsions"], 1)
        self.assertEqual(stats["summary"]["disciplinary_actions"], 1)

    # ------------------------------------ generate_expulsion_governance_report
    def test_governance_report_runs_without_appeals_doctype(self):
        """REGRESSION: the governance report LEFT JOINed the unshipped
        'Termination Appeals Process' table and used a non-f-string for the
        missing-documentation query, raising ProgrammingError (1146)/syntax
        errors. The report must now generate cleanly and include our entry."""
        doc = self._make_expulsion_entry()
        report = generate_expulsion_governance_report()
        self.assertIn("summary", report)
        self.assertIn("expulsions", report)
        self.assertIn("compliance_issues", report)
        names = {row["name"] for row in report["expulsions"]}
        self.assertIn(doc.name, names)
        # With no appeals doctype, every row reports has_appeal == 'No'.
        for row in report["expulsions"]:
            self.assertEqual(row.get("has_appeal"), "No")

    def test_governance_report_excludes_appeal_fields_when_toggle_off(self):
        """include_appeals=0 strips appeals fields from the detailed rows."""
        self._make_expulsion_entry()
        report = generate_expulsion_governance_report(include_appeals=0)
        for row in report["expulsions"]:
            self.assertNotIn("has_appeal", row)
            self.assertNotIn("appeal_status", row)
            self.assertNotIn("under_appeal", row)

    def test_governance_report_with_chapter_filter(self):
        """A chapter filter restricts the detailed expulsion rows."""
        chapter = self._make_chapter_with_member(self.member.name)
        doc = self._make_expulsion_entry(chapter_involved=chapter.name)
        report = generate_expulsion_governance_report(chapter=chapter.name)
        names = {row["name"] for row in report["expulsions"]}
        self.assertIn(doc.name, names)
        for row in report["expulsions"]:
            self.assertEqual(row["chapter_involved"], chapter.name)

    # -------------------------------------------- get_member_expulsion_history
    def test_member_history_returns_entries_with_empty_appeals(self):
        """REGRESSION: member history enhanced each record by querying the
        unshipped appeals doctype, raising DoesNotExistError. It must now return
        the member's expulsions with an empty appeals list."""
        doc = self._make_expulsion_entry()
        history = get_member_expulsion_history(self.member.name)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["name"], doc.name)
        self.assertEqual(history[0]["status"], "Active")
        self.assertEqual(history[0]["appeals"], [])

    def test_member_history_empty_for_unknown_member(self):
        """A member with no expulsions yields an empty history."""
        other = self.create_test_member(
            first_name="Clean", last_name="Record", email="clean.record@test.invalid"
        )
        history = get_member_expulsion_history(other.name)
        self.assertEqual(history, [])
