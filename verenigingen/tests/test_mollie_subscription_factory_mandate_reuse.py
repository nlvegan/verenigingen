"""Regression test for #987: the Mollie-subscription factory's SEPA Mandate
get-or-create filter can never match.

``EnhancedTestFactoryBridge.create_test_mollie_subscription`` (enhanced_test_
factory.py) looks for a reusable mandate with
``frappe.db.get_value("SEPA Mandate", {"member": ..., "docstatus": 1}, ...)``.
SEPA Mandate has no ``is_submittable`` in its DocType JSON, so every mandate a
normal path creates sits at docstatus 0 forever -- the filter matches nothing,
and the factory silently creates a brand-new mandate on every call instead of
reusing the member's existing one.

A test that only inspected the filter STRING would pass for the wrong reason
(see CLAUDE.md's TDD section): the actual behaviour this bug destroys is
REUSE, so the test below calls the factory method twice for the same member
and asserts the second call returns the SAME mandate, not a second one.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMollieSubscriptionFactoryMandateReuse(EnhancedTestCase):
    def test_second_call_reuses_the_first_mandate(self):
        member = self.create_test_member(
            first_name="Mandate",
            last_name="Reuse",
            email=f"mandate.reuse.{frappe.generate_hash(length=8)}@example.com",
            birth_date="1985-01-01",
        )

        first = self.create_test_mollie_subscription(member=member, iban="NL91ABNA0417164300")
        first_mandate_name = first["sepa_mandate"].name

        second = self.create_test_mollie_subscription(member=member, iban="NL91ABNA0417164300")
        second_mandate_name = second["sepa_mandate"].name

        self.assertEqual(
            first_mandate_name,
            second_mandate_name,
            "the second call must REUSE the member's existing active mandate, not create another one",
        )

        mandate_count = frappe.db.count("SEPA Mandate", {"member": member.name})
        self.assertEqual(1, mandate_count, "exactly one SEPA Mandate should exist for this member")
