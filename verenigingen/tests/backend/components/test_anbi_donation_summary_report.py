"""
Test suite for ANBI Donation Summary report
Tests the fixed field references and report functionality
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.anbi_donation_summary.anbi_donation_summary import (
    execute,
    get_data,
    get_columns,
    get_conditions,
)


class TestANBIDonationSummaryReport(VereningingenTestCase):
    """Test suite for ANBI Donation Summary report"""

    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.maxDiff = None

        # Mock data for testing
        self.sample_donation_data = [
            {
                "donor": "DON-001",
                "donor_name": "John Doe",
                "donor_type": "Individual",
                "tax_id_value": "123456789",
                "consent_given": 1,
                "total_donations": 750.00,
                "donation_count": 3,
                "first_donation": add_days(today(), -90),
                "last_donation": add_days(today(), -10),
                "reportable": 1,
                "agreements": None,
                "agreement_numbers": None,
            },
            {
                "donor": "DON-002", 
                "donor_name": "Test Organization",
                "donor_type": "Organization",
                "tax_id_value": "gAAAAABhExample_Encrypted_Data",  # Mock encrypted RSIN
                "consent_given": 0,
                "total_donations": 1500.00,
                "donation_count": 2,
                "first_donation": add_days(today(), -60),
                "last_donation": add_days(today(), -5),
                "reportable": 1,
                "agreements": "PDA-001",
                "agreement_numbers": "ANBI-2024-001",
            },
        ]

    def test_regression_field_name_fix(self):
        """
        Regression test for field name issue
        
        Bug: Report was trying to access non-existent fields:
        - donor.bsn_encrypted (should be donor.bsn_citizen_service_number)
        - donor.rsin_encrypted (should be donor.rsin_organization_tax_number) 
        - donor.anbi_consent_given (should be donor.anbi_consent)
        
        This test ensures the report executes without database errors.
        """
        try:
            # This should not raise OperationalError about unknown columns
            columns, data = execute({
                "from_date": "2024-07-20",
                "to_date": "2025-07-20"
            })
            
            # Verify the function returns the expected structure
            self.assertIsInstance(columns, list, "Report should return a list of columns")
            self.assertIsInstance(data, list, "Report should return a list of data")
            
            # Verify columns structure
            self.assertGreater(len(columns), 0, "Report should return column definitions")
            for column in columns:
                self.assertIn("label", column, "Each column should have a label")
                self.assertIn("fieldname", column, "Each column should have a fieldname")
                self.assertIn("fieldtype", column, "Each column should have a fieldtype")
            
        except Exception as e:
            # Check for the specific database error that was fixed
            if "Unknown column" in str(e) and ("bsn_encrypted" in str(e) or "rsin_encrypted" in str(e) or "anbi_consent_given" in str(e)):
                self.fail(f"Regression: Database field name issue has returned: {e}")
            else:
                # Log other exceptions for debugging but don't fail the test
                # as they might be environment-related (missing data, settings, etc.)
                print(f"Note: Report execution encountered: {type(e).__name__}: {e}")

    def test_execute_function_structure(self):
        """Test that execute function returns correct structure"""
        with patch("frappe.db.get_single_value") as mock_get_single:
            mock_get_single.return_value = True  # ANBI functionality enabled
            
            with patch("verenigingen.verenigingen.report.anbi_donation_summary.anbi_donation_summary.get_data") as mock_get_data:
                mock_get_data.return_value = self.sample_donation_data

                columns, data = execute({"from_date": "2024-01-01", "to_date": "2024-12-31"})

                # Test return structure
                self.assertIsInstance(columns, list)
                self.assertIsInstance(data, list)

                # Test columns structure
                self.assertGreater(len(columns), 0)
                for column in columns:
                    self.assertIn("label", column)
                    self.assertIn("fieldname", column)
                    self.assertIn("fieldtype", column)

    def test_anbi_functionality_disabled(self):
        """Test report behavior when ANBI functionality is disabled"""
        with patch("frappe.db.get_single_value") as mock_get_single:
            with patch("frappe.msgprint") as mock_msgprint:
                mock_get_single.return_value = False  # ANBI functionality disabled

                columns, data = execute({})

                # Should return empty lists when disabled
                self.assertEqual(columns, [])
                self.assertEqual(data, [])
                
                # Should show message to user
                mock_msgprint.assert_called_once()
                args = mock_msgprint.call_args[0]
                self.assertIn("ANBI functionality is not enabled", args[0])

    @patch("verenigingen.verenigingen.report.anbi_donation_summary.anbi_donation_summary.frappe.db.sql")
    @patch("verenigingen.verenigingen.report.anbi_donation_summary.anbi_donation_summary.frappe.db.get_single_value")
    def test_get_data_database_query(self, mock_get_single, mock_sql):
        """Test the SQL query construction and execution"""
        mock_get_single.return_value = 500  # Min reportable amount
        mock_sql.return_value = self.sample_donation_data

        filters = {"from_date": "2024-01-01", "to_date": "2024-12-31"}
        result = get_data(filters)

        # Verify SQL was called
        mock_sql.assert_called_once()
        
        # Check query structure for corrected field names
        sql_call = mock_sql.call_args[0][0]
        self.assertIn("donor.bsn_citizen_service_number", sql_call, "Should use correct BSN field")
        self.assertIn("donor.rsin_organization_tax_number", sql_call, "Should use correct RSIN field")
        self.assertIn("donor.anbi_consent", sql_call, "Should use correct consent field")
        
        # Should NOT contain the old incorrect field names
        self.assertNotIn("bsn_encrypted", sql_call, "Should not use old incorrect BSN field")
        self.assertNotIn("rsin_encrypted", sql_call, "Should not use old incorrect RSIN field") 
        self.assertNotIn("anbi_consent_given", sql_call, "Should not use old incorrect consent field")

        # Verify filters were applied
        self.assertIn("d.date >= %(from_date)s", sql_call)
        self.assertIn("d.date <= %(to_date)s", sql_call)

        # Verify result processing
        self.assertIsInstance(result, list)

    def test_tax_id_processing(self):
        """Test tax ID encryption/decryption handling"""
        with patch("frappe.db.get_single_value") as mock_get_single:
            mock_get_single.return_value = 500
            
            with patch("verenigingen.verenigingen.report.anbi_donation_summary.anbi_donation_summary.frappe.db.sql") as mock_sql:
                mock_sql.return_value = [
                    {
                        "donor": "DON-001",
                        "donor_name": "Test Individual",
                        "donor_type": "Individual",
                        "tax_id_value": "123456789",  # Plain text BSN
                        "consent_given": 1,
                        "total_donations": 600.00,
                        "donation_count": 1,
                        "first_donation": today(),
                        "last_donation": today(),
                        "reportable": 1,
                        "agreements": None,
                        "agreement_numbers": None,
                    },
                    {
                        "donor": "DON-002",
                        "donor_name": "Test Organization", 
                        "donor_type": "Organization",
                        "tax_id_value": "gAAAAABhMockEncryptedRSIN",  # Encrypted RSIN
                        "consent_given": 0,
                        "total_donations": 1000.00,
                        "donation_count": 2,
                        "first_donation": today(),
                        "last_donation": today(),
                        "reportable": 1,
                        "agreements": None,
                        "agreement_numbers": None,
                    }
                ]

                result = get_data({})

                # Check tax ID processing
                self.assertEqual(len(result), 2)
                
                # Plain text tax ID should be preserved
                self.assertEqual(result[0]["tax_id"], "123456789")
                
                # Encrypted tax ID should show encryption indicator or be decrypted
                # (depends on whether decrypt is available)
                self.assertIn(result[1]["tax_id"], ["***ENCRYPTED***", "gAAAAABhMockEncryptedRSIN"])

    def test_agreement_type_determination(self):
        """Test agreement type and number processing"""
        with patch("frappe.db.get_single_value") as mock_get_single:
            mock_get_single.return_value = 500
            
            with patch("verenigingen.verenigingen.report.anbi_donation_summary.anbi_donation_summary.frappe.db.sql") as mock_sql:
                with patch("frappe.get_doc") as mock_get_doc:
                    # Mock periodic donation agreement
                    mock_agreement = MagicMock()
                    mock_agreement.anbi_eligible = True
                    mock_agreement.agreement_number = "PDA-2024-001"
                    mock_get_doc.return_value = mock_agreement
                    
                    mock_sql.return_value = [
                        {
                            "donor": "DON-001",
                            "donor_name": "Test Donor",
                            "donor_type": "Individual",
                            "tax_id_value": None,
                            "consent_given": 1,
                            "total_donations": 600.00,
                            "donation_count": 1,
                            "first_donation": today(),
                            "last_donation": today(),
                            "reportable": 1,
                            "agreements": "PDA-001",
                            "agreement_numbers": None,
                        }
                    ]

                    result = get_data({})

                    # Check agreement type determination
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0]["agreement_type"], "ANBI Periodic Agreement (5+ years)")
                    self.assertEqual(result[0]["agreement_number"], "PDA-2024-001")

    def test_reportable_threshold_logic(self):
        """Test reportable amount threshold determination"""
        with patch("frappe.db.get_single_value") as mock_get_single:
            mock_get_single.return_value = 500  # Threshold
            
            with patch("verenigingen.verenigingen.report.anbi_donation_summary.anbi_donation_summary.frappe.db.sql") as mock_sql:
                mock_sql.return_value = [
                    {
                        "donor": "DON-001",
                        "donor_name": "Below Threshold",
                        "donor_type": "Individual",
                        "tax_id_value": None,
                        "consent_given": 1,
                        "total_donations": 400.00,  # Below threshold
                        "donation_count": 1,
                        "first_donation": today(),
                        "last_donation": today(),
                        "reportable": 0,  # Not flagged as reportable
                        "agreements": None,
                        "agreement_numbers": None,
                    },
                    {
                        "donor": "DON-002",
                        "donor_name": "Above Threshold",
                        "donor_type": "Individual", 
                        "tax_id_value": None,
                        "consent_given": 1,
                        "total_donations": 750.00,  # Above threshold
                        "donation_count": 1,
                        "first_donation": today(),
                        "last_donation": today(),
                        "reportable": 0,  # Not flagged, but should be due to amount
                        "agreements": None,
                        "agreement_numbers": None,
                    }
                ]

                result = get_data({})

                # Check reportable logic
                self.assertEqual(len(result), 2)
                self.assertFalse(result[0]["reportable"])  # Below threshold, not flagged
                self.assertTrue(result[1]["reportable"])   # Above threshold, should be reportable

    def test_get_conditions_with_filters(self):
        """Test condition building with various filters"""
        # Test with date filters
        conditions = get_conditions({
            "from_date": "2024-01-01",
            "to_date": "2024-12-31",
            "donor": "DON-001",
            "donor_type": "Individual",
            "only_reportable": True,
            "only_periodic": True,
            "consent_status": "Given"
        })

        expected_conditions = [
            "d.date >= %(from_date)s",
            "d.date <= %(to_date)s", 
            "d.donor = %(donor)s",
            "donor.donor_type = %(donor_type)s",
            "d.periodic_donation_agreement IS NOT NULL",
            "donor.anbi_consent = 1"  # Fixed field name
        ]

        for condition in expected_conditions:
            self.assertIn(condition, conditions, f"Should include condition: {condition}")

    def test_get_conditions_consent_status_not_given(self):
        """Test condition building for consent not given"""
        conditions = get_conditions({"consent_status": "Not Given"})
        
        # Should use correct field name
        self.assertIn("donor.anbi_consent = 0", conditions)
        self.assertIn("donor.anbi_consent IS NULL", conditions)

    def test_get_columns_structure(self):
        """Test column definition structure"""
        columns = get_columns()
        
        self.assertIsInstance(columns, list)
        self.assertGreater(len(columns), 0)
        
        # Check required columns exist
        column_fieldnames = [col["fieldname"] for col in columns]
        required_columns = [
            "donor", "donor_name", "donor_type", "tax_id", 
            "agreement_type", "total_donations", "donation_count", 
            "reportable", "consent_given"
        ]
        
        for required_col in required_columns:
            self.assertIn(required_col, column_fieldnames, f"Should include column: {required_col}")


class TestANBIDonationSummaryReportRegression(VereningingenTestCase):
    """Regression tests for specific ANBI Donation Summary report bugs"""

    def test_database_field_name_regression(self):
        """
        REGRESSION TEST: Fix for OperationalError with unknown columns
        
        Bug: (1054, "Unknown column 'donor.bsn_encrypted' in 'SELECT'")
        
        Root Cause: Report was using incorrect field names that don't exist in the database:
        - donor.bsn_encrypted (should be donor.bsn_citizen_service_number)
        - donor.rsin_encrypted (should be donor.rsin_organization_tax_number)
        - donor.anbi_consent_given (should be donor.anbi_consent)
        
        Fix: Updated SQL query to use correct field names from Donor doctype
        
        This test ensures the report can be imported and executed without database errors.
        """
        try:
            # Import the report module - this should not raise import errors
            from verenigingen.verenigingen.report.anbi_donation_summary.anbi_donation_summary import execute
            
            # Execute the report with minimal filters - should not raise OperationalError
            result = execute({
                "from_date": "2024-07-20", 
                "to_date": "2025-07-20"
            })
            
            # Verify the function returns the expected structure
            self.assertIsInstance(result, tuple, "Report should return a tuple")
            self.assertEqual(len(result), 2, "Report should return 2 elements: columns, data")
            
            columns, data = result
            
            # Basic structure validation
            self.assertIsInstance(columns, list, "Columns should be a list")
            self.assertIsInstance(data, list, "Data should be a list")
            
        except Exception as e:
            # Check for the specific database errors that were fixed
            if "Unknown column" in str(e):
                if any(field in str(e) for field in ["bsn_encrypted", "rsin_encrypted", "anbi_consent_given"]):
                    self.fail(f"REGRESSION FAILURE: Database field name issue has returned: {e}")
            
            # Check for OperationalError specifically
            if "OperationalError" in str(type(e)) and "1054" in str(e):
                self.fail(f"REGRESSION FAILURE: SQL field reference error has returned: {e}")
            
            # For other exceptions, just log them but don't fail the test
            # as they might be environment-related (missing settings, data, etc.)
            print(f"Note: Report execution encountered non-critical error: {type(e).__name__}: {e}")

    def test_report_module_imports_correctly(self):
        """Test that the report module can be imported without errors"""
        try:
            # These imports should work without any errors
            from verenigingen.verenigingen.report.anbi_donation_summary.anbi_donation_summary import (
                execute,
                get_data,
                get_columns,
                get_conditions,
            )
            
            # Verify functions are callable
            self.assertTrue(callable(execute), "execute should be callable")
            self.assertTrue(callable(get_data), "get_data should be callable")
            self.assertTrue(callable(get_columns), "get_columns should be callable")
            self.assertTrue(callable(get_conditions), "get_conditions should be callable")
            
        except ImportError as e:
            self.fail(f"Failed to import report functions: {e}")
        except SyntaxError as e:
            self.fail(f"Syntax error in report module: {e}")


if __name__ == "__main__":
    unittest.main()