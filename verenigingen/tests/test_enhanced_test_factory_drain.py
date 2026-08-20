"""Regression tests for EnhancedTestCase._drain_tracked_documents.

The drain runs in tearDown after frappe.db.rollback() and deletes documents
the factory tracked, so that records committed during a test (or by production
code the test invoked) do not survive into the next run.

Pre-fix history: 3 PRs (#57, #60, plus an earlier) added test-specific
tearDown overrides to clean up leaked Customer/Member records. Those were
symptoms of this framework gap; see
docs/plans/2026-05-24-test-framework-tracked-doc-drain-design.md.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDrainTrackedDocuments(EnhancedTestCase):
    """Verify the drain deletes committed records and tracks the auto-Customer."""

    def test_factory_tracks_auto_created_customer(self):
        """A Member created with auto_create_customer should have its Customer tracked."""
        member = self.create_test_member(
            first_name="DrainTest",
            last_name="AutoCustomer",
            email="draintest.autocustomer@test.invalid",
        )

        self.assertTrue(member.customer, "Expected auto-created Customer on member")

        tracked = [(d["doctype"], d["name"]) for d in self.factory.core.created_records]
        self.assertIn(
            ("Customer", member.customer),
            tracked,
            "Customer should be tracked by Core factory for tearDown drain",
        )

    def test_drain_deletes_committed_member_and_customer(self):
        """Drain removes committed Member + auto-Customer that rollback couldn't undo.

        Note: the manual mid-test drain commits the deletes. The tearDown
        drain will then re-run as a no-op (lists already cleared). This
        explicit call is a test-of-the-drain, NOT an idiom for production tests.
        """
        member = self.create_test_member(
            first_name="DrainTest",
            last_name="Committed",
            email="draintest.committed@test.invalid",
        )
        member_name = member.name
        customer_name = member.customer

        frappe.db.commit()

        self.assertTrue(frappe.db.exists("Member", member_name))
        self.assertTrue(frappe.db.exists("Customer", customer_name))

        self._drain_tracked_documents()

        self.assertFalse(
            frappe.db.exists("Member", member_name),
            f"Member {member_name} should be deleted by drain",
        )
        self.assertFalse(
            frappe.db.exists("Customer", customer_name),
            f"Customer {customer_name} should be deleted by drain",
        )

    def test_drain_is_idempotent(self):
        """First drain deletes; second drain is a clean no-op. Both verify records gone."""
        member = self.create_test_member(
            first_name="DrainTest",
            last_name="Idempotent",
            email="draintest.idempotent@test.invalid",
        )
        member_name = member.name
        customer_name = member.customer
        frappe.db.commit()

        self._drain_tracked_documents()

        self.assertFalse(
            frappe.db.exists("Member", member_name),
            "First drain call should delete the Member",
        )
        self.assertFalse(
            frappe.db.exists("Customer", customer_name),
            "First drain call should delete the Customer",
        )
        self.assertEqual(self.factory.created_documents, [])
        self.assertEqual(self.factory.core.created_records, [])

        self._drain_tracked_documents()

        self.assertEqual(self.factory.created_documents, [])
        self.assertEqual(self.factory.core.created_records, [])

    def test_drain_skips_negative_priority_records(self):
        """Records tracked with priority < 0 are shared infrastructure; drain must skip them.

        This is the safety contract that `_ensure_master_data` relies on: shared
        roots like 'All Departments' and 'Netherlands' Territory must NOT be
        torn down between test methods.
        """
        chapter = self.create_chapter()
        flipped = False
        for d in self.factory.created_documents:
            if d['doctype'] == "Chapter" and d['name'] == chapter.name:
                d['priority'] = -1
                flipped = True
                break
        self.assertTrue(flipped, "Chapter should be in Enhanced tracked list")

        frappe.db.commit()
        try:
            self._drain_tracked_documents()
            self.assertTrue(
                frappe.db.exists("Chapter", chapter.name),
                "Chapter with priority < 0 should survive drain",
            )
        finally:
            if frappe.db.exists("Chapter", chapter.name):
                frappe.delete_doc("Chapter", chapter.name, force=True, ignore_permissions=True)
                frappe.db.commit()

    def test_dedupe_keeps_highest_priority_across_sources(self):
        """When the same doc is tracked by both Enhanced (prio=5) and Core (prio=0),
        dedupe must keep prio=5 so delete ordering matches Enhanced's contract."""
        self.factory.created_documents.append(
            {"doctype": "ToyDoc", "name": "X", "priority": 5, "test_run_id": "t"}
        )
        self.factory.core.created_records.append({"doctype": "ToyDoc", "name": "X"})

        tracked: dict = {}
        for d in self.factory.created_documents:
            key = (d['doctype'], d['name'])
            prio = d.get('priority', 0)
            if key not in tracked or prio > tracked[key]:
                tracked[key] = prio
        for d in self.factory.core.created_records:
            key = (d['doctype'], d['name'])
            if key not in tracked or 0 > tracked[key]:
                tracked[key] = 0

        self.assertEqual(
            tracked[("ToyDoc", "X")], 5,
            "Dedupe must retain the highest priority across sources",
        )

        self.factory.created_documents = [
            d for d in self.factory.created_documents
            if not (d['doctype'] == "ToyDoc" and d['name'] == "X")
        ]
        self.factory.core.created_records = [
            d for d in self.factory.core.created_records
            if not (d['doctype'] == "ToyDoc" and d['name'] == "X")
        ]


