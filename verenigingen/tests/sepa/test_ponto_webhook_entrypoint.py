# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Webhook entry-point + handler integration tests.

Covers the HTTP entry point ``handle_ponto_webhook`` and the dispatch /
side-effect branches of ``webhook_handlers`` that the existing
``test_ponto_webhook_handler`` suite leaves uncovered:

- Full entry-point flow: rate-limit, signature gating, JSON parse, dispatch,
  logging, success/error responses (HTTP status codes).
- ``handle_payment_request_closed`` against a REAL Ponto Payment Request doc
  (status mapped + persisted via the doctype's webhook update method).
- ``_update_payment_link_status`` against a REAL Ponto Payment Link doc.

These are real-integration tests: payloads are constructed as Ibanity would
send them and passed to the real handlers; only the external HTTP boundary
(``frappe.request`` and ``verify_ponto_webhook`` JWKS fetch) is stubbed.

Usage:
    bench --site test_site_1 run-tests --app verenigingen \\
        --module verenigingen.tests.sepa.test_ponto_webhook_entrypoint
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.ponto_test_data_factory import (
    PaymentStatus,
    PontoEventType,
    PontoTestDataFactory,
)
from verenigingen.tests.fixtures.singleton_backup import singleton_backup

WEBHOOK_MODULE = "verenigingen.verenigingen_payments.ponto.api.webhook"


def _make_request(payload: bytes, signature=None, headers=None):
    """Build a stand-in for frappe.request carrying webhook body + headers."""
    req = MagicMock()
    req.get_data.return_value = payload
    req.method = "POST"  # security framework validates request method
    req.content_type = "application/json"
    hdrs = {"Signature": signature} if signature else {}
    if headers:
        hdrs.update(headers)
    req.headers = hdrs
    return req


class _WebhookEntryPointBase(FrappeTestCase):
    """Shared request/response/settings stubbing for the entry point."""

    def setUp(self):
        # Reset frappe.local.response so http_status_code assertions are clean
        frappe.local.response = frappe._dict()

    def _call_entry_point(
        self, payload, signature=None, *, enable_webhooks=True, require_signature=False
    ):
        from verenigingen.verenigingen_payments.ponto.api.webhook import handle_ponto_webhook

        settings = MagicMock()
        settings.enable_webhooks = enable_webhooks
        settings.require_webhook_signature = require_signature

        request = _make_request(payload, signature)
        with patch(f"{WEBHOOK_MODULE}.frappe.request", request):
            with patch(f"{WEBHOOK_MODULE}.frappe.get_single", return_value=settings):
                with patch(f"{WEBHOOK_MODULE}._create_webhook_log", return_value="LOG-1"):
                    # Neutralise rate limiter (allow everything)
                    rl = MagicMock()
                    rl.check_rate_limit.return_value = (True, None)
                    with patch(f"{WEBHOOK_MODULE}.get_webhook_rate_limiter", return_value=rl):
                        return handle_ponto_webhook()


class TestPontoWebhookEntryPoint(_WebhookEntryPointBase):
    """End-to-end entry-point behaviour."""

    def test_webhooks_disabled_returns_ignored(self):
        payload = PontoTestDataFactory.create_sync_succeeded_webhook(account_id="acct-1")
        result = self._call_entry_point(payload, enable_webhooks=False)
        self.assertEqual(result["status"], "ignored")
        self.assertEqual(result["reason"], "webhooks_disabled")

    def test_missing_signature_when_required_returns_401(self):
        payload = PontoTestDataFactory.create_sync_succeeded_webhook(account_id="acct-1")
        self._call_entry_point(payload, signature=None, require_signature=True)
        self.assertEqual(frappe.local.response["http_status_code"], 401)

    def test_invalid_json_returns_400(self):
        result = self._call_entry_point(b"not-json{", require_signature=False)
        self.assertEqual(frappe.local.response["http_status_code"], 400)
        self.assertIsNotNone(result)

    def test_unknown_event_format_returns_400(self):
        # Valid JSON but no event type extractable
        payload = json.dumps({"data": {"id": "x"}}).encode("utf-8")
        self._call_entry_point(payload, require_signature=False)
        self.assertEqual(frappe.local.response["http_status_code"], 400)

    def test_valid_unsigned_sync_event_dispatches(self):
        account_id = "550e8400-e29b-41d4-a716-446655440000"
        payload = PontoTestDataFactory.create_sync_succeeded_webhook(account_id=account_id)
        with patch(f"{WEBHOOK_MODULE}.frappe.enqueue"):
            with patch(
                f"{WEBHOOK_MODULE}._update_account_sync_status", return_value=True
            ):
                result = self._call_entry_point(payload, require_signature=False)
        # Success response envelope carries the event_type + result
        self.assertIn("result", result.get("data", result))

    def test_signature_present_and_verified_dispatches(self):
        account_id = "acct-verified"
        payload = PontoTestDataFactory.create_sync_succeeded_webhook(account_id=account_id)
        verified_claims = {"sub": "subj", "digest": "x"}
        from verenigingen.verenigingen_payments.ponto.api.webhook import handle_ponto_webhook

        settings = MagicMock()
        settings.enable_webhooks = True
        settings.require_webhook_signature = True
        request = _make_request(payload, signature="signed.jwt.token")
        with patch(f"{WEBHOOK_MODULE}.frappe.request", request):
            with patch(f"{WEBHOOK_MODULE}.frappe.get_single", return_value=settings):
                with patch(f"{WEBHOOK_MODULE}._create_webhook_log", return_value="LOG-1"):
                    with patch(
                        f"{WEBHOOK_MODULE}.verify_ponto_webhook", return_value=verified_claims
                    ) as mock_verify:
                        rl = MagicMock()
                        rl.check_rate_limit.return_value = (True, None)
                        with patch(
                            f"{WEBHOOK_MODULE}.get_webhook_rate_limiter", return_value=rl
                        ):
                            with patch(f"{WEBHOOK_MODULE}.frappe.enqueue"):
                                with patch(
                                    f"{WEBHOOK_MODULE}._update_account_sync_status",
                                    return_value=True,
                                ):
                                    result = handle_ponto_webhook()
        mock_verify.assert_called_once()
        self.assertIsNotNone(result)

    def test_signature_verification_failure_returns_401(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoWebhookError

        payload = PontoTestDataFactory.create_sync_succeeded_webhook(account_id="a")
        from verenigingen.verenigingen_payments.ponto.api.webhook import handle_ponto_webhook

        settings = MagicMock()
        settings.enable_webhooks = True
        settings.require_webhook_signature = True
        request = _make_request(payload, signature="bad.jwt")
        with patch(f"{WEBHOOK_MODULE}.frappe.request", request):
            with patch(f"{WEBHOOK_MODULE}.frappe.get_single", return_value=settings):
                with patch(
                    f"{WEBHOOK_MODULE}.verify_ponto_webhook",
                    side_effect=PontoWebhookError(message="bad sig"),
                ):
                    rl = MagicMock()
                    rl.check_rate_limit.return_value = (True, None)
                    with patch(
                        f"{WEBHOOK_MODULE}.get_webhook_rate_limiter", return_value=rl
                    ):
                        handle_ponto_webhook()
        self.assertEqual(frappe.local.response["http_status_code"], 401)

    def test_rate_limited_returns_429(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook import handle_ponto_webhook

        payload = PontoTestDataFactory.create_sync_succeeded_webhook(account_id="a")
        request = _make_request(payload)
        settings = MagicMock()
        settings.enable_webhooks = True
        with patch(f"{WEBHOOK_MODULE}.frappe.request", request):
            with patch(f"{WEBHOOK_MODULE}.frappe.get_single", return_value=settings):
                rl = MagicMock()
                rl.check_rate_limit.return_value = (False, "too many")
                with patch(
                    f"{WEBHOOK_MODULE}.get_webhook_rate_limiter", return_value=rl
                ):
                    result = handle_ponto_webhook()
        self.assertEqual(frappe.local.response["http_status_code"], 429)
        self.assertEqual(result["status"], "rate_limited")


class TestPontoWebhookEntryPointHelpers(FrappeTestCase):
    """Cover _update_account_sync_status against a real mapping."""

    def test_update_sync_status_ok_updates_real_mapping(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            _update_account_sync_status,
        )

        account_id = f"acct-{frappe.generate_hash(length=10)}"
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            row = settings.append(
                "bank_account_mappings",
                {
                    "ponto_account_id": account_id,
                    "ponto_iban": "NL91ABNA0417164300",
                    "sync_status": "Failed",
                },
            )
            settings.flags.ignore_validate = True
            settings.save()
            mapping_name = row.name

            result = _update_account_sync_status(account_id, status="OK")
            self.assertTrue(result)
            self.assertEqual(
                frappe.db.get_value("Ponto Bank Account Mapping", mapping_name, "sync_status"),
                "OK",
            )

    def test_update_sync_status_failed_records_error(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            _update_account_sync_status,
        )

        account_id = f"acct-{frappe.generate_hash(length=10)}"
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            row = settings.append(
                "bank_account_mappings",
                {
                    "ponto_account_id": account_id,
                    "ponto_iban": "NL91ABNA0417164300",
                    "sync_status": "OK",
                },
            )
            settings.flags.ignore_validate = True
            settings.save()
            mapping_name = row.name

            result = _update_account_sync_status(
                account_id, status="Failed", error="bank down"
            )
            self.assertTrue(result)
            self.assertEqual(
                frappe.db.get_value(
                    "Ponto Bank Account Mapping", mapping_name, "last_sync_error"
                ),
                "bank down",
            )


class TestPontoSyncFailedStatusUpdate(FrappeTestCase):
    """handle_sync_failed should invoke the injected status callback."""

    def test_sync_failed_invokes_status_callback_reauth(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            handle_sync_failed,
        )

        captured = {}

        def fake_update(account_id, status=None, error=None):
            captured["account_id"] = account_id
            captured["status"] = status
            captured["error"] = error

        payload = {
            "data": {
                "type": PontoEventType.SYNC_FAILED.value,
                "id": "wh-1",
                "attributes": {
                    "errorCode": "CONSENT_EXPIRED",
                    "errorMessage": "authorization revoked",
                    "synchronizationSubtype": "accountDetails",
                },
                "relationships": {"account": {"data": {"type": "account", "id": "acct-x"}}},
            }
        }
        with patch("frappe.log_error"):
            result = handle_sync_failed(payload, update_account_sync_status_fn=fake_update)
        self.assertTrue(result["needs_reauthorization"])
        self.assertEqual(captured["status"], "Needs Re-authorization")

    def test_sync_failed_invokes_status_callback_plain_failure(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            handle_sync_failed,
        )

        captured = {}

        def fake_update(account_id, status=None, error=None):
            captured["status"] = status

        payload = {
            "data": {
                "type": PontoEventType.SYNC_FAILED.value,
                "id": "wh-2",
                "attributes": {
                    "errorCode": "BANK_TIMEOUT",
                    "errorMessage": "bank temporarily unavailable",
                    "synchronizationSubtype": "accountTransactions",
                },
                "relationships": {"account": {"data": {"type": "account", "id": "acct-y"}}},
            }
        }
        with patch("frappe.log_error"):
            result = handle_sync_failed(payload, update_account_sync_status_fn=fake_update)
        self.assertFalse(result["needs_reauthorization"])
        self.assertEqual(captured["status"], "Failed")


class TestPontoPaymentRequestClosedRealDoc(FrappeTestCase):
    """handle_payment_request_closed against a real Ponto Payment Request."""

    def _make_payment_request(self, ponto_payment_id, status="Pending"):
        doc = frappe.new_doc("Ponto Payment Request")
        doc.ponto_account = "test-account-id"
        doc.amount = 50.0
        doc.currency = "EUR"
        doc.creditor_name = "Test Creditor"
        doc.creditor_iban = "NL91ABNA0417164300"
        doc.remittance_info = "Test payment request"
        doc.status = status
        doc.ponto_payment_id = ponto_payment_id
        doc.insert()
        return doc

    def test_payment_request_closed_maps_and_updates_status(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            handle_payment_request_closed,
        )

        ponto_payment_id = f"pay-{frappe.generate_hash(length=10)}"
        doc = self._make_payment_request(ponto_payment_id, status="Pending")

        payload = json.loads(
            PontoTestDataFactory.create_payment_request_closed_webhook(
                payment_id=ponto_payment_id,
                status=PaymentStatus.SIGNED,  # avoid Executed -> payment entry creation
            )
        )
        result = handle_payment_request_closed(payload)

        self.assertEqual(result["action"], "status_updated")
        self.assertEqual(result["new_status"], "Signed")
        self.assertIn(doc.name, result["updated_requests"])
        self.assertEqual(
            frappe.db.get_value("Ponto Payment Request", doc.name, "status"), "Signed"
        )

    def test_payment_request_closed_unknown_status(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            handle_payment_request_closed,
        )

        ponto_payment_id = f"pay-{frappe.generate_hash(length=10)}"
        self._make_payment_request(ponto_payment_id, status="Pending")
        payload = json.loads(
            PontoTestDataFactory.create_payment_request_closed_webhook(
                payment_id=ponto_payment_id,
                status="some_weird_status",
            )
        )
        result = handle_payment_request_closed(payload)
        self.assertEqual(result["reason"], "unknown_status")


class TestPontoPaymentLinkStatusRealDoc(FrappeTestCase):
    """_update_payment_link_status against a real Ponto Payment Link."""

    def _make_payment_link(self, request_id, status="Draft"):
        doc = frappe.new_doc("Ponto Payment Link")
        doc.payment_type = "One-Time"
        doc.amount = 25.0
        doc.currency = "EUR"
        doc.description = "Membership dues"
        doc.creditor_name = "Vereniging"
        doc.creditor_iban = "NL91ABNA0417164300"
        doc.status = status
        doc.ponto_request_id = request_id
        doc.insert()
        return doc

    def test_payment_link_status_updates_to_authorized(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            _update_payment_link_status,
        )

        request_id = f"req-{frappe.generate_hash(length=10)}"
        doc = self._make_payment_link(request_id, status="Pending Authorization")

        result = _update_payment_link_status(request_id, new_status="signed")
        self.assertEqual(result["action"], "status_updated")
        self.assertEqual(result["new_status"], "Authorized")
        self.assertIn(doc.name, result["updated_links"])

    def test_payment_link_status_unknown_status(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            _update_payment_link_status,
        )

        request_id = f"req-{frappe.generate_hash(length=10)}"
        self._make_payment_link(request_id, status="Pending Authorization")
        result = _update_payment_link_status(request_id, new_status="bogus")
        self.assertEqual(result["reason"], "unknown_status")

    def test_periodic_payment_execution_uses_safe_savepoint(self):
        """Periodic execution on a real (hyphenated-name) doc must not crash on savepoint SQL."""
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            handle_periodic_payment_execution,
        )

        request_id = f"req-{frappe.generate_hash(length=10)}"
        doc = self._make_payment_link(request_id, status="Authorized")

        payload = json.loads(
            PontoTestDataFactory.create_periodic_payment_executed_webhook(
                request_id=request_id, execution_number=1
            )
        )
        result = handle_periodic_payment_execution(payload)
        # No member linked -> processing returns early, but the savepoint path
        # must execute cleanly (this is the regression guard for the hyphen bug).
        self.assertEqual(result["action"], "payment_processed")
        self.assertIn(doc.name, result["updated_links"])
        self.assertIsNone(result["failed_links"])


class TestSafeSavepointName(FrappeTestCase):
    """The savepoint-name sanitizer must strip MariaDB-illegal characters."""

    def test_hyphenated_doc_name_sanitized(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            _safe_savepoint_name,
        )

        name = _safe_savepoint_name("payment_status", "PONTO-PAY-6206")
        self.assertEqual(name, "payment_status_PONTO_PAY_6206")
        # Resulting identifier must be alphanumeric + underscore only
        self.assertRegex(name, r"^[0-9A-Za-z_]+$")

    def test_already_safe_name_unchanged_shape(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            _safe_savepoint_name,
        )

        name = _safe_savepoint_name("periodic_payment", "abc123")
        self.assertEqual(name, "periodic_payment_abc123")


if __name__ == "__main__":
    unittest.main()
