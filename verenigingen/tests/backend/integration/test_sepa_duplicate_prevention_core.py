# Copyright (c) 2026, Verenigingen
# For license information, please see license.txt

"""
SEPA Duplicate Prevention - Core Safety Logic Tests

Complements ``test_sepa_security_feedback.py`` (which covers the Redis Lua
release path, capability verification, compact cache extraction and concurrency)
by exercising the *complement*: the deterministic single-process safety contracts
that protect against double-debiting.

These tests use REAL Redis (via frappe.cache, in-memory lock fallback when
``use_redis_locks_for_sepa`` is unset) and REAL DocTypes (Sales Invoice,
Payment Entry, SEPA Mandate, SEPA Return File Log). They assert OBSERVABLE
effects -- a held lock blocks a second acquire, an idempotent op runs exactly
once, a duplicate payment creates no second Payment Entry -- not stubbed returns.

Covered methods/branches:
- acquire_processing_lock / release_processing_lock: real lock semantics
  (held -> second acquire False; released -> re-acquire True; ownership-guarded
  release; expiry via short TTL).
- generate_idempotency_key: exact SHA256 values, determinism, distinctness.
- execute_idempotent_operation: exact-once execution proven via a counter
  side-effect; cached result returned without re-running; failures not cached.
- amounts_match_with_tolerance: boundary (at/over/under tolerance) + coercion.
- create_payment_entry_with_duplicate_check: missing invoice, fully-paid guard
  (no second Payment Entry created), over-allocation guard.
- check_batch_processing_status: same-transaction reprocess + different-transaction
  branches, and the clean (no existing payments) pass-through.
- check_return_file_processed: already-processed branch + clean pass-through.
- verify_redis_capabilities / check_redis_health: real result shape against the
  running cache.
- validate_batch_mandates: missing-member, no-active-mandate, all-valid branches.

test-quality-enforcer: exempt-thread-context-setup
"""

import hashlib
import uuid

import frappe

