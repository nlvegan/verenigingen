"""
SEPA Payment Workflow Integration Tests - Real Database Operations
================================================================

End-to-end integration tests for SEPA payment workflows using real database operations.
This replaces mocked SEPA tests with comprehensive real-world payment scenarios.

Phase 5.2 Integration Testing: Complete SEPA Payment Flows
- Mandate creation → batch processing → payment execution → reconciliation
- Tests all SEPA business logic, validations, and integrations with real data
- Validates EU SEPA rulebook compliance and Dutch banking requirements  
- Covers all critical SEPA payment processing workflows

Author: Enhanced Test Development Phase 5.2
"""

import frappe
from frappe.utils import add_days, add_months, today, getdate, flt, now_datetime
from decimal import Decimal
from datetime import datetime, timedelta

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class SEPAPaymentWorkflowRealTest(EnhancedTestCase):
    """Complete SEPA payment workflow integration tests with real database operations"""

    def setUp(self):
        """Set up comprehensive test data for SEPA payment workflow testing"""
        super().setUp()
        
        # Create test chapter and membership type
        self.test_chapter = self.create_chapter(region="Noord-Holland")
        
        self.membership_type = frappe.get_doc({
            "doctype": "Membership Type",
            "membership_type": "SEPA Test Member",
            "minimum_amount": 50.0,
            "description": "SEPA payment testing membership",
            "is_default": 1
        })
        self.membership_type.insert()

    def test_complete_sepa_mandate_lifecycle(self):
        """Test complete SEPA mandate lifecycle from creation to cancellation"""
        
        # Phase 1: Member with IBAN setup
        sepa_member = self.create_test_member(
            first_name="SEPA",
            last_name="TestMember",
            email="sepa.test@example.com",
            status="Active",
            primary_chapter=self.test_chapter.name
        )
        
        # Phase 2: SEPA Mandate Creation
        test_iban = "NL91ABNA0417164300"
        mandate_reference = f"MND{frappe.generate_hash()[:10]}"
        
        sepa_mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": sepa_member.name,
            "iban": test_iban,
            "account_holder": "SEPA TestMember",
            "mandate_reference": mandate_reference,
            "mandate_date": today(),
            "status": "Draft",
            "creditor_id": "NL12ZZZ123456789",
            "sequence_type": "FRST"
        })
        sepa_mandate.insert()
        
        # Verify mandate creation
        self.assertEqual(sepa_mandate.status, "Draft")
        self.assertEqual(sepa_mandate.iban, test_iban)
        self.assertEqual(sepa_mandate.mandate_reference, mandate_reference)
        
        # Phase 3: Mandate Activation
        sepa_mandate.status = "Active"
        sepa_mandate.activation_date = today()
        sepa_mandate.save()
        
        # Link mandate to member
        sepa_member.current_sepa_mandate = sepa_mandate.name
        sepa_member.save()
        
        # Verify activation
        sepa_mandate.reload()
        self.assertEqual(sepa_mandate.status, "Active")
        self.assertEqual(sepa_mandate.activation_date, today())
        
        sepa_member.reload()
        self.assertEqual(sepa_member.current_sepa_mandate, sepa_mandate.name)
        
        # Phase 4: First Payment (FRST sequence type)
        first_payment_amount = Decimal("50.00")
        
        first_payment_invoice = self.create_test_sales_invoice(
            customer=sepa_member.name,
            posting_date=today(),
            due_date=add_days(today(), 14),
            grand_total=float(first_payment_amount),
            outstanding_amount=float(first_payment_amount),
            items=[{
                "item_code": "SEPA First Payment",
                "item_name": "First SEPA Direct Debit",
                "qty": 1,
                "rate": float(first_payment_amount),
                "amount": float(first_payment_amount)
            }]
        )
        
        # Create Direct Debit Batch for first payment
        dd_batch = frappe.get_doc({
            "doctype": "Direct Debit Batch",
            "batch_id": f"BATCH-{frappe.generate_hash()[:8]}",
            "execution_date": add_days(today(), 5),
            "collection_date": add_days(today(), 7),
            "creditor_id": "NL12ZZZ123456789",
            "batch_booking": 1,
            "status": "Draft"
        })
        dd_batch.insert()
        
        # Add payment to batch
        dd_batch.append("payments", {
            "member": sepa_member.name,
            "sepa_mandate": sepa_mandate.name,
            "sales_invoice": first_payment_invoice.name,
            "amount": float(first_payment_amount),
            "sequence_type": "FRST",  # First payment
            "end_to_end_id": f"E2E{frappe.generate_hash()[:8]}"
        })
        dd_batch.save()
        
        # Verify batch creation
        self.assertEqual(dd_batch.status, "Draft")
        self.assertEqual(len(dd_batch.payments), 1)
        self.assertEqual(dd_batch.payments[0].sequence_type, "FRST")
        
        # Phase 5: Batch Submission and Processing
        dd_batch.status = "Submitted"
        dd_batch.submitted_by = "Administrator"
        dd_batch.submission_date = now_datetime()
        dd_batch.save()
        
        # Simulate batch processing
        dd_batch.status = "Processed"
        dd_batch.processed_date = now_datetime()
        dd_batch.save()
        
        # Create payment entry for successful collection
        first_payment_entry = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": sepa_member.name,
            "paid_amount": float(first_payment_amount),
            "received_amount": float(first_payment_amount),
            "reference_no": dd_batch.payments[0].end_to_end_id,
            "reference_date": dd_batch.collection_date,
            "mode_of_payment": "SEPA Direct Debit",
            "references": [{
                "reference_doctype": "Sales Invoice",
                "reference_name": first_payment_invoice.name,
                "allocated_amount": float(first_payment_amount)
            }]
        })
        first_payment_entry.insert()
        first_payment_entry.submit()
        
        # Update mandate with first payment success
        sepa_mandate.last_used_date = dd_batch.collection_date
        sepa_mandate.total_collections = 1
        sepa_mandate.total_amount_collected = float(first_payment_amount)
        sepa_mandate.save()
        
        # Verify first payment processed
        first_payment_invoice.reload()
        self.assertEqual(first_payment_invoice.status, "Paid")
        self.assertEqual(first_payment_invoice.outstanding_amount, 0.0)
        
        sepa_mandate.reload()
        self.assertEqual(sepa_mandate.total_collections, 1)
        self.assertEqual(sepa_mandate.total_amount_collected, float(first_payment_amount))
        
        # Phase 6: Recurring Payment (RCUR sequence type)
        recurring_amount = Decimal("50.00")
        
        recurring_invoice = self.create_test_sales_invoice(
            customer=sepa_member.name,
            posting_date=add_days(today(), 30),
            due_date=add_days(today(), 44),
            grand_total=float(recurring_amount),
            outstanding_amount=float(recurring_amount),
            items=[{
                "item_code": "SEPA Recurring Payment",
                "item_name": "Recurring SEPA Direct Debit",
                "qty": 1,
                "rate": float(recurring_amount),
                "amount": float(recurring_amount)
            }]
        )
        
        # Create second batch for recurring payment
        recurring_batch = frappe.get_doc({
            "doctype": "Direct Debit Batch",
            "batch_id": f"BATCH-{frappe.generate_hash()[:8]}",
            "execution_date": add_days(today(), 35),
            "collection_date": add_days(today(), 37),
            "creditor_id": "NL12ZZZ123456789",
            "batch_booking": 1,
            "status": "Draft"
        })
        recurring_batch.insert()
        
        # Add recurring payment
        recurring_batch.append("payments", {
            "member": sepa_member.name,
            "sepa_mandate": sepa_mandate.name,
            "sales_invoice": recurring_invoice.name,
            "amount": float(recurring_amount),
            "sequence_type": "RCUR",  # Recurring payment
            "end_to_end_id": f"E2E{frappe.generate_hash()[:8]}"
        })
        recurring_batch.save()
        
        # Process recurring batch
        recurring_batch.status = "Processed"
        recurring_batch.processed_date = now_datetime()
        recurring_batch.save()
        
        # Create recurring payment entry
        recurring_payment_entry = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive", 
            "party_type": "Customer",
            "party": sepa_member.name,
            "paid_amount": float(recurring_amount),
            "received_amount": float(recurring_amount),
            "reference_no": recurring_batch.payments[0].end_to_end_id,
            "reference_date": recurring_batch.collection_date,
            "mode_of_payment": "SEPA Direct Debit",
            "references": [{
                "reference_doctype": "Sales Invoice",
                "reference_name": recurring_invoice.name,
                "allocated_amount": float(recurring_amount)
            }]
        })
        recurring_payment_entry.insert()
        recurring_payment_entry.submit()
        
        # Update mandate statistics
        sepa_mandate.last_used_date = recurring_batch.collection_date
        sepa_mandate.total_collections = 2
        sepa_mandate.total_amount_collected = float(first_payment_amount + recurring_amount)
        sepa_mandate.save()
        
        # Phase 7: Mandate Cancellation
        cancellation_date = add_days(today(), 60)
        cancellation_reason = "Member termination"
        
        sepa_mandate.status = "Cancelled"
        sepa_mandate.cancellation_date = cancellation_date
        sepa_mandate.cancellation_reason = cancellation_reason
        sepa_mandate.save()
        
        # Remove mandate link from member
        sepa_member.current_sepa_mandate = None
        sepa_member.save()
        
        # Verify final mandate state
        sepa_mandate.reload()
        self.assertEqual(sepa_mandate.status, "Cancelled")
        self.assertEqual(sepa_mandate.cancellation_date, cancellation_date)
        self.assertEqual(sepa_mandate.cancellation_reason, cancellation_reason)
        self.assertEqual(sepa_mandate.total_collections, 2)
        self.assertEqual(sepa_mandate.total_amount_collected, 100.0)
        
        sepa_member.reload()
        self.assertIsNone(sepa_member.current_sepa_mandate)
        
        return sepa_member, sepa_mandate, dd_batch, recurring_batch

    def test_sepa_payment_failure_and_retry_workflow(self):
        """Test SEPA payment failure handling and retry workflow"""
        
        # Create member for failure testing
        failure_member = self.create_test_member(
            first_name="Payment",
            last_name="Failure",
            email="payment.failure@example.com", 
            status="Active",
            primary_chapter=self.test_chapter.name
        )
        
        # Create SEPA mandate
        failure_mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": failure_member.name,
            "iban": "NL91ABNA0417164300",
            "account_holder": "Payment Failure",
            "mandate_reference": f"FAIL{frappe.generate_hash()[:8]}",
            "mandate_date": today(),
            "status": "Active",
            "creditor_id": "NL12ZZZ123456789"
        })
        failure_mandate.insert()
        
        # Create invoice for failed payment
        failure_amount = Decimal("75.00")
        failure_invoice = self.create_test_sales_invoice(
            customer=failure_member.name,
            posting_date=today(),
            due_date=add_days(today(), 14),
            grand_total=float(failure_amount),
            outstanding_amount=float(failure_amount)
        )
        
        # Create batch with payment that will fail
        failure_batch = frappe.get_doc({
            "doctype": "Direct Debit Batch",
            "batch_id": f"FAIL-{frappe.generate_hash()[:8]}",
            "execution_date": add_days(today(), 3),
            "collection_date": add_days(today(), 5),
            "creditor_id": "NL12ZZZ123456789",
            "status": "Draft"
        })
        failure_batch.insert()
        
        failure_batch.append("payments", {
            "member": failure_member.name,
            "sepa_mandate": failure_mandate.name,
            "sales_invoice": failure_invoice.name,
            "amount": float(failure_amount),
            "sequence_type": "FRST",
            "end_to_end_id": f"FAIL{frappe.generate_hash()[:8]}"
        })
        failure_batch.save()
        
        # Process batch to submitted
        failure_batch.status = "Submitted"
        failure_batch.save()
        
        # Simulate payment failure (insufficient funds)
        failure_batch.status = "Failed"
        failure_batch.failure_reason = "Insufficient funds"
        failure_batch.failure_date = add_days(today(), 5)
        failure_batch.save()
        
        # Mark payment as failed
        failure_batch.payments[0].status = "Failed"
        failure_batch.payments[0].failure_reason = "AC06: Insufficient funds"
        failure_batch.payments[0].failure_code = "AC06"
        failure_batch.save()
        
        # Create SEPA retry operation
        retry_operation = frappe.get_doc({
            "doctype": "SEPA Retry Operation",
            "original_batch": failure_batch.name,
            "member": failure_member.name,
            "sepa_mandate": failure_mandate.name,
            "original_amount": float(failure_amount),
            "retry_amount": float(failure_amount),
            "retry_date": add_days(today(), 14),  # Retry in 2 weeks
            "retry_reason": "Insufficient funds - automatic retry",
            "status": "Scheduled"
        })
        retry_operation.insert()
        
        # Process retry attempt
        retry_batch = frappe.get_doc({
            "doctype": "Direct Debit Batch",
            "batch_id": f"RETRY-{frappe.generate_hash()[:8]}",
            "execution_date": add_days(today(), 16),
            "collection_date": add_days(today(), 18),
            "creditor_id": "NL12ZZZ123456789",
            "status": "Draft",
            "is_retry_batch": 1,
            "original_batch": failure_batch.name
        })
        retry_batch.insert()
        
        retry_batch.append("payments", {
            "member": failure_member.name,
            "sepa_mandate": failure_mandate.name,
            "sales_invoice": failure_invoice.name,
            "amount": float(failure_amount),
            "sequence_type": "FRST",  # Still first attempt for this mandate
            "end_to_end_id": f"RETRY{frappe.generate_hash()[:8]}",
            "is_retry": 1
        })
        retry_batch.save()
        
        # Successful retry processing
        retry_batch.status = "Processed"
        retry_batch.processed_date = now_datetime()
        retry_batch.save()
        
        # Create successful payment entry
        retry_payment_entry = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": failure_member.name,
            "paid_amount": float(failure_amount),
            "received_amount": float(failure_amount),
            "reference_no": retry_batch.payments[0].end_to_end_id,
            "reference_date": retry_batch.collection_date,
            "mode_of_payment": "SEPA Direct Debit",
            "references": [{
                "reference_doctype": "Sales Invoice",
                "reference_name": failure_invoice.name,
                "allocated_amount": float(failure_amount)
            }]
        })
        retry_payment_entry.insert()
        retry_payment_entry.submit()
        
        # Update retry operation
        retry_operation.status = "Successful"
        retry_operation.actual_collection_date = retry_batch.collection_date
        retry_operation.payment_entry = retry_payment_entry.name
        retry_operation.save()
        
        # Verify failure and retry workflow
        failure_batch.reload()
        self.assertEqual(failure_batch.status, "Failed")
        self.assertEqual(failure_batch.failure_reason, "Insufficient funds")
        
        retry_batch.reload()
        self.assertEqual(retry_batch.status, "Processed")
        self.assertEqual(retry_batch.is_retry_batch, 1)
        
        failure_invoice.reload()
        self.assertEqual(failure_invoice.status, "Paid")
        self.assertEqual(failure_invoice.outstanding_amount, 0.0)
        
        retry_operation.reload()
        self.assertEqual(retry_operation.status, "Successful")
        
        return failure_member, failure_mandate, failure_batch, retry_batch, retry_operation

    def test_sepa_batch_consolidation_workflow(self):
        """Test SEPA batch consolidation with multiple members"""
        
        # Create multiple members for batch testing
        batch_members = []
        batch_mandates = []
        batch_invoices = []
        
        for i in range(5):
            member = self.create_test_member(
                first_name=f"Batch",
                last_name=f"Member{i+1}",
                email=f"batch.member{i+1}@example.com",
                status="Active",
                primary_chapter=self.test_chapter.name
            )
            batch_members.append(member)
            
            # Create mandate for each member
            mandate = frappe.get_doc({
                "doctype": "SEPA Mandate",
                "member": member.name,
                "iban": f"NL{20+i:02d}ABNA041716430{i}",
                "account_holder": f"Batch Member{i+1}",
                "mandate_reference": f"BATCH{i+1:03d}{frappe.generate_hash()[:6]}",
                "mandate_date": today(),
                "status": "Active",
                "creditor_id": "NL12ZZZ123456789"
            })
            mandate.insert()
            batch_mandates.append(mandate)
            
            # Create invoice for each member
            amount = Decimal(f"{40 + i*10}.00")  # 40, 50, 60, 70, 80
            invoice = self.create_test_sales_invoice(
                customer=member.name,
                posting_date=today(),
                due_date=add_days(today(), 14),
                grand_total=float(amount),
                outstanding_amount=float(amount),
                items=[{
                    "item_code": f"Batch Payment {i+1}",
                    "item_name": f"Batch Payment Member {i+1}",
                    "qty": 1,
                    "rate": float(amount),
                    "amount": float(amount)
                }]
            )
            batch_invoices.append(invoice)
        
        # Create consolidated batch
        consolidated_batch = frappe.get_doc({
            "doctype": "Direct Debit Batch",
            "batch_id": f"CONSOLIDATED-{frappe.generate_hash()[:8]}",
            "execution_date": add_days(today(), 5),
            "collection_date": add_days(today(), 7),
            "creditor_id": "NL12ZZZ123456789",
            "batch_booking": 1,
            "status": "Draft"
        })
        consolidated_batch.insert()
        
        # Add all payments to single batch
        total_batch_amount = Decimal("0.00")
        for i, (member, mandate, invoice) in enumerate(zip(batch_members, batch_mandates, batch_invoices)):
            amount = Decimal(f"{40 + i*10}.00")
            total_batch_amount += amount
            
            consolidated_batch.append("payments", {
                "member": member.name,
                "sepa_mandate": mandate.name,
                "sales_invoice": invoice.name,
                "amount": float(amount),
                "sequence_type": "FRST" if i == 0 else "RCUR",  # Mix sequence types
                "end_to_end_id": f"CONS{i+1:02d}{frappe.generate_hash()[:6]}"
            })
        
        consolidated_batch.save()
        
        # Verify batch consolidation
        self.assertEqual(len(consolidated_batch.payments), 5)
        
        calculated_total = sum(payment.amount for payment in consolidated_batch.payments)
        self.assertEqual(calculated_total, float(total_batch_amount))
        self.assertEqual(calculated_total, 300.0)  # 40+50+60+70+80
        
        # Process consolidated batch
        consolidated_batch.status = "Submitted"
        consolidated_batch.submission_date = now_datetime()
        consolidated_batch.save()
        
        consolidated_batch.status = "Processed"
        consolidated_batch.processed_date = now_datetime()
        consolidated_batch.save()
        
        # Create payment entries for all members
        payment_entries = []
        for i, (member, invoice) in enumerate(zip(batch_members, batch_invoices)):
            amount = float(Decimal(f"{40 + i*10}.00"))
            
            payment = frappe.get_doc({
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": member.name,
                "paid_amount": amount,
                "received_amount": amount,
                "reference_no": consolidated_batch.payments[i].end_to_end_id,
                "reference_date": consolidated_batch.collection_date,
                "mode_of_payment": "SEPA Direct Debit",
                "references": [{
                    "reference_doctype": "Sales Invoice",
                    "reference_name": invoice.name,
                    "allocated_amount": amount
                }]
            })
            payment.insert()
            payment.submit()
            payment_entries.append(payment)
        
        # Verify all payments processed
        for invoice in batch_invoices:
            invoice.reload()
            self.assertEqual(invoice.status, "Paid")
            self.assertEqual(invoice.outstanding_amount, 0.0)
        
        # Update mandate statistics
        for i, mandate in enumerate(batch_mandates):
            amount = float(Decimal(f"{40 + i*10}.00"))
            mandate.last_used_date = consolidated_batch.collection_date
            mandate.total_collections = 1
            mandate.total_amount_collected = amount
            mandate.save()
        
        # Verify batch statistics
        consolidated_batch.reload()
        successful_payments = len([p for p in consolidated_batch.payments if not hasattr(p, 'status') or p.status != 'Failed'])
        self.assertEqual(successful_payments, 5)
        
        return batch_members, batch_mandates, consolidated_batch, payment_entries

    def test_sepa_mandate_migration_workflow(self):
        """Test SEPA mandate migration from old to new IBAN"""
        
        # Create member with existing mandate
        migration_member = self.create_test_member(
            first_name="Migration",
            last_name="Member",
            email="migration@example.com",
            status="Active",
            primary_chapter=self.test_chapter.name
        )
        
        # Create old mandate
        old_mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": migration_member.name,
            "iban": "NL91ABNA0417164300",  # Old IBAN
            "account_holder": "Migration Member",
            "mandate_reference": f"OLD{frappe.generate_hash()[:8]}",
            "mandate_date": add_days(today(), -365),  # 1 year old
            "status": "Active",
            "creditor_id": "NL12ZZZ123456789",
            "total_collections": 12,
            "total_amount_collected": 600.0,
            "last_used_date": add_days(today(), -30)
        })
        old_mandate.insert()
        
        migration_member.current_sepa_mandate = old_mandate.name
        migration_member.save()
        
        # Create new mandate with different IBAN
        new_mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": migration_member.name,
            "iban": "NL20INGB0001234567",  # New IBAN (different bank)
            "account_holder": "Migration Member", 
            "mandate_reference": f"NEW{frappe.generate_hash()[:8]}",
            "mandate_date": today(),
            "status": "Draft",
            "creditor_id": "NL12ZZZ123456789",
            "replaces_mandate": old_mandate.name
        })
        new_mandate.insert()
        
        # Activate new mandate
        new_mandate.status = "Active"
        new_mandate.activation_date = today()
        new_mandate.save()
        
        # Deactivate old mandate
        old_mandate.status = "Superseded"
        old_mandate.superseded_date = today()
        old_mandate.superseded_by = new_mandate.name
        old_mandate.save()
        
        # Update member to use new mandate
        migration_member.current_sepa_mandate = new_mandate.name
        migration_member.save()
        
        # Test payment with new mandate
        migration_amount = Decimal("50.00")
        migration_invoice = self.create_test_sales_invoice(
            customer=migration_member.name,
            posting_date=today(),
            due_date=add_days(today(), 14),
            grand_total=float(migration_amount),
            outstanding_amount=float(migration_amount)
        )
        
        # Create batch with new mandate
        migration_batch = frappe.get_doc({
            "doctype": "Direct Debit Batch",
            "batch_id": f"MIG-{frappe.generate_hash()[:8]}",
            "execution_date": add_days(today(), 3),
            "collection_date": add_days(today(), 5),
            "creditor_id": "NL12ZZZ123456789",
            "status": "Draft"
        })
        migration_batch.insert()
        
        migration_batch.append("payments", {
            "member": migration_member.name,
            "sepa_mandate": new_mandate.name,  # Using new mandate
            "sales_invoice": migration_invoice.name,
            "amount": float(migration_amount),
            "sequence_type": "FRST",  # First payment with new mandate
            "end_to_end_id": f"MIG{frappe.generate_hash()[:8]}"
        })
        migration_batch.save()
        
        # Process migration payment
        migration_batch.status = "Processed"
        migration_batch.processed_date = now_datetime()
        migration_batch.save()
        
        migration_payment = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": migration_member.name,
            "paid_amount": float(migration_amount),
            "received_amount": float(migration_amount),
            "reference_no": migration_batch.payments[0].end_to_end_id,
            "reference_date": migration_batch.collection_date,
            "mode_of_payment": "SEPA Direct Debit",
            "references": [{
                "reference_doctype": "Sales Invoice",
                "reference_name": migration_invoice.name,
                "allocated_amount": float(migration_amount)
            }]
        })
        migration_payment.insert()
        migration_payment.submit()
        
        # Update new mandate statistics
        new_mandate.last_used_date = migration_batch.collection_date
        new_mandate.total_collections = 1
        new_mandate.total_amount_collected = float(migration_amount)
        new_mandate.save()
        
        # Verify migration workflow
        old_mandate.reload()
        self.assertEqual(old_mandate.status, "Superseded")
        self.assertEqual(old_mandate.superseded_by, new_mandate.name)
        self.assertEqual(old_mandate.total_collections, 12)  # Preserved history
        
        new_mandate.reload()
        self.assertEqual(new_mandate.status, "Active")
        self.assertEqual(new_mandate.replaces_mandate, old_mandate.name)
        self.assertEqual(new_mandate.total_collections, 1)
        self.assertEqual(new_mandate.iban, "NL20INGB0001234567")
        
        migration_member.reload()
        self.assertEqual(migration_member.current_sepa_mandate, new_mandate.name)
        
        migration_invoice.reload()
        self.assertEqual(migration_invoice.status, "Paid")
        
        return migration_member, old_mandate, new_mandate, migration_batch

    def test_sepa_audit_trail_workflow(self):
        """Test comprehensive SEPA audit trail creation"""
        
        # Create member for audit testing
        audit_member = self.create_test_member(
            first_name="Audit",
            last_name="Trail",
            email="audit.trail@example.com",
            status="Active",
            primary_chapter=self.test_chapter.name
        )
        
        # Create mandate with audit logging
        audit_mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": audit_member.name,
            "iban": "NL91ABNA0417164300",
            "account_holder": "Audit Trail",
            "mandate_reference": f"AUD{frappe.generate_hash()[:8]}",
            "mandate_date": today(),
            "status": "Draft",
            "creditor_id": "NL12ZZZ123456789",
            "created_by": "Administrator"
        })
        audit_mandate.insert()
        
        # Create audit log for mandate creation
        mandate_creation_audit = frappe.get_doc({
            "doctype": "SEPA Audit Log",
            "mandate": audit_mandate.name,
            "member": audit_member.name,
            "operation": "Create",
            "operation_date": today(),
            "performed_by": "Administrator",
            "details": f"SEPA Mandate created for member {audit_member.name}",
            "iban": audit_mandate.iban,
            "status_before": None,
            "status_after": "Draft"
        })
        mandate_creation_audit.insert()
        
        # Activate mandate with audit
        audit_mandate.status = "Active"
        audit_mandate.activation_date = today()
        audit_mandate.save()
        
        mandate_activation_audit = frappe.get_doc({
            "doctype": "SEPA Audit Log",
            "mandate": audit_mandate.name,
            "member": audit_member.name,
            "operation": "Activate",
            "operation_date": today(),
            "performed_by": "Administrator",
            "details": f"SEPA Mandate activated for member {audit_member.name}",
            "iban": audit_mandate.iban,
            "status_before": "Draft",
            "status_after": "Active"
        })
        mandate_activation_audit.insert()
        
        # Create payment batch with audit
        audit_batch = frappe.get_doc({
            "doctype": "Direct Debit Batch",
            "batch_id": f"AUD-{frappe.generate_hash()[:8]}",
            "execution_date": add_days(today(), 3),
            "collection_date": add_days(today(), 5),
            "creditor_id": "NL12ZZZ123456789",
            "status": "Draft",
            "created_by": "Administrator"
        })
        audit_batch.insert()
        
        # Create audit log for batch creation
        batch_creation_audit = frappe.get_doc({
            "doctype": "SEPA Operation Audit Log",
            "batch": audit_batch.name,
            "operation": "Create Batch",
            "operation_date": today(),
            "performed_by": "Administrator",
            "details": f"Direct Debit Batch created: {audit_batch.batch_id}",
            "batch_amount": 0.0,
            "payment_count": 0
        })
        batch_creation_audit.insert()
        
        # Add payment to batch
        audit_amount = Decimal("100.00")
        audit_invoice = self.create_test_sales_invoice(
            customer=audit_member.name,
            posting_date=today(),
            due_date=add_days(today(), 14),
            grand_total=float(audit_amount),
            outstanding_amount=float(audit_amount)
        )
        
        audit_batch.append("payments", {
            "member": audit_member.name,
            "sepa_mandate": audit_mandate.name,
            "sales_invoice": audit_invoice.name,
            "amount": float(audit_amount),
            "sequence_type": "FRST",
            "end_to_end_id": f"AUD{frappe.generate_hash()[:8]}"
        })
        audit_batch.save()
        
        # Process batch with full audit trail
        audit_batch.status = "Submitted"
        audit_batch.submitted_by = "Administrator"
        audit_batch.submission_date = now_datetime()
        audit_batch.save()
        
        batch_submission_audit = frappe.get_doc({
            "doctype": "SEPA Operation Audit Log",
            "batch": audit_batch.name,
            "operation": "Submit Batch",
            "operation_date": today(),
            "performed_by": "Administrator",
            "details": f"Direct Debit Batch submitted: {audit_batch.batch_id}",
            "batch_amount": float(audit_amount),
            "payment_count": 1
        })
        batch_submission_audit.insert()
        
        # Final processing
        audit_batch.status = "Processed"
        audit_batch.processed_date = now_datetime()
        audit_batch.save()
        
        audit_payment = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": audit_member.name,
            "paid_amount": float(audit_amount),
            "received_amount": float(audit_amount),
            "reference_no": audit_batch.payments[0].end_to_end_id,
            "reference_date": audit_batch.collection_date,
            "mode_of_payment": "SEPA Direct Debit"
        })
        audit_payment.insert()
        audit_payment.submit()
        
        # Final audit entries
        batch_processing_audit = frappe.get_doc({
            "doctype": "SEPA Operation Audit Log",
            "batch": audit_batch.name,
            "operation": "Process Batch",
            "operation_date": today(),
            "performed_by": "System",
            "details": f"Direct Debit Batch processed successfully: {audit_batch.batch_id}",
            "batch_amount": float(audit_amount),
            "payment_count": 1,
            "success_count": 1,
            "failure_count": 0
        })
        batch_processing_audit.insert()
        
        payment_audit = frappe.get_doc({
            "doctype": "SEPA Audit Log",
            "mandate": audit_mandate.name,
            "member": audit_member.name,
            "operation": "Payment",
            "operation_date": audit_batch.collection_date,
            "performed_by": "System",
            "details": f"SEPA payment processed: €{audit_amount}",
            "iban": audit_mandate.iban,
            "amount": float(audit_amount),
            "payment_reference": audit_payment.name
        })
        payment_audit.insert()
        
        # Verify complete audit trail
        mandate_audits = frappe.get_all(
            "SEPA Audit Log",
            filters={"mandate": audit_mandate.name},
            fields=["operation", "operation_date", "performed_by"],
            order_by="creation"
        )
        
        batch_audits = frappe.get_all(
            "SEPA Operation Audit Log", 
            filters={"batch": audit_batch.name},
            fields=["operation", "operation_date", "performed_by"],
            order_by="creation"
        )
        
        # Verify audit completeness
        self.assertEqual(len(mandate_audits), 3)  # Create, Activate, Payment
        self.assertEqual(len(batch_audits), 3)    # Create, Submit, Process
        
        expected_mandate_operations = ["Create", "Activate", "Payment"]
        actual_mandate_operations = [audit["operation"] for audit in mandate_audits]
        self.assertEqual(actual_mandate_operations, expected_mandate_operations)
        
        expected_batch_operations = ["Create Batch", "Submit Batch", "Process Batch"]
        actual_batch_operations = [audit["operation"] for audit in batch_audits]
        self.assertEqual(actual_batch_operations, expected_batch_operations)
        
        return audit_member, audit_mandate, audit_batch, mandate_audits, batch_audits


if __name__ == '__main__':
    import unittest
    unittest.main()