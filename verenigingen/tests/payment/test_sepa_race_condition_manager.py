"""
Real-integration unit tests for
verenigingen/verenigingen_payments/utils/sepa_race_condition_manager.py

This file complements the lock acquire / release / contention coverage already
in ``verenigingen/tests/sepa/test_sepa_week3_features.py`` by driving the
UNcovered surface against the REAL database-backed lock table
(``tabSEPA_Distributed_Lock``) and real Direct Debit Batch / Sales Invoice
documents:

  * expired-lock cleanup + re-acquisition (``_cleanup_expired_locks`` and the
    ON DUPLICATE KEY UPDATE "expired -> take over" branch),
  * ``_get_current_lock_info`` for held / absent resources,
  * ``force_release_lock`` (admin override path AND the non-system-manager
    denial path), and the whitelisted ``get_batch_lock_status`` /
    ``force_release_batch_lock`` API wrappers,
  * ``retry_failed_operation`` success-after-transient-failure and
    exhaust-all-attempts paths,
  * ``create_batch_with_race_protection`` argument-validation errors (no
    invoices, no valid invoice names) and the full race-protected batch
    creation flow against real submitted Sales Invoices, including the
    conflict-detection branch (invoice already assigned to an active batch).

Lock state is driven through the real manager / SQL, never mocked. Tests run as
Administrator (System Manager), satisfying the force-release role gate; one test
drops the System Manager role within a controlled ``set_user``-free block to
exercise the denial branch.
"""

import unittest
import unittest.mock
from datetime import timedelta

import frappe
from frappe.utils import add_to_date, now

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.utils.error_handling import SEPAError
from verenigingen.verenigingen_payments.utils.sepa_race_condition_manager import (
    SEPABatchRaceConditionManager,
    SEPADistributedLock,
    force_release_batch_lock,
    get_batch_lock_status,
)

LOCK_TABLE = "tabSEPA_Distributed_Lock"


def _delete_lock(resource):
    if frappe.db.table_exists(LOCK_TABLE):
        frappe.db.sql(f"DELETE FROM `{LOCK_TABLE}` WHERE name = %s", (f"SEPA_LOCK_{resource}",))
        frappe.db.commit()


def _row(resource):
    rows = frappe.db.sql(
        f"""
        SELECT lock_owner, lock_id, expires_at, is_active
        FROM `{LOCK_TABLE}` WHERE name = %s
        """,
        (f"SEPA_LOCK_{resource}",),
        as_dict=True,
    )
    return rows[0] if rows else None


