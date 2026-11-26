"""#3059: the Mollie bulk run and the debug/admin bulk-process must not re-absorb a 1213/1205.

Once the orchestrator raises a lock error instead of returning ``status="error"`` (#3013), two
callers turned it back into an ordinary per-row / per-request failure:

* ``mollie_bulk_run_service._process_rows`` marked the row Failed, carried on, and the next
  checkpoint COMMITTED whatever the failed unit had half-written (after a 1205 a Bank Transaction),
  while the row lost its link to it, so the next run's "BT already exists" shortcut marked the
  payment Skipped and it was never retried.
* ``MollieDebugService.bulk_process_member_payments`` (and the background batch job, the
  ``_submit_processed_documents`` handler, and the admin wrapper ``bulk_payment_admin_service``)
  folded it into ``result["error"]`` / a returned dict.

The lock error is raised at the DRIVER (``Cursor.execute`` raises ``OperationalError(1213/1205)``,
which frappe's dispatch wraps into ``QueryDeadlockError`` / ``QueryTimeoutError``), from inside a
stand-in orchestrator, so it takes the same path through frappe as the real one.

Probe shortcuts, stated:
* the orchestrator is a stand-in that raises the lock error itself: the real orchestrator only
  raises one after PR #3065 (#3013), so this pins what the CALLERS do with the exception, not that
  the orchestrator raises it;
* the lock error is injected, not provoked, so the server does not really roll back (1213) or
  half-apply (1205); the rollback test therefore asserts the caller's own ``db.rollback()`` by
  writing a row before raising.

Run:
    PYTHONPATH=<worktree> bench --site test_site_13 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_bulk_lock_errors_3059
"""

from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment import test_mollie_bulk_run as bulk_run_helpers
from verenigingen.tests.payment.test_mollie_debug_service_bulk import (
    FakeSDKClient,
    _BulkServiceTest,
    _FakeOrchestrator,
    _make_result,
    _make_service,
    _patch_sdk_and_orchestrator,
)
from verenigingen.tests.support.sepa_test_company import get_eur_bank_account, get_eur_test_company
from verenigingen.verenigingen_payments.services import mollie_bulk_run_service as svc

LOCK_CODES_3059 = ((1213, frappe.QueryDeadlockError), (1205, frappe.QueryTimeoutError))
_MARKER_3059 = "lock3059marker"


def raise_lock_error_at_driver_3059(code):
    """Run a real statement while the DRIVER raises OperationalError(code) for it."""
    cursor_cls = frappe.db._cursor.__class__
    real_execute = cursor_cls.execute

    def execute(cursor, query, *args, **kwargs):
        if isinstance(query, str) and _MARKER_3059 in query:
            raise frappe.db.OperationalError(code, "injected at the driver")
        return real_execute(cursor, query, *args, **kwargs)

    # Mock justified: fault injection at the driver; every other statement runs for real
    with patch.object(cursor_cls, "execute", execute):
        frappe.db.sql(f"SELECT 1 /* {_MARKER_3059} */")


class _LockRaisingOrchestrator(_FakeOrchestrator):
    """The debug-service fake, with every routed method raising a driver-level lock error."""

    def __init__(self, code):
        super().__init__()
        self._code = code

    def process_payment(self, payment_id=None, invoice_name=None, create_missing_invoice=False):
        raise_lock_error_at_driver_3059(self._code)

    def process_bt_only_payment(self, payment_id=None):
        raise_lock_error_at_driver_3059(self._code)

    def process_orphaned_payment(self, payment_id=None, allow_anonymous=False):
        raise_lock_error_at_driver_3059(self._code)


_mk_result = bulk_run_helpers._mk_result
_patch_orchestrator = bulk_run_helpers._patch_orchestrator


