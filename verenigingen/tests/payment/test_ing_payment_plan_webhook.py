# Copyright (c) 2026, Verenigingen
"""Pay.nl webhook -> payment-plan installment finalization."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase

WEBHOOK_MODULE = "verenigingen.verenigingen_payments.ing_checkout.api.webhook"
FINALIZER_PATH = (
    "verenigingen.verenigingen_payments.services.payment_plan_finalization."
    "finalize_payment_plan_installment"
)


def _order_payload(order_id, intent_name, status_code=100):
    return {
        "id": order_id,
        "object": {
            "reference": f"PPP:{intent_name}",
            "status": {"code": status_code, "action": "PAID" if status_code == 100 else "OTHER"},
            "amount": {"value": 4000, "currency": "EUR"},
        },
    }


class TestINGPaymentPlanWebhook(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        # authenticate_webhook() calls frappe.set_user() for the rest of the
        # request; save/restore so it doesn't leak into other tests or disturb
        # track_doc cleanup (which runs as the original test session user).
        self._orig_session_user = frappe.session.user
        self.member = self._create_member()
        self.plan = self._create_plan(self.member.name)

    def tearDown(self):
        frappe.set_user(self._orig_session_user)
        super().tearDown()

    def _create_member(self):
        m = frappe.new_doc("Member")
        m.first_name = "IngHook"
        m.last_name = "Member"
        m.email = f"inghook-{frappe.generate_hash(length=6)}@example.com"
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

    def _install_request(self, body: bytes):
        """Install a request-like object so handle_payment() can be driven
        end-to-end, mirroring the scaffolding in
        ing_checkout/tests/test_webhook_endpoints.py.
        """
        self._orig_request = getattr(frappe.local, "request", None)
        frappe.local.response = frappe._dict({})
        frappe.local.request_ip = "203.0.113.9"
        frappe.local.form_dict = frappe._dict({})
        frappe.local.request = SimpleNamespace(
            method="POST",
            path="/api/method/ing_checkout_webhook",
            get_data=lambda: body,
            data=body,
            headers=SimpleNamespace(get=lambda key, default=None: default),
        )
        self.addCleanup(self._restore_request)

    def _restore_request(self):
        frappe.local.request = self._orig_request

    def _handle_payment_for_reference(self, order_id, intent_name, status_code=100):
        """Drive the full handle_payment() entry point for a PPP: reference,
        with only the true external boundaries (rate limiter, signature
        verification) stubbed out. is_duplicate_webhook and log_webhook run
        for real so the dedup-log assertion reflects production behavior.
        """
        self._install_request(json.dumps(_order_payload(order_id, intent_name, status_code)).encode("utf-8"))

        limiter = MagicMock()
        limiter.check_rate_limit.return_value = (True, None)

        from verenigingen.verenigingen_payments.ing_checkout.api import webhook as wh

        with (
            patch(f"{WEBHOOK_MODULE}.get_webhook_rate_limiter", return_value=limiter),
            patch(f"{WEBHOOK_MODULE}.verify_ing_checkout_webhook", return_value=True),
        ):
            return wh.handle_payment()

    def _create_transaction(self, transaction_id, status="Paid", amount=40.0):
        txn = frappe.get_doc(
            {
                "doctype": "ING Checkout Transaction",
                "transaction_id": transaction_id,
                "status": status,
                "amount": amount,
                "currency": "EUR",
            }
        ).insert(ignore_permissions=True)
        self.track_doc("ING Checkout Transaction", txn.name)
        return txn

    def _create_intent(self, payment_id="EX-hook"):
        intent = frappe.get_doc(
            {
                "doctype": "Payment Plan Payment",
                "payment_plan": self.plan.name,
                "installment_number": 1,
                "amount": 40.0,
                "currency": "EUR",
                "member": self.member.name,
                "gateway": "Pay.nl",
                "status": "Pending",
                "payment_id": payment_id,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Payment Plan Payment", intent.name)
        return intent

    def test_paid_webhook_finalizes_installment(self):
        from verenigingen.verenigingen_payments.ing_checkout.api.webhook import (
            _maybe_finalize_payment_plan,
        )

        intent = self._create_intent(payment_id="EX-paid")
        handled = _maybe_finalize_payment_plan("EX-paid", _order_payload("EX-paid", intent.name, 100))
        self.assertTrue(handled)  # dispatch consumed the webhook
        intent.reload()
        self.assertEqual(intent.status, "Paid")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Paid")

    def test_non_plan_reference_not_handled(self):
        from verenigingen.verenigingen_payments.ing_checkout.api.webhook import (
            _maybe_finalize_payment_plan,
        )

        payload = {
            "id": "EX-si",
            "object": {
                "reference": "SINV:ACC-SINV-2025-00001",
                "status": {"code": 100},
                "amount": {"value": 100, "currency": "EUR"},
            },
        }
        self.assertFalse(_maybe_finalize_payment_plan("EX-si", payload))

    def test_failed_webhook_leaves_installment_payable(self):
        from verenigingen.verenigingen_payments.ing_checkout.api.webhook import (
            _maybe_finalize_payment_plan,
        )

        intent = self._create_intent(payment_id="EX-fail")
        handled = _maybe_finalize_payment_plan("EX-fail", _order_payload("EX-fail", intent.name, -63))
        self.assertTrue(handled)
        intent.reload()
        self.assertEqual(intent.status, "Failed")
        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Pending")

    def test_handle_payment_finalizer_error_returns_500_with_no_dedup_log(self):
        """Regression (A3 phase 2 review): the literal mechanism preventing a
        dedup row on finalizer error lives in handle_payment()'s own control
        flow (webhook.py:85-89), not in _maybe_finalize_payment_plan alone.
        Drive the full entry point -- not the helper directly -- so this test
        actually exercises that branch.
        """
        intent = self._create_intent(payment_id="EX-hook-err")
        order_id = "ING-ERR-1"

        before = frappe.get_all("Webhook Processing Log", filters={"webhook_id": order_id}, pluck="name")
        self.assertEqual(before, [])
        before_total = frappe.db.count("Webhook Processing Log")

        with patch(FINALIZER_PATH, return_value={"status": "error", "message": "boom"}):
            result = self._handle_payment_for_reference(order_id, intent.name, status_code=100)

        self.assertEqual(frappe.local.response.get("http_status_code"), 500)
        self.assertEqual(result.get("status"), "error")

        # No Webhook Processing Log row was written for this event -- an
        # error dedup row would make Pay.nl's identical retry short-circuit
        # to a 200 "duplicate" and the finalizer would never re-run.
        after = frappe.get_all("Webhook Processing Log", filters={"webhook_id": order_id}, pluck="name")
        self.assertEqual(after, [])
        self.assertEqual(frappe.db.count("Webhook Processing Log"), before_total)

        # The intent/plan were left untouched by the mocked-error finalizer.
        intent.reload()
        self.assertEqual(intent.status, "Pending")

    def test_duplicate_paid_delivery_does_not_downgrade_transaction(self):
        """Regression (A3 phase 2 final review): a duplicate delivery of an
        already-finalized paid installment must not flip the ING Checkout
        Transaction back to "Pending". The finalizer's idempotency guard
        returns {"status": "skipped"} for an intent that is already "Paid",
        and _maybe_finalize_payment_plan must leave a Paid transaction's
        status untouched on any non-success result.
        """
        from verenigingen.verenigingen_payments.ing_checkout.api.webhook import (
            _maybe_finalize_payment_plan,
        )

        order_id = "EX-dup-paid"
        # Intent is already finalized (status Paid) - triggers the finalizer's
        # own idempotency guard, which returns {"status": "skipped", ...}.
        intent = self._create_intent(payment_id=order_id)
        frappe.db.set_value("Payment Plan Payment", intent.name, "status", "Paid")

        txn = self._create_transaction(order_id, status="Paid")

        handled = _maybe_finalize_payment_plan(order_id, _order_payload(order_id, intent.name, 100))
        self.assertTrue(handled)

        txn.reload()
        self.assertEqual(txn.status, "Paid")

    def test_handle_payment_finalizer_success_returns_200(self):
        """Companion positive case: a successful finalize via the full
        handle_payment() entry point does NOT set a 500 status.
        """
        intent = self._create_intent(payment_id="EX-hook-ok")
        order_id = "ING-OK-1"

        with patch(
            FINALIZER_PATH,
            return_value={"status": "success", "message": "ok"},
        ):
            result = self._handle_payment_for_reference(order_id, intent.name, status_code=100)

        self.assertNotEqual(frappe.local.response.get("http_status_code"), 500)
        self.assertEqual(result.get("status"), "success")
