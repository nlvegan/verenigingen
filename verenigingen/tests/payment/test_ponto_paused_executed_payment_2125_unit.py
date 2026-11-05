"""
#2125 / #1288 / #1848: Ponto reports a payment EXECUTED for a request whose Ponto account
mapping is Paused (or staff-disabled). The Payment Entry would book against a shared or
wrong-currency GL, so it is refused. The money has moved, so staff must get ONE loud,
specific alert naming the row and the amount, and the request must not be marked Executed
or Paid.

Driven through the real paths: refresh_status (UI button), the hourly poll's
``_refresh_one``, ``update_status_from_webhook`` and the webhook entrypoint
``handle_payment_request_closed``. Only the Ponto HTTP boundary is stubbed
(``get_payment_client``). Named ``*_unit.py`` for that boundary stub.
"""

import json
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.ponto_test_data_factory import PaymentStatus, PontoTestDataFactory
from verenigingen.tests.payment.test_ponto_payment_request_paid_after_pe import (
    PAY_CLIENT_PATH,
    _mock_ponto_get_payment_client,
    _PontoPaymentRequestFixtures,
)
from verenigingen.verenigingen_payments.ponto.services.configuration_service import (
    PontoConfigurationService,
)

MARKER = "PONTO-EXECUTED-UNBOOKABLE"


class TestExecutedPaymentOnPausedAccount(_PontoPaymentRequestFixtures, EnhancedTestCase):
    AMOUNT = 123.45

    def tearDown(self):
        PontoConfigurationService.clear_cache()
        super().tearDown()

    def _paused_request(self, hint, disabled_only=False):
        req = self._create_ponto_request(self._create_supplier(hint), status="Signed", amount=self.AMOUNT)
        if disabled_only:
            frappe.db.set_value(
                "Ponto Bank Account Mapping",
                {"parent": "Ponto Settings", "ponto_account_id": self.TEST_PONTO_ACCOUNT_ID},
                "enabled",
                0,
            )
            PontoConfigurationService.clear_cache()
        else:
            PontoConfigurationService.pause_mapping(self.TEST_PONTO_ACCOUNT_ID, "shared bank account X")
        return req

    def _alerts(self, req):
        return frappe.get_all(
            "Notification Log",
            filters={"document_type": req.doctype, "document_name": req.name, "subject": ["like", f"{MARKER}%"]},
            fields=["subject", "email_content", "for_user"],
        )

    def _assert_unbooked_and_alerted(self, req):
        row = frappe.db.get_value(
            "Ponto Payment Request", req.name, ["status", "payment_entry"], as_dict=True
        )
        self.assertEqual(row.status, "Signed", "must not be marked Executed (or Paid)")
        self.assertFalse(row.payment_entry)
        self.assertFalse(frappe.db.exists("Payment Entry", {"reference_no": req.name}))
        alerts = self._alerts(req)
        # one Notification Log per recipient, none duplicated: a single alert, not one per attempt
        self.assertTrue(alerts)
        self.assertEqual(len({a.for_user for a in alerts}), len(alerts), alerts)
        text = alerts[0].subject + (alerts[0].email_content or "")
        self.assertIn(req.name, text)
        self.assertIn("123.45", text)
        self.assertIn("shared bank account X", text)

    def test_refresh_status_alerts_once_and_leaves_the_row_signed(self):
        req = self._paused_request("RefreshPaused")
        self.expectErrorLog(MARKER, "Ponto payment executed but cannot be booked")
        counts = []
        for _ in range(2):  # a repeat (hourly poll) must not alert again
            with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
                req.reload()
                result = req.refresh_status()
            self.assertEqual(result["status"], "Signed")
            counts.append(len(self._alerts(req)))
        self.assertGreater(counts[0], 0)
        self.assertEqual(counts[0], counts[1], "the repeat must not send a second alert")
        self._assert_unbooked_and_alerted(req)

    def test_poll_path_alerts_and_leaves_the_row_signed(self):
        from verenigingen.verenigingen_payments.ponto.services.status_poll_service import _refresh_one

        req = self._paused_request("PollPaused")
        self.expectErrorLog(MARKER, "Ponto payment executed but cannot be booked")
        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            outcome = _refresh_one("Ponto Payment Request", req.name)
        self.assertEqual(outcome, "ok")
        self._assert_unbooked_and_alerted(req)

    def test_webhook_entrypoint_alerts_and_leaves_the_row_signed(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            handle_payment_request_closed,
        )

        req = self._paused_request("WebhookPaused")
        self.expectErrorLog(MARKER, "Ponto payment executed but cannot be booked")
        payload = json.loads(
            PontoTestDataFactory.create_payment_request_closed_webhook(
                payment_id=req.ponto_payment_id, status=PaymentStatus.EXECUTED
            )
        )
        result = handle_payment_request_closed(payload)
        self.assertNotIn(req.name, result.get("updated_requests") or [])
        self.assertFalse(result.get("failed_requests"))
        self._assert_unbooked_and_alerted(req)

    def test_staff_disabled_mapping_is_refused_the_same_way(self):
        req = self._paused_request("DisabledOnly", disabled_only=True)
        self.expectErrorLog(MARKER, "Ponto payment executed but cannot be booked")
        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            req.refresh_status()
        row = frappe.db.get_value("Ponto Payment Request", req.name, ["status", "payment_entry"], as_dict=True)
        self.assertEqual((row.status, row.payment_entry), ("Signed", None))
        self.assertTrue(self._alerts(req))

    def test_usable_mapping_still_books_and_sends_no_alert(self):
        """Control: an enabled, OK mapping takes the normal path (no alert)."""
        req = self._create_ponto_request(
            self._create_supplier("Usable"), status="Signed", amount=self.AMOUNT, track_priority=6
        )
        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            req.refresh_status()
        self.assertEqual(self._alerts(req), [])
        self.assertEqual(frappe.db.get_value("Ponto Payment Request", req.name, "status"), "Executed")
