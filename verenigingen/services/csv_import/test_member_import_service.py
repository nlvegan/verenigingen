# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberImportService Tests - TDD tests for member import service.

Tests member creation/update logic extracted from MijnRood CSV Import DocType.
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestMemberImportService(FrappeTestCase):
    """Test MemberImportService functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        # Ensure test membership type exists.
        # Membership Type reqd fields: membership_type_name (autoname=field:),
        # minimum_amount, role_profile.
        if not frappe.db.exists("Membership Type", "Regular"):
            role_profile = frappe.db.get_value(
                "Role Profile", {"name": "Verenigingen Staff"}, "name"
            ) or frappe.db.get_value("Role Profile", {}, "name")
            frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Regular",
                    "minimum_amount": 60.0,
                    "role_profile": role_profile,
                }
            ).insert(ignore_permissions=True)
            frappe.db.commit()

    def setUp(self):
        """Set up each test."""
        super().setUp()
        self.created_members = []

    def tearDown(self):
        """Clean up created test members."""
        for member_name in self.created_members:
            try:
                frappe.delete_doc("Member", member_name, force=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    def _create_member(self, **fields):
        """Create a Member fixture. Named _create_* so the permission bypass is
        recognised as fixture setup rather than test logic."""
        member = frappe.new_doc("Member")
        member.status = "Active"
        for field, value in fields.items():
            setattr(member, field, value)
        member.flags.ignore_workflow = True
        member._system_update = True
        member.insert(ignore_permissions=True)
        frappe.db.commit()
        self.created_members.append(member.name)
        return member

    # ============================================================
    # Tests for determine_member_status()
    # ============================================================

    def test_determine_member_status_active_lid(self):
        """Test status determination for 'lid' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("lid")

        self.assertEqual(status, "Active")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_active_standard(self):
        """Test status determination for 'standard' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("standard")

        self.assertEqual(status, "Active")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_aspirant(self):
        """Test status determination for 'aspirant' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("aspirant")

        self.assertEqual(status, "Active")
        self.assertTrue(is_aspirant)

    def test_determine_member_status_deceased(self):
        """Test status determination for 'overleden' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("overleden")

        self.assertEqual(status, "Deceased")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_terminated(self):
        """Test status determination for 'opgezegd' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("opgezegd")

        self.assertEqual(status, "Quit")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_banned(self):
        """Test status determination for 'geroyeerd' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("geroyeerd")

        self.assertEqual(status, "Banned")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_duplicate(self):
        """Test status determination for 'dubbel' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("dubbel")

        self.assertEqual(status, "Rejected")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_suspended(self):
        """Test status determination for 'geschorst' membership type."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("geschorst")

        self.assertEqual(status, "Suspended")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_unknown_defaults_active(self):
        """Test status determination for unknown type defaults to Active."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status("unknown_type")

        self.assertEqual(status, "Active")
        self.assertFalse(is_aspirant)

    def test_determine_member_status_case_insensitive(self):
        """Test status determination is case insensitive."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()

        status1, _ = service.determine_member_status("LID")
        status2, _ = service.determine_member_status("Lid")
        status3, _ = service.determine_member_status("lid")

        self.assertEqual(status1, "Active")
        self.assertEqual(status2, "Active")
        self.assertEqual(status3, "Active")

    def test_determine_member_status_handles_none(self):
        """Test status determination handles None gracefully."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, is_aspirant = service.determine_member_status(None)

        self.assertEqual(status, "Active")
        self.assertFalse(is_aspirant)

    # ============================================================
    # Tests for update_member_fields()
    # ============================================================

    def test_update_member_fields_basic_info(self):
        """Test updating basic member information from row data."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        member = frappe.new_doc("Member")

        row_data = {
            "member_id": "TEST-001",
            "first_name": "Jan",
            "tussenvoegsel": "van",
            "last_name": "Test",
            "email": "jan.test@example.com",
            "birth_date": "1990-01-15",
            "membership_type": "lid",
        }

        service.update_member_fields(member, row_data, "TEST-IMPORT-001")

        self.assertEqual(member.member_id, "TEST-001")
        self.assertEqual(member.first_name, "Jan")
        self.assertEqual(member.tussenvoegsel, "van")
        self.assertEqual(member.last_name, "Test")
        self.assertEqual(member.email, "jan.test@example.com")
        self.assertEqual(member.status, "Active")

    def test_update_member_fields_sets_system_flags(self):
        """Test that system flags are set for CSV import."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        member = frappe.new_doc("Member")

        row_data = {
            "first_name": "Test",
            "last_name": "Member",
            "membership_type": "lid",
        }

        service.update_member_fields(member, row_data, "TEST-IMPORT-001")

        self.assertTrue(member.flags.ignore_workflow)
        self.assertTrue(getattr(member, "_system_update", False))
        self.assertTrue(getattr(member, "_csv_import", False))

    def test_update_member_fields_with_iban_sets_payment_method(self):
        """Test that IBAN sets payment method to Bank Transfer."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        member = frappe.new_doc("Member")

        row_data = {
            "first_name": "Test",
            "last_name": "Member",
            "membership_type": "lid",
            "iban": "NL91ABNA0417164300",
        }

        service.update_member_fields(member, row_data, "TEST-IMPORT-001")

        self.assertEqual(member.iban, "NL91ABNA0417164300")
        self.assertEqual(member.payment_method, "Bank Transfer")

    def test_update_member_fields_with_mollie_sets_payment_method(self):
        """Test that Mollie data sets payment method to Mollie."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        member = frappe.new_doc("Member")

        row_data = {
            "first_name": "Test",
            "last_name": "Member",
            "membership_type": "lid",
            "custom_mollie_customer_id": "cst_test123",
        }

        service.update_member_fields(member, row_data, "TEST-IMPORT-001")

        self.assertEqual(member.payment_method, "Mollie")
        self.assertTrue(hasattr(member, "_mollie_data"))
        self.assertEqual(member._mollie_data["custom_mollie_customer_id"], "cst_test123")

    def test_update_member_fields_stores_address_data(self):
        """Test that address data is stored for later creation."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        member = frappe.new_doc("Member")

        row_data = {
            "first_name": "Test",
            "last_name": "Member",
            "membership_type": "lid",
            "address_line1": "Teststraat 123",
            "city": "Amsterdam",
            "postal_code": "1234 AB",
        }

        service.update_member_fields(member, row_data, "TEST-IMPORT-001")

        self.assertIsNotNone(member._pending_address_data)

    def test_update_member_fields_stores_termination_data_for_terminated(self):
        """Test that termination data is stored for terminated members."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        member = frappe.new_doc("Member")

        row_data = {
            "first_name": "Test",
            "last_name": "Member",
            "membership_type": "opgezegd",
        }

        service.update_member_fields(member, row_data, "TEST-IMPORT-001")

        self.assertEqual(member.status, "Quit")
        self.assertTrue(hasattr(member, "_pending_termination_data"))

    # ============================================================
    # Tests for create_or_update_member() - Integration
    # ============================================================

    def test_create_member_basic(self):
        """Test creating a new member from row data."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service
        from verenigingen.utils.csv_import_processor import bulk_member_operations

        service = get_member_import_service()

        row_data = {
            "row_number": 1,
            "member_id": "TEST-CREATE-001",
            "first_name": "Create",
            "last_name": "Test",
            "email": "create.test@example.com",
            "membership_type": "lid",
        }

        with bulk_member_operations("TEST-IMPORT"):
            result, member_name = service.create_or_update_member(
                row_data=row_data,
                import_doc_name="TEST-IMPORT-001",
                create_volunteer_records=False,
            )

        self.assertEqual(result, "created")
        self.assertIsNotNone(member_name)
        self.created_members.append(member_name)

        # Verify member was created correctly
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.member_id, "TEST-CREATE-001")
        self.assertEqual(member.first_name, "Create")
        self.assertEqual(member.status, "Active")

    def test_update_existing_member(self):
        """Test updating an existing member from row data."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service
        from verenigingen.utils.csv_import_processor import bulk_member_operations

        # First create a member
        member = self._create_member(
            first_name="Existing",
            last_name="Member",
            member_id="TEST-UPDATE-001",
            email="existing@example.com",
        )

        service = get_member_import_service()

        row_data = {
            "row_number": 1,
            "member_id": "TEST-UPDATE-001",
            "first_name": "Updated",
            "last_name": "Member",
            "email": "updated@example.com",
            "membership_type": "lid",
        }

        with bulk_member_operations("TEST-IMPORT"):
            result, member_name = service.create_or_update_member(
                row_data=row_data,
                import_doc_name="TEST-IMPORT-001",
                create_volunteer_records=False,
            )

        self.assertEqual(result, "updated")
        self.assertEqual(member_name, member.name)

        # Verify member was updated
        member.reload()
        self.assertEqual(member.first_name, "Updated")
        self.assertEqual(member.email, "updated@example.com")

    def test_create_member_duplicate_skipped(self):
        """Test that duplicate member creation is handled gracefully."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service
        from verenigingen.utils.csv_import_processor import bulk_member_operations

        # First create a member with specific email
        member = self._create_member(
            first_name="Duplicate",
            last_name="Test",
            email="duplicate.test@example.com",
        )

        service = get_member_import_service()

        # Try to create with same email - should find existing and update
        row_data = {
            "row_number": 1,
            "first_name": "New",
            "last_name": "Person",
            "email": "duplicate.test@example.com",
            "membership_type": "lid",
        }

        with bulk_member_operations("TEST-IMPORT"):
            result, member_name = service.create_or_update_member(
                row_data=row_data,
                import_doc_name="TEST-IMPORT-001",
                create_volunteer_records=False,
            )

        # Should update existing member found by email
        self.assertEqual(result, "updated")
        self.assertEqual(member_name, member.name)

    def test_update_validation_error_surfaces_reason_and_logs(self):
        """A ValidationError on the update path must not be reduced to bare 'failed'.

        Regression for MR-SYNC-2026-00087: a stale Dynamic Link in the member's
        payment_history (reference_doctype='Membership' pointing at a Membership
        Dues Schedule) makes _validate_links() raise LinkValidationError on every
        save. The service used to swallow the reason entirely — it returned
        ("failed", name) and, unlike the generic Exception branch, never wrote an
        Error Log — so the operator saw only "Member update failed" with nothing
        anywhere to explain it.

        The stale row is inserted with raw SQL on purpose: doc.save() would
        reject it, which is precisely why the corruption is invisible until the
        next save attempt.
        """
        from verenigingen.services.csv_import.member_import_service import get_member_import_service
        from verenigingen.utils.csv_import_processor import bulk_member_operations

        member = self._create_member(
            first_name="Stale",
            last_name="LinkMember",
            email="stale.link@example.com",
        )

        bogus_reference = "Schedule-Does-Not-Exist-As-A-Membership-001"
        frappe.db.sql(
            """
            INSERT INTO `tabMember Payment History`
                (name, parent, parenttype, parentfield, idx, docstatus,
                 transaction_type, reference_doctype, reference_name)
            VALUES (%s, %s, 'Member', 'payment_history', 1, 0,
                    'Membership Invoice', 'Membership', %s)
            """,
            (frappe.generate_hash(length=10), member.name, bogus_reference),
        )
        frappe.db.commit()

        log_marker = frappe.utils.now_datetime()

        with bulk_member_operations("TEST-IMPORT"):
            status, returned_name = get_member_import_service().create_or_update_member(
                row_data={
                    "row_number": 7,
                    "first_name": "Stale",
                    "last_name": "LinkMember",
                    "email": "stale.link@example.com",
                    "membership_type": "lid",
                },
                import_doc_name="TEST-IMPORT-001",
            )

        # Still a failure status, so every `status in ("created", "updated")`
        # caller keeps behaving identically.
        self.assertTrue(status.startswith("failed"), f"expected a failed status, got {status!r}")
        self.assertNotIn("created", status)
        self.assertNotIn("updated", status)
        self.assertEqual(returned_name, member.name)

        # The reason the operator needs is now in the status itself.
        self.assertIn(bogus_reference, status)

        # ...and an Error Log row carries the traceback. Assert the specific
        # title — a bare count would be satisfied by any unrelated Error Log.
        titles = frappe.get_all(
            "Error Log",
            filters={"creation": [">=", log_marker]},
            pluck="error",
            limit=50,
        )
        self.assertTrue(
            any("CSV Import Update Validation Error Row 7" in (t or "") for t in titles)
            or frappe.db.exists(
                "Error Log", {"method": ["like", "%CSV Import Update Validation Error Row 7%"]}
            ),
            "expected an Error Log titled 'CSV Import Update Validation Error Row 7'",
        )

    def test_failure_status_truncates_long_reasons(self):
        """The reason is capped so it cannot bloat the status or the event field."""
        from verenigingen.services.csv_import.member_import_service import (
            _FAILURE_REASON_MAX_LENGTH,
            _failure_status,
        )

        status = _failure_status(Exception("x" * 5000))

        self.assertTrue(status.startswith("failed: "))
        self.assertEqual(len(status) - len("failed: "), _FAILURE_REASON_MAX_LENGTH)

    def test_failure_status_collapses_newlines(self):
        """Keeps the status single-line for both the log and the sync-event field."""
        from verenigingen.services.csv_import.member_import_service import _failure_status

        self.assertEqual(
            _failure_status(Exception("line one\nline  two\n\tline three")),
            "failed: line one line two line three",
        )

    def test_failure_status_without_a_message_stays_bare(self):
        from verenigingen.services.csv_import.member_import_service import _failure_status

        self.assertEqual(_failure_status(Exception()), "failed")

    def test_singleton_service_instance(self):
        """Test that get_member_import_service returns singleton."""
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service1 = get_member_import_service()
        service2 = get_member_import_service()

        self.assertIs(service1, service2)