from verenigingen.api.sepa_duplicate_prevention import (
    _operation_cache,
    _processing_locks,
    acquire_processing_lock,
    amounts_match_with_tolerance,
    check_batch_processing_status,
    check_redis_health,
    check_return_file_processed,
    create_payment_entry_with_duplicate_check,
    execute_idempotent_operation,
    generate_idempotency_key,
    release_processing_lock,
    validate_batch_mandates,
    verify_redis_capabilities,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# =============================================================================
# Processing Locks - real acquire/release semantics
# =============================================================================


class TestProcessingLockSemantics(EnhancedTestCase):
    """The core race-prevention contract: a held lock blocks, a released lock frees."""

    def setUp(self):
        super().setUp()
        # Unique resource id per test so parallel/leftover state never collides.
        self.resource_type = "test_sepa_batch"
        self.resource_id = f"LOCK-{uuid.uuid4().hex}"
        self._acquired = []

    def tearDown(self):
        # Best-effort release of anything still held, then purge in-memory state
        # for the keys this test touched so we never poison sibling tests.
        for rtype, rid in self._acquired:
            try:
                release_processing_lock(rtype, rid)
            except Exception:
                pass
        super().tearDown()

    def _track(self, rtype, rid):
        self._acquired.append((rtype, rid))

    def test_second_acquire_while_held_fails(self):
        """A second acquire of the same resource while held returns False."""
        first = acquire_processing_lock(self.resource_type, self.resource_id, timeout=300)
        self._track(self.resource_type, self.resource_id)
        self.assertTrue(first, "First acquire of a free resource must succeed")

        second = acquire_processing_lock(self.resource_type, self.resource_id, timeout=300)
        self.assertFalse(second, "Second acquire while the lock is held must FAIL (return False)")

    def test_acquire_succeeds_again_after_release(self):
        """After release, the same resource can be acquired again."""
        self.assertTrue(acquire_processing_lock(self.resource_type, self.resource_id, timeout=300))
        self._track(self.resource_type, self.resource_id)

        release_processing_lock(self.resource_type, self.resource_id)

        reacquired = acquire_processing_lock(self.resource_type, self.resource_id, timeout=300)
        self.assertTrue(reacquired, "After release the resource must be acquirable again")

    def test_distinct_resources_do_not_block_each_other(self):
        """Locking resource A must not block resource B (lock is per resource)."""
        other_id = f"LOCK-{uuid.uuid4().hex}"
        self.assertTrue(acquire_processing_lock(self.resource_type, self.resource_id, timeout=300))
        self._track(self.resource_type, self.resource_id)

        self.assertTrue(
            acquire_processing_lock(self.resource_type, other_id, timeout=300),
            "A different resource id must be independently acquirable",
        )
        self._track(self.resource_type, other_id)

    def test_expired_lock_can_be_reacquired(self):
        """A lock whose TTL has elapsed is reclaimable without an explicit release.

        Uses a zero-second TTL so the in-memory expiry branch
        (current_time - lock_time < lock_ttl is False) is exercised deterministically.
        """
        self.assertTrue(acquire_processing_lock(self.resource_type, self.resource_id, timeout=0))
        self._track(self.resource_type, self.resource_id)

        # timeout=0 means the lock is already past its TTL on the next check.
        reacquired = acquire_processing_lock(self.resource_type, self.resource_id, timeout=0)
        self.assertTrue(reacquired, "An expired (timeout=0) lock must be reclaimable")

    def test_release_is_ownership_guarded(self):
        """Releasing a lock we do not own (no stored token) leaves it untouched.

        We acquire the lock, then forcibly drop our ownership token while leaving
        the lock record in place -- simulating a foreign owner. A release call must
        then NOT remove the still-active lock, so a fresh acquire still fails.
        """
        self.assertTrue(acquire_processing_lock(self.resource_type, self.resource_id, timeout=300))
        self._track(self.resource_type, self.resource_id)

        lock_key = f"{self.resource_type}:{self.resource_id}"
        from verenigingen.api import sepa_duplicate_prevention as mod

        # Drop our token so the lock looks foreign-owned to release_processing_lock.
        mod._lock_tokens.pop(lock_key, None)

        release_processing_lock(self.resource_type, self.resource_id)

        # Ownership mismatch -> lock not released -> still held -> re-acquire fails.
        self.assertIn(lock_key, _processing_locks, "Foreign-owned lock must NOT be released")
        self.assertFalse(
            acquire_processing_lock(self.resource_type, self.resource_id, timeout=300),
            "Lock that we failed to release must still block a new acquire",
        )


# =============================================================================
# Idempotency key generation - exact values & stability
# =============================================================================


class TestIdempotencyKeyGeneration(EnhancedTestCase):
    """generate_idempotency_key is pure logic: assert exact, stable, distinct."""

    def test_exact_sha256_value(self):
        """Key equals SHA256 of 'bank_transaction:batch:operation' (no user mixed in)."""
        expected = hashlib.sha256(b"BT-1:BATCH-1:payment").hexdigest()
        self.assertEqual(generate_idempotency_key("BT-1", "BATCH-1", "payment"), expected)

    def test_deterministic_across_calls(self):
        a = generate_idempotency_key("BT-9", "BATCH-9", "reversal")
        b = generate_idempotency_key("BT-9", "BATCH-9", "reversal")
        self.assertEqual(a, b)

    def test_distinct_for_each_component(self):
        base = generate_idempotency_key("BT-1", "BATCH-1", "payment")
        self.assertNotEqual(base, generate_idempotency_key("BT-2", "BATCH-1", "payment"))
        self.assertNotEqual(base, generate_idempotency_key("BT-1", "BATCH-2", "payment"))
        self.assertNotEqual(base, generate_idempotency_key("BT-1", "BATCH-1", "reversal"))

    def test_empty_components_are_stable(self):
        """Empty strings (used by create_payment_entry_with_duplicate_check) are stable."""
        expected = hashlib.sha256(b"::payment_INV-1").hexdigest()
        self.assertEqual(generate_idempotency_key("", "", "payment_INV-1"), expected)


# =============================================================================
# execute_idempotent_operation - exact-once via counter side effect
# =============================================================================


class TestExecuteIdempotentOperation(EnhancedTestCase):
    """Prove the operation runs exactly once; second call serves cache, no re-run."""

    def setUp(self):
        super().setUp()
        self.key = f"idem_{uuid.uuid4().hex}"

    def tearDown(self):
        _operation_cache.pop(self.key, None)
        super().tearDown()

    def test_operation_runs_once_then_serves_cache(self):
        counter = {"runs": 0}

        def op():
            counter["runs"] += 1
            return {"success": True, "payment_entry": "PE-EXACTLY-ONCE"}

        first = execute_idempotent_operation(self.key, op, ttl=60)
        self.assertEqual(counter["runs"], 1, "Operation must run on first call")
        self.assertTrue(first["success"])
        self.assertEqual(first["payment_entry"], "PE-EXACTLY-ONCE")

        second = execute_idempotent_operation(self.key, op, ttl=60)
        self.assertEqual(
            counter["runs"], 1, "Second call must serve cache WITHOUT re-running the operation func"
        )
        # Cached value preserves the key identifier extracted by _extract_cacheable_result.
        self.assertEqual(second.get("payment_entry"), "PE-EXACTLY-ONCE")

    def test_distinct_keys_each_execute(self):
        counter = {"runs": 0}

        def op():
            counter["runs"] += 1
            return {"success": True}

        other_key = f"idem_{uuid.uuid4().hex}"
        try:
            execute_idempotent_operation(self.key, op, ttl=60)
            execute_idempotent_operation(other_key, op, ttl=60)
            self.assertEqual(counter["runs"], 2, "Different idempotency keys must each execute")
        finally:
            _operation_cache.pop(other_key, None)

    def test_failed_operation_is_not_cached_and_reraises(self):
        """A raising op is not cached; a retry runs it again (failures must be retryable)."""
        counter = {"runs": 0}

        def failing_op():
            counter["runs"] += 1
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            execute_idempotent_operation(self.key, failing_op, ttl=60)
        self.assertEqual(counter["runs"], 1)

        # Failure was NOT cached -> a retry re-runs the operation.
        with self.assertRaises(ValueError):
            execute_idempotent_operation(self.key, failing_op, ttl=60)
        self.assertEqual(counter["runs"], 2, "Failed operations must not be cached (retryable)")


# =============================================================================
# amounts_match_with_tolerance - boundary & coercion
# =============================================================================


class TestAmountsMatchWithTolerance(EnhancedTestCase):
    """Decimal tolerance comparison: exact boundary, just-over, just-under, coercion."""

    def test_exactly_at_default_tolerance_matches(self):
        # default tolerance "0.02" -> difference of exactly 0.02 is within tolerance.
        self.assertTrue(amounts_match_with_tolerance(100.00, 100.02))
        self.assertTrue(amounts_match_with_tolerance(100.02, 100.00))

    def test_just_over_tolerance_does_not_match(self):
        self.assertFalse(amounts_match_with_tolerance(100.00, 100.03))

    def test_just_under_tolerance_matches(self):
        self.assertTrue(amounts_match_with_tolerance(100.00, 100.01))

    def test_exact_equality_matches(self):
        self.assertTrue(amounts_match_with_tolerance("50.00", "50.00", tolerance="0.00"))

    def test_zero_tolerance_rejects_any_difference(self):
        self.assertFalse(amounts_match_with_tolerance(50.00, 50.01, tolerance="0.00"))

    def test_type_coercion_str_int_decimal(self):
        from decimal import Decimal

        # str vs float vs int vs Decimal all compared via exact Decimal arithmetic.
        self.assertTrue(amounts_match_with_tolerance("100.00", 100.0))
        self.assertTrue(amounts_match_with_tolerance(100, Decimal("100.00")))
        self.assertTrue(amounts_match_with_tolerance(None, 0))

    def test_custom_wider_tolerance(self):
        self.assertTrue(amounts_match_with_tolerance(100.00, 100.50, tolerance="1.00"))
        self.assertFalse(amounts_match_with_tolerance(100.00, 101.50, tolerance="1.00"))

    def test_float_precision_not_a_false_negative(self):
        # 0.1 + 0.2 == 0.30000000000000004 in float; Decimal-via-string avoids that.
        self.assertTrue(amounts_match_with_tolerance(0.1 + 0.2, 0.3, tolerance="0.00001"))


# =============================================================================
# create_payment_entry_with_duplicate_check - the double-debit guard
# =============================================================================


class TestCreatePaymentEntryDuplicateCheck(EnhancedTestCase):
    """The guard must block a duplicate/over-allocating payment and create no PE."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="DupCheck", last_name="Member", email=f"dupcheck.{uuid.uuid4().hex[:8]}@test.invalid"
        )

    def _setup_submitted_invoice(self, rate):
        """Create + submit a Sales Invoice for the test member. (helper: ignore_permissions allowed)"""
        invoice = self.create_test_sales_invoice(
            self.member.name, item_code="Test Service", rate=rate
        )
        if invoice.docstatus == 0:
            invoice.submit()
        return invoice

    def _setup_full_payment(self, invoice):
        """Create + submit a Payment Entry fully paying the invoice via ERPNext core."""
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        pe = get_payment_entry("Sales Invoice", invoice.name)
        pe.reference_no = f"DUP-{uuid.uuid4().hex[:8]}"
        pe.reference_date = frappe.utils.today()
        pe.save(ignore_permissions=True)
        pe.submit()
        return pe

    def test_missing_invoice_raises(self):
        with self.assertRaises(frappe.ValidationError):
            create_payment_entry_with_duplicate_check(
                "SINV-DOES-NOT-EXIST-XYZ", 10.0, {"doctype": "Payment Entry"}
            )

    def test_fully_paid_invoice_blocks_and_creates_no_second_payment_entry(self):
        invoice = self._setup_submitted_invoice(rate=75.0)
        self._setup_full_payment(invoice)

        pe_count_before = frappe.db.count(
            "Payment Entry Reference",
            {"reference_name": invoice.name, "reference_doctype": "Sales Invoice"},
        )

        with self.assertRaises(frappe.ValidationError) as ctx:
            create_payment_entry_with_duplicate_check(
                invoice.name,
                75.0,
                {
                    "doctype": "Payment Entry",
                    "payment_type": "Receive",
                    "paid_amount": 75.0,
                },
            )
        self.assertIn("already fully paid", str(ctx.exception))

        pe_count_after = frappe.db.count(
            "Payment Entry Reference",
            {"reference_name": invoice.name, "reference_doctype": "Sales Invoice"},
        )
        self.assertEqual(
            pe_count_before,
            pe_count_after,
            "Duplicate-blocked payment must NOT create a second Payment Entry Reference",
        )

    def test_over_allocation_blocks(self):
        """An amount that would exceed the invoice total is rejected before any PE."""
        invoice = self._setup_submitted_invoice(rate=40.0)
        with self.assertRaises(frappe.ValidationError) as ctx:
            create_payment_entry_with_duplicate_check(
                invoice.name,
                1000.0,  # far exceeds the 40.0 invoice total
                {"doctype": "Payment Entry", "payment_type": "Receive", "paid_amount": 1000.0},
            )
        self.assertIn("exceed invoice total", str(ctx.exception))


# =============================================================================
# check_batch_processing_status - reprocess guards
# =============================================================================


class TestCheckBatchProcessingStatus(EnhancedTestCase):
    """Submitted payments linked to a batch must block reprocessing."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="BatchProc", last_name="Member", email=f"batchproc.{uuid.uuid4().hex[:8]}@test.invalid"
        )
        self.batch_name = f"SEPA-BATCH-{uuid.uuid4().hex[:8]}"
        self.txn_name = f"BANK-TXN-{uuid.uuid4().hex[:8]}"
        self._linked_pe = None

    def tearDown(self):
        if self._linked_pe:
            try:
                pe = frappe.get_doc("Payment Entry", self._linked_pe)
                if pe.docstatus == 1:
                    pe.cancel()
                frappe.delete_doc("Payment Entry", self._linked_pe, force=True)
            except Exception:
                pass
            frappe.db.commit()
        super().tearDown()

    def _setup_batch_linked_payment(self, txn_name):
        """Submit a Payment Entry tagged with this batch + bank transaction.

        (helper: ignore_permissions allowed) The custom_sepa_batch /
        custom_bank_transaction columns are exactly what check_batch_processing_status
        queries on. Those are Link fields (Direct Debit Batch / Bank Transaction);
        the guard only reads the *column values*, so we write them directly via
        db.set_value after submit to avoid materialising heavyweight link targets
        whose only role here would be to satisfy referential validation.
        """
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        invoice = self.create_test_sales_invoice(
            self.member.name, item_code="Test Service", rate=30.0
        )
        if invoice.docstatus == 0:
            invoice.submit()

        pe = get_payment_entry("Sales Invoice", invoice.name)
        pe.reference_no = f"BATCH-{uuid.uuid4().hex[:8]}"
        pe.reference_date = frappe.utils.today()
        pe.save(ignore_permissions=True)
        pe.submit()
        self._linked_pe = pe.name

        # Tag the submitted row with the batch/transaction the guard queries on.
        frappe.db.set_value(
            "Payment Entry",
            pe.name,
            {"custom_sepa_batch": self.batch_name, "custom_bank_transaction": txn_name},
            update_modified=False,
        )
        frappe.db.commit()
        return pe

    def test_clean_batch_passes(self):
        """A batch with no submitted payments yet does not raise."""
        # No payments linked -> guard is a no-op (returns None).
        self.assertIsNone(check_batch_processing_status(self.batch_name, self.txn_name))

    def test_same_transaction_reprocess_blocked(self):
        self._setup_batch_linked_payment(self.txn_name)
        with self.assertRaises(frappe.ValidationError) as ctx:
            check_batch_processing_status(self.batch_name, self.txn_name)
        self.assertIn("already been used", str(ctx.exception))

    def test_different_transaction_blocked(self):
        # Batch already processed by txn A; processing again with txn B must block.
        self._setup_batch_linked_payment(self.txn_name)
        other_txn = f"BANK-TXN-{uuid.uuid4().hex[:8]}"
        with self.assertRaises(frappe.ValidationError) as ctx:
            check_batch_processing_status(self.batch_name, other_txn)
        self.assertIn("different bank transaction", str(ctx.exception))


