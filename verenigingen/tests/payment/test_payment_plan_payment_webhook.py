# Copyright (c) 2026, Verenigingen
"""Webhook confirmation for payment-plan installment payments."""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


def _payment(payment_id, intent_name, status="paid"):
    """A minimal Mollie-payment-like dict as the router.fetch_payment would return."""
    return {
        "id": payment_id,
        "status": status,
        "metadata": {"reference_doctype": "Payment Plan Payment", "reference_docname": intent_name},
    }


class TestPaymentPlanPaymentWebhook(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._create_member()
        self.plan = self._create_plan(self.member.name)

    def _create_member(self):
        m = frappe.new_doc("Member")
        m.first_name = "Hook"
        m.last_name = "Member"
        m.email = f"hook-{frappe.generate_hash(length=6)}@example.com"
        m.member_since = today()
        m.save(ignore_permissions=True)
        self.track_doc("Member", m.name)
        return m

    def _create_plan(self, member_name):
        p = frappe.new_doc("Payment Plan")
        p.member = member_name
        p.plan_type = "Equal Installments"
        p.total_amount = 120.0
        p.number_of_installments = 3
        p.frequency = "Monthly"
        p.start_date = today()
        p.status = "Active"
        p.reason = "test"
        p.payment_method = "Bank Transfer"
        p.save(ignore_permissions=True)
        self.track_doc("Payment Plan", p.name)
        return p

    def _create_intent(self, installment_number=1, amount=40.0, payment_id="tr_hook1"):
        intent = frappe.get_doc(
            {
                "doctype": "Payment Plan Payment",
                "payment_plan": self.plan.name,
                "installment_number": installment_number,
                "amount": amount,
                "currency": "EUR",
                "member": self.member.name,
                "gateway": "Mollie",
                "status": "Pending",
                "payment_id": payment_id,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Payment Plan Payment", intent.name)
        return intent

    def test_paid_webhook_marks_installment_and_intent_paid(self):
        from verenigingen.verenigingen_payments.mollie.services.payment_plan_payment_handler import (
            handle_payment_plan_payment,
        )

        intent = self._create_intent()
        result = handle_payment_plan_payment("tr_hook1", _payment("tr_hook1", intent.name))
        self.assertEqual(result["status"], "success")

        intent.reload()
        self.assertEqual(intent.status, "Paid")
        self.assertEqual(intent.paid, 1)

        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Paid")
        self.assertEqual(plan.installments[0].payment_reference, "tr_hook1")

    def test_duplicate_paid_webhook_is_idempotent_noop(self):
        from verenigingen.verenigingen_payments.mollie.services.payment_plan_payment_handler import (
            handle_payment_plan_payment,
        )

        intent = self._create_intent()
        handle_payment_plan_payment("tr_hook1", _payment("tr_hook1", intent.name))
        # Second delivery must not raise and must not re-run process_payment.
        result = handle_payment_plan_payment("tr_hook1", _payment("tr_hook1", intent.name))
        self.assertEqual(result["status"], "skipped")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        # Still exactly one Paid installment (no double processing / no throw).
        self.assertEqual(plan.installments[0].status, "Paid")

    def test_second_intent_for_same_installment_is_skipped_not_double_processed(self):
        """Two intents for the SAME installment (member opened the pay page twice
        and both Mollie payments succeeded): the first finalizes normally, the
        second must be skipped (not throw "already paid" -> 500 -> Mollie retry
        loop), and the duplicate real charge is flagged via the intent's own
        status rather than silently dropped."""
        from verenigingen.verenigingen_payments.mollie.services.payment_plan_payment_handler import (
            handle_payment_plan_payment,
        )

        first_intent = self._create_intent(installment_number=1, payment_id="tr_hook_first")
        second_intent = self._create_intent(installment_number=1, payment_id="tr_hook_second")

        first_result = handle_payment_plan_payment(
            "tr_hook_first", _payment("tr_hook_first", first_intent.name)
        )
        self.assertEqual(first_result["status"], "success")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Paid")

        second_result = handle_payment_plan_payment(
            "tr_hook_second", _payment("tr_hook_second", second_intent.name)
        )
        self.assertEqual(second_result["status"], "skipped")

        # Installment is still Paid exactly once (no double processing / no throw).
        plan.reload()
        self.assertEqual(plan.installments[0].status, "Paid")

        # The second intent is marked Paid too, so it's not left dangling/re-tried,
        # while the log flags it for manual refund review.
        second_intent.reload()
        self.assertEqual(second_intent.status, "Paid")

    def test_failed_webhook_marks_intent_failed_installment_stays_payable(self):
        from verenigingen.verenigingen_payments.mollie.services.payment_plan_payment_handler import (
            handle_payment_plan_payment,
        )

        intent = self._create_intent()
        result = handle_payment_plan_payment("tr_hook1", _payment("tr_hook1", intent.name, status="failed"))
        self.assertEqual(result["status"], "skipped")
        intent.reload()
        self.assertEqual(intent.status, "Failed")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Pending")

    def test_dispatch_routes_plan_payment_before_donation_classification(self):
        from unittest.mock import Mock, patch

        from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
            get_unified_webhook_service,
        )

        intent = self._create_intent(payment_id="tr_dispatch")
        fake = _payment("tr_dispatch", intent.name)

        with patch(
            "verenigingen.verenigingen_payments.mollie.services.payment_type_router.get_payment_router"
        ) as get_router:
            router = Mock()
            router.fetch_payment.return_value = fake
            # If classification were reached it would raise, proving we dispatched first.
            router.classify_payment.side_effect = AssertionError("should not classify plan payments")
            get_router.return_value = router

            svc = get_unified_webhook_service()
            result = svc.process_payment_webhook("tr_dispatch", {})

        self.assertEqual(result["status"], "success")
        frappe.get_doc("Payment Plan Payment", intent.name).reload()
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Paid")
