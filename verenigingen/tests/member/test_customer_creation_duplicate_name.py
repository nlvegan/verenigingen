"""Regression tests for duplicate-name Customer creation (Option E).

Background: with Selling Settings cust_master_name="Customer Name", a Customer's
name IS its customer_name (the member's full name). Two members who share a full
name race in ERPNext's get_customer_name() check-then-insert and one insert
collides on the PK. Before the retry helper this aborted Customer creation for the
losing member. See docs/plans/2026-06-07-customer-naming-fragility-proposal.md.
"""

import frappe

from verenigingen.services.customer_group_resolver import resolve_non_group_customer_group
from verenigingen.services.member.approval.application_payments import (
    create_customer_for_member,
    insert_customer_with_duplicate_retry,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCustomerCreationDuplicateName(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # EnhancedTestCase.setUp sets frappe.flags.in_import = True (to skip user-creation
        # throttling). ERPNext's get_customer_name() guards its duplicate-suffixing with
        # `... and not frappe.flags.in_import`, so in_import=True disables the ' - N' dedup
        # entirely -- a behaviour PRODUCTION never sees (it runs with in_import False).
        # The retry helper relies on that suffixing to converge, so restore production
        # behaviour for these tests and put the flag back afterwards.
        self._saved_in_import = frappe.flags.in_import
        frappe.flags.in_import = False
        self.addCleanup(lambda: setattr(frappe.flags, "in_import", self._saved_in_import))

    def _new_customer_doc(self, customer_name):
        return frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": customer_name,
                "customer_type": "Individual",
                "customer_group": resolve_non_group_customer_group(),
                "territory": frappe.db.get_single_value("Selling Settings", "territory")
                or "All Territories",
            }
        )

    def test_retry_helper_resolves_pk_collision(self):
        """A Customer insert that collides on the name PK is retried to a suffix."""
        base = f"Dup Name {frappe.generate_hash(length=6)}"

        # Occupy the base name with a committed-in-transaction Customer.
        existing = self._new_customer_doc(base)
        existing.insert()
        self.assertEqual(existing.name, base)

        # Force a *real* PK collision: bypass autoname so the first insert attempts
        # the already-taken base name (this is the deterministic stand-in for the
        # cross-transaction race the helper exists to survive).
        dup = self._new_customer_doc(base)
        dup.name = base
        dup.flags.name_set = True

        insert_customer_with_duplicate_retry(dup)

        # Helper retried -> autoname re-derived a unique suffixed name.
        self.assertTrue(
            dup.name.startswith(f"{base} - "),
            f"expected a ' - N' suffixed name, got {dup.name!r}",
        )
        self.assertTrue(frappe.db.exists("Customer", dup.name))
        self.assertNotEqual(dup.name, base)

    def test_retry_helper_bounded_reraises(self):
        """If every attempt collides, the helper still raises (no silent swallow)."""
        base = f"Always Dup {frappe.generate_hash(length=6)}"
        existing = self._new_customer_doc(base)
        existing.insert()

        # max_attempts=1 -> no retry budget, the single forced collision must raise.
        dup = self._new_customer_doc(base)
        dup.name = base
        dup.flags.name_set = True
        with self.assertRaises(frappe.exceptions.DuplicateEntryError):
            insert_customer_with_duplicate_retry(dup, max_attempts=1)

    def test_two_same_named_members_both_get_customers(self):
        """End-to-end: two members sharing a full name each get a distinct Customer."""
        first = self.factory.create_member(first_name="Same", last_name="NameMember")
        # Force an identical full_name on a second, independently-named member.
        second = self.factory.create_member(first_name="Other", last_name="Person")
        second.first_name = first.first_name
        second.last_name = first.last_name
        second.full_name = first.full_name
        second.save()

        c1 = create_customer_for_member(first)
        c2 = create_customer_for_member(second)

        self.assertTrue(frappe.db.exists("Customer", c1.name))
        self.assertTrue(frappe.db.exists("Customer", c2.name))
        self.assertNotEqual(c1.name, c2.name, "same-named members must get distinct Customers")
        # Each Customer is linked back to its own member.
        self.assertEqual(frappe.db.get_value("Customer", c1.name, "member"), first.name)
        self.assertEqual(frappe.db.get_value("Customer", c2.name, "member"), second.name)