class TestBulkRunLockErrors3059(EnhancedTestCase):
    # Borrowed, not inherited: subclassing TestMollieBulkRun would re-run all of its tests here
    _create_test_run = bulk_run_helpers.TestMollieBulkRun._create_test_run
    _sample_payments = bulk_run_helpers.TestMollieBulkRun._sample_payments

    def setUp(self):
        super().setUp()
        # Suppresses only (asserts nothing). The run's own handlers log the failures they report, by
        # design; the other two are the unconfigured test site's Mollie bank/GL check and the real
        # orchestrator's lookup of fake payment ids, which the committed rows of this module's runs
        # trigger (same noise test_mollie_bulk_run.py produces).
        self.expectErrorLog(
            "Mollie Bulk Run",
            "Bank Transaction Creator Configuration Error",
            "Mollie Payment Orchestrator Error",
        )

    def test_injection_helper_surfaces_the_frappe_lock_classes(self):
        """Control: the injection helper really surfaces the frappe lock classes."""
        for code, exc_class in LOCK_CODES_3059:
            with self.subTest(code=code), self.assertRaises(exc_class):
                raise_lock_error_at_driver_3059(code)

    def _run_with_lock_error_on_second_row(self, code):
        run = self._create_test_run()
        payments = self._sample_payments(4)
        calls = []
        todo_marker = f"bulk3059-{frappe.generate_hash(length=8)}"

        def fake_process(pid):
            calls.append(pid)
            if len(calls) == 2:
                # A half-applied unit of work: written, not yet checkpointed
                frappe.get_doc({"doctype": "ToDo", "description": todo_marker}).insert()
                raise_lock_error_at_driver_3059(code)
            return _mk_result(pid, "success")

        with patch.object(svc, "_list_mollie_payments", return_value=payments), _patch_orchestrator(
            fake_process
        ):
            svc.execute_bulk_run(run.name)
        run.reload()
        return run, calls, todo_marker

    def test_lock_error_stops_the_run_instead_of_failing_one_row(self):
        for code, _exc in LOCK_CODES_3059:
            with self.subTest(code=code):
                run, calls, _marker = self._run_with_lock_error_on_second_row(code)
                self.assertEqual(run.status, "Failed")
                self.assertEqual(len(calls), 2, f"the run carried on after a {code}: {calls}")
                self.assertTrue(run.last_error)
                self.assertFalse(
                    [r for r in run.payments if "Unhandled exception" in (r.message or "")],
                    "a lock error was recorded as an ordinary per-row failure",
                )

    def test_half_applied_work_is_rolled_back_not_checkpointed(self):
        for code, _exc in LOCK_CODES_3059:
            with self.subTest(code=code):
                _run, _calls, marker = self._run_with_lock_error_on_second_row(code)
                leftover = frappe.get_all("ToDo", filters={"description": marker}, pluck="name")
                for name in leftover:
                    frappe.delete_doc("ToDo", name, force=True, ignore_permissions=True)
                self.assertEqual(leftover, [], f"a {code} left its half-written row committed")

    def test_resume_retries_the_payment_after_a_lock_error(self):
        run, calls, _marker = self._run_with_lock_error_on_second_row(1205)
        resumed = []

        def fake_resume(pid):
            resumed.append(pid)
            return _mk_result(pid, "success")

        with patch.object(svc, "_list_mollie_payments", return_value=[]), _patch_orchestrator(fake_resume):
            svc.execute_bulk_run(run.name)
        self.assertIn(calls[1], resumed, "the payment that hit the lock error was never retried")

    def test_ordinary_exception_still_fails_only_its_row(self):
        """Control: a non-lock exception keeps the existing contained-per-row behaviour."""
        run = self._create_test_run()
        payments = self._sample_payments(3)

        def fake_process(pid):
            if pid.endswith("001"):
                raise RuntimeError("simulated crash")
            return _mk_result(pid, "success")

        with patch.object(svc, "_list_mollie_payments", return_value=payments), _patch_orchestrator(
            fake_process
        ):
            svc.execute_bulk_run(run.name)
        run.reload()
        self.assertEqual(run.status, "Completed")
        self.assertEqual(run.total_failed, 1)


