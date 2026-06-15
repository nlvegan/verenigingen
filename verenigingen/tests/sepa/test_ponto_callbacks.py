"""
Integration tests for the Ponto redirect callback endpoints.

Covers:
- payment_callback (Ponto Payment Request redirect)
- payment_link_callback + payment_page (Ponto Payment Link / betaalverzoek)

These construct a realistic request (frappe.request.args with the redirect
params) and assert the doc status transitions and the redirect target written
to frappe.local.response. The outbound status-fetch HTTP call (refresh_status ->
payment client) is stubbed; the DocType writes are real.

Usage:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.sepa.test_ponto_callbacks
"""

import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.ponto_test_data_factory import TestIBAN


@contextmanager
def fake_request(**args):
    """Patch frappe.request.args + reset frappe.local.response for a callback.

    Restores the previous request and response on exit.
    """
    original_request = getattr(frappe.local, "request", None)
    original_response = dict(frappe.local.response) if frappe.local.response else {}

    mock_request = MagicMock()
    mock_request.args = args
    # The @public_api decorator validates request method/content-type; give it
    # real string values so the security framework accepts the GET callback.
    mock_request.method = "GET"
    mock_request.content_type = "application/x-www-form-urlencoded"
    mock_request.url = "https://site.example/api/method/ponto_callback"
    # get_url() reads request.host / scheme to build absolute URLs.
    mock_request.host = "site.example"
    mock_request.scheme = "https"
    mock_request.headers = {}
    frappe.local.request = mock_request
    frappe.local.response = frappe._dict()
    try:
        yield
    finally:
        frappe.local.request = original_request
        frappe.local.response = frappe._dict(original_response)


class TestPontoPaymentCallback(FrappeTestCase):
    """Tests for payment_callback (Ponto Payment Request)."""

    def setUp(self):
        super().setUp()
        # Avoid the handler switching to a different webhook user; keep the
        # current (test) user so doc writes use real permissions.
        self._svc_patch = patch(
            "verenigingen.verenigingen_payments.ponto.api.payment_callback.get_service_user",
            return_value=None,
        )
        self._svc_patch.start()
        self.addCleanup(self._svc_patch.stop)

    def _make_payment_request(self, status="Pending"):
        doc = frappe.new_doc("Ponto Payment Request")
        doc.ponto_account = "cb-acc"
        doc.amount = 20.00
        doc.currency = "EUR"
        doc.creditor_name = "Org"
        doc.creditor_iban = TestIBAN.ABN_AMRO_1
        doc.remittance_info = "ref"
        doc.status = status
        doc.ponto_payment_id = "ponto-id-1"
        doc.insert()
        self.addCleanup(lambda n=doc.name: self._cleanup("Ponto Payment Request", n))
        return doc

    def _cleanup(self, doctype, name):
        if frappe.db.exists(doctype, name):
            frappe.delete_doc(doctype, name, force=True)

    def test_missing_payment_request_redirects_to_desk(self):
        from verenigingen.verenigingen_payments.ponto.api.payment_callback import payment_callback

        with fake_request():
            payment_callback()
            self.assertEqual(frappe.local.response["type"], "redirect")
            self.assertTrue(frappe.local.response["location"].endswith("/desk"))

    def test_unknown_payment_request_redirects_to_desk(self):
        from verenigingen.verenigingen_payments.ponto.api.payment_callback import payment_callback

        with fake_request(payment_request="DOES-NOT-EXIST"):
            payment_callback()
            self.assertTrue(frappe.local.response["location"].endswith("/desk"))

    def test_access_denied_marks_cancelled(self):
        from verenigingen.verenigingen_payments.ponto.api.payment_callback import payment_callback

        doc = self._make_payment_request()
        with fake_request(payment_request=doc.name, error="access_denied"):
            payment_callback()
            self.assertIn(doc.name, frappe.local.response["location"])

        self.assertEqual(
            frappe.db.get_value("Ponto Payment Request", doc.name, "status"), "Cancelled"
        )

    def test_other_error_marks_rejected(self):
        from verenigingen.verenigingen_payments.ponto.api.payment_callback import payment_callback

        doc = self._make_payment_request()
        with fake_request(
            payment_request=doc.name,
            error="server_error",
            error_description="bank failure",
        ):
            payment_callback()

        self.assertEqual(
            frappe.db.get_value("Ponto Payment Request", doc.name, "status"), "Rejected"
        )

    def test_success_refreshes_status(self):
        from verenigingen.verenigingen_payments.ponto.api import payment_callback as cb_module

        doc = self._make_payment_request()

        # Stub refresh_status on the controller class so no API/network call.
        with patch(
            "verenigingen.verenigingen_payments.doctype.ponto_payment_request."
            "ponto_payment_request.PontoPaymentRequest.refresh_status",
            return_value={"status": "Signed"},
        ):
            with fake_request(payment_request=doc.name):
                cb_module.payment_callback()
                self.assertEqual(frappe.local.response["type"], "redirect")
                self.assertIn(doc.name, frappe.local.response["location"])

    def test_success_refresh_failure_still_redirects(self):
        from verenigingen.verenigingen_payments.ponto.api import payment_callback as cb_module

        doc = self._make_payment_request()
        with patch(
            "verenigingen.verenigingen_payments.doctype.ponto_payment_request."
            "ponto_payment_request.PontoPaymentRequest.refresh_status",
            side_effect=RuntimeError("api down"),
        ):
            with fake_request(payment_request=doc.name):
                cb_module.payment_callback()
                # Despite refresh failure, it redirects to the document (no raise).
                self.assertEqual(frappe.local.response["type"], "redirect")
                self.assertIn(doc.name, frappe.local.response["location"])


