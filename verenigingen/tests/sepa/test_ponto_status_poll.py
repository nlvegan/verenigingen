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

Fixture shortcuts, stated: most rows are ``insert()``-ed directly at the starting
status (docstatus 0) rather than submitted, because submit calls Ponto;
``TestPollOnReallySubmittedAndCancelledRows`` is the exception and drives REAL submitted
(``.submit()``) and cancelled (``.cancel()``) rows with only the HTTP layer stubbed (#1907,
#1931). ``creation`` is back-dated with ``db.set_value`` to make a row "too old";
``test_cancelled_rows_are_selected_..`` marks docstatus-2 with ``db.set_value`` (selection
logic only, stated there); Ponto Settings credentials are set on the Single so the job's
"is Ponto configured" gate passes.

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
from verenigingen.patches.v2_2.add_ponto_executed_on_cancelled_row_notification import (
    execute as register_alert_notification_type,
)
from verenigingen.tests.fixtures.singleton_backup import SingletonBackup
from verenigingen.tests.payment.test_ponto_submitted_documents import (
    _create_client,
    _PontoUsers,
)
from verenigingen.tests.support.sepa_test_company import (
    create_test_supplier,
    get_eur_bank_account,
    get_eur_test_company,
)
from verenigingen.verenigingen_payments.doctype.ponto_payment_request.ponto_payment_request import (
    PontoPaymentRequest,
)
from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError, PontoRateLimitError
from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient
from verenigingen.verenigingen_payments.ponto.core.submitted_rows import (
    DELIVERED_MARK,
    OWED_MARK,
    ALERT_KEY,
    ALERT_MARKER,
    ALERT_TITLE,
    UNDELIVERED_TITLE,
    owed_alerts,
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

    def _cancelled_docstatus(self, doc):
        """Fixture shortcut: an open-looking status on a docstatus-2 row (db.set_value)."""
        frappe.db.set_value(doc.doctype, doc.name, "docstatus", 2, update_modified=False)
        return doc

    def _http_stub(self, fake_get):
        """A context manager stubbing ONLY the transport (``requests.Session.get`` -> ``fake_get(session,
        url, **kwargs)``), the token manager and sleep: the real clients, ``with_retry``, the doctype
        methods and the guard all run."""
        from contextlib import ExitStack

        stack = ExitStack()
        token = stack.enter_context(
            patch("verenigingen.verenigingen_payments.ponto.core.ponto_client.PontoTokenManager")
        )
        token.return_value.get_valid_token.return_value = "token"
        stack.enter_context(patch.object(requests.Session, "get", fake_get))
        stack.enter_context(patch("time.sleep"))
        return stack

    def _all_ponto_errors(self):
        return ERROR_TITLE_PREFIX, "Ponto status poll stopped early", "status refresh failed"

    def _poll_errors(self):
        return frappe.db.count("Error Log", {"method": ["like", f"{ERROR_TITLE_PREFIX}%"]})


class TestPontoStatusPoll(_PollBase):
    # --- selection ----------------------------------------------------------

    def test_selects_exactly_the_open_rows_inside_the_window(self):
        errors_before = self._poll_errors()
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
        # A row with no Ponto id must be filtered out BEFORE refresh_status: it would throw on
        # it, which writes an Error Log row. (Cancelled rows are a separate pass, #1931: see
        # TestCancelledRowPass.)
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
            requests.exceptions.JSONDecodeError("not json", "<html>", 0),
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

    def test_the_root_cause_decides_not_the_outermost_exception(self):
        """A 503 raised while handling a 404 is still a 404 at the root: data."""
        try:
            try:
                raise PontoAPIError("root", status_code=404)
            except PontoAPIError:
                raise PontoAPIError("wrapper", status_code=503)
        except PontoAPIError as outer:
            self.assertFalse(status_poll_service._is_outage(outer))
        try:
            try:
                raise PontoAPIError("root", status_code=503)
            except PontoAPIError:
                raise PontoAPIError("wrapper", status_code=404)
        except PontoAPIError as outer:
            self.assertTrue(status_poll_service._is_outage(outer))

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
        # The token POST's timeout is a literal inside PontoTokenManager (token_manager.py,
        # request_kwargs "timeout": 30 in the token fetch), not a constant: not reachable
        # without a refactor, so it is repeated here.
        token_timeout = 30
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
        "200 garbage": (lambda: _response(200, b"<html>not json</html>"), True),
        "502 html page": (lambda: _response(502, b"<html>bad gateway</html>"), True),
    }

    def _fake_get(self, behaviour):
        def fake_get(session, url, **kwargs):
            if isinstance(behaviour, Exception):
                raise behaviour
            return behaviour()

        return fake_get

    def _real_clients(self, behaviour):
        """Context managers stubbing only the transport, token and sleep."""
        return self._http_stub(self._fake_get(behaviour))

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


class TestRealTokenManagerClassification(_PollBase):
    """The token endpoint, through the REAL PontoTokenManager: only Session.post/get and
    sleep are stubbed. A failing token fetch hits every row, so each of these is an outage."""

    def _classify_poll_row(self, token_behaviour, api_behaviour):
        from verenigingen.verenigingen_payments.ponto.utils.token_manager import PontoTokenManager

        def stub(behaviour):
            def fake(session, *args, **kwargs):
                if isinstance(behaviour, Exception):
                    raise behaviour
                return behaviour()

            return fake

        self._configure_ponto(True, mtls=False)
        row = self._make_poll_request("Pending")
        PontoTokenManager.clear_cache()
        self.addCleanup(PontoTokenManager.clear_cache)
        with patch.object(requests.Session, "post", stub(token_behaviour)):
            with patch.object(requests.Session, "get", stub(api_behaviour)), patch("time.sleep"):
                return status_poll_service._refresh_one(row.doctype, row.name)

    def test_a_failing_token_fetch_is_an_outage_whatever_it_looks_like(self):
        self.expectErrorLog(*self._all_ponto_errors())
        ok = lambda: _response(200, HEALTHY)  # noqa: E731
        cases = {
            "token 401": lambda: _response(401),
            "token 400": lambda: _response(400),
            "token 503": lambda: _response(503),
            "token connection error": requests.ConnectionError("x"),
            "token 200 html": lambda: _response(200, b"<html>maintenance</html>"),
            "token 502 html": lambda: _response(502, b"<html>bad gateway</html>"),
        }
        for name, behaviour in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self._classify_poll_row(behaviour, ok), status_poll_service.OUTAGE)

    def test_a_garbage_api_body_is_an_outage_and_a_404_still_is_not(self):
        self.expectErrorLog(*self._all_ponto_errors())
        token = lambda: _response(200, {"access_token": "t", "expires_in": 1800})  # noqa: E731
        self.assertEqual(
            self._classify_poll_row(token, lambda: _response(200, b"<html>x</html>")), status_poll_service.OUTAGE
        )
        self.assertEqual(self._classify_poll_row(token, lambda: _response(404)), status_poll_service.DATA_ERROR)


