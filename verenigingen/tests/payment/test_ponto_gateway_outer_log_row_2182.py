# Copyright (c) 2026, Verenigingen
"""One failed Ponto payment-link creation through the donation gateway = ONE Error Log row (#2182).

`PontoGateway.process_payment` used to write `frappe.log_error(f"... {e}", "Ponto Gateway Error")`
(arguments swapped: the dynamic text became the title, the literal landed in the traceback field)
on top of the controller's own row, which already names the Payment Link. Two rows per failure.

Only the Ponto HTTP client is stubbed (the API-failure test); the gateway, the real Ponto
Payment Link doctype, secure_document_operation and submit run for real. The non-API test
makes `donation.db_set` raise to reach a failure the controller never logs.

Usage:
    bench --site test_site_9 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_ponto_gateway_outer_log_row_2182
"""

import types
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import payment_gateways as pg

LINK_CLIENT_PATH = (
    "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
)
API_FAILURE = "ponto upstream 503 (stubbed 2182)"
DB_FAILURE = "disk on fire (stubbed 2182)"
INSERT_FAILURE = "insert refused (stubbed 2182)"


class _FailingClient:
    def create_payment_request(self, **kwargs):
        raise RuntimeError(API_FAILURE)


class _OkResult:
    id = "pi_2182"
    redirect_link = "https://bank.test/authorize/pi_2182"


class _OkClient:
    def create_payment_request(self, **kwargs):
        return _OkResult()


class TestPontoGatewayOuterLogRow(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.expectErrorLog(
            "Ponto payment link creation failed", "Ponto Gateway Error", "Ponto Gateway - Insert Error", "2182"
        )

    def _mark(self):
        # The table holds thousands of rows, so remember the newest creation stamp and
        # count rows strictly after it. Error Log is MyISAM: rows are visible regardless of rollback.
        return frappe.db.sql("select max(creation) from `tabError Log`")[0][0]

    def _new_rows(self, before):
        rows = frappe.get_all(
            "Error Log",
            filters={"creation": [">", before]} if before else {},
            fields=["name", "method", "error"],
        )
        # Ignore unrelated rows (e.g. a worker) - only rows this failure could have written.
        return [r for r in rows if "Ponto" in (r.method or "") or "2182" in (r.error or "")]

    def _run(self, client, donation):
        settings = types.SimpleNamespace(company_account_holder="Org", company_iban="NL39RABO0300065264")
        with patch.object(pg, "get_payments_settings", return_value=settings), patch(
            LINK_CLIENT_PATH, return_value=client
        ):
            return pg.PontoGateway().process_payment(donation, {})

    def _donation(self):
        donor = self.create_test_donor(donor_name="Ponto 2182 Donor")
        return self.create_test_donation(amount=12.0, mode_of_payment="Bank Transfer", donor=donor.name, paid=0)

    def _track_links(self, donation):
        for name in frappe.get_all(
            "Ponto Payment Link", filters={"reference_name": donation.name}, pluck="name"
        ):
            self.track_doc("Ponto Payment Link", name)

    def test_api_failure_writes_exactly_one_row_naming_the_link(self):
        donation = self._donation()
        before = self._mark()

        result = self._run(_FailingClient(), donation)

        self._track_links(donation)
        self.assertEqual(result["status"], "error")
        link_name = frappe.get_all("Ponto Payment Link", filters={"reference_name": donation.name}, pluck="name")[0]
        rows = self._new_rows(before)
        self.assertEqual(len(rows), 1, f"one failure must write one row, got {[r.method for r in rows]}")
        self.assertIn(link_name, rows[0].method)
        self.assertIn(API_FAILURE, rows[0].error or "")

    def test_donation_writeback_failure_leaves_one_row_with_title_and_traceback(self):
        donation = self._donation()
        before = self._mark()

        # Mock justified: no other seam makes the write after a successful submit fail.
        with patch.object(donation, "db_set", side_effect=RuntimeError(DB_FAILURE)):
            result = self._run(_OkClient(), donation)

        self._track_links(donation)
        self.assertEqual(result["status"], "error")
        rows = self._new_rows(before)
        self.assertEqual(len(rows), 1, f"expected one row, got {[r.method for r in rows]}")
        row = rows[0]
        # Title carries the document, the cause and a traceback sit in the error field.
        self.assertIn(donation.name, row.method)
        self.assertNotIn(DB_FAILURE, row.method, "the dynamic text must not land in the title")
        self.assertIn(DB_FAILURE, row.error or "")
        self.assertIn("Traceback", row.error or "")

    def test_insert_refusal_row_has_title_and_message_the_right_way_round(self):
        donation = self._donation()
        before = self._mark()
        refusal = types.SimpleNamespace(success=False, errors=[INSERT_FAILURE])

        # Mock justified: secure_document_operation is the app's wrapper and has no seam
        # that makes a plain insert refuse for a donation like this one.
        with patch.object(pg, "secure_document_operation", return_value=refusal):
            result = self._run(_OkClient(), donation)

        self.assertEqual(result["status"], "error")
        rows = self._new_rows(before)
        self.assertEqual(len(rows), 1, f"expected one row, got {[r.method for r in rows]}")
        self.assertIn(donation.name, rows[0].method)
        self.assertNotIn(INSERT_FAILURE, rows[0].method, "the dynamic text must not land in the title")
        self.assertIn(INSERT_FAILURE, rows[0].error or "")

    def test_timestamp_mismatch_at_submit_leaves_one_row_with_the_donation_name(self):
        """A REAL TimestampMismatchError from submit() (a ValidationError the controller never logs).

        Probe shortcut, stated: the row's `modified` is bumped between insert and submit by a
        wrapper around the real secure_document_operation; the controller is not touched.
        """
        donation = self._donation()
        before = self._mark()
        real_op = pg.secure_document_operation

        def insert_then_touch(*args, **kwargs):
            result = real_op(*args, **kwargs)
            frappe.db.set_value(
                "Ponto Payment Link", kwargs["doc"].name, "modified", "2099-01-01 00:00:00", update_modified=False
            )
            return result

        with patch.object(pg, "secure_document_operation", side_effect=insert_then_touch):
            result = self._run(_OkClient(), donation)

        self._track_links(donation)
        self.assertEqual(result["status"], "error")
        rows = self._new_rows(before)
        self.assertEqual(len(rows), 1, f"expected one row, got {[r.method for r in rows]}")
        self.assertIn(donation.name, rows[0].method)
        self.assertIn("TimestampMismatchError", rows[0].error or "")
