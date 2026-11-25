# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Branch coverage for verenigingen.services.supplier_group_resolver (#2547).

erpnext version-16 rejects a Supplier whose Supplier Group is a group node, so
the resolver must never hand one out: not from Buying Settings, not as the
fallback. Each test builds a group node that sorts FIRST by name, so a
resolver that takes the first row without checking ``is_group`` is caught.
"""

import frappe

from verenigingen.services.supplier_group_resolver import resolve_non_group_supplier_group
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSupplierGroupResolver(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._original_default = frappe.db.get_single_value("Buying Settings", "supplier_group")
        # "__0" sorts before every seeded name ("_Test Supplier Group", "All Supplier Groups").
        self.first_group = frappe.get_doc(
            {
                "doctype": "Supplier Group",
                "supplier_group_name": f"__0 Resolver Group {frappe.generate_hash(length=6)}",
                "parent_supplier_group": "All Supplier Groups",
                "is_group": 1,
            }
        ).insert(ignore_permissions=True)
        self.leaf = frappe.get_doc(
            {
                "doctype": "Supplier Group",
                "supplier_group_name": f"Resolver Leaf {frappe.generate_hash(length=6)}",
                "parent_supplier_group": "All Supplier Groups",
                "is_group": 0,
            }
        ).insert(ignore_permissions=True)

    def tearDown(self):
        frappe.db.set_single_value("Buying Settings", "supplier_group", self._original_default)
        super().tearDown()

    def _assert_leaf(self, name):
        self.assertIsNotNone(name)
        self.assertEqual(frappe.db.get_value("Supplier Group", name, "is_group"), 0)

    def test_a_leaf_default_is_returned_verbatim(self):
        frappe.db.set_single_value("Buying Settings", "supplier_group", self.leaf.name)
        self.assertEqual(resolve_non_group_supplier_group(), self.leaf.name)

    def test_a_group_default_is_skipped(self):
        frappe.db.set_single_value("Buying Settings", "supplier_group", self.first_group.name)
        resolved = resolve_non_group_supplier_group()
        self.assertNotEqual(resolved, self.first_group.name)
        self._assert_leaf(resolved)

    def test_a_stale_default_is_skipped(self):
        frappe.db.set_single_value("Buying Settings", "supplier_group", "Nonexistent Supplier Group Xyz")
        resolved = resolve_non_group_supplier_group()
        self.assertNotEqual(resolved, "Nonexistent Supplier Group Xyz")
        self._assert_leaf(resolved)

    def test_without_a_default_the_fallback_is_a_leaf(self):
        frappe.db.set_single_value("Buying Settings", "supplier_group", None)
        self._assert_leaf(resolve_non_group_supplier_group())

    # --- #2550 ruling (a): the fallback is a dedicated leaf named 'Unsorted' ---

    def test_without_a_default_the_fallback_is_the_unsorted_leaf_under_the_root(self):
        frappe.db.set_single_value("Buying Settings", "supplier_group", None)
        # control: other leaves exist (self.leaf, seeded ones), so a first-leaf pick would differ
        self.assertTrue(frappe.db.exists("Supplier Group", self.leaf.name))

        resolved = resolve_non_group_supplier_group()

        self.assertEqual(resolved, "Unsorted")
        self.assertEqual(
            frappe.db.get_value("Supplier Group", "Unsorted", ["is_group", "parent_supplier_group"]),
            (0, "All Supplier Groups"),
        )

    def test_a_stale_default_also_falls_back_to_unsorted(self):
        frappe.db.set_single_value("Buying Settings", "supplier_group", "Nonexistent Supplier Group Xyz")
        self.assertEqual(resolve_non_group_supplier_group(), "Unsorted")

    def test_a_group_default_also_falls_back_to_unsorted(self):
        frappe.db.set_single_value("Buying Settings", "supplier_group", self.first_group.name)
        self.assertEqual(resolve_non_group_supplier_group(), "Unsorted")

    def test_the_fallback_is_idempotent_and_never_duplicates_unsorted(self):
        frappe.db.set_single_value("Buying Settings", "supplier_group", None)
        resolve_non_group_supplier_group()
        resolve_non_group_supplier_group()
        self.assertEqual(frappe.db.count("Supplier Group", {"supplier_group_name": "Unsorted"}), 1)

    def test_a_leaf_default_still_wins_over_unsorted(self):
        frappe.db.set_single_value("Buying Settings", "supplier_group", self.leaf.name)
        self.assertEqual(resolve_non_group_supplier_group(), self.leaf.name)

    def test_an_unsorted_that_is_a_group_node_is_refused_not_assigned(self):
        frappe.db.set_single_value("Buying Settings", "supplier_group", None)
        resolve_non_group_supplier_group()
        frappe.db.set_value("Supplier Group", "Unsorted", "is_group", 1)
        with self.assertRaises(frappe.ValidationError):
            resolve_non_group_supplier_group()
