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
        # Create a test schedule using test factory
        schedule_doc = self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=25.0,
            frequency="monthly"
        )

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
        schedule_doc = self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=30.0,
            frequency="monthly"
        )

        # Retrieve via repository
        schedule = self.repo.get_active_schedule(self.test_member.name)

        self.assertIsNotNone(schedule)
        self.assertIsInstance(schedule, ScheduleInfo)
        self.assertEqual(schedule.member, self.test_member.name)
        self.assertEqual(schedule.status, "Active")

    def test_get_active_schedule_returns_none_when_no_active(self):
        """Test get_active_schedule returns None when no active schedule exists"""
        # Create cancelled schedule
        schedule_doc = self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=25.0,
            frequency="monthly"
        )
        # Cancel it
        schedule_doc.status = "Cancelled"
        schedule_doc.save()

        # Should return None
        schedule = self.repo.get_active_schedule(self.test_member.name)
        self.assertIsNone(schedule)

    def test_get_all_schedules_for_member(self):
        """Test retrieving all schedules (any status) for a member"""
        # Create active schedule
        schedule1 = self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=25.0,
            frequency="monthly"
        )

        # Create paused schedule
        schedule2 = self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=30.0,
            frequency="yearly"
        )
        schedule2.status = "Paused"
        schedule2.save()

        # Get all schedules
        schedules = self.repo.get_all_schedules_for_member(self.test_member.name)

        self.assertGreaterEqual(len(schedules), 2)
        schedule_statuses = {s.status for s in schedules}
        self.assertIn("Active", schedule_statuses)
        self.assertIn("Paused", schedule_statuses)

    def test_cancel_schedule_updates_correct_fields(self):
        """Test cancel_schedule updates status and reason"""
        # Create active schedule
        schedule_doc = self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=25.0,
            frequency="monthly"
        )

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
        schedule_doc = self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=25.0,
            frequency="monthly"
        )
        self.repo.cancel_schedule(schedule_doc.name, "Original reason")

        # Cancel again
        result = self.repo.cancel_schedule(schedule_doc.name, "New reason")

        # Should succeed with appropriate message
        self.assertTrue(result.success)
        self.assertIn("already", result.message.lower())

    def test_pause_schedule_updates_status(self):
        """Test pause_schedule changes status to Paused"""
        # Create active schedule
        schedule_doc = self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=25.0,
            frequency="monthly"
        )

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
        schedule_doc = self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=25.0,
            frequency="monthly"
        )

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
        self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=25.0,
            frequency="monthly"
        )
        self.create_test_dues_schedule(
            member=member2.name,
            amount=30.0,
            frequency="monthly"
        )

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
            schedule_doc = self.create_test_dues_schedule(
                member=self.test_member.name,
                amount=25.0,
                frequency="monthly"
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
        # Create schedule
        schedule_doc = self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=25.0,
            frequency="monthly"
        )

        # Set as Guest user (no permissions)
        frappe.set_user("Guest")

        try:
            result = self.repo.cancel_schedule(schedule_doc.name, "Should fail")
            # Should fail with permission error
            self.assertFalse(result.success)
            self.assertIn("permission", result.message.lower())
        finally:
            # Restore admin user
            frappe.set_user("Administrator")

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
