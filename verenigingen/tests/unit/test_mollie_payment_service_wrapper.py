"""
Unit tests for the Mollie Payment Service Compatibility Wrapper.

These tests verify that the compatibility wrapper properly delegates to the
new service layer while maintaining backward compatibility.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase


class TestMolliePaymentServiceWrapper(IntegrationTestCase):
    """Test the MolliePaymentService compatibility wrapper."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ensure we have a clean test environment
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test fixtures."""
        self.mock_complete_service = MagicMock()

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    def test_init_creates_complete_service(self, mock_complete_service_class):
        """Test that __init__ creates CompletePaymentService instance."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )

        service = MolliePaymentService()

        mock_complete_service_class.assert_called_once()
        self.assertIsNotNone(service._complete_service)

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    def test_create_single_payment_delegates_to_complete_service(
        self, mock_complete_service_class
    ):
        """Test that create_single_payment delegates to CompletePaymentService."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )

        mock_complete_service = MagicMock()
        mock_complete_service.create_donation_payment.return_value = {
            "status": "redirect_required",
            "payment_id": "tr_test123",
        }
        mock_complete_service_class.return_value = mock_complete_service

        service = MolliePaymentService()
        mock_donation_doc = MagicMock()
        mock_donation_doc.name = "DON-00001"
        form_data = {"amount": "25.00", "currency": "EUR", "return_url": "https://example.com"}

        result = service.create_single_payment(mock_donation_doc, form_data)

        mock_complete_service.create_donation_payment.assert_called_once_with(
            mock_donation_doc, form_data
        )
        self.assertEqual(result["status"], "redirect_required")
        self.assertEqual(result["payment_id"], "tr_test123")

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    @patch("verenigingen.utils.payment_services.mollie_payment_service.frappe")
    def test_create_payment_with_donation_reference(
        self, mock_frappe, mock_complete_service_class
    ):
        """Test create_payment loads donation doc when reference provided."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )

        mock_donation_doc = MagicMock()
        mock_donation_doc.name = "DON-00001"
        mock_frappe.get_doc.return_value = mock_donation_doc

        mock_complete_service = MagicMock()
        mock_complete_service.create_donation_payment.return_value = {
            "status": "redirect_required",
            "payment_id": "tr_test123",
        }
        mock_complete_service_class.return_value = mock_complete_service

        service = MolliePaymentService()
        payment_data = {
            "donation": "DON-00001",
            "amount": "25.00",
            "currency": "EUR",
            "return_url": "https://example.com",
        }

        result = service.create_payment(payment_data)

        mock_frappe.get_doc.assert_called_once_with("Donation", "DON-00001")
        mock_complete_service.create_donation_payment.assert_called_once()
        # Verify donation/donation_name is excluded from form_data
        call_args = mock_complete_service.create_donation_payment.call_args
        form_data_passed = call_args[0][1]
        self.assertNotIn("donation", form_data_passed)
        self.assertEqual(result["status"], "redirect_required")

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    @patch("verenigingen.utils.payment_services.mollie_payment_service.frappe")
    def test_create_payment_without_donation_reference_returns_error(
        self, mock_frappe, mock_complete_service_class
    ):
        """Test create_payment returns error when no donation reference provided."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )

        service = MolliePaymentService()
        payment_data = {
            "amount": "25.00",
            "currency": "EUR",
            "return_url": "https://example.com",
        }

        result = service.create_payment(payment_data)

        self.assertEqual(result["status"], "error")
        self.assertIn("donation reference is required", result["message"].lower())

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    @patch("verenigingen.utils.payment_services.mollie_payment_service.frappe")
    def test_create_payment_with_nonexistent_donation_returns_error(
        self, mock_frappe, mock_complete_service_class
    ):
        """Test create_payment returns error when donation doesn't exist."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )

        mock_frappe.get_doc.side_effect = frappe.DoesNotExistError
        mock_frappe.DoesNotExistError = frappe.DoesNotExistError
        mock_frappe.log_error = MagicMock()

        service = MolliePaymentService()
        payment_data = {"donation": "NONEXISTENT-DON"}

        result = service.create_payment(payment_data)

        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["message"].lower())

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    def test_process_webhook_extracts_payment_id_and_delegates(
        self, mock_complete_service_class
    ):
        """Test process_webhook extracts payment_id and calls correct method."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )

        mock_complete_service = MagicMock()
        mock_complete_service.process_webhook.return_value = {
            "status": "success",
            "payment_status": "paid",
        }
        mock_complete_service_class.return_value = mock_complete_service

        service = MolliePaymentService()
        webhook_data = {"id": "tr_test123", "status": "paid"}

        result = service.process_webhook(webhook_data)

        mock_complete_service.process_webhook.assert_called_once_with(
            "tr_test123", webhook_data
        )
        self.assertEqual(result["status"], "success")

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    def test_process_webhook_handles_payment_id_key(self, mock_complete_service_class):
        """Test process_webhook handles 'payment_id' key as alternative to 'id'."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )

        mock_complete_service = MagicMock()
        mock_complete_service.process_webhook.return_value = {"status": "success"}
        mock_complete_service_class.return_value = mock_complete_service

        service = MolliePaymentService()
        webhook_data = {"payment_id": "tr_test456"}

        result = service.process_webhook(webhook_data)

        mock_complete_service.process_webhook.assert_called_once_with(
            "tr_test456", webhook_data
        )

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    @patch("verenigingen.utils.payment_services.mollie_payment_service.frappe")
    def test_process_webhook_returns_error_when_no_payment_id(
        self, mock_frappe, mock_complete_service_class
    ):
        """Test process_webhook returns error when payment ID is missing."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )

        mock_frappe.log_error = MagicMock()

        service = MolliePaymentService()
        webhook_data = {"status": "paid"}  # No id or payment_id

        result = service.process_webhook(webhook_data)

        self.assertEqual(result["status"], "error")
        self.assertIn("payment id", result["message"].lower())
        mock_frappe.log_error.assert_called()

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    def test_get_payment_delegates_to_client(self, mock_complete_service_class):
        """Test get_payment delegates to client."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )

        mock_payment = MagicMock()
        mock_payment.id = "tr_test123"
        mock_payment.status = "paid"

        mock_complete_service = MagicMock()
        mock_complete_service.client.get_payment.return_value = mock_payment
        mock_complete_service_class.return_value = mock_complete_service

        service = MolliePaymentService()
        result = service.get_payment("tr_test123")

        mock_complete_service.client.get_payment.assert_called_once_with("tr_test123")
        self.assertEqual(result.id, "tr_test123")

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    def test_create_refund_with_valid_data(self, mock_complete_service_class):
        """Test create_refund with valid payment ID and amount."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )

        mock_refund = MagicMock()
        mock_refund.id = "re_test123"

        mock_complete_service = MagicMock()
        mock_complete_service.client.create_refund.return_value = mock_refund
        mock_complete_service_class.return_value = mock_complete_service

        service = MolliePaymentService()
        result = service.create_refund("tr_test123", 25.00, "Test refund")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["refund_id"], "re_test123")
        self.assertEqual(result["amount"], 25.00)
        self.assertEqual(result["payment_id"], "tr_test123")

        # Verify refund data format
        call_args = mock_complete_service.client.create_refund.call_args
        refund_data = call_args[0][1]
        self.assertEqual(refund_data["amount"]["currency"], "EUR")
        self.assertEqual(refund_data["amount"]["value"], "25.00")
        self.assertEqual(refund_data["description"], "Test refund")

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    def test_create_refund_without_payment_id_returns_error(
        self, mock_complete_service_class
    ):
        """Test create_refund returns error when payment ID is empty."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )

        service = MolliePaymentService()
        result = service.create_refund("", 25.00)

        self.assertEqual(result["status"], "error")
        self.assertIn("required", result["message"].lower())

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    def test_create_refund_with_zero_amount_returns_error(
        self, mock_complete_service_class
    ):
        """Test create_refund returns error when amount is zero or negative."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )

        service = MolliePaymentService()

        # Test zero amount
        result = service.create_refund("tr_test123", 0)
        self.assertEqual(result["status"], "error")
        self.assertIn("positive", result["message"].lower())

        # Test negative amount
        result = service.create_refund("tr_test123", -10.00)
        self.assertEqual(result["status"], "error")
        self.assertIn("positive", result["message"].lower())

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    @patch("verenigingen.utils.payment_services.mollie_payment_service.frappe")
    def test_create_refund_handles_validation_error(
        self, mock_frappe, mock_complete_service_class
    ):
        """Test create_refund handles MollieValidationError properly."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )
        from verenigingen.verenigingen_payments.mollie.exceptions import (
            MollieValidationError,
        )

        mock_frappe.log_error = MagicMock()

        mock_complete_service = MagicMock()
        mock_complete_service.client.create_refund.side_effect = MollieValidationError(
            "Amount exceeds available balance"
        )
        mock_complete_service_class.return_value = mock_complete_service

        service = MolliePaymentService()
        result = service.create_refund("tr_test123", 1000.00)

        self.assertEqual(result["status"], "error")
        self.assertIn("invalid", result["message"].lower())
        mock_frappe.log_error.assert_called()

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.CompletePaymentService"
    )
    @patch("verenigingen.utils.payment_services.mollie_payment_service.frappe")
    def test_create_refund_handles_api_error(
        self, mock_frappe, mock_complete_service_class
    ):
        """Test create_refund handles MollieAPIError properly."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            MolliePaymentService,
        )
        from verenigingen.verenigingen_payments.mollie.exceptions import MollieAPIError

        mock_frappe.log_error = MagicMock()

        mock_complete_service = MagicMock()
        mock_complete_service.client.create_refund.side_effect = MollieAPIError(
            "API rate limit exceeded"
        )
        mock_complete_service_class.return_value = mock_complete_service

        service = MolliePaymentService()
        result = service.create_refund("tr_test123", 25.00)

        self.assertEqual(result["status"], "error")
        self.assertIn("provider", result["message"].lower())
        mock_frappe.log_error.assert_called()


class TestProcessMolliePaymentFunction(IntegrationTestCase):
    """Test the process_mollie_payment standalone function."""

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.MolliePaymentService"
    )
    def test_process_mollie_payment_creates_service_and_calls_create_payment(
        self, mock_service_class
    ):
        """Test that process_mollie_payment delegates to MolliePaymentService."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            process_mollie_payment,
        )

        mock_service = MagicMock()
        mock_service.create_payment.return_value = {
            "status": "redirect_required",
            "payment_id": "tr_test123",
        }
        mock_service_class.return_value = mock_service

        payment_data = {"donation": "DON-00001", "amount": "25.00"}
        result = process_mollie_payment(payment_data)

        mock_service_class.assert_called_once()
        mock_service.create_payment.assert_called_once_with(payment_data)
        self.assertEqual(result["status"], "redirect_required")

    @patch(
        "verenigingen.utils.payment_services.mollie_payment_service.MolliePaymentService"
    )
    @patch("verenigingen.utils.payment_services.mollie_payment_service.frappe")
    def test_process_mollie_payment_handles_exception(
        self, mock_frappe, mock_service_class
    ):
        """Test that process_mollie_payment handles exceptions gracefully."""
        from verenigingen.utils.payment_services.mollie_payment_service import (
            process_mollie_payment,
        )

        mock_frappe.log_error = MagicMock()

        mock_service_class.side_effect = Exception("Service initialization failed")

        payment_data = {"donation": "DON-00001"}
        result = process_mollie_payment(payment_data)

        self.assertEqual(result["status"], "error")
        self.assertIn("Service initialization failed", result["message"])
        mock_frappe.log_error.assert_called()


if __name__ == "__main__":
    unittest.main()
