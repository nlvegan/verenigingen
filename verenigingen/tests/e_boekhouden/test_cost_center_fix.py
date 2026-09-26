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

import hashlib
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
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase, suspend_insert_capture
from verenigingen.tests.utils.secure_operation_race_helpers import duplicate_key_result
from verenigingen.utils.secure_operations import SecureOperationResult


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
        # Shared, lazily-built fixture: Company.on_update() cascades into a
        # default Cost Center hierarchy (root + "Main"), so this build must be
        # exempted from the captured-insert drain the same way
        # get_eur_test_company() is, or whichever test class runs first "owns"
        # the row and its teardown deletes it out from under every later class
        # in the shard (#328 shape).
        with suspend_insert_capture():
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


class _IsolatedCompanyTestBase(EnhancedTestCase):
    """A throwaway EUR company built FRESH inside each test method's own
    transaction -- deliberately NOT `_CostCenterTestBase.company`.

    That fixture is built once in setUpClass and its insert is committed, so
    later deleting its default cost centers and reinserting a same-named root
    collides with `_drain_captured_inserts`' own pre-delete `frappe.db.
    rollback()`: that rollback resurrects the ORIGINAL committed root+"Main"
    pair under the identical autoname (Cost Center autonames as
    "{cost_center_name} - {abbr}", which is deterministic per company), and the
    drain then correctly refuses to delete a root that -- once resurrected --
    has a real child ("Cannot delete ... as it has child nodes"). Measured: this
    produces a harmless but noisy TEST-LEAK warning on every test that deletes
    and recreates the shared company's root.

    Building the company here instead means the pre-drain rollback has nothing
    pre-existing to resurrect: the company was never committed, so the whole
    scenario (company, its auto-created defaults, this test's delete+recreate)
    is undone together and there is nothing left with the captured name.
    """

    def _create_isolated_company(self):
        # Keyed on the test method itself (not a shared counter) so two test
        # CLASSES running their own test methods can never generate the same
        # company/abbr pair, regardless of execution order.
        tag = hashlib.md5(f"{type(self).__name__}.{self._testMethodName}".encode()).hexdigest()[:6]
        name = f"TEST EBkh RootCC Fix {tag}"
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = f"TR{tag}"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def _delete_all_cost_centers(self, company):
        # Leaves (is_group=0) before groups: a group with a live child cannot
        # be deleted first.
        for cc in frappe.get_all(
            "Cost Center", filters={"company": company}, fields=["name"], order_by="is_group asc"
        ):
            frappe.delete_doc("Cost Center", cc.name, force=True, ignore_permissions=True)

    def _persist_root_cost_center(self, company):
        """Insert a root Cost Center for `company` the same way ensure_root_
        cost_center()'s create path does (post-#1359), bypassing the function
        under test -- used to plant the row a "concurrent creator" already won
        the race to insert."""
        abbr = frappe.db.get_value("Company", company, "abbr")
        doc = frappe.new_doc("Cost Center")
        doc.cost_center_name = company
        doc.company = company
        doc.is_group = 1
        doc.parent_cost_center = None
        doc.flags.ignore_mandatory = True
        doc.insert(ignore_permissions=True)
        self.assertEqual(doc.name, f"{company} - {abbr}")
        return doc.name


class TestEnsureRootCostCenterCreatePath(_IsolatedCompanyTestBase):
    """#1359: ensure_root_cost_center()'s create branch is only reached when a
    company has NO cost center matching any of its three existing-root checks
    (root by is_group+blank-parent, abbr-pattern name, cost_center_name==company).
    In practice that only happens for a company whose default cost centers were
    deleted after Company.on_update() auto-created them (manual cleanup, e.g.) --
    so the test reproduces that state directly rather than asserting on the
    auto-created row every other test in this module relies on.
    """

    def test_create_path_reached_when_defaults_are_gone(self):
        company = self._create_isolated_company()
        self._delete_all_cost_centers(company)
        self.assertEqual(frappe.db.count("Cost Center", {"company": company}), 0)

        root = ensure_root_cost_center(company)

        self.assertTrue(root, "create branch must produce a usable root, not None")
        self.assertEqual(frappe.db.get_value("Cost Center", root, "is_group"), 1)
        self.assertIn(frappe.db.get_value("Cost Center", root, "parent_cost_center"), ("", None))
        self.assertEqual(frappe.db.get_value("Cost Center", root, "cost_center_name"), company)

    def test_create_path_does_not_log_an_error(self):
        # A successful create is not a failure path; no Error Log should record it.
        error_log_marker = frappe.utils.now_datetime()
        company = self._create_isolated_company()
        self._delete_all_cost_centers(company)

        root = ensure_root_cost_center(company)

        self.assertTrue(root)
        self.assertFalse(
            frappe.db.exists(
                "Error Log",
                {"method": "Cost Center Creation Failed", "creation": [">=", error_log_marker]},
            )
        )


