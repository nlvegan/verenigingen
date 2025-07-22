"""
Regression test for the due date calculation issue found with ACC-SINV-2025-20221
Tests that invoice due dates are calculated correctly and not set to past dates.
"""

import frappe
from frappe.utils import today, add_days, getdate
from verenigingen.tests.utils.base import VereningingenTestCase


class TestRegressionInvoiceDueDateCalculation(VereningingenTestCase):
    """
    Regression test for the due date calculation bug where invoices were
    showing as "Overdue" on the same day they were created.
    
    Original issue: ACC-SINV-2025-20221 had:
    - posting_date: "2025-07-22" 
    - due_date: "2025-07-21" (PAST DATE!)
    - Result: Same-day invoice showed as "Overdue"
    
    Root cause: due_date was set to self.next_invoice_date instead of proper payment due date
    """

    def test_dues_schedule_invoice_due_date_not_in_past(self):
        """
        Test that dues schedule generated invoices have due dates in the future.
        
        This test prevents the exact bug that caused ACC-SINV-2025-20221 to 
        show as overdue on the same day it was created.
        """
        # Create test setup
        member = self.create_test_member(
            first_name="DueDate",
            last_name="Test",
            email="duedate.test@example.com"
        )
        
        # Create customer
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"{member.first_name} {member.last_name}"
        customer.customer_type = "Individual"
        customer.save()
        member.customer = customer.name
        member.save()
        self.track_doc("Customer", customer.name)
        
        # Create dues schedule with next_invoice_date in the PAST
        # This simulates the original bug condition
        past_date = add_days(today(), -1)  # Yesterday
        
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.schedule_name = f"DueDate Test Schedule {member.name}"
        dues_schedule.member = member.name
        dues_schedule.member_name = member.full_name
        dues_schedule.membership_type = "Daglid"
        dues_schedule.status = "Active"
        dues_schedule.billing_frequency = "Daily"
        dues_schedule.dues_rate = 2.0
        dues_schedule.next_invoice_date = past_date  # This is the problematic scenario
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        # Generate invoice using the dues schedule
        invoice_name = dues_schedule.create_sales_invoice()
        self.assertIsNotNone(invoice_name, "Invoice should be created successfully")
        self.track_doc("Sales Invoice", invoice_name)
        
        # Get the created invoice
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        
        # CRITICAL TEST: Due date should NOT be set to next_invoice_date (past date)
        due_date = getdate(invoice.due_date)
        posting_date = getdate(invoice.posting_date)
        next_invoice_date = getdate(dues_schedule.next_invoice_date)
        
        # Due date should NOT equal the past next_invoice_date
        self.assertNotEqual(due_date, next_invoice_date,
                           "Due date should NOT be set to next_invoice_date (this was the original bug)")
        
        # Due date should be on or after posting date
        self.assertGreaterEqual(due_date, posting_date,
                               "Due date must not be before posting date")
        
        # For daily billing without payment terms, due date should be 30 days from posting
        if not invoice.payment_terms_template:
            expected_due_date = add_days(posting_date, 30)
            self.assertEqual(due_date, expected_due_date,
                           "Due date should be 30 days from posting date when no payment terms")
        
        # Invoice should not immediately show as overdue
        self.assertNotEqual(invoice.status, "Overdue",
                           "Same-day invoice should not immediately be overdue")

    def test_invoice_due_date_with_payment_terms(self):
        """
        Test that invoices with payment terms calculate due dates correctly.
        """
        # Create test setup
        member = self.create_test_member(
            first_name="PaymentTerms",
            last_name="Test", 
            email="paymentterms.test@example.com"
        )
        
        # Create customer
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"{member.first_name} {member.last_name}"
        customer.customer_type = "Individual"
        customer.save()
        member.customer = customer.name
        member.save()
        self.track_doc("Customer", customer.name)
        
        # Create a payment terms template (if it doesn't exist)
        payment_terms_name = "Net 15 Days"
        if not frappe.db.exists("Payment Terms Template", payment_terms_name):
            payment_terms = frappe.new_doc("Payment Terms Template")
            payment_terms.template_name = payment_terms_name
            payment_terms.append("terms", {
                "payment_term": "Net 15 Days",
                "description": "15% due in 15 days",
                "invoice_portion": 100,
                "due_date_based_on": "Day(s) after invoice date",
                "credit_days": 15
            })
            payment_terms.save()
            self.track_doc("Payment Terms Template", payment_terms_name)
        
        # Create dues schedule with payment terms
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.schedule_name = f"PaymentTerms Test Schedule {member.name}"
        dues_schedule.member = member.name
        dues_schedule.member_name = member.full_name
        dues_schedule.membership_type = "Daglid"
        dues_schedule.status = "Active"
        dues_schedule.billing_frequency = "Daily"
        dues_schedule.dues_rate = 2.0
        dues_schedule.next_invoice_date = add_days(today(), -1)  # Past date
        dues_schedule.payment_terms_template = payment_terms_name
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        # Generate invoice
        invoice_name = dues_schedule.create_sales_invoice()
        self.track_doc("Sales Invoice", invoice_name)
        
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        
        # Verify payment terms template was set
        self.assertEqual(invoice.payment_terms_template, payment_terms_name,
                        "Payment terms template should be set on invoice")
        
        # Due date should be calculated by ERPNext based on payment terms
        # Not the past next_invoice_date
        due_date = getdate(invoice.due_date)
        posting_date = getdate(invoice.posting_date)
        next_invoice_date = getdate(dues_schedule.next_invoice_date)
        
        self.assertNotEqual(due_date, next_invoice_date,
                           "Due date should not be set to next_invoice_date when payment terms exist")
        
        self.assertGreaterEqual(due_date, posting_date,
                               "Due date should not be before posting date")

    def test_multiple_invoice_due_date_scenarios(self):
        """
        Test various scenarios for due date calculation to ensure robustness.
        """
        scenarios = [
            {
                "name": "Past next_invoice_date, no payment terms",
                "next_invoice_date": add_days(today(), -5),
                "payment_terms": None,
                "expected_due_offset": 30  # Days from posting date
            },
            {
                "name": "Future next_invoice_date, no payment terms", 
                "next_invoice_date": add_days(today(), 5),
                "payment_terms": None,
                "expected_due_offset": 30  # Should still use 30 days, not next_invoice_date
            },
            {
                "name": "Today next_invoice_date, no payment terms",
                "next_invoice_date": today(),
                "payment_terms": None, 
                "expected_due_offset": 30
            }
        ]
        
        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]):
                # Create member for this scenario
                member = self.create_test_member(
                    first_name="Scenario",
                    last_name=f"Test{len(scenarios)}",
                    email=f"scenario{len(scenarios)}.test@example.com"
                )
                
                # Create customer
                customer = frappe.new_doc("Customer")
                customer.customer_name = f"{member.first_name} {member.last_name}"
                customer.customer_type = "Individual"
                customer.save()
                member.customer = customer.name
                member.save()
                self.track_doc("Customer", customer.name)
                
                # Create dues schedule
                dues_schedule = frappe.new_doc("Membership Dues Schedule")
                dues_schedule.schedule_name = f"Scenario {scenario['name']} {member.name}"
                dues_schedule.member = member.name
                dues_schedule.member_name = member.full_name
                dues_schedule.membership_type = "Daglid"
                dues_schedule.status = "Active"
                dues_schedule.billing_frequency = "Daily"
                dues_schedule.dues_rate = 2.0
                dues_schedule.next_invoice_date = scenario["next_invoice_date"]
                if scenario["payment_terms"]:
                    dues_schedule.payment_terms_template = scenario["payment_terms"]
                dues_schedule.save()
                self.track_doc("Membership Dues Schedule", dues_schedule.name)
                
                # Generate invoice
                invoice_name = dues_schedule.create_sales_invoice()
                self.track_doc("Sales Invoice", invoice_name)
                
                invoice = frappe.get_doc("Sales Invoice", invoice_name)
                
                # Verify due date
                due_date = getdate(invoice.due_date)
                posting_date = getdate(invoice.posting_date)
                next_invoice_date = getdate(scenario["next_invoice_date"])
                
                # Due date should NEVER be set to next_invoice_date
                self.assertNotEqual(due_date, next_invoice_date,
                                   f"Due date should not equal next_invoice_date in scenario: {scenario['name']}")
                
                # Due date should not be in the past
                self.assertGreaterEqual(due_date, posting_date,
                                       f"Due date should not be before posting date in scenario: {scenario['name']}")
                
                # For scenarios without payment terms, check expected offset
                if not scenario["payment_terms"] and scenario["expected_due_offset"]:
                    expected_due_date = add_days(posting_date, scenario["expected_due_offset"])
                    self.assertEqual(due_date, expected_due_date,
                                   f"Due date should be {scenario['expected_due_offset']} days from posting in scenario: {scenario['name']}")

    def test_original_bug_scenario_exact_reproduction(self):
        """
        Exact reproduction of the original bug scenario for ACC-SINV-2025-20221.
        
        Original conditions:
        - Member: Assoc-Member-2025-07-0025 (Parko Janssen)  
        - Invoice: ACC-SINV-2025-20221
        - Membership type: Daglid (daily billing)
        - Issue: posting_date = 2025-07-22, due_date = 2025-07-21
        """
        # Create member similar to Parko Janssen
        member = self.create_test_member(
            first_name="Parko",
            last_name="TestUser",
            email="parko.testuser@example.com"
        )
        
        # Create customer
        customer = frappe.new_doc("Customer") 
        customer.customer_name = f"{member.first_name} {member.last_name} - 1"  # Similar naming
        customer.customer_type = "Individual"
        customer.save()
        member.customer = customer.name
        member.save()
        self.track_doc("Customer", customer.name)
        
        # Create membership
        membership = self.create_test_membership(
            member=member.name,
            membership_type="Daglid"
        )
        
        # Create dues schedule similar to the original
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.schedule_name = f"Daily Schedule {member.name}"
        dues_schedule.member = member.name
        dues_schedule.member_name = member.full_name
        dues_schedule.membership_type = "Daglid"
        dues_schedule.status = "Active"
        dues_schedule.billing_frequency = "Daily"
        dues_schedule.dues_rate = 2.0
        # Set next_invoice_date to yesterday (this caused the original bug)
        dues_schedule.next_invoice_date = add_days(today(), -1)
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        # Generate invoice (this is what happened at 06:22:52 on 2025-07-22)
        invoice_name = dues_schedule.create_sales_invoice()
        self.track_doc("Sales Invoice", invoice_name)
        
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        
        # VERIFY THE BUG IS FIXED
        posting_date = getdate(invoice.posting_date)
        due_date = getdate(invoice.due_date)
        
        # This was the original bug: due_date was before posting_date
        self.assertGreaterEqual(due_date, posting_date,
                               "Fixed: Due date should not be before posting date (original ACC-SINV-2025-20221 bug)")
        
        # Invoice should not immediately be overdue
        # (Note: status might be calculated differently, so we focus on the date logic)
        days_overdue = (posting_date - due_date).days
        self.assertLessEqual(days_overdue, 0,
                            "Invoice should not be overdue on creation date (original bug symptom)")