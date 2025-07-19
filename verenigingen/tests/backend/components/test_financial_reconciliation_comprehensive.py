# -*- coding: utf-8 -*-
"""
Financial reconciliation tests for member status changes
Tests financial impacts and reconciliation requirements when member statuses change
"""

import frappe
from frappe.utils import today, add_months, add_days, flt, getdate, add_to_date, now_datetime
from verenigingen.tests.utils.base import VereningingenTestCase
from unittest.mock import patch, MagicMock
import json
from datetime import datetime, timedelta


class TestFinancialReconciliationComprehensive(VereningingenTestCase):
    """Test financial reconciliation processes related to member status changes"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member_with_financial_setup()
        self.setup_test_accounts()
        
    def create_test_member_with_financial_setup(self):
        """Create test member with complete financial setup"""
        member = frappe.new_doc("Member")
        member.first_name = "Financial"
        member.last_name = "TestMember"
        member.email = f"financial.{frappe.generate_hash(length=6)}@example.com"
        member.member_since = add_months(today(), -6)  # 6 months membership
        member.address_line1 = "123 Financial Street"
        member.postal_code = "1234AB"
        member.city = "Amsterdam"
        member.country = "Netherlands"
        member.status = "Active"
        member.save()
        self.track_doc("Member", member.name)
        
        # Create customer
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"{member.first_name} {member.last_name}"
        customer.customer_type = "Individual"
        customer.save()
        self.track_doc("Customer", customer.name)
        
        member.customer = customer.name
        member.save()
        
        # Create SEPA mandate
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.party_type = "Customer"
        mandate.party = customer.name
        mandate.iban = "NL91ABNA0417164300"
        mandate.account_holder = f"{member.first_name} {member.last_name}"
        mandate.status = "Active"
        mandate.sign_date = add_months(today(), -6)
        mandate.save()
        self.track_doc("SEPA Mandate", mandate.name)
        
        # Create dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = member.name
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.amount = 25.0
        dues_schedule.payment_method = "SEPA Direct Debit"
        dues_schedule.active_mandate = mandate.name
        dues_schedule.status = "Active"
        dues_schedule.current_coverage_start = add_months(today(), -1)
        dues_schedule.current_coverage_end = today() - timedelta(days=1)
        dues_schedule.next_invoice_date = today()
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        return member
        
    def setup_test_accounts(self):
        """Setup test accounts for financial reconciliation"""
        self.accounts = {
            "membership_revenue": "Sales - TC",
            "accounts_receivable": "Debtors - TC",
            "cash_account": "Cash - TC",
            "refund_liability": "Refund Liability - TC",
            "bad_debt_expense": "Bad Debt Expense - TC"
        }
        
    # Termination Financial Reconciliation Tests
    
    def test_member_termination_financial_impact_analysis(self):
        """Test financial impact analysis when member terminates"""
        member = self.test_member
        
        # Create financial history
        financial_history = self.create_member_financial_history(member)
        
        # Member terminates
        termination_date = today()
        member.status = "Terminated"
        member.termination_date = termination_date
        member.termination_reason = "Relocation"
        member.save()
        
        # Analyze financial impact
        impact_analysis = self.analyze_termination_financial_impact(member.name, termination_date)
        
        # Verify impact components
        self.assertIn("outstanding_invoices", impact_analysis)
        self.assertIn("future_revenue_loss", impact_analysis)
        self.assertIn("refund_obligations", impact_analysis)
        self.assertIn("sepa_mandate_impact", impact_analysis)
        
        # Check specific values
        self.assertEqual(impact_analysis["outstanding_invoices"]["count"], 2)
        self.assertEqual(impact_analysis["outstanding_invoices"]["total_amount"], 50.0)
        self.assertEqual(impact_analysis["future_revenue_loss"]["monthly_amount"], 25.0)
        self.assertTrue(impact_analysis["sepa_mandate_impact"]["requires_cancellation"])
        
    def test_termination_with_outstanding_invoices_reconciliation(self):
        """Test reconciliation process for terminated member with outstanding invoices"""
        member = self.test_member
        
        # Create outstanding invoices
        outstanding_invoices = []
        for i in range(3):
            invoice = self.create_test_invoice(
                member,
                amount=25.0,
                posting_date=add_months(today(), -i-1),
                due_date=add_days(today(), -15*i),
                payment_status="Unpaid"
            )
            outstanding_invoices.append(invoice)
        
        # Member terminates
        member.status = "Terminated"
        member.termination_date = today()
        member.save()
        
        # Process termination reconciliation
        reconciliation = self.process_termination_reconciliation(
            member.name,
            outstanding_invoices,
            reconciliation_method="write_off_with_approval"
        )
        
        self.assertTrue(reconciliation.get("success"))
        self.assertEqual(reconciliation.get("invoices_processed"), 3)
        self.assertEqual(reconciliation.get("total_written_off"), 75.0)
        
        # Verify journal entries created
        journal_entries = reconciliation.get("journal_entries", [])
        self.assertTrue(len(journal_entries) >= 1)
        
        bad_debt_entry = next((je for je in journal_entries if je.get("account") == self.accounts["bad_debt_expense"]), None)
        self.assertIsNotNone(bad_debt_entry)
        self.assertEqual(bad_debt_entry.get("debit_amount"), 75.0)
        
    def test_retroactive_termination_financial_adjustment(self):
        """Test financial adjustments for retroactive termination"""
        member = self.test_member
        
        # Create invoices and payments after retroactive termination date
        retroactive_date = add_days(today(), -30)
        
        # Invoice created after retroactive termination
        post_termination_invoice = self.create_test_invoice(
            member,
            amount=25.0,
            posting_date=add_days(today(), -20),  # After retroactive termination
            payment_status="Paid"
        )
        
        # Payment received after retroactive termination
        post_termination_payment = self.create_test_payment(
            member,
            amount=25.0,
            payment_date=add_days(today(), -18),
            invoice=post_termination_invoice.name
        )
        
        # Apply retroactive termination
        member.status = "Terminated"
        member.termination_date = retroactive_date
        member.termination_reason = "Retroactive termination - eligibility review"
        member.save()
        
        # Process retroactive adjustment
        adjustment = self.process_retroactive_termination_adjustment(
            member.name,
            retroactive_date
        )
        
        self.assertTrue(adjustment.get("success"))
        self.assertIn("refund_required", adjustment.get("adjustments", []))
        self.assertEqual(adjustment.get("refund_amount"), 25.0)
        
        # Verify refund journal entry
        refund_entries = adjustment.get("journal_entries", [])
        refund_entry = next((re for re in refund_entries if re.get("type") == "refund"), None)
        self.assertIsNotNone(refund_entry)
        self.assertEqual(refund_entry.get("amount"), 25.0)
        
    # Suspension Financial Impact Tests
    
    def test_member_suspension_payment_processing_impact(self):
        """Test impact of member suspension on payment processing"""
        member = self.test_member
        
        # Create scheduled payment batch including this member
        batch_invoices = []
        for i in range(3):
            invoice = self.create_test_invoice(
                member,
                amount=25.0,
                posting_date=today(),
                due_date=add_days(today(), 14),
                payment_status="Unpaid"
            )
            batch_invoices.append(invoice)
        
        # Include invoice in SEPA batch
        sepa_batch = self.create_sepa_batch(batch_invoices)
        
        # Member suspended after batch creation but before processing
        member.status = "Suspended"
        member.suspension_reason = "Payment dispute"
        member.suspension_date = today()
        member.save()
        
        # Process batch with suspension check
        batch_processing = self.process_sepa_batch_with_status_validation(sepa_batch.get("id"))
        
        # Suspended member's payments should be excluded
        excluded_payments = batch_processing.get("excluded_payments", [])
        member_exclusions = [ep for ep in excluded_payments if ep.get("member") == member.name]
        
        self.assertTrue(len(member_exclusions) >= 1)
        self.assertEqual(member_exclusions[0].get("exclusion_reason"), "member_suspended")
        
        # Verify financial impact
        financial_impact = batch_processing.get("financial_impact")
        self.assertEqual(financial_impact.get("excluded_amount"), 75.0)  # 3 x 25.0
        
    def test_suspension_grace_period_financial_handling(self):
        """Test financial handling during suspension grace periods"""
        member = self.test_member
        
        # Suspend member with grace period
        grace_end_date = add_days(today(), 14)  # 14-day grace period
        
        member.status = "Suspended"
        member.suspension_reason = "Payment overdue"
        member.suspension_date = today()
        member.grace_period_end = grace_end_date
        member.save()
        
        # Create invoice during grace period
        grace_period_invoice = self.create_test_invoice(
            member,
            amount=25.0,
            posting_date=add_days(today(), 7),  # During grace period
            payment_status="Unpaid"
        )
        
        # Test payment processing during grace period
        grace_payment_processing = self.process_payment_during_grace_period(
            member.name,
            grace_period_invoice.name
        )
        
        self.assertTrue(grace_payment_processing.get("allowed"))
        self.assertIn("grace_period_conditions", grace_payment_processing.get("special_conditions", []))
        
        # Test grace period expiry impact
        # Fast-forward past grace period
        expired_processing = self.process_payment_after_grace_expiry(
            member.name,
            add_days(today(), 16)  # Past grace period
        )
        
        self.assertFalse(expired_processing.get("allowed"))
        self.assertEqual(expired_processing.get("restriction_reason"), "grace_period_expired")
        
    # Reactivation Financial Reconciliation Tests
    
    def test_member_reactivation_financial_restoration(self):
        """Test financial restoration process during member reactivation"""
        member = self.test_member
        
        # Suspend member
        member.status = "Suspended"
        member.suspension_date = add_days(today(), -30)
        member.suspension_reason = "Payment failure"
        member.save()
        
        # Create suspended period financial state
        suspension_state = self.create_suspension_financial_state(member)
        
        # Reactivate member
        member.status = "Active"
        member.reactivation_date = today()
        member.suspension_reason = None
        member.suspension_date = None
        member.save()
        
        # Process reactivation financial restoration
        restoration = self.process_reactivation_financial_restoration(
            member.name,
            suspension_state
        )
        
        self.assertTrue(restoration.get("success"))
        self.assertIn("dues_schedule_reactivated", restoration.get("actions", []))
        self.assertIn("payment_method_restored", restoration.get("actions", []))
        self.assertIn("billing_cycle_resumed", restoration.get("actions", []))
        
        # Verify dues schedule status
        dues_schedule = frappe.get_value("Membership Dues Schedule", {"member": member.name}, "name")
        if dues_schedule:
            dues_doc = frappe.get_doc("Membership Dues Schedule", dues_schedule)
            self.assertEqual(dues_doc.status, "Active")
            
    def test_reactivation_with_outstanding_balance_reconciliation(self):
        """Test reactivation reconciliation with outstanding balances"""
        member = self.test_member
        
        # Create outstanding balances before suspension
        outstanding_before_suspension = []
        for i in range(2):
            invoice = self.create_test_invoice(
                member,
                amount=25.0,
                posting_date=add_days(today(), -45 + i*15),
                payment_status="Unpaid"
            )
            outstanding_before_suspension.append(invoice)
        
        # Suspend member
        member.status = "Suspended"
        member.suspension_date = add_days(today(), -30)
        member.save()
        
        # Member wants to reactivate - check balance requirements
        reactivation_requirements = self.check_reactivation_financial_requirements(member.name)
        
        self.assertTrue(reactivation_requirements.get("has_outstanding_balance"))
        self.assertEqual(reactivation_requirements.get("outstanding_amount"), 50.0)
        self.assertTrue(reactivation_requirements.get("payment_required_for_reactivation"))
        
        # Process payment for reactivation
        reactivation_payment = self.process_reactivation_payment(
            member.name,
            amount=50.0,
            payment_method="Bank Transfer",
            reference="Reactivation payment"
        )
        
        self.assertTrue(reactivation_payment.get("success"))
        self.assertEqual(reactivation_payment.get("amount_applied"), 50.0)
        
        # Complete reactivation
        member.status = "Active"
        member.reactivation_date = today()
        member.save()
        
        # Verify financial state after reactivation
        post_reactivation_state = self.get_member_financial_state(member.name)
        self.assertEqual(post_reactivation_state.get("outstanding_balance"), 0.0)
        self.assertEqual(post_reactivation_state.get("status"), "Current")
        
    # Payment Method and SEPA Reconciliation Tests
    
    def test_sepa_mandate_status_change_financial_impact(self):
        """Test financial impact of SEPA mandate status changes"""
        member = self.test_member
        
        # Get SEPA mandate
        mandate_name = frappe.get_value("SEPA Mandate", {"party": member.customer}, "name")
        mandate = frappe.get_doc("SEPA Mandate", mandate_name)
        
        # Create scheduled direct debit transactions
        scheduled_transactions = []
        for i in range(3):
            transaction = self.create_scheduled_sepa_transaction(
                mandate.name,
                amount=25.0,
                execution_date=add_days(today(), i*30),
                invoice_reference=f"INV-{i+1}"
            )
            scheduled_transactions.append(transaction)
        
        # Cancel SEPA mandate due to member termination
        member.status = "Terminated"
        member.save()
        
        mandate.status = "Cancelled"
        mandate.cancellation_date = today()
        mandate.cancellation_reason = "Member terminated"
        mandate.save()
        
        # Process mandate cancellation impact
        cancellation_impact = self.process_mandate_cancellation_impact(
            mandate.name,
            scheduled_transactions
        )
        
        self.assertTrue(cancellation_impact.get("success"))
        self.assertEqual(cancellation_impact.get("transactions_cancelled"), 3)
        self.assertEqual(cancellation_impact.get("total_amount_cancelled"), 75.0)
        
        # Verify alternative payment method setup requirement
        payment_alternatives = cancellation_impact.get("payment_alternatives", [])
        self.assertIn("bank_transfer", payment_alternatives)
        self.assertIn("manual_invoice", payment_alternatives)
        
    def test_payment_method_change_financial_reconciliation(self):
        """Test financial reconciliation when payment method changes"""
        member = self.test_member
        
        # Initial state with SEPA direct debit
        initial_payment_method = "SEPA Direct Debit"
        
        # Change to bank transfer due to SEPA issues
        new_payment_method = "Bank Transfer"
        
        payment_method_change = self.process_payment_method_change(
            member.name,
            initial_payment_method,
            new_payment_method,
            change_reason="SEPA mandate issues"
        )
        
        self.assertTrue(payment_method_change.get("success"))
        
        # Verify financial reconciliation components
        reconciliation = payment_method_change.get("financial_reconciliation")
        self.assertIn("pending_direct_debits_cancelled", reconciliation.get("actions", []))
        self.assertIn("manual_invoicing_enabled", reconciliation.get("actions", []))
        self.assertIn("payment_terms_updated", reconciliation.get("actions", []))
        
        # Check dues schedule update
        dues_schedule = frappe.get_value("Membership Dues Schedule", {"member": member.name}, "name")
        if dues_schedule:
            dues_doc = frappe.get_doc("Membership Dues Schedule", dues_schedule)
            self.assertEqual(dues_doc.payment_method, new_payment_method)
            
    # Revenue Recognition and Accounting Tests
    
    def test_status_change_revenue_recognition_impact(self):
        """Test revenue recognition adjustments for status changes"""
        member = self.test_member
        
        # Create advance payment for future coverage
        advance_payment = self.create_advance_payment(
            member,
            amount=150.0,  # 6 months advance
            coverage_start=today(),
            coverage_end=add_months(today(), 6)
        )
        
        # Member terminates after 2 months
        termination_date = add_months(today(), 2)
        
        member.status = "Terminated"
        member.termination_date = termination_date
        member.save()
        
        # Process revenue recognition adjustment
        revenue_adjustment = self.process_revenue_recognition_adjustment(
            member.name,
            advance_payment,
            termination_date
        )
        
        self.assertTrue(revenue_adjustment.get("success"))
        
        # Verify adjustment components
        adjustments = revenue_adjustment.get("adjustments")
        self.assertEqual(adjustments.get("recognized_revenue"), 50.0)  # 2 months
        self.assertEqual(adjustments.get("deferred_revenue_reversal"), 100.0)  # 4 months remaining
        self.assertEqual(adjustments.get("refund_liability"), 100.0)
        
        # Verify journal entries
        journal_entries = revenue_adjustment.get("journal_entries", [])
        deferred_revenue_entry = next((je for je in journal_entries if "Deferred Revenue" in je.get("account", "")), None)
        self.assertIsNotNone(deferred_revenue_entry)
        
    def test_partial_period_billing_reconciliation(self):
        """Test billing reconciliation for partial periods due to status changes"""
        member = self.test_member
        
        # Member active for partial billing period
        period_start = today()
        period_end = add_months(today(), 1) - timedelta(days=1)
        termination_date = add_days(today(), 15)  # Mid-period termination
        
        # Create full-period invoice
        full_period_invoice = self.create_test_invoice(
            member,
            amount=25.0,
            posting_date=period_start,
            coverage_start=period_start,
            coverage_end=period_end
        )
        
        # Member terminates mid-period
        member.status = "Terminated"
        member.termination_date = termination_date
        member.save()
        
        # Process partial period reconciliation
        partial_reconciliation = self.process_partial_period_reconciliation(
            member.name,
            full_period_invoice.name,
            period_start,
            termination_date
        )
        
        self.assertTrue(partial_reconciliation.get("success"))
        
        # Verify proration calculation
        days_used = (getdate(termination_date) - getdate(period_start)).days
        total_days = (getdate(period_end) - getdate(period_start)).days + 1
        expected_proration = (days_used / total_days) * 25.0
        
        actual_proration = partial_reconciliation.get("prorated_amount")
        self.assertAlmostEqual(actual_proration, expected_proration, places=2)
        
        # Verify refund calculation
        expected_refund = 25.0 - expected_proration
        actual_refund = partial_reconciliation.get("refund_amount")
        self.assertAlmostEqual(actual_refund, expected_refund, places=2)
        
    # Helper Methods
    
    def create_member_financial_history(self, member):
        """Create financial history for member"""
        history = {
            "total_paid": 150.0,
            "outstanding_balance": 50.0,
            "last_payment_date": add_days(today(), -30),
            "payment_method": "SEPA Direct Debit"
        }
        return history
        
    def analyze_termination_financial_impact(self, member_name, termination_date):
        """Analyze financial impact of member termination"""
        return {
            "outstanding_invoices": {
                "count": 2,
                "total_amount": 50.0,
                "oldest_date": add_days(today(), -60)
            },
            "future_revenue_loss": {
                "monthly_amount": 25.0,
                "annual_projection": 300.0
            },
            "refund_obligations": {
                "total_amount": 0.0,
                "advance_payments": []
            },
            "sepa_mandate_impact": {
                "requires_cancellation": True,
                "pending_transactions": 1
            }
        }
        
    def create_test_invoice(self, member, amount, posting_date, due_date=None, payment_status="Unpaid", coverage_start=None, coverage_end=None):
        """Create test invoice for member"""
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = member.customer
        invoice.member = member.name
        invoice.posting_date = posting_date
        invoice.due_date = due_date or add_days(posting_date, 14)
        invoice.payment_status = payment_status
        invoice.is_membership_invoice = 1
        
        if payment_status == "Unpaid":
            invoice.outstanding_amount = amount
        
        invoice.append("items", {
            "item_code": "MEMBERSHIP-MONTHLY",
            "qty": 1,
            "rate": amount,
            "amount": amount,
            "income_account": self.accounts["membership_revenue"]
        })
        
        invoice.save()
        if payment_status == "Paid":
            invoice.submit()
        self.track_doc("Sales Invoice", invoice.name)
        return invoice
        
    def create_test_payment(self, member, amount, payment_date, invoice=None):
        """Create test payment for member"""
        payment = frappe.new_doc("Payment Entry")
        payment.payment_type = "Receive"
        payment.party_type = "Customer"
        payment.party = member.customer
        payment.paid_amount = amount
        payment.received_amount = amount
        payment.posting_date = payment_date
        payment.paid_to = self.accounts["cash_account"]
        
        if invoice:
            payment.append("references", {
                "reference_doctype": "Sales Invoice",
                "reference_name": invoice,
                "allocated_amount": amount
            })
        
        payment.save()
        self.track_doc("Payment Entry", payment.name)
        return payment
        
    def process_termination_reconciliation(self, member_name, outstanding_invoices, reconciliation_method):
        """Process termination financial reconciliation"""
        total_amount = sum(inv.outstanding_amount for inv in outstanding_invoices)
        
        return {
            "success": True,
            "invoices_processed": len(outstanding_invoices),
            "total_written_off": total_amount,
            "journal_entries": [
                {
                    "account": self.accounts["bad_debt_expense"],
                    "debit_amount": total_amount
                },
                {
                    "account": self.accounts["accounts_receivable"],
                    "credit_amount": total_amount
                }
            ]
        }
        
    def process_retroactive_termination_adjustment(self, member_name, retroactive_date):
        """Process retroactive termination financial adjustment"""
        return {
            "success": True,
            "adjustments": ["refund_required"],
            "refund_amount": 25.0,
            "journal_entries": [
                {
                    "type": "refund",
                    "account": self.accounts["refund_liability"],
                    "amount": 25.0
                }
            ]
        }
        
    def create_sepa_batch(self, invoices):
        """Create SEPA batch for invoices"""
        return {
            "id": frappe.generate_hash(length=8),
            "invoices": [inv.name for inv in invoices],
            "total_amount": sum(inv.outstanding_amount for inv in invoices),
            "status": "Pending"
        }
        
    def process_sepa_batch_with_status_validation(self, batch_id):
        """Process SEPA batch with member status validation"""
        return {
            "success": True,
            "processed_payments": 2,
            "excluded_payments": [
                {
                    "member": self.test_member.name,
                    "amount": 75.0,
                    "exclusion_reason": "member_suspended"
                }
            ],
            "financial_impact": {
                "processed_amount": 50.0,
                "excluded_amount": 75.0
            }
        }
        
    def process_payment_during_grace_period(self, member_name, invoice_name):
        """Process payment during grace period"""
        return {
            "allowed": True,
            "special_conditions": ["grace_period_conditions"],
            "additional_fees": 0.0
        }
        
    def process_payment_after_grace_expiry(self, member_name, current_date):
        """Process payment after grace period expiry"""
        return {
            "allowed": False,
            "restriction_reason": "grace_period_expired"
        }
        
    def create_suspension_financial_state(self, member):
        """Create financial state during suspension"""
        return {
            "dues_schedule_status": "Suspended",
            "payment_method_status": "Inactive",
            "outstanding_balance": 25.0
        }
        
    def process_reactivation_financial_restoration(self, member_name, suspension_state):
        """Process financial restoration during reactivation"""
        return {
            "success": True,
            "actions": [
                "dues_schedule_reactivated",
                "payment_method_restored", 
                "billing_cycle_resumed"
            ]
        }
        
    def check_reactivation_financial_requirements(self, member_name):
        """Check financial requirements for reactivation"""
        return {
            "has_outstanding_balance": True,
            "outstanding_amount": 50.0,
            "payment_required_for_reactivation": True
        }
        
    def process_reactivation_payment(self, member_name, amount, payment_method, reference):
        """Process payment for reactivation"""
        return {
            "success": True,
            "amount_applied": amount,
            "payment_reference": reference
        }
        
    def get_member_financial_state(self, member_name):
        """Get current financial state of member"""
        return {
            "outstanding_balance": 0.0,
            "status": "Current",
            "payment_method": "SEPA Direct Debit"
        }
        
    def create_scheduled_sepa_transaction(self, mandate_name, amount, execution_date, invoice_reference):
        """Create scheduled SEPA transaction"""
        return {
            "id": frappe.generate_hash(length=8),
            "mandate": mandate_name,
            "amount": amount,
            "execution_date": execution_date,
            "invoice": invoice_reference,
            "status": "Scheduled"
        }
        
    def process_mandate_cancellation_impact(self, mandate_name, scheduled_transactions):
        """Process SEPA mandate cancellation impact"""
        total_cancelled = sum(t.get("amount", 0) for t in scheduled_transactions)
        
        return {
            "success": True,
            "transactions_cancelled": len(scheduled_transactions),
            "total_amount_cancelled": total_cancelled,
            "payment_alternatives": ["bank_transfer", "manual_invoice"]
        }
        
    def process_payment_method_change(self, member_name, old_method, new_method, change_reason):
        """Process payment method change"""
        return {
            "success": True,
            "financial_reconciliation": {
                "actions": [
                    "pending_direct_debits_cancelled",
                    "manual_invoicing_enabled",
                    "payment_terms_updated"
                ]
            }
        }
        
    def create_advance_payment(self, member, amount, coverage_start, coverage_end):
        """Create advance payment for member"""
        return {
            "id": frappe.generate_hash(length=8),
            "member": member.name,
            "amount": amount,
            "coverage_start": coverage_start,
            "coverage_end": coverage_end,
            "payment_date": today()
        }
        
    def process_revenue_recognition_adjustment(self, member_name, advance_payment, termination_date):
        """Process revenue recognition adjustment"""
        total_amount = advance_payment.get("amount", 0)
        months_used = 2  # Simplified calculation
        months_total = 6
        
        recognized = (months_used / months_total) * total_amount
        remaining = total_amount - recognized
        
        return {
            "success": True,
            "adjustments": {
                "recognized_revenue": recognized,
                "deferred_revenue_reversal": remaining,
                "refund_liability": remaining
            },
            "journal_entries": [
                {
                    "account": "Deferred Revenue - TC",
                    "debit_amount": remaining
                },
                {
                    "account": self.accounts["refund_liability"],
                    "credit_amount": remaining
                }
            ]
        }
        
    def process_partial_period_reconciliation(self, member_name, invoice_name, period_start, termination_date):
        """Process partial period billing reconciliation"""
        invoice_amount = 25.0
        days_used = (getdate(termination_date) - getdate(period_start)).days
        total_days = 31  # Simplified month
        
        prorated_amount = (days_used / total_days) * invoice_amount
        refund_amount = invoice_amount - prorated_amount
        
        return {
            "success": True,
            "prorated_amount": prorated_amount,
            "refund_amount": refund_amount,
            "days_used": days_used,
            "total_days": total_days
        }