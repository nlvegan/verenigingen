"""
Unit tests for Ponto Betaalverzoek (payment-request) client.

These are Tier-1 unit tests: they stub ONLY the HTTP boundary (the inner
PontoClient's get/post/delete methods, which are the wrappers around
requests.Session) and the Ponto Settings singleton. They assert request
construction (endpoint/payload shape), response parsing into dataclasses, and
error handling. No live Ponto credentials are required.

Usage:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.sepa.test_ponto_betaalverzoek_client_unit
"""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.ponto_test_data_factory import TestIBAN
from verenigingen.tests.fixtures.singleton_backup import SingletonBackup


def _payment_request_api_data(
    request_id="pir-123",
    amount="25.00",
    signing_uri="https://myponto.com/sign/pir-123",
    signed_at=None,
    closed_at=None,
    status=None,
):
    """Build a realistic Ponto paymentInitiationRequest JSON:API data object."""
    attrs = {
        "amount": amount,
        "currency": "EUR",
        "creditorName": "Vegan Netwerk Nederland",
        "creditorAccountReference": TestIBAN.ABN_AMRO_1,
        "remittanceInformation": "Membership dues - John Doe",
        "redirectUri": "https://site.example/ponto/callback",
        "signingUri": signing_uri,
    }
    if signed_at:
        attrs["signedAt"] = signed_at
    if closed_at:
        attrs["closedAt"] = closed_at
    if status:
        attrs["status"] = status
    return {
        "type": "paymentInitiationRequest",
        "id": request_id,
        "attributes": attrs,
    }