class TestFactoryUniqueSuffixIsProcessGlobal(EnhancedTestCase):
    """Regression: the Customer-collision-prevention suffix appended to last_name
    in EnhancedTestDataFactory.create_member MUST come from a process-global
    counter, not a per-instance one.

    A fresh factory is built in every test's setUp; a per-instance counter
    resets to 1 each time, so every test's first member got last_name="<Name>1"
    -> identical Member full_name -> identical auto-created Customer name ->
    DuplicateEntryError on the Customer PRIMARY key (the largest CI failure
    bucket, B1). See docs/plans/2026-05-29-server-tests-red-baseline-triage.md.
    """

    def test_constructing_a_new_factory_does_not_reset_the_suffix_counter(self):
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory

        a = next(EnhancedTestDataFactory._global_unique_seq)
        b = next(EnhancedTestDataFactory._global_unique_seq)
        self.assertNotEqual(a, b, "the suffix counter must advance monotonically")

        # Building a new factory (as every setUp does) must NOT reset the shared
        # counter back to 1 — that reset was the root cause of the collisions.
        EnhancedTestDataFactory(seed=12345)
        c = next(EnhancedTestDataFactory._global_unique_seq)
        self.assertGreater(
            c, b,
            "constructing a new EnhancedTestDataFactory must not reset the "
            "process-global last_name suffix counter",
        )


