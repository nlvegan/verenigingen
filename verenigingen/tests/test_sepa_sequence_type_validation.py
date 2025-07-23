"""
Test SEPA Sequence Type Validation System
Tests the new validation system that properly fails when RCUR is used instead of FRST
"""

import unittest

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestSEPASequenceTypeValidation(VereningingenTestCase):
    """Test suite for SEPA sequence type validation in batches"""
    
    def setUp(self):
        super().setUp()
        
        # Create test member with unique name
        self.member = self.create_test_member(
            first_name="SeqTest",
            last_name="Member",
            email=f"seqtest{frappe.utils.random_string(6)}@example.com"
        )
        
        # Create test mandate
        self.mandate = self.create_test_sepa_mandate(
            member=self.member.name,
            bank_code="TEST"
        )
        
        # Create test membership and invoice
        self.membership = self.create_test_membership(
            member=self.member.name,
            membership_type=self.create_test_membership_type().name
        )
        
        # Create test invoice
        self.invoice = self.create_test_sales_invoice(
            customer=self.member.customer,
            grand_total=100.00
        )

    def test_sequence_type_validation_critical_error(self):
        """Test that validation fails when RCUR is used for first mandate usage"""
        # Create batch document
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Test Batch - Critical Error"
        batch.batch_type = "RCUR"
        batch.currency = "EUR"
        
        # Add invoice with incorrect sequence type (RCUR when it should be FRST)
        batch.append("invoices", {
            "invoice": self.invoice.name,
            "membership": self.membership.name,
            "member": self.member.name,
            "member_name": self.member.full_name,
            "amount": 100.00,
            "currency": "EUR",
            "iban": self.member.iban,
            "mandate_reference": self.mandate.mandate_id,
            "sequence_type": "RCUR",  # Wrong! Should be FRST for first usage
            "status": "Pending",
        })
        
        # Manual validation should throw error
        with self.assertRaises(frappe.exceptions.ValidationError) as context:
            batch.insert()
        
        # Check error message mentions SEPA compliance
        error_message = str(context.exception)
        self.assertIn("RCUR used for first mandate usage", error_message)
        self.assertIn("compliance violation", error_message)

    def test_sequence_type_validation_warning(self):
        """Test that validation creates warnings for other mismatches"""
        # First create a successful usage to set up mandate history
        from verenigingen.verenigingen.doctype.sepa_mandate_usage.sepa_mandate_usage import create_mandate_usage_record
        
        usage_name = create_mandate_usage_record(
            mandate_name=self.mandate.name,
            reference_doctype="Sales Invoice",
            reference_name="TEST-INV-001",
            amount=50.00
        )
        
        # Mark as collected
        self.mandate.reload()
        usage_record = self.mandate.usage_history[0]
        usage_record.status = "Collected"
        usage_record.processing_date = today()
        self.mandate.save()
        
        # Create batch with FRST when it should be RCUR (warning, not critical)
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Test Batch - Warning"
        batch.batch_type = "FRST"
        batch.currency = "EUR"
        
        batch.append("invoices", {
            "invoice": self.invoice.name,
            "membership": self.membership.name,
            "member": self.member.name,
            "member_name": self.member.full_name,
            "amount": 100.00,
            "currency": "EUR",
            "iban": self.member.iban,
            "mandate_reference": self.mandate.mandate_id,
            "sequence_type": "FRST",  # Wrong! Should be RCUR for second usage
            "status": "Pending",
        })
        
        # Should insert successfully but with warnings
        batch.insert()
        self.track_doc("Direct Debit Batch", batch.name)
        
        # Check validation results
        self.assertEqual(batch.validation_status, "Warnings")
        self.assertIsNotNone(batch.validation_warnings)
        
        warnings = frappe.parse_json(batch.validation_warnings)
        self.assertEqual(len(warnings), 1)
        
        warning = warnings[0]
        self.assertEqual(warning["invoice"], self.invoice.name)
        self.assertIn("mismatch", warning["issue"])
        self.assertEqual(warning["expected"], "RCUR")
        self.assertEqual(warning["actual"], "FRST")

    def test_sequence_type_auto_assignment(self):
        """Test that correct sequence types are auto-assigned when missing"""
        # Create batch without sequence type
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Test Batch - Auto Assignment"
        batch.batch_type = "FRST"
        batch.currency = "EUR"
        
        batch.append("invoices", {
            "invoice": self.invoice.name,
            "membership": self.membership.name,
            "member": self.member.name,
            "member_name": self.member.full_name,
            "amount": 100.00,
            "currency": "EUR",
            "iban": self.member.iban,
            "mandate_reference": self.mandate.mandate_id,
            # No sequence_type specified - should be auto-assigned
            "status": "Pending",
        })
        
        # Should insert successfully with auto-assigned sequence type
        batch.insert()
        self.track_doc("Direct Debit Batch", batch.name)
        
        # Check that sequence type was auto-assigned
        self.assertEqual(batch.validation_status, "Passed")
        invoice_row = batch.invoices[0]
        self.assertEqual(invoice_row.sequence_type, "FRST")  # Should be FRST for first usage

    def test_automated_processing_flag(self):
        """Test that automated processing flag affects validation behavior"""
        # Create batch with critical error but automated processing flag
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Test Batch - Automated"
        batch.batch_type = "RCUR"
        batch.currency = "EUR"
        batch._automated_processing = True  # Set automated flag
        
        batch.append("invoices", {
            "invoice": self.invoice.name,
            "membership": self.membership.name,
            "member": self.member.name,
            "member_name": self.member.full_name,
            "amount": 100.00,
            "currency": "EUR",
            "iban": self.member.iban,
            "mandate_reference": self.mandate.mandate_id,
            "sequence_type": "RCUR",  # Wrong! Should be FRST
            "status": "Pending",
        })
        
        # Should insert successfully in automated mode (doesn't throw)
        batch.insert()
        self.track_doc("Direct Debit Batch", batch.name)
        
        # But should have critical errors recorded
        self.assertEqual(batch.validation_status, "Critical Errors")
        self.assertIsNotNone(batch.validation_errors)
        
        errors = frappe.parse_json(batch.validation_errors)
        self.assertEqual(len(errors), 1)
        
        error = errors[0]
        self.assertEqual(error["invoice"], self.invoice.name)
        self.assertIn("compliance violation", error["issue"])

    def test_notification_system_integration(self):
        """Test that notification system properly handles validation results"""
        from verenigingen.api.sepa_batch_notifications import handle_automated_batch_validation
        
        # Create batch with critical errors
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Test Batch - Notifications"
        batch.batch_type = "RCUR"
        batch.currency = "EUR"
        batch._automated_processing = True
        
        batch.append("invoices", {
            "invoice": self.invoice.name,
            "membership": self.membership.name,
            "member": self.member.name,
            "member_name": self.member.full_name,
            "amount": 100.00,
            "currency": "EUR",
            "iban": self.member.iban,
            "mandate_reference": self.mandate.mandate_id,
            "sequence_type": "RCUR",
            "status": "Pending",
        })
        
        batch.insert()
        self.track_doc("Direct Debit Batch", batch.name)
        
        # Test notification handler
        critical_errors = frappe.parse_json(batch.validation_errors)
        warnings = []
        
        result = handle_automated_batch_validation(batch, critical_errors, warnings)
        
        # Should be blocked due to critical errors
        self.assertEqual(result["action"], "blocked")
        self.assertTrue(result["requires_intervention"])
        
        # Check that status was updated
        batch.reload()
        self.assertEqual(batch.status, "Validation Failed")

    def test_get_mandate_sequence_type_api(self):
        """Test the sequence type determination API"""
        from verenigingen.verenigingen.doctype.sepa_mandate_usage.sepa_mandate_usage import get_mandate_sequence_type
        
        # First usage should be FRST
        result = get_mandate_sequence_type(self.mandate.name, "TEST-INV-001")
        self.assertEqual(result["sequence_type"], "FRST")
        self.assertIn("First usage", result["reason"])
        
        # Create and collect first usage
        from verenigingen.verenigingen.doctype.sepa_mandate_usage.sepa_mandate_usage import create_mandate_usage_record
        
        create_mandate_usage_record(
            mandate_name=self.mandate.name,
            reference_doctype="Sales Invoice",
            reference_name="TEST-INV-001",
            amount=50.00
        )
        
        # Mark as collected
        self.mandate.reload()
        usage_record = self.mandate.usage_history[0]
        usage_record.status = "Collected"
        usage_record.processing_date = today()
        self.mandate.save()
        
        # Second usage should be RCUR
        result = get_mandate_sequence_type(self.mandate.name, "TEST-INV-002")
        self.assertEqual(result["sequence_type"], "RCUR")
        self.assertIn("Recurring usage", result["reason"])

    def test_validation_error_messages(self):
        """Test that validation error messages are clear and actionable"""
        # Create batch with multiple error types
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Test Batch - Error Messages"
        batch.batch_type = "RCUR"
        batch.currency = "EUR"
        batch._automated_processing = True
        
        # Add invoice with missing mandate
        batch.append("invoices", {
            "invoice": self.invoice.name,
            "membership": self.membership.name,
            "member": self.member.name,
            "member_name": self.member.full_name,
            "amount": 100.00,
            "currency": "EUR",
            "iban": self.member.iban,
            "mandate_reference": "NONEXISTENT-MANDATE",  # This mandate doesn't exist
            "sequence_type": "RCUR",
            "status": "Pending",
        })
        
        batch.insert()
        self.track_doc("Direct Debit Batch", batch.name)
        
        # Should have critical error for missing mandate
        self.assertEqual(batch.validation_status, "Critical Errors")
        errors = frappe.parse_json(batch.validation_errors)
        
        self.assertEqual(len(errors), 1)
        error = errors[0]
        self.assertEqual(error["invoice"], self.invoice.name)
        self.assertIn("No active mandate found", error["issue"])
        self.assertEqual(error["mandate_reference"], "NONEXISTENT-MANDATE")
    
    def test_error_handler_integration(self):
        """Test error handler integration with sequence type validation"""
        try:
            from verenigingen.utils.sepa_error_handler import get_sepa_error_handler
            
            handler = get_sepa_error_handler()
            
            # Test that validation errors are properly categorized
            validation_error = Exception("Invalid sequence type - RCUR used for first mandate usage")
            category = handler.categorize_error(validation_error)
            self.assertEqual(category, "validation")
            
            # Test that validation errors should not be retried
            should_retry = handler.should_retry(validation_error, attempt=1)
            self.assertFalse(should_retry)
            
            # Test circuit breaker status
            status = handler.get_circuit_breaker_status()
            self.assertIn(status["state"], ["closed", "open", "half_open"])
            
        except ImportError:
            self.skipTest("Error handler optimization not available")
    
    def test_mandate_service_integration(self):
        """Test mandate service integration with sequence type validation"""
        try:
            from verenigingen.utils.sepa_mandate_service import get_sepa_mandate_service
            
            service = get_sepa_mandate_service()
            
            # Test batch sequence type determination
            test_pairs = [(self.mandate.name, self.invoice.name)]
            sequence_types = service.get_sequence_types_batch(test_pairs)
            
            self.assertIsInstance(sequence_types, dict)
            cache_key = f"{self.mandate.name}:{self.invoice.name}"
            self.assertIn(cache_key, sequence_types)
            
            # Should return FRST for first usage
            self.assertEqual(sequence_types[cache_key], "FRST")
            
        except ImportError:
            self.skipTest("Mandate service optimization not available")


if __name__ == "__main__":
    unittest.main()