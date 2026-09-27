"""
Regression tests for #1528 and #1539.

scripts/performance/performance_profiler.py::process_payment_batch_simulation()
had two independent defects that combined to make it a no-op:

1. (#1539) Its input call, `get_unreconciled_payments(minimum_amount=0.0,
   limit=batch_size)`, was fed with no `customer` kwarg. That function
   unconditionally returns `[]` when `customer` is None
   (verenigingen_payments/utils/payment_utils.py) -- a deliberate guard other
   callers rely on and test directly (test_payment_utils.py::test_error_handling
   asserts `get_unreconciled_payments(customer=None) == []`), so it was fixed at
   the CALL SITE instead: find customers who actually have unreconciled
   payments and query per customer, matching the function's own documented
   per-customer usage.
2. (#1528) Once real payments do reach the loop, the Member lookup named
   `current_chapter_display` -- an HTML-fieldtype field with no DB column,
   same crash shape as #1516 -- in a frappe.get_all() fields list. The call
   sat inside `except Exception: continue`, so the crash never surfaced; it
   just silently skipped that payment's simulated work.

A third, review-found defect in the #1539 fix itself: the per-customer call
was given a flat `limit=batch_size` and the discovery loop never stopped once
the batch was full, so total rows fetched grew with the number of qualifying
customers instead of the batch size (O(batch_size^2) in the worst case).
`test_per_customer_query_cost_is_bounded_by_batch_size` guards that -- with a
fixture where every customer supplies exactly `batch_size` rows, a flat-limit
mutant that KEEPS an early break is indistinguishable from the fix (the first
customer alone fills the batch either way), so the fixture below deliberately
gives the first-discovered customer FEWER rows than the budget, forcing a
second customer to be queried and exposing the flat-limit-vs-remaining-budget
difference.

A fourth, review-found defect in the FIRST test above: with a fixed
`batch_size=50`, seeding enough newer qualifying Payment Entries on OTHER
customers could crowd the fixture's own customer out of the discovery
query's `limit=50` window entirely, failing the test even with correct code
under test. Fixed by sizing `batch_size` from a count of currently-qualifying
customers (+1), taken immediately before the call, so the discovery query's
own limit always covers every qualifying customer that exists at that moment
-- regardless of how much ambient data exists or how it is ordered.

A fifth, review-found defect: frappe.get_all() treats a falsy `limit` (0) as
NO limit at all, so an unguarded `batch_size=0` would make the discovery
query scan the entire Payment Entry table.
`test_batch_size_zero_or_negative_skips_the_discovery_query_entirely` guards
the early-return fix.
"""

import frappe