# =============================================================================
# check_return_file_processed - de-dup on file hash
# =============================================================================


class TestCheckReturnFileProcessed(EnhancedTestCase):
    """A return file whose hash is already logged must be rejected."""

    def setUp(self):
        super().setUp()
        self.file_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        self._log_name = None

    def tearDown(self):
        if self._log_name and frappe.db.exists("SEPA Return File Log", self._log_name):
            frappe.delete_doc("SEPA Return File Log", self._log_name, force=True)
            frappe.db.commit()
        super().tearDown()

    def _setup_return_file_log(self, file_hash):
        """Insert a SEPA Return File Log row for the given hash. (helper: ignore_permissions allowed)"""
        log = frappe.new_doc("SEPA Return File Log")
        log.file_hash = file_hash
        log.file_name = "test_return.xml"
        log.processing_date = frappe.utils.now_datetime()
        log.processed_by = frappe.session.user
        log.status = "Completed"
        log.insert(ignore_permissions=True)
        frappe.db.commit()
        self._log_name = log.name
        return log

    def test_unprocessed_file_passes(self):
        self.assertIsNone(check_return_file_processed(self.file_hash))

    def test_already_processed_file_blocked(self):
        self._setup_return_file_log(self.file_hash)
        with self.assertRaises(frappe.ValidationError) as ctx:
            check_return_file_processed(self.file_hash)
        self.assertIn("already processed", str(ctx.exception))


