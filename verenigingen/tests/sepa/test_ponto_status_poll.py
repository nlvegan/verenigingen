# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
#1885: the scheduled Ponto status poll.

The job is driven through the REAL scheduler entrypoint
(``frappe.get_attr(<path from hooks>)()`` as Administrator), against the real
doctype controllers, the real ``refresh_status`` decorator stack and the real
status maps. The ONLY stub is the Ponto HTTP client factory. Where a row becomes
Executed, ``create_payment_entry`` / ``process_payment_received`` are replaced by a
spy so Payment Entry attempts can be counted exactly (the Payment Entry itself is
covered by test_ponto_payment_request_paid_after_pe).

Fixture shortcuts, stated: rows are ``insert()``-ed directly at the starting status
(docstatus 0) rather than submitted, because submit calls Ponto; ``creation`` is
back-dated with ``db.set_value`` to make a row "too old"; Ponto Settings credentials
are set on the Single so the job's "is Ponto configured" gate passes.

Usage:
    bench --site test_site_13 run-tests --app verenigingen \\
        --module verenigingen.tests.sepa.test_ponto_status_poll
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_to_date, now_datetime, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.payment.test_ponto_payment_entry_creation import _ensure_ponto_clearing_account
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.doctype.ponto_payment_request.ponto_payment_request import (
    PontoPaymentRequest,
)
from verenigingen.verenigingen_payments.ponto.services import status_poll_service

PAY_CLIENT = "verenigingen.verenigingen_payments.ponto.clients.payment_client.get_payment_client"
LINK_CLIENT = (
    "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
)
JOB = "verenigingen.verenigingen_payments.ponto.services.status_poll_service.poll_open_ponto_payment_statuses"
ERROR_TITLE_PREFIX = "Ponto status poll failed"


class _PollBase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._configure_ponto(True)
        self._age_out_preexisting_open_rows()

    # --- fixtures -----------------------------------------------------------

    def _age_out_preexisting_open_rows(self):
        """Rows other suites left open on this site would be polled too, so push
        them out of the window. Rolled back with the test class (no commit here)."""
        long_ago = add_to_date(now_datetime(), days=-400)
        for doctype, statuses, _id_field in status_poll_service._POLLED:
            frappe.db.set_value(
                doctype, {"status": ["in", statuses]}, "creation", long_ago, update_modified=False
            )

    def _configure_ponto(self, configured):
        settings = frappe.get_single("Ponto Settings")
        settings.use_ibanity_mtls = 0
        settings.sandbox_mode = 1
        settings.sandbox_client_id = "poll-test-id" if configured else ""
        settings.sandbox_client_secret = "poll-test-secret" if configured else ""
        settings.flags.ignore_validate = True
        settings.save()

    def _make_poll_request(self, status="Pending", ponto_id=True, age_days=0):
        doc = frappe.new_doc("Ponto Payment Request")
        doc.update(dict(
            ponto_account="test-account-id", amount=50.0, currency="EUR",
            creditor_name="Test Creditor", creditor_iban="NL91ABNA0417164300",
            remittance_info="poll", status=status,
            ponto_payment_id=f"pay-{frappe.generate_hash(length=10)}" if ponto_id else None,
        ))
        doc.insert()
        return self._age(doc, age_days)

    def _make_poll_link(self, status="Pending Authorization", ponto_id=True, age_days=0):
        doc = frappe.new_doc("Ponto Payment Link")
        doc.update(dict(
            payment_type="One-Time", amount=25.0, currency="EUR", description="poll",
            creditor_name="Vereniging", creditor_iban="NL91ABNA0417164300", status=status,
            ponto_request_id=f"req-{frappe.generate_hash(length=10)}" if ponto_id else None,
        ))
        doc.insert()
        return self._age(doc, age_days)

    def _age(self, doc, age_days):
        if age_days:
            frappe.db.set_value(
                doc.doctype, doc.name, "creation",
                add_to_date(now_datetime(), days=-age_days), update_modified=False,
            )
        return doc

    def _poll_row_status(self, doc):
        return frappe.db.get_value(doc.doctype, doc.name, "status")

    def _pay_client(self, by_id):
        """Payment client stub: ``by_id`` maps ponto_payment_id -> Ponto status or an Exception."""
        client = MagicMock()

        def get_payment(account_id, payment_id):
            outcome = by_id.get(payment_id, "pending")
            if isinstance(outcome, Exception):
                raise outcome
            return SimpleNamespace(status=outcome)

        client.get_payment.side_effect = get_payment
        return client

    def _link_client(self, by_id):
        client = MagicMock()

        def get_payment_request(request_id):
            outcome = by_id.get(request_id, "pending")
            if isinstance(outcome, Exception):
                raise outcome
            return SimpleNamespace(status=outcome, debtor_name=None, debtor_iban=None, debtor_bank=None)

        client.get_payment_request.side_effect = get_payment_request
        return client

    def _run_job(self, pay=None, link=None):
        """Run the job via the hooked dotted path, as the scheduler does."""
        self.assertEqual(frappe.session.user, "Administrator")  # the scheduler's user
        pay = pay or self._pay_client({})
        link = link or self._link_client({})
        with patch(PAY_CLIENT, return_value=pay), patch(LINK_CLIENT, return_value=link):
            frappe.get_attr(JOB)()
        return pay, link

    def _poll_errors(self):
        return frappe.db.count("Error Log", {"method": ["like", f"{ERROR_TITLE_PREFIX}%"]})


