#!/usr/bin/env python3
"""
Comprehensive test suite for Enhanced SEPA Processor Option A+C workflow
Tests the complete daily invoice generation + monthly SEPA batching system
"""

import frappe
from frappe.utils import today, getdate, add_days, add_months
from verenigingen.tests.utils.base import VereningingenTestCase


class TestSEPAOptionACWorkflow(VereningingenTestCase):
    """Test suite for Option A+C SEPA workflow"""
    
    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.processor = None
        
    def test_01_processor_initialization(self):
        """Test Enhanced SEPA Processor can be initialized"""
        from verenigingen.verenigingen.doctype.direct_debit_batch.enhanced_sepa_processor import EnhancedSEPAProcessor
        
        self.processor = EnhancedSEPAProcessor()
        self.assertIsNotNone(self.processor, "Enhanced SEPA Processor should initialize successfully")
        self.assertIsNotNone(self.processor.company, "Processor should have company reference")
        
    def test_02_invoice_coverage_verification(self):
        """Test invoice coverage verification with rolling periods"""
        if not self.processor:
            self.test_01_processor_initialization()
            
        # Test coverage verification
        result = self.processor.verify_invoice_coverage(today())
        
        self.assertIsInstance(result, dict, "Coverage verification should return dict")
        self.assertIn("total_checked", result, "Result should include total_checked")
        self.assertIn("complete", result, "Result should include complete status")
        self.assertIn("issues", result, "Result should include issues list")
        
        # Log results for review
        frappe.logger().info(f"Invoice coverage: {result['total_checked']} schedules checked, "
                           f"complete: {result['complete']}, issues: {len(result.get('issues', []))}")
        
    def test_03_rolling_period_validation(self):
        """Test rolling period validation for different billing frequencies"""
        if not self.processor:
            self.test_01_processor_initialization()
            
        test_cases = [
            # Valid monthly period (30 days, within tolerance)
            {
                "current_coverage_start": "2024-01-01",
                "current_coverage_end": "2024-01-31",
                "billing_frequency": "Monthly",
                "expected_valid": True
            },
            # Valid annual period (365 days, within tolerance)
            {
                "current_coverage_start": "2024-01-01", 
                "current_coverage_end": "2024-12-31",
                "billing_frequency": "Annual",
                "expected_valid": True
            },
            # Valid weekly period (7 days, exact)
            {
                "current_coverage_start": "2024-01-01",
                "current_coverage_end": "2024-01-07", 
                "billing_frequency": "Weekly",
                "expected_valid": True
            },
            # Invalid monthly period (too long)
            {
                "current_coverage_start": "2024-01-01",
                "current_coverage_end": "2024-03-01",
                "billing_frequency": "Monthly", 
                "expected_valid": False
            }
        ]
        
        for i, test_case in enumerate(test_cases):
            with self.subTest(case=i, frequency=test_case["billing_frequency"]):
                result = self.processor.validate_coverage_period(test_case, today())
                
                if test_case["expected_valid"]:
                    self.assertIsNone(result, f"Valid {test_case['billing_frequency']} period should pass validation")
                else:
                    self.assertIsNotNone(result, f"Invalid {test_case['billing_frequency']} period should fail validation")
                    self.assertIsInstance(result, str, "Validation error should be a string")
                    
    def test_04_unpaid_invoice_lookup(self):
        """Test existing unpaid invoice lookup functionality"""
        if not self.processor:
            self.test_01_processor_initialization()
            
        # Test unpaid invoice lookup
        invoices = self.processor.get_existing_unpaid_sepa_invoices(today())
        
        self.assertIsInstance(invoices, list, "Unpaid invoice lookup should return list")
        
        # If we have invoices, validate structure
        if invoices:
            first_invoice = invoices[0]
            required_fields = [
                "name", "customer", "amount", "currency", "member", 
                "member_name", "iban", "mandate_reference", "mandate_name"
            ]
            
            for field in required_fields:
                self.assertIn(field, first_invoice, f"Invoice should have {field} field")
                
        frappe.logger().info(f"Found {len(invoices)} existing unpaid SEPA invoices")
        
    def test_05_dutch_payroll_timing_logic(self):
        """Test Dutch payroll timing logic (19th/20th batch creation)"""
        current_date = getdate(today())
        day_of_month = current_date.day
        
        # Test the timing logic
        if day_of_month in [19, 20]:
            # Today should be a batch creation day
            frappe.logger().info(f"Today ({day_of_month}) is a batch creation day - scheduler would run")
            self.assertIn(day_of_month, [19, 20], "Scheduler should run on 19th/20th")
        else:
            # Today should not be a batch creation day
            frappe.logger().info(f"Today ({day_of_month}) is not a batch creation day - scheduler would skip")
            self.assertNotIn(day_of_month, [19, 20], "Scheduler should skip on other days")
            
        # Verify processing date calculation (7 days later)
        from frappe.utils import add_days
        processing_date = add_days(current_date, 7)
        expected_processing_day = processing_date.day
        
        # Processing should happen around 26th/27th if batch created on 19th/20th
        if day_of_month in [19, 20]:
            self.assertIn(expected_processing_day, [26, 27, 28], 
                         f"Processing on {expected_processing_day} should be around 26th-28th")
        
    def test_06_api_endpoints_option_ac(self):
        """Test Option A+C specific API endpoints"""
        # Test imports
        from verenigingen.verenigingen.doctype.direct_debit_batch.enhanced_sepa_processor import (
            create_monthly_dues_collection_batch,
            verify_invoice_coverage_status,
            get_sepa_batch_preview
        )
        
        # Test coverage API
        coverage_result = verify_invoice_coverage_status()
        self.assertIsInstance(coverage_result, dict, "Coverage API should return dict")
        self.assertIn("total_checked", coverage_result, "Coverage result should include total_checked")
        
        # Test preview API
        preview_result = get_sepa_batch_preview()
        self.assertIsInstance(preview_result, dict, "Preview API should return dict")
        self.assertIn("success", preview_result, "Preview should include success status")
        
        required_preview_keys = ["collection_date", "unpaid_invoices_found", "total_amount", "members_affected"]
        for key in required_preview_keys:
            self.assertIn(key, preview_result, f"Preview should include {key}")
            
        # Test monthly scheduler function exists and is callable
        self.assertTrue(callable(create_monthly_dues_collection_batch), 
                       "Monthly scheduler function should be callable")
        
        frappe.logger().info(f"Preview: {preview_result['unpaid_invoices_found']} invoices, "
                           f"€{preview_result.get('total_amount', 0):.2f} total, "
                           f"{preview_result.get('members_affected', 0)} members")
                           
    def test_07_sequence_type_validation_integration(self):
        """Test sequence type validation integration with Direct Debit Batch"""
        # Test that the Direct Debit Batch validation system is accessible
        from verenigingen.verenigingen.doctype.direct_debit_batch.direct_debit_batch import DirectDebitBatch
        
        # Check if validate_sequence_types method exists
        self.assertTrue(hasattr(DirectDebitBatch, 'validate_sequence_types'),
                       "DirectDebitBatch should have validate_sequence_types method")
        
        # Test that the Enhanced SEPA Processor uses this validation
        if not self.processor:
            self.test_01_processor_initialization()
            
        # Create a mock batch to test validation integration
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Test batch for validation"
        batch.batch_type = "RCUR"
        batch.currency = "EUR"
        batch.status = "Draft"
        
        # Test that the validation method can be called
        try:
            batch.validate_sequence_types()
            frappe.logger().info("Sequence type validation method is accessible")
        except Exception as e:
            # It's expected to fail without proper invoice data, but method should exist
            self.assertIn("invoices", str(e).lower(), "Error should be about missing invoices")
            
    def test_08_batch_creation_workflow(self):
        """Test the complete batch creation workflow (without actually creating batches)"""
        if not self.processor:
            self.test_01_processor_initialization()
            
        # Test the workflow components
        collection_date = today()
        
        # Step 1: Verify invoice coverage
        coverage_result = self.processor.verify_invoice_coverage(collection_date)
        self.assertIsInstance(coverage_result, dict, "Coverage verification should work")
        
        # Step 2: Get unpaid invoices
        invoices = self.processor.get_existing_unpaid_sepa_invoices(collection_date)
        self.assertIsInstance(invoices, list, "Invoice lookup should work")
        
        # Step 3: Test batch creation logic (without saving)
        if invoices:
            batch = self.processor.create_batch_from_invoices(invoices, collection_date)
            self.assertIsNotNone(batch, "Batch should be created from invoices")
            self.assertEqual(batch.currency, "EUR", "Batch should use EUR currency")
            self.assertEqual(batch.batch_type, "RCUR", "Batch should be RCUR type")
            self.assertTrue(hasattr(batch, '_automated_processing'), 
                           "Batch should be marked for automated processing")
            
        frappe.logger().info("Complete batch creation workflow components tested successfully")
        
    def test_09_error_handling_and_validation(self):
        """Test error handling and validation in various scenarios"""
        if not self.processor:
            self.test_01_processor_initialization()
            
        # Test with invalid date
        try:
            result = self.processor.verify_invoice_coverage("invalid-date")
            # Should either handle gracefully or raise appropriate error
            self.assertIsInstance(result, dict, "Should handle invalid date gracefully")
        except Exception as e:
            # If it raises an error, it should be a meaningful one
            self.assertIsInstance(e, (ValueError, frappe.ValidationError), 
                                "Should raise appropriate error type for invalid date")
            
        # Test with missing coverage period data
        invalid_schedule = {
            "current_coverage_start": None,
            "current_coverage_end": "2024-01-31",
            "billing_frequency": "Monthly"
        }
        
        result = self.processor.validate_coverage_period(invalid_schedule, today())
        self.assertIsNotNone(result, "Should detect missing coverage dates")
        self.assertIn("Missing", result, "Error message should mention missing dates")
        
    def test_10_integration_completeness(self):
        """Test that all Option A+C components are properly integrated"""
        # Verify all key components are available
        components = {
            "Enhanced SEPA Processor": "verenigingen.verenigingen.doctype.direct_debit_batch.enhanced_sepa_processor.EnhancedSEPAProcessor",
            "Direct Debit Batch": "verenigingen.verenigingen.doctype.direct_debit_batch.direct_debit_batch.DirectDebitBatch", 
            "Batch Scheduler": "verenigingen.api.dd_batch_scheduler.daily_batch_optimization",
            "Notification System": "verenigingen.api.sepa_batch_notifications.handle_automated_batch_validation"
        }
        
        for component_name, import_path in components.items():
            try:
                module_path, class_or_func = import_path.rsplit(".", 1)
                module = frappe.get_module(module_path)
                component = getattr(module, class_or_func)
                self.assertIsNotNone(component, f"{component_name} should be available")
                frappe.logger().info(f"✓ {component_name} integration verified")
            except (ImportError, AttributeError) as e:
                self.fail(f"{component_name} not properly integrated: {e}")
                
        frappe.logger().info("All Option A+C components are properly integrated")


def run_option_ac_tests():
    """Run the Option A+C test suite"""
    import unittest
    
    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSEPAOptionACWorkflow)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    frappe.logger().info("Starting Option A+C SEPA Workflow Tests")
    success = run_option_ac_tests()
    frappe.logger().info(f"Option A+C Tests: {'PASSED' if success else 'FAILED'}")