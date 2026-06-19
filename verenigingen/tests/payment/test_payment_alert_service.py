"""
Real-integration tests for
verenigingen/verenigingen_payments/utils/payment_alert_service.py
(previously 0% covered).

``PaymentAlertService`` is the centralised alerting service for payment
integrations (ING Checkout, Mollie, Ponto). It is live: ``ing_checkout``'s
transaction_service imports ``get_payment_alert_service`` (through the
deprecation shim ``verenigingen/utils/payment_alert_service.py``). Each alert
method produces concrete side effects that this suite asserts on REAL records:

  * ``send_overpayment_alert`` writes a "Overpayment detected" Error Log, may
    add a real Comment to a transaction document, and dispatches an alert email.
  * ``send_payment_entry_failure_alert`` / ``send_reconciliation_alert`` dispatch
    alert emails.
  * ``_send_email_alert`` is gated on the ``accounts_managers_email`` hook. When
    NO recipients are configured (the state on this site) it writes a
    "No Alert Recipients Configured" Error Log and returns False; when recipients
    ARE configured it calls the email service and returns its success flag.

Infra boundaries that ARE mocked (each with an inline justification):
  * the OUTBOUND email transport — ``get_email_service().send_simple_email`` — is
    replaced by a fake returning a REAL ``OperationResult`` so we exercise the
    real success/failure plumbing without sending mail. Business logic (amounts,
    branch selection, Error Log / Comment writes) is NOT mocked.

Recipients seam: the hook is empty on this site, so to drive the
"recipients configured" branch the test sets the documented
``svc._recipients_cache`` (the per-instance cache the production ``property``
reads) rather than mutating global hooks / Single doctypes.

Base class: VereningingenTestCase (FrappeTestCase-derived, auto-rollback,
runs as Administrator).
"""

import unittest
from unittest.mock import patch

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.operation_result import OperationResult
from verenigingen.verenigingen_payments.utils.payment_alert_service import (
    PaymentAlertService,
    get_payment_alert_service,
)


class _FakeEmailService:
    """Stand-in for the outbound email transport. Records the last call and
    returns a REAL OperationResult so the production success/failure branch is
    exercised. Mock justified: send_simple_email is the outbound email boundary."""

    def __init__(self, success=True):
        self._success = success
        self.calls = []

    def send_simple_email(self, recipients, subject, message, notification_key=None, **kw):
        self.calls.append(
            {
                "recipients": recipients,
                "subject": subject,
                "message": message,
                "notification_key": notification_key,
            }
        )
        if self._success:
            return OperationResult.ok({"sent": True})
        return OperationResult.fail("smtp down")


