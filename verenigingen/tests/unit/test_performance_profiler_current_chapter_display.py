"""
Regression test for #1528 and #1539.

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

This test seeds one real, submitted Payment Entry against a real Member's
customer (no monkeypatch of get_unreconciled_payments -- it runs unmodified)
and drives process_payment_batch_simulation() end to end, so it is red on
unpatched develop for BOTH defects: #1539 alone means the Member lookup is
never even reached (`our_lookups` stays empty), and #1528 alone (once #1539
is fixed) means it's reached but crashes and gets swallowed (`processed`
stays 0 despite a real, findable payment).
"""

import frappe

from scripts.performance import performance_profiler
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

    def test_real_unreconciled_payment_is_found_and_processed_without_crashing(self):
        member_lookups = []
        original_get_all = frappe.get_all

        def spying_get_all(doctype, *args, **kwargs):
            # Forwards to the real frappe.get_all -- this is a spy, not a fake;
            # it changes nothing about what the function under test observes.
            if doctype == "Member":
                member_lookups.append(kwargs)
            return original_get_all(doctype, *args, **kwargs)

        frappe.get_all = spying_get_all
        try:
            processed = performance_profiler.process_payment_batch_simulation(batch_size=50)
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
