# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
"""
Spec-compliance tests for the Pay.nl Direct Debit mandate payloads.

These encode the official Pay.nl REST v2 contract
(https://developer.pay.nl/reference/post_directdebits-mandates,
https://developer.pay.nl/reference/post_directdebits,
https://developer.pay.nl/reference/delete_directdebits-mandates-mandateid)
which the integration originally did not match. The earlier code sent a
lowercase ``type``, a ``debtor`` object and read ``mandateId`` from the response;
the real API requires an UPPERCASE ``type``, a ``customer.bankAccount`` object,
``amount`` in integer cents, and returns the mandate id as ``code``.

These are unit tests against the payload builders (the HTTP boundary is mocked)
because the sandbox service behind our credentials does not grant Direct Debit
permission, so the create/execute/cancel calls cannot be exercised live yet.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.ing_checkout.services import MandateService
from verenigingen.verenigingen_payments.ing_checkout.tests.mandate_test_helpers import resolves_to


def _sepa(**overrides):
    data = {
        "name": "SEPA-00001",
        "iban": "NL91ABNA0417164300",
        "bic": "ABNANL2A",
        "account_holder_name": "Jan Jansen",
        "status": "Active",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _member(**overrides):
    data = {"name": "MEM-00001", "full_name": "Jan Jansen", "email": "jan@example.org"}
    data.update(overrides)
    return SimpleNamespace(**data)


class TestMandatePayloadSpec(FrappeTestCase):
    """The create-mandate payload must match Pay.nl's Mandate:Create contract."""

    def setUp(self):
        super().setUp()
        self.service = MandateService()
        self.service._settings = SimpleNamespace(service_id="SL-1234-5678")

    def _build(self, mandate_type="flexible", amount=12.50):
        return self.service._build_mandate_payload(
            sepa_mandate=_sepa(),
            member=_member(),
            mandate_type=mandate_type,
            amount=amount,
            description="Dues",
        )

    def test_type_is_uppercased(self):
        """Pay.nl rejects lowercase types with INVALID_DIRECT_DEBIT_TYPE."""
        self.assertEqual(self._build(mandate_type="flexible")["type"], "FLEXIBLE")
        self.assertEqual(self._build(mandate_type="single")["type"], "SINGLE")
        self.assertEqual(self._build(mandate_type="recurring")["type"], "RECURRING")

    def test_uses_customer_bankaccount_not_debtor(self):
        """Request must carry customer.bankAccount.{iban,owner}, not a debtor object."""
        payload = self._build()
        self.assertNotIn("debtor", payload)
        self.assertEqual(payload["customer"]["bankAccount"]["iban"], "NL91ABNA0417164300")
        self.assertEqual(payload["customer"]["bankAccount"]["owner"], "Jan Jansen")
        self.assertEqual(payload["customer"]["email"], "jan@example.org")

    def test_includes_bic_when_present(self):
        payload = self._build()
        self.assertEqual(payload["customer"]["bankAccount"]["bic"], "ABNANL2A")

    def test_omits_bic_when_absent(self):
        payload = self.service._build_mandate_payload(
            sepa_mandate=_sepa(bic=None), member=_member(), mandate_type="flexible", amount=10
        )
        self.assertNotIn("bic", payload["customer"]["bankAccount"])

    def test_amount_is_integer_cents(self):
        """amount.value is an integer in cents (12.50 EUR -> 1250)."""
        payload = self._build(amount=12.50)
        self.assertEqual(payload["amount"], {"value": 1250, "currency": "EUR"})
        self.assertIsInstance(payload["amount"]["value"], int)

    def test_includes_request_ip_address(self):
        """customer.ipAddress is required by Pay.nl; sourced from the request IP."""
        original = getattr(frappe.local, "request_ip", None)
        try:
            frappe.local.request_ip = "203.0.113.7"
            payload = self._build()
            self.assertEqual(payload["customer"]["ipAddress"], "203.0.113.7")
        finally:
            frappe.local.request_ip = original

    def test_serviceid_and_uppercase_default(self):
        payload = self._build()
        self.assertEqual(payload["serviceId"], "SL-1234-5678")


