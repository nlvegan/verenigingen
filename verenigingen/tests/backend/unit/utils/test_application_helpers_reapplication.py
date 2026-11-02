# -*- coding: utf-8 -*-
"""
Unit tests for the helpers the reapplication path shares with materialise_member().

update_member_from_reapplication() (and its seven characterization tests, which lived in this
module) was removed in #1765: approval updates an existing Member through materialise_member(),
covered by test_application_record_approval and test_reapplication_dues_template. The helpers
below are still called by materialise_member, so their edge cases stay pinned here.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.member.approval.application_helpers import (
    _append_chapter_notes,
    _apply_custom_contribution_fee,
    _sanitize_application_names,
)

# ---------------------------------------------------------------------------
# Helper unit tests (review feedback: edge cases for extracted helpers)
# ---------------------------------------------------------------------------


class TestSanitizeApplicationNames(FrappeTestCase):
    """Unit tests for _sanitize_application_names helper."""

    def test_all_fields_present(self):
        data = {
            "first_name": "Marie",
            "middle_name": "Anne",
            "tussenvoegsel": "van",
            "last_name": "Berg",
        }
        result = _sanitize_application_names(data)
        self.assertEqual(result, ("Marie", "Anne", "van", "Berg"))

    def test_missing_fields_return_empty_strings(self):
        result = _sanitize_application_names({})
        self.assertEqual(result, ("", "", "", ""))

    def test_whitespace_stripped(self):
        data = {"first_name": "  Jan  ", "last_name": "  Bakker  "}
        first, middle, tussen, last = _sanitize_application_names(data)
        self.assertEqual(first, "Jan")
        self.assertEqual(last, "Bakker")
        self.assertEqual(middle, "")
        self.assertEqual(tussen, "")


class TestApplyCustomContributionFee(FrappeTestCase):
    """Unit tests for _apply_custom_contribution_fee helper edge cases."""

    def _make_member(self):
        """Create an unsaved member doc for testing."""
        return frappe.get_doc({"doctype": "Member", "first_name": "Test", "last_name": "Fee"})

    def test_no_custom_fee_fields_is_noop(self):
        member = self._make_member()
        _apply_custom_contribution_fee(member, {}, context_label="test")
        self.assertFalse(getattr(member, "dues_rate", None))

    def test_malformed_string_treated_as_zero(self):
        """Non-numeric strings like '25,50' or 'abc' are logged and treated as 0."""
        member = self._make_member()
        _apply_custom_contribution_fee(
            member, {"custom_contribution_fee": "abc"}, context_label="test"
        )
        # No override should be set — invalid amount treated as 0
        self.assertFalse(getattr(member, "fee_override_reason", None))

    def test_comma_decimal_treated_as_zero(self):
        """European-style '25,50' is not valid Python float, treated as 0."""
        member = self._make_member()
        _apply_custom_contribution_fee(
            member, {"custom_contribution_fee": "25,50"}, context_label="test"
        )
        self.assertFalse(getattr(member, "fee_override_reason", None))

    def test_negative_amount_not_applied(self):
        member = self._make_member()
        _apply_custom_contribution_fee(
            member, {"custom_contribution_fee": "-10"}, context_label="test"
        )
        self.assertFalse(getattr(member, "fee_override_reason", None))

    def test_valid_amount_sets_fields(self):
        member = self._make_member()
        _apply_custom_contribution_fee(
            member, {"custom_contribution_fee": "42.00"}, context_label="application"
        )
        self.assertEqual(member.dues_rate, 42.0)
        self.assertIn("application", member.fee_override_reason)
        self.assertEqual(member.application_custom_fee, 42.0)

    def test_context_label_in_reason(self):
        member = self._make_member()
        _apply_custom_contribution_fee(
            member, {"custom_contribution_fee": "10"}, context_label="reapplication"
        )
        self.assertIn("reapplication", member.fee_override_reason)


class TestAppendChapterNotes(FrappeTestCase):
    """Unit tests for _append_chapter_notes helper."""

    def _make_member(self, notes=""):
        member = frappe.get_doc({"doctype": "Member", "first_name": "Test", "last_name": "Notes"})
        member.notes = notes
        return member

    def test_none_chapter_is_noop(self):
        member = self._make_member(notes="existing")
        _append_chapter_notes(member, None)
        self.assertEqual(member.notes, "existing")

    def test_empty_string_chapter_is_noop(self):
        member = self._make_member()
        _append_chapter_notes(member, "")
        self.assertFalse(member.notes)

    def test_nonexistent_chapter_uses_raw_name(self):
        """When Chapter doc doesn't exist, the raw chapter ID is used as display."""
        member = self._make_member()
        _append_chapter_notes(member, "NONEXISTENT-CHAPTER-XYZ", label="Test Label")
        self.assertIn("Test Label: NONEXISTENT-CHAPTER-XYZ", member.notes)

    def test_appends_to_existing_notes(self):
        member = self._make_member(notes="Previous note")
        _append_chapter_notes(member, "NONEXISTENT-CHAPTER-XYZ", label="Selected Chapter")
        self.assertTrue(member.notes.startswith("Previous note"))
        self.assertIn("Selected Chapter: NONEXISTENT-CHAPTER-XYZ", member.notes)

    def test_real_chapter_uses_region(self):
        chapters = frappe.get_all("Chapter", limit=1)
        if not chapters:
            self.skipTest("No Chapter exists")

        member = self._make_member()
        _append_chapter_notes(member, chapters[0]["name"], label="My Label")
        self.assertIn("My Label:", member.notes)
        self.assertIn(chapters[0]["name"], member.notes)
