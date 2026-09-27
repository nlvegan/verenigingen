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
`test_per_customer_query_cost_is_bounded_by_batch_size` guards that.

A fourth, review-found defect in the FIRST test above: with a fixed
`batch_size=50`, seeding enough newer qualifying Payment Entries on OTHER
customers could crowd the fixture's own customer out of the discovery
query's `limit=50` window entirely, failing the test even with correct code
under test. Fixed by sizing `batch_size` from a count of currently-qualifying
customers (+1), taken immediately before the call, so the discovery query's
own limit always covers every qualifying customer that exists at that moment
-- regardless of how much ambient data exists or how it is ordered.
"""

import frappe

from scripts.performance import performance_profiler
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

UNRECONCILED_CUSTOMER_PAYMENT_FILTERS = {
    "docstatus": 1,
    "unallocated_amount": [">", 0.0],
    "party_type": "Customer",
}


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
            processed = performance_profiler.process_payment_batch_simulation(batch_size=batch_size)
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

        Seeds 3 customers with 3 unreconciled Payment Entries each (one of
        them is the fixture's own customer from setUp, topped up to 3) and
        drives a batch_size of 3 -- exactly enough to be filled by the FIRST
        customer discovered alone. A flat per-customer limit with no early
        exit fetches all 3 customers' rows (9 total) to produce a batch of 3;
        the fix must fetch at most 3.
        """
        pre_existing = self._qualifying_customer_count()
        self.assertEqual(
            pre_existing,
            1,
            "expected only the fixture's own customer to qualify before seeding more -- "
            "ambient data on this site would make the row-count assertion below unreliable.",
        )

        batch_size = 3
        for _ in range(2):
            self.create_test_payment_entry(party=self.customer.name, submit=True)
        for _ in range(batch_size - 1):
            other_customer = self.factory.create_test_customer()
            for _ in range(3):
                self.create_test_payment_entry(party=other_customer.name, submit=True)

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
            performance_profiler.process_payment_batch_simulation(batch_size=batch_size)
        finally:
            frappe.get_all = original_get_all

        total_rows_fetched = sum(per_customer_call_rows)
        self.assertLessEqual(
            total_rows_fetched,
            batch_size,
            f"process_payment_batch_simulation(batch_size={batch_size}) fetched "
            f"{total_rows_fetched} Payment Entry rows across {len(per_customer_call_rows)} "
            f"per-customer quer{'y' if len(per_customer_call_rows) == 1 else 'ies'} to produce "
            f"a batch of {batch_size} -- each per-customer call must be capped at the "
            "remaining budget and the discovery loop must stop once the batch is full, or "
            "cost grows with the number of qualifying customers instead of the batch size.",
        )
