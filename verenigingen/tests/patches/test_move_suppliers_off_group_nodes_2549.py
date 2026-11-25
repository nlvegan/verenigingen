"""#2549: the patch moves Suppliers off Supplier Group nodes into the leaf 'Unsorted'.

Probe shortcut: ``execute`` is called directly (not through the patch runner), and a
Supplier is placed in a group node by a plain insert, which this bench's erpnext still
accepts (the v16 save-time refusal is not in the local tree). Only rows the test made
are asserted on; the site may hold other root-group Suppliers, which the patch also moves.
"""

import importlib

import frappe
from frappe.modules import patch_handler
from frappe.tests.utils import FrappeTestCase

from verenigingen.setup import patch_fragments

PATCH = "verenigingen.patches.v2_2.move_suppliers_off_group_nodes_2549"
ROOT = "All Supplier Groups"


def _run_move_patch_2549():
    importlib.import_module(PATCH).execute()


class TestMoveSuppliersOffGroupNodes(FrappeTestCase):
    def setUp(self):
        suffix = frappe.generate_hash(length=6)
        self.mid_group_2549 = frappe.get_doc(
            {
                "doctype": "Supplier Group",
                "supplier_group_name": f"Mid Node 2549 {suffix}",
                "parent_supplier_group": ROOT,
                "is_group": 1,
            }
        ).insert(ignore_permissions=True)
        self.leaf_2549 = frappe.get_doc(
            {
                "doctype": "Supplier Group",
                "supplier_group_name": f"Leaf 2549 {suffix}",
                "parent_supplier_group": ROOT,
                "is_group": 0,
            }
        ).insert(ignore_permissions=True)
        self.in_root = self._supplier_2549("Root", ROOT)
        self.in_mid = self._supplier_2549("Mid", self.mid_group_2549.name)
        self.in_leaf = self._supplier_2549("Leaf", self.leaf_2549.name)
        self.in_none = self._supplier_2549("None", None)

    def _supplier_2549(self, label, group):
        doc = frappe.get_doc(
            {
                "doctype": "Supplier",
                "supplier_name": f"S2549 {label} {frappe.generate_hash(length=6)}",
                "supplier_type": "Company",
                "supplier_group": group,
            }
        ).insert()
        return doc.name

    def _group_2549(self, supplier):
        return frappe.db.get_value("Supplier", supplier, "supplier_group")

    def test_root_and_other_group_node_suppliers_move_to_unsorted(self):
        self.assertEqual(self._group_2549(self.in_root), ROOT, "control: starts on the root")
        _run_move_patch_2549()
        self.assertEqual(self._group_2549(self.in_root), "Unsorted")
        self.assertEqual(self._group_2549(self.in_mid), "Unsorted")
        self.assertEqual(frappe.db.get_value("Supplier Group", "Unsorted", "is_group"), 0)

    def test_leaf_and_empty_group_suppliers_are_untouched(self):
        _run_move_patch_2549()
        self.assertEqual(self._group_2549(self.in_leaf), self.leaf_2549.name)
        self.assertIsNone(self._group_2549(self.in_none))

    def test_the_patch_is_idempotent(self):
        _run_move_patch_2549()
        before = frappe.db.get_value("Supplier", self.in_root, "modified")
        _run_move_patch_2549()
        self.assertEqual(self._group_2549(self.in_root), "Unsorted")
        self.assertEqual(frappe.db.count("Supplier Group", {"supplier_group_name": "Unsorted"}), 1)
        self.assertEqual(frappe.db.get_value("Supplier", self.in_root, "modified"), before)

    def test_it_still_creates_unsorted_when_no_supplier_needs_moving(self):
        frappe.db.delete("Supplier", {"name": ["in", [self.in_root, self.in_mid]]})
        frappe.db.delete("Supplier Group", {"name": "Unsorted"})
        _run_move_patch_2549()
        self.assertTrue(frappe.db.exists("Supplier Group", "Unsorted"))

    def test_the_patch_is_registered_as_a_fragment(self):
        patch_fragments.install()
        self.assertIn(PATCH, patch_handler.get_patches_from_app("verenigingen"))
