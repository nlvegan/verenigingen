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

import inspect
import json

import frappe
import requests
from frappe.utils import add_to_date, now_datetime, today
from rq.timeouts import JobTimeoutException

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.payment.test_ponto_payment_entry_creation import _ensure_ponto_clearing_account
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.doctype.ponto_payment_request.ponto_payment_request import (
    PontoPaymentRequest,
)
from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError, PontoRateLimitError
from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient
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
        self._clear_poll_cache()
        self._age_out_preexisting_open_rows()
        self.addCleanup(self._clear_poll_cache)

    # --- fixtures -----------------------------------------------------------

    def _age_out_preexisting_open_rows(self):
        """Rows other suites left open on this site would be polled too, so push
        them out of the window. Rolled back with the test class (no commit here)."""
        long_ago = add_to_date(now_datetime(), days=-400)
        for doctype, statuses, _id_field in status_poll_service._POLLED:
            frappe.db.set_value(
                doctype, {"status": ["in", statuses]}, "creation", long_ago, update_modified=False
            )

    def _configure_ponto(self, configured, mtls=True, mapping=True):
        """Ponto Settings as the clients need it: mTLS + Ibanity credentials + an enabled
        account mapping (the Link client's ``_verify_pis_enabled``). ``mtls=False`` gives
        a MyPonto-credentials-only site, where only the Request client can start."""
        settings = frappe.get_single("Ponto Settings")
        settings.use_ibanity_mtls = 1 if mtls else 0
        settings.sandbox_mode = 1
        settings.sandbox_client_id = "poll-test-id" if configured else ""
        settings.sandbox_client_secret = "poll-test-secret" if configured else ""
        settings.ibanity_client_id = "poll-test-ibanity" if configured else ""
        settings.ibanity_client_secret = "poll-test-ibanity-secret" if configured else ""
        settings.set("bank_account_mappings", [])
        if mapping:
            settings.append("bank_account_mappings", {"ponto_account_id": "test-account-id", "enabled": 1})
        settings.flags.ignore_validate = True
        settings.flags.ignore_links = True
        settings.flags.ignore_mandatory = True
        settings.save()

    def _clear_poll_cache(self):
        for doctype, _s, _i in status_poll_service._POLLED:
            frappe.cache().delete_value(status_poll_service._cursor_cache_key(doctype))
            for kind in ("unconfigured", "truncated"):
                frappe.cache().delete_value(f"ponto_status_poll_logged:{kind}:{doctype}")
        frappe.cache().delete_value("ponto_status_poll_rotation")

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

    def _all_ponto_errors(self):
        return ERROR_TITLE_PREFIX, "Ponto status poll stopped early", "status refresh failed"

    def _poll_errors(self):
        return frappe.db.count("Error Log", {"method": ["like", f"{ERROR_TITLE_PREFIX}%"]})


