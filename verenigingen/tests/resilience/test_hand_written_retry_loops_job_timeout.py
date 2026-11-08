# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
#2112: hand-written retry loops must not retry or swallow an RQ job timeout.

Follow-up to #1919 (shared wrappers). Each site here is a loop or handler written by hand.
The real ``rq.timeouts.JobTimeoutException`` is raised from the LOWEST layer the loop calls
(below any inner swallow on the real path); only ``time.sleep`` is patched, as a timing
boundary, so a retry is observable as a second attempt and a sleep. Each control proves the
same site still retries (or still swallows) an ordinary error, so "never retried" is not
satisfied by "never retries anything".
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from rq.timeouts import JobTimeoutException

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _ssh_settings():
    return frappe._dict(ssh_host="mijnrood.invalid", ssh_port=22, db_host="127.0.0.1", db_port=3306)


class TestMijnRoodConnectLoops(EnhancedTestCase):
    """Both clients wrap ``paramiko.Transport`` (the first call each attempt makes)."""

    def _clients(self):
        from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient
        from verenigingen.mijnrood_sync.sftp_client import MijnRoodSFTPClient

        settings = _ssh_settings()
        settings.documents_remote_path = "/docs"
        return (MijnRoodDatabaseClient(settings=settings), MijnRoodSFTPClient(settings=settings))

    def test_job_timeout_is_not_retried(self):
        for client in self._clients():
            with self.subTest(client=type(client).__name__):
                timeout = JobTimeoutException("t")
                with patch("paramiko.Transport", side_effect=timeout) as transport, patch(
                    "time.sleep"
                ) as sleep:
                    with self.assertRaises(JobTimeoutException) as ctx:
                        client.connect()
                self.assertIs(ctx.exception, timeout)
                self.assertEqual(transport.call_count, 1)
                sleep.assert_not_called()

    def test_control_transient_error_is_retried_the_configured_times(self):
        for client in self._clients():
            with self.subTest(client=type(client).__name__):
                with patch("paramiko.Transport", side_effect=OSError("reset")) as transport, patch(
                    "time.sleep"
                ) as sleep:
                    with self.assertRaises(ConnectionError):
                        client.connect(max_retries=3)
                self.assertEqual(transport.call_count, 3)
                self.assertEqual(sleep.call_count, 2)


MANAGER = "verenigingen.verenigingen_payments.utils.sepa_race_condition_manager"