class TestPontoStatusPoll(_PollBase):
    # --- selection ----------------------------------------------------------

    def test_selects_exactly_the_open_rows_inside_the_window(self):
        open_requests = [self._make_poll_request("Pending"), self._make_poll_request("Signed")]
        controls = [
            self._make_poll_request("Executed"), self._make_poll_request("Cancelled"), self._make_poll_request("Expired"),
            self._make_poll_request("Pending", age_days=status_poll_service.STALENESS_WINDOW_DAYS + 5),
            self._make_poll_request("Pending", ponto_id=False),
        ]
        open_links = [self._make_poll_link("Pending Authorization"), self._make_poll_link("Authorized")]
        link_controls = [
            self._make_poll_link("Executed"), self._make_poll_link("Cancelled"), self._make_poll_link("Expired"),
            self._make_poll_link("Pending Authorization", age_days=status_poll_service.STALENESS_WINDOW_DAYS + 5),
            self._make_poll_link("Pending Authorization", ponto_id=False),
        ]
        pay, link = self._run_job()

        polled = {c.kwargs["payment_id"] for c in pay.get_payment.call_args_list}
        self.assertEqual(polled, {d.ponto_payment_id for d in open_requests})
        self.assertFalse(polled & {d.ponto_payment_id for d in controls if d.ponto_payment_id})
        polled_links = {c.args[0] for c in link.get_payment_request.call_args_list}
        self.assertEqual(polled_links, {d.ponto_request_id for d in open_links})
        self.assertFalse(polled_links & {d.ponto_request_id for d in link_controls if d.ponto_request_id})

    def test_staleness_boundary_row_just_inside_is_polled(self):
        inside = self._make_poll_request("Pending", age_days=status_poll_service.STALENESS_WINDOW_DAYS - 1)
        pay, _ = self._run_job()
        self.assertEqual(
            {c.kwargs["payment_id"] for c in pay.get_payment.call_args_list}, {inside.ponto_payment_id}
        )

    def test_executed_row_is_never_touched(self):
        executed = self._make_poll_request("Executed")
        modified = frappe.db.get_value(executed.doctype, executed.name, "modified")
        pay = self._pay_client({executed.ponto_payment_id: "cancelled"})
        self._run_job(pay=pay)
        pay.get_payment.assert_not_called()
        self.assertEqual(self._poll_row_status(executed), "Executed")
        self.assertEqual(frappe.db.get_value(executed.doctype, executed.name, "modified"), modified)

    def test_poll_moves_open_rows_with_the_shared_map(self):
        request = self._make_poll_request("Pending")
        link = self._make_poll_link("Pending Authorization")
        self._run_job(
            pay=self._pay_client({request.ponto_payment_id: "signed"}),
            link=self._link_client({link.ponto_request_id: "signed"}),
        )
        self.assertEqual(self._poll_row_status(request), "Signed")
        self.assertEqual(self._poll_row_status(link), "Authorized")

    # --- isolation ----------------------------------------------------------

    def test_one_failing_row_does_not_stop_the_others(self):
        self.expectErrorLog(ERROR_TITLE_PREFIX, "Ponto status refresh failed", "Ponto payment link status refresh failed")
        before = self._poll_errors()
        broken = self._make_poll_request("Pending")
        healthy = self._make_poll_request("Pending")
        link_broken = self._make_poll_link("Pending Authorization")
        link_healthy = self._make_poll_link("Pending Authorization")
        self._run_job(
            pay=self._pay_client({
                broken.ponto_payment_id: RuntimeError("ponto down"),
                healthy.ponto_payment_id: "signed",
            }),
            link=self._link_client({
                link_broken.ponto_request_id: RuntimeError("ponto down"),
                link_healthy.ponto_request_id: "signed",
            }),
        )
        self.assertEqual(self._poll_row_status(healthy), "Signed")
        self.assertEqual(self._poll_row_status(broken), "Pending")
        self.assertEqual(self._poll_row_status(link_healthy), "Authorized")
        self.assertEqual(self._poll_row_status(link_broken), "Pending Authorization")
        # One poll Error Log row per failed row (refresh_status writes its own too).
        self.assertEqual(self._poll_errors() - before, 2)

    def test_failed_payment_entry_rolls_the_status_back_and_batch_continues(self):
        self.expectErrorLog(ERROR_TITLE_PREFIX, "Ponto status refresh failed", "Ponto payment link status refresh failed")
        failing = self._make_poll_request("Signed")
        healthy = self._make_poll_request("Signed")
        pay = self._pay_client({failing.ponto_payment_id: "executed", healthy.ponto_payment_id: "executed"})

        def pe(doc):
            if doc.name == failing.name:
                raise frappe.ValidationError("no bank mapping")

        with patch.object(PontoPaymentRequest, "create_payment_entry", autospec=True, side_effect=pe) as spy:
            self._run_job(pay=pay)
        self.assertEqual(spy.call_count, 2)
        self.assertEqual(self._poll_row_status(failing), "Signed")  # not stuck Executed (#1323)
        self.assertEqual(self._poll_row_status(healthy), "Executed")

    # --- configuration ------------------------------------------------------

    def test_not_configured_returns_quietly(self):
        self._make_poll_request("Pending")
        self._make_poll_link("Pending Authorization")
        self._configure_ponto(False)
        before_errors = frappe.db.count("Error Log")
        pay, link = self._run_job()
        pay.get_payment.assert_not_called()
        link.get_payment_request.assert_not_called()
        self.assertEqual(frappe.db.count("Error Log"), before_errors)

    def test_no_open_rows_never_builds_a_client(self):
        with patch(PAY_CLIENT) as pay_factory, patch(LINK_CLIENT) as link_factory:
            frappe.get_attr(JOB)()
        pay_factory.assert_not_called()
        link_factory.assert_not_called()

    # --- Payment Entry idempotency -----------------------------------------

    def test_executed_via_poll_attempts_exactly_one_payment_entry(self):
        doc = self._make_poll_request("Signed")
        pay = self._pay_client({doc.ponto_payment_id: "executed"})
        # Mock justified: spy on the Payment Entry creator only.
        with patch.object(PontoPaymentRequest, "create_payment_entry") as spy:
            self._run_job(pay=pay)
            self.assertEqual(spy.call_count, 1)
            self._run_job(pay=pay)  # a second tick: the row is Executed, not selected
            self.assertEqual(spy.call_count, 1)
        self.assertEqual(self._poll_row_status(doc), "Executed")

    def test_webhook_executed_first_then_poll_attempts_zero_more(self):
        doc = self._make_poll_request("Signed")
        pay = self._pay_client({doc.ponto_payment_id: "executed"})
        with patch.object(PontoPaymentRequest, "create_payment_entry") as spy:
            doc.reload().update_status_from_webhook("Executed")
            self.assertEqual(spy.call_count, 1)
            self._run_job(pay=pay)
            self.assertEqual(spy.call_count, 1)
        pay.get_payment.assert_not_called()

    # --- registration -------------------------------------------------------

    def test_job_is_registered_hourly_and_resolves(self):
        events = frappe.get_hooks("scheduler_events")
        self.assertIn(JOB, events.get("hourly", []))
        self.assertTrue(callable(frappe.get_attr(JOB)))

    def test_many_open_rows_are_not_refused_by_the_security_rate_limit(self):
        rows = [self._make_poll_request("Pending") for _ in range(25)]
        pay = self._pay_client({d.ponto_payment_id: "signed" for d in rows})
        before = self._poll_errors()
        self._run_job(pay=pay)
        self.assertEqual({self._poll_row_status(d) for d in rows}, {"Signed"})
        self.assertEqual(self._poll_errors(), before)