class TestEnsureRootCostCenterDuplicateRace(_IsolatedCompanyTestBase):
    """secure_document_operation() swallows the DuplicateEntryError a concurrent
    caller's race raises here and reports success=False instead of re-raising, so
    the `except frappe.DuplicateEntryError` ensure_root_cost_center() relied on to
    recognise "another process just created this" was unreachable -- and doubly
    so before #1359, since the create attempt it wrapped always failed on
    MandatoryError first (see TestEnsureRootCostCenterCreatePath). Now that the
    create attempt can succeed, this race is live and must be recoverable.
    """

    def test_duplicate_race_returns_the_winners_root_instead_of_none(self):
        # The "concurrent creator" already won: its root row genuinely exists.
        company = self._create_isolated_company()
        self._delete_all_cost_centers(company)
        winner_name = self._persist_root_cost_center(company)

        # Simulate the race window itself: ensure_root_cost_center()'s own
        # pre-checks (is_group+blank-parent lookup, abbr-pattern `exists`,
        # cost_center_name==company lookup) must all report NOTHING found --
        # that is the window a real concurrent creator wins in -- even though
        # `winner` already exists, since planting it up front (as above) would
        # otherwise let the FIRST pre-check find it directly and never touch
        # the create attempt / duplicate-key recovery this test targets. Only
        # the RECOVERY lookup that runs AFTER the mocked failed insert may see
        # it for real.
        real_get_value = frappe.db.get_value
        real_exists = frappe.db.exists
        op_attempted = {"done": False}

        def _fake_get_value(doctype, filters=None, *args, **kwargs):
            if not op_attempted["done"] and doctype == "Cost Center" and isinstance(filters, dict):
                return None
            return real_get_value(doctype, filters, *args, **kwargs)

        def _fake_exists(doctype, *args, **kwargs):
            if not op_attempted["done"] and doctype == "Cost Center":
                return False
            return real_exists(doctype, *args, **kwargs)

        def _duplicate_result(*args, **kwargs):
            op_attempted["done"] = True
            return duplicate_key_result("Cost Center", winner_name)

        with patch.object(frappe.db, "get_value", side_effect=_fake_get_value):
            with patch.object(frappe.db, "exists", side_effect=_fake_exists):
                with patch.object(ccfix, "secure_document_operation", side_effect=_duplicate_result):
                    result = ensure_root_cost_center(company)

        self.assertEqual(result, winner_name)

    def test_non_duplicate_failure_still_logs_and_returns_none(self):
        # Control: a genuine (non-duplicate) failure must still be reported,
        # and must NOT be papered over as "found the existing one" even when
        # a row that WOULD match the recovery lookup genuinely exists. A
        # fixture with no matching row at all cannot discriminate this: an
        # `is_duplicate_key_error()` that always returned True would still
        # find nothing and return None "by accident", passing identically to
        # the real, correct code. So plant a real match the same way the race
        # test does, and use the same fake-get_value/exists-until-the-
        # operation-is-attempted harness to force the create attempt without
        # letting the pre-checks find it first.
        self.expectErrorLog("Cost Center Creation Failed")
        error_log_marker = frappe.utils.now_datetime()
        company = self._create_isolated_company()
        self._delete_all_cost_centers(company)
        existing_name = self._persist_root_cost_center(company)

        real_get_value = frappe.db.get_value
        real_exists = frappe.db.exists
        op_attempted = {"done": False}

        def _fake_get_value(doctype, filters=None, *args, **kwargs):
            if not op_attempted["done"] and doctype == "Cost Center" and isinstance(filters, dict):
                return None
            return real_get_value(doctype, filters, *args, **kwargs)

        def _fake_exists(doctype, *args, **kwargs):
            if not op_attempted["done"] and doctype == "Cost Center":
                return False
            return real_exists(doctype, *args, **kwargs)

        other_failure = SecureOperationResult(False, "test_root_cc_other_failure")
        other_failure.add_error("Operation failed: PermissionError('No create permission for Cost Center')")

        def _other_failure_result(*args, **kwargs):
            op_attempted["done"] = True
            return other_failure

        with patch.object(frappe.db, "get_value", side_effect=_fake_get_value):
            with patch.object(frappe.db, "exists", side_effect=_fake_exists):
                with patch.object(ccfix, "secure_document_operation", side_effect=_other_failure_result):
                    result = ensure_root_cost_center(company)

        # A genuine non-duplicate failure must return None -- NOT
        # `existing_name`, even though that row is right there waiting for a
        # wrongly-lenient duplicate-key check to "recover" into.
        self.assertIsNone(result)
        self.assertNotEqual(result, existing_name)
        self.assertTrue(
            frappe.db.exists(
                "Error Log",
                {"method": "Cost Center Creation Failed", "creation": [">=", error_log_marker]},
            )
        )


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
