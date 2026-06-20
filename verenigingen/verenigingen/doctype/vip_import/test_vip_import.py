"""
Tests for VIP Import DocType

Tests the import of volunteer data from VIP (Volunteer Information Portal) exports.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

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

    def _make_vip_import_doc(self, **fields):
        """Create and insert a VIP Import fixture, returning the inserted doc."""
        data = {"doctype": "VIP Import"}
        data.update(fields)
        doc = frappe.get_doc(data)
        doc.insert(ignore_permissions=True)
        return doc

    def test_import_status_reflects_acr_failures(self):
        """Test that import status shows warning when ACR queuing fails."""
        # Create a VIP Import document. csv_file is a mandatory Attach field, so
        # provide a placeholder path (no file processing happens in this test, we
        # only exercise _set_final_import_status afterwards).
        import_doc = self._make_vip_import_doc(
            import_date=today(),
            csv_file="/files/test_vip_placeholder.csv",
        )
        frappe.db.commit()

        try:
            # Mock ACR result with error
            acr_result = {
                "error": "Redis connection failed",
                "acrs_created": 0,
                "active_volunteers_queued": 5,
            }

            stats = {
                "volunteers_created": 3,
                "volunteers_updated": 2,
                "volunteers_skipped": 0,
                "members_not_found": 0,
                "members_created": 0,
            }

            # Call the status update function
            from verenigingen.verenigingen.doctype.vip_import.vip_import import (
                _set_final_import_status,
            )

            _set_final_import_status(import_doc, stats=stats, acr_result=acr_result)
            frappe.db.commit()

            import_doc.reload()
            self.assertEqual(import_doc.import_status, "Completed with Warnings")
            self.assertIn("Redis connection failed", import_doc.acr_error or "")
        finally:
            # Cleanup
            frappe.delete_doc(import_doc.doctype, import_doc.name, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_queue_capacity_check_on_submit(self):
        """Test that queue capacity is checked before enqueueing import job."""
        from unittest.mock import patch

        # Create minimal VIP Import document
        import_doc = frappe.get_doc(
            {
                "doctype": "VIP Import",
                "import_date": today(),
                "import_status": "Ready for Import",
            }
        )

        # Mock queue capacity check to return False (queue full)
        with patch(
            "verenigingen.verenigingen.doctype.vip_import.vip_import.has_queue_capacity", return_value=False
        ) as mock_capacity:
            with patch(
                "verenigingen.verenigingen.doctype.vip_import.vip_import.wait_for_queue_capacity",
                return_value=False,
            ) as mock_wait:
                # Attempt to submit should throw
                with self.assertRaises(frappe.ValidationError) as context:
                    import_doc.on_submit()

                self.assertIn("queue", str(context.exception).lower())
                mock_capacity.assert_called_once()
                mock_wait.assert_called_once()

    def _create_race_condition_test_data(self, unique_id):
        """Create test member and volunteer for race condition testing.

        Args:
            unique_id: Unique identifier suffix for test data

        Returns:
            Tuple of (member, volunteer, row_data)
        """
        # Create a member
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Race",
                "last_name": "Test",
                "email": f"race-test-{unique_id}@example.com",
                "member_id": f"TEST-RACE-{unique_id}",
                "status": "Active",
            }
        )
        member.flags.bulk_member_operations = True
        member.insert(ignore_permissions=True)

        # Pre-create a volunteer to simulate race condition
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Race Test",
                "member": member.name,
                "status": "Active",
                "start_date": today(),
            }
        )
        volunteer.flags.bulk_member_operations = True
        volunteer.flags.skip_volunteer_account_creation = True
        volunteer.insert(ignore_permissions=True)
        frappe.db.commit()

        row = {
            "row_number": 1,
            "vip_user_id": f"race-test-{unique_id}",
            "first_name": "Race",
            "last_name": "Test",
            "organization_email": f"race-test-{unique_id}@example.com",
            "volunteer_status": "Active",
        }

        return member, volunteer, row

    def _cleanup_race_condition_test_data(self, member, volunteer):
        """Clean up test data created for race condition testing."""
        volunteer.delete(ignore_permissions=True)
        frappe.db.set_value("Member", member.name, "volunteer_record", None, update_modified=False)
        member.delete(ignore_permissions=True)
        frappe.db.commit()

    def test_duplicate_volunteer_handling_race_condition(self):
        """Test that concurrent volunteer creation is handled gracefully."""
        import uuid

        unique_id = str(uuid.uuid4())[:8]
        member, volunteer, row = self._create_race_condition_test_data(unique_id)

        from verenigingen.verenigingen.doctype.vip_import.vip_import import (
            _create_volunteer,
        )

        # This should NOT raise an error - should detect existing and return it
        result = _create_volunteer(row, member, import_batch_name=None)

        # Should return the existing volunteer, not create a duplicate
        self.assertEqual(result.name, volunteer.name)

        # Cleanup
        self._cleanup_race_condition_test_data(member, volunteer)

    def _create_savepoint_test_data(self, unique_id):
        """Create test member for savepoint rollback testing.

        Args:
            unique_id: Unique identifier suffix for test data

        Returns:
            Tuple of (member, row_data, test_vip_id)
        """
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

        return member, row, test_vip_id

    def _cleanup_savepoint_test_data(self, member, test_vip_id):
        """Clean up test data created for savepoint testing."""
        orphan_vol = frappe.db.exists("Volunteer", {"vip_user_id": test_vip_id})
        if orphan_vol:
            frappe.delete_doc("Volunteer", orphan_vol, force=True)
        if frappe.db.exists("Member", member.name):
            # Clear volunteer_record link before deleting member
            frappe.db.set_value("Member", member.name, "volunteer_record", None, update_modified=False)
            frappe.delete_doc("Member", member.name, force=True)
        frappe.db.commit()

    def test_savepoint_rollback_on_volunteer_link_failure(self):
        """Test that volunteer creation is rolled back if member link update fails."""
        import uuid

        unique_id = str(uuid.uuid4())[:8]
        member, row, test_vip_id = self._create_savepoint_test_data(unique_id)

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
            # Cleanup
            self._cleanup_savepoint_test_data(member, test_vip_id)

    def _create_test_member(self, first_name, last_name, email):
        # NOTE: Intentionally local — VIP import domain-specific setup (bulk_member_operations flag)
        """Create a test member for testing."""
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "status": "Active",
                "birth_date": "1990-01-01",  # Ensure old enough for volunteering
            }
        )
        member.flags.bulk_member_operations = True
        member.insert(ignore_permissions=True)
        frappe.db.commit()
        return member

    def test_create_volunteers_batch_uses_service(self):
        """Test that _create_volunteers_batch uses BulkVolunteerCreationService."""
        from verenigingen.services.volunteer.bulk_volunteer_creation_service import (
            BulkVolunteerCreationSummary,
        )

        # Create test member
        member = self._create_test_member(
            first_name="Bulk",
            last_name="ServiceTest",
            email="bulk-service-test@example.com",
        )

        try:
            # Mock the service
            mock_summary = BulkVolunteerCreationSummary(
                total_attempted=1,
                created=1,
            )

            # _create_volunteers_batch imports get_bulk_volunteer_creation_service
            # lazily from the service module, so patch it at its source module.
            with patch(
                "verenigingen.services.volunteer.bulk_volunteer_creation_service.get_bulk_volunteer_creation_service"
            ) as mock_get_service:
                mock_service = MagicMock()
                mock_service.create_volunteers_for_members.return_value = mock_summary
                mock_get_service.return_value = mock_service

                from verenigingen.verenigingen.doctype.vip_import.vip_import import (
                    _create_volunteers_batch,
                )

                result = _create_volunteers_batch(member_names=[member.name], import_batch_name="TEST-BULK")

                mock_service.create_volunteers_for_members.assert_called_once()
                self.assertEqual(result.created, 1)

        finally:
            # Cleanup
            member.delete(ignore_permissions=True)
            frappe.db.commit()


class TestVIPImportPureHelpers(FrappeTestCase):
    """Tests for pure (no-DB) helper functions in vip_import."""

    def test_sql_placeholders_zero_one_many(self):
        """_sql_placeholders must produce correct parameter strings for 0/1/many ids."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _sql_placeholders

        self.assertEqual(_sql_placeholders(0), "")
        self.assertEqual(_sql_placeholders(1), "%s")
        self.assertEqual(_sql_placeholders(3), "%s, %s, %s")
        # The placeholder count must equal the number of %s tokens (parameterization)
        self.assertEqual(_sql_placeholders(10).count("%s"), 10)

    def test_check_duplicate_vip_id_no_duplicates(self):
        """No duplicates -> empty error list."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _check_duplicate_vip_id

        mapped_data = [
            {"vip_user_id": "A-1", "row_number": 2},
            {"vip_user_id": "A-2", "row_number": 3},
        ]
        self.assertEqual(_check_duplicate_vip_id("A-1", mapped_data), [])

    def test_check_duplicate_vip_id_skips_blank_ids(self):
        """Rows with no vip_user_id must not be counted as duplicates."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _check_duplicate_vip_id

        mapped_data = [
            {"vip_user_id": "", "row_number": 2},
            {"vip_user_id": None, "row_number": 3},
            {"row_number": 4},
        ]
        self.assertEqual(_check_duplicate_vip_id("X", mapped_data), [])

    def test_check_duplicate_vip_id_multiple_duplicates(self):
        """Two later rows reusing an id produce two distinct error entries."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _check_duplicate_vip_id

        mapped_data = [
            {"vip_user_id": "DUP", "row_number": 2},
            {"vip_user_id": "DUP", "row_number": 5},
            {"vip_user_id": "DUP", "row_number": 9},
        ]
        errors = _check_duplicate_vip_id("DUP", mapped_data)
        self.assertEqual(len(errors), 2)
        # Each duplicate references the first-seen row (row 2)
        self.assertTrue(all("row 2" in e for e in errors))

    def test_get_import_template_structure(self):
        """get_import_template returns a 2-line CSV (header + sample) with expected columns."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import get_import_template

        self._as_admin()
        template = get_import_template()
        lines = [line for line in template.splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        header = lines[0]
        for expected_col in (
            "id",
            "nvv_relatie_nummer",
            "email",
            "private_email",
            "first_name",
            "last_name",
            "is_delegated_account",
        ):
            self.assertIn(expected_col, header)

    def _as_admin(self):
        frappe.set_user("Administrator")

    def test_format_skip_info_member_not_found(self):
        """Skip info for member_not_found builds identifier and name strings."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _format_skip_info

        row = {
            "vip_user_id": "VIP-9",
            "member_id": "M-9",
            "organization_email": "x@org.example.com",
            "first_name": "Anna",
            "last_name": "Jansen",
        }
        result = {"row": 7, "reason": "member_not_found", "status": "skipped"}
        info = _format_skip_info(row, result)
        self.assertEqual(info["row"], 7)
        self.assertEqual(info["reason"], "member_not_found")
        self.assertEqual(info["name"], "Anna Jansen")
        self.assertIn("VIP ID: VIP-9", info["identifier"])
        self.assertIn("Member ID: M-9", info["identifier"])
        self.assertIn("x@org.example.com", info["identifier"])

    def test_format_skip_info_no_identifier_no_name(self):
        """Empty row yields 'No identifier' and 'Unknown' name."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _format_skip_info

        info = _format_skip_info({}, {"status": "skipped"})
        self.assertEqual(info["identifier"], "No identifier")
        self.assertEqual(info["name"], "Unknown")
        self.assertEqual(info["reason"], "unknown")

    def test_generate_skipped_rows_log_empty(self):
        """Empty skip list returns empty string."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _generate_skipped_rows_log

        self.assertEqual(_generate_skipped_rows_log([]), "")

    def test_generate_skipped_rows_log_categorizes(self):
        """Skipped rows are categorized into Member Not Found / Already Exists / Errors / Other."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _generate_skipped_rows_log

        skipped = [
            {"row": 2, "reason": "member_not_found", "status": "skipped", "name": "A B", "identifier": "M-1"},
            {
                "row": 3,
                "reason": "volunteer_exists",
                "status": "skipped",
                "name": "C D",
                "identifier": "M-2",
                "volunteer": "VOL-1",
            },
            {
                "row": 4,
                "reason": "exception",
                "status": "error",
                "name": "E F",
                "identifier": "M-3",
                "error": "boom for user secret@example.com",
            },
            {"row": 5, "reason": "weird_reason", "status": "skipped", "name": "G H", "identifier": "M-4"},
        ]
        log = _generate_skipped_rows_log(skipped)
        self.assertIn("Member Not Found (1 rows)", log)
        self.assertIn("Volunteer Already Exists (1 rows)", log)
        self.assertIn("Processing Errors (1 rows)", log)
        self.assertIn("Other (1 rows)", log)
        self.assertIn("existing volunteer: VOL-1", log)
        # PII in error messages must be redacted in the log
        self.assertNotIn("secret@example.com", log)
        self.assertIn("[EMAIL REDACTED]", log)

    def test_generate_skipped_rows_log_truncates_per_category(self):
        """A category with more than MAX_SKIPPED_PER_CATEGORY entries is truncated with a '... more' line."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import (
            MAX_SKIPPED_PER_CATEGORY,
            _generate_skipped_rows_log,
        )

        n = MAX_SKIPPED_PER_CATEGORY + 5
        skipped = [
            {
                "row": i,
                "reason": "member_not_found",
                "status": "skipped",
                "name": f"Name {i}",
                "identifier": f"M-{i}",
            }
            for i in range(n)
        ]
        log = _generate_skipped_rows_log(skipped)
        self.assertIn(f"and {n - MAX_SKIPPED_PER_CATEGORY} more", log)


class TestVIPImportDocLifecycle(FrappeTestCase):
    """Tests for the VIPImport controller validate() / file-size path."""

    def _make_import(self, **kwargs):
        defaults = {
            "doctype": "VIP Import",
            "csv_file": "/files/test_vip_placeholder.csv",
        }
        defaults.update(kwargs)
        doc = frappe.get_doc(defaults)
        doc.insert(ignore_permissions=True)
        return doc

    def _make_file_doc(self, name_prefix, content):
        """Create and insert a private File fixture, returning the inserted doc."""
        file_doc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": f"{name_prefix}_{frappe.generate_hash(length=6)}.csv",
                "is_private": 1,
                "content": content,
            }
        ).insert(ignore_permissions=True)
        return file_doc

    def test_validate_sets_defaults_on_new(self):
        """validate() defaults import_date to today and import_status to Pending on insert."""
        doc = self._make_import()
        try:
            self.assertEqual(str(doc.import_date), today())
            self.assertEqual(doc.import_status, "Pending")
        finally:
            frappe.delete_doc(doc.doctype, doc.name, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_validate_file_size_under_limit_passes(self):
        """A small real attached file passes _validate_file_size without throwing."""
        # Create a real (tiny) File so _validate_file_size exercises the real os.path branch
        file_doc = self._make_file_doc("vip_small", "id,email\n1,a@b.com\n")
        frappe.db.commit()
        doc = None
        try:
            doc = self._make_import(csv_file=file_doc.file_url)
            # No exception means the under-limit branch executed
            self.assertEqual(doc.import_status, "Pending")
        finally:
            if doc:
                frappe.delete_doc(doc.doctype, doc.name, force=True, ignore_permissions=True)
            frappe.delete_doc(file_doc.doctype, file_doc.name, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_validate_file_size_over_limit_throws(self):
        """A file larger than MAX_FILE_SIZE_MB triggers a validation throw."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import MAX_FILE_SIZE_MB

        big_content = "x" * int((MAX_FILE_SIZE_MB + 1) * 1024 * 1024)
        file_doc = self._make_file_doc("vip_big", big_content)
        frappe.db.commit()
        try:
            with self.assertRaises(frappe.ValidationError):
                self._make_import(csv_file=file_doc.file_url)
        finally:
            frappe.delete_doc(file_doc.doctype, file_doc.name, force=True, ignore_permissions=True)
            frappe.db.commit()


class TestVIPImportCreateAndProcess(FrappeTestCase):
    """Integration tests for member creation and full row-processing branches."""

    def setUp(self):
        self._created_members = []
        self._created_volunteers = []
        self._created_imports = []

    def tearDown(self):
        for v in self._created_volunteers:
            if frappe.db.exists("Volunteer", v):
                frappe.delete_doc("Volunteer", v, force=True)
        for m in self._created_members:
            if frappe.db.exists("Member", m):
                frappe.db.set_value("Member", m, "volunteer_record", None, update_modified=False)
                frappe.delete_doc("Member", m, force=True)
        for imp in self._created_imports:
            if frappe.db.exists("VIP Import", imp):
                frappe.delete_doc("VIP Import", imp, force=True)
        frappe.db.commit()

    def _uid(self):
        import uuid

        return str(uuid.uuid4())[:8]

    def _make_member(self, **fields):
        """Build, insert (bulk flag) and track a Member fixture, returning the doc."""
        data = {"doctype": "Member"}
        data.update(fields)
        member = frappe.get_doc(data)
        member.flags.bulk_member_operations = True
        member.insert(ignore_permissions=True)
        self._created_members.append(member.name)
        return member

    def test_create_member_minimal(self):
        """_create_member creates a Member with email fallback and Active status."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _create_member

        uid = self._uid()
        row = {
            "first_name": "New",
            "last_name": "Recruit",
            "organization_email": f"new.recruit.{uid}@org.example.com",
            "member_id": f"VIP-NEW-{uid}",
        }
        member = _create_member(row)
        self._created_members.append(member.name)

        self.assertEqual(member.first_name, "New")
        self.assertEqual(member.status, "Active")
        # No personal_email -> falls back to organization_email
        self.assertEqual(member.email, row["organization_email"])
        self.assertEqual(member.member_id, f"VIP-NEW-{uid}")

    def test_process_single_row_creates_member_when_missing(self):
        """create_members_if_missing=True creates a member and then the volunteer."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _process_single_row

        uid = self._uid()
        import_doc = MagicMock()
        import_doc.create_members_if_missing = True
        import_doc.duplicate_handling = "Skip existing"
        import_doc.name = None

        row = {
            "row_number": 2,
            "first_name": "Created",
            "last_name": "Member",
            "vip_user_id": f"VIP-CM-{uid}",
            "personal_email": f"created.member.{uid}@example.com",
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

        self.assertEqual(result["status"], "created", result)
        self.assertEqual(stats["members_created"], 1)
        self.assertEqual(stats["volunteers_created"], 1)

        vol_name = result["volunteer"]
        self._created_volunteers.append(vol_name)
        member_name = frappe.db.get_value("Volunteer", vol_name, "member")
        if member_name:
            self._created_members.append(member_name)

    def test_process_single_row_update_existing(self):
        """duplicate_handling='Update existing' updates an existing volunteer."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import (
            _create_volunteer,
            _process_single_row,
        )

        uid = self._uid()
        member = self._make_member(
            first_name="Upd",
            last_name="Existing",
            member_id=f"VIP-UPD-{uid}",
            email=f"upd.existing.{uid}@example.com",
            status="Active",
            birth_date="1990-01-01",
        )
        frappe.db.commit()

        # Pre-create a volunteer with no vip_user_id
        vol = _create_volunteer({"volunteer_status": "Active"}, member)
        self._created_volunteers.append(vol.name)
        self.assertFalse(vol.vip_user_id)

        import_doc = MagicMock()
        import_doc.create_members_if_missing = False
        import_doc.duplicate_handling = "Update existing"
        import_doc.name = None

        row = {
            "row_number": 3,
            "member_id": f"VIP-UPD-{uid}",
            "vip_user_id": f"VIP-UPD-VOL-{uid}",
            "volunteer_status": "Inactive",
        }
        stats = {
            "volunteers_created": 0,
            "volunteers_updated": 0,
            "volunteers_skipped": 0,
            "members_not_found": 0,
            "members_created": 0,
        }
        result = _process_single_row(row, import_doc, stats)

        self.assertEqual(result["status"], "updated", result)
        self.assertEqual(stats["volunteers_updated"], 1)
        updated = frappe.get_doc("Volunteer", vol.name)
        self.assertEqual(updated.vip_user_id, f"VIP-UPD-VOL-{uid}")
        self.assertEqual(updated.status, "Inactive")

    def test_process_single_row_skip_existing(self):
        """duplicate_handling='Skip existing' skips an existing volunteer."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import (
            _create_volunteer,
            _process_single_row,
        )

        uid = self._uid()
        member = self._make_member(
            first_name="Skip",
            last_name="Existing",
            member_id=f"VIP-SKIP-{uid}",
            email=f"skip.existing.{uid}@example.com",
            status="Active",
            birth_date="1990-01-01",
        )
        frappe.db.commit()

        vol = _create_volunteer({"vip_user_id": f"VIP-SKIP-VOL-{uid}", "volunteer_status": "Active"}, member)
        self._created_volunteers.append(vol.name)

        import_doc = MagicMock()
        import_doc.create_members_if_missing = False
        import_doc.duplicate_handling = "Skip existing"
        import_doc.name = None

        row = {"row_number": 4, "member_id": f"VIP-SKIP-{uid}", "volunteer_status": "Active"}
        stats = {
            "volunteers_created": 0,
            "volunteers_updated": 0,
            "volunteers_skipped": 0,
            "members_not_found": 0,
            "members_created": 0,
        }
        result = _process_single_row(row, import_doc, stats)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "volunteer_exists")
        self.assertEqual(stats["volunteers_skipped"], 1)

    def test_create_volunteer_underage_throws(self):
        """A member below the minimum *volunteer* age cannot become a volunteer.

        The member-layer age enforcement (commit 36bb501b) blocks creating a member
        below ``minimum_membership_age`` outright, so a genuinely under-age member can
        no longer reach ``_create_volunteer`` at all. The scenario that DOES reach the
        volunteer-age gate is a member old enough to join but younger than a higher
        ``minimum_volunteer_age`` (a legitimate config: e.g. join at 16, volunteer at
        18). Configure that gap and assert ``_create_volunteer`` rejects them.
        """
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _create_volunteer

        settings = frappe.get_single("Verenigingen Settings")
        orig_membership_age = settings.get("minimum_membership_age")
        orig_volunteer_age = settings.get("minimum_volunteer_age")
        try:
            frappe.db.set_single_value("Verenigingen Settings", "minimum_membership_age", 16)
            frappe.db.set_single_value("Verenigingen Settings", "minimum_volunteer_age", 21)
            frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")

            uid = self._uid()
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "Young",
                    "last_name": "Person",
                    "member_id": f"VIP-YOUNG-{uid}",
                    "email": f"young.{uid}@example.com",
                    "status": "Active",
                    # 18: old enough to be a member (>=16), too young to volunteer (<21)
                    "birth_date": add_days(today(), -365 * 18),
                }
            )
            member.flags.bulk_member_operations = True
            member.insert(ignore_permissions=True)
            self._created_members.append(member.name)
            frappe.db.commit()

            with self.assertRaises(frappe.ValidationError):
                _create_volunteer({"volunteer_status": "Active"}, member)
        finally:
            frappe.db.set_single_value("Verenigingen Settings", "minimum_membership_age", orig_membership_age)
            frappe.db.set_single_value("Verenigingen Settings", "minimum_volunteer_age", orig_volunteer_age)
            frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")