class TestCreateMandateReadsCode(FrappeTestCase):
    """create_mandate_for_member must read the mandate id from the ``code`` field."""

    def setUp(self):
        super().setUp()
        self.mock_settings = SimpleNamespace(service_id="SL-1234-5678")

    def test_reads_code_from_response(self):
        mock_member = _member()
        mock_sepa = _sepa()

        with patch("frappe.get_doc") as mock_get_doc, resolves_to("SEPA-00001"):
            mock_get_doc.side_effect = lambda dt, name=None: (
                mock_member if dt == "Member" else mock_sepa if dt == "SEPA Mandate" else MagicMock()
            )
            mock_client = MagicMock()
            # Pay.nl returns the mandate id as "code" (IO-####-####-####), not mandateId/id.
            mock_client.create_mandate.return_value = {"code": "IO-1234-5678-9012"}

            service = MandateService()
            service._client = mock_client
            service._settings = self.mock_settings

            with patch(
                "verenigingen.verenigingen_payments.doctype.ing_checkout_mandate."
                "ing_checkout_mandate.get_or_create_mandate"
            ) as mock_create:
                mandate_doc = MagicMock()
                mandate_doc.name = "ING-MAND-00001"
                mandate_doc.status = "Pending"
                mock_create.return_value = mandate_doc
                result = service.create_mandate_for_member("MEM-00001", amount=12.50)

        self.assertTrue(result["success"], msg=result.get("error"))
        self.assertEqual(result["mandate_id"], "IO-1234-5678-9012")

    def test_missing_amount_returns_error(self):
        """Pay.nl requires amount (minimum 1 cent); creation without it must fail fast."""
        mock_member = _member()
        mock_sepa = _sepa()

        with patch("frappe.get_doc") as mock_get_doc, resolves_to("SEPA-00001"):
            mock_get_doc.side_effect = lambda dt, name=None: (
                mock_member if dt == "Member" else mock_sepa if dt == "SEPA Mandate" else MagicMock()
            )
            service = MandateService()
            service._client = MagicMock()
            service._settings = self.mock_settings

            result = service.create_mandate_for_member("MEM-00001", amount=None)

        self.assertFalse(result["success"])
        self.assertIn("amount", result["error"].lower())
        service._client.create_mandate.assert_not_called()


class TestExecuteDebitPayload(FrappeTestCase):
    """DirectDebit:Add identifies the mandate via the ``mandate`` field, not ``mandateId``."""

    def test_uses_mandate_field_and_cents(self):
        from verenigingen.verenigingen_payments.doctype.ing_checkout_mandate.ing_checkout_mandate import (
            INGCheckoutMandate,
        )

        doc = frappe.new_doc("ING Checkout Mandate")
        doc.mandate_id = "IO-1234-5678-9012"
        doc.mandate_type = "flexible"
        doc.status = "Active"

        mock_client = MagicMock()
        mock_client.create_direct_debit.return_value = {"success": True}

        with patch(
            "verenigingen.verenigingen_payments.ing_checkout.client.get_client", return_value=mock_client
        ), patch.object(INGCheckoutMandate, "save"):
            doc.execute_debit(amount=49.99, description="Membership dues")

        payload = mock_client.create_direct_debit.call_args[0][0]
        self.assertEqual(payload["mandate"], "IO-1234-5678-9012")
        self.assertNotIn("mandateId", payload)
        self.assertEqual(payload["amount"]["value"], 4999)


class TestCancelMandateHttp(FrappeTestCase):
    """Mandate:Delete is HTTP DELETE on /directdebits/mandates/{id} (no /cancel suffix)."""

    @patch("requests.Session.request")
    def test_cancel_uses_http_delete(self, mock_request):
        from verenigingen.verenigingen_payments.ing_checkout.client import PayNLClient
        from verenigingen.verenigingen_payments.ing_checkout.tests.test_client import (
            MockResponse,
            MockSettings,
        )

        mock_request.return_value = MockResponse({"success": True}, 200)
        client = PayNLClient(settings=MockSettings())

        client.cancel_mandate("IO-1234-5678-9012")

        kwargs = mock_request.call_args.kwargs
        self.assertEqual(kwargs["method"], "DELETE")
        self.assertTrue(kwargs["url"].endswith("/directdebits/mandates/IO-1234-5678-9012"))
        self.assertNotIn("/cancel", kwargs["url"])