class TestFinancialBatchQueueIsolation(EnhancedTestCase):
    """Regression: FinancialHistoryBatchProcessor keeps a PROCESS-GLOBAL,
    class-level ``_payment_queue`` / ``_expense_queue``. A prior test can leave a
    dangling entry (its member/invoice were rolled back at tearDown, but the
    in-memory queue entry survives). The next test's first
    ``add_invoice_to_payment_history()`` drains the queue INLINE via
    ``_maybe_process_batches()``; processing the stale entry raises
    DoesNotExistError inside ``_process_member_payment_batch``, whose
    ``except`` clause issues a *transaction-wide* ``frappe.db.rollback()`` that
    wipes the CURRENT test's uncommitted setUp data (e.g. the TEST-MEMBERSHIP
    item) -> LinkValidationError on the next invoice save.

    This was the sole test still baselined after issue #162
    (test_performance_under_integrated_load): local-green / CI-red because it
    only reproduces when another batch-processor test runs first in the same
    process. Several tests (test_invoice_events_coverage,
    test_volunteer_expenses_history_restore, ...) worked around it by clearing
    the queues in their own setUp/tearDown; EnhancedTestCase now resets them
    centrally so the footgun cannot bite any future test.

    The transaction-wide rollback itself has since been fixed at source -- the
    per-member handlers confine themselves to a savepoint and skip a member that
    no longer exists -- so this reset is now defence in depth rather than the only
    protection.
    """

    @staticmethod
    def _batch():
        from verenigingen.utils.financial_history_batch_processor import (
            FinancialHistoryBatchProcessor,
        )

        return FinancialHistoryBatchProcessor

    @staticmethod
    def _queue_depth(queue):
        return sum(len(entries) for entries in queue.values())

    def test_reset_clears_stale_batch_queue_entries(self):
        """The per-method reset empties both class-level queues."""
        BP = self._batch()
        BP._payment_queue["STALE-MEMBER"]["STALE-INVOICE"] = {
            "operation": "add_update",
            "timestamp": frappe.utils.now(),
            "data": {},
        }
        BP._expense_queue["STALE-MEMBER"]["STALE-EXPENSE"] = {
            "operation": "add_update",
            "timestamp": frappe.utils.now(),
            "data": {},
        }

        self._reset_financial_history_batch_queue()

        self.assertEqual(
            self._queue_depth(BP._payment_queue),
            0,
            "stale payment-queue entries must be cleared by the reset",
        )
        self.assertEqual(
            self._queue_depth(BP._expense_queue),
            0,
            "stale expense-queue entries must be cleared by the reset",
        )

    def _insert_uncommitted_marker(self, code):
        """Insert an uncommitted Item that stands in for a test's setUp data."""
        frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": code,
                "item_name": code,
                "item_group": "All Item Groups",
                "stock_uom": "Nos",
                "is_stock_item": 0,
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(frappe.db.exists("Item", code), f"precondition: {code} present")

    @staticmethod
    def _inject_stale_entry(member):
        """Queue a dangling payment op for a member that does not exist in the
        DB, as a prior rolled-back test would have left behind, and disarm the
        30s throttle so the next drain actually fires."""
        BP = TestFinancialBatchQueueIsolation._batch()
        BP._payment_queue[member]["FAKE-INVOICE"] = {
            "operation": "add_update",
            "timestamp": frappe.utils.now(),
            "data": {},
        }
        BP._last_processed.clear()

    def test_stale_entry_no_longer_rolls_back_the_caller(self):
        """The queue reset is now defence in depth, not the only protection.

        This test used to open with a NEGATIVE CONTROL asserting the bug: drain a
        dangling entry without resetting, and _process_member_payment_batch's
        transaction-wide frappe.db.rollback() wiped the caller's uncommitted marker.
        That control started failing once the processor was fixed to (a) skip a
        member that no longer exists -- an expected race for a queue drained up to
        five minutes later -- and (b) roll back to a SAVEPOINT, so a failure cannot
        escape the member that caused it.

        Asserting the bug still reproduces would pin the footgun as a requirement,
        so both arms now assert the caller survives: once with the stale entry
        processed, once with it reset away first.
        See tests/payment/test_financial_batch_transaction_scope.py."""
        BP = self._batch()

        # --- Stale entry processed, NOT reset: the caller must be untouched ---
        marker_unreset = f"BatchIsoUnreset-{self.uid}"
        self._insert_uncommitted_marker(marker_unreset)
        self.track_doc("Item", marker_unreset)
        self._inject_stale_entry("NONEXISTENT-MEMBER-UNRESET")
        BP._maybe_process_batches()
        self.assertTrue(
            frappe.db.exists("Item", marker_unreset),
            "draining a stale entry rolled back the caller's uncommitted work -- the "
            "per-member rollback escaped its savepoint",
        )

        # --- Reset first: the queue is empty, so nothing is processed at all ---
        marker_reset = f"BatchIsoReset-{self.uid}"
        self._insert_uncommitted_marker(marker_reset)
        self.track_doc("Item", marker_reset)
        self._inject_stale_entry("NONEXISTENT-MEMBER-RESET")
        self._reset_financial_history_batch_queue()
        BP._maybe_process_batches()
        self.assertTrue(
            frappe.db.exists("Item", marker_reset),
            "with the reset the stale entry is gone, so nothing touches the caller",
        )
        self.assertEqual(
            self._queue_depth(BP._payment_queue), 0, "reset must leave the queue empty"
        )