class TestVIPImportFinalStatusAndAccountCreation(FrappeTestCase):
    """Tests for _set_final_import_status (happy path) and _process_account_creation."""

    def _make_import(self):
        doc = frappe.get_doc(
            {
                "doctype": "VIP Import",
                "csv_file": "/files/test_vip_placeholder.csv",
            }
        )
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return doc

    def _make_member(self, **fields):
        """Build, insert (bulk flag) and return a Member fixture."""
        data = {"doctype": "Member"}
        data.update(fields)
        member = frappe.get_doc(data)
        member.flags.bulk_member_operations = True
        member.insert(ignore_permissions=True)
        return member

    def _make_volunteer(self, member, **fields):
        """Build, insert (bulk flag, skip account creation) and return a Volunteer fixture."""
        data = {"doctype": "Volunteer", "member": member.name}
        data.update(fields)
        vol = frappe.get_doc(data)
        vol.flags.bulk_member_operations = True
        vol.flags.skip_volunteer_account_creation = True
        vol.insert(ignore_permissions=True)
        return vol

    def test_set_final_status_completed_with_summary_and_skipped_log(self):
        """No ACR error -> status Completed, summary + skipped log + error log all populated."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _set_final_import_status

        import_doc = self._make_import()
        try:
            stats = {
                "volunteers_created": 4,
                "volunteers_updated": 1,
                "volunteers_skipped": 2,
                "members_not_found": 1,
                "members_created": 3,
            }
            acr_result = {
                "acrs_created": 2,
                "active_volunteers_queued": 5,
                "inactive_skipped": 1,
                "users_linked": 1,
                "tracker_name": "TRACKER-1",
            }
            skipped_rows = [
                {
                    "row": 9,
                    "reason": "member_not_found",
                    "status": "skipped",
                    "name": "Lost Member",
                    "identifier": "M-9",
                }
            ]
            errors = ["Row 3: boom"]
            skipped_reasons = ["Row 8: delegated account shared@org.example.com"]

            _set_final_import_status(
                import_doc=import_doc,
                stats=stats,
                acr_result=acr_result,
                errors=errors,
                skipped_rows=skipped_rows,
                skipped_reasons=skipped_reasons,
            )
            frappe.db.commit()
            import_doc.reload()

            self.assertEqual(import_doc.import_status, "Completed")
            self.assertEqual(import_doc.volunteers_created, 4)
            self.assertEqual(import_doc.members_created, 3)
            self.assertEqual(import_doc.acrs_created, 2)
            self.assertEqual(import_doc.acrs_queued_for_active, 5)
            self.assertEqual(import_doc.bulk_operation_tracker, "TRACKER-1")
            self.assertIn("Volunteers created: 4", import_doc.import_summary)
            self.assertIn("Account Creation", import_doc.import_summary)
            self.assertIn("Active volunteers queued: 5", import_doc.import_summary)
            self.assertIn("Lost Member", import_doc.skipped_rows_log)
            self.assertIn("1 errors encountered", import_doc.top_errors_summary)
            self.assertIn("Delegated Accounts Skipped", import_doc.error_log)
            # PII in delegated reasons must be redacted
            self.assertNotIn("shared@org.example.com", import_doc.error_log)
        finally:
            import_doc.delete(ignore_permissions=True)
            frappe.db.commit()

    def test_set_final_status_all_inactive_branch(self):
        """When only inactive volunteers were processed, summary reports no upgrades needed."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _set_final_import_status

        import_doc = self._make_import()
        try:
            stats = {
                "volunteers_created": 0,
                "volunteers_updated": 2,
                "volunteers_skipped": 0,
                "members_not_found": 0,
                "members_created": 0,
            }
            acr_result = {"active_volunteers_queued": 0, "inactive_skipped": 2}
            _set_final_import_status(import_doc=import_doc, stats=stats, acr_result=acr_result)
            frappe.db.commit()
            import_doc.reload()
            self.assertEqual(import_doc.import_status, "Completed")
            self.assertIn("no account upgrades needed", import_doc.import_summary)
        finally:
            frappe.delete_doc(import_doc.doctype, import_doc.name, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_process_account_creation_no_active_volunteers(self):
        """No created/updated volunteers -> empty (no-op) result, no error."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _process_account_creation

        result = _process_account_creation(
            "VIP-FAKE-IMPORT",
            [
                {"status": "skipped", "volunteer": None},
                {"status": "error", "volunteer": None},
            ],
        )
        self.assertEqual(result["active_volunteers_queued"], 0)
        self.assertEqual(result["acrs_created"], 0)
        self.assertIsNone(result["error"])

    def test_process_account_creation_filters_inactive(self):
        """Inactive volunteers are counted as inactive_skipped, not queued."""
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _process_account_creation

        # Create a member + an Inactive volunteer (real DB rows, no account creation queued)
        uid = frappe.generate_hash(length=6)
        member = self._make_member(
            first_name="Inactive",
            last_name="Vol",
            member_id=f"VIP-INACT-{uid}",
            email=f"inact.{uid}@example.com",
            status="Active",
            birth_date="1990-01-01",
        )
        frappe.db.commit()

        vol = self._make_volunteer(
            member,
            volunteer_name="Inactive Vol",
            status="Inactive",
            start_date=today(),
        )
        frappe.db.commit()

        try:
            result = _process_account_creation(
                "VIP-FAKE-IMPORT",
                [{"status": "created", "volunteer": vol.name, "volunteer_status": "Inactive"}],
            )
            self.assertEqual(result["active_volunteers_queued"], 0)
            self.assertEqual(result["inactive_skipped"], 1)
            self.assertEqual(result["acrs_created"], 0)
            self.assertIsNone(result["error"])
        finally:
            frappe.delete_doc("Volunteer", vol.name, force=True)
            frappe.db.set_value("Member", member.name, "volunteer_record", None, update_modified=False)
            frappe.delete_doc("Member", member.name, force=True)
            frappe.db.commit()


if __name__ == "__main__":
    unittest.main()
