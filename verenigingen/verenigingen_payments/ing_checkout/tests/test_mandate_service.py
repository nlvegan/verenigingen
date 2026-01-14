# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for MandateService.

Tests the business logic for ING Checkout SEPA Direct Debit mandate management.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase


class TestMandateService(IntegrationTestCase):
    """Test cases for MandateService."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test fixtures for each test."""
        super().setUp()
        # Create mock settings
        self.mock_settings = {
            "service_id": "SL-1234-5678",
            "terms_and_conditions_url": "https://example.com/terms",
        }

    # -------------------------------------------------------------------------
    # create_mandate_for_member Tests
    # -------------------------------------------------------------------------

    @patch(
        "verenigingen.verenigingen_payments.ing_checkout.services.mandate_service.MandateService.settings",
        new_callable=lambda: property(lambda self: {"service_id": "SL-1234", "terms_and_conditions_url": "/terms"}),
    )
    @patch(
        "verenigingen.verenigingen_payments.ing_checkout.services.mandate_service.MandateService.client"
    )
    def test_create_mandate_for_member_success(self, mock_client_prop, mock_settings):
        """Test successful mandate creation for member."""
        from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

        # Mock member and SEPA mandate
        mock_member = MagicMock()
        mock_member.name = "MEM-00001"
        mock_member.full_name = "Test Member"
        mock_member.email = "test@example.com"
        mock_member.sepa_mandate = "SEPA-00001"

        mock_sepa = MagicMock()
        mock_sepa.name = "SEPA-00001"
        mock_sepa.iban = "NL91ABNA0417164300"
        mock_sepa.account_holder_name = "Test Member"
        mock_sepa.status = "Active"

        with patch("frappe.get_doc") as mock_get_doc:

            def get_doc_side_effect(doctype, name=None):
                if doctype == "Member":
                    return mock_member
                if doctype == "SEPA Mandate":
                    return mock_sepa
                return MagicMock()

            mock_get_doc.side_effect = get_doc_side_effect

            # Mock Pay.nl client response
            mock_client = MagicMock()
            mock_client.create_mandate.return_value = {
                "mandateId": "MD-123456789",
                "status": "pending",
            }

            service = MandateService()
            service._client = mock_client
            service._settings = self.mock_settings

            # Mock get_or_create_mandate
            with patch(
                "verenigingen.verenigingen_payments.doctype.ing_checkout_mandate.ing_checkout_mandate.get_or_create_mandate"
            ) as mock_create:
                mock_mandate_doc = MagicMock()
                mock_mandate_doc.name = "ING-MAND-00001"
                mock_mandate_doc.status = "Pending"
                mock_create.return_value = mock_mandate_doc

                result = service.create_mandate_for_member("MEM-00001")

                self.assertTrue(result["success"])
                self.assertEqual(result["mandate_id"], "MD-123456789")
                mock_client.create_mandate.assert_called_once()

    @patch(
        "verenigingen.verenigingen_payments.ing_checkout.services.mandate_service.MandateService.client"
    )
    def test_create_mandate_for_member_no_sepa_mandate(self, mock_client):
        """Test mandate creation fails when member has no SEPA mandate."""
        from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

        # Mock member without SEPA mandate
        mock_member = MagicMock()
        mock_member.name = "MEM-00001"
        mock_member.sepa_mandate = None

        with patch("frappe.get_doc", return_value=mock_member):
            service = MandateService()
            service._settings = self.mock_settings

            result = service.create_mandate_for_member("MEM-00001")

            self.assertFalse(result["success"])
            self.assertIn("no active SEPA mandate", result["error"].lower())

    @patch(
        "verenigingen.verenigingen_payments.ing_checkout.services.mandate_service.MandateService.client"
    )
    def test_create_mandate_for_member_inactive_sepa_mandate(self, mock_client):
        """Test mandate creation fails when SEPA mandate is inactive."""
        from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

        # Mock member with inactive SEPA mandate
        mock_member = MagicMock()
        mock_member.name = "MEM-00001"
        mock_member.sepa_mandate = "SEPA-00001"

        mock_sepa = MagicMock()
        mock_sepa.status = "Cancelled"
        mock_sepa.iban = "NL91ABNA0417164300"

        with patch("frappe.get_doc") as mock_get_doc:

            def get_doc_side_effect(doctype, name=None):
                if doctype == "Member":
                    return mock_member
                if doctype == "SEPA Mandate":
                    return mock_sepa
                return MagicMock()

            mock_get_doc.side_effect = get_doc_side_effect

            service = MandateService()
            service._settings = self.mock_settings

            result = service.create_mandate_for_member("MEM-00001")

            self.assertFalse(result["success"])
            self.assertIn("no active SEPA mandate", result["error"].lower())

    @patch(
        "verenigingen.verenigingen_payments.ing_checkout.services.mandate_service.MandateService.client"
    )
    @patch("frappe.log_error")
    def test_create_mandate_for_member_api_error(self, mock_log_error, mock_client_prop):
        """Test mandate creation handles API errors gracefully."""
        from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

        # Mock member and SEPA mandate
        mock_member = MagicMock()
        mock_member.name = "MEM-00001"
        mock_member.full_name = "Test Member"
        mock_member.email = "test@example.com"
        mock_member.sepa_mandate = "SEPA-00001"

        mock_sepa = MagicMock()
        mock_sepa.name = "SEPA-00001"
        mock_sepa.iban = "NL91ABNA0417164300"
        mock_sepa.account_holder_name = "Test Member"
        mock_sepa.status = "Active"

        with patch("frappe.get_doc") as mock_get_doc:

            def get_doc_side_effect(doctype, name=None):
                if doctype == "Member":
                    return mock_member
                if doctype == "SEPA Mandate":
                    return mock_sepa
                return MagicMock()

            mock_get_doc.side_effect = get_doc_side_effect

            # Mock Pay.nl client to raise error
            mock_client = MagicMock()
            mock_client.create_mandate.side_effect = Exception("API connection failed")

            service = MandateService()
            service._client = mock_client
            service._settings = self.mock_settings

            result = service.create_mandate_for_member("MEM-00001")

            self.assertFalse(result["success"])
            self.assertIn("API connection failed", result["error"])
            mock_log_error.assert_called()

    # -------------------------------------------------------------------------
    # execute_debit_for_invoice Tests
    # -------------------------------------------------------------------------

    def test_execute_debit_for_invoice_success(self):
        """Test successful direct debit execution."""
        from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

        # Mock mandate and invoice
        mock_mandate = MagicMock()
        mock_mandate.name = "ING-MAND-00001"
        mock_mandate.mandate_id = "MD-123456789"
        mock_mandate.status = "Active"
        mock_mandate.execute_debit.return_value = {"referenceId": "DD-98765"}

        mock_invoice = MagicMock()
        mock_invoice.name = "SINV-00001"
        mock_invoice.outstanding_amount = 100.00

        with patch("frappe.get_doc") as mock_get_doc:

            def get_doc_side_effect(doctype, name=None):
                if doctype == "ING Checkout Mandate":
                    return mock_mandate
                if doctype == "Sales Invoice":
                    return mock_invoice
                return MagicMock()

            mock_get_doc.side_effect = get_doc_side_effect

            # Mock transaction creation
            with patch(
                "verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction.get_or_create_transaction"
            ) as mock_create_transaction:
                mock_transaction = MagicMock()
                mock_transaction.name = "ING-TXN-00001"
                mock_create_transaction.return_value = mock_transaction

                service = MandateService()
                result = service.execute_debit_for_invoice("ING-MAND-00001", "SINV-00001")

                self.assertTrue(result["success"])
                self.assertEqual(result["reference_id"], "DD-98765")
                self.assertEqual(result["transaction_name"], "ING-TXN-00001")
                mock_mandate.execute_debit.assert_called_once()

    def test_execute_debit_for_invoice_inactive_mandate(self):
        """Test direct debit fails with inactive mandate."""
        from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

        # Mock inactive mandate
        mock_mandate = MagicMock()
        mock_mandate.name = "ING-MAND-00001"
        mock_mandate.status = "Cancelled"

        mock_invoice = MagicMock()
        mock_invoice.outstanding_amount = 100.00

        with patch("frappe.get_doc") as mock_get_doc:

            def get_doc_side_effect(doctype, name=None):
                if doctype == "ING Checkout Mandate":
                    return mock_mandate
                if doctype == "Sales Invoice":
                    return mock_invoice
                return MagicMock()

            mock_get_doc.side_effect = get_doc_side_effect

            service = MandateService()
            result = service.execute_debit_for_invoice("ING-MAND-00001", "SINV-00001")

            self.assertFalse(result["success"])
            self.assertIn("not active", result["error"].lower())

    def test_execute_debit_for_invoice_zero_outstanding(self):
        """Test direct debit fails when invoice has no outstanding amount."""
        from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

        # Mock mandate and paid invoice
        mock_mandate = MagicMock()
        mock_mandate.name = "ING-MAND-00001"
        mock_mandate.status = "Active"

        mock_invoice = MagicMock()
        mock_invoice.outstanding_amount = 0.00

        with patch("frappe.get_doc") as mock_get_doc:

            def get_doc_side_effect(doctype, name=None):
                if doctype == "ING Checkout Mandate":
                    return mock_mandate
                if doctype == "Sales Invoice":
                    return mock_invoice
                return MagicMock()

            mock_get_doc.side_effect = get_doc_side_effect

            service = MandateService()
            result = service.execute_debit_for_invoice("ING-MAND-00001", "SINV-00001")

            self.assertFalse(result["success"])
            self.assertIn("no outstanding amount", result["error"].lower())

    @patch("frappe.log_error")
    def test_execute_debit_for_invoice_api_error(self, mock_log_error):
        """Test direct debit handles API errors gracefully."""
        from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

        # Mock mandate and invoice
        mock_mandate = MagicMock()
        mock_mandate.name = "ING-MAND-00001"
        mock_mandate.status = "Active"
        mock_mandate.execute_debit.side_effect = Exception("Payment processing failed")

        mock_invoice = MagicMock()
        mock_invoice.outstanding_amount = 100.00

        with patch("frappe.get_doc") as mock_get_doc:

            def get_doc_side_effect(doctype, name=None):
                if doctype == "ING Checkout Mandate":
                    return mock_mandate
                if doctype == "Sales Invoice":
                    return mock_invoice
                return MagicMock()

            mock_get_doc.side_effect = get_doc_side_effect

            service = MandateService()
            result = service.execute_debit_for_invoice("ING-MAND-00001", "SINV-00001")

            self.assertFalse(result["success"])
            self.assertIn("Payment processing failed", result["error"])
            mock_log_error.assert_called()

    # -------------------------------------------------------------------------
    # sync_mandate_status Tests
    # -------------------------------------------------------------------------

    def test_sync_mandate_status_changed(self):
        """Test mandate status sync when status changes."""
        from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

        # Mock mandate
        mock_mandate = MagicMock()
        mock_mandate.name = "ING-MAND-00001"
        mock_mandate.mandate_id = "MD-123456789"
        mock_mandate.status = "Pending"

        with patch("frappe.get_doc", return_value=mock_mandate):
            # Mock Pay.nl client response
            mock_client = MagicMock()
            mock_client.get_mandate.return_value = {"status": "active"}

            service = MandateService()
            service._client = mock_client

            # Mock MANDATE_STATUS_MAP
            with patch(
                "verenigingen.verenigingen_payments.doctype.ing_checkout_mandate.ing_checkout_mandate.MANDATE_STATUS_MAP",
                {"active": "Active", "pending": "Pending"},
            ):
                result = service.sync_mandate_status("ING-MAND-00001")

                self.assertTrue(result["success"])
                self.assertEqual(result["old_status"], "Pending")
                self.assertEqual(result["new_status"], "Active")
                self.assertTrue(result["changed"])

    def test_sync_mandate_status_unchanged(self):
        """Test mandate status sync when status hasn't changed."""
        from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

        # Mock mandate already Active
        mock_mandate = MagicMock()
        mock_mandate.name = "ING-MAND-00001"
        mock_mandate.mandate_id = "MD-123456789"
        mock_mandate.status = "Active"

        with patch("frappe.get_doc", return_value=mock_mandate):
            # Mock Pay.nl client response
            mock_client = MagicMock()
            mock_client.get_mandate.return_value = {"status": "active"}

            service = MandateService()
            service._client = mock_client

            # Mock MANDATE_STATUS_MAP
            with patch(
                "verenigingen.verenigingen_payments.doctype.ing_checkout_mandate.ing_checkout_mandate.MANDATE_STATUS_MAP",
                {"active": "Active", "pending": "Pending"},
            ):
                result = service.sync_mandate_status("ING-MAND-00001")

                self.assertTrue(result["success"])
                self.assertFalse(result["changed"])

    def test_sync_mandate_status_api_error(self):
        """Test mandate status sync handles API errors gracefully."""
        from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

        # Mock mandate
        mock_mandate = MagicMock()
        mock_mandate.mandate_id = "MD-123456789"

        with patch("frappe.get_doc", return_value=mock_mandate):
            # Mock Pay.nl client to raise error
            mock_client = MagicMock()
            mock_client.get_mandate.side_effect = Exception("API error")

            service = MandateService()
            service._client = mock_client

            result = service.sync_mandate_status("ING-MAND-00001")

            self.assertFalse(result["success"])
            self.assertIn("API error", result["error"])

    # -------------------------------------------------------------------------
    # get_active_mandates_for_member Tests
    # -------------------------------------------------------------------------

    def test_get_active_mandates_for_member_returns_list(self):
        """Test getting active mandates returns list of mandate data."""
        from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

        mock_mandates = [
            {
                "name": "ING-MAND-00001",
                "mandate_id": "MD-123",
                "mandate_type": "flexible",
                "debtor_iban": "NL91ABNA0417164300",
                "created_date": "2024-01-15",
            },
            {
                "name": "ING-MAND-00002",
                "mandate_id": "MD-456",
                "mandate_type": "recurring",
                "debtor_iban": "NL91ABNA0417164301",
                "created_date": "2024-02-20",
            },
        ]

        with patch("frappe.get_all", return_value=mock_mandates):
            service = MandateService()
            result = service.get_active_mandates_for_member("MEM-00001")

            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["mandate_id"], "MD-123")
            self.assertEqual(result[1]["mandate_id"], "MD-456")

    def test_get_active_mandates_for_member_no_mandates(self):
        """Test getting active mandates when member has none."""
        from verenigingen.verenigingen_payments.ing_checkout.services import MandateService

        with patch("frappe.get_all", return_value=[]):
            service = MandateService()
            result = service.get_active_mandates_for_member("MEM-00001")

            self.assertEqual(result, [])

    # -------------------------------------------------------------------------
    # Factory Function Tests
    # -------------------------------------------------------------------------

    def test_get_mandate_service_returns_instance(self):
        """Test that factory function returns MandateService instance."""
        from verenigingen.verenigingen_payments.ing_checkout.services import (
            MandateService,
            get_mandate_service,
        )

        service = get_mandate_service()
        self.assertIsInstance(service, MandateService)

    def test_get_mandate_service_creates_new_instance(self):
        """Test that factory creates new instance each call."""
        from verenigingen.verenigingen_payments.ing_checkout.services import get_mandate_service

        service1 = get_mandate_service()
        service2 = get_mandate_service()

        self.assertIsNot(service1, service2)


if __name__ == "__main__":
    unittest.main()
