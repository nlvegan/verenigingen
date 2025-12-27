# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import random_string


class TestDonor(FrappeTestCase):
    """Tests for Donor DocType"""

    def tearDown(self):
        """Clean up test donors"""
        frappe.db.rollback()

    def test_bsn_validation_with_valid_9_digits(self):
        """Test that valid 9-digit BSN passes validation"""
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Test Donor {random_string(5)}"
        donor.donor_type = "Individual"
        donor.donor_email = f"test_{random_string(5)}@example.com"
        # Valid BSN that passes eleven-proof: 111222333
        donor.bsn_citizen_service_number = "111222333"

        # Should not raise
        donor.validate_tax_identifiers()

    def test_bsn_validation_rejects_invalid_length(self):
        """Test that BSN with wrong length is rejected"""
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Test Donor {random_string(5)}"
        donor.donor_type = "Individual"
        donor.donor_email = f"test_{random_string(5)}@example.com"
        donor.bsn_citizen_service_number = "12345"  # Only 5 digits

        with self.assertRaises(frappe.ValidationError) as context:
            donor.validate_tax_identifiers()

        self.assertIn("9 digits", str(context.exception))

    def test_encrypted_bsn_skips_validation(self):
        """
        Regression test: Encrypted BSN values should skip validation.

        When a Donor document is loaded from the database (e.g., during
        child table updates), the BSN field contains the encrypted value
        like 'ENC:gAAAA...'. Validation should skip these values since
        they were already validated during the original save.

        GitHub issue: Donor validation failed on update_child_table
        """
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Test Donor {random_string(5)}"
        donor.donor_type = "Individual"
        donor.donor_email = f"test_{random_string(5)}@example.com"

        # Simulate encrypted BSN (as loaded from database)
        encrypted_bsn = "ENC:gAAAAABpTASYIcIHK_buv-2wsuVJDqP3IZWh8uUY"
        donor.bsn_citizen_service_number = encrypted_bsn

        # Verify it's recognized as encrypted
        self.assertTrue(donor.is_encrypted(donor.bsn_citizen_service_number))

        # Validation should pass (skip encrypted values)
        donor.validate_tax_identifiers()

        # BSN should remain unchanged (not processed)
        self.assertEqual(donor.bsn_citizen_service_number, encrypted_bsn)

    def test_encrypted_rsin_skips_validation(self):
        """
        Regression test: Encrypted RSIN values should skip validation.

        Same issue as BSN - RSIN validation should skip encrypted values.
        """
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Test Org {random_string(5)}"
        donor.donor_type = "Organization"
        donor.donor_email = f"org_{random_string(5)}@example.com"

        # Simulate encrypted RSIN (as loaded from database)
        encrypted_rsin = "ENC:gAAAAABpTASYIcIHK_buv-2wsuVJDqP3IZWh8uUY"
        donor.rsin_organization_tax_number = encrypted_rsin

        # Verify it's recognized as encrypted
        self.assertTrue(donor.is_encrypted(donor.rsin_organization_tax_number))

        # Validation should pass (skip encrypted values)
        donor.validate_tax_identifiers()

        # RSIN should remain unchanged
        self.assertEqual(donor.rsin_organization_tax_number, encrypted_rsin)

    def test_bsn_eleven_proof_validation(self):
        """Test BSN eleven-proof algorithm validation"""
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Test Donor {random_string(5)}"
        donor.donor_type = "Individual"
        donor.donor_email = f"test_{random_string(5)}@example.com"

        # Valid BSN (passes eleven-proof): 123456782
        self.assertTrue(donor.validate_bsn_eleven_proof("123456782"))

        # Invalid BSN (fails eleven-proof): 123456789
        self.assertFalse(donor.validate_bsn_eleven_proof("123456789"))

    def test_bsn_encryption_roundtrip(self):
        """Test that BSN encryption/decryption works correctly"""
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Test Donor {random_string(5)}"
        donor.donor_type = "Individual"
        donor.donor_email = f"test_{random_string(5)}@example.com"

        original_bsn = "123456782"  # Valid BSN

        # Encrypt
        encrypted = donor.encrypt_field(original_bsn)
        self.assertTrue(encrypted.startswith("ENC:"))
        self.assertTrue(donor.is_encrypted(encrypted))

        # Decrypt
        decrypted = donor.decrypt_field(encrypted)
        self.assertEqual(decrypted, original_bsn)

    def test_full_save_with_bsn_then_reload_and_validate(self):
        """
        Integration test: Save donor with BSN, reload, and validate.

        This simulates the real-world scenario where:
        1. Donor is saved with valid BSN (gets encrypted)
        2. Document is reloaded from database (BSN is encrypted)
        3. Validation runs (e.g., during child table update)

        This should not raise any validation errors.
        """
        # Create and save donor with valid BSN
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Integration Test Donor {random_string(5)}"
        donor.donor_type = "Individual"
        donor.donor_email = f"integration_{random_string(5)}@example.com"
        donor.bsn_citizen_service_number = "123456782"  # Valid BSN
        donor.insert()

        donor_name = donor.name

        try:
            # Reload from database (BSN will be encrypted)
            reloaded_donor = frappe.get_doc("Donor", donor_name)

            # Verify BSN is encrypted in database
            self.assertTrue(reloaded_donor.is_encrypted(reloaded_donor.bsn_citizen_service_number))

            # Validate should pass (this was failing before the fix)
            reloaded_donor.validate()

            # Save should also work
            reloaded_donor.save()

        finally:
            # Cleanup
            frappe.delete_doc("Donor", donor_name, force=True)
