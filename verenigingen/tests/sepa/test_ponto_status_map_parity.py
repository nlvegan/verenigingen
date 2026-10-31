# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
#1835: polling (``refresh_status``) and the webhook must classify every Ponto
status the same way, for both Ponto doctypes.

Real doctype controllers and the real webhook handlers run; the ONLY stub is the
Ponto HTTP client factory (``get_payment_client`` / ``get_betaalverzoek_client``).
Rows are inserted directly at the starting status (``insert()``, not a submit
that would call Ponto), matching the existing Ponto doctype suites; that is a
fixture shortcut for "a row that already went through signing".

"executed" is left out of the end-to-end loop on purpose: it creates a Payment
Entry (covered by test_ponto_payment_request_paid_after_pe). It is still
compared through the maps themselves.

Usage:
    bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.sepa.test_ponto_status_map_parity
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.ponto_test_data_factory import PontoTestDataFactory
from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
    _update_payment_link_status,
    handle_payment_request_closed,
)
from verenigingen.verenigingen_payments.ponto.core.status_maps import (
    LINK_STATUS_MAP,
    REQUEST_STATUS_MAP,
)

PAY_CLIENT = "verenigingen.verenigingen_payments.ponto.clients.payment_client.get_payment_client"
LINK_CLIENT = (
    "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
)

# Every Ponto status string any path knows, plus one nobody knows.
ALL_PONTO_STATUSES = sorted(set(REQUEST_STATUS_MAP) | set(LINK_STATUS_MAP) | {"someNewStatus"})
# End-to-end loop skips "executed" (Payment Entry side effect, covered elsewhere).
LOOP_STATUSES = [s for s in ALL_PONTO_STATUSES if s != "executed"]


def _status_select_options(doctype):
    return frappe.get_meta(doctype).get_field("status").options.split("\n")


