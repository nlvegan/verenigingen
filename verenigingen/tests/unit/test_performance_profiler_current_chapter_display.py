"""
Regression test for #1528.

scripts/performance/performance_profiler.py::process_payment_batch_simulation()
named Member.current_chapter_display -- an HTML-fieldtype field with no DB
column -- in a frappe.get_all() fields list (same crash shape as #1516's four
sites: MySQLdb.OperationalError 1054, unconditional). The call sat inside
`except Exception: continue`, so the crash never surfaced; it just silently
skipped that payment's simulated work, and the function under-reported how
many payments it actually processed.

Reachability note (see #1528 and the follow-up filed for this): the function's
only real caller in this file, `get_unreconciled_payments(minimum_amount=0.0,
limit=batch_size)`, is called with no `customer` kwarg -- and
`get_unreconciled_payments` unconditionally returns `[]` when `customer` is
None (verenigingen/verenigingen_payments/utils/payment_utils.py). So this line
never actually executes when the script is run as intended via `main()`;
verified empirically on test_site_1. That is a separate, unrelated dead-code
defect in this script, not the field-list bug -- this test exercises the
crash site directly by monkeypatching the module-local `get_unreconciled_payments`
import to hand back one real payment, bypassing that unrelated dead branch.
"""

import frappe

import verenigingen.utils.payment_utils as payment_utils_shim
from scripts.performance import performance_profiler
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPerformanceProfilerCurrentChapterDisplay(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member()
        customer = self.factory.create_test_customer(customer_name=self.member.full_name)
        frappe.db.set_value("Member", self.member.name, "customer", customer.name, update_modified=False)
        self.payment_entry = self.create_test_payment_entry(party=customer.name)

    def test_member_lookup_does_not_crash_on_current_chapter_display(self):
        """The Member lookup must not silently drop a payment it was handed.

        Feeds process_payment_batch_simulation() exactly one payment whose
        party matches a real Member's customer -- the branch that reaches the
        buggy frappe.get_all() call -- and asserts it is actually counted as
        processed, not swallowed by the try/except around it. Also spies on
        frappe.get_all("Member", ...) directly: a "wrong fix" that quietly
        wraps just that call in its own try/except (instead of removing the
        bad field) would leave `processed == 1` too, since the outer flow
        would still run to completion -- so the outcome check alone does not
        discriminate against it. The captured fields list does.
        """
        fake_payment = frappe._dict(name=self.payment_entry.name)
        original_get_unreconciled = payment_utils_shim.get_unreconciled_payments
        payment_utils_shim.get_unreconciled_payments = lambda **kwargs: [fake_payment]

        member_get_all_fields = []
        original_get_all = frappe.get_all

        def spying_get_all(doctype, *args, **kwargs):
            if doctype == "Member":
                member_get_all_fields.append(kwargs.get("fields"))
            return original_get_all(doctype, *args, **kwargs)

        frappe.get_all = spying_get_all
        try:
            processed = performance_profiler.process_payment_batch_simulation(batch_size=1)
        finally:
            frappe.get_all = original_get_all
            payment_utils_shim.get_unreconciled_payments = original_get_unreconciled

        self.assertEqual(
            processed,
            1,
            "process_payment_batch_simulation() silently skipped the one payment handed "
            "to it -- the Member lookup crashed (current_chapter_display has no DB column) "
            "and the surrounding try/except swallowed it without a trace.",
        )
        self.assertTrue(member_get_all_fields, "the Member lookup was never reached")
        self.assertNotIn(
            "current_chapter_display",
            member_get_all_fields[0],
            "current_chapter_display has no DB column and must not be requested from Member",
        )
