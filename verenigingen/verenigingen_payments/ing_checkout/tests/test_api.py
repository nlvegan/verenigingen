# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for ING Checkout API endpoints

Tests the whitelisted API methods for payment initiation and status checking.
"""

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.ing_checkout.api import payment


class MockSettings:
    """Mock INGCheckoutSettings for testing."""

    def __init__(self):
        self.enabled = True
        self.sandbox_mode = True
        self.service_id = "SL-1234-5678"
        self.token_code = "AT-1234-5678"
        self._api_token = "test_api_token_40_characters_long_xxxxx"
        self.default_return_url = "https://example.com/thanks"
        self.terms_and_conditions_url = "https://example.com/terms"

    def get_api_credentials(self):
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


class TestCreateIdealPayment(FrappeTestCase):
    """Test create_ideal_payment API endpoint."""

    def setUp(self):
        super().setUp()
        # Create a test Sales Invoice for reference
        self.test_customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "Test ING Checkout Customer",
                "customer_type": "Individual",
            }
        )
        if not frappe.db.exists("Customer", self.test_customer.customer_name):
            self.test_customer.insert(ignore_permissions=True)

    def tearDown(self):
        # Clean up test data
        if frappe.db.exists("Customer", "Test ING Checkout Customer"):
            frappe.delete_doc("Customer", "Test ING Checkout Customer", force=True)
        super().tearDown()

    @patch("verenigingen.verenigingen_payments.ing_checkout.client.get_client")
    def test_create_payment_success(self, mock_get_client):
        """Test successful iDEAL payment creation."""
        # Setup mock client
        mock_client = MagicMock()
        mock_client.create_order.return_value = {
            "id": "EX-1234-5678-9012",
            "status": "pending",
            "links": {
                "redirect": "https://connect.pay.nl/checkout/abc123",
            },
        }
        # Mock the settings on the client
        mock_client.settings = MockSettings()
        mock_get_client.return_value = mock_client

        # Also mock the local import of get_client
        with patch.object(payment, "get_client", return_value=mock_client):
            # And mock get_ing_checkout_settings which is imported inside the function
            with patch(
                "verenigingen.verenigingen_payments.doctype.ing_checkout_settings.ing_checkout_settings.get_ing_checkout_settings",
                return_value=MockSettings(),
            ):
                result = payment.create_ideal_payment(
                    reference_doctype="Customer",
                    reference_name="Test ING Checkout Customer",
                    amount=25.00,
                    description="Test payment",
                )

        self.assertTrue(result["success"])
        self.assertEqual(result["transaction_id"], "EX-1234-5678-9012")
        self.assertEqual(result["redirect_url"], "https://connect.pay.nl/checkout/abc123")

        # Verify client was called with correct data
        mock_client.create_order.assert_called_once()
        call_args = mock_client.create_order.call_args[0][0]
        self.assertEqual(call_args["amount"]["value"], 2500)  # Converted to cents
        self.assertEqual(call_args["amount"]["currency"], "EUR")
        self.assertEqual(call_args["paymentMethod"]["id"], 10)  # iDEAL

    @patch("verenigingen.verenigingen_payments.ing_checkout.client.get_client")
    def test_create_payment_description_truncated(self, mock_get_client):
        """Test that description is truncated to 30 characters."""
        mock_client = MagicMock()
        mock_client.create_order.return_value = {
            "id": "EX-1234-5678-9012",
            "links": {"redirect": "https://example.com"},
        }
        mock_client.settings = MockSettings()
        mock_get_client.return_value = mock_client

        long_description = "This is a very long description that exceeds thirty characters"

        with patch.object(payment, "get_client", return_value=mock_client):
            with patch(
                "verenigingen.verenigingen_payments.doctype.ing_checkout_settings.ing_checkout_settings.get_ing_checkout_settings",
                return_value=MockSettings(),
            ):
                result = payment.create_ideal_payment(
                    reference_doctype="Customer",
                    reference_name="Test ING Checkout Customer",
                    amount=25.00,
                    description=long_description,
                )

        # Verify description was truncated
        call_args = mock_client.create_order.call_args[0][0]
        self.assertEqual(len(call_args["description"]), 30)
        self.assertEqual(call_args["description"], long_description[:30])

    def test_create_payment_invalid_amount(self):
        """Test that invalid amount raises error."""
        result = payment.create_ideal_payment(
            reference_doctype="Customer",
            reference_name="Test ING Checkout Customer",
            amount=0,
            description="Test",
        )

        self.assertFalse(result["success"])

    def test_create_payment_missing_reference(self):
        """Test that missing reference raises error."""
        result = payment.create_ideal_payment(
            reference_doctype="Customer",
            reference_name="NonExistent Customer",
            amount=25.00,
            description="Test",
        )

        self.assertFalse(result["success"])


class TestGetPaymentStatus(FrappeTestCase):
    """Test get_payment_status API endpoint."""

    @patch("verenigingen.verenigingen_payments.ing_checkout.api.payment.get_client")
    def test_get_status_paid(self, mock_get_client):
        """Test getting status of paid order."""
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "id": "EX-1234-5678-9012",
            "status": {"code": 100, "action": "PAID"},
            "payments": [
                {
                    "customerMethod": {
                        "iban": "NL91INGB0001234567",
                        "name": "J. de Vries",
                    }
                }
            ],
        }
        mock_get_client.return_value = mock_client

        result = payment.get_payment_status("EX-1234-5678-9012")

        self.assertTrue(result["success"])
        self.assertTrue(result["paid"])
        self.assertEqual(result["status_code"], 100)
        self.assertEqual(result["status_action"], "PAID")
        self.assertEqual(result["customer_iban"], "NL91INGB0001234567")
        self.assertEqual(result["customer_name"], "J. de Vries")

    @patch("verenigingen.verenigingen_payments.ing_checkout.api.payment.get_client")
    def test_get_status_pending(self, mock_get_client):
        """Test getting status of pending order."""
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "id": "EX-1234-5678-9012",
            "status": {"code": 20, "action": "PENDING"},
            "payments": [],
        }
        mock_get_client.return_value = mock_client

        result = payment.get_payment_status("EX-1234-5678-9012")

        self.assertTrue(result["success"])
        self.assertFalse(result["paid"])
        self.assertEqual(result["status_code"], 20)
        self.assertEqual(result["status_action"], "PENDING")

    @patch("verenigingen.verenigingen_payments.ing_checkout.api.payment.get_client")
    def test_get_status_cancelled(self, mock_get_client):
        """Test getting status of cancelled order."""
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "id": "EX-1234-5678-9012",
            "status": {"code": -90, "action": "CANCELLED"},
            "payments": [],
        }
        mock_get_client.return_value = mock_client

        result = payment.get_payment_status("EX-1234-5678-9012")

        self.assertTrue(result["success"])
        self.assertFalse(result["paid"])
        self.assertEqual(result["status_code"], -90)
        self.assertEqual(result["status_action"], "CANCELLED")

    def test_get_status_missing_id(self):
        """Test that missing transaction ID raises error."""
        result = payment.get_payment_status("")

        self.assertFalse(result["success"])


class TestTestConnection(FrappeTestCase):
    """Test test_connection API endpoint."""

    @patch("verenigingen.verenigingen_payments.ing_checkout.api.payment.get_client")
    def test_connection_success(self, mock_get_client):
        """Test successful connection test."""
        mock_client = MagicMock()
        mock_client.test_connection.return_value = {
            "success": True,
            "message": "Connection successful",
            "service_name": "Test Service",
        }
        mock_get_client.return_value = mock_client

        result = payment.test_connection()

        self.assertTrue(result["success"])
        self.assertEqual(result["service_name"], "Test Service")

    @patch("verenigingen.verenigingen_payments.ing_checkout.api.payment.get_client")
    def test_connection_failure(self, mock_get_client):
        """Test connection test failure."""
        mock_client = MagicMock()
        mock_client.test_connection.return_value = {
            "success": False,
            "message": "Authentication failed",
        }
        mock_get_client.return_value = mock_client

        result = payment.test_connection()

        self.assertFalse(result["success"])
        self.assertIn("failed", result["message"].lower())