class _Base(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _request(self, status="Pending"):
        doc = frappe.new_doc("Ponto Payment Request")
        doc.update(dict(
            ponto_account="test-account-id",
            amount=50.0,
            currency="EUR",
            creditor_name="Test Creditor",
            creditor_iban="NL91ABNA0417164300",
            remittance_info="parity",
            status=status,
            ponto_payment_id=f"pay-{frappe.generate_hash(length=10)}",
        ))
        doc.insert()
        return doc

    def _link(self, status="Pending Authorization"):
        doc = frappe.new_doc("Ponto Payment Link")
        doc.update(dict(
            payment_type="One-Time",
            amount=25.0,
            currency="EUR",
            description="parity",
            creditor_name="Vereniging",
            creditor_iban="NL91ABNA0417164300",
            status=status,
            ponto_request_id=f"req-{frappe.generate_hash(length=10)}",
        ))
        doc.insert()
        return doc

    def _poll_request(self, doc, ponto_status):
        client = MagicMock()
        client.get_payment.return_value = SimpleNamespace(status=ponto_status)
        with patch(PAY_CLIENT, return_value=client):
            doc.refresh_status()
        return frappe.db.get_value("Ponto Payment Request", doc.name, "status")

    def _poll_link(self, doc, ponto_status):
        client = MagicMock()
        client.get_payment_request.return_value = SimpleNamespace(
            status=ponto_status, debtor_name=None, debtor_iban=None, debtor_bank=None
        )
        with patch(LINK_CLIENT, return_value=client):
            doc.refresh_status()
        return frappe.db.get_value("Ponto Payment Link", doc.name, "status")

    def _webhook_request(self, doc, ponto_status):
        handle_payment_request_closed(
            json.loads(
                PontoTestDataFactory.create_payment_request_closed_webhook(
                    payment_id=doc.ponto_payment_id, status=ponto_status
                )
            )
        )
        return frappe.db.get_value("Ponto Payment Request", doc.name, "status")

    def _webhook_link(self, doc, ponto_status):
        _update_payment_link_status(doc.ponto_request_id, ponto_status)
        return frappe.db.get_value("Ponto Payment Link", doc.name, "status")


class TestStatusMapsAreRealOptions(_Base):
    def test_every_target_is_a_select_option(self):
        """A mapped status the doctype cannot hold would fail on save."""
        self.assertLessEqual(set(REQUEST_STATUS_MAP.values()), set(_status_select_options("Ponto Payment Request")))
        self.assertLessEqual(set(LINK_STATUS_MAP.values()), set(_status_select_options("Ponto Payment Link")))


class TestPollingAndWebhookAgree(_Base):
    def test_request_every_status_same_result_both_paths(self):
        for ponto_status in LOOP_STATUSES:
            with self.subTest(ponto_status=ponto_status):
                polled = self._poll_request(self._request(), ponto_status)
                hooked = self._webhook_request(self._request(), ponto_status)
                self.assertEqual(polled, hooked)

    def test_link_every_status_same_result_both_paths(self):
        for ponto_status in LOOP_STATUSES:
            with self.subTest(ponto_status=ponto_status):
                polled = self._poll_link(self._link(), ponto_status)
                hooked = self._webhook_link(self._link(), ponto_status)
                self.assertEqual(polled, hooked)

    def test_request_poll_adopts_cancelled(self):
        """The #1835 symptom: the poll used to leave a Cancelled-at-Ponto row Pending."""
        self.assertEqual(self._poll_request(self._request(), "cancelled"), "Cancelled")

    def test_link_poll_adopts_cancelled_and_expired(self):
        self.assertEqual(self._poll_link(self._link(), "cancelled"), "Cancelled")
        self.assertEqual(self._poll_link(self._link(), "expired"), "Expired")

    def test_request_has_no_expired_so_it_is_left_unchanged(self):
        """No Expired option on the Request: unmapped, kept as is, by both paths."""
        self.assertNotIn("Expired", _status_select_options("Ponto Payment Request"))
        self.assertEqual(self._poll_request(self._request("Signed"), "expired"), "Signed")
        self.assertEqual(self._webhook_request(self._request("Signed"), "expired"), "Signed")

    def test_unknown_status_keeps_current_status_on_both_paths(self):
        self.assertEqual(self._poll_request(self._request("Signed"), "someNewStatus"), "Signed")
        self.assertEqual(self._poll_link(self._link("Authorized"), "someNewStatus"), "Authorized")
        self.assertEqual(self._webhook_request(self._request("Signed"), "someNewStatus"), "Signed")
        self.assertEqual(self._webhook_link(self._link("Authorized"), "someNewStatus"), "Authorized")

    def test_link_client_closed_marker_polls_to_executed(self):
        """'closed' is betaalverzoek_client's own marker (closedAt set); behaviour kept.

        No sales_invoice on the row, so process_payment_received() is a no-op and
        no Payment Entry is involved. See the #1835 report on closed -> Executed.
        """
        self.assertEqual(self._poll_link(self._link("Pending Authorization"), "closed"), "Executed")


class TestNoBackwardMoves(_Base):
    def test_request_poll_pending_does_not_undo_signed(self):
        self.assertEqual(self._poll_request(self._request("Signed"), "pending"), "Signed")

    def test_request_webhook_pending_does_not_undo_signed(self):
        self.assertEqual(self._webhook_request(self._request("Signed"), "unsigned"), "Signed")

    def test_link_poll_pending_does_not_undo_authorized(self):
        self.assertEqual(self._poll_link(self._link("Authorized"), "pending"), "Authorized")

    def test_link_webhook_signed_does_not_undo_executed(self):
        self.assertEqual(self._webhook_link(self._link("Executed"), "signed"), "Executed")

    def test_request_executed_is_not_undone_by_pending(self):
        self.assertEqual(self._poll_request(self._request("Executed"), "pending"), "Executed")

    def test_forward_moves_still_happen(self):
        """Control: Pending -> Signed and a locally Cancelled row -> Signed/Executed path stay open."""
        self.assertEqual(self._poll_request(self._request("Pending"), "signed"), "Signed")
        self.assertEqual(self._poll_link(self._link("Pending Authorization"), "signed"), "Authorized")
        # A local cancel is not authoritative (it is not deleted at Ponto): Ponto's
        # word still wins from a non-chain status.
        self.assertEqual(self._poll_request(self._request("Cancelled"), "signed"), "Signed")
