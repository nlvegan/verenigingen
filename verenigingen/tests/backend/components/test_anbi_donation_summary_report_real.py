"""
Real Integration Tests for ANBI Donation Summary Report
======================================================

Phase 5.1 Database Mock Elimination: Dutch Tax Compliance Report Testing
Replaces frappe.db.sql and frappe.db.get_single_value mocks with real database operations.

Key Improvements:
- Eliminates frappe.db.sql mocks - uses real Donation and Donor data
- Eliminates frappe.db.get_single_value mocks - uses actual Verenigingen Settings  
- Tests real Dutch tax compliance logic (BSN/RSIN fields)
- Validates authentic ANBI consent and reporting requirements
- Tests actual SQL query execution against real database schema

This approach catches real tax compliance issues, database schema problems, and 
Dutch regulatory compliance bugs that mocked tests completely miss.
"""

import frappe
from frappe.utils import add_days, today, flt

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.report.anbi_donation_summary.anbi_donation_summary import (
    execute,
    get_data,
    get_columns,
    get_conditions,
)


class TestANBIDonationSummaryReportReal(EnhancedTestCase):
    """Real integration tests for ANBI Donation Summary report without SQL mocks"""

    def setUp(self):
        """Set up real test data using Enhanced Test Factory"""
        super().setUp()
        
        # Enable ANBI functionality in real settings (replaces get_single_value mock)
        if not frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality"):
            settings = frappe.get_single("Verenigingen Settings")
            settings.enable_anbi_functionality = 1
            settings.save()
        
        # Create test donors with real Dutch tax compliance data  
        from verenigingen.tests.fixtures.dutch_validation_helpers import get_test_bsn_numbers, generate_valid_rsin
        
        valid_bsns = get_test_bsn_numbers()
        
        self.individual_donor = self.create_test_donor(
            donor_name="Jan Test Donateur",
            donor_type="Individual", 
            bsn_citizen_service_number=valid_bsns[0],  # Valid BSN that passes eleven-proof
            anbi_consent=1  # Consent given for tax reporting
        )
        
        self.organization_donor = self.create_test_donor(
            donor_name="Test Organisatie BV",
            donor_type="Organization",
            rsin_organization_tax_number=generate_valid_rsin(),  # Valid RSIN that passes validation
            anbi_consent=1
        )
        
        self.no_consent_donor = self.create_test_donor(
            donor_name="Privacy Donateur",
            donor_type="Individual",
            bsn_citizen_service_number=valid_bsns[1],  # Different valid BSN
            anbi_consent=0  # No consent - should affect reporting
        )
        
        # Create real donations with different scenarios
        self.create_donation_scenarios()

    def create_donation_scenarios(self):
        """Create realistic donation test scenarios with real database operations"""
        
        # Individual donor - multiple small donations (reportable aggregate)
        self.individual_donation_1 = self.create_test_donation(
            donor=self.individual_donor.name,
            amount=250.0,
            donation_date=add_days(today(), -60),
            paid=1,
            belastingdienst_reportable=1,
            anbi_agreement_number="ANBI-2024-001"
        )
        
        self.individual_donation_2 = self.create_test_donation(
            donor=self.individual_donor.name,
            amount=300.0,
            donation_date=add_days(today(), -30),
            paid=1,
            belastingdienst_reportable=1,
            anbi_agreement_number="ANBI-2024-001"
        )
        
        # Organization donor - large donation
        self.organization_donation = self.create_test_donation(
            donor=self.organization_donor.name,
            amount=1500.0,
            donation_date=add_days(today(), -45),
            paid=1,
            belastingdienst_reportable=1,
            anbi_agreement_number="ANBI-2024-002"
        )
        
        # No consent donor - should appear but flagged appropriately
        self.no_consent_donation = self.create_test_donation(
            donor=self.no_consent_donor.name,
            amount=100.0,
            donation_date=add_days(today(), -20),
            paid=1,
            belastingdienst_reportable=1
        )

    def test_anbi_report_execution_real_database(self):
        """Test complete ANBI report execution with real database (no SQL mocks)"""
        
        # Execute report with real database operations
        # This replaces @patch("frappe.db.sql") with actual SQL execution
        filters = {
            "from_date": add_days(today(), -90),
            "to_date": today()
        }
        
        columns, data = execute(filters)
        
        # Verify report structure from real execution
        self.assertIsInstance(columns, list)
        self.assertGreater(len(columns), 0)
        self.assertIsInstance(data, list)
        
        # Verify column structure contains Dutch tax compliance fields
        column_names = [col["fieldname"] for col in columns]
        self.assertIn("tax_id", column_names)  # BSN/RSIN field
        self.assertIn("consent_given", column_names)  # ANBI consent
        self.assertIn("reportable", column_names)  # Tax reportable flag
        
        # Data should contain our test donors from real database
        donor_names = [row.get("donor_name") for row in data]
        self.assertIn("Jan Test Donateur", donor_names)
        self.assertIn("Test Organisatie BV", donor_names)

    def test_anbi_sql_query_real_execution(self):
        """Test get_data SQL query with real database execution (eliminates SQL mocks)"""
        
        # Execute data query with real database operations
        # This replaces @patch("frappe.db.sql") with actual query execution
        filters = {
            "from_date": add_days(today(), -90),
            "to_date": today()
        }
        
        data = get_data(filters)
        
        # Verify real SQL execution returns valid data structure
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        
        # Find our test donors in real results
        individual_result = next((row for row in data if row["donor"] == self.individual_donor.name), None)
        organization_result = next((row for row in data if row["donor"] == self.organization_donor.name), None)
        
        # Verify individual donor aggregation (real database calculations)
        self.assertIsNotNone(individual_result)
        self.assertEqual(individual_result["donor_type"], "Individual")
        self.assertEqual(flt(individual_result["total_donations"]), 550.0)  # 250 + 300
        self.assertEqual(individual_result["donation_count"], 2)
        self.assertEqual(individual_result["consent_given"], 1)
        
        # Verify organization donor data (real database queries)
        self.assertIsNotNone(organization_result)
        self.assertEqual(organization_result["donor_type"], "Organization") 
        self.assertEqual(flt(organization_result["total_donations"]), 1500.0)
        self.assertEqual(organization_result["donation_count"], 1)

    def test_dutch_tax_id_field_logic_real(self):
        """Test Dutch BSN/RSIN field logic with real database operations"""
        
        # Test that SQL query correctly selects BSN for individuals, RSIN for organizations
        # This validates the actual database schema and field references
        filters = {"from_date": add_days(today(), -90), "to_date": today()}
        data = get_data(filters)
        
        # Find results and verify tax ID field selection
        individual_result = next((row for row in data if row["donor"] == self.individual_donor.name), None)
        organization_result = next((row for row in data if row["donor"] == self.organization_donor.name), None)
        
        # Individual should show BSN (real database field)
        self.assertIsNotNone(individual_result)
        self.assertEqual(individual_result["tax_id_value"], "123456782")
        
        # Organization should show RSIN (real database field)
        self.assertIsNotNone(organization_result) 
        self.assertEqual(organization_result["tax_id_value"], "123456789")

    def test_anbi_consent_filtering_real_database(self):
        """Test ANBI consent logic with real database state"""
        
        # Execute query to get all donors including no-consent donor
        filters = {"from_date": add_days(today(), -90), "to_date": today()}
        data = get_data(filters)
        
        # Verify consent field comes from real database
        no_consent_result = next((row for row in data if row["donor"] == self.no_consent_donor.name), None)
        
        if no_consent_result:  # May be filtered out depending on business logic
            self.assertEqual(no_consent_result["consent_given"], 0)
        
        # Verify donors with consent are present
        individual_result = next((row for row in data if row["donor"] == self.individual_donor.name), None)
        self.assertIsNotNone(individual_result)
        self.assertEqual(individual_result["consent_given"], 1)

    def test_anbi_settings_integration_real(self):
        """Test ANBI settings integration with real database configuration"""
        
        # Test that ANBI functionality check works with real settings
        # This replaces @patch("frappe.db.get_single_value") with actual settings query
        anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")
        self.assertTrue(anbi_enabled)
        
        # Execute report - should work when ANBI is enabled
        columns, data = execute({"from_date": today(), "to_date": today()})
        self.assertIsInstance(columns, list)
        self.assertIsInstance(data, list)
        
        # Test disabling ANBI functionality temporarily
        settings = frappe.get_single("Verenigingen Settings")
        original_setting = settings.enable_anbi_functionality
        settings.enable_anbi_functionality = 0
        settings.save()
        
        try:
            # Should return empty results when ANBI disabled
            columns, data = execute({"from_date": today(), "to_date": today()})
            self.assertEqual(len(data), 0)
            
        finally:
            # Restore original setting
            settings.enable_anbi_functionality = original_setting
            settings.save()

    def test_donation_aggregation_real_sql(self):
        """Test donation aggregation logic with real SQL execution"""
        
        # Create additional donation for aggregation testing
        additional_donation = self.create_test_donation(
            donor=self.individual_donor.name,
            amount=150.0,
            donation_date=add_days(today(), -10),
            paid=1,
            belastingdienst_reportable=1
        )
        
        # Execute real SQL aggregation
        filters = {"from_date": add_days(today(), -90), "to_date": today()}
        data = get_data(filters)
        
        # Find individual donor result
        individual_result = next((row for row in data if row["donor"] == self.individual_donor.name), None)
        self.assertIsNotNone(individual_result)
        
        # Verify real SQL aggregation calculations  
        self.assertEqual(flt(individual_result["total_donations"]), 700.0)  # 250 + 300 + 150
        self.assertEqual(individual_result["donation_count"], 3)
        
        # Verify date range calculations (MIN/MAX from real SQL)
        self.assertIsNotNone(individual_result["first_donation"])
        self.assertIsNotNone(individual_result["last_donation"])

    def test_report_filtering_real_database_operations(self):
        """Test report filtering with real database queries"""
        
        # Test date range filtering with real SQL WHERE clauses
        recent_only_filters = {
            "from_date": add_days(today(), -25),
            "to_date": today()
        }
        
        recent_data = get_data(recent_only_filters)
        
        # Should exclude donations older than 25 days (real date filtering)
        # Only no_consent_donation and individual_donation_2 should be included
        total_results = len(recent_data)
        self.assertGreaterEqual(total_results, 1)  # At least some recent donations
        
        # Verify date filtering worked with real database operations
        for row in recent_data:
            if row["donor"] == self.individual_donor.name:
                # Should only include more recent donation, not the 60-day old one
                self.assertLess(flt(row["total_donations"]), 550.0)  # Less than full total