class TestSepaLockAcquireLoop(EnhancedTestCase):
    """The lock helpers read the clock before they touch the table, so the fault is injected
    at the module's own ``now`` / ``get_datetime`` (the first call in the helper under test)."""

    def _lock(self):
        from verenigingen.verenigingen_payments.utils.sepa_race_condition_manager import SEPADistributedLock

        return SEPADistributedLock()

    def _acquire(self, lock):
        return lock._acquire_lock_internal(
            resource="test-2112", lock_type="batch_creation", timeout=60, metadata={}, acquisition_timeout=30
        )

    def test_job_timeout_in_the_cleanup_helper_propagates(self):
        with patch(f"{MANAGER}.now", side_effect=JobTimeoutException("t")) as clock, patch(
            "frappe.db.rollback"
        ), patch("time.sleep") as sleep:
            with self.assertRaises(JobTimeoutException):
                self._acquire(self._lock())
        self.assertEqual(clock.call_count, 1)
        sleep.assert_not_called()

    def test_job_timeout_in_the_acquire_attempt_is_not_retried(self):
        """Cleanup is stubbed so the acquire loop's own handler is what sees the timeout."""
        lock = self._lock()
        with patch.object(lock, "_cleanup_expired_locks"), patch(
            f"{MANAGER}.get_datetime", side_effect=JobTimeoutException("t")
        ) as clock, patch("frappe.db.rollback"), patch("time.sleep") as sleep:
            with self.assertRaises(JobTimeoutException):
                self._acquire(lock)
        self.assertEqual(clock.call_count, 1)
        sleep.assert_not_called()

    def test_job_timeout_while_releasing_is_not_swallowed(self):
        with patch(f"{MANAGER}.now", side_effect=JobTimeoutException("t")):
            with self.assertRaises(JobTimeoutException):
                self._lock()._release_lock_internal("lock-2112")

    def test_control_release_error_is_still_swallowed(self):
        with patch(f"{MANAGER}.now", side_effect=RuntimeError("clock hiccup")):
            self._lock()._release_lock_internal("lock-2112")  # must not raise

    def test_control_ordinary_error_is_retried_three_times(self):
        from verenigingen.utils.error_handling import SEPAError

        lock = self._lock()
        with patch.object(lock, "_cleanup_expired_locks"), patch(
            f"{MANAGER}.get_datetime", side_effect=RuntimeError("hiccup")
        ) as clock, patch("frappe.db.rollback"), patch("time.sleep") as sleep:
            with self.assertRaises(SEPAError):
                self._acquire(lock)
        self.assertEqual(clock.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


class TestSepaRetryFailedOperation(EnhancedTestCase):
    """The method is wrapped in ``@handle_api_error``, which must not eat the timeout either."""

    def _manager(self):
        from verenigingen.verenigingen_payments.utils.sepa_race_condition_manager import (
            SEPABatchRaceConditionManager,
        )

        return SEPABatchRaceConditionManager()

    def _run(self, first):
        attempts = []

        def op():
            attempts.append(1)
            if len(attempts) == 1:
                raise first
            return "ok"

        with patch("time.sleep") as sleep:
            try:
                result, error = self._manager().retry_failed_operation(op), None
            except Exception as e:
                result, error = None, e
        return attempts, sleep, result, error

    def test_job_timeout_propagates_after_one_attempt(self):
        timeout = JobTimeoutException("t")
        attempts, sleep, _, error = self._run(timeout)
        self.assertIs(error, timeout)
        self.assertEqual(len(attempts), 1)
        sleep.assert_not_called()

    def test_control_transient_error_is_retried(self):
        attempts, sleep, result, error = self._run(RuntimeError("temporary glitch"))
        self.assertIsNone(error)
        self.assertEqual(result, "ok")
        self.assertEqual(len(attempts), 2)
        sleep.assert_called_once()


class TestHandleApiErrorDecorator(EnhancedTestCase):
    def test_timeout_direct_and_implicitly_chained_propagate(self):
        from verenigingen.utils.error_handling import handle_api_error

        def chained():
            try:
                raise JobTimeoutException("t")
            except JobTimeoutException:
                raise RuntimeError("API call failed")  # Ponto-client shape: no ``from``

        for raiser in (lambda: (_ for _ in ()).throw(JobTimeoutException("t")), chained):
            wrapped = handle_api_error(raiser)
            with self.assertRaises(Exception) as ctx:
                wrapped()
            self.assertTrue(
                isinstance(ctx.exception, JobTimeoutException)
                or isinstance(ctx.exception.__context__, JobTimeoutException)
            )

    def test_control_ordinary_error_still_becomes_a_result(self):
        from verenigingen.utils.error_handling import handle_api_error

        def boom():
            raise RuntimeError("ordinary")

        self.expectErrorLog("ordinary")
        with self.assertErrorLog("ordinary"):
            result = handle_api_error(boom)()
        self.assertFalse(result.success)


class TestEBoekhoudenTokenFetch(EnhancedTestCase):
    def _client(self):
        from verenigingen.e_boekhouden.utils.http_client_mixin import EBoekhoudenHTTPClientMixin

        class Client(EBoekhoudenHTTPClientMixin):
            pass

        settings = SimpleNamespace(
            api_url="https://api.invalid", api_token="x", get_password=lambda *_: "secret"
        )
        client = Client()
        client._init_http_client(settings)
        return client

    def test_job_timeout_is_not_swallowed(self):
        timeout = JobTimeoutException("t")
        with patch("requests.post", side_effect=timeout) as post:
            with self.assertRaises(JobTimeoutException) as ctx:
                self._client()._get_session_token()
        self.assertIs(ctx.exception, timeout)
        self.assertEqual(post.call_count, 1)

    def test_control_ordinary_error_is_still_logged_and_returns_none(self):
        self.expectErrorLog("Error getting session token")
        with patch("requests.post", side_effect=ConnectionError("down")):
            with self.assertErrorLog("Error getting session token"):
                self.assertIsNone(self._client()._get_session_token())


class TestDonorContactRetry(EnhancedTestCase):
    def _donor(self):
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Retry Probe"
        donor.donor_email = "retry-probe-2112@example.com"
        return donor

    def test_job_timeout_is_not_retried(self):
        timeout = JobTimeoutException("t")
        with patch(
            "verenigingen.utils.secure_operations.secure_document_operation", side_effect=timeout
        ) as op, patch("time.sleep") as sleep:
            with self.assertRaises(JobTimeoutException):
                self._donor().create_new_customer_contact("NO-SUCH-CUSTOMER")
        self.assertEqual(op.call_count, 1)
        sleep.assert_not_called()

    def test_control_ordinary_error_is_retried(self):
        results = [RuntimeError("transient"), SimpleNamespace(success=True, errors=[])]
        with patch(
            "verenigingen.utils.secure_operations.secure_document_operation", side_effect=results
        ) as op, patch("time.sleep") as sleep:
            contact = self._donor().create_new_customer_contact("NO-SUCH-CUSTOMER")
        self.assertIsNotNone(contact)
        self.assertEqual(op.call_count, 2)
        sleep.assert_called_once()


class TestAddressRefreshTask(EnhancedTestCase):
    """Scheduler job: one timeout must stop the loop, not be counted as one member's error.

    The job's own query selects the members (real DB). Probe shortcut, stated: two members
    get ``primary_address`` set with ``db_set`` so the job's SELECT returns at least two
    rows; the per-member work (``update_other_members_at_address_display``) is the injected
    boundary, so no Address is built.
    """

    def setUp(self):
        super().setUp()
        for i in range(2):
            member = self.create_test_member(
                first_name=f"Addr2112{i}", last_name="Probe", email=f"addr2112-{i}@example.com"
            )
            member.db_set("primary_address", "probe-address-2112", update_modified=False)
            member.db_set("other_members_at_address", None, update_modified=False)

    def _run(self, error):
        from verenigingen.tasks.address_optimization import refresh_member_address_displays
        from verenigingen.verenigingen.doctype.member.member import Member

        with patch.object(Member, "update_other_members_at_address_display", side_effect=error) as work:
            with patch("time.sleep"):
                try:
                    result, raised = refresh_member_address_displays(), None
                except Exception as e:
                    result, raised = None, e
        return work, result, raised

    def test_job_timeout_stops_the_loop_and_propagates(self):
        timeout = JobTimeoutException("t")
        work, _, raised = self._run(timeout)
        self.assertIs(raised, timeout)
        self.assertEqual(work.call_count, 1)

    def test_control_ordinary_error_is_counted_and_the_loop_continues(self):
        self.expectErrorLog("Error refreshing address display")
        with self.assertErrorLog("Error refreshing address display"):
            work, result, raised = self._run(RuntimeError("one bad member"))
        self.assertIsNone(raised)
        self.assertGreaterEqual(work.call_count, 2)
        self.assertEqual(result.get("error_count"), work.call_count, result)
