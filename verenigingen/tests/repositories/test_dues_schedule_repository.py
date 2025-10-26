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


class TestDuesScheduleRepository(EnhancedTestCase):
    """Test suite for DuesScheduleRepository"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.repo = DuesScheduleRepository()

        # Create test member
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Repository",
            email="test.repository@example.com",
            birth_date="1990-01-01",
        )

    def _create_simple_schedule(self, member_name, amount=25.0, status="Active", **kwargs):
        """Helper to create a simple dues schedule bypassing complex validations"""
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "member": member_name,
            "schedule_name": kwargs.get("schedule_name", f"Test Schedule {frappe.generate_hash(length=8)}"),
            "dues_rate": amount,
            "billing_frequency": kwargs.get("billing_frequency", "Monthly"),
            "membership_type": kwargs.get("membership_type", "Regular"),  # Required field
            "status": status,
            "next_invoice_date": kwargs.get("next_invoice_date", add_months(today(), 1)) if status == "Active" else None,
            "contribution_mode": kwargs.get("contribution_mode", "Tier"),
            **{k: v for k, v in kwargs.items() if k not in ["schedule_name", "billing_frequency", "next_invoice_date", "contribution_mode", "membership_type"]}
        })
        schedule.flags.ignore_validate = True  # Skip business rule validation for tests
        schedule.insert(ignore_permissions=True)
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
                self.assertIn(
                    field,
                    valid_fields,
                    f"BASIC_FIELDS contains invalid field: {field}"
                )

        # Check FULL_FIELDS
        for field in self.repo.FULL_FIELDS:
            if field != "name":
                self.assertIn(
                    field,
                    valid_fields,
                    f"FULL_FIELDS contains invalid field: {field}"
                )

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

    def test_get_all_schedules_for_member(self):
        """Test retrieving all schedules (any status) for a member"""
        # Create schedules with different statuses
        self._create_simple_schedule(self.test_member.name, status="Active", schedule_name="Active Schedule")
        self._create_simple_schedule(self.test_member.name, status="Paused", schedule_name="Paused Schedule")
        self._create_simple_schedule(self.test_member.name, status="Cancelled", schedule_name="Cancelled Schedule")

        # Get all schedules
        schedules = self.repo.get_all_schedules_for_member(self.test_member.name)

        self.assertGreaterEqual(len(schedules), 3)
        schedule_statuses = {s.status for s in schedules}
        self.assertIn("Active", schedule_statuses)
        self.assertIn("Paused", schedule_statuses)
        self.assertIn("Cancelled", schedule_statuses)

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
        self.assertEqual(schedule_doc.cancellation_reason, reason)

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
        self.assertIsNotNone(schedule_doc.pause_reason)

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

        # Batch retrieve
        schedules = self.repo.get_schedules_for_members(
            [self.test_member.name, member2.name]
        )

        # Should get both schedules in single query
        self.assertGreaterEqual(len(schedules), 2)
        member_names = {s.member for s in schedules}
        self.assertIn(self.test_member.name, member_names)
        self.assertIn(member2.name, member_names)

    def test_batch_cancel_multiple_schedules(self):
        """Test batch cancellation of multiple schedules"""
        # Create multiple schedules
        schedule_names = []
        for i in range(3):
            schedule_doc = self._create_simple_schedule(
                self.test_member.name,
                schedule_name=f"Batch Cancel {i}"
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


if __name__ == "__main__":
    unittest.main()