class TestLinkPaymentEntryViaPoll(_PollBase):
    """#1840 + #1885 with REAL Payment Entry rows: a link with a submitted Sales
    Invoice would book one under the old ``closed`` -> Executed mapping."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()
        cls.ponto_account = _ensure_ponto_clearing_account(cls.company)

    def _invoiced_link(self, status="Pending Authorization", amount=30.0):
        sepa = SEPATestDataFactory(seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True)
        member = sepa.create_test_member(first_name="PollPE")
        if not member.customer:
            member.db_set("customer", sepa.create_test_customer(customer_name=f"Cust {member.full_name}").name)
            member.reload()
        invoice = sepa.create_test_sales_invoice(
            customer=member.customer, grand_total=amount * 2, status="Unpaid", company=self.company,
            posting_date=today(), due_date=today(), is_membership_invoice=1, submit=True,
        )
        link = self._make_poll_link(status)
        # The invoice is twice the link amount, so a second booking would NOT be refused as
        # "already paid" and a double-booking mutant is visible as a second Payment Entry.
        link.db_set({"sales_invoice": invoice.name, "member": member.name, "amount": amount})
        return link.reload()

    def _payment_entries(self, link):
        return frappe.get_all("Payment Entry", filters={"reference_no": link.ponto_request_id}, pluck="name")

    def test_closed_marker_from_the_real_client_parser_changes_nothing(self):
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            PaymentInitiationRequest,
        )

        link = self._invoiced_link()
        parsed = PaymentInitiationRequest.from_api_response(
            {"id": link.ponto_request_id, "attributes": {"closedAt": "2026-01-02T10:00:00Z"}}
        )
        self.assertEqual(parsed.status, "closed")  # premise: the marker really is produced
        client = MagicMock()
        client.get_payment_request.return_value = parsed
        with patch(LINK_CLIENT, return_value=client):
            frappe.get_doc("Ponto Payment Link", link.name).refresh_status()  # manual path
            self._run_job(link=client)  # scheduled path
        self.assertEqual(self._poll_row_status(link), "Pending Authorization")
        self.assertEqual(self._payment_entries(link), [])
        self.assertFalse(frappe.db.get_value("Ponto Payment Link", link.name, "payment_entry"))

    def test_explicit_executed_status_books_exactly_one_payment_entry(self):
        link = self._invoiced_link()
        client = self._link_client({link.ponto_request_id: "executed"})
        self._run_job(link=client)
        self.assertEqual(self._poll_row_status(link), "Executed")
        entries = self._payment_entries(link)
        self.assertEqual(len(entries), 1)
        self.assertEqual(frappe.db.get_value("Ponto Payment Link", link.name, "payment_entry"), entries[0])
        self._run_job(link=client)  # second tick: Executed is not selected
        self.assertEqual(self._payment_entries(link), entries)

    def test_webhook_booked_first_then_poll_books_nothing_more(self):
        link = self._invoiced_link()
        self.assertTrue(frappe.get_doc("Ponto Payment Link", link.name).update_status_from_webhook("Executed"))
        entries = self._payment_entries(link)
        self.assertEqual(len(entries), 1)
        client = self._link_client({link.ponto_request_id: "executed"})
        self._run_job(link=client)
        client.get_payment_request.assert_not_called()
        self.assertEqual(self._payment_entries(link), entries)
