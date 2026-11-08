# Copyright (c) 2026, Verenigingen
"""A failed Ponto create call must leave an Error Log row that names the document (#2114).

Before #1924 the only way to match a create-failure row to a document was the IBAN and
amount the client wrapper appended to the message. #1924 removed those (a leak), so the
row must carry the document name instead. It must still not carry the creditor IBAN.

Only the HTTP client is stubbed; the controllers' real before_submit() runs.

Usage:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_ponto_create_error_log_docname_2114
"""

from unittest.mock import MagicMock, patch as mock_patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_ponto_payment_request_paid_after_pe import (
    _PontoPaymentRequestFixtures,
)

PAY_CLIENT_PATH = "verenigingen.verenigingen_payments.ponto.clients.payment_client.get_payment_client"
LINK_CLIENT_PATH = (
    "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
)
CREDITOR_IBAN = "NL91ABNA0417164300"
FAILURE = "Ponto API said no (stubbed)"


class TestPontoCreateErrorLogDocname(_PontoPaymentRequestFixtures, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.expectErrorLog("Ponto payment creation failed", "Ponto payment link creation failed")

    def _rows(self, title_prefix):
        return frappe.get_all(
            "Error Log",
            filters={"method": ["like", f"{title_prefix}%"]},
            fields=["name", "method", "error"],
        )

    def _failing_client(self):
        client = MagicMock()
        client.create_payment.side_effect = Exception(FAILURE)
        client.create_payment_request.side_effect = Exception(FAILURE)
        return client

    def _assert_row_names_doc_without_iban(self, title_prefix, doc_name, before):
        new = [r for r in self._rows(title_prefix) if r.name not in before]
        self.assertEqual(len(new), 1, "exactly one new create-failure row expected")
        row = new[0]
        self.assertIn(doc_name, row.method)
        self.assertNotIn(CREDITOR_IBAN, row.method)
        self.assertNotIn(CREDITOR_IBAN, row.error or "")
        self.assertIn(FAILURE, row.error or "", "the cause must still be recorded")

    def test_payment_request_create_failure_names_the_request(self):
        supplier = self._create_supplier("Err2114")
        req = frappe.new_doc("Ponto Payment Request")
        req.ponto_account = self.TEST_PONTO_ACCOUNT_ID
        req.amount = 42.0
        req.currency = "EUR"
        req.creditor_name = "Test Creditor"
        req.creditor_iban = CREDITOR_IBAN
        req.remittance_info = "Test payment #2114"
        req.reference_doctype = "Supplier"
        req.reference_name = supplier.name
        req.insert(ignore_permissions=True)
        self.track_doc("Ponto Payment Request", req.name)
        before = {r.name for r in self._rows("Ponto payment creation failed")}

        with mock_patch(PAY_CLIENT_PATH, return_value=self._failing_client()):
            with self.assertRaises(frappe.ValidationError):
                req.submit()

        self._assert_row_names_doc_without_iban("Ponto payment creation failed", req.name, before)

    def test_payment_link_create_failure_names_the_link(self):
        link = frappe.new_doc("Ponto Payment Link")
        link.payment_type = "One-Time"
        link.amount = 25.0
        link.currency = "EUR"
        link.description = "Test payment #2114"
        link.creditor_name = "Test Association"
        link.creditor_iban = CREDITOR_IBAN
        link.insert(ignore_permissions=True)
        self.track_doc("Ponto Payment Link", link.name)
        before = {r.name for r in self._rows("Ponto payment link creation failed")}

        with mock_patch(LINK_CLIENT_PATH, return_value=self._failing_client()):
            with self.assertRaises(frappe.ValidationError):
                link.submit()

        self._assert_row_names_doc_without_iban("Ponto payment link creation failed", link.name, before)
