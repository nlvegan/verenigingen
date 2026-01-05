# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for PayNLClient

These tests use mocked HTTP responses to test the client logic
without making actual API calls.
"""

import base64
import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.ing_checkout.client import (
    PayNLAuthenticationError,
    PayNLClient,
    PayNLError,
    PayNLValidationError,
)


class MockSettings:
    """Mock INGCheckoutSettings for testing."""

    def __init__(
        self,
        enabled=True,
        sandbox_mode=True,
        service_id="SL-1234-5678",
        token_code="AT-1234-5678",
        api_token="test_api_token_40_characters_long_xxxxx",
    ):
        self.enabled = enabled
        self.sandbox_mode = sandbox_mode
        self.service_id = service_id
        self.token_code = token_code
        self._api_token = api_token

    def get_api_credentials(self):
        if not self.enabled:
            raise frappe.ValidationError("ING Checkout integration is not enabled")
        return {
            "token_code": self.token_code,
            "api_token": self._api_token,
            "service_id": self.service_id,
            "sandbox_mode": self.sandbox_mode,
        }

    def get_password(self, fieldname):
        if fieldname == "api_token":
            return self._api_token
        return None


class MockResponse:
    """Mock requests.Response for testing."""

    def __init__(self, json_data, status_code=200, text=None):
        self._json_data = json_data
        self.status_code = status_code
        self.text = text or json.dumps(json_data)

    def json(self):
        return self._json_data


class TestPayNLClientAuthentication(FrappeTestCase):
    """Test client authentication setup."""

    def test_basic_auth_header_format(self):
        """Test that Basic Auth header is correctly formatted."""
        settings = MockSettings()
        client = PayNLClient(settings=settings)

        # Access session to trigger auth setup
        session = client.session

        auth_header = session.headers.get("Authorization")
        self.assertIsNotNone(auth_header)
        self.assertTrue(auth_header.startswith("Basic "))

        # Decode and verify credentials
        encoded_part = auth_header.replace("Basic ", "")
        decoded = base64.b64decode(encoded_part).decode("utf-8")
        expected = f"{settings.token_code}:{settings._api_token}"
        self.assertEqual(decoded, expected)

    def test_session_headers(self):
        """Test that session has correct headers."""
        settings = MockSettings()
        client = PayNLClient(settings=settings)

        session = client.session

        self.assertEqual(session.headers.get("Content-Type"), "application/json")
        self.assertEqual(session.headers.get("Accept"), "application/json")
        self.assertIn("Verenigingen", session.headers.get("User-Agent", ""))


class TestPayNLClientOrderAPI(FrappeTestCase):
    """Test Order API methods."""

    def setUp(self):
        super().setUp()
        self.settings = MockSettings()
        self.client = PayNLClient(settings=self.settings)

    @patch("requests.Session.request")
    def test_create_order_success(self, mock_request):
        """Test successful order creation."""
        mock_response = MockResponse(
            {
                "id": "EX-1234-5678-9012",
                "status": "pending",
                "links": {
                    "redirect": "https://connect.pay.nl/checkout/abc123",
                    "status": "https://rest.pay.nl/v2/orders/EX-1234-5678-9012",
                },
            }
        )
        mock_request.return_value = mock_response

        order_data = {
            "serviceId": "SL-1234-5678",
            "amount": {"value": 2500, "currency": "EUR"},
            "description": "Test payment",
            "reference": "TEST-001",
            "returnUrl": "https://example.com/thanks",
            "exchangeUrl": "https://example.com/webhook",
            "paymentMethod": {"id": 10},
        }

        result = self.client.create_order(order_data)

        self.assertEqual(result["id"], "EX-1234-5678-9012")
        self.assertEqual(result["status"], "pending")
        self.assertIn("redirect", result["links"])

        # Verify the request was made correctly
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        self.assertEqual(call_args.kwargs["method"], "POST")
        self.assertIn("/v3/orders", call_args.kwargs["url"])
        self.assertEqual(call_args.kwargs["json"], order_data)

    @patch("requests.Session.request")
    def test_create_order_validation_error(self, mock_request):
        """Test order creation with validation error."""
        mock_response = MockResponse(
            {
                "message": "Validation failed",
                "violations": [{"propertyPath": "amount.value", "message": "must be greater than 0"}],
            },
            status_code=422,
        )
        mock_request.return_value = mock_response

        with self.assertRaises(PayNLValidationError) as context:
            self.client.create_order({"invalid": "data"})

        self.assertIn("amount.value", str(context.exception))
        self.assertEqual(context.exception.status_code, 422)

    @patch("requests.Session.request")
    def test_get_order_success(self, mock_request):
        """Test getting order details."""
        mock_response = MockResponse(
            {
                "id": "EX-1234-5678-9012",
                "reference": "TEST-001",
                "status": {"code": 100, "action": "PAID"},
                "amount": {"value": 2500, "currency": "EUR"},
                "payments": [
                    {
                        "paymentMethod": {"id": 10, "name": "iDEAL"},
                        "customerMethod": {
                            "iban": "NL91INGB0001234567",
                            "name": "J. de Vries",
                            "bic": "INGBNL2A",
                        },
                    }
                ],
            }
        )
        mock_request.return_value = mock_response

        result = self.client.get_order("EX-1234-5678-9012")

        self.assertEqual(result["status"]["code"], 100)
        self.assertEqual(result["status"]["action"], "PAID")
        self.assertEqual(result["payments"][0]["customerMethod"]["iban"], "NL91INGB0001234567")


class TestPayNLClientMandateAPI(FrappeTestCase):
    """Test SEPA Direct Debit Mandate API methods."""

    def setUp(self):
        super().setUp()
        self.settings = MockSettings()
        self.client = PayNLClient(settings=self.settings)

    @patch("requests.Session.request")
    def test_create_mandate_success(self, mock_request):
        """Test successful mandate creation."""
        mock_response = MockResponse(
            {
                "mandateId": "IO-1234-5678-9012",
                "status": "pending",
                "objectCode": "IO-1234-5678-9012",
            }
        )
        mock_request.return_value = mock_response

        mandate_data = {
            "serviceId": "SL-1234-5678",
            "type": "flexible",
            "amount": {"value": 2500, "currency": "EUR"},
            "description": "Contributie",
            "debtor": {
                "iban": "NL91INGB0001234567",
                "name": "J. de Vries",
                "email": "test@example.com",
            },
            "termsAndConditionsUrl": "https://example.com/terms",
            "exchangeUrl": "https://example.com/webhook",
        }

        result = self.client.create_mandate(mandate_data)

        self.assertEqual(result["mandateId"], "IO-1234-5678-9012")
        self.assertEqual(result["status"], "pending")

        # Verify request URL uses GMS endpoint
        call_args = mock_request.call_args
        self.assertIn("rest.pay.nl", call_args.kwargs["url"])
        self.assertIn("/v2/directdebits/mandates", call_args.kwargs["url"])

    @patch("requests.Session.request")
    def test_create_direct_debit_success(self, mock_request):
        """Test successful direct debit execution."""
        mock_response = MockResponse(
            {
                "referenceId": "IL-1234-5678-9012",
                "status": "pending",
            }
        )
        mock_request.return_value = mock_response

        debit_data = {
            "mandateId": "IO-1234-5678-9012",
            "amount": {"value": 2500, "currency": "EUR"},
            "description": "Contributie Q1 2025",
            "processDate": "2025-01-15",
        }

        result = self.client.create_direct_debit(debit_data)

        self.assertEqual(result["referenceId"], "IL-1234-5678-9012")


class TestPayNLClientErrorHandling(FrappeTestCase):
    """Test error handling."""

    def setUp(self):
        super().setUp()
        self.settings = MockSettings()
        self.client = PayNLClient(settings=self.settings)

    @patch("requests.Session.request")
    def test_authentication_error_401(self, mock_request):
        """Test 401 authentication error handling."""
        mock_response = MockResponse(
            {"message": "Invalid credentials"},
            status_code=401,
        )
        mock_request.return_value = mock_response

        with self.assertRaises(PayNLAuthenticationError) as context:
            self.client.get_order("EX-1234")

        self.assertEqual(context.exception.status_code, 401)

    @patch("requests.Session.request")
    def test_authentication_error_403(self, mock_request):
        """Test 403 access denied error handling."""
        mock_response = MockResponse(
            {"message": "Access denied"},
            status_code=403,
        )
        mock_request.return_value = mock_response

        with self.assertRaises(PayNLAuthenticationError) as context:
            self.client.get_order("EX-1234")

        self.assertEqual(context.exception.status_code, 403)

    @patch("requests.Session.request")
    def test_generic_error_500(self, mock_request):
        """Test 500 server error handling."""
        mock_response = MockResponse(
            {"message": "Internal server error"},
            status_code=500,
        )
        mock_request.return_value = mock_response

        with self.assertRaises(PayNLError) as context:
            self.client.get_order("EX-1234")

        self.assertEqual(context.exception.status_code, 500)

    @patch("requests.Session.request")
    def test_connection_timeout(self, mock_request):
        """Test connection timeout handling."""
        import requests

        mock_request.side_effect = requests.exceptions.Timeout("Connection timed out")

        with self.assertRaises(PayNLError) as context:
            self.client.get_order("EX-1234")

        self.assertIn("timed out", str(context.exception).lower())

    @patch("requests.Session.request")
    def test_connection_error(self, mock_request):
        """Test connection error handling."""
        import requests

        mock_request.side_effect = requests.exceptions.ConnectionError("Connection refused")

        with self.assertRaises(PayNLError) as context:
            self.client.get_order("EX-1234")

        self.assertIn("connect", str(context.exception).lower())


class TestPayNLClientTestConnection(FrappeTestCase):
    """Test the test_connection method."""

    def setUp(self):
        super().setUp()
        self.settings = MockSettings()
        self.client = PayNLClient(settings=self.settings)

    @patch("requests.Session.request")
    def test_connection_success(self, mock_request):
        """Test successful connection test."""
        mock_response = MockResponse(
            {
                "name": "Test Service",
                "id": "SL-1234-5678",
            }
        )
        mock_request.return_value = mock_response

        result = self.client.test_connection()

        self.assertTrue(result["success"])
        self.assertEqual(result["service_name"], "Test Service")

    @patch("requests.Session.request")
    def test_connection_auth_failure(self, mock_request):
        """Test connection test with auth failure."""
        mock_response = MockResponse(
            {"message": "Invalid credentials"},
            status_code=401,
        )
        mock_request.return_value = mock_response

        result = self.client.test_connection()

        self.assertFalse(result["success"])
        self.assertIn("Authentication failed", result["message"])
