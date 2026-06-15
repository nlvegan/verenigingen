"""
Unit tests for Ponto Payment (SEPA credit transfer) client.

Tier-1 unit tests: only the inner PontoClient HTTP boundary is stubbed.
Asserts endpoint/payload construction, response parsing, validation and error
handling. No live Ponto credentials required.

Usage:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.sepa.test_ponto_payment_client_unit
"""

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.ponto_test_data_factory import TestIBAN


def _payment_api_data(payment_id="pay-1", status="pending", redirect="https://p/sign"):
    return {
        "type": "paymentInitiationRequest",
        "id": payment_id,
        "attributes": {
            "status": status,
            "amount": "100.00",
            "currency": "EUR",
            "creditorName": "Supplier BV",
            "creditorAccountReference": TestIBAN.ABN_AMRO_1,
            "creditorAccountReferenceType": "IBAN",
            "remittanceInformation": "Invoice INV-2025-001",
            "remittanceInformationType": "unstructured",
            "requestedExecutionDate": "2026-02-01",
        },
        "links": {"redirect": redirect},
    }


class TestPontoPaymentClientUnit(FrappeTestCase):
    """Unit tests for PontoPaymentClient with HTTP boundary stubbed."""

    ACCOUNT_ID = "acc-uuid-pay"

    def _make_client(self):
        from verenigingen.verenigingen_payments.ponto.clients.payment_client import (
            PontoPaymentClient,
        )

        with patch(
            "verenigingen.verenigingen_payments.ponto.clients.payment_client.PontoClient"
        ) as mock_cls:
            mock_inner = MagicMock()
            mock_cls.return_value = mock_inner
            client = PontoPaymentClient()
        return client, client._client

    # -------------------------------------------------------------------------
    # PaymentRequest.from_api_response
    # -------------------------------------------------------------------------

    def test_from_api_response_parses_fields(self):
        from verenigingen.verenigingen_payments.ponto.clients.payment_client import (
            PaymentRequest,
        )

        req = PaymentRequest.from_api_response(_payment_api_data())
        self.assertEqual(req.id, "pay-1")
        self.assertEqual(req.status, "pending")
        self.assertEqual(req.amount, Decimal("100.00"))
        self.assertEqual(req.creditor_iban, TestIBAN.ABN_AMRO_1)
        self.assertEqual(req.requested_execution_date, date(2026, 2, 1))
        self.assertEqual(req.redirect_link, "https://p/sign")

    def test_from_api_response_bad_exec_date_tolerated(self):
        from verenigingen.verenigingen_payments.ponto.clients.payment_client import (
            PaymentRequest,
        )

        data = _payment_api_data()
        data["attributes"]["requestedExecutionDate"] = "not-a-date"
        req = PaymentRequest.from_api_response(data)
        self.assertIsNone(req.requested_execution_date)

    # -------------------------------------------------------------------------
    # create_payment
    # -------------------------------------------------------------------------

    def test_create_payment_builds_endpoint_and_payload(self):
        client, inner = self._make_client()
        inner.post.return_value = {"data": _payment_api_data()}

        result = client.create_payment(
            account_id=self.ACCOUNT_ID,
            amount=100.00,
            currency="EUR",
            creditor_name="Supplier BV",
            creditor_iban=TestIBAN.ABN_AMRO_1,
            remittance_info="Invoice INV-2025-001",
            redirect_uri="https://site/cb",
            creditor_bic="ABNANL2A",
            requested_execution_date=date(2026, 2, 1),
            end_to_end_id="E2E",
        )

        endpoint = inner.post.call_args.args[0]
        self.assertEqual(
            endpoint,
            f"/accounts/{self.ACCOUNT_ID}/payment-initiation-requests",
        )
        attrs = inner.post.call_args.kwargs["data"]["data"]["attributes"]
        self.assertEqual(attrs["amount"], 100.0)
        self.assertEqual(attrs["redirectUri"], "https://site/cb")
        self.assertEqual(attrs["creditorAgent"], "ABNANL2A")
        self.assertEqual(attrs["requestedExecutionDate"], "2026-02-01")
        self.assertEqual(attrs["endToEndId"], "E2E")
        self.assertEqual(result.id, "pay-1")

    def test_create_payment_rejects_non_eur(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError

        client, inner = self._make_client()
        with self.assertRaises(PontoIntegrationError):
            client.create_payment(
                account_id=self.ACCOUNT_ID,
                amount=10,
                currency="USD",
                creditor_name="x",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="r",
            )
        inner.post.assert_not_called()

    def test_create_payment_rejects_zero_amount(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError

        client, _ = self._make_client()
        with self.assertRaises(PontoIntegrationError):
            client.create_payment(
                account_id=self.ACCOUNT_ID,
                amount=0,
                currency="EUR",
                creditor_name="x",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="r",
            )

    def test_create_payment_rejects_excess_amount(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError

        client, _ = self._make_client()
        with self.assertRaises(PontoIntegrationError):
            client.create_payment(
                account_id=self.ACCOUNT_ID,
                amount=1_000_000_000.0,
                currency="EUR",
                creditor_name="x",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="r",
            )

    def test_create_payment_rejects_three_decimals(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError

        client, _ = self._make_client()
        with self.assertRaises(PontoIntegrationError):
            client.create_payment(
                account_id=self.ACCOUNT_ID,
                amount=10.001,
                currency="EUR",
                creditor_name="x",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="r",
            )

    def test_create_payment_rejects_invalid_iban(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError

        client, _ = self._make_client()
        with self.assertRaises(PontoIntegrationError):
            client.create_payment(
                account_id=self.ACCOUNT_ID,
                amount=10,
                currency="EUR",
                creditor_name="x",
                creditor_iban="NL00BANK0000000000",
                remittance_info="r",
            )

    def test_create_payment_wraps_error(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client, inner = self._make_client()
        inner.post.side_effect = RuntimeError("boom")
        with self.assertRaises(PontoAPIError):
            client.create_payment(
                account_id=self.ACCOUNT_ID,
                amount=10,
                currency="EUR",
                creditor_name="x",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="r",
            )

    # -------------------------------------------------------------------------
    # get / list / delete
    # -------------------------------------------------------------------------

    def test_get_payment_builds_endpoint(self):
        client, inner = self._make_client()
        inner.get.return_value = {"data": _payment_api_data(payment_id="p9")}
        result = client.get_payment(self.ACCOUNT_ID, "p9")
        inner.get.assert_called_once_with(
            f"/accounts/{self.ACCOUNT_ID}/payment-initiation-requests/p9"
        )
        self.assertEqual(result.id, "p9")

    def test_get_payment_wraps_error(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client, inner = self._make_client()
        inner.get.side_effect = RuntimeError("boom")
        with self.assertRaises(PontoAPIError):
            client.get_payment(self.ACCOUNT_ID, "p9")

    def test_list_payments_parses_all(self):
        client, inner = self._make_client()
        inner.get_paginated.return_value = [
            _payment_api_data(payment_id="a"),
            _payment_api_data(payment_id="b"),
        ]
        result = client.list_payments(self.ACCOUNT_ID, limit=10, max_pages=2)
        inner.get_paginated.assert_called_once_with(
            f"/accounts/{self.ACCOUNT_ID}/payment-initiation-requests",
            limit=10,
            max_pages=2,
        )
        self.assertEqual([p.id for p in result], ["a", "b"])

    def test_list_payments_wraps_error(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client, inner = self._make_client()
        inner.get_paginated.side_effect = RuntimeError("boom")
        with self.assertRaises(PontoAPIError):
            client.list_payments(self.ACCOUNT_ID)

    def test_delete_payment_builds_endpoint(self):
        client, inner = self._make_client()
        inner.delete.return_value = True
        result = client.delete_payment(self.ACCOUNT_ID, "p3")
        inner.delete.assert_called_once_with(
            f"/accounts/{self.ACCOUNT_ID}/payment-initiation-requests/p3"
        )
        self.assertTrue(result)

    def test_delete_payment_wraps_error(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client, inner = self._make_client()
        inner.delete.side_effect = RuntimeError("boom")
        with self.assertRaises(PontoAPIError):
            client.delete_payment(self.ACCOUNT_ID, "p3")

    def test_factory_returns_instance(self):
        from verenigingen.verenigingen_payments.ponto.clients.payment_client import (
            PontoPaymentClient,
            get_payment_client,
        )

        with patch(
            "verenigingen.verenigingen_payments.ponto.clients.payment_client.PontoClient"
        ):
            self.assertIsInstance(get_payment_client(), PontoPaymentClient)


if __name__ == "__main__":
    unittest.main()