class TestCancelledRowSelection(_PollBase):
    """#1931 selection and bounds. Shortcut, stated: the rows are docstatus-0 rows pushed to
    docstatus 2 with ``db.set_value`` (``_cancelled_docstatus``), which is exactly the state a real
    cancel leaves in the table (``on_cancel`` sets "Cancelled" in memory only, #1918); the real
    submit/cancel flow is driven in TestPollOnReallySubmittedAndCancelledRows. The client factory is
    stubbed here: this class is about WHICH rows are read, not about what Ponto answers."""

    def _ids(self, client_mock, kind):
        if kind == "request":
            return [c.kwargs["payment_id"] for c in client_mock.get_payment.call_args_list]
        return [c.args[0] for c in client_mock.get_payment_request.call_args_list]

    def test_cancelled_rows_are_selected_only_when_open_have_an_id_and_are_in_the_window(self):
        window = status_poll_service.STALENESS_WINDOW_DAYS
        wanted = [
            self._cancelled_docstatus(self._make_poll_request("Pending")),
            self._cancelled_docstatus(self._make_poll_request("Signed")),
        ]
        controls = [
            self._cancelled_docstatus(self._make_poll_request("Executed")),  # not open
            self._cancelled_docstatus(self._make_poll_request("Cancelled")),  # not open
            self._cancelled_docstatus(self._make_poll_request("Pending", age_days=window + 5)),
            self._cancelled_docstatus(self._make_poll_request("Pending", ponto_id=False)),
        ]
        link_wanted = [self._cancelled_docstatus(self._make_poll_link("Authorized"))]
        link_controls = [
            self._cancelled_docstatus(self._make_poll_link("Executed")),
            self._cancelled_docstatus(self._make_poll_link("Pending Authorization", age_days=window + 5)),
            self._cancelled_docstatus(self._make_poll_link("Pending Authorization", ponto_id=False)),
        ]
        # Control for "docstatus != 2 only": an ordinary open row is still read in the SAME run.
        live = self._make_poll_request("Pending")
        pay, link = self._run_job()
        self.assertEqual(
            set(self._ids(pay, "request")),
            {d.ponto_payment_id for d in wanted} | {live.ponto_payment_id},
        )
        self.assertEqual(set(self._ids(link, "link")), {d.ponto_request_id for d in link_wanted})
        for d in controls:
            self.assertNotIn(d.ponto_payment_id, self._ids(pay, "request"))
        for d in link_controls:
            self.assertNotIn(d.ponto_request_id, self._ids(link, "link"))

    def test_a_flood_of_cancelled_rows_neither_starves_open_rows_nor_is_starved(self):
        self.expectErrorLog("Ponto status poll batch truncated")  # 5 cancelled rows > the cap of 2
        with patch.object(status_poll_service, "CANCELLED_BATCH_LIMIT", 2):
            cancelled = [
                self._cancelled_docstatus(self._make_poll_request("Pending", age_days=20 - i)) for i in range(5)
            ]
            live = self._make_poll_request("Pending")
            seen_cancelled, runs = set(), 0
            while seen_cancelled != {d.ponto_payment_id for d in cancelled} and runs < 5:
                pay, _link = self._run_job()
                ids = self._ids(pay, "request")
                self.assertIn(live.ponto_payment_id, ids, "an open row was not read in this run")
                this_run = [i for i in ids if i != live.ponto_payment_id]
                self.assertLessEqual(len(this_run), 2, "the cancelled pass exceeded its own cap")
                seen_cancelled |= set(this_run)
                runs += 1
            self.assertEqual(seen_cancelled, {d.ponto_payment_id for d in cancelled})
            self.assertEqual(runs, 3, "5 rows at 2 per run, rotating: 3 runs reach all of them")

    def test_the_cancelled_pass_does_not_move_the_open_rows_cursor(self):
        """Review F2. More open rows than BATCH_LIMIT AND cancelled rows present: the open rotation
        must still reach every open row. The cancelled rows are the NEWEST rows, so a cursor shared
        with them would sit past every open row and the open pass would wrap to its head forever."""
        self.expectErrorLog("Ponto status poll batch truncated")
        open_rows = [self._make_poll_request("Pending", age_days=20 - i) for i in range(4)]
        for i in range(3):
            self._cancelled_docstatus(self._make_poll_request("Pending", age_days=5 - i))
        wanted = {d.ponto_payment_id for d in open_rows}
        seen = set()
        with patch.object(status_poll_service, "BATCH_LIMIT", 2), patch.object(
            status_poll_service, "CANCELLED_BATCH_LIMIT", 2
        ):
            for _run in range(2):
                pay, _link = self._run_job()
                seen |= set(self._ids(pay, "request")) & wanted
        self.assertEqual(seen, wanted, "an open row was starved by the cancelled pass's cursor")

    def test_the_cancelled_pass_runs_after_the_open_rows_and_is_cut_off_by_the_shared_budget(self):
        """The shared wall-clock budget: open rows are always attempted first. With the budget already
        spent after the first row, the cancelled row is the one left for a later run."""
        live = self._make_poll_request("Pending")
        cancelled = self._cancelled_docstatus(self._make_poll_request("Pending", age_days=1))
        self.expectErrorLog("Ponto status poll stopped early")
        ticks = iter([0, 0, 10**6, 10**6, 10**6])
        with patch.object(status_poll_service, "_monotonic", lambda: next(ticks)):
            pay, _link = self._run_job()
        self.assertEqual(self._ids(pay, "request"), [live.ponto_payment_id])
        self.assertNotIn(cancelled.ponto_payment_id, self._ids(pay, "request"))


