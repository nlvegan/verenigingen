# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for ING Checkout webhook handlers

Tests payment, mandate, and direct debit webhook processing including:
- Payload validation and parsing
- Reference parsing (new and legacy formats)
- Transaction creation and updates
- Error handling and logging
"""

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.ing_checkout.api.webhook import (
    _parse_reference,
    _process_direct_debit_webhook,
    _process_mandate_webhook,
    _process_payment_webhook,
)


class TestParseReference(FrappeTestCase):
    """Test reference parsing logic."""

    def test_new_format_sales_invoice(self):
        """Test new format: SINV:ACC-SINV-2025-00001."""
        with patch("frappe.db.exists", return_value=True):
            doctype, name = _parse_reference("SINV:ACC-SINV-2025-00001")
            self.assertEqual(doctype, "Sales Invoice")
            self.assertEqual(name, "ACC-SINV-2025-00001")

    def test_new_format_member(self):
        """Test new format: MEM:MEM-00001."""
        with patch("frappe.db.exists", return_value=True):
            doctype, name = _parse_reference("MEM:MEM-00001")
            self.assertEqual(doctype, "Member")
            self.assertEqual(name, "MEM-00001")

    def test_new_format_purchase_invoice(self):
        """Test new format: PINV:ACC-PINV-2025-00001."""
        with patch("frappe.db.exists", return_value=True):
            doctype, name = _parse_reference("PINV:ACC-PINV-2025-00001")
            self.assertEqual(doctype, "Purchase Invoice")
            self.assertEqual(name, "ACC-PINV-2025-00001")

    def test_new_format_document_not_found(self):
        """Test new format with non-existent document."""
        with patch("frappe.db.exists", return_value=False):
            doctype, name = _parse_reference("SINV:DOES-NOT-EXIST")
            self.assertIsNone(doctype)
            self.assertIsNone(name)

    def test_new_format_unknown_doctype_code(self):
        """Test new format with unknown doctype code falls through."""
        with patch("frappe.db.exists", return_value=False):
            doctype, name = _parse_reference("UNKNOWN:SOME-DOC")
            self.assertIsNone(doctype)
            self.assertIsNone(name)

    def test_legacy_format_direct_match(self):
        """Test legacy format: direct document name match."""
        with patch("frappe.db.exists") as mock_exists:
            # First call for Sales Invoice returns True
            mock_exists.return_value = True
            doctype, name = _parse_reference("ACC-SINV-2025-00001")
            self.assertEqual(doctype, "Sales Invoice")
            self.assertEqual(name, "ACC-SINV-2025-00001")

    def test_legacy_format_prefix_match(self):
        """Test legacy format: prefix-based match."""
        with patch("frappe.db.exists") as mock_exists:
            # Direct lookup fails, prefix lookup succeeds
            def exists_side_effect(doctype, name):
                if doctype == "Sales Invoice" and name == "SAL-INV-2025-00001":
                    return True
                return False

            mock_exists.side_effect = exists_side_effect
            doctype, name = _parse_reference("SAL-INV-2025-00001")
            self.assertEqual(doctype, "Sales Invoice")

    def test_empty_reference(self):
        """Test empty reference returns None."""
        doctype, name = _parse_reference("")
        self.assertIsNone(doctype)
        self.assertIsNone(name)

    def test_none_reference(self):
        """Test None reference returns None."""
        doctype, name = _parse_reference(None)
        self.assertIsNone(doctype)
        self.assertIsNone(name)

    def test_unmatched_reference(self):
        """Test unmatched reference returns None."""
        with patch("frappe.db.exists", return_value=False):
            doctype, name = _parse_reference("RANDOM-TEXT-12345")
            self.assertIsNone(doctype)
            self.assertIsNone(name)


class TestProcessPaymentWebhook(FrappeTestCase):
    """Test payment webhook processing."""

    def setUp(self):
        super().setUp()
        self.valid_payload = {
            "id": "EX-1234-5678-9012",
            "event": "status_changed",
            "type": "order",
            "object": {
                "id": "EX-1234-5678-9012",
                "reference": "SINV:ACC-SINV-2025-00001",
                "status": {"code": 100, "action": "PAID"},
                "amount": {"value": 2500, "currency": "EUR"},
                "payments": [
                    {
                        "customerMethod": {
                            "iban": "NL91ABNA0417164300",
                            "name": "Test Customer",
                        }
                    }
                ],
            },
        }

    @patch("verenigingen.verenigingen_payments.ing_checkout.api.webhook._parse_reference")
    @patch(
        "verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction.get_or_create_transaction"
    )
    def test_process_payment_webhook_success(self, mock_get_transaction, mock_parse):
        """Test successful payment webhook processing."""
        mock_parse.return_value = ("Sales Invoice", "ACC-SINV-2025-00001")

        mock_transaction = MagicMock()
        mock_transaction.name = "ING-TXN-00001"
        mock_transaction.status = "Paid"
        mock_transaction.payment_entry = "PE-00001"
        mock_get_transaction.return_value = mock_transaction

        result = _process_payment_webhook("EX-1234-5678-9012", self.valid_payload)

        self.assertEqual(result["transaction_name"], "ING-TXN-00001")
        self.assertEqual(result["status"], "Paid")
        self.assertEqual(result["reference_doctype"], "Sales Invoice")
        mock_transaction.update_from_webhook.assert_called_once_with(self.valid_payload)

    @patch("verenigingen.verenigingen_payments.ing_checkout.api.webhook._parse_reference")
    @patch(
        "verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction.get_or_create_transaction"
    )
    def test_process_payment_webhook_no_reference(self, mock_get_transaction, mock_parse):
        """Test payment webhook with unmatched reference."""
        mock_parse.return_value = (None, None)

        mock_transaction = MagicMock()
        mock_transaction.name = "ING-TXN-00002"
        mock_transaction.status = "Processing"
        mock_transaction.payment_entry = None
        mock_get_transaction.return_value = mock_transaction

        payload = {
            "id": "EX-5555-6666-7777",
            "object": {
                "reference": "UNKNOWN-REF",
                "amount": {"value": 1000, "currency": "EUR"},
            },
        }

        result = _process_payment_webhook("EX-5555-6666-7777", payload)

        # Should still process, just without linked document
        self.assertEqual(result["reference_doctype"], None)
        self.assertEqual(result["reference_name"], None)

    def test_amount_conversion_from_cents(self):
        """Test that amount is properly converted from cents to EUR."""
        with patch(
            "verenigingen.verenigingen_payments.ing_checkout.api.webhook._parse_reference",
            return_value=("Sales Invoice", "ACC-SINV-2025-00001"),
        ):
            with patch(
                "verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction.get_or_create_transaction"
            ) as mock_get:
                mock_transaction = MagicMock()
                mock_transaction.name = "ING-TXN-00003"
                mock_transaction.status = "Paid"
                mock_transaction.payment_entry = None
                mock_get.return_value = mock_transaction

                payload = {
                    "id": "EX-8888-9999-0000",
                    "object": {
                        "reference": "SINV:ACC-SINV-2025-00001",
                        "amount": {"value": 12345, "currency": "EUR"},  # 123.45 EUR
                    },
                }

                _process_payment_webhook("EX-8888-9999-0000", payload)

                # Check amount was converted from cents
                mock_get.assert_called_once()
                call_kwargs = mock_get.call_args[1]
                self.assertEqual(call_kwargs["amount"], 123.45)


class TestProcessMandateWebhook(FrappeTestCase):
    """Test mandate webhook processing."""

    def test_mandate_not_found(self):
        """Test handling of webhook for unknown mandate."""
        with patch("frappe.db.get_value", return_value=None):
            payload = {
                "id": "MANDATE-12345",
                "object": {"status": "active"},
            }

            result = _process_mandate_webhook("MANDATE-12345", payload)

            self.assertTrue(result["handled"])
            self.assertEqual(result["action"], "logged")
            self.assertEqual(result["reason"], "mandate_not_found")

    @patch("frappe.db.get_value")
    @patch("frappe.get_doc")
    def test_mandate_status_update(self, mock_get_doc, mock_get_value):
        """Test successful mandate status update."""
        mock_get_value.return_value = "ING-MANDATE-00001"

        mock_mandate = MagicMock()
        mock_mandate.status = "Pending"
        mock_get_doc.return_value = mock_mandate

        with patch(
            "verenigingen.verenigingen_payments.doctype.ing_checkout_mandate.ing_checkout_mandate.MANDATE_STATUS_MAP",
            {"active": "Active"},
        ):
            payload = {
                "id": "MANDATE-12345",
                "object": {"status": "active"},
            }

            result = _process_mandate_webhook("MANDATE-12345", payload)

            self.assertTrue(result["handled"])
            self.assertEqual(result["action"], "status_updated")
            self.assertEqual(result["old_status"], "Pending")
            # Webhook user has write permission on ING Checkout Mandate
            mock_mandate.save.assert_called_once_with()

    @patch("frappe.db.get_value")
    @patch("frappe.get_doc")
    def test_mandate_unknown_status(self, mock_get_doc, mock_get_value):
        """Test mandate webhook with unknown status."""
        mock_get_value.return_value = "ING-MANDATE-00001"

        with patch(
            "verenigingen.verenigingen_payments.doctype.ing_checkout_mandate.ing_checkout_mandate.MANDATE_STATUS_MAP",
            {},
        ):
            payload = {
                "id": "MANDATE-12345",
                "object": {"status": "weird_status"},
            }

            result = _process_mandate_webhook("MANDATE-12345", payload)

            self.assertTrue(result["handled"])
            self.assertEqual(result["action"], "logged")
            self.assertEqual(result["reason"], "unknown_status")


class TestProcessDirectDebitWebhook(FrappeTestCase):
    """Test direct debit webhook processing."""

    def test_transaction_not_found(self):
        """Test handling of webhook for unknown transaction."""
        with patch("frappe.db.get_value", return_value=None):
            payload = {
                "id": "DEBIT-12345",
                "object": {"status": "completed"},
            }

            result = _process_direct_debit_webhook("DEBIT-12345", payload)

            self.assertTrue(result["handled"])
            self.assertEqual(result["action"], "logged")
            self.assertEqual(result["reason"], "transaction_not_found")

    @patch("frappe.db.get_value")
    @patch("frappe.get_doc")
    def test_transaction_update(self, mock_get_doc, mock_get_value):
        """Test successful transaction update."""
        mock_get_value.return_value = "ING-TXN-00001"

        mock_transaction = MagicMock()
        mock_transaction.name = "ING-TXN-00001"
        mock_transaction.status = "Paid"
        mock_get_doc.return_value = mock_transaction

        payload = {
            "id": "DEBIT-12345",
            "object": {"status": "completed"},
        }

        result = _process_direct_debit_webhook("DEBIT-12345", payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["action"], "transaction_updated")
        self.assertEqual(result["transaction_name"], "ING-TXN-00001")
        mock_transaction.update_from_webhook.assert_called_once_with(payload)


# Note: Endpoint-level tests (handle_payment, handle_mandate, handle_direct_debit)
# are omitted because frappe.request is a Werkzeug LocalProxy that cannot be
# easily mocked in unit tests. The internal processing functions (_process_*_webhook)
# provide complete coverage of the webhook processing logic.
