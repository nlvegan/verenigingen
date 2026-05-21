# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for verenigingen.services.customer_group_resolver.

Covers the four branches:
1. Settings points to a leaf -> returns the leaf verbatim.
2. Settings points to a group node -> falls back to "Individual" / any leaf.
3. Settings points to a deleted name -> falls back to a leaf (treats as missing).
4. No leaf Customer Group exists at all -> throws ValidationError.

Branch (1) is already covered by ``test_customer_handling_service_integration.
test_resolve_non_group_customer_group_accepts_settings_when_leaf``. This file
adds dedicated coverage for branches (2), (3), and (4) - the cases that
matter on fresh CI sites and on misconfigured production sites.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.services.customer_group_resolver import resolve_non_group_customer_group


class TestCustomerGroupResolver(EnhancedTestCase):
    """Direct branch coverage for the customer_group_resolver helper."""

    def setUp(self):
        super().setUp()
        # Snapshot the Settings value so each test can mutate freely.
        self._original_setting = frappe.db.get_single_value(
            "Selling Settings", "customer_group"
        )

    def tearDown(self):
        # Restore Selling Settings even if the test threw.
        frappe.db.set_single_value(
            "Selling Settings", "customer_group", self._original_setting
        )
        super().tearDown()

    def test_falls_back_to_leaf_when_settings_is_group_node(self):
        """Settings pointing to a group node (e.g. the root) must be
        replaced with a leaf - never passed through verbatim. This is the
        case that broke 77 Account Creation tests in CI on 2026-04-19."""
        root = frappe.db.get_value(
            "Customer Group", {"is_group": 1}, "name", order_by="name asc"
        )
        if not root:
            self.skipTest("No group-node Customer Group on this site.")

        frappe.db.set_single_value("Selling Settings", "customer_group", root)

        resolved = resolve_non_group_customer_group()
        is_group = frappe.db.get_value("Customer Group", resolved, "is_group")
        self.assertEqual(
            is_group,
            0,
            f"Resolver returned {resolved!r} which has is_group={is_group}; "
            f"must be a leaf.",
        )

    def test_falls_back_to_leaf_when_settings_points_to_deleted_name(self):
        """A stale Settings pointer (group that has been deleted) must not
        pass through. get_value returns None for missing records, and
        'not None' is truthy, so a naive check would silently leak the
        bad name downstream into Link validation."""
        frappe.db.set_single_value(
            "Selling Settings", "customer_group", "NonexistentCustomerGroupXyz"
        )

        resolved = resolve_non_group_customer_group()
        self.assertNotEqual(resolved, "NonexistentCustomerGroupXyz")
        is_group = frappe.db.get_value("Customer Group", resolved, "is_group")
        self.assertEqual(is_group, 0)

    def test_prefers_individual_over_other_leaves(self):
        """When the Settings fallback fires (group node or missing), the
        resolver should prefer the 'Individual' leaf if it exists, before
        falling back to any other leaf in name order. This stabilises the
        choice across sites that have multiple leaves."""
        if not frappe.db.exists("Customer Group", "Individual"):
            self.skipTest("'Individual' Customer Group does not exist on this site.")
        # Ensure Individual is actually a leaf - skip otherwise so the test
        # doesn't lie about what it's exercising.
        if frappe.db.get_value("Customer Group", "Individual", "is_group") != 0:
            self.skipTest("'Individual' is a group node on this site.")

        # Force the fallback branch by pointing Settings at a group node.
        root = frappe.db.get_value("Customer Group", {"is_group": 1}, "name")
        if not root:
            self.skipTest("No group-node Customer Group on this site.")
        frappe.db.set_single_value("Selling Settings", "customer_group", root)

        self.assertEqual(resolve_non_group_customer_group(), "Individual")

    def test_throws_when_no_leaf_customer_group_exists(self):
        """If neither the Settings default nor 'Individual' nor any other
        leaf exists, the resolver must throw a clear, translatable error
        rather than returning a falsy or group-node value. This is the
        last-resort case for a site that has every Customer Group as a
        parent."""
        # Snapshot all leaf groups so we can restore them, then temporarily
        # mark each as a group node. We must NOT delete the records (Link
        # validation across the site depends on them) - flipping is_group
        # achieves the same "no leaf exists" precondition non-destructively.
        leaves = frappe.get_all("Customer Group", filters={"is_group": 0}, pluck="name")
        if not leaves:
            self.skipTest("Test cannot run when no leaf already exists.")

        try:
            for name in leaves:
                frappe.db.set_value(
                    "Customer Group", name, "is_group", 1, update_modified=False
                )
            frappe.db.set_single_value(
                "Selling Settings", "customer_group", leaves[0]
            )
            # Verify the precondition really took effect.
            still_leaves = frappe.db.get_value(
                "Customer Group", {"is_group": 0}, "name"
            )
            self.assertIsNone(
                still_leaves,
                "Test precondition not met: at least one leaf still present.",
            )

            with self.assertRaises(frappe.ValidationError) as ctx:
                resolve_non_group_customer_group()
            self.assertIn("non-group Customer Group", str(ctx.exception))
        finally:
            # Restore every flipped record so subsequent tests aren't broken.
            for name in leaves:
                frappe.db.set_value(
                    "Customer Group", name, "is_group", 0, update_modified=False
                )
