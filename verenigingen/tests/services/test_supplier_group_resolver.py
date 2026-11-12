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