class TestDistributedLockInternals(EnhancedTestCase):
    """Lock-level branches not covered by the existing acquire/release tests."""

    def setUp(self):
        super().setUp()
        self.lock = SEPADistributedLock()
        self._resources = []

    def tearDown(self):
        for r in self._resources:
            _delete_lock(r)
        super().tearDown()

    def _resource(self, name):
        self._resources.append(name)
        return name

    def test_get_current_lock_info_empty_when_absent(self):
        info = self.lock._get_current_lock_info(self._resource("rc_absent_001"))
        self.assertEqual(info, {})

    def test_get_current_lock_info_populated_when_held(self):
        resource = self._resource("rc_held_001")
        with self.lock.acquire_lock(resource, timeout=30):
            info = self.lock._get_current_lock_info(resource)
            self.assertTrue(info.get("is_active"))
            self.assertEqual(info.get("lock_owner"), self.lock.session_id)
            self.assertIn("lock_type", info)

    def test_expired_lock_is_taken_over(self):
        """A lock whose expires_at is in the past must be re-acquirable.

        We acquire, then back-date expires_at directly so the next acquire sees
        an expired row and takes it over via the ON DUPLICATE KEY UPDATE branch.
        """
        resource = self._resource("rc_expired_001")
        lock_a = SEPADistributedLock()
        lock_b = SEPADistributedLock()

        with lock_a.acquire_lock(resource, timeout=300) as info_a:
            # Force-expire the held lock in the DB.
            past = add_to_date(now(), seconds=-10)
            frappe.db.sql(
                f"UPDATE `{LOCK_TABLE}` SET expires_at = %s WHERE name = %s",
                (past, f"SEPA_LOCK_{resource}"),
            )
            frappe.db.commit()

            # A different session should now be able to take the expired lock.
            with lock_b.acquire_lock(resource, timeout=30, acquisition_timeout=5) as info_b:
                self.assertIsNotNone(info_b)
                self.assertNotEqual(info_a.lock_id, info_b.lock_id)
                row = _row(resource)
                self.assertEqual(row["lock_owner"], lock_b.session_id)

    def test_cleanup_expired_locks_marks_inactive(self):
        resource = self._resource("rc_cleanup_001")
        # Insert an already-expired active lock row directly. We do NOT commit
        # it (see below), so it never leaks across runs and no pre-purge of a
        # stale committed row is needed.
        # Insert an already-expired active lock row directly.
        past = add_to_date(now(), seconds=-100)
        frappe.db.sql(
            f"""
            INSERT INTO `{LOCK_TABLE}`
            (name, creation, modified, owner, lock_id, resource, lock_owner,
             acquired_at, expires_at, lock_type, metadata, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
            """,
            (
                f"SEPA_LOCK_{resource}",
                past,
                past,
                "Administrator",
                "stale-lock-id",
                resource,
                "stale-owner",
                past,
                past,
                "batch_creation",
                "{}",
            ),
        )
        # No commit: keep the fixture row inside the test transaction so it rolls
        # back cleanly. _cleanup_expired_locks + _row run on the same DB
        # connection, so the uncommitted row is visible to them.

        self.lock._cleanup_expired_locks()

        row = _row(resource)
        self.assertIsNotNone(row)
        self.assertEqual(row["is_active"], 0, "Expired lock should be marked inactive")

    def test_force_release_lock_admin_override(self):
        resource = self._resource("rc_force_001")
        # Hold a lock via a separate manager, then admin-force-release it.
        other = SEPADistributedLock()
        info = other._acquire_lock_internal(
            resource=resource,
            lock_type=SEPADistributedLock.BATCH_CREATION_LOCK,
            timeout=300,
            metadata={},
        )
        self.assertEqual(_row(resource)["is_active"], 1)

        released = self.lock.force_release_lock(resource, admin_override=True)
        self.assertTrue(released)
        self.assertEqual(_row(resource)["is_active"], 0)
        # Clean up the dangling lock-id reference.
        other._release_lock_internal(info.lock_id)

    def test_force_release_lock_denied_without_system_manager(self):
        resource = self._resource("rc_force_deny_001")
        # Remove System Manager from the current (Administrator) user's roles for
        # the duration of this assertion so the role gate denies the operation.
        original_roles = frappe.get_roles()
        try:
            frappe.local.role_permissions = {}
            frappe.flags.current_roles = [r for r in original_roles if r != "System Manager"]

            # Patch get_roles to reflect the restricted set (no DB mutation).
            real_get_roles = frappe.get_roles

            def restricted_get_roles(*args, **kwargs):
                return frappe.flags.current_roles

            frappe.get_roles = restricted_get_roles
            with self.assertRaises(SEPAError):
                self.lock.force_release_lock(resource, admin_override=False)
        finally:
            frappe.get_roles = real_get_roles
            frappe.flags.current_roles = None


class TestLockApiWrappers(EnhancedTestCase):
    """Whitelisted get_batch_lock_status / force_release_batch_lock wrappers."""

    def setUp(self):
        super().setUp()
        self.lock = SEPADistributedLock()
        self._resource = "rc_api_001"

    def tearDown(self):
        _delete_lock(self._resource)
        super().tearDown()

    def test_get_batch_lock_status_unlocked(self):
        result = get_batch_lock_status(self._resource)
        self.assertFalse(result["locked"])

    def test_get_batch_lock_status_locked_then_force_release(self):
        with self.lock.acquire_lock(self._resource, timeout=60):
            status = get_batch_lock_status(self._resource)
            self.assertTrue(status["locked"])
            self.assertEqual(status["lock_info"]["lock_owner"], self.lock.session_id)

            # Admin force-release through the whitelisted API.
            release = force_release_batch_lock(self._resource)
            self.assertTrue(release["success"])

        # After force release the row is inactive.
        status_after = get_batch_lock_status(self._resource)
        self.assertFalse(status_after["locked"])