class TestDebugBulkLockErrors3059(_BulkServiceTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Resolved once here: get_eur_bank_account commits, which would prematurely commit a
        # test body's untracked fixtures (see test_mollie_debug_service_bulk.TestBulkProcessMemberPayments)
        cls._eur_bank_account_name = get_eur_bank_account(get_eur_test_company())

    def test_each_route_reraises_a_lock_error(self):
        routes = {
            "process_payment": {},
            "bt_only": {"mode": "bt_only"},
            "bt_only_orphaned": {"mode": "bt_only_orphaned"},
        }
        for code, exc_class in LOCK_CODES_3059:
            for route, mode in routes.items():
                with self.subTest(code=code, route=route):
                    pid = self._unique_pid()
                    modes = {pid: mode} if mode else {}
                    with _patch_sdk_and_orchestrator(FakeSDKClient(), _LockRaisingOrchestrator(code)):
                        service = _make_service()
                        with self.assertRaises(exc_class):
                            service.bulk_process_member_payments([pid], docstatus=0, payment_modes=modes)

    def test_lock_error_aborts_the_remaining_payments(self):
        pid_first, pid_second = self._unique_pid(), self._unique_pid()
        orch = _LockRaisingOrchestrator(1213)
        with _patch_sdk_and_orchestrator(FakeSDKClient(), orch):
            with self.assertRaises(frappe.QueryDeadlockError):
                _make_service().bulk_process_member_payments([pid_first, pid_second], docstatus=0)

    def test_background_batch_job_reraises(self):
        for code, exc_class in LOCK_CODES_3059:
            with self.subTest(code=code):
                pid = self._unique_pid()
                with _patch_sdk_and_orchestrator(FakeSDKClient(), _LockRaisingOrchestrator(code)):
                    with self.assertRaises(exc_class):
                        _make_service().process_payment_batch_background(1, [pid], 0, {}, "job3059")

    def test_submit_step_reraises(self):
        """A lock error raised by the REAL submit of a real draft Bank Transaction escapes."""
        bt = self._draft_bank_transaction_3059()
        pid = self._unique_pid()
        orch = _FakeOrchestrator(
            results_by_id={pid: _make_result(pid, status="success", bank_transaction=bt.name)}
        )
        cursor_cls = frappe.db._cursor.__class__
        real_execute = cursor_cls.execute

        def execute(cursor, query, *args, **kwargs):
            if isinstance(query, str) and query.lstrip().upper().startswith("UPDATE `TABBANK TRANSACTION`"):
                raise frappe.db.OperationalError(1213, "injected at the driver")
            return real_execute(cursor, query, *args, **kwargs)

        # Mock justified: fault injection at the driver; every other statement runs for real
        with _patch_sdk_and_orchestrator(FakeSDKClient(), orch), patch.object(cursor_cls, "execute", execute):
            with self.assertRaises(frappe.QueryDeadlockError):
                _make_service().bulk_process_member_payments([pid], docstatus=1)

    def _draft_bank_transaction_3059(self):
        bank_account = self._eur_bank_account_name
        bt = frappe.new_doc("Bank Transaction")
        bt.date = today()
        bt.description = "Mollie bulk lock test 3059"
        bt.deposit = 10.0
        bt.withdrawal = 0
        bt.currency = "EUR"
        bt.reference_number = self._unique_pid()
        bt.bank_account = bank_account
        bt.insert()
        self.track_doc("Bank Transaction", bt.name)
        return bt

    def test_ordinary_error_is_still_reported_in_the_result(self):
        """Control: a non-lock exception keeps being folded into result["error"]."""

        class _Boom(_FakeOrchestrator):
            def process_payment(self, **_kw):
                raise RuntimeError("ordinary failure")

        with _patch_sdk_and_orchestrator(FakeSDKClient(), _Boom()):
            result = _make_service().bulk_process_member_payments([self._unique_pid()], docstatus=0)
        self.assertIn("ordinary failure", result["error"])


class TestAdminWrapperLockErrors3059(_BulkServiceTest):
    def test_admin_wrapper_reraises_a_lock_error(self):
        from verenigingen.verenigingen_payments.mollie.services import bulk_payment_admin_service as admin

        for code, exc_class in LOCK_CODES_3059:
            with self.subTest(code=code):
                pid = self._unique_pid()
                with _patch_sdk_and_orchestrator(FakeSDKClient(), _LockRaisingOrchestrator(code)):
                    with self.assertRaises(exc_class):
                        admin.bulk_process_member_payments([pid], 0, None, None, access_check=lambda: True)