class PaymentAlertBase(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.svc = PaymentAlertService()

    # ---- helpers -----------------------------------------------------------

    def _with_recipients(self, recipients=("accounts@example.org",)):
        """Drive the 'recipients configured' branch via the documented cache."""
        self.svc._recipients_cache = list(recipients)

    def _error_logs_with(self, needle):
        return frappe.get_all(
            "Error Log",
            filters={"error": ["like", f"%{needle}%"]},
            fields=["name", "error"],
        )

    def _patch_email(self, success=True):
        """Patch the outbound email transport. Mock justified: outbound email."""
        fake = _FakeEmailService(success=success)
        patcher = patch(
            "verenigingen.services.communication.email_service.get_email_service",
            return_value=fake,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake


# =============================================================================
# Factory
# =============================================================================
class TestFactory(PaymentAlertBase):
    def test_factory_returns_service_instance(self):
        svc = get_payment_alert_service()
        self.assertIsInstance(svc, PaymentAlertService)

    def test_recipients_property_reads_hook_and_caches(self):
        # On this site the accounts_managers_email hook is unset -> [].
        fresh = PaymentAlertService()
        self.assertEqual(fresh.alert_recipients, frappe.get_hooks("accounts_managers_email") or [])
        # Second read is served from the per-instance cache.
        fresh._recipients_cache = ["sentinel@example.org"]
        self.assertEqual(fresh.alert_recipients, ["sentinel@example.org"])


# =============================================================================
# _send_email_alert — recipient gating (the live branch on this site)
# =============================================================================
class TestSendEmailAlertGating(PaymentAlertBase):
    def test_no_recipients_logs_error_and_returns_false(self):
        # No recipients configured -> production logs a dedicated Error Log and
        # returns False WITHOUT touching the email service.
        ctx = f"CTX-{frappe.generate_hash(length=8)}"
        with patch(
            "verenigingen.services.communication.email_service.get_email_service"
        ) as get_es:
            result = self.svc._send_email_alert(
                subject="s", message="m", alert_type="reconciliation", context_id=ctx
            )
            get_es.assert_not_called()
        self.assertFalse(result)
        logs = self._error_logs_with("accounts_managers_email hook not configured")
        self.assertTrue(any(ctx in log["error"] for log in logs))

    def test_recipients_configured_calls_email_and_returns_success(self):
        self._with_recipients(["a@example.org", "b@example.org"])
        fake = self._patch_email(success=True)
        ctx = f"CTX-{frappe.generate_hash(length=8)}"
        result = self.svc._send_email_alert(
            subject="Subj", message="Body", alert_type="overpayment", context_id=ctx
        )
        self.assertTrue(result)
        self.assertEqual(len(fake.calls), 1)
        call = fake.calls[0]
        self.assertEqual(call["recipients"], ["a@example.org", "b@example.org"])
        # alert_type maps to the correct notification_key.
        self.assertEqual(call["notification_key"], "payment_alert_overpayment")

    def test_email_failure_returns_false(self):
        self._with_recipients()
        self._patch_email(success=False)
        result = self.svc._send_email_alert(
            subject="s", message="m", alert_type="payment_entry_failure", context_id="X"
        )
        self.assertFalse(result)

    def test_unknown_alert_type_maps_to_failure_key(self):
        self._with_recipients()
        fake = self._patch_email(success=True)
        self.svc._send_email_alert(
            subject="s", message="m", alert_type="totally_unknown", context_id="X"
        )
        self.assertEqual(fake.calls[0]["notification_key"], "payment_alert_failure")

    def test_email_exception_is_swallowed_returns_false(self):
        self._with_recipients()
        # Email transport raises -> production catches, warns, returns False.
        # Mock justified: outbound email transport.
        boom = patch(
            "verenigingen.services.communication.email_service.get_email_service",
            side_effect=RuntimeError("smtp exploded"),
        )
        boom.start()
        self.addCleanup(boom.stop)
        result = self.svc._send_email_alert(
            subject="s", message="m", alert_type="reconciliation", context_id="X"
        )
        self.assertFalse(result)


# =============================================================================
# send_overpayment_alert
# =============================================================================
class TestOverpaymentAlert(PaymentAlertBase):
    def test_writes_overpayment_error_log(self):
        # Even with no recipients, the method always writes an "Overpayment
        # detected" Error Log capturing the computed overpayment.
        txn = f"TXN-{frappe.generate_hash(length=8)}"
        sent = self.svc.send_overpayment_alert(
            source="ING Checkout",
            transaction_id=txn,
            reference_name="SINV-OVP-1",
            amount_paid=150.0,
            amount_due=100.0,
        )
        # No recipients on this site -> email not sent.
        self.assertFalse(sent)
        logs = self._error_logs_with(f"Overpayment: {txn}")
        # Title contains the txn id; message carries the 50.00 overpayment.
        matching = [
            log
            for log in self._error_logs_with(txn)
            if "Overpayment: 50.00" in log["error"]
        ]
        self.assertTrue(matching, "overpayment Error Log with computed 50.00 must exist")

    def test_overpayment_email_dispatched_when_recipients_set(self):
        self._with_recipients()
        fake = self._patch_email(success=True)
        txn = f"TXN-{frappe.generate_hash(length=8)}"
        sent = self.svc.send_overpayment_alert(
            source="Mollie",
            transaction_id=txn,
            reference_name="SINV-OVP-2",
            amount_paid=120.0,
            amount_due=100.0,
        )
        self.assertTrue(sent)
        self.assertEqual(len(fake.calls), 1)
        call = fake.calls[0]
        self.assertIn("20.00", call["subject"])
        # Real formatted HTML body carries both amounts and the source.
        self.assertIn("Mollie", call["message"])
        self.assertIn("120.00", call["message"])
        self.assertIn("100.00", call["message"])
        self.assertEqual(call["notification_key"], "payment_alert_overpayment")

    def test_overpayment_adds_comment_to_transaction_doc(self):
        # When a transaction doctype/name is supplied, a real Comment is added to
        # that document. Use a real persisted ToDo (any doc supporting comments).
        todo = frappe.new_doc("ToDo")
        todo.description = "alert target"
        todo.insert()
        self.svc.send_overpayment_alert(
            source="ING Checkout",
            transaction_id="TXN-CMT",
            reference_name="SINV-CMT",
            amount_paid=130.0,
            amount_due=100.0,
            transaction_doctype="ToDo",
            transaction_name=todo.name,
        )
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "ToDo", "reference_name": todo.name},
            fields=["content"],
        )
        self.assertTrue(
            any("Overpayment of 30.00 detected" in (c["content"] or "") for c in comments),
            "an overpayment Comment must be added to the transaction document",
        )

    def test_overpayment_comment_bad_doc_is_swallowed(self):
        # Adding a comment to a nonexistent document must not raise (the alert
        # path still logs + attempts email).
        sent = self.svc.send_overpayment_alert(
            source="ING Checkout",
            transaction_id="TXN-BADDOC",
            reference_name="SINV",
            amount_paid=110.0,
            amount_due=100.0,
            transaction_doctype="ToDo",
            transaction_name="NON-EXISTENT-TODO-XYZ",
        )
        # No recipients -> returns False, but crucially did not raise.
        self.assertFalse(sent)


