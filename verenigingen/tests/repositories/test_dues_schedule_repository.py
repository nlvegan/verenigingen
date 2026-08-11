"""
Comprehensive tests for DuesScheduleRepository

Tests cover:
- Field name validation against DocType schema
- Query operations (get_active_schedule, get_all_schedules_for_member)
- Mutation operations (cancel_schedule, pause_schedule, update_next_invoice_date)
- Batch operations (get_schedules_for_members, cancel_multiple_schedules)
- Permission enforcement
- Error handling and edge cases
"""

import unittest

import frappe
from frappe.utils import add_months, today

from verenigingen.repositories import DuesScheduleRepository, ScheduleInfo, ScheduleStatus
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _ensure_named_membership_type(type_name):
    """Idempotently ensure a Membership Type with a specific literal `name`.

    The enhanced factory uniquifies names, so it cannot produce a record named
    exactly "Regular". These schedules reference the type by literal name, which
    is not seeded on fresh CI-mirror sites.
    """
    if frappe.db.exists("Membership Type", type_name):
        return type_name
    role_profile = frappe.db.get_value(
        "Role Profile", {"name": ["like", "%Member%"]}, "name"
    ) or frappe.db.get_value("Role Profile", {}, "name")
    doc = frappe.get_doc(
        {
            "doctype": "Membership Type",
            "membership_type_name": type_name,
            "is_active": 1,
            "role_profile": role_profile,
            "minimum_amount": 15.00,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc.name


class TestDuesScheduleRepository(EnhancedTestCase):
    """Test suite for DuesScheduleRepository"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.repo = DuesScheduleRepository()

        # Schedules below reference Membership Type "Regular" by its literal name;
        # ensure it exists on fresh CI-mirror sites where it is not seeded.
        _ensure_named_membership_type("Regular")

        # Create test member
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Repository",
            email="test.repository@example.com",
            birth_date="1990-01-01",
        )

    def _create_simple_schedule(self, member_name, amount=25.0, status="Active", **kwargs):
        """Helper to create a simple dues schedule bypassing complex validations"""
        schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "member": member_name,
                "schedule_name": kwargs.get(
                    "schedule_name", f"Test Schedule {frappe.generate_hash(length=8)}"
                ),
                "dues_rate": amount,
                "billing_frequency": kwargs.get("billing_frequency", "Monthly"),
                "membership_type": kwargs.get("membership_type", "Regular"),  # Required field
                "status": status,
                "next_invoice_date": kwargs.get("next_invoice_date", add_months(today(), 1))
                if status == "Active"
                else None,
                "contribution_mode": kwargs.get("contribution_mode", "Fixed"),
                "currency": kwargs.get("currency", "EUR"),  # Mandatory field
                "docstatus": 0,  # Draft status to ensure it's not filtered out
                **{
                    k: v
                    for k, v in kwargs.items()
                    if k
                    not in [
                        "schedule_name",
                        "billing_frequency",
                        "next_invoice_date",
                        "contribution_mode",
                        "membership_type",
                        "currency",
                        "docstatus",
                    ]
                },
            }
        )
        schedule.flags.ignore_validate = True  # Skip business rule validation for tests
        schedule.insert(ignore_permissions=True)
        frappe.db.commit()  # Commit immediately so other queries can see it
        return schedule

    def test_repository_initialization(self):
        """Test repository initializes correctly"""
        self.assertEqual(self.repo.doctype, "Membership Dues Schedule")
        self.assertIsNotNone(self.repo.BASIC_FIELDS)
        self.assertIsNotNone(self.repo.FULL_FIELDS)

    def test_field_names_match_doctype_schema(self):
        """CRITICAL: Verify all field names match DocType JSON schema"""
        # Read the actual DocType JSON to verify field names
        doctype_meta = frappe.get_meta("Membership Dues Schedule")
        valid_fields = {df.fieldname for df in doctype_meta.fields}

        # Check BASIC_FIELDS
        for field in self.repo.BASIC_FIELDS:
            if field != "name":  # 'name' is always valid
                self.assertIn(field, valid_fields, f"BASIC_FIELDS contains invalid field: {field}")

        # Check FULL_FIELDS
        for field in self.repo.FULL_FIELDS:
            if field != "name":
                self.assertIn(field, valid_fields, f"FULL_FIELDS contains invalid field: {field}")

    def test_schedule_info_dataclass_field_mapping(self):
        """Test ScheduleInfo dataclass correctly maps to DocType fields"""
        # Create a test schedule
        schedule_doc = self._create_simple_schedule(self.test_member.name, amount=25.0)

        # Retrieve via repository
        schedule_info = self.repo.get_active_schedule(self.test_member.name)

        # Verify mapping
        self.assertIsNotNone(schedule_info)
        self.assertEqual(schedule_info.member, self.test_member.name)
        self.assertEqual(schedule_info.dues_rate, 25.0)
        self.assertEqual(schedule_info.status, "Active")

    def test_get_active_schedule_for_member(self):
        """Test retrieving active schedule for a member"""
        # Create active schedule
        schedule_doc = self._create_simple_schedule(self.test_member.name, amount=30.0)

        # Retrieve via repository
        schedule = self.repo.get_active_schedule(self.test_member.name)

        self.assertIsNotNone(schedule)
        self.assertIsInstance(schedule, ScheduleInfo)
        self.assertEqual(schedule.member, self.test_member.name)
        self.assertEqual(schedule.status, "Active")

    def test_get_active_schedule_returns_none_when_no_active(self):
        """Test get_active_schedule returns None when no active schedule exists"""
        # Create cancelled schedule
        schedule_doc = self._create_simple_schedule(self.test_member.name, status="Cancelled")

        # Should return None
        schedule = self.repo.get_active_schedule(self.test_member.name)
        self.assertIsNone(schedule)

    def test_get_schedules_filters_by_status(self):
        """Test get_schedules_for_members only returns active schedules"""
        # Create schedules with different statuses
        self._create_simple_schedule(
            self.test_member.name, status="Active", schedule_name="Active Schedule 1"
        )
        self._create_simple_schedule(
            self.test_member.name, status="Active", schedule_name="Active Schedule 2"
        )
        self._create_simple_schedule(self.test_member.name, status="Paused", schedule_name="Paused Schedule")
        self._create_simple_schedule(
            self.test_member.name, status="Cancelled", schedule_name="Cancelled Schedule"
        )

        # Get schedules using batch method - should only return Active ones
        schedules = self.repo.get_schedules_for_members([self.test_member.name])

        # Should only get the 2 active schedules
        self.assertEqual(len(schedules), 2)
        for schedule in schedules:
            self.assertEqual(schedule.status, "Active")

    def test_cancel_schedule_updates_correct_fields(self):
        """Test cancel_schedule updates status and reason"""
        # Create active schedule
        schedule_doc = self._create_simple_schedule(self.test_member.name)

        # Cancel via repository
        reason = "Test cancellation"
        result = self.repo.cancel_schedule(schedule_doc.name, reason)

        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.schedule_name, schedule_doc.name)

        # Verify database state
        schedule_doc.reload()
        self.assertEqual(schedule_doc.status, "Cancelled")

        # Verify comment was added (repository uses comments for audit trail, not fields)
        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Membership Dues Schedule",
                "reference_name": schedule_doc.name,
                "comment_type": "Comment",
            },
            fields=["content"],
            order_by="creation desc",
            limit=1,
        )
        self.assertEqual(len(comments), 1)
        self.assertIn(reason, comments[0].content)

    def test_cancel_schedule_idempotency(self):
        """Test cancelling an already cancelled schedule is idempotent"""
        # Create and cancel schedule
        schedule_doc = self._create_simple_schedule(self.test_member.name)
        self.repo.cancel_schedule(schedule_doc.name, "Original reason")

        # Cancel again
        result = self.repo.cancel_schedule(schedule_doc.name, "New reason")

        # Should succeed with appropriate message
        self.assertTrue(result.success)
        self.assertIn("already", result.message.lower())

    def test_pause_schedule_updates_status(self):
        """Test pause_schedule changes status to Paused"""
        # Create active schedule
        schedule_doc = self._create_simple_schedule(self.test_member.name)

        # Pause via repository
        reason = "Test pause"
        result = self.repo.pause_schedule(schedule_doc.name, reason)

        # Verify result
        self.assertTrue(result.success)

        # Verify database state
        schedule_doc.reload()
        self.assertEqual(schedule_doc.status, "Paused")

        # Verify comment was added (repository uses comments for audit trail)
        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Membership Dues Schedule",
                "reference_name": schedule_doc.name,
                "comment_type": "Comment",
            },
            fields=["content"],
            order_by="creation desc",
            limit=1,
        )
        self.assertEqual(len(comments), 1)
        self.assertIn(reason, comments[0].content)

    def test_update_next_invoice_date(self):
        """Test updating next invoice date"""
        # Create active schedule
        schedule_doc = self._create_simple_schedule(self.test_member.name)

        # Update date via repository
        new_date = add_months(today(), 2)
        success = self.repo.update_next_invoice_date(schedule_doc.name, new_date)

        self.assertTrue(success)

        # Verify database state
        schedule_doc.reload()
        self.assertEqual(str(schedule_doc.next_invoice_date), str(new_date))

    def test_batch_get_schedules_for_members(self):
        """Test batch retrieval of schedules for multiple members"""
        # Create second test member
        member2 = self.create_test_member(
            first_name="Second",
            last_name="Member",
            email="second.member@example.com",
            birth_date="1992-01-01",
        )

        # Create schedules for both members
        self._create_simple_schedule(self.test_member.name)
        self._create_simple_schedule(member2.name)

        # Batch retrieve active schedules
        schedules = self.repo.get_schedules_for_members([self.test_member.name, member2.name])

        # Should get both active schedules in single query
        self.assertEqual(len(schedules), 2)
        member_names = {s.member for s in schedules}
        self.assertIn(self.test_member.name, member_names)
        self.assertIn(member2.name, member_names)
        # All should be active
        for schedule in schedules:
            self.assertEqual(schedule.status, "Active")

    def test_batch_cancel_multiple_schedules(self):
        """Test batch cancellation of multiple schedules"""
        # Create multiple schedules
        schedule_names = []
        for i in range(3):
            schedule_doc = self._create_simple_schedule(
                self.test_member.name, schedule_name=f"Batch Cancel {i}"
            )
            schedule_names.append(schedule_doc.name)

        # Batch cancel
        reason = "Batch cancellation test"
        results = self.repo.cancel_multiple_schedules(schedule_names, reason)

        # Verify all succeeded
        self.assertEqual(len(results), 3)
        for schedule_name, result in results.items():
            self.assertTrue(result.success)

            # Verify database state
            schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule_name)
            self.assertEqual(schedule_doc.status, "Cancelled")

    def test_permission_check_on_cancel(self):
        """Test cancel_schedule enforces permission checks"""
        # Create schedule as admin
        schedule_doc = self._create_simple_schedule(self.test_member.name)

        # Save current user
        current_user = frappe.session.user

        # Switch to Guest user (no permissions) to test permission validation
        frappe.set_user("Guest")

        try:
            result = self.repo.cancel_schedule(schedule_doc.name, "Should fail")
            # Should fail with permission error
            self.assertFalse(result.success)
            self.assertIn("permission", result.message.lower())
        finally:
            # Restore original user in teardown
            frappe.set_user(current_user)

    def test_empty_member_name_returns_none(self):
        """Test repository handles empty member name gracefully"""
        schedule = self.repo.get_active_schedule("")
        self.assertIsNone(schedule)

        schedule = self.repo.get_active_schedule(None)
        self.assertIsNone(schedule)

    def test_schedule_status_enum(self):
        """Test ScheduleStatus enum contains expected values"""
        self.assertEqual(ScheduleStatus.ACTIVE.value, "Active")
        self.assertEqual(ScheduleStatus.PAUSED.value, "Paused")
        self.assertEqual(ScheduleStatus.CANCELLED.value, "Cancelled")
        self.assertEqual(ScheduleStatus.COMPLETED.value, "Completed")


class TestUpdateScheduleRate(EnhancedTestCase):
    """Tests for DuesScheduleRepository.update_schedule_rate()."""

    def setUp(self):
        super().setUp()
        self.repo = DuesScheduleRepository()
        self.test_member = self.create_test_member(
            first_name="Rate",
            last_name="Update",
            email="rate.update@example.com",
            birth_date="1990-01-01",
        )
        # Create a dedicated Membership Type whose auto-created template rate is
        # aligned with its (absent) minimum. Grabbing an arbitrary existing type
        # can pick one whose minimum_amount (e.g. €25) exceeds its template rate
        # (€15), which makes schedule .save() throw "Template dues rate cannot be
        # less than membership type minimum".
        self._membership_type = self.create_test_membership_type(minimum_amount=5.0).name
        # Create a submitted Membership so schedule validate() passes
        self._membership = self._create_active_membership(self.test_member.name)
        # Deactivate any auto-created schedules from membership submission
        # so our test schedule is the only active one (avoids duplicate-schedule validation)
        self._deactivate_existing_schedules(self.test_member.name)

    def _create_active_membership(self, member_name):
        """Create a minimal submitted Membership to satisfy schedule validation."""
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member_name,
                "membership_type": self._membership_type,
                "start_date": today(),
                "status": "Active",
            }
        )
        membership.flags.ignore_validate = True
        membership.flags.ignore_links = True
        membership.flags.ignore_mandatory = True
        membership.insert(ignore_permissions=True)
        membership.submit()
        frappe.db.commit()
        return membership

    def _deactivate_existing_schedules(self, member_name):
        """Cancel any existing schedules so test schedule creation won't hit duplicate validation."""
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "is_template": 0, "status": "Active"},
            pluck="name",
        )
        for name in schedules:
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")
        if schedules:
            frappe.db.commit()

    def _create_simple_schedule(self, member_name, amount=25.0, status="Active", **kwargs):
        """Helper to create a simple dues schedule bypassing complex validations."""
        schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "member": member_name,
                "schedule_name": kwargs.get(
                    "schedule_name", f"Test Schedule {frappe.generate_hash(length=8)}"
                ),
                "dues_rate": amount,
                "billing_frequency": kwargs.get("billing_frequency", "Monthly"),
                "membership_type": kwargs.get("membership_type", self._membership_type),
                "currency": kwargs.get("currency", "EUR"),
                "status": status,
                "next_invoice_date": kwargs.get("next_invoice_date", add_months(today(), 1))
                if status == "Active"
                else None,
                "contribution_mode": kwargs.get("contribution_mode", "Fixed"),
                "docstatus": 0,
                **{
                    k: v
                    for k, v in kwargs.items()
                    if k
                    not in [
                        "schedule_name",
                        "billing_frequency",
                        "next_invoice_date",
                        "contribution_mode",
                        "membership_type",
                        "currency",
                        "docstatus",
                    ]
                },
            }
        )
        schedule.flags.ignore_validate = True
        schedule.flags.ignore_links = True
        schedule.flags.ignore_mandatory = True
        schedule.insert(ignore_permissions=True)
        frappe.db.commit()
        return schedule

    # ─── Happy path ─────────────────────────────────────────────────

    def test_updates_rate_successfully(self):
        """Rate is updated and result indicates success."""
        schedule = self._create_simple_schedule(self.test_member.name, amount=25.0)

        result = self.repo.update_schedule_rate(schedule.name, 30.0, "Annual increase")

        self.assertTrue(result.success)
        self.assertEqual(result.method_used, "update")
        self.assertIn("25.0", result.message)
        self.assertIn("30.0", result.message)

        schedule.reload()
        self.assertEqual(schedule.dues_rate, 30.0)

    def test_sets_custom_amount_fields(self):
        """uses_custom_amount and custom_amount_reason are set when mark_as_custom=True."""
        schedule = self._create_simple_schedule(self.test_member.name, amount=25.0)

        self.repo.update_schedule_rate(schedule.name, 30.0, "MijnRood sync")

        schedule.reload()
        self.assertEqual(schedule.uses_custom_amount, 1)
        self.assertIn("MijnRood sync", schedule.custom_amount_reason)
        self.assertIn("25.0", schedule.custom_amount_reason)
        self.assertIn("30.0", schedule.custom_amount_reason)

    def test_skips_custom_amount_when_disabled(self):
        """uses_custom_amount is NOT set when mark_as_custom=False."""
        schedule = self._create_simple_schedule(self.test_member.name, amount=25.0)

        self.repo.update_schedule_rate(schedule.name, 30.0, "Type change", mark_as_custom=False)

        schedule.reload()
        self.assertEqual(schedule.dues_rate, 30.0)
        self.assertFalse(schedule.uses_custom_amount)

    def test_appends_to_notes(self):
        """Notes field receives a timestamped entry."""
        schedule = self._create_simple_schedule(self.test_member.name, amount=25.0)
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "notes", "Existing note")
        frappe.db.commit()

        self.repo.update_schedule_rate(schedule.name, 35.0, "Price adjustment")

        schedule.reload()
        self.assertIn("Existing note", schedule.notes)
        self.assertIn(today(), schedule.notes)
        self.assertIn("25.0", schedule.notes)
        self.assertIn("35.0", schedule.notes)
        self.assertIn("Price adjustment", schedule.notes)

    def test_appends_custom_amount_reason_preserving_history(self):
        """custom_amount_reason is appended, not replaced, on successive updates."""
        schedule = self._create_simple_schedule(self.test_member.name, amount=25.0)
        frappe.db.set_value(
            "Membership Dues Schedule",
            schedule.name,
            {
                "custom_amount_reason": "First amendment: rate 20.0 → 25.0",
                "uses_custom_amount": 1,
            },
        )
        frappe.db.commit()

        self.repo.update_schedule_rate(schedule.name, 30.0, "Second amendment")

        schedule.reload()
        self.assertIn("First amendment", schedule.custom_amount_reason)
        self.assertIn("Second amendment", schedule.custom_amount_reason)

    def test_updates_paused_schedule(self):
        """Paused schedules can be updated (not just Active ones)."""
        schedule = self._create_simple_schedule(self.test_member.name, amount=25.0, status="Paused")

        result = self.repo.update_schedule_rate(schedule.name, 35.0, "Rate correction")

        self.assertTrue(result.success)
        self.assertEqual(result.method_used, "update")
        schedule.reload()
        self.assertEqual(schedule.dues_rate, 35.0)

    def test_updates_to_zero_rate_rejected_when_minimum_set(self):
        """Zero rate is rejected when membership type has a minimum amount."""
        schedule = self._create_simple_schedule(self.test_member.name, amount=30.0)

        result = self.repo.update_schedule_rate(schedule.name, 0.0, "Dues waived")

        # Validation rejects rates below the membership type minimum_amount
        self.assertFalse(result.success)
        self.assertIn("minimum", result.message.lower())

    # ─── Idempotency ────────────────────────────────────────────────

    def test_idempotent_when_rate_matches(self):
        """Returns no_change_needed when rate already equals new_rate."""
        schedule = self._create_simple_schedule(self.test_member.name, amount=25.0)

        result = self.repo.update_schedule_rate(schedule.name, 25.0, "No actual change")

        self.assertTrue(result.success)
        self.assertEqual(result.method_used, "no_change_needed")
        self.assertIn("already matches", result.message)

    def test_idempotent_does_not_modify_notes(self):
        """Notes are NOT appended when rate is unchanged."""
        schedule = self._create_simple_schedule(self.test_member.name, amount=25.0)
        original_notes = schedule.notes or ""

        self.repo.update_schedule_rate(schedule.name, 25.0, "Idempotent call")

        schedule.reload()
        self.assertEqual(schedule.notes or "", original_notes)

    # ─── Input validation ───────────────────────────────────────────

    def test_rejects_empty_schedule_name(self):
        """Returns failure for empty schedule_name."""
        result = self.repo.update_schedule_rate("", 25.0, "Test")

        self.assertFalse(result.success)
        self.assertEqual(result.method_used, "none")

    def test_rejects_none_schedule_name(self):
        """Returns failure for None schedule_name."""
        result = self.repo.update_schedule_rate(None, 25.0, "Test")

        self.assertFalse(result.success)

    def test_rejects_negative_rate(self):
        """Returns failure for negative dues rate."""
        schedule = self._create_simple_schedule(self.test_member.name, amount=25.0)

        result = self.repo.update_schedule_rate(schedule.name, -10.0, "Bad rate")

        self.assertFalse(result.success)
        self.assertIn("non-negative", result.message)

        # Verify rate was NOT changed
        schedule.reload()
        self.assertEqual(schedule.dues_rate, 25.0)

    # ─── Permission enforcement ─────────────────────────────────────

    def test_permission_denied_for_guest(self):
        """Returns failure when user lacks write permission."""
        schedule = self._create_simple_schedule(self.test_member.name, amount=25.0)

        current_user = frappe.session.user
        frappe.set_user("Guest")
        try:
            result = self.repo.update_schedule_rate(schedule.name, 30.0, "Should fail")

            self.assertFalse(result.success)
            self.assertIn("permission", result.message.lower())
        finally:
            frappe.set_user(current_user)

    # ─── Error handling ─────────────────────────────────────────────

    def test_nonexistent_schedule_returns_failure(self):
        """Returns failure for a schedule_name that doesn't exist."""
        result = self.repo.update_schedule_rate("NONEXISTENT-001", 25.0, "Ghost schedule")

        self.assertFalse(result.success)
        self.assertEqual(result.method_used, "none")
        self.assertTrue(len(result.errors) > 0)


if __name__ == "__main__":
    unittest.main()