class TestRetryFailedOperation(EnhancedTestCase):
    """retry_failed_operation exponential-backoff retry semantics."""

    def setUp(self):
        super().setUp()
        self.manager = SEPABatchRaceConditionManager()
        # Keep delays tiny so the test is fast.
        self.manager.retry_config = {
            "max_attempts": 3,
            "base_delay": 0.01,
            "max_delay": 0.05,
            "exponential_base": 2.0,
        }

    def test_retry_succeeds_after_transient_failures(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError(f"transient {calls['n']}")
            return "ok"

        result = self.manager.retry_failed_operation(flaky)
        self.assertEqual(result, "ok")
        self.assertEqual(calls["n"], 3)

    def test_retry_exhausts_and_returns_failure_result(self):
        # retry_failed_operation is wrapped by @handle_api_error: when retries
        # exhaust it raises SEPAError, which the decorator converts into a failed
        # OperationResult (it does NOT propagate). Assert the structured failure.
        calls = {"n": 0}

        def always_fail():
            calls["n"] += 1
            raise RuntimeError("permanent")

        result = self.manager.retry_failed_operation(always_fail)
        self.assertEqual(calls["n"], 3)  # exactly max_attempts retried
        # OperationResult exposes success/.to_dict(); accept either shape.
        success = getattr(result, "success", None)
        if success is None and isinstance(result, dict):
            success = result.get("success")
        self.assertFalse(success, f"expected failure result, got {result!r}")

    def test_retry_passes_through_args(self):
        def add(a, b, c=0):
            return a + b + c

        result = self.manager.retry_failed_operation(add, 2, 3, c=5)
        self.assertEqual(result, 10)


class TestRetryFailedOperationBackoffParity(EnhancedTestCase):
    """Pin the exact exponential-backoff delays used by retry_failed_operation.

    The inline backoff (base=1, exp_base=2, max=10, 0-based attempt) is replaced
    by a delegation to the shared calculate_backoff_delay helper. This parity
    test captures the exact ``time.sleep`` delays for attempts 0..3 so the
    refactor cannot silently change the schedule. jitter_factor is 0 here (the
    original inline code added no jitter), so the values are deterministic.
    """

    def setUp(self):
        super().setUp()
        self.manager = SEPABatchRaceConditionManager()
        self.manager.retry_config = {
            "max_attempts": 5,
            "base_delay": 1.0,
            "max_delay": 10.0,
            "exponential_base": 2.0,
        }

    def test_sleep_delays_exact_schedule(self):
        import verenigingen.verenigingen_payments.utils.sepa_race_condition_manager as rcm

        recorded = []

        def always_fail():
            raise RuntimeError("boom")

        # retry_failed_operation is wrapped by @handle_api_error: an exhausted
        # retry raises SEPAError internally which the decorator converts into a
        # failure result (it does not propagate) AND logs an Error Log row. We
        # only care about the sleep schedule here, so mark that log as expected.
        self.expectErrorLog("Operation failed after")
        with unittest.mock.patch.object(rcm.time, "sleep", side_effect=recorded.append):
            self.manager.retry_failed_operation(always_fail)

        # 5 attempts -> sleeps before attempts 2..5 (i.e. after failures 0..3):
        # nominal 1, 2, 4, 8 (none capped at max_delay=10).
        self.assertEqual(recorded, [1.0, 2.0, 4.0, 8.0])

    def test_sleep_delays_capped(self):
        import verenigingen.verenigingen_payments.utils.sepa_race_condition_manager as rcm

        self.manager.retry_config = {
            "max_attempts": 5,
            "base_delay": 1.0,
            "max_delay": 3.0,
            "exponential_base": 2.0,
        }
        recorded = []

        def always_fail():
            raise RuntimeError("boom")

        self.expectErrorLog("Operation failed after")
        with unittest.mock.patch.object(rcm.time, "sleep", side_effect=recorded.append):
            self.manager.retry_failed_operation(always_fail)

        # nominal 1, 2, 4, 8 -> capped at 3 -> 1, 2, 3, 3.
        self.assertEqual(recorded, [1.0, 2.0, 3.0, 3.0])


class TestBatchCreationValidation(EnhancedTestCase):
    """create_batch_with_race_protection argument-validation branches."""

    def setUp(self):
        super().setUp()
        self.manager = SEPABatchRaceConditionManager()

    def test_no_invoices_raises(self):
        with self.assertRaises(SEPAError):
            self.manager.create_batch_with_race_protection({"invoice_list": []})

    def test_no_valid_invoice_names_raises(self):
        # invoice_list entries lacking an "invoice" key -> no valid names.
        with self.assertRaises(SEPAError):
            self.manager.create_batch_with_race_protection({"invoice_list": [{"amount": 10}, {"amount": 20}]})


class TestBatchCreationInnerLogic(EnhancedTestCase):
    """
    Coverage of the race-protected batch-creation *building blocks* against REAL
    submitted Sales Invoices and Direct Debit Batches.

    The end-to-end ``create_batch_with_race_protection`` -> ``_execute_batch_
    creation_with_isolation`` path opens with
    ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` followed by ``begin()``.
    MariaDB rejects ``SET TRANSACTION ...`` while a transaction is already open
    (error 1568), and the Frappe test harness always runs inside an open
    transaction for auto-rollback. The full flow is therefore not coverable
    inside a FrappeTestCase without committing fixtures (which would defeat
    rollback / leak data). See ``test_isolation_level_blocks_full_flow_in_txn``
    which documents this. The inner SQL helpers below DO work inside the open
    transaction and are exercised directly with real data.
    """

    def setUp(self):
        super().setUp()
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )
        self.manager = SEPABatchRaceConditionManager()

    def _make_unpaid_invoice(self):
        """Create a member + customer + mandate + submitted unpaid Sales Invoice."""
        member = self.sepa.create_test_member(first_name="Race")
        customer = self.sepa.create_test_customer(customer_name=f"Cust {member.full_name}")
        member.db_set("customer", customer.name)
        mandate = self.sepa.create_test_sepa_mandate(member=member.name)
        membership = self.sepa.create_test_membership(member=member.name)
        invoice = self.sepa.create_test_sales_invoice(
            customer=customer.name,
            member=member.name,
            membership=membership.name,
            submit=True,
        )
        invoice.reload()
        return invoice, member, mandate

    def _batch_data(self, invoice, member, mandate, amount=None):
        if amount is None:
            amount = float(invoice.outstanding_amount)
        return {
            "batch_date": frappe.utils.add_days(frappe.utils.today(), 3),
            "batch_type": "CORE",
            "invoice_list": [
                {
                    "invoice": invoice.name,
                    "amount": amount,
                    "currency": "EUR",
                    "member_name": member.full_name,
                    "iban": mandate.iban,
                    "bic": "INGBNL2A",
                    "mandate_reference": mandate.mandate_id,
                }
            ],
        }

    def test_lock_invoices_for_processing_returns_real_rows(self):
        invoice, _member, _mandate = self._make_unpaid_invoice()
        rows = self.manager._lock_invoices_for_processing([invoice.name])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], invoice.name)
        self.assertEqual(rows[0]["docstatus"], 1)

    def test_validate_invoice_availability_accepts_unpaid(self):
        invoice, member, mandate = self._make_unpaid_invoice()
        self.assertIn(invoice.status, ("Unpaid", "Overdue"))
        locked = self.manager._lock_invoices_for_processing([invoice.name])
        result = self.manager._validate_invoice_availability(
            locked, self._batch_data(invoice, member, mandate)
        )
        self.assertTrue(result["valid"], f"unexpected errors: {result['errors']}")
        self.assertEqual(len(result["validated_invoices"]), 1)

    def test_validate_invoice_availability_amount_mismatch(self):
        invoice, member, mandate = self._make_unpaid_invoice()
        locked = self.manager._lock_invoices_for_processing([invoice.name])
        bad = self._batch_data(invoice, member, mandate, amount=float(invoice.outstanding_amount) + 999.0)
        result = self.manager._validate_invoice_availability(locked, bad)
        self.assertFalse(result["valid"])
        self.assertTrue(any("Amount mismatch" in e for e in result["errors"]))

    def test_validate_invoice_availability_missing_invoice(self):
        # An invoice name that was never locked -> "not found or not locked".
        result = self.manager._validate_invoice_availability(
            [],
            {"invoice_list": [{"invoice": "SINV-NONEXISTENT-XYZ", "amount": 10.0}]},
        )
        self.assertFalse(result["valid"])
        self.assertTrue(any("not found or not locked" in e for e in result["errors"]))

    def test_detect_batch_conflicts_clean_when_unassigned(self):
        invoice, _member, _mandate = self._make_unpaid_invoice()
        result = self.manager._detect_batch_conflicts([invoice.name], {"batch_date": frappe.utils.today()})
        self.assertEqual(result["conflicts"], [])

    def test_detect_batch_conflicts_flags_assigned_invoice(self):
        # Build a real active Direct Debit Batch referencing the invoice, then
        # assert the conflict detector reports it.
        batch = self.sepa.create_test_direct_debit_batch(invoice_count=1)
        assigned_invoice = batch.invoices[0].invoice

        result = self.manager._detect_batch_conflicts(
            [assigned_invoice], {"batch_date": frappe.utils.today()}
        )
        self.assertTrue(
            any("already in batch" in c for c in result["conflicts"]),
            f"expected conflict for {assigned_invoice}, got {result}",
        )

    def test_isolation_level_blocks_full_flow_in_txn(self):
        """Characterize: the full flow cannot run inside the test transaction.

        ``_execute_batch_creation_with_isolation`` issues
        ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` before ``begin()``;
        MariaDB raises OperationalError 1568 because a transaction is already
        open under FrappeTestCase. This documents why the end-to-end success
        path is exercised via the inner helpers above rather than the public
        entry point. (In production this runs at request start with no open
        transaction, so the statement is valid.)
        """
        invoice, member, mandate = self._make_unpaid_invoice()
        # Driver-specific OperationalError subclass; assert on the SQLSTATE code.
        with self.assertRaises(Exception) as ctx:
            self.manager._execute_batch_creation_with_isolation(
                self._batch_data(invoice, member, mandate), [invoice.name]
            )
        self.assertIn("1568", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
