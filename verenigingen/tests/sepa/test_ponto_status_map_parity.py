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

Moving a row to Executed creates a Payment Entry. Those cells stub ONLY the
Payment Entry creator as a spy (``create_payment_entry`` /
``process_payment_received``) and, on the link webhook path, ``frappe.enqueue``.
The Payment Entry itself is covered by test_ponto_payment_request_paid_after_pe.

Usage:
    bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.sepa.test_ponto_status_map_parity
"""

import ast
import inspect
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.ponto_test_data_factory import PontoTestDataFactory
from verenigingen.verenigingen_payments.doctype.ponto_payment_link import ponto_payment_link
from verenigingen.verenigingen_payments.doctype.ponto_payment_link.ponto_payment_link import (
    PontoPaymentLink,
)
from verenigingen.verenigingen_payments.doctype.ponto_payment_request import ponto_payment_request
from verenigingen.verenigingen_payments.doctype.ponto_payment_request.ponto_payment_request import (
    PontoPaymentRequest,
)
from verenigingen.verenigingen_payments.ponto.api import webhook_handlers
from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
    _update_payment_link_status,
    handle_payment_request_closed,
)
from verenigingen.verenigingen_payments.ponto.core import status_maps
from verenigingen.verenigingen_payments.ponto.core.status_maps import (
    LINK_STATUS_MAP,
    REQUEST_STATUS_MAP,
    is_refused_move,
)

PAY_CLIENT = "verenigingen.verenigingen_payments.ponto.clients.payment_client.get_payment_client"
LINK_CLIENT = (
    "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
)

WEBHOOK_ENQUEUE = "verenigingen.verenigingen_payments.ponto.api.webhook_handlers.frappe.enqueue"

# Ponto inputs the table covers, in column order. "executed" is Ponto's word for
# a paid request.
PONTO_INPUTS = ["pending", "signed", "executed", "cancelled", "rejected", "failed", "expired"]

# (starting local status) -> {ponto status -> resulting local status}.
# HARDCODED on purpose: nothing here is derived from the code under test.
# Rulings of 2026-10-31: Executed is final; Cancelled/Rejected/Failed/Expired may
# move forward (Signed/Authorized, Executed) but never back to Pending.
REQUEST_EXPECTED = {
    "Pending": {
        "pending": "Pending", "signed": "Signed", "executed": "Executed", "cancelled": "Cancelled",
        "rejected": "Rejected", "failed": "Failed", "expired": "Expired",
    },
    "Signed": {
        "pending": "Signed", "signed": "Signed", "executed": "Executed", "cancelled": "Cancelled",
        "rejected": "Rejected", "failed": "Failed", "expired": "Expired",
    },
    "Executed": {
        "pending": "Executed", "signed": "Executed", "executed": "Executed", "cancelled": "Executed",
        "rejected": "Executed", "failed": "Executed", "expired": "Executed",
    },
    "Cancelled": {
        "pending": "Cancelled", "signed": "Signed", "executed": "Executed", "cancelled": "Cancelled",
        "rejected": "Rejected", "failed": "Failed", "expired": "Expired",
    },
    "Rejected": {
        "pending": "Rejected", "signed": "Signed", "executed": "Executed", "cancelled": "Cancelled",
        "rejected": "Rejected", "failed": "Failed", "expired": "Expired",
    },
    "Failed": {
        "pending": "Failed", "signed": "Signed", "executed": "Executed", "cancelled": "Cancelled",
        "rejected": "Rejected", "failed": "Failed", "expired": "Expired",
    },
    "Expired": {
        "pending": "Expired", "signed": "Signed", "executed": "Executed", "cancelled": "Cancelled",
        "rejected": "Rejected", "failed": "Failed", "expired": "Expired",
    },
}

LINK_EXPECTED = {
    "Pending Authorization": {
        "pending": "Pending Authorization", "signed": "Authorized", "executed": "Executed",
        "cancelled": "Cancelled", "rejected": "Rejected", "failed": "Failed", "expired": "Expired",
    },
    "Authorized": {
        "pending": "Authorized", "signed": "Authorized", "executed": "Executed",
        "cancelled": "Cancelled", "rejected": "Rejected", "failed": "Failed", "expired": "Expired",
    },
    "Executed": {
        "pending": "Executed", "signed": "Executed", "executed": "Executed",
        "cancelled": "Executed", "rejected": "Executed", "failed": "Executed", "expired": "Executed",
    },
    "Cancelled": {
        "pending": "Cancelled", "signed": "Authorized", "executed": "Executed",
        "cancelled": "Cancelled", "rejected": "Rejected", "failed": "Failed", "expired": "Expired",
    },
    "Rejected": {
        "pending": "Rejected", "signed": "Authorized", "executed": "Executed",
        "cancelled": "Cancelled", "rejected": "Rejected", "failed": "Failed", "expired": "Expired",
    },
    "Failed": {
        "pending": "Failed", "signed": "Authorized", "executed": "Executed",
        "cancelled": "Cancelled", "rejected": "Rejected", "failed": "Failed", "expired": "Expired",
    },
    "Expired": {
        "pending": "Expired", "signed": "Authorized", "executed": "Executed",
        "cancelled": "Cancelled", "rejected": "Rejected", "failed": "Failed", "expired": "Expired",
    },
}


def _private_status_maps(source):
    """Dict literals in ``source`` that look like a Ponto status map."""
    return [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Dict)
        and {"unsigned", "cancelled"} & {k.value for k in node.keys if isinstance(k, ast.Constant)}
    ]


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

    def _webhook_request_result(self, doc, ponto_status):
        return handle_payment_request_closed(
            json.loads(
                PontoTestDataFactory.create_payment_request_closed_webhook(
                    payment_id=doc.ponto_payment_id, status=ponto_status
                )
            )
        )

    def _webhook_request(self, doc, ponto_status):
        self._webhook_request_result(doc, ponto_status)
        return frappe.db.get_value("Ponto Payment Request", doc.name, "status")

    def _webhook_link(self, doc, ponto_status):
        _update_payment_link_status(doc.ponto_request_id, ponto_status)
        return frappe.db.get_value("Ponto Payment Link", doc.name, "status")


class TestTransitionTables(_Base):
    """Every (start, incoming Ponto status) cell, both doctypes, both paths."""

    def _run_cells(self, expected, make, drive, pe_creator_cls, pe_method, enqueues_on_executed=False):
        for start, row in expected.items():
            for ponto_status in PONTO_INPUTS:
                want = row[ponto_status]
                with self.subTest(start=start, ponto=ponto_status):
                    doc = make(start)
                    # Mock justified: spy on the Payment Entry creator only.
                    with patch.object(pe_creator_cls, pe_method) as pe_spy:
                        with patch(WEBHOOK_ENQUEUE) as enqueue_spy:
                            got = drive(doc, ponto_status)
                    self.assertEqual(got, want)
                    # A Payment Entry is attempted EXACTLY ONCE when a row newly becomes
                    # Executed, and never for an already-Executed row.
                    paid = want == "Executed" and start != "Executed"
                    self.assertEqual(pe_spy.call_count, 1 if paid else 0)
                    # Only the link webhook queues a Payment Entry job, once per Executed
                    # event on a row with no payment_entry (also when already Executed:
                    # that is the retry path, guarded in the job by reference_no).
                    queued = enqueues_on_executed and ponto_status == "executed"
                    self.assertEqual(enqueue_spy.call_count, 1 if queued else 0)

    def test_request_poll_table(self):
        self._run_cells(REQUEST_EXPECTED, self._request, self._poll_request,
                        PontoPaymentRequest, "create_payment_entry")

    def test_request_webhook_table(self):
        self._run_cells(REQUEST_EXPECTED, self._request, self._webhook_request,
                        PontoPaymentRequest, "create_payment_entry")

    def test_link_poll_table(self):
        self._run_cells(LINK_EXPECTED, self._link, self._poll_link,
                        PontoPaymentLink, "process_payment_received")

    def test_link_webhook_table(self):
        self._run_cells(LINK_EXPECTED, self._link, self._webhook_link,
                        PontoPaymentLink, "process_payment_received", enqueues_on_executed=True)

    def test_link_webhook_enqueues_payment_entry_job_from_cancelled(self):
        """Cancelled -> Executed on the link webhook queues the Payment Entry job."""
        doc = self._link("Cancelled")
        # No sales_invoice on the row, so process_payment_received() is a real no-op.
        with patch(WEBHOOK_ENQUEUE) as enqueue_spy:
            self.assertEqual(self._webhook_link(doc, "executed"), "Executed")
        enqueue_spy.assert_called_once()

    def test_link_webhook_never_enqueues_for_refused_move_off_executed(self):
        doc = self._link("Executed")
        doc.db_set("payment_entry", None)
        with patch(WEBHOOK_ENQUEUE) as enqueue_spy:
            self.assertEqual(self._webhook_link(doc, "cancelled"), "Executed")
        enqueue_spy.assert_not_called()


class TestStatusMapsLiteral(_Base):
    """The maps pinned as literals, so the tests above are not derived from them."""

    def test_request_map(self):
        self.assertEqual(
            REQUEST_STATUS_MAP,
            {
                "pending": "Pending", "unsigned": "Pending", "signed": "Signed",
                "executed": "Executed", "rejected": "Rejected", "failed": "Failed",
                "cancelled": "Cancelled", "expired": "Expired",
            },
        )

    def test_link_map(self):
        self.assertEqual(
            LINK_STATUS_MAP,
            {
                "pending": "Pending Authorization", "unsigned": "Pending Authorization",
                "signed": "Authorized", "authorized": "Authorized", "executed": "Executed",
                "rejected": "Rejected", "failed": "Failed", "cancelled": "Cancelled",
                "expired": "Expired",
            },
        )

    def test_every_target_is_a_select_option(self):
        """A mapped status the doctype cannot hold would fail on save."""
        self.assertLessEqual(set(REQUEST_STATUS_MAP.values()), set(_status_select_options("Ponto Payment Request")))
        self.assertLessEqual(set(LINK_STATUS_MAP.values()), set(_status_select_options("Ponto Payment Link")))
        self.assertIn("Expired", _status_select_options("Ponto Payment Request"))

    def test_the_four_writers_use_the_shared_module(self):
        """Import identity, plus no private copy of a map left in any writer."""
        self.assertIs(webhook_handlers.map_request_status, status_maps.map_request_status)
        self.assertIs(webhook_handlers.map_link_status, status_maps.map_link_status)
        self.assertIs(ponto_payment_request.map_request_status, status_maps.map_request_status)
        self.assertIs(ponto_payment_link.map_link_status, status_maps.map_link_status)
        self.assertIs(ponto_payment_request.is_refused_move, status_maps.is_refused_move)
        self.assertIs(ponto_payment_link.is_refused_move, status_maps.is_refused_move)
        for module in (webhook_handlers, ponto_payment_request, ponto_payment_link):
            self.assertFalse(_private_status_maps(inspect.getsource(module)), module.__name__)

    def test_private_map_scan_catches_a_planted_copy(self):
        """Control for the scan above: it must see a private map when one exists."""
        planted = 'def f(s):\n    return {"unsigned": "Pending", "signed": "Signed"}.get(s)\n'
        self.assertTrue(_private_status_maps(planted))
        self.assertFalse(_private_status_maps("x = {'a': 1}\n"))

    def test_is_refused_move_rulings(self):
        """The pure rule, cell by cell (A and B of the 2026-10-31 ruling)."""
        for new in ("Pending", "Signed", "Cancelled", "Rejected", "Failed", "Expired"):
            self.assertTrue(is_refused_move("Executed", new), new)
        self.assertFalse(is_refused_move("Executed", "Executed"))
        for src in ("Cancelled", "Rejected", "Failed", "Expired"):
            self.assertTrue(is_refused_move(src, "Pending"), src)
            self.assertTrue(is_refused_move(src, "Pending Authorization"), src)
            self.assertTrue(is_refused_move(src, "Draft"), src)
            self.assertFalse(is_refused_move(src, "Signed"), src)
            self.assertFalse(is_refused_move(src, "Authorized"), src)
            self.assertFalse(is_refused_move(src, "Executed"), src)
        self.assertTrue(is_refused_move("Signed", "Pending"))
        self.assertTrue(is_refused_move("Authorized", "Pending Authorization"))
        self.assertFalse(is_refused_move("Signed", "Cancelled"))


class TestPathsAgree(_Base):
    def test_request_poll_and_webhook_agree_on_every_ponto_status(self):
        for ponto_status in PONTO_INPUTS + ["unsigned", "someNewStatus"]:
            if ponto_status == "executed":
                continue  # covered by the tables, with the Payment Entry spy
            with self.subTest(ponto_status=ponto_status):
                self.assertEqual(
                    self._poll_request(self._request(), ponto_status),
                    self._webhook_request(self._request(), ponto_status),
                )

    def test_link_poll_and_webhook_agree_on_every_ponto_status(self):
        for ponto_status in PONTO_INPUTS + ["unsigned", "authorized", "someNewStatus"]:
            if ponto_status == "executed":
                continue
            with self.subTest(ponto_status=ponto_status):
                self.assertEqual(
                    self._poll_link(self._link(), ponto_status),
                    self._webhook_link(self._link(), ponto_status),
                )

    def test_unknown_status_keeps_current_status_on_both_paths(self):
        self.assertEqual(self._poll_request(self._request("Signed"), "someNewStatus"), "Signed")
        self.assertEqual(self._poll_link(self._link("Authorized"), "someNewStatus"), "Authorized")
        self.assertEqual(self._webhook_request(self._request("Signed"), "someNewStatus"), "Signed")
        self.assertEqual(self._webhook_link(self._link("Authorized"), "someNewStatus"), "Authorized")

    def test_link_client_closed_marker_leaves_status_unchanged_1840(self):
        """Maintainer ruling 2026-10-31 (#1840): the betaalverzoek client's own ``closed``
        marker (closedAt without a status; it also covers rejected/expired) is never
        Executed. The status stays as it was. This replaces the test that pinned the old
        ``closed`` -> Executed behaviour; the Payment Entry side, with a real invoice and
        real Payment Entry rows, is in test_ponto_status_poll.TestLinkPaymentEntryViaPoll.
        """
        for start in ("Pending Authorization", "Authorized"):
            with self.subTest(start=start):
                self.assertEqual(self._poll_link(self._link(start), "closed"), start)


class TestWebhookReportsRefusedMovesHonestly(_Base):
    def test_update_status_from_webhook_returns_whether_it_moved(self):
        req = self._request("Signed")
        self.assertFalse(req.update_status_from_webhook("Pending"))
        self.assertFalse(req.update_status_from_webhook("Signed"))
        self.assertTrue(req.update_status_from_webhook("Rejected"))
        link = self._link("Authorized")
        self.assertFalse(link.update_status_from_webhook("Pending Authorization"))
        self.assertFalse(link.update_status_from_webhook("Authorized"))
        self.assertTrue(link.update_status_from_webhook("Rejected"))

    def test_request_refusal_is_reported_not_claimed_as_an_update(self):
        doc = self._request("Executed")
        with patch.object(PontoPaymentRequest, "create_payment_entry"):
            result = self._webhook_request_result(doc, "cancelled")
        self.assertEqual(result["updated_requests"], [])
        self.assertEqual(result["refused_requests"], [{"name": doc.name, "status": "Executed"}])

    def test_request_move_is_reported_as_updated(self):
        doc = self._request("Pending")
        result = self._webhook_request_result(doc, "signed")
        self.assertEqual(result["updated_requests"], [doc.name])
        self.assertIsNone(result["refused_requests"])

    def test_link_refusal_is_reported_not_claimed_as_an_update(self):
        doc = self._link("Cancelled")
        result = _update_payment_link_status(doc.ponto_request_id, "pending")
        self.assertEqual(result["updated_links"], [])
        self.assertEqual(result["refused_links"], [{"name": doc.name, "status": "Cancelled"}])

    def test_link_move_is_reported_as_updated(self):
        doc = self._link("Pending Authorization")
        result = _update_payment_link_status(doc.ponto_request_id, "signed")
        self.assertEqual(result["updated_links"], [doc.name])
        self.assertIsNone(result["refused_links"])
