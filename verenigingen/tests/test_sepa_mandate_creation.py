"""
Test Suite for SEPA Mandate Creation Methods
Tests the new JavaScript-exposed methods for mandate creation validation and processing
"""

import unittest

import frappe
from frappe.utils import today


class TestSEPAMandateCreation(unittest.TestCase):
    """Test SEPA mandate creation methods exposed for JavaScript"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        cls.test_records = []

        # Create test member
        cls.member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "SEPA",
                "last_name": "Creation",
                "email": "sepa.creation@test.com",
                "full_name": "SEPA Creation",
                "status": "Active",
                "iban": "NL91ABNA0417164300",
                "bic": "ABNANL2A",
            }
        )
        cls.member.insert(ignore_permissions=True)
        cls.test_records.append(cls.member)

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        # Clean up any SEPA mandates first
        mandates = frappe.get_all("SEPA Mandate", filters={"member": cls.member.name})
        for mandate in mandates:
            try:
                frappe.delete_doc("SEPA Mandate", mandate.name, force=True)
            except Exception:
                pass

        # Clean up test records
        for record in reversed(cls.test_records):
            try:
                record.delete(ignore_permissions=True, force=True)
            except Exception:
                pass

    def setUp(self):
        """Set up each test"""
        frappe.set_user("Administrator")

        # Clean up any existing mandates before each test
        existing_mandates = frappe.get_all("SEPA Mandate", filters={"member": self.member.name})
        for mandate in existing_mandates:
            try:
                frappe.delete_doc("SEPA Mandate", mandate.name, force=True)
            except Exception:
                pass

    # ===== TEST validate_mandate_creation =====

    def test_validate_mandate_creation_valid_data(self):
        """Test validate_mandate_creation with valid data"""
        from verenigingen.verenigingen.doctype.member.member import validate_mandate_creation

        result = validate_mandate_creation(
            member=self.member.name, iban="NL91ABNA0417164300", mandate_id="TEST-MANDATE-001"
        )

        self.assertTrue(result.get("valid"))
        self.assertNotIn("error", result)

    def test_validate_mandate_creation_nonexistent_member(self):
        """Test validate_mandate_creation with non-existent member"""
        from verenigingen.verenigingen.doctype.member.member import validate_mandate_creation

        result = validate_mandate_creation(
            member="NON-EXISTENT-MEMBER", iban="NL91ABNA0417164300", mandate_id="TEST-MANDATE-001"
        )

        self.assertIn("error", result)
        self.assertIn("Member does not exist", result["error"])

    def test_validate_mandate_creation_duplicate_mandate_id(self):
        """Test validate_mandate_creation with duplicate mandate ID"""
        from verenigingen.verenigingen.doctype.member.member import validate_mandate_creation

        # Create existing mandate
        existing_mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": "DUPLICATE-MANDATE-001",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": "NL91ABNA0417164300",
                "sign_date": today(),
                "status": "Active",
            }
        )
        existing_mandate.insert()

        try:
            result = validate_mandate_creation(
                member=self.member.name,
                iban="DE89370400440532013000",  # Different IBAN
                mandate_id="DUPLICATE-MANDATE-001",  # Same mandate ID
            )

            self.assertIn("error", result)
            self.assertIn("already exists", result["error"])
        finally:
            existing_mandate.delete()

    def test_validate_mandate_creation_existing_iban_mandate(self):
        """Test validate_mandate_creation with existing mandate for same IBAN"""
        from verenigingen.verenigingen.doctype.member.member import validate_mandate_creation

        # Create existing mandate for same IBAN
        existing_mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": "EXISTING-IBAN-001",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": "NL91ABNA0417164300",
                "sign_date": today(),
                "status": "Active",
                "is_active": 1,
            }
        )
        existing_mandate.insert()

        try:
            result = validate_mandate_creation(
                member=self.member.name,
                iban="NL91ABNA0417164300",  # Same IBAN
                mandate_id="NEW-MANDATE-001",  # Different mandate ID
            )

            self.assertTrue(result.get("valid"))
            self.assertIn("existing_mandate", result)
            self.assertEqual(result["existing_mandate"], "EXISTING-IBAN-001")
            self.assertIn("warning", result)
        finally:
            existing_mandate.delete()

    # ===== TEST derive_bic_from_iban =====

    def test_derive_bic_from_iban_dutch_banks(self):
        """Test BIC derivation for Dutch banks"""
        from verenigingen.verenigingen.doctype.member.member import derive_bic_from_iban

        test_cases = [
            ("NL91ABNA0417164300", "ABNANL2A"),  # ABN AMRO
            ("NL91INGB0001234567", "INGBNL2A"),  # ING Bank
            ("NL91RABO0123456789", "RABONL2U"),  # Rabobank
            ("NL91TRIO0123456789", "TRIONL2U"),  # Triodos Bank
        ]

        for iban, expected_bic in test_cases:
            with self.subTest(iban=iban):
                result = derive_bic_from_iban(iban)
                self.assertEqual(result.get("bic"), expected_bic)

    def test_derive_bic_from_iban_invalid_iban(self):
        """Test BIC derivation with invalid IBAN"""
        from verenigingen.verenigingen.doctype.member.member import derive_bic_from_iban

        result = derive_bic_from_iban("INVALID-IBAN")
        self.assertIsNone(result.get("bic"))

    def test_derive_bic_from_iban_unknown_bank(self):
        """Test BIC derivation with unknown bank code"""
        from verenigingen.verenigingen.doctype.member.member import derive_bic_from_iban

        result = derive_bic_from_iban("NL91UNKN0123456789")
        self.assertIsNone(result.get("bic"))

    # ===== TEST get_active_sepa_mandate =====

    def test_get_active_sepa_mandate_no_mandate(self):
        """Test get_active_sepa_mandate with no existing mandates"""
        from verenigingen.verenigingen.doctype.member.member import get_active_sepa_mandate

        result = get_active_sepa_mandate(self.member.name)
        self.assertIsNone(result)

    def test_get_active_sepa_mandate_with_active_mandate(self):
        """Test get_active_sepa_mandate with active mandate"""
        from verenigingen.verenigingen.doctype.member.member import get_active_sepa_mandate

        # Create active mandate
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": "ACTIVE-MANDATE-001",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": "NL91ABNA0417164300",
                "sign_date": today(),
                "status": "Active",
                "is_active": 1,
            }
        )
        mandate.insert()

        try:
            result = get_active_sepa_mandate(self.member.name)

            self.assertIsNotNone(result)
            self.assertEqual(result["mandate_id"], "ACTIVE-MANDATE-001")
            self.assertEqual(result["status"], "Active")
        finally:
            mandate.delete()

    def test_get_active_sepa_mandate_with_iban_filter(self):
        """Test get_active_sepa_mandate with IBAN filter"""
        from verenigingen.verenigingen.doctype.member.member import get_active_sepa_mandate

        # Create two mandates with different IBANs
        mandate1 = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": "IBAN-MANDATE-001",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": "NL91ABNA0417164300",
                "sign_date": today(),
                "status": "Active",
                "is_active": 1,
            }
        )
        mandate1.insert()

        mandate2 = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": "IBAN-MANDATE-002",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": "DE89370400440532013000",
                "sign_date": today(),
                "status": "Active",
                "is_active": 1,
            }
        )
        mandate2.insert()

        try:
            # Test filtering by specific IBAN
            result = get_active_sepa_mandate(member=self.member.name, iban="DE89370400440532013000")

            self.assertIsNotNone(result)
            self.assertEqual(result["mandate_id"], "IBAN-MANDATE-002")
            self.assertEqual(result["iban"], "DE89370400440532013000")
        finally:
            mandate1.delete()
            mandate2.delete()

    # ===== TEST create_and_link_mandate_enhanced =====

    def test_create_and_link_mandate_enhanced_basic(self):
        """Test basic mandate creation and linking"""
        from verenigingen.verenigingen.doctype.member.member import create_and_link_mandate_enhanced

        result = create_and_link_mandate_enhanced(
            member=self.member.name,
            mandate_id="ENHANCED-MANDATE-001",
            iban="NL91ABNA0417164300",
            bic="ABNANL2A",
            account_holder_name=self.member.full_name,
            mandate_type="Recurring",
            sign_date=today(),
            used_for_memberships=1,
            used_for_donations=0,
            notes="Test mandate creation",
        )

        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("mandate_id"), "ENHANCED-MANDATE-001")

        # Verify mandate was created
        mandate = frappe.get_doc("SEPA Mandate", result["mandate_name"])
        self.assertEqual(mandate.mandate_id, "ENHANCED-MANDATE-001")
        self.assertEqual(mandate.member, self.member.name)
        self.assertEqual(mandate.mandate_type, "RCUR")  # Converted from "Recurring"
        self.assertEqual(mandate.status, "Active")

        # Verify mandate was linked to member
        member_doc = frappe.get_doc("Member", self.member.name)
        mandate_links = [
            link for link in member_doc.sepa_mandates if link.mandate_reference == "ENHANCED-MANDATE-001"
        ]
        self.assertEqual(len(mandate_links), 1)
        self.assertTrue(mandate_links[0].is_current)

        # Cleanup
        mandate.delete()

    def test_create_and_link_mandate_enhanced_one_off(self):
        """Test one-off mandate creation"""
        from verenigingen.verenigingen.doctype.member.member import create_and_link_mandate_enhanced

        result = create_and_link_mandate_enhanced(
            member=self.member.name,
            mandate_id="ONEOFF-MANDATE-001",
            iban="NL91ABNA0417164300",
            account_holder_name=self.member.full_name,
            mandate_type="One-off",  # Should convert to OOFF
        )

        self.assertTrue(result.get("success"))

        # Verify mandate type conversion
        mandate = frappe.get_doc("SEPA Mandate", result["mandate_name"])
        self.assertEqual(mandate.mandate_type, "OOFF")

        # Cleanup
        mandate.delete()

    def test_create_and_link_mandate_enhanced_replace_existing(self):
        """Test mandate creation with replacement of existing mandate"""
        from verenigingen.verenigingen.doctype.member.member import create_and_link_mandate_enhanced

        # Create existing mandate and link to member
        existing_mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": "OLD-MANDATE-001",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": "NL91ABNA0417164300",
                "sign_date": today(),
                "status": "Active",
            }
        )
        existing_mandate.insert()

        # Link to member
        member_doc = frappe.get_doc("Member", self.member.name)
        member_doc.append(
            "sepa_mandates",
            {
                "sepa_mandate": existing_mandate.name,
                "mandate_reference": "OLD-MANDATE-001",
                "is_current": 1,
                "status": "Active",
                "valid_from": today(),
            },
        )
        member_doc.save()

        try:
            # Create new mandate with replacement
            result = create_and_link_mandate_enhanced(
                member=self.member.name,
                mandate_id="NEW-MANDATE-001",
                iban="DE89370400440532013000",  # Different IBAN
                account_holder_name=self.member.full_name,
                replace_existing="OLD-MANDATE-001",
            )

            self.assertTrue(result.get("success"))

            # Verify old mandate link is no longer current
            member_doc.reload()
            old_links = [
                link for link in member_doc.sepa_mandates if link.mandate_reference == "OLD-MANDATE-001"
            ]
            self.assertEqual(len(old_links), 1)
            self.assertFalse(old_links[0].is_current)

            # Verify new mandate link is current
            new_links = [
                link for link in member_doc.sepa_mandates if link.mandate_reference == "NEW-MANDATE-001"
            ]
            self.assertEqual(len(new_links), 1)
            self.assertTrue(new_links[0].is_current)

            # Cleanup
            new_mandate = frappe.get_doc("SEPA Mandate", result["mandate_name"])
            new_mandate.delete()
        finally:
            existing_mandate.delete()

    def test_create_and_link_mandate_enhanced_invalid_member(self):
        """Test mandate creation with invalid member"""
        from verenigingen.verenigingen.doctype.member.member import create_and_link_mandate_enhanced

        with self.assertRaises(frappe.exceptions.ValidationError):
            create_and_link_mandate_enhanced(
                member="NON-EXISTENT-MEMBER",
                mandate_id="INVALID-MANDATE-001",
                iban="NL91ABNA0417164300",
                account_holder_name="Test Name",
            )

    def test_create_and_link_mandate_enhanced_missing_required_fields(self):
        """Test mandate creation with missing required fields"""
        from verenigingen.verenigingen.doctype.member.member import create_and_link_mandate_enhanced

        # Test missing mandate_id
        with self.assertRaises(frappe.exceptions.ValidationError):
            create_and_link_mandate_enhanced(
                member=self.member.name,
                mandate_id="",  # Empty mandate ID
                iban="NL91ABNA0417164300",
                account_holder_name=self.member.full_name,
            )

        # Test missing IBAN
        with self.assertRaises(frappe.exceptions.ValidationError):
            create_and_link_mandate_enhanced(
                member=self.member.name,
                mandate_id="TEST-MANDATE-001",
                iban="",  # Empty IBAN
                account_holder_name=self.member.full_name,
            )

    # ===== INTEGRATION TESTS =====

    def test_full_mandate_creation_workflow(self):
        """Test complete mandate creation workflow as used by JavaScript"""
        from verenigingen.verenigingen.doctype.member.member import (
            create_and_link_mandate_enhanced,
            derive_bic_from_iban,
            validate_mandate_creation,
        )

        # Step 1: Validate mandate creation
        validation_result = validate_mandate_creation(
            member=self.member.name, iban="NL91INGB0001234567", mandate_id="WORKFLOW-MANDATE-001"
        )
        self.assertTrue(validation_result.get("valid"))

        # Step 2: Derive BIC from IBAN
        bic_result = derive_bic_from_iban("NL91INGB0001234567")
        expected_bic = "INGBNL2A"
        self.assertEqual(bic_result.get("bic"), expected_bic)

        # Step 3: Create and link mandate
        creation_result = create_and_link_mandate_enhanced(
            member=self.member.name,
            mandate_id="WORKFLOW-MANDATE-001",
            iban="NL91INGB0001234567",
            bic=bic_result.get("bic"),
            account_holder_name=self.member.full_name,
            mandate_type="Recurring",
            used_for_memberships=1,
            notes="Full workflow test",
        )

        self.assertTrue(creation_result.get("success"))

        # Verify complete setup
        mandate = frappe.get_doc("SEPA Mandate", creation_result["mandate_name"])
        self.assertEqual(mandate.bic, expected_bic)
        self.assertEqual(mandate.iban, "NL91INGB0001234567")
        self.assertEqual(mandate.status, "Active")

        # Cleanup
        mandate.delete()


def run_sepa_mandate_creation_tests():
    """Run all SEPA mandate creation tests"""
    print("🏦 Running SEPA Mandate Creation Tests...")

    suite = unittest.TestLoader().loadTestsFromTestCase(TestSEPAMandateCreation)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All SEPA mandate creation tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        for failure in result.failures:
            print(f"FAIL: {failure[0]}")
            print(f"  {failure[1]}")
        for error in result.errors:
            print(f"ERROR: {error[0]}")
            print(f"  {error[1]}")
        return False


if __name__ == "__main__":
    run_sepa_mandate_creation_tests()