class TestPontoPaymentLinkCallback(FrappeTestCase):
    """Tests for payment_link_callback + payment_page (betaalverzoek)."""

    def setUp(self):
        super().setUp()
        self._svc_patch = patch(
            "verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback.get_service_user",
            return_value=None,
        )
        self._svc_patch.start()
        self.addCleanup(self._svc_patch.stop)

    def _make_payment_link(self, status="Pending Authorization"):
        doc = frappe.new_doc("Ponto Payment Link")
        doc.payment_type = "One-Time"
        doc.amount = 25.00
        doc.currency = "EUR"
        doc.description = "Membership dues"
        doc.creditor_name = "Org"
        doc.creditor_iban = TestIBAN.ABN_AMRO_1
        doc.status = status
        doc.ponto_request_id = "ponto-req-1"
        doc.redirect_link = "https://myponto.com/sign/req-1"
        doc.insert()
        self.addCleanup(lambda n=doc.name: self._cleanup("Ponto Payment Link", n))
        return doc

    def _cleanup(self, doctype, name):
        if frappe.db.exists(doctype, name):
            frappe.delete_doc(doctype, name, force=True)

    def test_missing_payment_link_redirects_home(self):
        from verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback import (
            payment_link_callback,
        )

        with fake_request():
            payment_link_callback()
            self.assertEqual(frappe.local.response["type"], "redirect")
            self.assertTrue(frappe.local.response["location"].endswith("/app/home"))

    def test_unknown_payment_link_redirects_home(self):
        from verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback import (
            payment_link_callback,
        )

        with fake_request(payment_link="NOPE"):
            payment_link_callback()
            self.assertTrue(frappe.local.response["location"].endswith("/app/home"))

    def test_access_denied_marks_cancelled(self):
        from verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback import (
            payment_link_callback,
        )

        doc = self._make_payment_link()
        with fake_request(payment_link=doc.name, error="access_denied"):
            payment_link_callback()
            self.assertIn("payment-success", frappe.local.response["location"])

        self.assertEqual(
            frappe.db.get_value("Ponto Payment Link", doc.name, "status"), "Cancelled"
        )

    def test_other_error_marks_rejected(self):
        from verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback import (
            payment_link_callback,
        )

        doc = self._make_payment_link()
        with fake_request(
            payment_link=doc.name, error="server_error", error_description="boom"
        ):
            payment_link_callback()
            self.assertIn("payment-success", frappe.local.response["location"])

        self.assertEqual(
            frappe.db.get_value("Ponto Payment Link", doc.name, "status"), "Rejected"
        )

    def test_success_refreshes_and_redirects(self):
        from verenigingen.verenigingen_payments.ponto.api import betaalverzoek_callback as cb

        doc = self._make_payment_link()
        with patch(
            "verenigingen.verenigingen_payments.doctype.ponto_payment_link."
            "ponto_payment_link.PontoPaymentLink.refresh_status",
            return_value={"status": "Executed"},
        ):
            with fake_request(payment_link=doc.name):
                cb.payment_link_callback()
                self.assertIn("payment-success", frappe.local.response["location"])

    def test_success_refresh_failure_still_redirects(self):
        from verenigingen.verenigingen_payments.ponto.api import betaalverzoek_callback as cb

        doc = self._make_payment_link()
        with patch(
            "verenigingen.verenigingen_payments.doctype.ponto_payment_link."
            "ponto_payment_link.PontoPaymentLink.refresh_status",
            side_effect=RuntimeError("api down"),
        ):
            with fake_request(payment_link=doc.name):
                cb.payment_link_callback()
                self.assertIn("payment-success", frappe.local.response["location"])

    # -------------------------------------------------------------------------
    # payment_page
    # -------------------------------------------------------------------------

    def test_payment_page_returns_details_for_pending(self):
        from verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback import payment_page

        doc = self._make_payment_link(status="Pending Authorization")
        with fake_request(link=doc.name):
            result = payment_page()
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["payment_link"], doc.name)
        self.assertEqual(result["amount"], 25.00)
        self.assertEqual(result["redirect_link"], "https://myponto.com/sign/req-1")

    def test_payment_page_already_paid(self):
        from verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback import payment_page

        doc = self._make_payment_link(status="Executed")
        with fake_request(link=doc.name):
            result = payment_page()
        self.assertEqual(result["status"], "already_paid")

    def test_payment_page_cancelled(self):
        from verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback import payment_page

        doc = self._make_payment_link(status="Cancelled")
        with fake_request(link=doc.name):
            result = payment_page()
        self.assertEqual(result["status"], "cancelled")

    def test_payment_page_missing_link_throws(self):
        from verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback import payment_page

        with fake_request():
            with self.assertRaises(frappe.exceptions.DoesNotExistError):
                payment_page()

    def test_payment_page_unknown_link_throws(self):
        from verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback import payment_page

        with fake_request(link="NOPE"):
            with self.assertRaises(frappe.exceptions.DoesNotExistError):
                payment_page()


if __name__ == "__main__":
    unittest.main()
