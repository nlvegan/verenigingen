# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Payment Failure & Recovery Workflow Test
Tests payment failure scenarios and recovery processes
"""


import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.services.customer_group_resolver import resolve_non_group_customer_group
from verenigingen.tests.utils.base import VereningingenWorkflowTestCase
from verenigingen.tests.utils.reminder_mail_state import ensure_outgoing_email_account
from verenigingen.tests.utils.factories import TestDataBuilder, TestStateManager


class TestPaymentFailureRecovery(VereningingenWorkflowTestCase):
    """
    Payment Failure & Recovery Test

    Stage 1: Create member with SEPA mandate
    Stage 2: A membership invoice is left unpaid (the collection failed)
    Stage 3: The payment retry is scheduled through the real API
    Stage 4: Retries are exhausted and the failure is escalated
    Stage 5: The member is suspended (staff action; not triggered by escalation in production)
    Stage 6: The invoice is paid and the member is reactivated (not triggered by payment in production)

    Every stage drives production code (retry_failed_payment, PaymentRetryManager,
    suspend_member_safe, unsuspend_member_safe) and asserts what that code wrote.
    """

    def setUp(self):
        """Set up the payment failure recovery test"""
        super().setUp()
        self.state_manager = TestStateManager()
        self.test_data_builder = TestDataBuilder()

        # The acting user is staff registered the way real staff are: through a staff Team whose
        # default role profile is Verenigingen Administrator (#2467). Roles alone are not enough:
        # the @critical_api(FINANCIAL) endpoints grant CRITICAL through a Role Profile only.
        self.admin_user = self._create_team_registered_admin()

        # Ensure ERPNext infrastructure exists for payment testing
        self.erpnext_infra = self.ensure_erpnext_infrastructure()

        # Create test environment with proper permissions
        self.test_chapter = self.create_test_chapter(
            chapter_name=f"Payment Test Chapter {frappe.generate_hash(length=6)}",
            postal_codes="3000-7999",
            introduction="Test chapter for payment failure testing",
        )

        # A uniquely named type: "Annual" is get-or-created by other modules' fixtures, so a
        # literal name collides in setUp when they run first in a shard.
        self.membership_type = self.create_test_membership_type()

        # The escalation mail is queued only when a default outgoing account exists (CI has none).
        ensure_outgoing_email_account(self)

    def tearDown(self):
        # Seating a profile that carries Employee creates one for the user (#1694); drain it.
        for user in [d["name"] for d in self._test_docs if d["doctype"] == "User"]:
            for employee in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
                self.track_doc("Employee", employee)
        super().tearDown()

    def _create_team_registered_admin(self):
        """A user whose Verenigingen Administrator profile comes from a Team membership"""
        from verenigingen.services.member.account.user_role_profile_calculator import (
            sync_user_role_profile,
        )
        from verenigingen.setup import create_default_team_roles

        email = f"payrecovery.admin.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name="PayAdmin", last_name="Staff", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)

        create_default_team_roles()
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"Payment Recovery Admins {frappe.generate_hash(length=6)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": today(),
                "default_role_profile": "Verenigingen Administrator",
                "is_association_wide": 1,
            }
        )
        team.append(
            "team_members",
            {"volunteer": volunteer.name, "team_role": "Team Member", "from_date": today(), "status": "Active"},
        )
        team.insert()
        self.track_doc("Team", team.name)
        sync_user_role_profile(user.name)
        return frappe.get_doc("User", user.name)

    def test_payment_failure_recovery_workflow(self):
        """Test the complete payment failure and recovery workflow"""

        stages = [
            {
                "name": "Stage 1: Create Member with SEPA Mandate",
                "function": self._stage_1_create_member_sepa,
                "validations": [self._validate_member_sepa_created]},
            {
                "name": "Stage 2: Invoice Left Unpaid",
                "function": self._stage_2_unpaid_invoice,
                "validations": [self._validate_payment_failed]},
            {
                "name": "Stage 3: Schedule Payment Retry",
                "function": self._stage_3_schedule_retry,
                "validations": [self._validate_retry_scheduled]},
            {
                "name": "Stage 4: Retries Exhausted - Escalation",
                "function": self._stage_4_escalate,
                "validations": [self._validate_escalated]},
            {
                "name": "Stage 5: Multiple Failures - Suspension",
                "function": self._stage_5_multiple_failures_suspension,
                "validations": [self._validate_member_suspended]},
            {
                "name": "Stage 6: Payment Recovery - Reactivation",
                "function": self._stage_6_payment_recovery,
                "validations": [self._validate_member_reactivated]},
        ]

        self.define_workflow(stages)

        with self.workflow_transaction():
            self.execute_workflow()

        # Final validations
        self._validate_complete_payment_recovery()

    # Stage 1: Create Member with SEPA Mandate
    def _stage_1_create_member_sepa(self, context):
        """Stage 1: Create a member with SEPA mandate

        Note: Uses ignore_permissions for test data setup (standard Frappe test pattern).
        The actual workflow operations in later stages use proper user context.
        """
        from frappe.utils import random_string

        unique_id = random_string(6).lower()

        # Create member with IBAN and account holder required for SEPA
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "PaymentTest",
                "last_name": f"Member-{unique_id}",
                "email": f"payment.test.{unique_id}@example.com",
                "contact_number": "+31698765432",
                "payment_method": "SEPA Direct Debit",
                "iban": "NL91ABNA0417164300",
                "bank_account_name": f"PaymentTest Member-{unique_id}",
                "status": "Active"}
        )
        member.insert(ignore_permissions=True)

        # Add to chapter membership history
        member.append(
            "chapter_membership_history",
            {
                "chapter_name": self.test_chapter.name,
                "start_date": today(),
                "assignment_type": "Member",
                "status": "Active"},
        )
        member.save(ignore_permissions=True)
        self.track_doc("Member", member.name)

        # Create SEPA mandate with unique reference
        sepa_mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": member.name,
                "iban": "NL91ABNA0417164300",
                "bic": "ABNANL2A",
                "account_holder_name": f"{member.first_name} {member.last_name}",
                "mandate_date": today(),
                "sign_date": today(),
                "mandate_reference": f"MANDATE-{unique_id}",
                "status": "Active",
                "mandate_type": "RCUR"}
        )
        sepa_mandate.insert(ignore_permissions=True)
        self.track_doc("SEPA Mandate", sepa_mandate.name)

        # Create customer in ERPNext with unique name
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"PaymentTest Member-{unique_id}",
                "customer_type": "Individual",
                "customer_group": resolve_non_group_customer_group(),
                "territory": "Netherlands"}
        )
        customer.insert(ignore_permissions=True)
        self.track_doc("Customer", customer.name)

        # Link customer to member - reload to avoid timestamp mismatch
        member.reload()
        member.customer = customer.name
        member.save(ignore_permissions=True)

        # Create membership
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": self.membership_type.name,
                "start_date": today(),
                "end_date": add_months(today(), 12),
                "status": "Active"}
        )
        membership.insert(ignore_permissions=True)
        # An Active membership is a submitted one: a draft is status "Draft" whatever is passed in,
        # and PaymentRetryManager only links an Active membership.
        membership.submit()

        # Record state
        self.state_manager.record_state("Member", member.name, "Created with SEPA")
        self.state_manager.record_state("SEPA Mandate", sepa_mandate.name, "Active")

        return {
            "member_name": member.name,
            "sepa_mandate_name": sepa_mandate.name,
            "customer_name": customer.name,
            "membership_name": membership.name}

    def _validate_member_sepa_created(self, context):
        """Validate member and SEPA mandate were created"""
        member_name = context.get("member_name")
        sepa_mandate_name = context.get("sepa_mandate_name")

        # Check member exists
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.payment_method, "SEPA Direct Debit")
        self.assertEqual(member.status, "Active")

        # Check SEPA mandate exists
        sepa_mandate = frappe.get_doc("SEPA Mandate", sepa_mandate_name)
        self.assertEqual(sepa_mandate.status, "Active")
        self.assertEqual(sepa_mandate.member, member_name)

    def _make_invoice(self, customer_name):
        """Submit a EUR-safe membership invoice for the customer (ERPNext scaffolding)"""
        infra = self.erpnext_infra

        with self.as_user(self.admin_user.name):
            invoice = frappe.get_doc(
                {
                    "doctype": "Sales Invoice",
                    "customer": customer_name,
                    "company": infra["company"],
                    "currency": frappe.db.get_value("Company", infra["company"], "default_currency"),
                    "selling_price_list": None,
                    "posting_date": today(),
                    "due_date": add_days(today(), 30),
                    "payment_terms_template": None,
                    "items": [
                        {
                            "item_code": infra["membership_item"],
                            "description": "Annual Membership Fee",
                            "qty": 1,
                            "rate": 100.00,
                            "amount": 100.00,
                            "cost_center": infra["cost_center"],
                            "income_account": infra["income_account"]}
                    ]}
            )
            invoice.insert()
            invoice.submit()
        self.track_doc("Sales Invoice", invoice.name)
        return invoice

    # Stage 2: Invoice left unpaid
    def _stage_2_unpaid_invoice(self, context):
        """Stage 2: A membership invoice that nobody has paid (the collection failed).

        Only the ERPNext scaffolding runs here; the app behaviour under test starts at Stage 3.
        """
        invoice = self._make_invoice(context.get("customer_name"))

        self.state_manager.record_state("Payment", invoice.name, "Failed")
        return {"invoice_name": invoice.name}

    def _validate_payment_failed(self, context):
        """The invoice is submitted and still outstanding"""
        invoice = frappe.get_doc("Sales Invoice", context.get("invoice_name"))
        self.assertEqual(invoice.docstatus, 1)
        self.assertEqual(invoice.outstanding_amount, 100.00)
        self.assertIn(invoice.status, ["Unpaid", "Overdue"], "Invoice should still be outstanding")

    # Stage 3: Schedule the payment retry
    def _stage_3_schedule_retry(self, context):
        """Stage 3: The member asks for a retry through the real whitelisted endpoint"""
        from verenigingen.api.payment_dashboard import retry_failed_payment

        invoice_name = context.get("invoice_name")

        with self.as_user(self.admin_user.name):
            first = retry_failed_payment(invoice_name)
            # A second request while the first is Scheduled must be refused, not queue a duplicate.
            second = retry_failed_payment(invoice_name)
            # A different invoice of the same member is a separate retry: the duplicate guard is
            # per invoice, not per member.
            other_invoice = self._make_invoice(context.get("customer_name"))
            other = retry_failed_payment(other_invoice.name)

        return {"first_retry": first, "second_retry": second, "other_retry": other, "other_invoice_name": other_invoice.name}

    def _validate_retry_scheduled(self, context):
        """The first call scheduled a retry record; the second was refused"""
        first = context.get("first_retry")
        second = context.get("second_retry")
        # The @critical_api wrapper serialises OperationResult to a dict.
        self.assertTrue(first["success"], f"retry_failed_payment refused: {first}")
        self.assertFalse(second["success"], "A second retry request must be refused while one is Scheduled")
        self.assertIn("already scheduled", second["error"]["message"])
        self.assertTrue(
            context.get("other_retry")["success"],
            f"A second invoice of the same member must still be retryable: {context.get('other_retry')}",
        )

        retry = self._get_retry_record(context)
        self.assertEqual(retry.status, "Scheduled")
        self.assertEqual(retry.retry_count, 1)
        self.assertEqual(retry.member, context.get("member_name"))
        self.assertEqual(retry.membership, context.get("membership_name"))
        self.assertGreater(getdate(retry.next_retry_date), getdate(today()))
        self.assertEqual(len(retry.retry_log), 1)

    def _get_retry_record(self, context):
        retry_name = frappe.db.get_value("SEPA Payment Retry", {"invoice": context.get("invoice_name")})
        self.assertTrue(retry_name, "retry_failed_payment should have created a SEPA Payment Retry")
        return frappe.get_doc("SEPA Payment Retry", retry_name)

    # Stage 4: Retries exhausted
    def _stage_4_escalate(self, context):
        """Stage 4: Retries run out through real schedule_retry calls, then the next one escalates.

        Stage 3 made attempt 1 through the API; the loop makes the remaining max_retries - 1 real
        attempts, then one more call hits the limit.
        """
        from verenigingen.verenigingen_payments.utils.payment_retry import PaymentRetryManager

        invoice_name = context.get("invoice_name")
        manager = PaymentRetryManager()
        max_retries = manager.retry_config["max_retries"]

        with self.as_user(self.admin_user.name):
            attempts = [
                manager.schedule_retry(invoice_name, "AM04", f"Insufficient funds {n}")
                for n in range(2, max_retries + 1)
            ]
            result = manager.schedule_retry(invoice_name, "AM04", "Insufficient funds")

        self.state_manager.record_state("Payment", invoice_name, "Retry Failed")
        return {"retry_attempts": attempts, "escalation_result": result, "max_retries": max_retries}

    def _validate_escalated(self, context):
        """The manager refuses further retries, marks the record Escalated, notes the membership
        and queues the escalation mail"""
        max_retries = context.get("max_retries")
        attempts = context.get("retry_attempts")
        self.assertEqual(len(attempts), max_retries - 1)
        for number, attempt in enumerate(attempts, start=2):
            self.assertTrue(attempt["scheduled"], f"attempt {number} should have been scheduled")
            self.assertEqual(attempt["attempt_number"], number)

        result = context.get("escalation_result")
        self.assertFalse(result["scheduled"])
        self.assertIn("escalated", result["message"].lower())

        retry = self._get_retry_record(context)
        self.assertEqual(retry.status, "Escalated")
        self.assertEqual(retry.retry_count, max_retries)
        self.assertEqual(len(retry.retry_log), max_retries)
        self.assertTrue(retry.escalated_on)

        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Membership", "reference_name": context.get("membership_name")},
            pluck="content",
        )
        self.assertTrue(
            any("Escalated for manual review" in c for c in comments),
            f"Membership should carry the escalation comment, got {comments}",
        )

        queued = frappe.get_all(
            "Email Queue",
            filters={"reference_doctype": "Member", "reference_name": context.get("member_name")},
            pluck="name",
        )
        self.assertTrue(queued, "The escalation mail to staff should be queued")

        invoice = frappe.get_doc("Sales Invoice", context.get("invoice_name"))
        self.assertIn(invoice.status, ["Overdue", "Unpaid"])

    # Stage 5: Suspension
    def _stage_5_multiple_failures_suspension(self, context):
        """Stage 5: Suspend the member through the real termination-integration service.

        Hand-sequenced: nothing in production suspends a member when a retry escalates. This
        stage checks the suspend service itself, in the order a staff member would run it.
        """
        from verenigingen.services.termination.termination_integration import suspend_member_safe

        member_name = context.get("member_name")

        with self.as_user(self.admin_user.name):
            result = suspend_member_safe(
                member_name, "Multiple payment failures", suspend_user=False, suspend_teams=False
            )

        self.state_manager.record_state("Member", member_name, "Suspended")
        return {"suspension_result": result}

    def _validate_member_suspended(self, context):
        """The service reports success and the Member row really changed"""
        result = context.get("suspension_result")
        self.assertTrue(result["success"], f"suspend_member_safe failed: {result}")
        self.assertTrue(result["member_suspended"])

        member = frappe.get_doc("Member", context.get("member_name"))
        self.assertEqual(member.status, "Suspended")
        self.assertIn("Reason: Multiple payment failures", member.notes)
        self.assertIn("(Pre-suspension status: Active)", member.notes)

    # Stage 6: Recovery
    def _stage_6_payment_recovery(self, context):
        """Stage 6: The invoice is paid with a real Payment Entry, then the member is reactivated.

        Hand-sequenced: nothing in production reactivates a member (or closes the retry record)
        when the invoice is paid. This checks the unsuspend service and the invoice settlement.
        """
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        from verenigingen.services.termination.termination_integration import unsuspend_member_safe

        member_name = context.get("member_name")
        invoice_name = context.get("invoice_name")

        with self.as_user(self.admin_user.name):
            payment = get_payment_entry("Sales Invoice", invoice_name)
            payment.paid_to = self.erpnext_infra["cash_account"]
            payment.reference_no = f"RECOVERY-{invoice_name}"
            payment.reference_date = today()
            payment.insert()
            payment.submit()
            reactivation = unsuspend_member_safe(member_name, "Payment recovered", restore_teams=False)
        self.track_doc("Payment Entry", payment.name)

        self.state_manager.record_state("Payment", invoice_name, "Recovered")
        self.state_manager.record_state("Member", member_name, "Reactivated")
        return {"recovery_payment": payment.name, "reactivation_result": reactivation}

    def _validate_member_reactivated(self, context):
        """The invoice is Paid and the member is back to its pre-suspension status"""
        invoice = frappe.get_doc("Sales Invoice", context.get("invoice_name"))
        self.assertEqual(invoice.status, "Paid")
        self.assertEqual(invoice.outstanding_amount, 0)

        reactivation = context.get("reactivation_result")
        self.assertTrue(reactivation["success"], f"unsuspend_member_safe failed: {reactivation}")
        self.assertTrue(reactivation["member_unsuspended"])

        member = frappe.get_doc("Member", context.get("member_name"))
        self.assertEqual(member.status, "Active")
        self.assertIn("Reason: Payment recovered", member.notes)

    def _validate_complete_payment_recovery(self):
        """The recorded states form the failure -> suspension -> recovery sequence, and the
        database agrees with them (the recorder alone would only prove the test ran)"""
        context = self.get_workflow_context()
        member_name = context.get("member_name")
        invoice_name = context.get("invoice_name")

        member_states = [
            t["to_state"] for t in self.state_manager.get_transitions("Member", member_name)
        ]
        self.assertEqual(member_states, ["Suspended", "Reactivated"])

        payment_states = [
            t["to_state"] for t in self.state_manager.get_transitions("Payment", invoice_name)
        ]
        self.assertEqual(payment_states, ["Retry Failed", "Recovered"])

        self.assertEqual(frappe.db.get_value("Member", member_name, "status"), "Active")
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice_name, "status"), "Paid")
        # Characterisation of CURRENT behaviour, not a requirement: paying the invoice does not
        # close the retry record. Drop this line if a payment hook ever starts to.
        self.assertEqual(
            frappe.db.get_value("SEPA Payment Retry", {"invoice": invoice_name}, "status"), "Escalated"
        )
