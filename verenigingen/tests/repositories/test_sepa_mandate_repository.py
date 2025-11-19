"""
Unit Tests for SEPA Mandate Repository

Tests field name correctness, CRUD operations, batch operations, and security.
"""

import frappe
from frappe.utils import today, add_days
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.repositories import SEPAMandateRepository, MandateInfo, MandateOperationResult


class TestSEPAMandateRepository(EnhancedTestCase):
    """Test SEPA Mandate Repository field validation and operations"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.repo = SEPAMandateRepository()

        # Create test member
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Member",
            email="test.member@example.com",
            birth_date="1990-01-01"
        )

    def test_repository_initialization(self):
        """Verify repository initializes correctly"""
        self.assertEqual(self.repo.doctype, "SEPA Mandate")
        self.assertIsNotNone(self.repo.BASIC_FIELDS)
        self.assertIsNotNone(self.repo.FULL_FIELDS)

    def test_field_names_match_doctype_schema(self):
        """CRITICAL: Verify all field names match DocType JSON schema"""
        # Test that FULL_FIELDS contains correct field names
        self.assertIn("mandate_id", self.repo.FULL_FIELDS)
        self.assertIn("sign_date", self.repo.FULL_FIELDS)
        self.assertIn("cancelled_date", self.repo.FULL_FIELDS)

        # Verify WRONG field names are NOT present
        self.assertNotIn("mandate_reference", self.repo.FULL_FIELDS)
        self.assertNotIn("signature_date", self.repo.FULL_FIELDS)
        self.assertNotIn("cancellation_date", self.repo.FULL_FIELDS)

    def test_mandate_info_dataclass_field_mapping(self):
        """Verify MandateInfo dataclass uses correct field names"""
        # Create a test mandate using Frappe ORM to ensure field names are valid
        mandate_doc = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "mandate_id": "TEST-MANDATE-001",
            "member": self.test_member.name,
            "account_holder_name": "Test Member",
            "iban": "NL91 ABNA 0417 1643 00",  # Valid IBAN with proper checksum
            "status": "Active",
            "is_active": 1,
            "sign_date": today(),
        }).insert()

        # Fetch via repository
        mandate_info = self.repo.get_mandate_by_name(mandate_doc.name)

        # Verify correct field names exist and have values
        self.assertIsNotNone(mandate_info)
        self.assertEqual(mandate_info.name, mandate_doc.name)
        self.assertEqual(mandate_info.mandate_id, "TEST-MANDATE-001")
        self.assertIsNotNone(mandate_info.sign_date)
        self.assertEqual(mandate_info.status, "Active")
        self.assertEqual(mandate_info.is_active, 1)

    def test_get_active_mandates_for_member(self):
        """Test retrieving active mandates for a member"""
        # Use the same valid IBAN that works in existing tests
        valid_iban = "NL91 ABNA 0417 1643 00"

        # Create two active mandates
        mandate1 = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "mandate_id": "TEST-M1",
            "member": self.test_member.name,
            "account_holder_name": "Test Member",
            "iban": valid_iban,
            "status": "Active",
            "is_active": 1,
            "sign_date": today(),
        }).insert()

        mandate2 = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "mandate_id": "TEST-M2",
            "member": self.test_member.name,
            "account_holder_name": "Test Member",
            "iban": valid_iban,
            "status": "Active",
            "is_active": 1,
            "sign_date": today(),
        }).insert()

        # Create one cancelled mandate (should be excluded)
        cancelled_mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "mandate_id": "TEST-M3",
            "member": self.test_member.name,
            "account_holder_name": "Test Member",
            "iban": valid_iban,
            "status": "Cancelled",
            "is_active": 0,
            "sign_date": add_days(today(), -30),
            "cancelled_date": today(),
        }).insert()

        # Query via repository (use FULL_FIELDS to get mandate_id)
        mandates = self.repo.get_active_mandates_for_member(
            self.test_member.name,
            fields=self.repo.FULL_FIELDS
        )

        # Verify results
        self.assertEqual(len(mandates), 2)
        self.assertIsInstance(mandates[0], MandateInfo)

        mandate_ids = [m.mandate_id for m in mandates]
        self.assertIn("TEST-M1", mandate_ids)
        self.assertIn("TEST-M2", mandate_ids)
        self.assertNotIn("TEST-M3", mandate_ids)  # Cancelled should be excluded

    def test_deactivate_mandate_updates_correct_fields(self):
        """CRITICAL: Verify deactivation writes to cancelled_date not cancellation_date"""
        # Create active mandate
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "mandate_id": "TEST-DEACTIVATE",
            "member": self.test_member.name,
            "account_holder_name": "Test Member",
            "iban": "NL91 ABNA 0417 1643 00",  # Valid IBAN
            "status": "Active",
            "is_active": 1,
            "sign_date": today(),
        }).insert()

        # Deactivate via repository
        result = self.repo.deactivate_mandate(
            mandate.name,
            reason="Test deactivation",
            cancellation_date=today()
        )

        # Verify operation succeeded
        self.assertIsInstance(result, MandateOperationResult)
        self.assertTrue(result.success, f"Deactivation failed: {result.message}")
        self.assertEqual(result.mandate_name, mandate.name)

        # Reload from database and verify CORRECT field names
        mandate.reload()
        self.assertEqual(mandate.status, "Cancelled")
        self.assertEqual(mandate.is_active, 0)
        self.assertIsNotNone(mandate.cancelled_date)  # ✅ CORRECT field name
        # Compare as strings since frappe may return date object
        self.assertEqual(str(mandate.cancelled_date), str(today()))
        self.assertEqual(mandate.cancellation_reason, "Test deactivation")

    def test_deactivate_mandate_idempotency(self):
        """Verify deactivating already-cancelled mandate is idempotent"""
        # Create mandate
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "mandate_id": "TEST-IDEMPOTENT",
            "member": self.test_member.name,
            "account_holder_name": "Test Member",
            "iban": "NL91 ABNA 0417 1643 00",  # Valid IBAN
            "status": "Active",
            "is_active": 1,
            "sign_date": today(),
        }).insert()

        # First deactivation
        result1 = self.repo.deactivate_mandate(mandate.name, "First cancellation")
        self.assertTrue(result1.success)
        self.assertIn(result1.method_used, ["direct_sql_update"])

        # Second deactivation - should be idempotent
        result2 = self.repo.deactivate_mandate(mandate.name, "Second cancellation")
        self.assertTrue(result2.success)
        self.assertEqual(result2.method_used, "already_cancelled")
        self.assertIn("already", result2.message.lower())

    def test_deactivate_mandates_for_iban_change(self):
        """Test the main use case: IBAN change batch deactivation"""
        # Create multiple active mandates with same IBAN (with spaces as stored in DB)
        old_iban = "NL91 ABNA 0417 1643 00"
        new_iban = "NL02 RABO 0300 0652 64"

        mandates = []
        for i in range(3):
            mandate = frappe.get_doc({
                "doctype": "SEPA Mandate",
                "mandate_id": f"TEST-IBAN-CHANGE-{i}",
                "member": self.test_member.name,
                "account_holder_name": "Test Member",
                "iban": old_iban,
                "status": "Active",
                "is_active": 1,
                "sign_date": add_days(today(), -30),
            }).insert()
            mandates.append(mandate)

        # Perform IBAN change deactivation
        results = self.repo.deactivate_mandates_for_member_iban_change(
            member_name=self.test_member.name,
            old_iban=old_iban,
            new_iban=new_iban
        )

        # Verify all mandates were processed
        self.assertEqual(len(results), 3)

        # Verify all succeeded
        for mandate_name, result in results.items():
            self.assertTrue(result.success, f"Failed: {result.message}")
            # Check for IBAN in message (may or may not have spaces)
            self.assertTrue(
                new_iban in result.message or new_iban.replace(" ", "") in result.message,
                f"New IBAN not found in message: {result.message}"
            )

        # Verify database state
        for mandate in mandates:
            mandate.reload()
            self.assertEqual(mandate.status, "Cancelled")
            self.assertEqual(mandate.is_active, 0)
            self.assertIsNotNone(mandate.cancelled_date)
            # IBANs may have spaces, so check both ways
            self.assertTrue(
                old_iban in mandate.cancellation_reason or
                old_iban.replace(" ", "") in mandate.cancellation_reason.replace(" ", ""),
                f"Old IBAN not in reason: {mandate.cancellation_reason}"
            )
            self.assertTrue(
                new_iban in mandate.cancellation_reason or
                new_iban.replace(" ", "") in mandate.cancellation_reason.replace(" ", ""),
                f"New IBAN not in reason: {mandate.cancellation_reason}"
            )

    def test_batch_deactivation_no_mandates(self):
        """Test batch deactivation when member has no active mandates"""
        # Create member with no mandates
        member_without_mandates = self.create_test_member(
            first_name="No",
            last_name="Mandates",
            email="no.mandates@example.com"
        )

        # Try to deactivate (should return empty dict)
        results = self.repo.deactivate_mandates_for_member_iban_change(
            member_name=member_without_mandates.name,
            old_iban="NL91ABNA0417164300",
            new_iban="NL47RABO0300065264"
        )

        self.assertEqual(len(results), 0)

    def test_permission_checks_enforced(self):
        """Verify permission checks work correctly"""
        # Create mandate as System Manager
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "mandate_id": "TEST-PERMISSION",
            "member": self.test_member.name,
            "account_holder_name": "Test Member",
            "iban": "NL91 ABNA 0417 1643 00",  # Valid IBAN
            "status": "Active",
            "is_active": 1,
            "sign_date": today(),
        }).insert()

        # Switch to Guest user (no permissions)
        frappe.set_user("Guest")

        # Try to deactivate (should fail with permission error)
        result = self.repo.deactivate_mandate(mandate.name, "Should fail")

        self.assertFalse(result.success)
        self.assertIn("permission", result.message.lower())
        self.assertEqual(result.method_used, "none")

        # Restore user
        frappe.set_user("Administrator")

    def test_empty_parameter_validation(self):
        """Test handling of empty/invalid parameters"""
        # Empty mandate name
        result = self.repo.deactivate_mandate("", "Test")
        self.assertFalse(result.success)
        self.assertIn("No mandate name", result.message)

        # None mandate name
        result = self.repo.deactivate_mandate(None, "Test")
        self.assertFalse(result.success)

        # Empty member name for query
        mandates = self.repo.get_active_mandates_for_member("")
        self.assertEqual(len(mandates), 0)

        mandates = self.repo.get_active_mandates_for_member(None)
        self.assertEqual(len(mandates), 0)

    def test_mandate_info_type_safety(self):
        """Verify MandateInfo dataclass type safety"""
        # Create mandate
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "mandate_id": "TEST-TYPE-SAFETY",
            "member": self.test_member.name,
            "account_holder_name": "Test Member",
            "iban": "NL91 ABNA 0417 1643 00",  # Valid IBAN
            "status": "Active",
            "is_active": 1,
            "sign_date": today(),
        }).insert()

        # Fetch via repository
        mandate_info = self.repo.get_mandate_by_name(mandate.name)

        # Verify type
        self.assertIsInstance(mandate_info, MandateInfo)

        # Verify all required fields present
        self.assertIsNotNone(mandate_info.name)
        self.assertIsNotNone(mandate_info.member)
        self.assertIsNotNone(mandate_info.iban)
        self.assertIsNotNone(mandate_info.status)
        self.assertIsInstance(mandate_info.is_active, int)

    def tearDown(self):
        """Clean up test data"""
        # Delete all test mandates
        frappe.db.delete("SEPA Mandate", {"mandate_id": ["like", "TEST-%"]})

        super().tearDown()