# =============================================================================
# validate_batch_mandates - mandate presence per batch item
# =============================================================================


class TestValidateBatchMandates(EnhancedTestCase):
    """Each invoice line must resolve to an active, membership-enabled mandate."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="MandateVal", last_name="Member", email=f"mandateval.{uuid.uuid4().hex[:8]}@test.invalid"
        )
        self._mandate_name = None

    def tearDown(self):
        if self._mandate_name and frappe.db.exists("SEPA Mandate", self._mandate_name):
            frappe.delete_doc("SEPA Mandate", self._mandate_name, force=True)
            frappe.db.commit()
        super().tearDown()

    def _setup_active_mandate(self, member_name):
        """Create an active, membership-usable SEPA mandate. (helper: ignore_permissions allowed)"""
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.mandate_id = f"VAL-{uuid.uuid4().hex[:10]}"
        mandate.member = member_name
        mandate.account_holder_name = "Mandate Val Member"
        mandate.iban = self.factory.create_test_iban()
        mandate.status = "Active"
        mandate.is_active = 1
        mandate.used_for_memberships = 1
        mandate.sign_date = frappe.utils.today()
        mandate.insert(ignore_permissions=True)
        frappe.db.commit()
        self._mandate_name = mandate.name
        return mandate

    def test_item_without_member_is_flagged(self):
        result = validate_batch_mandates({"invoices": [{"invoice": "SINV-1"}]})
        self.assertFalse(result["valid"])
        self.assertEqual(result["total_items"], 1)
        self.assertEqual(result["valid_items"], 0)
        self.assertEqual(result["missing_mandates"][0]["reason"], "No member specified")

    def test_member_without_active_mandate_is_flagged(self):
        result = validate_batch_mandates(
            {"invoices": [{"invoice": "SINV-2", "member": self.member.name}]}
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["missing_mandates"][0]["reason"], "No active SEPA mandate found")
        self.assertEqual(result["missing_mandates"][0]["member"], self.member.name)

    def test_member_with_active_mandate_is_valid(self):
        self._setup_active_mandate(self.member.name)
        result = validate_batch_mandates(
            {"invoices": [{"invoice": "SINV-3", "member": self.member.name}]}
        )
        self.assertTrue(result["valid"], f"Expected valid, got: {result}")
        self.assertEqual(result["missing_mandates"], [])
        self.assertEqual(result["valid_items"], 1)

    def test_empty_batch_is_trivially_valid(self):
        result = validate_batch_mandates({"invoices": []})
        self.assertTrue(result["valid"])
        self.assertEqual(result["total_items"], 0)


# =============================================================================
# Redis health / capability result shape against the running cache
# =============================================================================


class TestRedisHealthAndCapabilityShape(EnhancedTestCase):
    """Assert the real result dicts have the documented shape (Redis IS running)."""

    def test_capability_result_shape(self):
        result = verify_redis_capabilities()
        # Always-present keys regardless of configuration.
        for key in (
            "redis_available",
            "set_nx_ex_supported",
            "eval_supported",
            "basic_ops_supported",
            "issues",
            "verified",
        ):
            self.assertIn(key, result)
        self.assertIsInstance(result["issues"], list)
        self.assertIsInstance(result["verified"], bool)

        if not frappe.conf.get("use_redis_locks_for_sepa", False):
            # When not enabled, verification is skipped with an explanatory issue.
            self.assertFalse(result["verified"])
            self.assertTrue(any("not enabled" in i for i in result["issues"]))

    def test_health_result_shape(self):
        result = check_redis_health()
        for key in ("healthy", "redis_configured", "redis_reachable", "capabilities_verified", "message"):
            self.assertIn(key, result)
        self.assertIsInstance(result["healthy"], bool)
        self.assertIsInstance(result["message"], str)

        if not result["redis_configured"]:
            # Unconfigured is reported healthy with the documented message.
            self.assertTrue(result["healthy"])
            self.assertIn("not configured", result["message"])