from scripts.performance.performance_profiler import (
    UNRECONCILED_CUSTOMER_PAYMENT_FILTERS,
    process_payment_batch_simulation,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPerformanceProfilerPaymentBatchSimulation(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member()
        self.customer = self.factory.create_test_customer(customer_name=self.member.full_name)
        frappe.db.set_value(
            "Member", self.member.name, "customer", self.customer.name, update_modified=False
        )
        # submit=True: unallocated_amount is only computed on submit, and
        # get_unreconciled_payments() filters on unallocated_amount > 0.
        self.payment_entry = self.create_test_payment_entry(party=self.customer.name, submit=True)

    def _qualifying_customer_count(self):
        """How many distinct customers currently have an unreconciled Payment
        Entry -- the same query process_payment_batch_simulation()'s
        discovery step runs. Used to size `batch_size` so the discovery
        query's own `limit` always covers every qualifying customer that
        exists AT CALL TIME, regardless of ambient data or its ordering.
        """
        return len(
            frappe.get_all(
                "Payment Entry",
                filters=UNRECONCILED_CUSTOMER_PAYMENT_FILTERS,
                pluck="party",
                distinct=True,
            )
        )

    def _force_creation(self, payment_entry_name, creation):
        """Set a Payment Entry's `creation` timestamp directly, so the
        discovery query's `order_by="creation desc"` sorts deterministically
        -- not by timing luck between fixture rows created microseconds
        apart in the same test.
        """
        frappe.db.set_value(
            "Payment Entry", payment_entry_name, "creation", creation, update_modified=False
        )

    def test_real_unreconciled_payment_is_found_and_processed_without_crashing(self):
        member_lookups = []
        original_get_all = frappe.get_all

        def spying_get_all(doctype, *args, **kwargs):
            # Forwards to the real frappe.get_all -- this is a spy, not a fake;
            # it changes nothing about what the function under test observes.
            if doctype == "Member":
                member_lookups.append(kwargs)
            return original_get_all(doctype, *args, **kwargs)

        # +1 is slack, not a requirement: the count already includes our own
        # fixture's customer (created in setUp, above), so `count` alone would
        # suffice -- the margin just guards a customer appearing between this
        # count and the call below.
        batch_size = self._qualifying_customer_count() + 1

        frappe.get_all = spying_get_all
        try:
            processed = process_payment_batch_simulation(batch_size=batch_size)
        finally:
            frappe.get_all = original_get_all

        self.assertGreaterEqual(
            processed,
            1,
            "process_payment_batch_simulation() did not count the one real unreconciled "
            "Payment Entry the fixture seeded (#1539: the call site fed "
            "get_unreconciled_payments() with no customer, which always returns []).",
        )

        our_lookups = [
            call for call in member_lookups if call.get("filters", {}).get("customer") == self.customer.name
        ]
        self.assertTrue(
            our_lookups,
            "the Member lookup was never reached for our seeded payment's customer -- the "
            "payment was never found in the first place (#1539).",
        )
        for call in member_lookups:
            self.assertNotIn(
                "current_chapter_display",
                call.get("fields") or [],
                "current_chapter_display has no DB column and must not be requested from "
                "Member (#1528).",
            )

    def test_per_customer_query_cost_is_bounded_by_batch_size(self):
        """Each per-customer call must request only the REMAINING budget, and
        the discovery loop must stop once the batch is full -- not fetch a
        flat `batch_size` rows per customer regardless of how many are
        already collected.

        Customer A has 2 qualifying Payment Entries, customer B has 5,
        batch_size=3, and discovery order is pinned by forcing each row's
        `creation` timestamp into the FUTURE (A newest, B next) rather than
        by requiring no ambient qualifying data to exist first. With
        `order_by="creation desc"`, A and B always sort ahead of anything
        carrying a real, present-day `creation` -- including setUp's own
        fixture row and any leaked/ambient Payment Entries already on the
        site -- so the batch of 3 always fills from A(2) + B(1) before
        either the ambient data or the real-timestamped rows are reached:
          - correct code: A contributes all 2 (remaining budget 3), B is then
            asked for only the remaining 1 -> total 3.
          - a flat-limit mutant (limit=batch_size on every call, regardless
            of how much is already collected) asks B for 3 (its own flat
            limit) on top of A's 2 -> total 5, even with an early-exit check
            that would otherwise look identical to the fix.
        A fixture giving every customer exactly `batch_size` rows cannot
        distinguish these: the first customer alone would fill the batch
        either way, which is why A supplies FEWER rows than the budget here.
        """
        batch_size = 3

        # Customer B: 5 qualifying Payment Entries, forced into the future
        # but behind A (below) -- and ahead of anything with a real,
        # present-day creation timestamp.
        customer_b = self.factory.create_test_customer()
        for _ in range(5):
            pe = self.create_test_payment_entry(party=customer_b.name, submit=True)
            self._force_creation(pe.name, "2099-01-01 00:00:00")

        # Customer A: 2 qualifying Payment Entries, forced further into the
        # future than B -- discovered first regardless of ambient data or
        # real-time ordering.
        customer_a = self.factory.create_test_customer()
        for _ in range(2):
            pe = self.create_test_payment_entry(party=customer_a.name, submit=True)
            self._force_creation(pe.name, "2099-01-02 00:00:00")

        per_customer_call_rows = []
        original_get_all = frappe.get_all

        def spying_get_all(doctype, *args, **kwargs):
            result = original_get_all(doctype, *args, **kwargs)
            # The discovery query passes `pluck`; the per-customer queries
            # (inside get_unreconciled_payments) do not -- this is how the two
            # Payment-Entry-doctype call shapes are told apart.
            if doctype == "Payment Entry" and "pluck" not in kwargs:
                per_customer_call_rows.append(len(result))
            return result

        frappe.get_all = spying_get_all
        try:
            process_payment_batch_simulation(batch_size=batch_size)
        finally:
            frappe.get_all = original_get_all

        total_rows_fetched = sum(per_customer_call_rows)
        self.assertLessEqual(
            total_rows_fetched,
            batch_size,
            f"process_payment_batch_simulation(batch_size={batch_size}) fetched "
            f"{total_rows_fetched} Payment Entry rows across {per_customer_call_rows} "
            f"per-customer queries -- expected at most {batch_size} (customer A's 2 rows "
            "plus only 1 of customer B's 5, since A is discovered first and fills 2 of the "
            "3-row budget). Each per-customer call must be capped at the REMAINING budget, "
            "not a flat batch_size, or cost grows with the number of qualifying customers "
            "instead of the batch size.",
        )

    def test_batch_size_zero_or_negative_skips_the_discovery_query_entirely(self):
        """frappe.get_all() treats a falsy `limit` (0) as NO limit at all, so
        an unguarded batch_size<=0 would make the discovery query scan every
        unreconciled Payment Entry on the site just to produce an empty
        batch. It must return early, before the discovery query ever runs.
        """
        for batch_size in (0, -1):
            discovery_calls = []
            original_get_all = frappe.get_all

            def spying_get_all(doctype, *args, **kwargs):
                if doctype == "Payment Entry" and "pluck" in kwargs:
                    discovery_calls.append(kwargs)
                return original_get_all(doctype, *args, **kwargs)

            frappe.get_all = spying_get_all
            try:
                processed = process_payment_batch_simulation(batch_size=batch_size)
            finally:
                frappe.get_all = original_get_all

            self.assertEqual(processed, 0, f"batch_size={batch_size} must process nothing")
            self.assertEqual(
                discovery_calls,
                [],
                f"process_payment_batch_simulation(batch_size={batch_size}) ran the discovery "
                "query anyway -- frappe.get_all() treats limit=0 as NO limit, so this would "
                "scan the whole Payment Entry table before the loop no-ops on nothing to do.",
            )
