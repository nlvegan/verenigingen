"""
Regression test for the specific issue found with Assoc-Member-2025-07-0025
Tests the exact scenario that caused payment history sync to fail.
"""

import frappe
from frappe.utils import today, add_days, getdate
from verenigingen.tests.utils.base import VereningingenTestCase


class TestRegressionPaymentHistoryDraftStatus(VereningingenTestCase):
    """
    Regression test specifically for the payment history sync failure
    that occurred with member Assoc-Member-2025-07-0025 on 2025-07-22.
    
    This test recreates the exact conditions that caused the issue:
    1. Auto-generated invoice from dues schedule
    2. Invoice submission triggers payment history sync  
    3. Payment history sync fails due to "Draft" status validation
    4. Member can't see their invoice in payment history
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # "Daglid" is a production membership type absent on fresh test sites.
        from verenigingen.tests.fixtures.test_data_factory import ensure_membership_type_exists

        ensure_membership_type_exists("Daglid", amount=2.0)

    def test_payment_history_sync_with_auto_generated_invoice(self):
        """
        Test that reproduces the exact failure scenario from 2025-07-22.
        
        This test ensures that:
        1. Dues schedule can generate invoices
        2. Invoice submission doesn't fail on payment history sync
        3. Member can see their invoice in payment history after submission
        4. Payment status validation accepts "Draft" status
        """
        # Create member with customer (like Parko Janssen)
        member = self.create_test_member(
            first_name="Regression",
            last_name="TestUser", 
            email="regression.test@example.com"
        )
        
        # Ensure customer exists (required for invoices)
        if not member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{member.first_name} {member.last_name}"
            customer.customer_type = "Individual"
            customer.save()
            member.customer = customer.name
            member.save()
            self.track_doc("Customer", customer.name)
        
        # Create membership. This auto-creates an active dues schedule (and
        # production allows only one active schedule per member), so reuse it
        # instead of inserting a second one. generate_invoice() also requires the
        # member to have an active membership, which the membership provides.
        membership = self.create_test_membership(
            member=member.name,
            membership_type="Daglid"
        )
        if membership.docstatus == 0:
            membership.submit()  # submit -> member has active membership + auto schedule

        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        dues_schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        dues_schedule.billing_frequency = "Daily"
        dues_schedule.dues_rate = 2.0
        dues_schedule.next_invoice_date = today()
        dues_schedule.save()
        
        # Get initial payment history count
        initial_count = len(member.payment_history) if hasattr(member, 'payment_history') else 0
        
        # Generate and submit invoice (this is what failed originally).
        # generate_invoice() returns the Sales Invoice *document*, not its name.
        try:
            invoice_doc = dues_schedule.generate_invoice()
            self.assertIsNotNone(invoice_doc, "Invoice generation should succeed")
            invoice_name = invoice_doc.name if hasattr(invoice_doc, "name") else invoice_doc
            self.track_doc("Sales Invoice", invoice_name)

            invoice = frappe.get_doc("Sales Invoice", invoice_name)
            
            # Verify invoice was created with proper due date (not in past)
            self.assertGreaterEqual(getdate(invoice.due_date), getdate(today()),
                                   "Invoice due date should not be in the past")
            
            # If invoice is submitted, payment history should sync without error
            if invoice.docstatus == 1:
                # Refresh member to get updated payment history
                member.reload()
                
                # Check payment history was updated
                final_count = len(member.payment_history) if hasattr(member, 'payment_history') else 0
                self.assertGreaterEqual(final_count, initial_count,
                                      "Payment history should be updated after invoice submission")
                
                # Verify the specific invoice appears in history
                invoice_found = False
                for payment in member.payment_history:
                    if hasattr(payment, 'invoice') and payment.invoice == invoice_name:
                        invoice_found = True
                        # Verify payment status is valid (should not cause validation error)
                        self.assertIn(payment.payment_status, 
                                    ['Draft', 'Unpaid', 'Partially Paid', 'Paid', 'Overdue', 'Cancelled'],
                                    f"Payment status '{payment.payment_status}' should be valid")
                        break
                
                self.assertTrue(invoice_found, 
                               "Invoice should appear in member payment history (the original bug)")
                
        except Exception as e:
            self.fail(f"Invoice generation and payment history sync should not fail: {str(e)}")
    
    def test_manual_payment_history_refresh_after_invoice_submission(self):
        """
        Test manual payment history refresh - the specific action that failed for the user.
        
        This test simulates the user clicking "Refresh Financial History" button
        after an invoice was submitted but not appearing in their payment history.
        """
        # Create test setup
        member = self.create_test_member(
            first_name="Manual",
            last_name="Refresh",
            email="manual.refresh@example.com"
        )
        
        # Create the member's Customer with a unique name. create_test_member here
        # (VereningingenTestCase) does not auto-create a Customer nor uniquify the
        # passed names, so a plain '<first> <last>' Customer name collides with data
        # from an earlier run (DuplicateEntryError). Append a hash.
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"{member.first_name} {member.last_name} {frappe.generate_hash(length=6)}"
        customer.customer_type = "Individual"
        customer.save()
        member.customer = customer.name
        member.save()
        self.track_doc("Customer", customer.name)
        
        # Create a submitted invoice (simulating one that was auto-generated).
        # Use the SEPA test factory so the invoice has a company, debit_to, income
        # account, cost center and v16-mandatory price-list fields set correctly --
        # a bare frappe.new_doc("Sales Invoice") fails on "Please select a Company".
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

        sepa_factory = SEPATestDataFactory()
        invoice = sepa_factory.create_test_sales_invoice(
            customer=member.customer,
            member=member.name,
            grand_total=2.0,
            status="Unpaid",
            submit=True,  # triggers payment history sync
        )
        self.track_doc("Sales Invoice", invoice.name)
        
        # Now test manual refresh (the action that failed for the user)
        try:
            # This is what happens when user clicks "Refresh Financial History"
            member.load_payment_history()
            refresh_success = True
            error_message = None
        except Exception as e:
            refresh_success = False
            error_message = str(e)
        
        self.assertTrue(refresh_success, 
                       f"Manual payment history refresh should succeed. Error: {error_message}")
        
        # Verify invoice now appears in payment history
        invoice_in_history = any(
            hasattr(p, 'invoice') and p.invoice == invoice.name 
            for p in member.payment_history
        )
        self.assertTrue(invoice_in_history,
                       "Invoice should appear in payment history after manual refresh")

    def test_draft_status_validation_in_payment_history_doctype(self):
        """
        Test that the Member Payment History doctype properly validates Draft status.
        
        This is the core validation that was failing.
        """
        # Get the doctype meta
        meta = frappe.get_meta("Member Payment History")
        payment_status_field = None
        
        for field in meta.fields:
            if field.fieldname == "payment_status":
                payment_status_field = field
                break
        
        self.assertIsNotNone(payment_status_field, 
                           "Payment Status field should exist in Member Payment History")
        
        # Check that Draft is in the allowed options
        options = payment_status_field.options.split('\n')
        self.assertIn('Draft', options,
                     "Draft should be allowed as a payment status (this was the original bug)")
        
        # Test creating a payment history record with Draft status
        member = self.create_test_member(
            first_name="Draft", 
            last_name="Status",
            email="draft.status@example.com"
        )
        
        member.append("payment_history", {
            "invoice": None,
            "posting_date": today(),
            "amount": 2.0,
            "payment_status": "Draft",  # This should be allowed now
            "status": "Draft",
            "transaction_type": "Regular Invoice"
        })
        
        # This save should succeed without validation error
        try:
            member.save()
            save_success = True
            error_message = None
        except Exception as e:
            save_success = False  
            error_message = str(e)
        
        self.assertTrue(save_success,
                       f"Saving member with Draft payment status should succeed. Error: {error_message}")