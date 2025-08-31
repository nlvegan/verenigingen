"""
ANBI Donation Summary Report - Optimized Real Database Testing  
==============================================================

Proven mock elimination pattern applied to Dutch tax compliance reporting.
OPTIMIZED for <5 second execution with valid Dutch tax identifiers.

Eliminates database mocks for business logic while preserving infrastructure mocks.
Discovers real production issues through authentic Dutch compliance testing.
"""

import frappe
from frappe.utils import add_days, today
from unittest.mock import patch
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.report.anbi_donation_summary.anbi_donation_summary import (
    execute,
    get_data,
    get_columns,
    get_conditions,
)


class TestANBIDonationSummaryReportOptimizedReal(EnhancedTestCase):
    """Optimized real database tests for ANBI donation summary - eliminates critical database mocks"""

    def setUp(self):
        """Lightweight setup - minimal test data creation with VALID Dutch identifiers"""
        super().setUp()
        
        # Import Dutch validation helpers for VALID BSN/RSIN
        from verenigingen.tests.fixtures.dutch_validation_helpers import (
            generate_valid_bsn, 
            generate_valid_rsin
        )
        
        # Generate valid BSN/RSIN that pass eleven-proof validation
        self.valid_bsn = generate_valid_bsn()
        self.valid_rsin = generate_valid_rsin()
        
        # Ensure ANBI functionality is enabled - NO MOCKS
        settings = frappe.get_single("Verenigingen Settings")
        settings.enable_anbi_functionality = 1
        settings.anbi_minimum_reportable_amount = 500.0
        settings.save()

    def test_anbi_settings_real_database_no_mocks(self):
        """ELIMINATES frappe.db.get_single_value mocks - uses real ANBI settings"""
        
        # Test real settings retrieval - NO DATABASE MOCKS
        anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")
        self.assertTrue(anbi_enabled, "Real ANBI functionality should be enabled")
        
        min_reportable = frappe.db.get_single_value("Verenigingen Settings", "anbi_minimum_reportable_amount")
        self.assertEqual(float(min_reportable), 500.0, "Real reportable threshold should be retrieved")
        
        # Test report execution with real settings - NO MOCKS
        columns, data = execute({"from_date": today(), "to_date": today()})
        
        self.assertIsInstance(columns, list, "Should return column definitions from real execution")
        self.assertIsInstance(data, list, "Should return data array from real execution")

    def test_donation_aggregation_real_database_optimized(self):
        """ELIMINATES frappe.db.sql mocks - uses real donation aggregation with valid BSN"""
        
        # Create test donor with VALID BSN - NO MOCKS
        test_donor = frappe.get_doc({
            "doctype": "Donor",
            "donor_name": "Valid BSN Donor",
            "donor_type": "Individual",
            "bsn_citizen_service_number": self.valid_bsn,  # Valid BSN that passes validation
            "anbi_consent": 1,
            "donor_email": "valid.bsn@example.com"
        })
        test_donor.insert()
        self.track_doc("Donor", test_donor.name)
        
        # Create test member for donation context
        test_member = self.create_test_member(
            first_name="ANBI",
            last_name="Test",
            email=f"anbi.{frappe.utils.random_string(4)}@example.com"
        )
        
        # Create real donations - NO MOCKS
        donation_amounts = [600.0, 400.0]  # Total: 1000.0, above threshold
        
        for amount in donation_amounts:
            donation = frappe.get_doc({
                "doctype": "Donation",
                "donor": test_donor.name,
                "amount": amount,
                "donation_date": today(),
                "paid": 1,
                "docstatus": 1,
                "belastingdienst_reportable": 1 if amount >= 500 else 0,
                "member": test_member.name
            })
            donation.insert()
            self.track_doc("Donation", donation.name)
        
        # Test real donation data retrieval - NO DATABASE MOCKS
        filters = {"from_date": today(), "to_date": today(), "donor": test_donor.name}
        result_data = get_data(filters)
        
        # Validate real aggregation results - NO MOCKS
        self.assertEqual(len(result_data), 1, "Should aggregate donations by donor")
        donor_data = result_data[0]
        
        self.assertEqual(donor_data["donor"], test_donor.name)
        self.assertEqual(donor_data["donor_name"], "Valid BSN Donor")
        self.assertEqual(donor_data["donor_type"], "Individual")
        self.assertEqual(float(donor_data["total_donations"]), 1000.0, "Real aggregation should sum amounts")
        self.assertEqual(int(donor_data["donation_count"]), 2, "Real count should match donations created")
        self.assertTrue(donor_data["reportable"], "Should be reportable above threshold")

    def test_bsn_field_access_real_database_optimized(self):
        """ELIMINATES BSN field mocks - validates real Dutch BSN field usage with valid data"""
        
        # Create donor with VALID BSN - NO MOCKS
        bsn_donor = frappe.get_doc({
            "doctype": "Donor",
            "donor_name": "BSN Field Test",
            "donor_type": "Individual",
            "bsn_citizen_service_number": self.valid_bsn,  # Valid BSN
            "anbi_consent": 1,
            "donor_email": "bsn.test@example.com"
        })
        bsn_donor.insert()
        self.track_doc("Donor", bsn_donor.name)
        
        # Create test member and donation
        member = self.create_test_member(
            first_name="BSN",
            last_name="Test",
            email=f"bsn.{frappe.utils.random_string(4)}@example.com"
        )
        
        donation = frappe.get_doc({
            "doctype": "Donation",
            "donor": bsn_donor.name,
            "amount": 750.0,
            "donation_date": today(),
            "paid": 1,
            "docstatus": 1,
            "belastingdienst_reportable": 1,
            "member": member.name
        })
        donation.insert()
        self.track_doc("Donation", donation.name)
        
        # Test real BSN field access in report query - NO FIELD MOCKS
        result_data = get_data({"donor": bsn_donor.name})
        
        self.assertEqual(len(result_data), 1)
        bsn_result = result_data[0]
        
        # Validate real BSN field retrieval (correct field name: bsn_citizen_service_number)
        self.assertEqual(bsn_result["tax_id_value"], self.valid_bsn, "Should retrieve real valid BSN")
        self.assertEqual(bsn_result["donor_type"], "Individual")
        self.assertTrue(bsn_result["consent_given"], "Should retrieve real consent status")

    def test_rsin_field_access_real_database_optimized(self):
        """ELIMINATES RSIN field mocks - validates real Dutch RSIN field usage with valid data"""
        
        # Create donor with VALID RSIN - NO MOCKS
        rsin_donor = frappe.get_doc({
            "doctype": "Donor",
            "donor_name": "Valid RSIN Organization",
            "donor_type": "Organization",
            "rsin_organization_tax_number": self.valid_rsin,  # Valid RSIN
            "anbi_consent": 1,
            "donor_email": "rsin.test@example.com"
        })
        rsin_donor.insert()
        self.track_doc("Donor", rsin_donor.name)
        
        # Create test member and donation
        member = self.create_test_member(
            first_name="RSIN",
            last_name="Test",
            email=f"rsin.{frappe.utils.random_string(4)}@example.com"
        )
        
        donation = frappe.get_doc({
            "doctype": "Donation",
            "donor": rsin_donor.name,
            "amount": 1200.0,
            "donation_date": today(),
            "paid": 1,
            "docstatus": 1,
            "belastingdienst_reportable": 1,
            "member": member.name
        })
        donation.insert()
        self.track_doc("Donation", donation.name)
        
        # Test real RSIN field access - NO FIELD MOCKS
        result_data = get_data({"donor": rsin_donor.name})
        
        self.assertEqual(len(result_data), 1)
        rsin_result = result_data[0]
        
        # Validate real RSIN field retrieval (correct field name: rsin_organization_tax_number)
        self.assertEqual(rsin_result["tax_id_value"], self.valid_rsin, "Should retrieve real valid RSIN")
        self.assertEqual(rsin_result["donor_type"], "Organization")
        self.assertTrue(rsin_result["consent_given"], "Should retrieve real consent status")

    def test_anbi_consent_field_real_database_optimized(self):
        """ELIMINATES anbi_consent mocks - uses real consent field validation with valid data"""
        
        # Create donors with different consent status - real field operations with valid identifiers
        consent_donor = frappe.get_doc({
            "doctype": "Donor",
            "donor_name": "Consent Given Valid",
            "donor_type": "Individual",
            "bsn_citizen_service_number": self.valid_bsn,  # Valid BSN
            "anbi_consent": 1,  # Real field name, not anbi_consent_given
            "donor_email": "consent.given@example.com"
        })
        consent_donor.insert()
        self.track_doc("Donor", consent_donor.name)
        
        # Test consent filtering with real field access - NO MOCKS
        consent_conditions = get_conditions({"consent_status": "Given"})
        
        # Validate real field names are used (corrected from anbi_consent_given)
        self.assertIn("donor.anbi_consent = 1", consent_conditions, "Should use correct consent field name")
        
        # Execute report with consent filter - real database query
        member = self.create_test_member(
            first_name="Consent",
            last_name="Test", 
            email=f"consent.{frappe.utils.random_string(4)}@example.com"
        )
        
        donation = frappe.get_doc({
            "doctype": "Donation",
            "donor": consent_donor.name,
            "amount": 800.0,
            "donation_date": today(),
            "paid": 1,
            "docstatus": 1,
            "belastingdienst_reportable": 1,
            "member": member.name
        })
        donation.insert()
        self.track_doc("Donation", donation.name)
        
        consent_data = get_data({"consent_status": "Given"})
        
        # Should retrieve based on real consent field values
        consent_donors = [d["donor_name"] for d in consent_data if d.get("donor_name")]
        self.assertIn("Consent Given Valid", consent_donors, "Should find donor with real consent=1")

    @patch("frappe.utils.password.decrypt")  # Mock ONLY encryption infrastructure
    def test_encrypted_tax_id_with_real_database_optimized(self, mock_decrypt):
        """Tests encrypted tax ID with real database - preserves infrastructure mock only"""
        mock_decrypt.return_value = "123456789"  # Mock decryption result
        
        # Create donor with encrypted tax ID - real database storage
        encrypted_donor = frappe.get_doc({
            "doctype": "Donor",
            "donor_name": "Encrypted Tax ID Test",
            "donor_type": "Organization",
            "rsin_organization_tax_number": "gAAAAABhMockEncryptedData",  # Simulated encrypted
            "anbi_consent": 1,
            "donor_email": "encrypted.test@example.com"
        })
        encrypted_donor.insert()
        self.track_doc("Donor", encrypted_donor.name)
        
        # Create donation - real database operation
        member = self.create_test_member(
            first_name="Encrypted",
            last_name="Test",
            email=f"encrypted.{frappe.utils.random_string(4)}@example.com"
        )
        
        donation = frappe.get_doc({
            "doctype": "Donation", 
            "donor": encrypted_donor.name,
            "amount": 950.0,
            "donation_date": today(),
            "paid": 1,
            "docstatus": 1,
            "belastingdienst_reportable": 1,
            "member": member.name
        })
        donation.insert()
        self.track_doc("Donation", donation.name)
        
        # Test with real database retrieval and mocked decryption
        result_data = get_data({"donor": encrypted_donor.name})
        
        self.assertEqual(len(result_data), 1)
        encrypted_result = result_data[0]
        
        # Real database field retrieved, infrastructure decryption mocked
        self.assertEqual(encrypted_result["tax_id_value"], "gAAAAABhMockEncryptedData")
        mock_decrypt.assert_called_with("gAAAAABhMockEncryptedData")

    def test_database_mock_elimination_summary_anbi_optimized(self):
        """Summary test - document database mocks eliminated with performance validation"""
        import time
        
        start_time = time.time()
        
        # Create test data with real operations
        summary_donor = frappe.get_doc({
            "doctype": "Donor",
            "donor_name": "Summary Test Valid",
            "donor_type": "Individual",
            "bsn_citizen_service_number": self.valid_bsn,  # Valid BSN
            "anbi_consent": 1,
            "donor_email": "summary.test@example.com"
        })
        summary_donor.insert()
        self.track_doc("Donor", summary_donor.name)
        
        member = self.create_test_member(
            first_name="Summary",
            last_name="Test",
            email=f"summary.{frappe.utils.random_string(4)}@example.com"
        )
        
        # ELIMINATED MOCK 1: frappe.db.get_single_value for ANBI settings
        real_anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")
        real_min_reportable = frappe.db.get_single_value("Verenigingen Settings", "anbi_minimum_reportable_amount")
        
        # ELIMINATED MOCK 2: frappe.db.sql for donation aggregation queries
        donation = frappe.get_doc({
            "doctype": "Donation",
            "donor": summary_donor.name,
            "amount": 650.0,
            "donation_date": today(),
            "paid": 1,
            "docstatus": 1,
            "belastingdienst_reportable": 1,
            "member": member.name
        })
        donation.insert()
        self.track_doc("Donation", donation.name)
        
        real_donation_data = get_data({"donor": summary_donor.name})  # Real SQL execution
        
        # ELIMINATED MOCK 3: Donor field access (bsn_citizen_service_number, anbi_consent)
        real_donor_doc = frappe.get_doc("Donor", summary_donor.name)  # Real retrieval
        
        elapsed = time.time() - start_time
        
        # Validation: All operations used real database, not mocks
        self.assertIsNotNone(real_anbi_enabled, "Real ANBI setting retrieved")
        self.assertIsNotNone(real_min_reportable, "Real threshold retrieved")
        self.assertEqual(len(real_donation_data), 1, "Real donation query executed")
        self.assertEqual(real_donor_doc.donor_name, "Summary Test Valid", "Real donor retrieval")
        
        # Performance validation: <5 second target achieved
        self.assertLess(elapsed, 5.0, f"Real operations took {elapsed:.2f}s - should be <5s")
        
        # SUCCESS: Critical database mocks eliminated with good performance
        print("✅ ANBI OPTIMIZED DATABASE MOCK ELIMINATION SUCCESS:")
        print("   - frappe.db.get_single_value mocks → Real ANBI settings retrieval")
        print("   - frappe.db.sql mocks → Real donation aggregation queries")
        print("   - BSN/RSIN field mocks → Real valid Dutch tax ID validation")
        print("   - anbi_consent field mocks → Real consent field access")
        print("   - Infrastructure mocks preserved (encryption/decryption)")
        print(f"   - Performance: {elapsed:.3f}s (target: <5s)")


if __name__ == "__main__":
    import unittest
    unittest.main()