class TestBetaalverzoekClientUnit(FrappeTestCase):
    """Unit tests for PontoBetaalverzoekClient (HTTP boundary stubbed)."""

    TEST_ACCOUNT_ID = "acc-uuid-0001"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._singleton_backup = SingletonBackup("Ponto Settings")
        cls._singleton_backup.backup()
        cls._setup_settings()

    @classmethod
    def tearDownClass(cls):
        cls._singleton_backup.restore()
        super().tearDownClass()

    @classmethod
    def _setup_settings(cls):
        """Enable mTLS + a bank-account mapping so _verify_pis_enabled passes."""
        settings = frappe.get_single("Ponto Settings")
        settings.ibanity_client_id = "test_client_id"
        settings.ibanity_client_secret = "test_client_secret"
        settings.sandbox_client_id = "test_client_id"
        settings.sandbox_client_secret = "test_client_secret"
        settings.sandbox_mode = 1
        settings.use_ibanity_mtls = 1
        settings.ibanity_certificate = (
            "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----"
        )
        settings.ibanity_private_key = (
            "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
        )
        # Add an enabled bank account mapping
        settings.set("bank_account_mappings", [])
        settings.append(
            "bank_account_mappings",
            {
                "ponto_account_id": cls.TEST_ACCOUNT_ID,
                "enabled": 1,
            },
        )
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        settings.flags.ignore_validate = False
        frappe.db.commit()

    def _make_client(self):
        """Build a betaalverzoek client with the inner HTTP client mocked.

        PontoClient (the HTTP boundary) is fully replaced so no real network /
        token fetch / mTLS file work happens. _verify_pis_enabled runs against
        the real (test-configured) Ponto Settings.
        """
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            PontoBetaalverzoekClient,
        )

        with patch(
            "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.PontoClient"
        ) as mock_ponto_cls:
            mock_inner = MagicMock()
            mock_ponto_cls.return_value = mock_inner
            client = PontoBetaalverzoekClient()
        return client, client._client

    # -------------------------------------------------------------------------
    # sanitize_sepa_text
    # -------------------------------------------------------------------------

    def test_sanitize_sepa_text_strips_disallowed_chars(self):
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            sanitize_sepa_text,
        )

        result = sanitize_sepa_text("Café & Co. #1 — payment!")
        # accents normalized, & -> +, # removed, em-dash -> -, ! -> .
        self.assertNotIn("&", result)
        self.assertNotIn("#", result)
        self.assertNotIn("é", result)
        self.assertIn("+", result)

    def test_sanitize_sepa_text_empty_passthrough(self):
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            sanitize_sepa_text,
        )

        self.assertEqual(sanitize_sepa_text(""), "")

    # -------------------------------------------------------------------------
    # PaymentInitiationRequest.from_api_response (status inference)
    # -------------------------------------------------------------------------

    def test_from_api_response_status_pending(self):
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            PaymentInitiationRequest,
        )

        req = PaymentInitiationRequest.from_api_response(_payment_request_api_data())
        self.assertEqual(req.status, "pending")
        self.assertEqual(req.amount, Decimal("25.00"))
        self.assertEqual(req.currency, "EUR")
        self.assertEqual(req.redirect_link, "https://myponto.com/sign/pir-123")

    def test_from_api_response_status_signed(self):
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            PaymentInitiationRequest,
        )

        data = _payment_request_api_data(signed_at="2026-01-01T10:00:00Z")
        req = PaymentInitiationRequest.from_api_response(data)
        self.assertEqual(req.status, "signed")

    def test_from_api_response_status_closed(self):
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            PaymentInitiationRequest,
        )

        data = _payment_request_api_data(
            signed_at="2026-01-01T10:00:00Z", closed_at="2026-01-02T10:00:00Z"
        )
        req = PaymentInitiationRequest.from_api_response(data)
        self.assertEqual(req.status, "closed")

    def test_from_api_response_explicit_status_wins(self):
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            PaymentInitiationRequest,
        )

        data = _payment_request_api_data(status="rejected", closed_at="2026-01-02T10:00:00Z")
        req = PaymentInitiationRequest.from_api_response(data)
        self.assertEqual(req.status, "rejected")

    def test_from_api_response_empty_data_raises(self):
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            PaymentInitiationRequest,
        )
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        with self.assertRaises(PontoAPIError):
            PaymentInitiationRequest.from_api_response({})

    def test_from_api_response_missing_id_raises(self):
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            PaymentInitiationRequest,
        )
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        with self.assertRaises(PontoAPIError):
            PaymentInitiationRequest.from_api_response({"attributes": {"amount": "1"}})

    def test_from_api_response_missing_attributes_raises(self):
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            PaymentInitiationRequest,
        )
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        with self.assertRaises(PontoAPIError):
            PaymentInitiationRequest.from_api_response({"id": "x"})

    # -------------------------------------------------------------------------
    # create_payment_request - happy path & request construction
    # -------------------------------------------------------------------------

    def test_create_payment_request_builds_correct_endpoint_and_payload(self):
        client, inner = self._make_client()
        inner.post.return_value = {"data": _payment_request_api_data()}

        result = client.create_payment_request(
            amount=25.00,
            creditor_name="Vegan Netwerk Nederland",
            creditor_iban=TestIBAN.ABN_AMRO_1,
            remittance_info="Membership dues - John Doe",
            redirect_uri="https://site.example/ponto/callback",
            creditor_bic="ABNANL2A",
            end_to_end_id="E2E-001",
        )

        inner.post.assert_called_once()
        endpoint = inner.post.call_args.args[0]
        payload = inner.post.call_args.kwargs["data"]
        self.assertEqual(
            endpoint, f"/accounts/{self.TEST_ACCOUNT_ID}/payment-requests"
        )
        attrs = payload["data"]["attributes"]
        self.assertEqual(payload["data"]["type"], "paymentInitiationRequest")
        self.assertEqual(attrs["amount"], 25.0)
        self.assertEqual(attrs["currency"], "EUR")
        self.assertEqual(attrs["creditorAccountReference"], TestIBAN.ABN_AMRO_1)
        self.assertEqual(attrs["creditorAccountReferenceType"], "IBAN")
        self.assertEqual(attrs["redirectUri"], "https://site.example/ponto/callback")
        self.assertEqual(attrs["creditorAgent"], "ABNANL2A")
        self.assertEqual(attrs["creditorAgentType"], "BIC")
        self.assertEqual(attrs["endToEndId"], "E2E-001")
        self.assertEqual(result.id, "pir-123")
        self.assertEqual(result.redirect_link, "https://myponto.com/sign/pir-123")

    def test_create_payment_request_promotes_top_level_links(self):
        """When redirect link is in top-level links (not in data), it is promoted."""
        client, inner = self._make_client()
        data = _payment_request_api_data(signing_uri="")  # no signingUri
        inner.post.return_value = {
            "data": data,
            "links": {"redirect": "https://myponto.com/top-level-redirect"},
        }

        result = client.create_payment_request(
            amount=10.00,
            creditor_name="Org",
            creditor_iban=TestIBAN.ABN_AMRO_1,
            remittance_info="ref",
        )
        self.assertEqual(result.redirect_link, "https://myponto.com/top-level-redirect")

    def test_create_payment_request_rejects_zero_amount(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError

        client, inner = self._make_client()
        with self.assertRaises(PontoIntegrationError):
            client.create_payment_request(
                amount=0,
                creditor_name="Org",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="ref",
            )
        inner.post.assert_not_called()

    def test_create_payment_request_rejects_excess_amount(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError

        client, _ = self._make_client()
        with self.assertRaises(PontoIntegrationError):
            client.create_payment_request(
                amount=1_000_000_000.00,
                creditor_name="Org",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="ref",
            )

    def test_create_payment_request_rejects_three_decimals(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError

        client, _ = self._make_client()
        with self.assertRaises(PontoIntegrationError):
            client.create_payment_request(
                amount=25.123,
                creditor_name="Org",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="ref",
            )

    def test_create_payment_request_rejects_invalid_iban(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError

        client, _ = self._make_client()
        with self.assertRaises(PontoIntegrationError):
            client.create_payment_request(
                amount=25.00,
                creditor_name="Org",
                creditor_iban="NL00BANK0000000000",  # bad checksum
                remittance_info="ref",
            )

    def test_create_payment_request_normalizes_iban_spaces_case(self):
        client, inner = self._make_client()
        inner.post.return_value = {"data": _payment_request_api_data()}

        client.create_payment_request(
            amount=25.00,
            creditor_name="Org",
            creditor_iban="nl91 abna 0417 1643 00",
            remittance_info="ref",
        )
        attrs = inner.post.call_args.kwargs["data"]["data"]["attributes"]
        self.assertEqual(attrs["creditorAccountReference"], TestIBAN.ABN_AMRO_1)

    def test_create_payment_request_wraps_api_error(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client, inner = self._make_client()
        inner.post.side_effect = PontoAPIError("boom", status_code=400, error_code="x")

        with self.assertRaises(PontoAPIError) as ctx:
            client.create_payment_request(
                amount=25.00,
                creditor_name="Org",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="ref",
            )
        # PontoAPIError is re-raised directly (details preserved)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_create_payment_request_wraps_generic_error(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client, inner = self._make_client()
        inner.post.side_effect = RuntimeError("network down")

        with self.assertRaises(PontoAPIError) as ctx:
            client.create_payment_request(
                amount=25.00,
                creditor_name="Org",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="ref",
            )
        self.assertIn("network down", str(ctx.exception))

    # -------------------------------------------------------------------------
    # get_payment_request / list / delete
    # -------------------------------------------------------------------------

    def test_get_payment_request_builds_endpoint(self):
        client, inner = self._make_client()
        inner.get.return_value = {"data": _payment_request_api_data(request_id="pir-9")}

        result = client.get_payment_request("pir-9")
        inner.get.assert_called_once_with(
            f"/accounts/{self.TEST_ACCOUNT_ID}/payment-requests/pir-9"
        )
        self.assertEqual(result.id, "pir-9")

    def test_get_payment_request_error_wrapped(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client, inner = self._make_client()
        inner.get.side_effect = RuntimeError("not found")
        with self.assertRaises(PontoAPIError):
            client.get_payment_request("pir-9")

    def test_list_payment_requests_parses_all(self):
        client, inner = self._make_client()
        inner.get_paginated.return_value = [
            _payment_request_api_data(request_id="a"),
            _payment_request_api_data(request_id="b"),
        ]
        result = client.list_payment_requests(limit=25)
        inner.get_paginated.assert_called_once_with(
            "/payment-requests", limit=25, max_pages=None
        )
        self.assertEqual([r.id for r in result], ["a", "b"])

    def test_list_payment_requests_error_wrapped(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client, inner = self._make_client()
        inner.get_paginated.side_effect = RuntimeError("boom")
        with self.assertRaises(PontoAPIError):
            client.list_payment_requests()

    def test_delete_payment_request_builds_endpoint(self):
        client, inner = self._make_client()
        inner.delete.return_value = True
        result = client.delete_payment_request("pir-5")
        inner.delete.assert_called_once_with(
            f"/accounts/{self.TEST_ACCOUNT_ID}/payment-requests/pir-5"
        )
        self.assertTrue(result)

    def test_delete_payment_request_error_wrapped(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client, inner = self._make_client()
        inner.delete.side_effect = RuntimeError("boom")
        with self.assertRaises(PontoAPIError):
            client.delete_payment_request("pir-5")

    # -------------------------------------------------------------------------
    # Deprecated periodic methods raise NotImplementedError
    # -------------------------------------------------------------------------

    def test_periodic_methods_raise_not_implemented(self):
        client, _ = self._make_client()
        with self.assertRaises(NotImplementedError):
            client.create_periodic_payment_request(
                amount=1, creditor_name="x", creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="r", frequency="monthly",
            )
        with self.assertRaises(NotImplementedError):
            client.get_periodic_payment_request("x")
        with self.assertRaises(NotImplementedError):
            client.list_periodic_payment_requests()
        with self.assertRaises(NotImplementedError):
            client.delete_periodic_payment_request("x")

    # -------------------------------------------------------------------------
    # _verify_pis_enabled configuration guards
    # -------------------------------------------------------------------------

    def _setup_mtls_flag(self, enabled):
        """Test setup helper: toggle the Ponto Settings mTLS flag."""
        settings = frappe.get_single("Ponto Settings")
        settings.use_ibanity_mtls = 1 if enabled else 0
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    def test_verify_pis_disabled_when_mtls_off(self):
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            PontoBetaalverzoekClient,
        )
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoConfigurationError

        self._setup_mtls_flag(False)
        self.addCleanup(self._setup_mtls_flag, True)

        with patch(
            "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.PontoClient"
        ):
            with self.assertRaises(PontoConfigurationError):
                PontoBetaalverzoekClient()


if __name__ == "__main__":
    unittest.main()