class TestPontoStatusPoll(_PollBase):
    # --- selection ----------------------------------------------------------

    def _cancelled_docstatus(self, doc):
        """Fixture shortcut: an open-looking status on a docstatus-2 row (db.set_value)."""
        frappe.db.set_value(doc.doctype, doc.name, "docstatus", 2, update_modified=False)
        return doc

    def test_selects_exactly_the_open_rows_inside_the_window(self):
        errors_before = self._poll_errors()
        cancelled_request = self._cancelled_docstatus(self._make_poll_request("Pending"))
        cancelled_link = self._cancelled_docstatus(self._make_poll_link("Pending Authorization"))
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
        # A docstatus-2 row and a row with no Ponto id must be filtered out BEFORE
        # refresh_status: it would throw on them, which writes an Error Log row.
        self.assertNotIn(cancelled_request.ponto_payment_id, polled)
        self.assertNotIn(cancelled_link.ponto_request_id, polled_links)
        self.assertEqual(self._poll_errors(), errors_before)

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

    def _unconfigured_logs(self):
        return frappe.db.count("Error Log", {"method": ["like", "Ponto status poll skipped%"]})

    def test_not_configured_skips_and_logs_once_a_day(self):
        self._make_poll_request("Pending")
        self._make_poll_link("Pending Authorization")
        self._configure_ponto(False)
        before = self._unconfigured_logs()
        with self.assertErrorLog("Ponto status poll skipped"):
            pay, link = self._run_job()
        pay.get_payment.assert_not_called()
        link.get_payment_request.assert_not_called()
        self.assertEqual(self._unconfigured_logs() - before, 2)  # one per doctype
        with self.assertNoErrorLog():
            self._run_job()
        self.assertEqual(self._unconfigured_logs() - before, 2)  # not again today

    def test_each_doctype_is_gated_on_what_its_client_needs(self):
        """mTLS off: the Request client starts (OAuth credentials), the Link client
        refuses (``_verify_pis_enabled``), so only Requests are polled."""
        self.expectErrorLog("Ponto status poll skipped")
        request = self._make_poll_request("Pending")
        link = self._make_poll_link("Pending Authorization")
        self._configure_ponto(True, mtls=False)
        pay, link_client = self._run_job()
        self.assertEqual([c.kwargs["payment_id"] for c in pay.get_payment.call_args_list][-1:], [request.ponto_payment_id])
        link_client.get_payment_request.assert_not_called()
        self.assertEqual(self._poll_row_status(link), "Pending Authorization")
        # mTLS on but no enabled account mapping: still not the Link client's predicate.
        self._configure_ponto(True, mapping=False)
        _pay, link_client = self._run_job()
        link_client.get_payment_request.assert_not_called()

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

    # --- fairness, caps, outage budget -----------------------------------------

    def _tick_polled_ids(self, pay_by_id=None, ticks=1):
        pay = self._pay_client(pay_by_id or {})
        runs = []
        for _ in range(ticks):
            pay.get_payment.reset_mock()
            self._run_job(pay=pay)
            runs.append([c.kwargs["payment_id"] for c in pay.get_payment.call_args_list])
        return runs

    def test_batch_cap_limits_each_run_and_logs_one_truncation_row(self):
        self.expectErrorLog("Ponto status poll batch truncated")
        rows = [self._make_poll_request("Pending", age_days=20 - i) for i in range(5)]
        before = frappe.db.count("Error Log", {"method": ["like", "Ponto status poll batch truncated%"]})
        with patch.object(status_poll_service, "BATCH_LIMIT", 3):
            (first,) = self._tick_polled_ids()
        self.assertEqual(first, [d.ponto_payment_id for d in rows[:3]])  # oldest first, capped
        after = frappe.db.count("Error Log", {"method": ["like", "Ponto status poll batch truncated%"]})
        self.assertEqual(after - before, 1)

    def test_rows_past_the_cap_are_not_starved(self):
        """#1885 review F2: 101 abandoned rows plus 1 fresh one never polled the fresh
        one under oldest-first. Cap 3 here, so 5 abandoned + 1 fresh, Requests (which,
        unlike Links, do not bump ``modified`` on an unchanged poll)."""
        self.expectErrorLog("Ponto status poll batch truncated")
        zombies = [self._make_poll_request("Pending", age_days=25 - i) for i in range(5)]
        fresh = self._make_poll_request("Pending")
        with patch.object(status_poll_service, "BATCH_LIMIT", 3):
            first, second = self._tick_polled_ids({fresh.ponto_payment_id: "signed"}, ticks=2)
        self.assertEqual(first, [d.ponto_payment_id for d in zombies[:3]])
        self.assertIn(fresh.ponto_payment_id, second)
        self.assertEqual(self._poll_row_status(fresh), "Signed")

    def test_total_outage_stops_after_consecutive_failures_with_one_summary_row(self):
        self.expectErrorLog(
            ERROR_TITLE_PREFIX, "Ponto status poll stopped early", "Ponto status refresh failed",
            "Ponto payment link status refresh failed",
        )
        for _ in range(4):
            self._make_poll_request("Pending")
            self._make_poll_link("Pending Authorization")
        down = ConnectionError("simulated outage")
        pay = MagicMock()
        pay.get_payment.side_effect = down
        link = MagicMock()
        link.get_payment_request.side_effect = down
        before = self._poll_errors()
        stops_before = frappe.db.count("Error Log", {"method": "Ponto status poll stopped early"})
        self._run_job(pay=pay, link=link)
        limit = status_poll_service.MAX_CONSECUTIVE_OUTAGE_FAILURES
        self.assertEqual(pay.get_payment.call_count + link.get_payment_request.call_count, limit)
        self.assertEqual(self._poll_errors() - before, limit)  # one per failed row ...
        stops = frappe.db.count("Error Log", {"method": "Ponto status poll stopped early"})
        self.assertEqual(stops - stops_before, 1)  # ... plus ONE summary, not one per skipped row

    def test_a_success_resets_the_consecutive_failure_count(self):
        self.expectErrorLog(ERROR_TITLE_PREFIX, "Ponto status refresh failed")
        rows = [self._make_poll_request("Pending", age_days=20 - i) for i in range(6)]
        outcomes = {d.ponto_payment_id: ConnectionError("down") for d in rows}
        outcomes[rows[2].ponto_payment_id] = "pending"  # a success between failures
        outcomes[rows[5].ponto_payment_id] = "pending"
        (polled,) = self._tick_polled_ids(outcomes)
        self.assertEqual(len(polled), 6)  # never 3 failures in a row

    def test_wall_clock_budget_stops_the_run_with_one_summary_row(self):
        self.expectErrorLog("Ponto status poll stopped early")
        for i in range(5):
            self._make_poll_request("Pending", age_days=20 - i)
        ticks = iter(range(0, 10_000, 40))  # fake clock: every reading is 40 s later
        stops_before = frappe.db.count("Error Log", {"method": "Ponto status poll stopped early"})
        with patch.object(status_poll_service, "_monotonic", lambda: next(ticks)):
            (polled,) = self._tick_polled_ids()
        # deadline = 0 + 120; readings 40, 80 allow rows 1 and 2, reading 120 stops.
        self.assertEqual(len(polled), 2)
        stops = frappe.db.count("Error Log", {"method": "Ponto status poll stopped early"})
        self.assertEqual(stops - stops_before, 1)

    def test_a_deadlock_aborts_the_run_instead_of_being_swallowed(self):
        """``refresh_status`` wraps everything in ``frappe.throw``; the deadlock must still
        escape (#1885 review F4), and later rows must not be polled against a dead transaction."""
        self.expectErrorLog("Ponto status refresh failed")
        first = self._make_poll_request("Pending", age_days=5)
        second = self._make_poll_request("Pending", age_days=4)
        pay = self._pay_client({first.ponto_payment_id: frappe.QueryDeadlockError("1213")})
        with self.assertRaises(frappe.QueryDeadlockError):
            self._run_job(pay=pay)
        polled = [c.kwargs["payment_id"] for c in pay.get_payment.call_args_list]
        self.assertNotIn(second.ponto_payment_id, polled)

    def test_a_job_timeout_raised_by_the_client_call_is_never_swallowed_as_a_row_failure(self):
        """Covers a JobTimeoutException raised in the client call as refresh_status sees it
        (the stub replaces the client, so this is OUTSIDE with_retry). One raised inside
        with_retry mid-HTTP is swallowed by that layer first: #1919, not covered here."""
        self.expectErrorLog("Ponto status refresh failed")
        row = self._make_poll_request("Pending")
        pay = self._pay_client({row.ponto_payment_id: JobTimeoutException("300s")})
        with self.assertRaises(JobTimeoutException):
            self._run_job(pay=pay)

    def test_a_failed_row_is_rolled_back_to_its_savepoint(self):
        """A row that writes and then fails must leave nothing behind. The 'write' is made
        inside the stubbed client call (a db.set_value on a bystander row)."""
        self.expectErrorLog(ERROR_TITLE_PREFIX, "Ponto status refresh failed")
        bystander = self._make_poll_request("Executed")
        failing = self._make_poll_request("Pending")
        pay = MagicMock()

        def write_then_fail(account_id, payment_id):
            frappe.db.set_value(bystander.doctype, bystander.name, "remittance_info", "DIRTY")
            raise ConnectionError("down mid-write")

        pay.get_payment.side_effect = write_then_fail
        self._run_job(pay=pay)
        self.assertEqual(frappe.db.get_value(bystander.doctype, bystander.name, "remittance_info"), "poll")
        self.assertEqual(self._poll_row_status(failing), "Pending")

    # --- outage classification, rotation, cursor semantics -----------------------

    def _tick(self, pay=None, link=None):
        pay = pay or self._pay_client({})
        link = link or self._link_client({})
        pay.get_payment.reset_mock()
        link.get_payment_request.reset_mock()
        self._run_job(pay=pay, link=link)
        return (
            [c.kwargs["payment_id"] for c in pay.get_payment.call_args_list],
            [c.args[0] for c in link.get_payment_request.call_args_list],
        )

    def test_outage_failures_in_front_do_not_starve_the_other_doctype(self):
        """Probe E (review): 3 Requests whose client raises + 1 healthy Link. Requests-first
        every run polled the Link never. The doctype order now alternates."""
        self.expectErrorLog(*self._all_ponto_errors())
        bad = [self._make_poll_request("Pending", age_days=20 - i) for i in range(3)]
        link = self._make_poll_link("Pending Authorization")
        pay = self._pay_client({d.ponto_payment_id: ConnectionError("down") for d in bad})
        link_client = self._link_client({link.ponto_request_id: "signed"})
        for _ in range(2):
            self._tick(pay, link_client)
        self.assertEqual(self._poll_row_status(link), "Authorized")

    def test_data_errors_do_not_count_toward_the_outage_stop(self):
        self.expectErrorLog(*self._all_ponto_errors())
        bad = [self._make_poll_request("Pending", age_days=20 - i) for i in range(5)]
        link = self._make_poll_link("Pending Authorization")
        refused = PontoAPIError("not found", status_code=404)
        pay = self._pay_client({d.ponto_payment_id: refused for d in bad})
        link_client = self._link_client({link.ponto_request_id: "signed"})
        with patch.object(status_poll_service, "_rotated", lambda batches: batches):  # Requests first
            requests_polled, links_polled = self._tick(pay, link_client)
        self.assertEqual(len(requests_polled), 5)  # no stop after 3 data errors
        self.assertEqual(links_polled, [link.ponto_request_id])
        self.assertEqual(frappe.db.count("Error Log", {"method": "Ponto status poll stopped early"}), 0)

    def test_classification_on_exception_classes_not_message_text(self):
        """Class-level cases only. The wrapper-built chains that matter are driven through the
        REAL clients in TestRealClientClassification below."""
        for exc in [
            PontoRateLimitError("slow down"),
            PontoAPIError("boom", status_code=503),
            ConnectionError("x"),
            TimeoutError("x"),
            requests.ConnectionError("x"),
        ]:
            with self.subTest(exc=repr(exc)):
                self.assertTrue(status_poll_service._is_outage(exc))
        for exc in [
            PontoAPIError("outage outage 503 connection", status_code=404),  # misleading text
            PontoAPIError("bad", status_code=422),
            ValueError("503"),
            frappe.ValidationError("connection refused"),
            PontoAPIError("Missing 'id' field"),  # status-less, nothing deeper: data (ruling)
        ]:
            with self.subTest(exc=repr(exc)):
                self.assertFalse(status_poll_service._is_outage(exc))

    def test_outage_failures_across_both_doctypes_share_one_consecutive_count(self):
        self.expectErrorLog(*self._all_ponto_errors())
        for i in range(2):
            self._make_poll_request("Pending", age_days=20 - i)
            self._make_poll_link("Pending Authorization", age_days=20 - i)
        down = ConnectionError("down")
        pay, link = MagicMock(), MagicMock()
        pay.get_payment.side_effect = down
        link.get_payment_request.side_effect = down
        self._run_job(pay=pay, link=link)
        self.assertEqual(
            pay.get_payment.call_count + link.get_payment_request.call_count,
            status_poll_service.MAX_CONSECUTIVE_OUTAGE_FAILURES,
        )

    def test_doctype_order_alternates_between_runs(self):
        self._make_poll_request("Pending")
        self._make_poll_link("Pending Authorization")
        order = []
        for _ in range(2):
            pay, link = self._pay_client({}), self._link_client({})
            pay.get_payment.side_effect = lambda **k: order.append("request") or SimpleNamespace(status="pending")
            link.get_payment_request.side_effect = lambda r: order.append("link") or SimpleNamespace(
                status="pending", debtor_name=None, debtor_iban=None, debtor_bank=None
            )
            self._run_job(pay=pay, link=link)
        self.assertEqual(sorted(order[:2]), ["link", "request"])
        self.assertNotEqual(order[0], order[2])  # a different doctype goes first on run 2

    def test_run_budget_leaves_room_for_the_slowest_row(self):
        self.assertLess(
            status_poll_service.RUN_BUDGET_SECONDS + status_poll_service.MAX_ROW_SECONDS,
            status_poll_service.QUEUE_TIMEOUT_SECONDS,
        )

    def test_max_row_seconds_covers_the_clients_real_retry_and_timeout_settings(self):
        """MAX_ROW_SECONDS is derived from the client's settings here, not just asserted."""
        retry = PontoClient.DEFAULT_RETRY_CONFIG
        request_timeout = inspect.signature(PontoClient.get).parameters["timeout"].default
        token_timeout = 30  # PontoTokenManager's token POST ("timeout": 30 in token_manager.py)
        backoff = sum(min(retry.base_delay * 2**i, retry.max_delay) for i in range(retry.max_attempts - 1))
        worst = retry.max_attempts * request_timeout + 2 * backoff + token_timeout  # 2x: jitter allowance
        self.assertGreaterEqual(status_poll_service.MAX_ROW_SECONDS, worst)

    def test_cursor_resumes_after_the_last_attempted_row_of_an_early_stop(self):
        """Stopping early must not skip the unattempted rows: the next run starts right
        after the last row actually attempted (not after the batch's last row)."""
        self.expectErrorLog(*self._all_ponto_errors())
        rows = [self._make_poll_request("Pending", age_days=20 - i) for i in range(5)]
        down = {d.ponto_payment_id: ConnectionError("down") for d in rows[:3]}
        first, _ = self._tick(self._pay_client(down))
        self.assertEqual(first, [d.ponto_payment_id for d in rows[:3]])  # stopped after 3
        second, _ = self._tick(self._pay_client({}))
        self.assertEqual(second[:2], [d.ponto_payment_id for d in rows[3:]])

    def test_selection_wraps_round_to_the_head_when_the_tail_is_short(self):
        self.expectErrorLog("Ponto status poll batch truncated")
        rows = [self._make_poll_request("Pending", age_days=20 - i) for i in range(5)]
        with patch.object(status_poll_service, "BATCH_LIMIT", 3):
            first, _ = self._tick()
            second, _ = self._tick()
        self.assertEqual(first, [d.ponto_payment_id for d in rows[:3]])
        self.assertEqual(second, [d.ponto_payment_id for d in (rows[3], rows[4], rows[0])])

    def test_a_fatal_abort_does_not_advance_the_cursor(self):
        """The transaction rolls back with the abort, so the Redis cursor must not move
        past rows whose work was lost."""
        self.expectErrorLog("Ponto status poll batch truncated", "status refresh failed")
        rows = [self._make_poll_request("Pending", age_days=20 - i) for i in range(5)]
        key = status_poll_service._cursor_cache_key("Ponto Payment Request")
        with patch.object(status_poll_service, "BATCH_LIMIT", 2):
            self._tick()  # normal run: cursor now after rows[1]
            cursor = frappe.cache().get_value(key)
            self.assertEqual(cursor.name, rows[1].name)
            pay = self._pay_client({rows[3].ponto_payment_id: frappe.QueryDeadlockError("1213")})
            with self.assertRaises(frappe.QueryDeadlockError):
                self._run_job(pay=pay)
        self.assertEqual(frappe.cache().get_value(key).name, rows[1].name)

    def test_unconfigured_with_no_open_rows_logs_nothing(self):
        self._configure_ponto(False)
        with self.assertNoErrorLog():
            self._run_job()

    def test_truncation_row_is_written_once_a_day_not_every_run(self):
        self.expectErrorLog("Ponto status poll batch truncated")
        for i in range(4):
            self._make_poll_request("Pending", age_days=20 - i)
        like = {"method": ["like", "Ponto status poll batch truncated%"]}
        before = frappe.db.count("Error Log", like)
        with patch.object(status_poll_service, "BATCH_LIMIT", 2):
            self._tick()
            self._tick()
        self.assertEqual(frappe.db.count("Error Log", like) - before, 1)


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


