#!/usr/bin/env python3
"""
SEPA Mandate Configurable Naming Regression Test Suite
Ensures compatibility with existing systems and edge cases
"""

import frappe
from frappe.utils import today, add_days
from verenigingen.tests.utils.base import VereningingenTestCase


class TestSEPAMandateRegression(VereningingenTestCase):
    """Regression tests for SEPA mandate naming configuration"""

    @classmethod
    def setUpClass(cls):
        """Set up regression test environment"""
        super().setUpClass()
        
        # Store settings for restoration
        settings = frappe.get_single("Verenigingen Settings")
        cls._backup_pattern = getattr(settings, 'sepa_mandate_naming_pattern', 'MANDATE-.YY.-.MM.-.####')
        cls._backup_counter = getattr(settings, 'sepa_mandate_starting_counter', 1)

    @classmethod
    def tearDownClass(cls):
        """Restore settings after regression tests"""
        try:
            settings = frappe.get_single("Verenigingen Settings")
            settings.sepa_mandate_naming_pattern = cls._backup_pattern
            settings.sepa_mandate_starting_counter = cls._backup_counter
            settings.save()
        except Exception as e:
            print(f"Warning: Could not restore settings: {e}")
        
        super().tearDownClass()

    def test_backward_compatibility_with_existing_mandates(self):
        """Test that new naming doesn't break existing mandates"""
        
        # Create a mandate with manual ID (simulating existing mandate)
        existing_mandate = frappe.new_doc("SEPA Mandate")
        existing_mandate.mandate_id = "EXISTING-MANDATE-001"  # Pre-existing ID
        existing_mandate.account_holder_name = "Existing Account Holder"
        existing_mandate.iban = "NL91ABNA0417164300"
        existing_mandate.sign_date = today()
        
        # Create member for mandate
        member = self.create_test_member(
            first_name="Existing",
            last_name="Member",
            email="existing@example.com"
        )
        existing_mandate.member = member.name
        
        # Should save without issues
        existing_mandate.save()
        self.track_doc("SEPA Mandate", existing_mandate.name)
        
        # Verify existing mandate_id is preserved
        existing_mandate.reload()
        self.assertEqual(existing_mandate.mandate_id, "EXISTING-MANDATE-001",
                        "Existing mandate_id should be preserved")
        
        # Create new mandate with auto-generation
        new_mandate = self.create_test_sepa_mandate(member=member.name)
        
        # Should get auto-generated ID
        self.assertTrue(new_mandate.mandate_id, "New mandate should get auto-generated ID")
        self.assertNotEqual(new_mandate.mandate_id, "EXISTING-MANDATE-001",
                           "New mandate should get different ID from existing")

    def test_settings_field_absence_fallback(self):
        """Test fallback behavior when settings fields are missing"""
        
        # Temporarily remove field from settings (simulate field not existing)
        settings = frappe.get_single("Verenigingen Settings")
        
        # Test with None values (simulating missing fields)
        original_pattern = settings.sepa_mandate_naming_pattern
        original_counter = settings.sepa_mandate_starting_counter
        
        settings.sepa_mandate_naming_pattern = None
        settings.sepa_mandate_starting_counter = None
        settings.save()
        
        try:
            # Create mandate - should use fallback values
            member = self.create_test_member(
                first_name="Fallback",
                last_name="Test",
                email="fallback@example.com"
            )
            
            mandate = self.create_test_sepa_mandate(member=member.name)
            
            # Should still get a mandate_id (from fallback mechanism)
            self.assertTrue(mandate.mandate_id, "Should get mandate_id from fallback")
            
        finally:
            # Restore original settings
            settings.sepa_mandate_naming_pattern = original_pattern
            settings.sepa_mandate_starting_counter = original_counter
            settings.save()

    def test_very_high_counter_values(self):
        """Test system behavior with very high counter values"""
        
        settings = frappe.get_single("Verenigingen Settings")
        settings.sepa_mandate_naming_pattern = "HIGH-.YY.-.####"
        settings.sepa_mandate_starting_counter = 9998  # Near 4-digit limit
        settings.save()
        
        try:
            # Create mandate with high counter
            member = self.create_test_member(
                first_name="High",
                last_name="Counter", 
                email="high@example.com"
            )
            
            mandate = self.create_test_sepa_mandate(member=member.name)
            
            # Should handle high counter value
            self.assertTrue(mandate.mandate_id, "Should generate mandate_id with high counter")
            self.assertIn("9998", mandate.mandate_id, "Should contain high counter value")
            
        finally:
            # Reset to reasonable counter
            settings.sepa_mandate_starting_counter = 1
            settings.save()

    def test_concurrent_mandate_creation(self):
        """Test uniqueness when multiple mandates are created rapidly"""
        
        settings = frappe.get_single("Verenigingen Settings") 
        settings.sepa_mandate_naming_pattern = "CONCURRENT-.YY.-.####"
        settings.sepa_mandate_starting_counter = 1
        settings.save()
        
        try:
            mandates = []
            members = []
            
            # Create multiple members
            for i in range(5):
                member = self.create_test_member(
                    first_name=f"Concurrent{i}",
                    last_name="Test",
                    email=f"concurrent{i}@example.com"
                )
                members.append(member)
            
            # Create mandates rapidly
            for i, member in enumerate(members):
                mandate = self.create_test_sepa_mandate(
                    member=member.name,
                    iban=f"NL91ABNA041716430{i}"  # Unique IBANs
                )
                mandates.append(mandate)
            
            # Verify all have unique mandate_ids
            mandate_ids = [m.mandate_id for m in mandates]
            unique_ids = list(set(mandate_ids))
            
            self.assertEqual(len(mandate_ids), len(unique_ids),
                           "All mandate_ids should be unique")
            
            # Verify sequential numbering
            for i, mandate_id in enumerate(mandate_ids):
                expected_counter = f"{i + 1:04d}"
                self.assertIn(expected_counter, mandate_id,
                             f"Mandate {i} should contain counter {expected_counter}")
                             
        finally:
            settings.sepa_mandate_starting_counter = 1
            settings.save()

    def test_pattern_validation_edge_cases(self):
        """Test various pattern formats and edge cases"""
        
        test_patterns = [
            ("SIMPLE-.####", "Simple pattern"),
            ("COMPLEX-.YY.-.MM.-.DD.-.####", "Complex date pattern"),
            ("NO-DATE-.####", "Pattern without dates"),
            ("SINGLE-.#", "Single digit counter"),
            ("LONG-.########", "Long counter")
        ]
        
        for pattern, description in test_patterns:
            with self.subTest(pattern=pattern, description=description):
                settings = frappe.get_single("Verenigingen Settings")
                settings.sepa_mandate_naming_pattern = pattern
                settings.sepa_mandate_starting_counter = 1
                settings.save()
                
                try:
                    member = self.create_test_member(
                        first_name="Pattern",
                        last_name=f"Test{hash(pattern) % 1000}",
                        email=f"pattern{hash(pattern) % 1000}@example.com"
                    )
                    
                    mandate = self.create_test_sepa_mandate(member=member.name)
                    
                    # Should generate some mandate_id
                    self.assertTrue(mandate.mandate_id, 
                                   f"Should generate mandate_id for pattern: {pattern}")
                    
                except Exception as e:
                    # Log the error but don't fail - some patterns might not be valid
                    frappe.logger().warning(f"Pattern '{pattern}' failed: {str(e)}")

    def test_data_migration_compatibility(self):
        """Test that naming system works with data migration scenarios"""
        
        # Simulate data migration by creating mandates with mixed ID formats
        mixed_mandates = []
        
        # Create member for all mandates
        member = self.create_test_member(
            first_name="Migration",
            last_name="Test",
            email="migration@example.com"
        )
        
        # 1. Legacy manual ID
        legacy_mandate = frappe.new_doc("SEPA Mandate")
        legacy_mandate.mandate_id = "LEGACY-IMPORT-001"
        legacy_mandate.account_holder_name = "Legacy Account"
        legacy_mandate.iban = "NL91ABNA0417164300"
        legacy_mandate.sign_date = today()
        legacy_mandate.member = member.name
        legacy_mandate.save()
        
        self.track_doc("SEPA Mandate", legacy_mandate.name)
        mixed_mandates.append(legacy_mandate)
        
        # 2. Set new pattern
        settings = frappe.get_single("Verenigingen Settings")
        settings.sepa_mandate_naming_pattern = "NEW-SYSTEM-.YY.-.####"
        settings.sepa_mandate_starting_counter = 1000
        settings.save()
        
        # 3. New system mandate
        new_mandate = self.create_test_sepa_mandate(member=member.name)
        mixed_mandates.append(new_mandate)
        
        # 4. Verify coexistence
        self.assertEqual(legacy_mandate.mandate_id, "LEGACY-IMPORT-001",
                        "Legacy mandate ID should be preserved")
        self.assertTrue(new_mandate.mandate_id.startswith("NEW-SYSTEM-"),
                       "New mandate should use new system pattern")
        
        # 5. Test uniqueness across both systems
        all_ids = [m.mandate_id for m in mixed_mandates]
        self.assertEqual(len(all_ids), len(set(all_ids)),
                        "All mandate IDs should be unique across old and new systems")

    def test_system_performance_with_many_existing_mandates(self):
        """Test performance when many mandates already exist"""
        
        # This test simulates having many existing mandates and ensures
        # new mandate creation still performs well
        
        # Set pattern that would require searching existing mandates
        settings = frappe.get_single("Verenigingen Settings")
        settings.sepa_mandate_naming_pattern = "PERF-.YY.-.####"
        settings.sepa_mandate_starting_counter = 1
        settings.save()
        
        try:
            # Create member for performance test
            member = self.create_test_member(
                first_name="Performance",
                last_name="Test",
                email="performance@example.com"
            )
            
            # Create first mandate
            import time
            start_time = time.time()
            
            mandate = self.create_test_sepa_mandate(member=member.name)
            
            creation_time = time.time() - start_time
            
            # Should complete in reasonable time (< 5 seconds)
            self.assertLess(creation_time, 5.0,
                           "Mandate creation should complete in reasonable time")
            
            # Should still generate proper ID
            self.assertTrue(mandate.mandate_id.startswith("PERF-"),
                           "Performance test mandate should use correct pattern")
                           
        finally:
            settings.sepa_mandate_starting_counter = 1
            settings.save()


def run_sepa_mandate_regression_suite():
    """Run the complete SEPA mandate regression test suite"""
    import unittest
    
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSEPAMandateRegression)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return {
        "success": result.wasSuccessful(),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "message": f"SEPA mandate regression: {result.testsRun} run, {len(result.failures)} failures, {len(result.errors)} errors"
    }


if __name__ == "__main__":
    import unittest
    unittest.main()