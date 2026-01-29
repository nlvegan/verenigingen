"""
Tests for VIP Import DocType

Tests the import of volunteer data from VIP (Volunteer Information Portal) exports.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from verenigingen.utils.csv.vip_data_validator import VIPDataValidator


class TestVIPDataValidator(FrappeTestCase):
    """Test cases for VIP Data Validator."""

    def setUp(self):
        """Set up test fixtures."""
        self.validator = VIPDataValidator()

    def test_field_mapping(self):
        """Test that CSV columns are mapped correctly."""
        row = {
            "id": "123",
            "google_account_ref": "abc123",
            "nvv_relatie_nummer": "12345",
            "email": "test@org.example.com",
            "private_email": "personal@example.com",
            "first_name": "Jan",
            "last_name": "de Vries",
            "status": "available",
        }

        mapped = self.validator.map_row_data(row, 2)

        self.assertEqual(mapped["vip_user_id"], "123")
        self.assertEqual(mapped["google_workspace_id"], "abc123")
        self.assertEqual(mapped["member_id"], "12345")
        self.assertEqual(mapped["organization_email"], "test@org.example.com")
        self.assertEqual(mapped["personal_email"], "personal@example.com")
        self.assertEqual(mapped["first_name"], "Jan")
        self.assertEqual(mapped["last_name"], "de Vries")
        self.assertEqual(mapped["vip_status"], "available")

    def test_status_mapping(self):
        """Test VIP status to Volunteer status mapping."""
        test_cases = [
            ("available", "Active"),
            ("holiday", "Inactive"),
            ("break", "Inactive"),
            ("unavailable", "Retired"),
            ("quit", "Retired"),
            ("AVAILABLE", "Active"),  # Case insensitive
            ("Holiday", "Inactive"),  # Case insensitive
        ]

        for vip_status, expected in test_cases:
            result = self.validator.map_status(vip_status)
            self.assertEqual(result, expected, f"Status '{vip_status}' should map to '{expected}'")

    def test_status_mapping_fallback(self):
        """Test status mapping with is_active fallback."""
        # Unknown status with is_active=True
        result = self.validator.map_status("unknown", is_active=True)
        self.assertEqual(result, "Active")

        # Unknown status with is_active=False
        result = self.validator.map_status("unknown", is_active=False)
        self.assertEqual(result, "Inactive")

        # No status info defaults to Active
        result = self.validator.map_status(None, is_active=None)
        self.assertEqual(result, "Active")

    def test_delegated_account_detection(self):
        """Test that delegated accounts are correctly identified."""
        csv_data = [
            {
                "id": "1",
                "email": "user@org.example.com",
                "is_delegated_account": "false",
            },
            {
                "id": "2",
                "email": "shared@org.example.com",
                "is_delegated_account": "true",
            },
            {
                "id": "3",
                "email": "another@org.example.com",
                "is_delegated_account": "1",
            },
        ]

        mapped_data, errors, skipped = self.validator.validate_and_map_data(csv_data, skip_delegated=True)

        # Only non-delegated account should be in mapped_data
        self.assertEqual(len(mapped_data), 1)
        self.assertEqual(mapped_data[0]["vip_user_id"], "1")

        # Should have 2 skipped reasons
        self.assertEqual(len(skipped), 2)

    def test_delegated_account_not_skipped(self):
        """Test that delegated accounts are included when skip_delegated=False."""
        csv_data = [
            {
                "id": "1",
                "email": "shared@org.example.com",
                "is_delegated_account": "true",
            },
        ]

        mapped_data, errors, skipped = self.validator.validate_and_map_data(csv_data, skip_delegated=False)

        self.assertEqual(len(mapped_data), 1)
        self.assertEqual(len(skipped), 0)

    def test_email_validation(self):
        """Test email format validation."""
        valid_emails = [
            "test@example.com",
            "user.name@domain.org",
            "user+tag@example.co.uk",
        ]

        invalid_emails = [
            "notanemail",
            "@nodomain.com",
            "noat.com",
            "double..dots@example.com",
        ]

        for email in valid_emails:
            self.assertTrue(self.validator._validate_email(email), f"'{email}' should be valid")

        for email in invalid_emails:
            self.assertFalse(self.validator._validate_email(email), f"'{email}' should be invalid")

    def test_phone_number_preference(self):
        """Test that mobile number is preferred over phone number."""
        row = {
            "phone_number": "+31201234567",
            "mobile_number": "+31612345678",
        }

        mapped = self.validator.map_row_data(row, 2)
        contact = self.validator._get_preferred_phone(mapped)

        # Mobile should be preferred
        self.assertIn("612345678", contact)

    def test_phone_number_fallback(self):
        """Test phone number fallback when no mobile."""
        row = {
            "phone_number": "+31201234567",
        }

        mapped = self.validator.map_row_data(row, 2)
        contact = self.validator._get_preferred_phone(mapped)

        # Should fall back to phone_number
        self.assertIn("201234567", contact)

    def test_row_requires_identifier(self):
        """Test that rows without any identifier are rejected."""
        csv_data = [
            {
                "id": "1",
                "first_name": "Jan",
                "last_name": "de Vries",
                # No member_id, email, or private_email
            },
        ]

        mapped_data, errors, skipped = self.validator.validate_and_map_data(csv_data)

        self.assertEqual(len(mapped_data), 0)
        self.assertEqual(len(errors), 1)
        self.assertIn("No identifier found", errors[0])

    def test_preview_summary(self):
        """Test preview summary generation."""
        csv_data = [
            {
                "id": "1",
                "nvv_relatie_nummer": "12345",
                "email": "test1@org.example.com",
                "status": "available",
            },
            {
                "id": "2",
                "nvv_relatie_nummer": "12346",
                "email": "test2@org.example.com",
                "status": "holiday",
            },
            {
                "id": "3",
                "email": "shared@org.example.com",
                "is_delegated_account": "true",
            },
        ]

        preview = self.validator.get_preview_summary(csv_data)

        self.assertEqual(preview["total_rows"], 3)
        self.assertEqual(preview["valid_rows"], 2)
        self.assertEqual(preview["skipped_rows"], 1)
        self.assertEqual(preview["with_member_id"], 2)
        self.assertIn("Active", preview["status_breakdown"])
        self.assertIn("Inactive", preview["status_breakdown"])


class TestVIPImportIntegration(FrappeTestCase):
    """Integration tests for VIP Import DocType."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures that persist across tests."""
        super().setUpClass()

        # Create a test member for matching
        cls.test_member = None
        if not frappe.db.exists("Member", {"member_id": "TEST-VIP-001"}):
            cls.test_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "Test",
                    "last_name": "VIP Member",
                    "member_id": "TEST-VIP-001",
                    "email": "test.vip@example.com",
                    "status": "Active",
                }
            )
            cls.test_member.flags.bulk_member_operations = True
            cls.test_member.insert(ignore_permissions=True)
        else:
            cls.test_member = frappe.get_doc("Member", {"member_id": "TEST-VIP-001"})

    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures."""
        # Clean up test volunteers
        for vol in frappe.get_all(
            "Volunteer",
            filters={"vip_user_id": ["like", "TEST-VIP-%"]},
            pluck="name",
        ):
            frappe.delete_doc("Volunteer", vol, force=True)

        # Clean up test member
        if cls.test_member:
            # First unlink volunteer_record
            frappe.db.set_value("Member", cls.test_member.name, "volunteer_record", None)
            frappe.delete_doc("Member", cls.test_member.name, force=True)

        super().tearDownClass()

    def test_find_member_by_member_id(self):
        """Test member lookup by member_id."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _find_member

        row = {"member_id": "TEST-VIP-001"}
        member = _find_member(row)

        self.assertIsNotNone(member)
        self.assertEqual(member.member_id, "TEST-VIP-001")

    def test_find_member_by_email(self):
        """Test member lookup by email fallback."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _find_member

        row = {"personal_email": "test.vip@example.com"}
        member = _find_member(row)

        self.assertIsNotNone(member)
        self.assertEqual(member.email, "test.vip@example.com")

    def test_create_volunteer(self):
        """Test volunteer creation from VIP data."""
        import uuid

        from verenigingen.verenigingen.doctype.vip_import.vip_import import _create_volunteer

        unique_id = str(uuid.uuid4())[:8]
        row = {
            "vip_user_id": f"TEST-VIP-VOL-{unique_id}",
            "google_workspace_id": f"test-gws-{unique_id}",
            "organization_email": f"test.volunteer.{unique_id}@org.example.com",
            "volunteer_status": "Active",
            "start_date": "2024-01-15",
            "notes": "Test volunteer",
        }

        volunteer = _create_volunteer(row, self.test_member)

        self.assertIsNotNone(volunteer)
        self.assertEqual(volunteer.vip_user_id, row["vip_user_id"])
        self.assertEqual(volunteer.google_workspace_id, row["google_workspace_id"])
        self.assertEqual(volunteer.email, row["organization_email"])
        self.assertEqual(volunteer.status, "Active")
        self.assertEqual(volunteer.member, self.test_member.name)

        # Clean up
        frappe.delete_doc("Volunteer", volunteer.name, force=True)

    def test_update_volunteer(self):
        """Test volunteer update with VIP data."""
        import uuid

        from verenigingen.verenigingen.doctype.vip_import.vip_import import (
            _create_volunteer,
            _update_volunteer,
        )

        unique_id = str(uuid.uuid4())[:8]

        # Create initial volunteer
        initial_row = {
            "vip_user_id": f"TEST-VIP-VOL-{unique_id}",
            "volunteer_status": "Active",
        }
        volunteer = _create_volunteer(initial_row, self.test_member)

        # Update with additional data
        update_row = {
            "google_workspace_id": f"updated-gws-{unique_id}",
            "organization_email": f"updated.{unique_id}@org.example.com",
            "volunteer_status": "Inactive",
            "notes": "Updated notes",
        }

        updated = _update_volunteer(volunteer, update_row, self.test_member)

        self.assertEqual(updated.google_workspace_id, update_row["google_workspace_id"])
        self.assertEqual(updated.email, update_row["organization_email"])
        self.assertEqual(updated.status, "Inactive")
        self.assertIn("Updated notes", updated.note)

        # Clean up
        frappe.delete_doc("Volunteer", volunteer.name, force=True)


class TestVIPImportBackgroundJob(FrappeTestCase):
    """Integration tests for VIP Import background job processing."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()

        # Create test member for background job tests
        cls.test_member = None
        if not frappe.db.exists("Member", {"member_id": "TEST-VIP-BG-001"}):
            cls.test_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "Background",
                    "last_name": "Test Member",
                    "member_id": "TEST-VIP-BG-001",
                    "email": "bg.test@example.com",
                    "status": "Active",
                    "birth_date": "1990-01-01",  # Ensure member is old enough
                }
            )
            cls.test_member.flags.bulk_member_operations = True
            cls.test_member.insert(ignore_permissions=True)
        else:
            cls.test_member = frappe.get_doc("Member", {"member_id": "TEST-VIP-BG-001"})

    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures."""
        # Clean up test volunteers
        for vol in frappe.get_all(
            "Volunteer",
            filters={"vip_user_id": ["like", "TEST-VIP-BG-%"]},
            pluck="name",
        ):
            frappe.delete_doc("Volunteer", vol, force=True)

        # Clean up test VIP Import documents
        for imp in frappe.get_all(
            "VIP Import",
            filters={"descriptive_name": ["like", "TEST-BG-%"]},
            pluck="name",
        ):
            frappe.delete_doc("VIP Import", imp, force=True)

        # Clean up test member
        if cls.test_member:
            frappe.db.set_value("Member", cls.test_member.name, "volunteer_record", None)
            frappe.delete_doc("Member", cls.test_member.name, force=True)

        super().tearDownClass()

    def test_sanitize_error_message(self):
        """Test PII sanitization from error messages."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _sanitize_error_message

        # Test email sanitization
        msg_with_email = "Error for user test@example.com on row 5"
        sanitized = _sanitize_error_message(msg_with_email)
        self.assertNotIn("test@example.com", sanitized)
        self.assertIn("[EMAIL REDACTED]", sanitized)

        # Test phone sanitization
        msg_with_phone = "Contact number +31612345678 is invalid"
        sanitized = _sanitize_error_message(msg_with_phone)
        self.assertNotIn("+31612345678", sanitized)
        self.assertIn("[PHONE REDACTED]", sanitized)

        # Test message without PII
        msg_clean = "Row 5: Invalid status value"
        sanitized = _sanitize_error_message(msg_clean)
        self.assertEqual(sanitized, msg_clean)

    def test_check_duplicate_vip_id(self):
        """Test duplicate VIP ID detection."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _check_duplicate_vip_id

        mapped_data = [
            {"vip_user_id": "VIP-001", "row_number": 2},
            {"vip_user_id": "VIP-002", "row_number": 3},
            {"vip_user_id": "VIP-001", "row_number": 4},  # Duplicate
            {"vip_user_id": "VIP-003", "row_number": 5},
        ]

        errors = _check_duplicate_vip_id("VIP-001", mapped_data)

        # Should detect the duplicate
        self.assertEqual(len(errors), 1)
        self.assertIn("Duplicate VIP User ID", errors[0])
        self.assertIn("VIP-001", errors[0])

    def test_validate_volunteer_age(self):
        """Test volunteer age validation."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _validate_volunteer_age

        # Create mock member with young birth date (under 16)
        young_member = MagicMock()
        young_member.get = lambda x: "2015-01-01" if x == "birth_date" else None
        young_member.birth_date = "2015-01-01"

        error = _validate_volunteer_age(young_member)
        self.assertIsNotNone(error)
        self.assertIn("at least", error.lower())

        # Create mock member with adult birth date
        adult_member = MagicMock()
        adult_member.get = lambda x: "1990-01-01" if x == "birth_date" else None
        adult_member.birth_date = "1990-01-01"

        error = _validate_volunteer_age(adult_member)
        self.assertIsNone(error)

        # Test member without birth date (should pass - can't validate)
        no_dob_member = MagicMock()
        no_dob_member.get = lambda x: None
        no_dob_member.birth_date = None

        error = _validate_volunteer_age(no_dob_member)
        self.assertIsNone(error)

    def test_process_single_row_creates_volunteer(self):
        """Test single row processing creates volunteer correctly."""
        import uuid

        from verenigingen.verenigingen.doctype.vip_import.vip_import import _process_single_row

        unique_id = str(uuid.uuid4())[:8]

        # Create a mock import document
        # Note: import_doc.name is None to skip batch tracking validation
        # since we don't have a real VIP Import doc in the database
        import_doc = MagicMock()
        import_doc.create_members_if_missing = False
        import_doc.duplicate_handling = "Skip existing"
        import_doc.name = None  # Skip batch tracking in test - Link validation would fail

        # Test row that should match our test member
        row = {
            "row_number": 2,
            "member_id": "TEST-VIP-BG-001",
            "vip_user_id": f"TEST-VIP-BG-VOL-{unique_id}",
            "volunteer_status": "Active",
        }

        stats = {
            "volunteers_created": 0,
            "volunteers_updated": 0,
            "volunteers_skipped": 0,
            "members_not_found": 0,
            "members_created": 0,
        }

        result = _process_single_row(row, import_doc, stats)

        # Debug output if test fails
        if result.get("status") == "error":
            print(f"ERROR in test_process_single_row_creates_volunteer: {result.get('error')}")

        self.assertEqual(
            result["status"],
            "created",
            f"Expected 'created' but got '{result.get('status')}'. Error: {result.get('error')}",
        )
        self.assertEqual(stats["volunteers_created"], 1)

        # Clean up created volunteer
        if result.get("volunteer"):
            frappe.delete_doc("Volunteer", result["volunteer"], force=True)

    def test_process_single_row_member_not_found(self):
        """Test single row processing when member not found."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _process_single_row

        import_doc = MagicMock()
        import_doc.create_members_if_missing = False
        import_doc.duplicate_handling = "Skip existing"
        import_doc.name = None  # Skip batch tracking in test

        row = {
            "row_number": 2,
            "member_id": "NONEXISTENT-MEMBER-ID",
            "vip_user_id": "TEST-VIP-BG-VOL-002",
            "volunteer_status": "Active",
        }

        stats = {
            "volunteers_created": 0,
            "volunteers_updated": 0,
            "volunteers_skipped": 0,
            "members_not_found": 0,
            "members_created": 0,
        }

        result = _process_single_row(row, import_doc, stats)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "member_not_found")
        self.assertEqual(stats["members_not_found"], 1)


class TestVIPImportRobustness(FrappeTestCase):
    """Test robustness features of VIP Import."""

    def test_savepoint_rollback_on_volunteer_link_failure(self):
        """Test that volunteer creation is rolled back if member link update fails."""
        import uuid

        unique_id = str(uuid.uuid4())[:8]
        test_email = f"savepoint-test-{unique_id}@example.com"
        test_vip_id = f"savepoint-test-{unique_id}"
        test_member_id = f"TEST-SAVEPOINT-{unique_id}"

        # Create a member with unique email and explicit member_id to avoid auto-gen collision
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Savepoint",
                "last_name": "Test",
                "email": test_email,
                "member_id": test_member_id,  # Explicit unique member_id
                "status": "Active",
            }
        )
        member.flags.bulk_member_operations = True
        member.insert(ignore_permissions=True)
        frappe.db.commit()

        row = {
            "row_number": 1,
            "vip_user_id": test_vip_id,
            "member_id": test_member_id,  # Match by member_id for more reliable lookup
            "first_name": "Savepoint",
            "last_name": "Test",
            "organization_email": test_email,
            "volunteer_status": "Active",
        }

        # Mock db.set_value to fail on volunteer_record update
        original_set_value = frappe.db.set_value

        def failing_set_value(doctype, name, field, value=None, *args, **kwargs):
            # Fail on the volunteer_record update to Member
            if doctype == "Member" and field == "volunteer_record":
                raise Exception("Simulated DB failure on volunteer_record update")
            return original_set_value(doctype, name, field, value, *args, **kwargs)

        import_doc = MagicMock()
        import_doc.create_members_if_missing = False
        import_doc.duplicate_handling = "Update existing"
        import_doc.name = None  # Skip batch tracking in test

        stats = {
            "volunteers_created": 0,
            "volunteers_updated": 0,
            "volunteers_skipped": 0,
            "members_not_found": 0,
            "members_created": 0,
        }

        try:
            with patch.object(frappe.db, "set_value", failing_set_value):
                from verenigingen.verenigingen.doctype.vip_import.vip_import import (
                    _process_single_row,
                )

                result = _process_single_row(row, import_doc, stats)

            # Should return error status
            self.assertEqual(result["status"], "error", f"Expected error status, got: {result}")

            # Volunteer should NOT exist (rolled back)
            volunteer_exists = frappe.db.exists("Volunteer", {"vip_user_id": test_vip_id})
            self.assertFalse(volunteer_exists, "Volunteer should be rolled back on failure")
        finally:
            # Cleanup - delete any orphaned volunteer and the test member
            orphan_vol = frappe.db.exists("Volunteer", {"vip_user_id": test_vip_id})
            if orphan_vol:
                frappe.delete_doc("Volunteer", orphan_vol, force=True)
            if frappe.db.exists("Member", member.name):
                # Clear volunteer_record link before deleting member
                frappe.db.set_value("Member", member.name, "volunteer_record", None, update_modified=False)
                frappe.delete_doc("Member", member.name, force=True)
            frappe.db.commit()


if __name__ == "__main__":
    unittest.main()
