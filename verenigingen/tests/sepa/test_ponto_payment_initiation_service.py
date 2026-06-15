"""
Integration tests for the Ponto Payment Initiation Service.

These exercise the high-level service that creates real "Ponto Payment Request"
documents and coordinates with the payment client. The Ponto HTTP boundary
(get_payment_client) is stubbed so submit/cancel do not hit the network; the
DocType, validation, and ORM paths are real.

Usage:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.sepa.test_ponto_payment_initiation_service
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.ponto_test_data_factory import TestIBAN
from verenigingen.tests.fixtures.singleton_backup import SingletonBackup

PAY_CLIENT_PATH = (
    "verenigingen.verenigingen_payments.ponto.clients.payment_client.get_payment_client"
)


class TestPontoPaymentInitiationService(FrappeTestCase):
    """Tests for payment_initiation_service helpers."""

    TEST_ACCOUNT_ID = "svc-acc-uuid-0001"

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
        settings = frappe.get_single("Ponto Settings")
        settings.ibanity_client_id = "test_client_id"
        settings.ibanity_client_secret = "test_client_secret"
        settings.sandbox_client_id = "test_client_id"
        settings.sandbox_client_secret = "test_client_secret"
        settings.sandbox_mode = 1
        settings.set("bank_account_mappings", [])
        settings.append(
            "bank_account_mappings",
            {"ponto_account_id": cls.TEST_ACCOUNT_ID, "enabled": 1},
        )
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        settings.flags.ignore_validate = False
        frappe.db.commit()

    def _mock_payment_client(self):
        """Return a (patcher, mock_client) for get_payment_client."""
        mock_client = MagicMock()
        mock_payment = MagicMock()
        mock_payment.id = "ponto-pay-id"
        mock_payment.redirect_link = "https://myponto.com/sign/abc"
        mock_client.create_payment.return_value = mock_payment
        mock_client.delete_payment.return_value = True
        return mock_client

    # -------------------------------------------------------------------------
    # create_sepa_payment - validation (no doc creation)
    # -------------------------------------------------------------------------

    def test_rejects_zero_amount(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_sepa_payment,
        )

        with self.assertRaises(PontoIntegrationError):
            create_sepa_payment(
                ponto_account_id=self.TEST_ACCOUNT_ID,
                amount=0,
                creditor_name="X",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="r",
            )

    def test_rejects_excess_amount(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_sepa_payment,
        )

        with self.assertRaises(PontoIntegrationError):
            create_sepa_payment(
                ponto_account_id=self.TEST_ACCOUNT_ID,
                amount=1_000_000_000.0,
                creditor_name="X",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="r",
            )

    def test_rejects_three_decimals(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_sepa_payment,
        )

        with self.assertRaises(PontoIntegrationError):
            create_sepa_payment(
                ponto_account_id=self.TEST_ACCOUNT_ID,
                amount=10.001,
                creditor_name="X",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="r",
            )

    def test_rejects_missing_creditor(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_sepa_payment,
        )

        with self.assertRaises(PontoIntegrationError):
            create_sepa_payment(
                ponto_account_id=self.TEST_ACCOUNT_ID,
                amount=10,
                creditor_name="",
                creditor_iban="",
                remittance_info="r",
            )

    def test_rejects_invalid_iban(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_sepa_payment,
        )

        with self.assertRaises(PontoIntegrationError):
            create_sepa_payment(
                ponto_account_id=self.TEST_ACCOUNT_ID,
                amount=10,
                creditor_name="X",
                creditor_iban="NL00BANK0000000000",
                remittance_info="r",
            )

    def test_rejects_missing_remittance(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_sepa_payment,
        )

        with self.assertRaises(PontoIntegrationError):
            create_sepa_payment(
                ponto_account_id=self.TEST_ACCOUNT_ID,
                amount=10,
                creditor_name="X",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="",
            )

    def test_rejects_unknown_account(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_sepa_payment,
        )

        with self.assertRaises(PontoIntegrationError):
            create_sepa_payment(
                ponto_account_id="account-not-in-settings",
                amount=10,
                creditor_name="X",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="r",
            )

    # -------------------------------------------------------------------------
    # create_sepa_payment - document creation
    # -------------------------------------------------------------------------

    def test_create_draft_without_submit(self):
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_sepa_payment,
        )

        doc = create_sepa_payment(
            ponto_account_id=self.TEST_ACCOUNT_ID,
            amount=42.50,
            creditor_name="Supplier BV",
            creditor_iban=TestIBAN.ABN_AMRO_1,
            remittance_info="Invoice 99",
            auto_submit=False,
        )
        self.addCleanup(self._delete_doc, doc.name)
        self.assertEqual(doc.docstatus, 0)
        self.assertEqual(doc.status, "Draft")
        self.assertEqual(doc.currency, "EUR")
        self.assertEqual(doc.amount, 42.50)

    def test_create_and_submit_calls_api(self):
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_sepa_payment,
        )

        mock_client = self._mock_payment_client()
        with patch(PAY_CLIENT_PATH, return_value=mock_client):
            doc = create_sepa_payment(
                ponto_account_id=self.TEST_ACCOUNT_ID,
                amount=15.00,
                creditor_name="Supplier BV",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="Invoice 100",
                auto_submit=True,
            )
        self.addCleanup(self._delete_doc, doc.name)
        mock_client.create_payment.assert_called_once()
        self.assertEqual(doc.docstatus, 1)
        self.assertEqual(doc.status, "Pending")
        self.assertEqual(doc.ponto_payment_id, "ponto-pay-id")
        self.assertEqual(doc.redirect_link, "https://myponto.com/sign/abc")

    # -------------------------------------------------------------------------
    # get_payment_authorization_url / refresh / list / cancel
    # -------------------------------------------------------------------------

    def test_get_payment_authorization_url(self):
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_sepa_payment,
            get_payment_authorization_url,
        )

        mock_client = self._mock_payment_client()
        with patch(PAY_CLIENT_PATH, return_value=mock_client):
            doc = create_sepa_payment(
                ponto_account_id=self.TEST_ACCOUNT_ID,
                amount=15.00,
                creditor_name="Supplier BV",
                creditor_iban=TestIBAN.ABN_AMRO_1,
                remittance_info="Invoice 101",
                auto_submit=True,
            )
        self.addCleanup(self._delete_doc, doc.name)
        url = get_payment_authorization_url(doc.name)
        self.assertEqual(url, "https://myponto.com/sign/abc")

    def test_list_pending_payments(self):
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_sepa_payment,
            list_pending_payments,
        )

        doc = create_sepa_payment(
            ponto_account_id=self.TEST_ACCOUNT_ID,
            amount=33.00,
            creditor_name="Supplier BV",
            creditor_iban=TestIBAN.ABN_AMRO_1,
            remittance_info="Invoice 102",
            auto_submit=False,
        )
        self.addCleanup(self._delete_doc, doc.name)

        pending = list_pending_payments(ponto_account_id=self.TEST_ACCOUNT_ID)
        names = [p["name"] for p in pending]
        self.assertIn(doc.name, names)

    def test_cancel_draft_payment_deletes(self):
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            cancel_payment,
            create_sepa_payment,
        )

        doc = create_sepa_payment(
            ponto_account_id=self.TEST_ACCOUNT_ID,
            amount=12.00,
            creditor_name="Supplier BV",
            creditor_iban=TestIBAN.ABN_AMRO_1,
            remittance_info="Invoice 103",
            auto_submit=False,
        )
        name = doc.name
        result = cancel_payment(name)
        self.assertTrue(result)
        self.assertFalse(frappe.db.exists("Ponto Payment Request", name))

    def test_cancel_executed_payment_throws(self):
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            cancel_payment,
            create_sepa_payment,
        )

        doc = create_sepa_payment(
            ponto_account_id=self.TEST_ACCOUNT_ID,
            amount=12.00,
            creditor_name="Supplier BV",
            creditor_iban=TestIBAN.ABN_AMRO_1,
            remittance_info="Invoice 104",
            auto_submit=False,
        )
        self.addCleanup(self._delete_doc, doc.name)
        frappe.db.set_value("Ponto Payment Request", doc.name, "status", "Executed")

        with self.assertRaises(frappe.ValidationError):
            cancel_payment(doc.name)

    def _delete_doc(self, name):
        if frappe.db.exists("Ponto Payment Request", name):
            try:
                doc = frappe.get_doc("Ponto Payment Request", name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Ponto Payment Request", name, force=True)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