# =============================================================================
# send_payment_entry_failure_alert
# =============================================================================
class TestPaymentEntryFailureAlert(PaymentAlertBase):
    def test_no_recipients_returns_false(self):
        self.assertFalse(
            self.svc.send_payment_entry_failure_alert(
                source="Ponto",
                transaction_id="TXN-F1",
                reference_name="SINV-F1",
                amount=42.0,
                error_message="boom",
            )
        )

    def test_failure_email_body_contains_error_and_amount(self):
        self._with_recipients()
        fake = self._patch_email(success=True)
        sent = self.svc.send_payment_entry_failure_alert(
            source="Ponto",
            transaction_id="TXN-F2",
            reference_name=None,  # exercise the 'N/A' formatting branch
            amount=42.5,
            error_message="LinkValidationError: missing party",
        )
        self.assertTrue(sent)
        call = fake.calls[0]
        self.assertIn("URGENT", call["subject"])
        self.assertIn("TXN-F2", call["subject"])
        self.assertIn("LinkValidationError: missing party", call["message"])
        self.assertIn("42.50", call["message"])
        self.assertIn("N/A", call["message"])  # reference_name None -> 'N/A'
        self.assertEqual(call["notification_key"], "payment_alert_failure")


# =============================================================================
# send_reconciliation_alert
# =============================================================================
class TestReconciliationAlert(PaymentAlertBase):
    def test_no_recipients_returns_false(self):
        self.assertFalse(
            self.svc.send_reconciliation_alert(
                source="Mollie",
                transaction_id="TXN-R1",
                issue_type="amount_mismatch",
                details="paid 10, due 12",
            )
        )

    def test_reconciliation_email_body_and_key(self):
        self._with_recipients()
        fake = self._patch_email(success=True)
        sent = self.svc.send_reconciliation_alert(
            source="Mollie",
            transaction_id="TXN-R2",
            issue_type="amount_mismatch",
            details="paid 10, due 12",
        )
        self.assertTrue(sent)
        call = fake.calls[0]
        self.assertIn("amount_mismatch", call["subject"])
        self.assertIn("TXN-R2", call["subject"])
        self.assertIn("paid 10, due 12", call["message"])
        self.assertEqual(call["notification_key"], "payment_alert_reconciliation")


if __name__ == "__main__":
    unittest.main()
