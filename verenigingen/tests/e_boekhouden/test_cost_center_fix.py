"""
Tests for verenigingen/e_boekhouden/utils/eboekhouden_cost_center_fix.py

Covers the cost-center hierarchy helpers that are DB-backed but need NO live
eBoekhouden HTTP connection:

  - ensure_root_cost_center
  - create_cost_center_safe (create + already-exists + group-promotion paths)
  - fix_cost_center_groups (whitelisted)
  - cleanup_cost_centers (whitelisted)
  - add_eboekhouden_id_field (whitelisted; idempotent)
  - migrate_cost_centers_with_hierarchy (eBoekhouden API stubbed)

These complement test_cost_center_creation.py / test_cost_center_parsing.py /
test_cost_center_ui_integration.py which target the *settings* cost-center
functions, not this module.

Run with:
    bench --site test_site_5 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_cost_center_fix
"""

import json
import unittest
from unittest.mock import patch

import frappe

from verenigingen.e_boekhouden.utils import eboekhouden_cost_center_fix as ccfix
from verenigingen.e_boekhouden.utils.eboekhouden_cost_center_fix import (
    add_eboekhouden_id_field,
    cleanup_cost_centers,
    create_cost_center_safe,
    ensure_root_cost_center,
    fix_cost_center_groups,
    migrate_cost_centers_with_hierarchy,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _CostCenterTestBase(EnhancedTestCase):
    """Provides a dedicated EUR company so cost-center tests don't collide with
    the shared _Test Company fixtures (and so EUR/Dutch logic is exercised)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()
        cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST EBkh CostCenter Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TECC"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def _persist_cost_center(self, name, is_group=0, parent=None):
        full = f"{name} - {self.abbr}"
        if frappe.db.exists("Cost Center", full):
            return full
        if parent is None:
            parent = ensure_root_cost_center(self.company)
        doc = frappe.new_doc("Cost Center")
        doc.cost_center_name = name
        doc.company = self.company
        doc.is_group = is_group
        doc.parent_cost_center = parent
        doc.insert(ignore_permissions=True)
        return doc.name


class TestEnsureRootCostCenter(_CostCenterTestBase):
    def test_returns_existing_root(self):
        root = ensure_root_cost_center(self.company)
        self.assertTrue(root)
        # Idempotent: a second call returns the same root
        self.assertEqual(ensure_root_cost_center(self.company), root)

    def test_root_is_group(self):
        root = ensure_root_cost_center(self.company)
        self.assertEqual(frappe.db.get_value("Cost Center", root, "is_group"), 1)


class TestCreateCostCenterSafe(_CostCenterTestBase):
    def test_create_new_leaf(self):
        root = ensure_root_cost_center(self.company)
        cc_data = {"id": 9001, "code": "9001", "name": "EBkh Safe Leaf A"}
        result = create_cost_center_safe(cc_data, self.company, root, {})
        self.assertTrue(result["success"])
        self.assertTrue(frappe.db.exists("Cost Center", result["name"]))
        self.assertEqual(frappe.db.get_value("Cost Center", result["name"], "is_group"), 0)

    def test_create_group_when_has_children(self):
        root = ensure_root_cost_center(self.company)
        cc_data = {"id": 9002, "code": "9002", "name": "EBkh Safe Group B"}
        result = create_cost_center_safe(cc_data, self.company, root, {}, has_children={9002})
        self.assertTrue(result["success"])
        self.assertEqual(frappe.db.get_value("Cost Center", result["name"], "is_group"), 1)

    def test_existing_returns_exists_flag(self):
        root = ensure_root_cost_center(self.company)
        cc_data = {"id": 9003, "code": "9003", "name": "EBkh Safe Existing C"}
        first = create_cost_center_safe(cc_data, self.company, root, {})
        self.assertTrue(first["success"])
        # Second call: cost center already exists
        second = create_cost_center_safe(cc_data, self.company, root, {})
        self.assertFalse(second["success"])
        self.assertTrue(second["exists"])
        self.assertEqual(second["name"], first["name"])

    def test_existing_promoted_to_group(self):
        root = ensure_root_cost_center(self.company)
        cc_data = {"id": 9004, "code": "9004", "name": "EBkh Safe Promote D"}
        # Create as leaf
        first = create_cost_center_safe(cc_data, self.company, root, {})
        self.assertEqual(frappe.db.get_value("Cost Center", first["name"], "is_group"), 0)
        # Now it gains children -> create_cost_center_safe should promote it
        second = create_cost_center_safe(cc_data, self.company, root, {}, has_children={9004})
        self.assertTrue(second["exists"])
        self.assertEqual(frappe.db.get_value("Cost Center", second["name"], "is_group"), 1)

    def test_name_built_from_code_and_name(self):
        root = ensure_root_cost_center(self.company)
        cc_data = {"id": 9005, "code": "9005", "name": "EBkh Coded E"}
        result = create_cost_center_safe(cc_data, self.company, root, {})
        self.assertIn("9005 - EBkh Coded E", result["name"])

    def test_fallback_to_id_when_no_name(self):
        root = ensure_root_cost_center(self.company)
        cc_data = {"id": 9006, "code": "", "name": "", "description": ""}
        result = create_cost_center_safe(cc_data, self.company, root, {})
        self.assertTrue(result["success"])
        self.assertIn("9006", result["name"])

    def test_error_when_no_name_id_or_description(self):
        root = ensure_root_cost_center(self.company)
        cc_data = {"id": "", "code": "", "name": "", "description": ""}
        result = create_cost_center_safe(cc_data, self.company, root, {})
        self.assertFalse(result["success"])
        self.assertIn("No cost center name", result["error"])


class TestFixCostCenterGroups(_CostCenterTestBase):
    def test_promotes_parent_with_children(self):
        root = ensure_root_cost_center(self.company)
        # Create parent as a group, add a child while it is still a group...
        parent = self._persist_cost_center("EBkh FixParent", is_group=1, parent=root)
        self._persist_cost_center("EBkh FixChild", is_group=0, parent=parent)
        # ...then flip the parent to a leaf at DB level to simulate the bad state
        # fix_cost_center_groups is designed to repair.
        frappe.db.set_value("Cost Center", parent, "is_group", 0)
        frappe.db.commit()

        result = fix_cost_center_groups(self.company)
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["fixed"], 1)
        self.assertEqual(frappe.db.get_value("Cost Center", parent, "is_group"), 1)


class TestCleanupCostCenters(_CostCenterTestBase):
    def test_reparents_orphans_to_root(self):
        root = ensure_root_cost_center(self.company)
        # Create an orphan: a cost center with empty parent_cost_center
        orphan = self._persist_cost_center("EBkh Orphan", is_group=0, parent=root)
        frappe.db.set_value("Cost Center", orphan, "parent_cost_center", "")
        frappe.db.commit()

        result = cleanup_cost_centers(self.company)
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["fixed"], 1)
        self.assertEqual(frappe.db.get_value("Cost Center", orphan, "parent_cost_center"), root)


class TestAddEboekhoudenIdField(EnhancedTestCase):
    def test_idempotent(self):
        # The custom field may already exist; the function must succeed either way.
        result = add_eboekhouden_id_field()
        self.assertTrue(result["success"])
        # Column should now exist
        self.assertTrue(frappe.db.has_column("Cost Center", "eboekhouden_id"))
        # Second call: "already exists" path
        result2 = add_eboekhouden_id_field()
        self.assertTrue(result2["success"])


class TestMigrateCostCentersWithHierarchy(_CostCenterTestBase):
    """migrate_cost_centers_with_hierarchy fetches via EBoekhoudenAPI.get_cost_centers.
    We stub that single HTTP boundary method; no live connection is made."""

    class _StubSettings:
        def __init__(self, company):
            self.default_company = company

    def _patched_api(self, items):
        """Return a patch context for EBoekhoudenAPI used inside the function."""
        api_payload = {"success": True, "data": json.dumps({"items": items})}

        class _StubAPI:
            def __init__(self, settings):
                pass

            def get_cost_centers(self_inner):
                return api_payload

        return patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI",
            _StubAPI,
        )

    def test_no_cost_centers(self):
        with self._patched_api([]):
            result = migrate_cost_centers_with_hierarchy(self._StubSettings(self.company))
        self.assertTrue(result["success"])
        self.assertIn("No cost centers", result["message"])

    def test_api_failure_propagates(self):
        class _FailAPI:
            def __init__(self, settings):
                pass

            def get_cost_centers(self):
                return {"success": False, "error": "boom"}

        with patch("verenigingen.e_boekhouden.utils.eboekhouden_api.EBoekhoudenAPI", _FailAPI):
            result = migrate_cost_centers_with_hierarchy(self._StubSettings(self.company))
        self.assertFalse(result["success"])
        self.assertIn("boom", result["error"])

    def test_no_default_company(self):
        with self._patched_api([{"id": 1, "code": "1", "name": "X"}]):
            result = migrate_cost_centers_with_hierarchy(self._StubSettings(None))
        self.assertFalse(result["success"])
        self.assertIn("default company", result["error"].lower())

    def test_creates_parent_then_child(self):
        items = [
            {"id": 7001, "code": "7001", "name": "EBkh Parent P", "parentId": 0},
            {"id": 7002, "code": "7002", "name": "EBkh Child Q", "parentId": 7001},
        ]
        with self._patched_api(items):
            result = migrate_cost_centers_with_hierarchy(self._StubSettings(self.company))
        self.assertTrue(result["success"])
        self.assertEqual(result["total"], 2)
        # Parent created as group (it has a child)
        parent_name = frappe.db.get_value(
            "Cost Center",
            {"cost_center_name": "7001 - EBkh Parent P", "company": self.company},
            "name",
        )
        self.assertTrue(parent_name)
        self.assertEqual(frappe.db.get_value("Cost Center", parent_name, "is_group"), 1)
        # Child created under the parent
        child_name = frappe.db.get_value(
            "Cost Center",
            {"cost_center_name": "7002 - EBkh Child Q", "company": self.company},
            "name",
        )
        self.assertTrue(child_name)
        self.assertEqual(frappe.db.get_value("Cost Center", child_name, "parent_cost_center"), parent_name)


if __name__ == "__main__":
    unittest.main()