class TestPollOnReallySubmittedAndCancelledRows(_PontoUsers, _PollBase):
    """#1907 + #1931 through the REAL lifecycle. Rows reach docstatus 1 through ``.submit()`` and
    docstatus 2 through ``.cancel()`` (the client factory is stubbed for those two calls only: they
    are not what is under test). The POLL then runs with only ``requests.Session.get``, the token
    manager and sleep stubbed: the real Ponto clients, ``with_retry``, ``refresh_status``, the
    ``before_update_after_submit`` guard and the system flag all execute."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()
        cls.bank_account = get_eur_bank_account(cls.company)

    def setUp(self):
        super().setUp()
        # The mapping the base configured, plus the Bank Account a Request's submit needs.
        settings = frappe.get_single("Ponto Settings")
        for m in settings.get("bank_account_mappings", []):
            m.bank_account = self.bank_account
        settings.flags.ignore_validate = True
        settings.flags.ignore_links = True
        settings.save()

    # --- fixtures: real lifecycle -------------------------------------------

    def _poll_submitted_request(self, amount=42.0):
        supplier = create_test_supplier("PollSub", prefix="_Test Poll Supplier")
        self.track_doc("Supplier", supplier.name)
        req = frappe.new_doc("Ponto Payment Request")
        req.update(dict(
            ponto_account="test-account-id", amount=amount, currency="EUR",
            creditor_name=supplier.supplier_name, creditor_iban="NL91ABNA0417164300",
            remittance_info="poll #1931", reference_doctype="Supplier", reference_name=supplier.name,
        ))
        req.insert()
        with patch(PAY_CLIENT, return_value=_create_client(f"pay-{frappe.generate_hash(length=10)}")):
            req.submit()
        self.assertEqual((req.docstatus, req.status), (1, "Pending"), "fixture must be a really submitted row")
        return req

    def _poll_submitted_link(self, amount=30.0):
        link = frappe.new_doc("Ponto Payment Link")
        link.update(dict(
            payment_type="One-Time", amount=amount, currency="EUR", description="poll #1931",
            creditor_name="Vereniging Test", creditor_iban="NL91ABNA0417164300",
        ))
        link.insert()
        with patch(LINK_CLIENT, return_value=_create_client(f"req-{frappe.generate_hash(length=10)}")):
            link.submit()
        self.assertEqual((link.docstatus, link.status), (1, "Pending Authorization"))
        return link

    def _cancel(self, doc):
        """The real cancel. The stub only absorbs the DELETE ``on_cancel`` sends to Ponto."""
        path = PAY_CLIENT if doc.doctype == "Ponto Payment Request" else LINK_CLIENT
        gone = SimpleNamespace(delete_payment=lambda **kw: None, delete_payment_request=lambda *a, **kw: None)
        with patch(path, return_value=gone):
            doc.cancel()
        row = self._state(doc)
        self.assertEqual(row.docstatus, 2)
        # #1918, measured here: the DB keeps the OPEN status, which is what makes the row selectable.
        # The cancelled pass depends on it: if #1918 is fixed this assertion trips, and the pass's
        # selection (status_poll_service._open_where, cancelled=True) must change with it.
        self.assertIn(row.status, ("Pending", "Pending Authorization"))
        return doc

    def _state(self, doc):
        return frappe.db.get_value(
            doc.doctype, doc.name, ["docstatus", "status", "payment_entry", "modified"], as_dict=True
        )

    # --- the HTTP layer -----------------------------------------------------

    def _poll(self, answers):
        """Run the job. ``answers`` maps a Ponto id to a Ponto status string or an HTTP error code."""
        self.requested = []

        def fake_get(session, url, **kwargs):
            ponto_id = url.rsplit("/", 1)[-1]
            self.requested.append(ponto_id)
            outcome = answers.get(ponto_id, "pending")
            if isinstance(outcome, int):
                return _response(outcome)
            return _response(200, {"data": {"id": ponto_id, "attributes": {"status": outcome}}})

        self.assertEqual(frappe.session.user, "Administrator")
        with self._http_stub(fake_get):
            frappe.get_attr(JOB)()

    # --- #1907: the poll moves REALLY submitted rows -------------------------

    def test_poll_moves_the_status_of_a_really_submitted_request_and_link(self):
        req, link = self._poll_submitted_request(), self._poll_submitted_link()
        errors_before = self._poll_errors()
        self._poll({req.ponto_payment_id: "signed", link.ponto_request_id: "signed"})
        self.assertEqual(self._state(req).docstatus, 1)
        self.assertEqual(self._state(link).docstatus, 1)
        self.assertEqual(self._state(req).status, "Signed")
        self.assertEqual(self._state(link).status, "Authorized")
        self.assertEqual(self._poll_errors(), errors_before, "the guard must not have refused the poll")

    # --- #1931: Executed on a cancelled row ----------------------------------

    def _assert_alerts_once_and_untouched(self, doc, ponto_id, amount):
        self.expectErrorLog(ALERT_TITLE)
        before = self._state(doc)
        self._poll({ponto_id: "executed"})
        self._assert_one_alert(doc.doctype, doc.name, ponto_id, amount)
        self.assertEqual(self._state(doc), before, "the cancelled document must not change")
        self.assertIn(ponto_id, self.requested, "the cancelled row must have been read from Ponto")
        self.assertFalse(frappe.get_all("Payment Entry", filters={"reference_no": doc.name}))
        self._poll({ponto_id: "executed"})  # second run: the alert's own dedupe
        self._assert_one_alert(doc.doctype, doc.name, ponto_id, amount)
        self.assertEqual(self._state(doc), before)

    def test_executed_on_a_cancelled_request_alerts_exactly_once_and_changes_nothing(self):
        req = self._cancel(self._poll_submitted_request())
        self._assert_alerts_once_and_untouched(req, req.ponto_payment_id, req.amount)

    def test_executed_on_a_cancelled_link_alerts_exactly_once_and_changes_nothing(self):
        link = self._cancel(self._poll_submitted_link())
        self._assert_alerts_once_and_untouched(link, link.ponto_request_id, link.amount)

    def test_any_other_ponto_status_on_a_cancelled_row_alerts_and_writes_nothing(self):
        """``signed`` and ``rejected`` both DIFFER from the stored open status, so an "alert on any
        status change" implementation fails here; the row was really READ each time."""
        req = self._cancel(self._poll_submitted_request())
        link = self._cancel(self._poll_submitted_link())
        before = {d.name: self._state(d) for d in (req, link)}
        errors_before = self._poll_errors()
        for ponto_status in ("signed", "rejected", "failed", "cancelled", "expired", "pending", "closed"):
            self._poll({req.ponto_payment_id: ponto_status, link.ponto_request_id: ponto_status})
            self.assertIn(req.ponto_payment_id, self.requested)
            self.assertIn(link.ponto_request_id, self.requested)
        self.assertEqual({d.name: self._state(d) for d in (req, link)}, before)
        self.assertEqual(self._alerts_for(req.doctype, req.name), ([], []))
        self.assertEqual(self._alerts_for(link.doctype, link.name), ([], []))
        self.assertEqual(self._poll_errors(), errors_before, "no save was attempted on a cancelled row")

    def test_an_open_row_in_the_same_run_is_still_refreshed_normally(self):
        """Control: the cancelled pass does not replace the open pass. Rows of both kinds, one run."""
        live_req, live_link = self._poll_submitted_request(), self._poll_submitted_link()
        dead_req, dead_link = self._cancel(self._poll_submitted_request()), self._cancel(self._poll_submitted_link())
        self.expectErrorLog(ALERT_TITLE)
        self._poll({
            live_req.ponto_payment_id: "signed", live_link.ponto_request_id: "signed",
            dead_req.ponto_payment_id: "executed", dead_link.ponto_request_id: "executed",
        })
        self.assertEqual(self._state(live_req).status, "Signed")
        self.assertEqual(self._state(live_link).status, "Authorized")
        for dead, ponto_id in ((dead_req, dead_req.ponto_payment_id), (dead_link, dead_link.ponto_request_id)):
            self._assert_one_alert(dead.doctype, dead.name, ponto_id, dead.amount)
            self.assertEqual(self._state(dead).docstatus, 2)
        self.assertEqual(self._alerts_for(live_req.doctype, live_req.name), ([], []))

    # --- #1931: a 404 on a cancelled row -------------------------------------

    def test_a_404_on_a_cancelled_row_is_quiet_and_never_stops_the_run(self):
        """``on_cancel`` deletes a Pending payment at Ponto, so a cancelled row may well 404 (NOT
        established: what Ponto really answers). Three of each kind in front of a paid one
        (MAX_CONSECUTIVE_OUTAGE_FAILURES in a row, per kind) must write no Error Log row, not trip
        the outage stop, and still let the paid one alert."""
        gone = [self._cancel(self._poll_submitted_request()) for _ in range(3)]
        gone += [self._cancel(self._poll_submitted_link()) for _ in range(3)]
        for i, d in enumerate(gone):  # oldest first, so the paid rows come last in each pass
            self._age(d, 10 - i)
        paid_req = self._cancel(self._poll_submitted_request())
        paid_link = self._cancel(self._poll_submitted_link())
        self.expectErrorLog(ALERT_TITLE)
        errors_before = self._poll_errors()
        stops_before = frappe.db.count("Error Log", {"method": "Ponto status poll stopped early"})
        answers = {d.get("ponto_payment_id") or d.get("ponto_request_id"): 404 for d in gone}
        answers.update({paid_req.ponto_payment_id: "executed", paid_link.ponto_request_id: "executed"})
        self._poll(answers)
        self.assertEqual(self._poll_errors(), errors_before, "a 404 on a cancelled row must not be logged")
        self.assertEqual(frappe.db.count("Error Log", {"method": "Ponto status poll stopped early"}), stops_before)
        self._assert_one_alert(paid_req.doctype, paid_req.name, paid_req.ponto_payment_id, paid_req.amount)
        self._assert_one_alert(paid_link.doctype, paid_link.name, paid_link.ponto_request_id, paid_link.amount)

    def test_only_a_404_is_quiet_other_failures_on_a_cancelled_row_still_classify_and_log(self):
        """Control for the test above: the quiet path is a 404, not 'every error on a cancelled row'."""
        self.expectErrorLog(*self._all_ponto_errors())
        cases = {404: status_poll_service.GONE, 400: status_poll_service.DATA_ERROR,
                 503: status_poll_service.OUTAGE, 401: status_poll_service.OUTAGE}
        for code, expected in cases.items():
            for make in (self._poll_submitted_request, self._poll_submitted_link):
                with self.subTest(code=code, doctype=make.__name__):
                    row = self._cancel(make())
                    before = frappe.db.count("Error Log", {"method": ["like", f"{ERROR_TITLE_PREFIX}%"]})
                    with self._http_stub(lambda session, url, **kw: _response(code)):
                        got = status_poll_service._refresh_one(row.doctype, row.name, cancelled=True)
                    self.assertEqual(got, expected)
                    logged = frappe.db.count("Error Log", {"method": ["like", f"{ERROR_TITLE_PREFIX}%"]}) - before
                    self.assertEqual(logged, 0 if expected == status_poll_service.GONE else 1)

    # --- #1931 review F1: an undeliverable alert must not repeat every hour ---------------

    def _unseed_alert_key(self):
        """Fresh installs run no patches: the key has no row and counts as disabled."""
        backup = SingletonBackup("Verenigingen Email Configuration")
        backup.backup()
        self.addCleanup(backup.restore)
        config = frappe.get_single("Verenigingen Email Configuration")
        config.notification_types = [n for n in config.notification_types if n.notification_key != ALERT_KEY]
        config.save()

    def _undelivered_rows(self, doc):
        return frappe.db.count(
            "Error Log",
            {"method": UNDELIVERED_TITLE, "error": ["like", f"{ALERT_MARKER}: {doc.doctype} {doc.name} %"]},
        )

    def test_an_undeliverable_alert_is_loud_once_not_once_per_poll(self):
        req = self._cancel(self._poll_submitted_request())
        self.expectErrorLog(ALERT_TITLE, UNDELIVERED_TITLE)
        self._unseed_alert_key()
        self._poll({req.ponto_payment_id: "executed"})
        self.assertEqual(self._undelivered_rows(req), 1, "the FIRST undeliverable alert must be loud")
        for _ in range(3):  # the hourly poll, three more hours
            self._poll({req.ponto_payment_id: "executed"})
        self.assertEqual(self._undelivered_rows(req), 1, "one NOT DELIVERED row per row, not one per run")
        self.assertEqual(
            frappe.db.count("Error Log", {"method": ALERT_TITLE, "error": ["like", f"%{req.name} %"]}), 1
        )

    def test_each_documents_undelivered_row_is_its_own(self):
        """Review N1: the cap is scoped to the document. One row's NOT DELIVERED row must not
        suppress another row's, whether of the other doctype or not."""
        req = self._cancel(self._poll_submitted_request())
        link = self._cancel(self._poll_submitted_link())
        self.expectErrorLog(ALERT_TITLE, UNDELIVERED_TITLE)
        self._unseed_alert_key()
        self._poll({req.ponto_payment_id: "executed", link.ponto_request_id: "executed"})
        self.assertEqual((self._undelivered_rows(req), self._undelivered_rows(link)), (1, 1))

    def test_a_later_deliverable_alert_is_still_delivered_after_an_undelivered_one(self):
        """The cap is on the loud Error Log row only: once the key is seeded the next poll delivers."""
        req = self._cancel(self._poll_submitted_request())
        self.expectErrorLog(ALERT_TITLE, UNDELIVERED_TITLE)
        self._unseed_alert_key()
        self._poll({req.ponto_payment_id: "executed"})
        self.assertEqual(self._alerts_for(req.doctype, req.name)[0], [])
        register_alert_notification_type()
        self._poll({req.ponto_payment_id: "executed"})
        self.assertTrue(self._alerts_for(req.doctype, req.name)[0], "a Notification Log must now exist")
        self.assertEqual(self._undelivered_rows(req), 1)

    # --- #1931 (ruling 2026-11-01): keep sending an undelivered alert until it is delivered ---

    def _push_out_of_window(self, doc):
        """Fixture shortcut: raw writes that age BOTH ``creation`` and ``modified`` past the window, so
        the cancelled pass no longer selects the row whichever column the window counts from."""
        long_ago = add_to_date(now_datetime(), days=-(status_poll_service.STALENESS_WINDOW_DAYS + 10))
        frappe.db.set_value(
            doc.doctype, doc.name, {"creation": long_ago, "modified": long_ago}, update_modified=False
        )

    def _states(self, doc):
        """(OWED, DELIVERED) markers on the document."""
        return tuple(
            bool(frappe.db.exists("Comment", {"reference_doctype": doc.doctype, "reference_name": doc.name,
                                              "comment_type": "Info", "content": ["like", f"%{mark}%"]}))
            for mark in (OWED_MARK, DELIVERED_MARK)
        )

    def _notification_logs(self, doc):
        return self._alerts_for(doc.doctype, doc.name)[0]

    def _undeliverable_cancelled_rows(self):
        """A cancelled Request and Link, both Executed at Ponto, alerted while the key is unseeded."""
        req = self._cancel(self._poll_submitted_request())
        link = self._cancel(self._poll_submitted_link())
        self.expectErrorLog(ALERT_TITLE, UNDELIVERED_TITLE)
        self._unseed_alert_key()
        self._poll({req.ponto_payment_id: "executed", link.ponto_request_id: "executed"})
        for doc in (req, link):
            self.assertEqual(self._states(doc), (True, False), "first alert: OWED recorded, not delivered")
            self.assertEqual(self._notification_logs(doc), [])
        return req, link

    def test_an_undelivered_alert_is_retried_after_the_row_left_the_window_without_asking_ponto(self):
        req, link = self._undeliverable_cancelled_rows()
        for doc in (req, link):
            self._push_out_of_window(doc)
        self._poll({})  # still unseeded: retried, still undeliverable, nothing asked of Ponto
        self.assertEqual(self.requested, [], "the retry must not call Ponto")
        register_alert_notification_type()  # the key is seeded later
        self._poll({})
        self.assertEqual(self.requested, [], "the retry must not call Ponto")
        for doc in (req, link):
            self.assertTrue(self._notification_logs(doc), "the alert must be delivered once the key exists")
            self.assertEqual(self._states(doc), (True, True))
            self.assertEqual(self._state(doc).docstatus, 2)

    def test_once_delivered_nothing_is_retried_or_written_again(self):
        req, link = self._undeliverable_cancelled_rows()
        for doc in (req, link):
            self._push_out_of_window(doc)
        register_alert_notification_type()
        self._poll({})
        before = {d.name: (self._notification_logs(d), self._state(d)) for d in (req, link)}
        errors = frappe.db.count("Error Log")
        comments = frappe.db.count("Comment", {"comment_type": "Info", "content": ["like", "%PONTO-ALERT-%"]})
        for _ in range(2):
            self._poll({})
        self.assertEqual({d.name: (self._notification_logs(d), self._state(d)) for d in (req, link)}, before)
        self.assertEqual(frappe.db.count("Error Log"), errors)
        self.assertEqual(
            frappe.db.count("Comment", {"comment_type": "Info", "content": ["like", "%PONTO-ALERT-%"]}), comments
        )
        self.assertEqual(self.requested, [])
        owed_now = {(o.doctype, o.name) for o in owed_alerts(1000)}
        self.assertFalse(owed_now & {(req.doctype, req.name), (link.doctype, link.name)}, "delivered = not owed")

    def test_the_owed_marker_survives_an_error_log_clear(self):
        """Error Log is pruned (14 days by default); the retry must not depend on it."""
        req, _link = self._undeliverable_cancelled_rows()
        self._push_out_of_window(req)
        frappe.db.delete("Error Log", {"error": ["like", f"%{req.name}%"]})
        self.assertEqual(
            frappe.db.count("Error Log", {"error": ["like", f"%{req.name}%"]}), 0, "control: log cleared"
        )
        register_alert_notification_type()
        self._poll({})
        self.assertTrue(self._notification_logs(req))
        self.assertEqual(self._states(req), (True, True))

    def test_an_in_window_undelivered_alert_is_still_retried_by_the_cancelled_pass(self):
        """Unchanged behaviour: a row still inside the window keeps being read and alerted."""
        req, _link = self._undeliverable_cancelled_rows()
        register_alert_notification_type()
        self._poll({req.ponto_payment_id: "executed"})
        self.assertIn(req.ponto_payment_id, self.requested)
        self.assertTrue(self._notification_logs(req))

    def test_the_owed_retry_is_bounded_and_rotates(self):
        rows = [self._cancel(self._poll_submitted_request()) for _ in range(3)]
        self.expectErrorLog(ALERT_TITLE, UNDELIVERED_TITLE)
        self._unseed_alert_key()
        self._poll({r.ponto_payment_id: "executed" for r in rows})
        for r in rows:
            self._push_out_of_window(r)
        register_alert_notification_type()
        with patch.object(status_poll_service, "OWED_ALERT_RETRY_LIMIT", 2):
            self._poll({})
            self.assertEqual(sum(bool(self._notification_logs(r)) for r in rows), 2)
            self._poll({})
        self.assertTrue(all(self._notification_logs(r) for r in rows), "the third row must not be starved")
