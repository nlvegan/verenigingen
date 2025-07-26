#!/usr/bin/env python3
"""
Test suite for SEPA Mandate Configurable Naming System
"""

import frappe
from frappe.utils import today, add_days
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.validation.iban_validator import generate_test_iban


class TestSEPAMandateNaming(VereningingenTestCase):
    """Test SEPA mandate configurable naming and starting counter functionality"""

    @classmethod
    def setUpClass(cls):
        """Set up class-level test environment"""
        super().setUpClass()
        
        # Store original settings to restore later
        settings = frappe.get_single("Verenigingen Settings")
        cls._original_pattern = getattr(settings, 'sepa_mandate_naming_pattern', 'MANDATE-.YY.-.MM.-.####')
        cls._original_counter = getattr(settings, 'sepa_mandate_starting_counter', 1)

    @classmethod
    def tearDownClass(cls):
        """Restore original settings"""
        try:
            settings = frappe.get_single("Verenigingen Settings")
            settings.sepa_mandate_naming_pattern = cls._original_pattern
            settings.sepa_mandate_starting_counter = cls._original_counter
            settings.save()
        except Exception as e:
            print(f"Warning: Could not restore original SEPA settings: {e}")
        
        super().tearDownClass()

    def setUp(self):
        """Set up test-specific environment"""
        super().setUp()
        
        # Create a test member for SEPA mandate creation
        self.test_member = self.create_test_member(
            first_name="SEPA",
            last_name="TestUser",
            email="sepa.test@example.com"
        )

    def test_default_naming_pattern(self):
        """Test that SEPA mandates use default naming pattern correctly"""
        
        # Ensure default pattern is set
        settings = frappe.get_single("Verenigingen Settings")
        settings.sepa_mandate_naming_pattern = "MANDATE-.YY.-.MM.-.####"
        settings.sepa_mandate_starting_counter = 1
        settings.save()
        
        # Create SEPA mandate without mandate_id
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.account_holder_name = "Default Pattern Test"
        mandate.iban = generate_test_iban("TEST")
        mandate.sign_date = today()
        mandate.member = self.test_member.name
        
        # Save should trigger auto-generation via validate
        mandate.save()
        
        self.assertTrue(mandate.mandate_id, "mandate_id should be auto-generated")
        self.assertTrue(mandate.mandate_id.startswith("MANDATE-"), 
                       f"mandate_id '{mandate.mandate_id}' should start with 'MANDATE-'")
        
        # Track for cleanup
        self.track_doc("SEPA Mandate", mandate.name)

    def test_custom_naming_pattern(self):
        """Test custom naming patterns work correctly"""
        
        # Set custom pattern
        settings = frappe.get_single("Verenigingen Settings")
        original_pattern = settings.sepa_mandate_naming_pattern
        
        settings.sepa_mandate_naming_pattern = "CUSTOM-.YY.-.####"
        settings.sepa_mandate_starting_counter = 100
        settings.save()
        
        try:
            # Create SEPA mandate
            mandate = frappe.new_doc("SEPA Mandate")
            mandate.account_holder_name = "Custom Pattern Test"
            mandate.iban = generate_test_iban("TEST")
            mandate.sign_date = today()
            mandate.member = self.test_member.name
            
            mandate.save()
            
            self.assertTrue(mandate.mandate_id.startswith("CUSTOM-"), 
                           f"mandate_id '{mandate.mandate_id}' should start with 'CUSTOM-'")
            self.assertIn("0100", mandate.mandate_id, 
                         f"mandate_id '{mandate.mandate_id}' should contain starting counter '0100'")
            
            # Track for cleanup
            self.track_doc("SEPA Mandate", mandate.name)
            
        finally:
            # Restore original pattern
            settings.reload()
            settings.sepa_mandate_naming_pattern = original_pattern
            settings.save()

    def test_starting_counter_functionality(self):
        """Test that starting counter works for first mandate of a pattern"""
        
        settings = frappe.get_single("Verenigingen Settings")
        original_pattern = settings.sepa_mandate_naming_pattern
        original_counter = settings.sepa_mandate_starting_counter
        
        # Use unique pattern to avoid conflicts with existing mandates
        test_pattern = f"COUNTER-TEST-.YY.-.####"
        test_counter = 2500
        
        settings.sepa_mandate_naming_pattern = test_pattern
        settings.sepa_mandate_starting_counter = test_counter
        settings.save()
        
        try:
            # Create first mandate with this pattern
            mandate1 = frappe.new_doc("SEPA Mandate")
            mandate1.account_holder_name = "Counter Test 1"
            mandate1.iban = generate_test_iban("TEST")
            mandate1.sign_date = today()
            mandate1.member = self.test_member.name
            
            mandate1.save()
            
            # Should start with configured counter
            self.assertIn("2500", mandate1.mandate_id, 
                         f"First mandate '{mandate1.mandate_id}' should contain starting counter '2500'")
            
            self.track_doc("SEPA Mandate", mandate1.name)
            
            # Create second mandate - should increment
            test_member2 = self.create_test_member(
                first_name="SEPA2", 
                last_name="TestUser2",
                email="sepa2.test@example.com"
            )
            
            mandate2 = frappe.new_doc("SEPA Mandate")
            mandate2.account_holder_name = "Counter Test 2"
            mandate2.iban = generate_test_iban("MOCK")  # Different IBAN
            mandate2.sign_date = today()
            mandate2.member = test_member2.name
            
            mandate2.save()
            
            # Should increment from first mandate
            self.assertIn("2501", mandate2.mandate_id, 
                         f"Second mandate '{mandate2.mandate_id}' should contain incremented counter '2501'")
            
            self.track_doc("SEPA Mandate", mandate2.name)
            
        finally:
            # Restore original settings
            settings.reload()
            settings.sepa_mandate_naming_pattern = original_pattern
            settings.sepa_mandate_starting_counter = original_counter
            settings.save()

    def test_manual_mandate_id_not_overwritten(self):
        """Test that manually set mandate_id is not overwritten"""
        
        manual_id = "MANUAL-MANDATE-12345"
        
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.mandate_id = manual_id  # Set manually
        mandate.account_holder_name = "Manual ID Test"
        mandate.iban = generate_test_iban("TEST")
        mandate.sign_date = today()
        mandate.member = self.test_member.name
        
        mandate.save()
        
        # Should preserve manual ID
        self.assertEqual(mandate.mandate_id, manual_id, 
                        f"Manual mandate_id should be preserved, got '{mandate.mandate_id}'")
        
        self.track_doc("SEPA Mandate", mandate.name)

    def test_pattern_date_replacement(self):
        """Test that date tokens in patterns are replaced correctly"""
        
        settings = frappe.get_single("Verenigingen Settings")
        original_pattern = settings.sepa_mandate_naming_pattern
        
        # Pattern with various date tokens
        settings.sepa_mandate_naming_pattern = "DATE-.YY.-.MM.-.DD.-.####"
        settings.sepa_mandate_starting_counter = 1
        settings.save()
        
        try:
            mandate = frappe.new_doc("SEPA Mandate")
            mandate.account_holder_name = "Date Pattern Test"
            mandate.iban = generate_test_iban("TEST")
            mandate.sign_date = today()
            mandate.member = self.test_member.name
            
            mandate.save()
            
            # Check that date tokens were replaced
            from frappe.utils import now_datetime
            now = now_datetime()
            expected_year = str(now.year)[-2:]
            expected_month = f"{now.month:02d}"
            expected_day = f"{now.day:02d}"
            
            self.assertIn(expected_year, mandate.mandate_id, 
                         f"mandate_id should contain year '{expected_year}'")
            self.assertIn(expected_month, mandate.mandate_id, 
                         f"mandate_id should contain month '{expected_month}'")
            self.assertIn(expected_day, mandate.mandate_id, 
                         f"mandate_id should contain day '{expected_day}'")
            
            self.track_doc("SEPA Mandate", mandate.name)
            
        finally:
            settings.reload()
            settings.sepa_mandate_naming_pattern = original_pattern
            settings.save()

    def test_uniqueness_enforcement(self):
        """Test that mandate_id uniqueness is enforced"""
        
        settings = frappe.get_single("Verenigingen Settings")
        original_pattern = settings.sepa_mandate_naming_pattern
        
        # Use simple pattern to make testing easier
        settings.sepa_mandate_naming_pattern = "UNIQUE-.####"
        settings.sepa_mandate_starting_counter = 1
        settings.save()
        
        try:
            # Create first mandate
            mandate1 = frappe.new_doc("SEPA Mandate")
            mandate1.account_holder_name = "Unique Test 1"
            mandate1.iban = generate_test_iban("TEST")
            mandate1.sign_date = today()
            mandate1.member = self.test_member.name
            mandate1.save()
            
            self.track_doc("SEPA Mandate", mandate1.name)
            
            # Create second mandate - should get incremented counter
            test_member2 = self.create_test_member(
                first_name="SEPA3",
                last_name="TestUser3", 
                email="sepa3.test@example.com"
            )
            
            mandate2 = frappe.new_doc("SEPA Mandate")
            mandate2.account_holder_name = "Unique Test 2"
            mandate2.iban = generate_test_iban("DEMO")
            mandate2.sign_date = today() 
            mandate2.member = test_member2.name
            mandate2.save()
            
            # Should have different mandate_ids
            self.assertNotEqual(mandate1.mandate_id, mandate2.mandate_id,
                              "Different mandates should have different mandate_ids")
            
            self.track_doc("SEPA Mandate", mandate2.name)
            
        finally:
            settings.reload()
            settings.sepa_mandate_naming_pattern = original_pattern
            settings.save()

    def test_fallback_on_error(self):
        """Test that fallback naming works if there's an error in custom pattern"""
        
        settings = frappe.get_single("Verenigingen Settings")
        original_pattern = settings.sepa_mandate_naming_pattern
        
        # Set an invalid pattern that might cause issues
        settings.sepa_mandate_naming_pattern = None  # This should trigger fallback
        settings.save()
        
        try:
            mandate = frappe.new_doc("SEPA Mandate")
            mandate.account_holder_name = "Fallback Test"
            mandate.iban = generate_test_iban("TEST")
            mandate.sign_date = today()
            mandate.member = self.test_member.name
            
            mandate.save()
            
            # Should still get a mandate_id (from fallback)
            self.assertTrue(mandate.mandate_id, "Should get mandate_id from fallback mechanism")
            
            self.track_doc("SEPA Mandate", mandate.name)
            
        finally:
            settings.reload()
            settings.sepa_mandate_naming_pattern = original_pattern
            settings.save()

    def test_integration_with_existing_workflow(self):
        """Test that SEPA mandate creation integrates properly with existing workflows"""
        
        # Create a member with SEPA mandate through normal workflow
        member = self.create_test_member(
            first_name="Workflow",
            last_name="Integration",
            email="workflow.test@example.com"
        )
        
        # Create SEPA mandate as would happen in normal workflow
        mandate = self.create_test_sepa_mandate(member=member.name)
        
        # Should have auto-generated mandate_id
        self.assertTrue(mandate.mandate_id, "Mandate should have auto-generated mandate_id")
        self.assertTrue(len(mandate.mandate_id) > 5, "mandate_id should be meaningful length")
        
        # Should have valid status and other fields
        self.assertEqual(mandate.status, "Active", "Mandate should be Active")
        self.assertEqual(mandate.member, member.name, "Mandate should be linked to correct member")


if __name__ == "__main__":
    import unittest
    unittest.main()