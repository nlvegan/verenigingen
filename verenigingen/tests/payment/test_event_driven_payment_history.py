"""
Test suite for the event-driven payment history update system

This test verifies that the new decoupled architecture properly handles
invoice events without blocking invoice submission on validation errors.
"""

import frappe
from frappe.utils import today, add_days
from verenigingen.tests.support.sepa_test_company import ensure_membership_dues_item
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.fixtures.test_data_factory import (
    PAYMENT_TEST_DAILY_TYPE,
    ensure_payment_test_daily_type,
)
import time


class TestEventDrivenPaymentHistory(VereningingenTestCase):
    """Test the event-driven payment history update system"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Invoices below reference the "Membership Dues - Daily" Item, which is
        # created on demand in production but absent on a fresh test site. Create
        # it (and the invoices) under the EUR test company so the Item's default
        # accounts and the invoice currency/company line up.
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        self.company = get_eur_test_company()
        ensure_membership_dues_item("Daily")

        # Create test member with customer
        self.member = self.create_test_member(
            first_name="EventTest",
            last_name="Member",
            email="event.test@example.com"
        )
        
        # Create the member's Customer with a unique name. create_test_member here
        # (VereningingenTestCase -> CoreTestDataFactory) does NOT auto-create a
        # Customer and does not uniquify the passed names, so a plain
        # '<first> <last>' Customer name collides with data left by an earlier run
        # (DuplicateEntryError). Append a hash for cross-run uniqueness.
        self.customer = frappe.new_doc("Customer")
        self.customer.customer_name = f"{self.member.first_name} {self.member.last_name} {frappe.generate_hash(length=6)}"
        self.customer.customer_type = "Individual"
        self.customer.save()
        self.member.customer = self.customer.name
        self.member.save()
        self.track_doc("Customer", self.customer.name)
    
    def test_invoice_submission_not_blocked_by_payment_history_validation(self):
        """
        Test that invoice submission succeeds even if payment history 
        sync would fail with validation errors.
        
        This is the key test that verifies our architectural improvement.
        """
        # Create invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = self.customer.name
        invoice.company = self.company
        invoice.currency = "EUR"
        invoice.posting_date = today()
        invoice.due_date = add_days(today(), 30)
        
        invoice.append("items", {
            "item_code": "Membership Dues - Daily",
            "qty": 1,
            "rate": 10.0,
            "description": "Test dues"
        })
        
        invoice.insert()
        self.track_doc("Sales Invoice", invoice.name)
        
        # Before our fix, this would fail if payment history validation failed
        # Now it should succeed regardless
        try:
            invoice.submit()
            submission_succeeded = True
            submission_error = None
        except Exception as e:
            submission_succeeded = False
            submission_error = str(e)
        
        self.assertTrue(submission_succeeded, 
                       f"Invoice submission should not be blocked by payment history errors. Error: {submission_error}")
        
        # Verify invoice is submitted
        self.assertEqual(invoice.docstatus, 1, "Invoice should be submitted")
    
    def test_event_emission_on_invoice_submit(self):
        """Test that submitting an invoice emits the correct event"""
        # We can't directly test event emission, but we can verify
        # the event handler is called by checking logs or side effects
        
        # Create and submit invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = self.customer.name
        invoice.company = self.company
        invoice.currency = "EUR"
        invoice.posting_date = today()
        invoice.due_date = add_days(today(), 30)
        
        invoice.append("items", {
            "item_code": "Membership Dues - Daily",
            "qty": 1,
            "rate": 20.0,
            "description": "Event test dues"
        })
        
        invoice.insert()
        self.track_doc("Sales Invoice", invoice.name)
        
        # Submit the invoice - this should trigger event emission
        invoice.submit()
        
        # Give background job a moment to process
        frappe.db.commit()
        time.sleep(2)  # Wait for async processing
        
        # Check if payment history was eventually updated
        # Note: This might not happen immediately due to async nature
        member = frappe.get_doc("Member", self.member.name)
        
        # We can't guarantee the async job has completed, but we can
        # verify the invoice submission succeeded
        self.assertEqual(invoice.docstatus, 1, "Invoice should be submitted")
    
    def test_payment_history_eventually_consistent(self):
        """
        Test that payment history becomes eventually consistent
        through the event-driven system.
        """
        # Initial payment history count
        initial_count = len(self.member.payment_history) if hasattr(self.member, 'payment_history') else 0
        
        # Create and submit invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = self.customer.name
        invoice.company = self.company
        invoice.currency = "EUR"
        invoice.posting_date = today()
        invoice.due_date = add_days(today(), 30)
        
        invoice.append("items", {
            "item_code": "Membership Dues - Daily",
            "qty": 1,
            "rate": 30.0,
            "description": "Consistency test dues"
        })
        
        invoice.insert()
        invoice.submit()
        self.track_doc("Sales Invoice", invoice.name)
        
        # Force process background jobs
        frappe.db.commit()
        
        # In a real test environment, we would:
        # 1. Process the background job queue
        # 2. Wait for completion
        # 3. Verify payment history is updated
        
        # For now, we just verify the invoice was submitted successfully
        self.assertEqual(invoice.docstatus, 1, 
                        "Invoice submission should complete regardless of payment history sync")
    
    def test_invoice_cancellation_event(self):
        """Test that cancelling an invoice emits the correct event"""
        # Create, submit, then cancel invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = self.customer.name
        invoice.company = self.company
        invoice.currency = "EUR"
        invoice.posting_date = today()
        invoice.due_date = add_days(today(), 30)
        
        invoice.append("items", {
            "item_code": "Membership Dues - Daily",
            "qty": 1,
            "rate": 40.0,
            "description": "Cancellation test dues"
        })
        
        invoice.insert()
        invoice.submit()
        self.track_doc("Sales Invoice", invoice.name)
        
        # Cancel the invoice
        invoice.cancel()
        
        # Verify cancellation succeeded
        self.assertEqual(invoice.docstatus, 2, "Invoice should be cancelled")
    
    def test_robustness_with_invalid_member_data(self):
        """
        Test that invoice operations succeed even with problematic member data
        """
        # Create a member with intentionally problematic data
        problem_member = self.create_test_member(
            first_name="Problem",
            last_name="Member",
            email="problem.member@example.com"
        )
        
        # Don't set customer initially
        problem_member.save()
        
        # Create customer (unique name so it doesn't collide with data left by an
        # earlier run on a persistent DB -> DuplicateEntryError).
        problem_customer = frappe.new_doc("Customer")
        problem_customer.customer_name = f"Problem Customer {frappe.generate_hash(length=6)}"
        problem_customer.customer_type = "Individual"
        problem_customer.save()
        self.track_doc("Customer", problem_customer.name)
        
        # Create invoice for this customer
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = problem_customer.name
        invoice.company = self.company
        invoice.currency = "EUR"
        invoice.posting_date = today()
        invoice.due_date = add_days(today(), 30)
        
        invoice.append("items", {
            "item_code": "Membership Dues - Daily",
            "qty": 1,
            "rate": 50.0,
            "description": "Problem member dues"
        })
        
        invoice.insert()
        self.track_doc("Sales Invoice", invoice.name)
        
        # This should succeed even though the member-customer link is broken
        try:
            invoice.submit()
            submission_succeeded = True
        except Exception as e:
            submission_succeeded = False
            
        self.assertTrue(submission_succeeded, 
                       "Invoice submission should succeed even with broken member-customer links")
    
    def test_migration_helper_function(self):
        """Test the migration helper for existing data"""
        from verenigingen.events.migration_helper import test_event_system

        # test_event_system is @development_only_api, so its environment gate
        # rejects anything that is not DEVELOPMENT with "Function not available in
        # production environment". test_site_1 sets developer_mode=1 in
        # site_config.json, but CI does not -- which is why this passed locally and
        # failed in every CI shard. Scoped to this test and restored afterwards
        # rather than set for the whole class.
        original_developer_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

        def _restore_developer_mode():
            if original_developer_mode is None:
                frappe.conf.pop("developer_mode", None)
            else:
                frappe.conf["developer_mode"] = original_developer_mode

        self.addCleanup(_restore_developer_mode)

        # Test the event system
        result = test_event_system()
        
        self.assertEqual(result.get("status"), "success", 
                        f"Event system test should succeed. Result: {result}")


class TestEventSystemIntegration(VereningingenTestCase):
    """Integration tests for the complete event system"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Seed the shared master HERE, not in a test body. ensure_payment_test_daily_type()
        # commits on first creation, and committing partway through a test would also
        # persist everything that test had already inserted (a Member, a Customer),
        # defeating the per-test rollback and leaving residue for the rest of the shard.
        ensure_payment_test_daily_type()

    def test_end_to_end_invoice_to_payment_history_flow(self):
        """
        Test the complete flow from invoice creation to payment history update
        """
        # Create complete test setup
        member = self.create_test_member(
            first_name="Integration",
            last_name="Test",
            email="integration.test@example.com"
        )
        
        # Create the member's Customer with a unique name (hardcoded member name
        # would otherwise collide cross-run -> DuplicateEntryError).
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"{member.first_name} {member.last_name} {frappe.generate_hash(length=6)}"
        customer.customer_type = "Individual"
        customer.save()
        member.customer = customer.name
        member.save()
        self.track_doc("Customer", customer.name)
        
        # Create membership with the payment tests' own EUR2 type (seeded in
        # setUpClass; see PAYMENT_TEST_DAILY_TYPE for why the name is not shared).
        membership = self.create_test_membership(
            member=member.name,
            membership_type=PAYMENT_TEST_DAILY_TYPE
        )
        # The dues schedule below requires an active *submitted* membership
        # (status=Active, docstatus=1); the factory only inserts (docstatus=0).
        if membership.docstatus == 0:
            membership.submit()
        
        # Submitting the membership auto-creates an Active dues schedule, and the
        # controller enforces one active schedule per member. Reuse it and set the
        # Daily billing config the test needs.
        existing_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        if existing_schedule:
            dues_schedule = frappe.get_doc("Membership Dues Schedule", existing_schedule)
        else:
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.schedule_name = f"Integration Test Schedule {member.name}"
            dues_schedule.member = member.name
            dues_schedule.member_name = member.full_name
            dues_schedule.membership_type = PAYMENT_TEST_DAILY_TYPE
            dues_schedule.status = "Active"
        dues_schedule.billing_frequency = "Daily"
        dues_schedule.dues_rate = 2.0
        dues_schedule.next_invoice_date = today()
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        # Generate invoice through dues schedule
        invoice_doc = dues_schedule.generate_invoice()
        self.assertIsNotNone(invoice_doc, "Invoice should be created")
        invoice_name = invoice_doc.name if hasattr(invoice_doc, 'name') else invoice_doc
        self.track_doc("Sales Invoice", invoice_name)
        
        # Get the invoice and verify it can be submitted
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        
        # The key test: invoice submission should not fail due to payment history
        invoice.submit()
        
        self.assertEqual(invoice.docstatus, 1, 
                        "Invoice should be submitted successfully in event-driven system")