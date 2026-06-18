# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Branch coverage for PayNLClient (client.py) not covered by test_client.py.

Covers the GMS read/delete methods (get_mandate, list_mandates with and without
filters, cancel_mandate as HTTP DELETE, get_direct_debit), the
non-JSON-response handling in _handle_response, the generic RequestException
mapping, test_connection's PayNLError branch, the developer_mode logging path,
and the get_client factory. The HTTP layer is stubbed at requests.Session.request
(the true external boundary); all request-shaping and response-parsing logic
runs for real.
"""

import json
from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.ing_checkout.client import (
    PayNLClient,
    PayNLError,
    get_client,
)
from verenigingen.verenigingen_payments.ing_checkout.tests.test_client import (
    MockResponse,
    MockSettings,
)


class TestGMSReadMethods(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.client = PayNLClient(settings=MockSettings())

    @patch("requests.Session.request")
    def test_get_mandate_uses_get_on_mandate_resource(self, mock_request):
        mock_request.return_value = MockResponse({"mandateId": "IO-1", "status": "active"})
        result = self.client.get_mandate("IO-1")
        self.assertEqual(result["status"], "active")
        call = mock_request.call_args
        self.assertEqual(call.kwargs["method"], "GET")
        self.assertIn("/v2/directdebits/mandates/IO-1", call.kwargs["url"])

    @patch("requests.Session.request")
    def test_list_mandates_no_filters_sends_only_limit(self, mock_request):
        mock_request.return_value = MockResponse({"mandates": []})
        self.client.list_mandates()
        params = mock_request.call_args.kwargs["params"]
        self.assertEqual(params, {"limit": 50})

    @patch("requests.Session.request")
    def test_list_mandates_with_filters(self, mock_request):
        mock_request.return_value = MockResponse({"mandates": []})
        self.client.list_mandates(service_id="SL-9", status="active", limit=10)
        params = mock_request.call_args.kwargs["params"]
        self.assertEqual(params["limit"], 10)
        self.assertEqual(params["serviceId"], "SL-9")
        self.assertEqual(params["status"], "active")

    @patch("requests.Session.request")
    def test_cancel_mandate_uses_http_delete(self, mock_request):
        mock_request.return_value = MockResponse({"cancelled": True})
        result = self.client.cancel_mandate("IO-1")
        self.assertTrue(result["cancelled"])
        call = mock_request.call_args
        # Pay.nl spec: Mandate:Delete is a DELETE on the resource, not POST /cancel.
        self.assertEqual(call.kwargs["method"], "DELETE")
        self.assertIn("/v2/directdebits/mandates/IO-1", call.kwargs["url"])
        self.assertNotIn("/cancel", call.kwargs["url"])

    @patch("requests.Session.request")
    def test_get_direct_debit(self, mock_request):
        mock_request.return_value = MockResponse({"referenceId": "IL-1", "status": "pending"})
        result = self.client.get_direct_debit("IL-1")
        self.assertEqual(result["referenceId"], "IL-1")
        call = mock_request.call_args
        self.assertEqual(call.kwargs["method"], "GET")
        self.assertIn("/v2/directdebits/IL-1", call.kwargs["url"])


class TestResponseHandlingBranches(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.client = PayNLClient(settings=MockSettings())

    @patch("requests.Session.request")
    def test_non_json_body_wrapped_in_raw_response(self, mock_request):
        """A 200 with non-JSON text becomes {'raw_response': text}."""
        bad = MagicMock()
        bad.status_code = 200
        bad.text = "<html>not json</html>"
        bad.json.side_effect = json.JSONDecodeError("x", "y", 0)
        mock_request.return_value = bad

        result = self.client.get_order("EX-1")
        self.assertEqual(result, {"raw_response": "<html>not json</html>"})

    @patch("requests.Session.request")
    def test_empty_body_returns_empty_dict(self, mock_request):
        empty = MagicMock()
        empty.status_code = 200
        empty.text = ""
        mock_request.return_value = empty
        self.assertEqual(self.client.get_order("EX-1"), {})

    @patch("requests.Session.request")
    def test_generic_request_exception_mapped(self, mock_request):
        mock_request.side_effect = requests.exceptions.RequestException("weird")
        with self.assertRaises(PayNLError) as ctx:
            self.client.get_order("EX-1")
        self.assertIn("weird", str(ctx.exception))

    @patch("requests.Session.request")
    def test_400_with_error_key(self, mock_request):
        mock_request.return_value = MockResponse({"error": "bad thing"}, status_code=400)
        with self.assertRaises(PayNLError) as ctx:
            self.client.get_order("EX-1")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("bad thing", str(ctx.exception))


class TestTestConnectionErrorBranch(FrappeTestCase):
    @patch("requests.Session.request")
    def test_connection_generic_failure(self, mock_request):
        """A non-auth PayNLError surfaces as success=False with 'Connection failed'."""
        mock_request.return_value = MockResponse({"message": "boom"}, status_code=500)
        client = PayNLClient(settings=MockSettings())
        result = client.test_connection()
        self.assertFalse(result["success"])
        self.assertIn("Connection failed", result["message"])


class TestLogRequestDeveloperMode(FrappeTestCase):
    @patch("requests.Session.request")
    def test_log_request_runs_in_developer_mode(self, mock_request):
        """In developer_mode the debug logger path executes without raising."""
        mock_request.return_value = MockResponse({"id": "EX-1"})
        client = PayNLClient(settings=MockSettings())

        fake_logger = MagicMock()
        with patch.dict(frappe.conf, {"developer_mode": 1}):
            with patch("frappe.logger", return_value=fake_logger) as mock_logger:
                client.get_order("EX-1")
                # The paynl debug logger was obtained and called.
                mock_logger.assert_any_call("paynl", allow_site=True)
                self.assertTrue(fake_logger.debug.called)
                # The logged JSON carries the request method and status.
                logged = fake_logger.debug.call_args[0][0]
                payload = json.loads(logged)
                self.assertEqual(payload["method"], "GET")
                self.assertEqual(payload["status_code"], 200)


class TestGetClientFactory(FrappeTestCase):
    def test_get_client_returns_client_with_settings(self):
        settings = MockSettings()
        client = get_client(settings=settings)
        self.assertIsInstance(client, PayNLClient)
        self.assertIs(client._settings, settings)