class TestCursorIsBoundNotSpliced(_PollBase):
    def test_a_cursor_name_with_a_quote_and_backslash_cannot_reach_the_sql_text(self):
        rows = [self._make_poll_request("Pending", age_days=20 - i) for i in range(3)]
        nasty = frappe._dict(name="x' OR 1=1 -- \\", creation=add_to_date(now_datetime(), days=-30))
        frappe.cache().set_value(status_poll_service._cursor_cache_key("Ponto Payment Request"), nasty)
        statuses, id_field = ["Pending", "Signed"], "ponto_payment_id"
        with patch.object(status_poll_service, "BATCH_LIMIT", 10):
            batch = status_poll_service._next_batch("Ponto Payment Request", statuses, id_field)
        # Cursor older than every row: all three come back, in order, and nothing raised.
        self.assertEqual([r.name for r in batch if r.name in {d.name for d in rows}], [d.name for d in rows])


def _response(status, body=None, headers=None):
    response = requests.Response()
    response.status_code = status
    response._content = body if isinstance(body, bytes) else json.dumps(
        body if body is not None else {"errors": [{"code": "c", "detail": "d"}]}
    ).encode()
    response.headers.update({"Content-Type": "application/json", **(headers or {})})
    response.url = "https://ponto.invalid/x"
    return response


