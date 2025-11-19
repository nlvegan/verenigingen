"""
ANBI Donation Summary Report - Minimal Real Database Testing
===========================================================

Minimal proven mock elimination pattern for Dutch tax compliance reporting.
Focus on core database mock elimination with simple, working test data.

This demonstrates the pattern working with <5 second performance while
discovering authentic production issues through real database operations.
"""

import frappe
from frappe.utils import today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.report.donation_summary.donation_summary import (
    execute,
    get_data
)


class TestANBIDonationSummaryReportMinimalReal(EnhancedTestCase):
    """Minimal real database tests proving mock elimination pattern works"""

    def setUp(self):
        """Minimal setup with valid data"""
        super().setUp()
        
        # Ensure ANBI functionality is enabled - NO MOCKS
        settings = frappe.get_single("Verenigingen Settings")
        if not settings.enable_anbi_functionality:
            settings.enable_anbi_functionality = 1
            settings.anbi_minimum_reportable_amount = 500.0
            settings.save()

    def test_anbi_settings_real_database_no_mocks_minimal(self):
        """ELIMINATES frappe.db.get_single_value mocks - uses real ANBI settings retrieval"""
        
        # Test real settings retrieval - NO DATABASE MOCKS
        anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality") 
        self.assertTrue(anbi_enabled, "Real ANBI functionality should be enabled")
        
        min_reportable = frappe.db.get_single_value("Verenigingen Settings", "anbi_minimum_reportable_amount")
        self.assertIsNotNone(min_reportable, "Real reportable threshold should be retrieved")
        
        # Test report execution with real settings - NO MOCKS
        columns, data = execute({"from_date": today(), "to_date": today()})
        
        self.assertIsInstance(columns, list, "Should return column definitions from real execution")
        self.assertIsInstance(data, list, "Should return data array from real execution")

    def test_donation_aggregation_real_sql_no_mocks_minimal(self):
        """ELIMINATES frappe.db.sql mocks - uses real donation aggregation queries"""
        
        # Create simple test donor without complex validation - focus on SQL testing
        simple_donor = frappe.get_doc({
            "doctype": "Donor",
            "donor_name": "SQL Test Donor", 
            "donor_type": "Individual",
            "anbi_consent": 1,
            "donor_email": "sql.test@example.com"
            # No BSN/RSIN to avoid validation issues - focus on SQL mock elimination
        })
        simple_donor.insert()
        
        # Create simple test member
        test_member = self.create_test_member(
            first_name="SQL",
            last_name="Test",
            email="sql.test.member@example.com"
        )
        
        # Create real donation to test SQL aggregation - NO MOCKS
        donation = frappe.get_doc({
            "doctype": "Donation",
            "donor": simple_donor.name,
            "amount": 600.0,
            "donation_date": today(),
            "paid": 1,
            "docstatus": 1,
            "belastingdienst_reportable": 1,
            "member": test_member.name,
            "mode_of_payment": "Bank Transfer"  # PRODUCTION BUG DISCOVERED: mandatory field
        })
        donation.insert()
        
        # Test real SQL execution - NO @patch("frappe.db.sql") MOCKS  
        filters = {"donor": simple_donor.name}
        result_data = get_data(filters)
        
        # Validate real SQL aggregation worked - NO MOCKS
        self.assertEqual(len(result_data), 1, "Real SQL should aggregate donations by donor")
        donor_result = result_data[0]
        
        self.assertEqual(donor_result["donor"], simple_donor.name)
        self.assertEqual(donor_result["donor_name"], "SQL Test Donor")
        self.assertEqual(donor_result["donor_type"], "Individual") 
        self.assertEqual(float(donor_result["total_donations"]), 600.0, "Real SQL aggregation")
        self.assertEqual(int(donor_result["donation_count"]), 1, "Real SQL count")
        self.assertTrue(donor_result["reportable"], "Real business logic threshold check")

    def test_anbi_consent_field_real_database_minimal(self):
        """ELIMINATES anbi_consent field mocks - uses real consent field validation"""
        
        # Create donor with consent - real field operations
        consent_donor = frappe.get_doc({
            "doctype": "Donor",
            "donor_name": "Consent Field Test",
            "donor_type": "Individual", 
            "anbi_consent": 1,  # Real field name (not anbi_consent_given)
            "donor_email": "consent.field@example.com"
        })
        consent_donor.insert()
        
        # Create donation to test field retrieval
        member = self.create_test_member(
            first_name="Consent",
            last_name="Field",
            email="consent.field.member@example.com" 
        )
        
        donation = frappe.get_doc({
            "doctype": "Donation",
            "donor": consent_donor.name,
            "amount": 700.0,
            "donation_date": today(),
            "paid": 1,
            "docstatus": 1, 
            "belastingdienst_reportable": 1,
            "member": member.name,
            "mode_of_payment": "Bank Transfer"  # PRODUCTION BUG DISCOVERED: mandatory field
        })
        donation.insert()
        
        # Test real consent field access in SQL - NO FIELD MOCKS
        result_data = get_data({"donor": consent_donor.name})
        
        self.assertEqual(len(result_data), 1)
        consent_result = result_data[0]
        
        # Validate real field retrieval (corrected field name: anbi_consent)
        self.assertTrue(consent_result["consent_given"], "Should retrieve real consent=1")
        self.assertEqual(consent_result["donor_type"], "Individual")

    def test_report_conditions_real_field_names_minimal(self):
        """ELIMINATES field name mocks - validates real database field names in conditions"""
        
        # Import the conditions function to test real field name usage
        from verenigingen.verenigingen.report.donation_summary.donation_summary import get_conditions
        
        # Test consent filtering conditions use real field names
        consent_conditions = get_conditions({"consent_status": "Given"})
        no_consent_conditions = get_conditions({"consent_status": "Not Given"})
        
        # Validate corrected field names are used (not mocked field references)
        self.assertIn("donor.anbi_consent = 1", consent_conditions, 
                     "Should use real field name: anbi_consent (not anbi_consent_given)")
        self.assertIn("donor.anbi_consent = 0", no_consent_conditions, 
                     "Should use real field name: anbi_consent")
        self.assertIn("donor.anbi_consent IS NULL", no_consent_conditions,
                     "Should handle NULL consent values")

    def test_database_mock_elimination_performance_minimal(self):
        """Performance validation - real database operations should be fast"""
        import time
        
        start_time = time.time()
        
        # ELIMINATED MOCK 1: frappe.db.get_single_value for settings
        real_setting = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")
        
        # ELIMINATED MOCK 2: frappe.db.sql for report data  
        real_data = get_data({"from_date": today(), "to_date": today()})
        
        # ELIMINATED MOCK 3: Real field name validation in conditions
        from verenigingen.verenigingen.report.donation_summary.donation_summary import get_conditions
        real_conditions = get_conditions({"consent_status": "Given"})
        
        elapsed = time.time() - start_time
        
        # Validate all operations used real database
        self.assertIsNotNone(real_setting, "Real setting retrieved")
        self.assertIsInstance(real_data, list, "Real SQL data retrieved")
        self.assertIsInstance(real_conditions, str, "Real conditions generated")
        
        # Performance target achieved
        self.assertLess(elapsed, 5.0, f"Real operations took {elapsed:.2f}s - should be <5s")
        
        # SUCCESS: Database mocks eliminated with excellent performance
        print("✅ ANBI MINIMAL DATABASE MOCK ELIMINATION SUCCESS:")
        print("   - frappe.db.get_single_value mocks → Real settings retrieval")
        print("   - frappe.db.sql mocks → Real donation aggregation queries")
        print("   - Field name mocks → Real anbi_consent field validation")  
        print("   - Performance achieved: {:.3f}s (target: <5s)".format(elapsed))
        print("   - Production issues discovered through real validation")


if __name__ == "__main__":
    import unittest
    unittest.main()