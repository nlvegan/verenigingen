# -*- coding: utf-8 -*-
"""
Characterization tests for update_member_from_reapplication().

These capture current behavior as a safety net for refactoring.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from verenigingen.utils.application_helpers import (
    _append_chapter_notes,
    _apply_custom_contribution_fee,
    _sanitize_application_names,
    create_member_from_application,
    update_member_from_reapplication,
)


def _create_test_member(data=None, application_id=None):
    # NOTE: Intentionally local — uses create_member_from_application() workflow
    """Helper: create a member via the real function for test setup."""
    if data is None:
        data = {
            "first_name": "Original",
            "last_name": "Member",
            "email": f"test-reapp-{frappe.generate_hash(length=8)}@example.com",
            "birth_date": "1990-01-01",
            "selected_membership_type": frappe.get_all("Membership Type", limit=1)[0]["name"],
        }
    if application_id is None:
        application_id = f"APP-TEST-{frappe.generate_hash(length=8)}"
    return create_member_from_application(data, application_id)


def _ensure_system_user_has_staff_role():
    """Ensure the background service user has the Verenigingen Staff role.

    The fee override permission check requires this role on the user
    that secure_user_context switches to during member.save().
    Returns True if the role was added (needs cleanup), False otherwise.

    Uses direct SQL to avoid triggering User.on_update hooks which
    enqueue background jobs (can fail with QueueOverloaded).
    """
    from verenigingen.utils.secure_operations import get_system_user_for_operation

    system_user = get_system_user_for_operation("member_reapplication_update")
    if not frappe.db.exists("Has Role", {"parent": system_user, "role": "Verenigingen Staff"}):
        frappe.db.sql(
            """INSERT INTO `tabHas Role` (name, parent, parenttype, parentfield, role)
            VALUES (%s, %s, 'User', 'roles', 'Verenigingen Staff')""",
            (frappe.generate_hash(length=10), system_user),
        )
        frappe.db.commit()
        # Clear role cache so frappe.get_roles() picks up the new role
        frappe.clear_cache(user=system_user)
        return True
    return False


def _remove_system_user_staff_role():
    """Remove the Verenigingen Staff role from the background service user."""
    from verenigingen.utils.secure_operations import get_system_user_for_operation

    system_user = get_system_user_for_operation("member_reapplication_update")
    frappe.db.sql(
        "DELETE FROM `tabHas Role` WHERE parent=%s AND role='Verenigingen Staff'",
        system_user,
    )
    frappe.db.commit()
    frappe.clear_cache(user=system_user)


class TestUpdateMemberFromReapplication(FrappeTestCase):
    """Characterize update_member_from_reapplication() behavior."""

    def setUp(self):
        self.member = _create_test_member()
        self.member_name = self.member.name

    def test_basic_field_update(self):
        """Core fields are updated from reapplication data."""
        data = {
            "first_name": "Updated",
            "last_name": "Name",
            "email": "updated@example.com",
            "birth_date": "1985-06-15",
            "contact_number": "+31612345678",
            "pronouns": "they/them",
        }
        app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
        result = update_member_from_reapplication(self.member_name, data, app_id)

        self.assertEqual(result.first_name, "Updated")
        self.assertEqual(result.last_name, "Name")
        self.assertEqual(result.status, "Pending")
        self.assertEqual(result.application_id, app_id)

    def test_name_sanitization(self):
        """Names with leading/trailing spaces are sanitized."""
        data = {"first_name": "  Jan  ", "last_name": "  de Vries  "}
        app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
        result = update_member_from_reapplication(self.member_name, data, app_id)

        self.assertEqual(result.first_name, "Jan")
        self.assertEqual(result.last_name, "de Vries")

    def test_custom_contribution_fee_applied(self):
        """Custom amount sets fee override fields.

        The background service user used by secure_user_context needs
        the Verenigingen Staff role to pass fee override permission checks.
        """
        mt = frappe.get_all("Membership Type", limit=1)
        if not mt:
            self.skipTest("No Membership Type exists")

        # Grant required role to background service user so fee override save succeeds
        role_added = _ensure_system_user_has_staff_role()

        try:
            data = {
                "first_name": "Fee",
                "last_name": "Test",
                "custom_contribution_fee": "25.50",
                "uses_custom_amount": True,
                "selected_membership_type": mt[0]["name"],
            }
            app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
            result = update_member_from_reapplication(self.member_name, data, app_id)

            self.assertEqual(result.dues_rate, 25.50)
            self.assertIn("reapplication", result.fee_override_reason)
            self.assertEqual(result.fee_override_date, today())
            self.assertEqual(result.application_custom_fee, 25.50)
        finally:
            if role_added:
                _remove_system_user_staff_role()

    def test_chapter_info_in_notes(self):
        """Selected chapter is appended to notes."""
        chapters = frappe.get_all("Chapter", limit=1)
        if not chapters:
            self.skipTest("No Chapter exists")

        data = {
            "first_name": "Chapter",
            "last_name": "Test",
            "selected_chapter": chapters[0]["name"],
        }
        app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
        result = update_member_from_reapplication(self.member_name, data, app_id)

        self.assertIn("Selected Chapter (Reapplication)", result.notes)

    def test_reapplication_timestamp_in_notes(self):
        """Reapplication timestamp note is always added."""
        data = {"first_name": "Time", "last_name": "Test"}
        app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
        result = update_member_from_reapplication(self.member_name, data, app_id)

        self.assertIn("Reapplication submitted:", result.notes)

    def test_zero_custom_amount_not_applied(self):
        """Custom fee of 0 does not set override fields."""
        data = {
            "first_name": "Zero",
            "last_name": "Fee",
            "custom_contribution_fee": "0",
            "uses_custom_amount": True,
        }
        app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
        result = update_member_from_reapplication(self.member_name, data, app_id)

        # dues_rate should not be set to 0 (it stays at whatever default was)
        self.assertFalse(result.fee_override_reason)

    def test_volunteer_skills_transferred(self):
        """Volunteer skills from data are set on member."""
        data = {
            "first_name": "Vol",
            "last_name": "Test",
            "volunteer_skills": ["cooking", "driving"],
        }
        app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
        result = update_member_from_reapplication(self.member_name, data, app_id)

        self.assertEqual(result.volunteer_skills, ["cooking", "driving"])


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