HEALTHY = {"data": {"id": "x", "attributes": {"status": "signed", "signedAt": "2026-01-01T00:00:00Z"}}}


class TestRealClientClassification(_PollBase):
    """Fault injected BELOW every layer that rewrites it (#1924): the real
    PontoPaymentClient / PontoBetaalverzoekClient / PontoClient run, and only
    ``requests.Session.get`` (and the token manager and sleep) are stubbed. The wrappers
    re-raise a status-less PontoAPIError, so only the root cause still knows 404 vs 503."""

    # name -> (what Session.get does, expected outage?)
    CASES = {
        "404": (lambda: _response(404), False),
        "400": (lambda: _response(400), False),
        "422": (lambda: _response(422), False),
        "401": (lambda: _response(401), True),
        "429": (lambda: _response(429, headers={"Retry-After": "3"}), True),
        "500": (lambda: _response(500), True),
        "503": (lambda: _response(503), True),
        "connection error": (requests.ConnectionError("refused"), True),
        "timeout": (requests.Timeout("slow"), True),
        "200 garbage": (lambda: _response(200, b"<html>not json</html>"), False),
    }

    def _fake_get(self, behaviour):
        def fake_get(session, url, **kwargs):
            if isinstance(behaviour, Exception):
                raise behaviour
            return behaviour()

        return fake_get

    def _real_clients(self, behaviour):
        """Context managers stubbing only the transport, token and sleep."""
        from contextlib import ExitStack

        stack = ExitStack()
        token = stack.enter_context(patch("verenigingen.verenigingen_payments.ponto.core.ponto_client.PontoTokenManager"))
        token.return_value.get_valid_token.return_value = "token"
        stack.enter_context(patch.object(requests.Session, "get", self._fake_get(behaviour)))
        stack.enter_context(patch("time.sleep"))
        return stack

    def test_each_failure_is_classified_through_the_real_request_client(self):
        self.expectErrorLog(*self._all_ponto_errors())
        for name, (behaviour, outage) in self.CASES.items():
            with self.subTest(case=name, doctype="request"):
                row = self._make_poll_request("Pending")
                with self._real_clients(behaviour):
                    got = status_poll_service._refresh_one(row.doctype, row.name)
                self.assertEqual(got, status_poll_service.OUTAGE if outage else status_poll_service.DATA_ERROR)

    def test_each_failure_is_classified_through_the_real_betaalverzoek_client(self):
        self.expectErrorLog(*self._all_ponto_errors())
        cases = dict(self.CASES)
        cases["200 empty data"] = (lambda: _response(200, {"data": {}}), False)
        for name, (behaviour, outage) in cases.items():
            with self.subTest(case=name, doctype="link"):
                row = self._make_poll_link("Pending Authorization")
                with self._real_clients(behaviour):
                    got = status_poll_service._refresh_one(row.doctype, row.name)
                self.assertEqual(got, status_poll_service.OUTAGE if outage else status_poll_service.DATA_ERROR)

    def test_poison_404_rows_never_starve_the_healthy_rows(self):
        """Review's poison404 probe: 7 Ponto-404 Requests and 3 healthy ones. Every healthy
        row must be polled on every run; the 404s must not trip the outage stop."""
        self.expectErrorLog(*self._all_ponto_errors())
        rows = [self._make_poll_request("Pending", age_days=20 - i) for i in range(10)]
        poison = {d.ponto_payment_id for d in rows[:7]}

        def fake_get(session, url, **kwargs):
            payment_id = url.rsplit("/", 1)[-1]
            return _response(404) if payment_id in poison else _response(200, HEALTHY)

        stops_before = frappe.db.count("Error Log", {"method": "Ponto status poll stopped early"})
        for _run in range(3):
            seen = []

            def recording(session, url, **kwargs):
                seen.append(url.rsplit("/", 1)[-1])
                return fake_get(session, url, **kwargs)

            with patch("verenigingen.verenigingen_payments.ponto.core.ponto_client.PontoTokenManager") as tm:
                tm.return_value.get_valid_token.return_value = "token"
                with patch.object(requests.Session, "get", recording), patch("time.sleep"):
                    frappe.get_attr(JOB)()
            healthy = {d.ponto_payment_id for d in rows[7:]}
            self.assertTrue(healthy <= set(seen), "a healthy row was not polled")
        self.assertEqual(frappe.db.count("Error Log", {"method": "Ponto status poll stopped early"}), stops_before)
