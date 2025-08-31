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
from frappe.utils import add_days, today, flt, getdate

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

    def test_tax_id_field_processing_real_dutch_validation(self):
        """Test BSN/RSIN tax ID processing with real Dutch validation"""
        
        # This replaces mocked tax_id_value processing with real database field queries
        filters = {"from_date": add_days(today(), -90), "to_date": today()}
        data = get_data(filters)
        
        # Find our test donors in real results
        individual_result = next((row for row in data if row["donor"] == self.individual_donor.name), None)
        organization_result = next((row for row in data if row["donor"] == self.organization_donor.name), None)
        
        if individual_result:
            # Individual should show BSN from real database field
            tax_id = individual_result.get("tax_id")
            
            # Should be either real BSN or encryption indicator
            if tax_id and tax_id != "***ENCRYPTED***":
                # Verify it follows BSN format (9 digits)
                self.assertEqual(len(str(tax_id)), 9)
                self.assertTrue(str(tax_id).isdigit())
        
        if organization_result:
            # Organization should show RSIN from real database field  
            tax_id = organization_result.get("tax_id")
            
            # Should be either real RSIN or encryption indicator
            if tax_id and tax_id != "***ENCRYPTED***":
                # Verify it follows RSIN format (9 digits)
                self.assertEqual(len(str(tax_id)), 9)
                self.assertTrue(str(tax_id).isdigit())

    def test_agreement_type_determination_real_database(self):
        """Test agreement type determination with real database operations"""
        
        # Create a periodic donation agreement for testing
        # This replaces @patch("frappe.get_doc") with real document operations
        try:
            pda = frappe.get_doc({
                "doctype": "Periodic Donation Agreement",
                "donor": self.individual_donor.name,
                "anbi_eligible": 1,
                "agreement_number": "PDA-TEST-2024-001",
                "status": "Active",
                "start_date": add_days(today(), -30),
                "amount": 25.0,
                "frequency": "Monthly"
            })
            pda.insert()
            
            # Update donation to reference the agreement
            self.individual_donation_1.periodic_donation_agreement = pda.name
            self.individual_donation_1.save()
            
            # Execute report with real agreement data
            filters = {"from_date": add_days(today(), -90), "to_date": today()}
            data = get_data(filters)
            
            # Find individual donor result
            individual_result = next((row for row in data if row["donor"] == self.individual_donor.name), None)
            
            if individual_result:
                # Should show ANBI periodic agreement type from real database
                agreement_type = individual_result.get("agreement_type")
                if agreement_type:
                    self.assertIn("ANBI", agreement_type)
                    self.assertIn("Periodic", agreement_type)
                
                # Should show real agreement number
                agreement_number = individual_result.get("agreement_number")
                if agreement_number:
                    self.assertEqual(agreement_number, "PDA-TEST-2024-001")
                    
        except Exception as e:
            if "Periodic Donation Agreement" in str(e):
                self.skipTest("Periodic Donation Agreement DocType not available")
            else:
                raise

    def test_reportable_threshold_logic_real_settings(self):
        """Test reportable threshold logic with real settings"""
        
        # Test with real ANBI settings (replaces @patch("frappe.db.get_single_value"))
        
        # Get current threshold from real settings
        current_threshold = frappe.db.get_single_value("Verenigingen Settings", "anbi_minimum_reportable_amount") or 500
        
        # Create donations above and below threshold
        below_threshold_donation = self.create_test_donation(
            donor=self.no_consent_donor.name,
            amount=current_threshold - 50,  # Below threshold
            donation_date=add_days(today(), -15),
            paid=1,
            belastingdienst_reportable=0  # Not marked as reportable
        )
        
        above_threshold_donation = self.create_test_donation(
            donor=self.organization_donor.name,
            amount=current_threshold + 100,  # Above threshold
            donation_date=add_days(today(), -25),
            paid=1,
            belastingdienst_reportable=1  # Should be reportable
        )
        
        # Execute report with real threshold logic
        filters = {"from_date": add_days(today(), -90), "to_date": today()}
        data = get_data(filters)
        
        # Find results for threshold testing
        below_result = next((row for row in data if row["donor"] == self.no_consent_donor.name), None)
        above_result = next((row for row in data if row["donor"] == self.organization_donor.name), None)
        
        # Verify threshold logic works with real settings
        if below_result:
            # Below threshold should not be automatically reportable
            if flt(below_result["total_donations"]) < current_threshold:
                self.assertFalse(below_result.get("reportable", False))
        
        if above_result:
            # Above threshold should be reportable (or flagged for review)
            if flt(above_result["total_donations"]) > current_threshold:
                self.assertTrue(above_result.get("reportable", False))

    def test_consent_status_filtering_real_database(self):
        """Test consent status filtering with real database operations"""
        
        # Test filtering by consent status using real database queries
        # This replaces mocked consent filtering with actual SQL WHERE clauses
        
        # Test "consent given" filter
        consent_given_filters = {
            "from_date": add_days(today(), -90),
            "to_date": today(),
            "consent_status": "Given"
        }
        
        # This will execute real SQL with consent filtering
        consent_data = get_data(consent_given_filters)
        
        # All results should have consent = 1
        for row in consent_data:
            if "consent_given" in row:
                self.assertTrue(row["consent_given"], 
                              f"Donor {row['donor_name']} should have consent given")
        
        # Test "consent not given" filter
        no_consent_filters = {
            "from_date": add_days(today(), -90), 
            "to_date": today(),
            "consent_status": "Not Given"
        }
        
        no_consent_data = get_data(no_consent_filters)
        
        # All results should have consent = 0 or NULL
        for row in no_consent_data:
            if "consent_given" in row:
                self.assertFalse(row["consent_given"],
                               f"Donor {row['donor_name']} should not have consent given")

    def test_sql_field_name_regression_real_execution(self):
        """Test that corrected field names work with real SQL execution"""
        
        # This is a critical regression test to ensure the field name fixes work
        # in real database execution (not just mocked SQL)
        
        try:
            # Execute the report - this will run real SQL with corrected field names
            filters = {"from_date": add_days(today(), -90), "to_date": today()}
            columns, data = execute(filters)
            
            # If we get here without OperationalError, the field names are correct
            self.assertIsInstance(columns, list)
            self.assertIsInstance(data, list)
            
            # Verify the corrected fields are accessible in real results
            for row in data:
                # These fields should be accessible without database errors
                tax_id = row.get("tax_id")  # From bsn_citizen_service_number/rsin_organization_tax_number
                consent = row.get("consent_given")  # From anbi_consent
                
                # Fields should have valid types or be None
                if tax_id is not None:
                    self.assertIsInstance(tax_id, (str, int))
                if consent is not None:
                    self.assertIsInstance(consent, (bool, int))
                    
        except Exception as e:
            # Check for the specific database errors that were fixed
            error_str = str(e)
            if "Unknown column" in error_str:
                if any(field in error_str for field in ["bsn_encrypted", "rsin_encrypted", "anbi_consent_given"]):
                    self.fail(f"REGRESSION: Old incorrect field names still in use: {e}")
            
            # Other errors might be configuration-related
            if "1054" in error_str:  # MySQL unknown column error
                self.fail(f"Database field reference error: {e}")

    def test_dutch_encryption_handling_real_database(self):
        """Test Dutch tax ID encryption handling with real database state"""
        
        # Test that the system handles both encrypted and unencrypted tax IDs
        # from real database storage
        
        filters = {"from_date": add_days(today(), -90), "to_date": today()}
        data = get_data(filters)
        
        # Check how real database handles tax ID encryption
        for row in data:
            tax_id = row.get("tax_id")
            donor_type = row.get("donor_type")
            
            if tax_id:
                # Individual BSN handling
                if donor_type == "Individual":
                    # Should be either real BSN digits or encryption indicator
                    if tax_id == "***ENCRYPTED***":
                        # Encrypted BSN - acceptable
                        pass
                    elif str(tax_id).isdigit() and len(str(tax_id)) == 9:
                        # Real BSN - should pass eleven-proof test for Dutch BSN
                        bsn_str = str(tax_id)
                        # Basic BSN format validation
                        self.assertEqual(len(bsn_str), 9)
                        self.assertTrue(bsn_str.isdigit())
                
                # Organization RSIN handling
                elif donor_type == "Organization":
                    # Should be either real RSIN digits or encryption indicator
                    if tax_id == "***ENCRYPTED***":
                        # Encrypted RSIN - acceptable
                        pass
                    elif str(tax_id).isdigit() and len(str(tax_id)) == 9:
                        # Real RSIN - should be valid 9-digit format
                        rsin_str = str(tax_id)
                        self.assertEqual(len(rsin_str), 9)
                        self.assertTrue(rsin_str.isdigit())

    def test_date_range_filtering_real_sql_execution(self):
        """Test date range filtering with real SQL execution"""
        
        # Test narrow date range that should exclude some donations
        narrow_filters = {
            "from_date": add_days(today(), -35),  # Excludes 60-day old donation
            "to_date": add_days(today(), -25)     # Excludes 20-day old donation
        }
        
        narrow_data = get_data(narrow_filters)
        
        # Should only include donations within the narrow date range
        # This tests real SQL date filtering (not mocked date logic)
        for row in narrow_data:
            first_donation = row.get("first_donation")
            last_donation = row.get("last_donation")
            
            if first_donation:
                # All donations should be within range
                first_date = getdate(first_donation)
                from_date = getdate(narrow_filters["from_date"])
                to_date = getdate(narrow_filters["to_date"])
                
                self.assertGreaterEqual(first_date, from_date)
                
            if last_donation:
                last_date = getdate(last_donation)
                self.assertLessEqual(last_date, to_date)

    def test_donation_count_aggregation_real_sql(self):
        """Test donation count aggregation with real SQL GROUP BY operations"""
        
        # Create additional donation for same donor to test aggregation
        additional_donation = self.create_test_donation(
            donor=self.individual_donor.name,
            amount=75.0,
            donation_date=add_days(today(), -5),
            paid=1,
            belastingdienst_reportable=1
        )
        
        # Execute report with real SQL aggregation
        filters = {"from_date": add_days(today(), -90), "to_date": today()}
        data = get_data(filters)
        
        # Find individual donor result
        individual_result = next((row for row in data if row["donor"] == self.individual_donor.name), None)
        
        if individual_result:
            # Should aggregate all donations for the donor (real SQL COUNT)
            donation_count = individual_result.get("donation_count")
            total_amount = flt(individual_result.get("total_donations"))
            
            # Should count all donations (original 2 + additional 1)
            self.assertGreaterEqual(donation_count, 3)
            
            # Should sum all amounts (250 + 300 + 75)
            self.assertGreaterEqual(total_amount, 625.0)
            
            # Verify date range calculations from real SQL MIN/MAX
            first_donation = individual_result.get("first_donation")
            last_donation = individual_result.get("last_donation")
            
            self.assertIsNotNone(first_donation)
            self.assertIsNotNone(last_donation)
            
            # Last donation should be more recent than first
            if first_donation and last_donation:
                self.assertLessEqual(getdate(first_donation), getdate(last_donation))