class TestCapturedInsertDrain(EnhancedTestCase):
    """Regression: committed records created via RAW frappe inserts (not the
    factory) must be drained at tearDown, so they don't leak into later tests
    and cause order-dependent failures. See
    docs/plans/2026-05-29-server-tests-red-baseline-triage.md (isolation root cause).
    """

    def test_raw_committed_insert_is_captured_and_drained(self):
        import frappe

        name = f"Drain Probe Customer {self.uid}"
        # Raw insert + COMMIT — bypasses factory tracking and survives rollback.
        cust = frappe.get_doc(
            {"doctype": "Customer", "customer_name": name, "customer_type": "Individual"}
        )
        cust.insert(ignore_permissions=True)
        frappe.db.commit()
        created = cust.name

        self.assertTrue(frappe.db.exists("Customer", created), "precondition: customer committed")
        self.assertIn(
            ("Customer", created),
            self._captured_inserts,
            "raw insert should be captured by the global insert hook",
        )

        # Invoke the drain directly (tearDown runs it too).
        self._drain_captured_inserts()

        self.assertFalse(
            frappe.db.exists("Customer", created),
            "captured committed record must be drained (else it leaks into later tests)",
        )

    def test_seeded_master_data_survives_the_drain(self):
        """Regression: production code RE-creating a session-seeded shared record
        inside a test body must not have that record force-deleted at tearDown.

        `test_ensure_payment_modes_exist_creates_missing` deletes Mode of Payment
        "Mollie" and lets ensure_payment_modes_exist() re-seed it. The insert hook
        captured that re-seed and the drain deleted it, destroying the seed
        `tests.setup.before_tests` made for the whole process — so every later test
        in the same shard that built a Member with payment_method="Mollie" died on
        `LinkValidationError: Could not find Payment Method: Mollie`. Invisible
        until the two modules landed in one shard (CI run 31325518967, shard 9/12).

        The negative control lives in
        `test_raw_committed_insert_is_captured_and_drained`: a non-exempt doctype
        must still be drained, so this exemption cannot be widened into a no-op.
        """
        from verenigingen.services.member.approval.application_helpers import (
            ensure_payment_modes_exist,
        )

        if frappe.db.exists("Mode of Payment", "Mollie"):
            frappe.delete_doc("Mode of Payment", "Mollie", force=True, ignore_permissions=True)
        self.assertIn(
            "Mollie",
            ensure_payment_modes_exist(),
            "precondition: the helper re-creates the removed mode",
        )
        self.assertIn(
            ("Mode of Payment", "Mollie"),
            self._captured_inserts,
            "precondition: the re-seed goes through Document.db_insert and is captured",
        )

        self._drain_captured_inserts()

        self.assertTrue(
            frappe.db.exists("Mode of Payment", "Mollie"),
            "an exempt seeded record must survive the drain, or it is gone for the "
            "rest of the process and later tests fail link validation against it",
        )

    def test_singles_setvalue_is_not_captured(self):
        # Documents the known limit: Singles writes (update_single via set_value)
        # don't go through Document.db_insert, so they're neither captured nor
        # drained — correct, since Settings must persist / are restored separately.
        # Guards against a future change that would wrongly drain them.
        import frappe

        before = list(self._captured_inserts)
        frappe.db.set_value("System Settings", "System Settings", "language", "en")
        new = [k for k in self._captured_inserts if k not in before]
        self.assertEqual(new, [], "Singles set_value must not be captured as an insert")


class TestFactoryExistsBeforeMasterDataSetup(EnhancedTestCase):
    """Pin the setUp ordering contract that hid a nine-month-old failure.

    `_ensure_production_ready_setup()` reaches `_get_or_create_income_account` and
    `_ensure_company_cost_center`, both of which call `self.factory.track_document()`.
    `self.factory` was assigned AFTER that call, so on the first EnhancedTestCase
    test of a shard process -- the only one that finds the income account missing --
    setUp raised AttributeError. `_ensure_master_data` swallowed it and aborted,
    skipping the rest of the master data including the Netherlands territory, which
    then surfaced as `LinkValidationError: Could not find Territory: Netherlands` in
    whichever unrelated test built a Customer first (#291).

    Asserting on the ordering rather than on the symptom: the symptom only appears
    on a fresh site, which is why this went unnoticed for nine months.
    """

    def test_factory_is_available_to_master_data_setup(self):
        """The factory must exist by the time master-data setup runs."""
        seen = {}
        original = type(self)._ensure_production_ready_setup

        def spy(inner_self):
            seen["had_factory"] = hasattr(inner_self, "factory")
            return original(inner_self)

        # Drive a second setUp on a throwaway instance of this same class, with
        # _ensure_production_ready_setup instrumented, so we observe the real
        # ordering rather than re-implementing it.
        probe = type(self)(self._testMethodName)
        type(self)._ensure_production_ready_setup = spy
        try:
            probe.setUp()
        finally:
            type(self)._ensure_production_ready_setup = original
            try:
                probe.tearDown()
            except Exception:
                pass

        self.assertTrue(
            seen.get("had_factory"),
            "self.factory must be assigned BEFORE _ensure_production_ready_setup(); "
            "without it, master-data setup dies on AttributeError and silently "
            "skips the rest of the master data",
        )
