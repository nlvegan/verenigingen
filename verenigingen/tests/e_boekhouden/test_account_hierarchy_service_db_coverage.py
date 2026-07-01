"""Integration-level coverage for the DB-backed parts of
``verenigingen/e_boekhouden/services/account_hierarchy_service.py``.

The pure keyword/range helpers are covered by ``test_account_services.py``.
This module drives the DB-touching functions against REAL ERPNext Account
and Company docs (no eBoekhouden HTTP boundary is involved):

- ``find_or_create_group_account`` -- cache hit, existing-group short-circuit,
  root-parent resolution, group creation (parent/root_type/company/is_group),
  dry-run placeholder, missing-root guard, and the insert-exception guard.
- ``reorganize_account_hierarchy`` -- config guards (no company / no mappings)
  and the dry-run "would_move" / root-type-mismatch skip branches.
- ``reclassify_accounts_by_group_mappings`` -- config guards and the dry-run
  "would_update" account-type reclassification branch.

All group/leaf accounts and all E-Boekhouden Settings changes are written
WITHOUT commit, so EnhancedTestCase's per-method rollback isolates them. The
whitelisted orchestrators are exercised with ``dry_run=True`` so they never hit
their internal ``frappe.db.commit()`` (which would leak past rollback).

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_account_hierarchy_service_db_coverage
"""

import frappe

from verenigingen.e_boekhouden.services.account_hierarchy_service import (
    find_or_create_group_account,
    reclassify_accounts_by_group_mappings,
    reorganize_account_hierarchy,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


def _uniq(prefix):
    return f"{prefix} {frappe.generate_hash(length=6)}"


class _AccountHierarchyBase(EnhancedTestCase):
    """Shared EUR company with a full default ERPNext chart of accounts."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def _root_group_for(self, root_type):
        """Return the (parentless) root group account for a root_type."""
        rows = frappe.db.sql(
            """
            SELECT name FROM `tabAccount`
            WHERE company = %s AND root_type = %s AND is_group = 1
              AND (parent_account IS NULL OR parent_account = '')
            LIMIT 1
            """,
            (self.company, root_type),
        )
        return rows[0][0] if rows else None

    def _make_group_account(self, account_name, root_type):
        """Insert a real group Account under the matching root (uncommitted)."""
        doc = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": account_name,
                "company": self.company,
                "root_type": root_type,
                "is_group": 1,
                "parent_account": self._root_group_for(root_type),
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def _make_leaf_account(self, account_name, root_type, account_type=""):
        """Insert a real leaf Account under the matching root group (uncommitted)."""
        doc = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": account_name,
                "company": self.company,
                "root_type": root_type,
                "is_group": 0,
                "parent_account": self._root_group_for(root_type),
                "account_type": account_type or None,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def _persist_settings(self, default_company, mapping_rows):
        """Write E-Boekhouden Settings in-memory (no commit) for the orchestrators.

        Rolled back by EnhancedTestCase.tearDown. ``mapping_rows`` is a list of
        dicts with group_code/group_name/root_type/account_type.
        """
        settings = frappe.get_single("E-Boekhouden Settings")
        settings.default_company = default_company
        settings.set("group_type_mappings", [])
        for row in mapping_rows:
            settings.append("group_type_mappings", row)
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)
        return settings


# ---------------------------------------------------------------------------
# find_or_create_group_account
# ---------------------------------------------------------------------------
class TestFindOrCreateGroupAccount(_AccountHierarchyBase):
    def test_creates_group_under_correct_root(self):
        name = _uniq("VVN Liquide")
        groups_created = []
        result = find_or_create_group_account(
            group_code="001",
            group_name=name,
            root_type="Asset",
            company=self.company,
            dry_run=False,
            created_groups={},
            groups_created=groups_created,
        )
        self.assertIsNotNone(result)
        doc = frappe.get_doc("Account", result)
        # Real created doc must carry the requested classification/company.
        self.assertEqual(doc.is_group, 1)
        self.assertEqual(doc.root_type, "Asset")
        self.assertEqual(doc.company, self.company)
        # Parent must be the Asset ROOT (a parentless Asset group), not any group.
        self.assertEqual(doc.parent_account, self._root_group_for("Asset"))
        parent = frappe.get_doc("Account", doc.parent_account)
        self.assertEqual(parent.root_type, "Asset")
        self.assertFalse(parent.parent_account)
        # Bookkeeping list records the creation.
        self.assertEqual(len(groups_created), 1)
        self.assertEqual(groups_created[0]["status"], "created")
        self.assertEqual(groups_created[0]["account_id"], result)

    def test_cache_hit_short_circuits(self):
        """A pre-seeded cache entry is returned without touching the DB."""
        sentinel = "Cached Account - XYZ"
        created_groups = {"001_Asset": sentinel}
        groups_created = []
        result = find_or_create_group_account(
            group_code="001",
            group_name="Anything",
            root_type="Asset",
            company=self.company,
            dry_run=False,
            created_groups=created_groups,
            groups_created=groups_created,
        )
        self.assertEqual(result, sentinel)
        # Nothing created because the cache key matched.
        self.assertEqual(groups_created, [])

    def test_existing_group_is_reused_not_duplicated(self):
        name = _uniq("VVN Existing Grp")
        existing = self._make_group_account(name, "Asset")
        groups_created = []
        result = find_or_create_group_account(
            group_code="050",
            group_name=name,
            root_type="Asset",
            company=self.company,
            dry_run=False,
            created_groups={},
            groups_created=groups_created,
        )
        # Returns the already-existing group; no new doc, no bookkeeping entry.
        self.assertEqual(result, existing.name)
        self.assertEqual(groups_created, [])
        self.assertEqual(
            frappe.db.count("Account", {"account_name": name, "company": self.company, "is_group": 1}),
            1,
        )

    def test_dry_run_returns_placeholder_without_creating(self):
        name = _uniq("VVN DryRun Grp")
        groups_created = []
        result = find_or_create_group_account(
            group_code="060",
            group_name=name,
            root_type="Liability",
            company=self.company,
            dry_run=True,
            created_groups={},
            groups_created=groups_created,
        )
        self.assertEqual(result, f"{name} - {self.company}")
        # No real Account row was inserted.
        self.assertFalse(frappe.db.exists("Account", {"account_name": name, "company": self.company}))
        self.assertEqual(len(groups_created), 1)
        self.assertEqual(groups_created[0]["status"], "would_create")
        self.assertEqual(groups_created[0]["parent"], self._root_group_for("Liability"))

    def test_missing_root_returns_none(self):
        """A company with no root account of the requested type yields None."""
        result = find_or_create_group_account(
            group_code="001",
            group_name="Whatever",
            root_type="Asset",
            company="Nonexistent Company " + frappe.generate_hash(length=6),
            dry_run=False,
            created_groups={},
            groups_created=[],
        )
        self.assertIsNone(result)

    def test_insert_exception_returns_none(self):
        """When the group insert fails (duplicate name) the guard returns None.

        A leaf account with the same account_name already exists, so the group
        insert collides on the generated Account name -> DuplicateEntryError is
        caught -> None. The existing-group probe (is_group=1) does not see the
        leaf, so execution reaches the insert.
        """
        name = _uniq("VVN Collide")
        self._make_leaf_account(name, "Asset")
        groups_created = []
        result = find_or_create_group_account(
            group_code="070",
            group_name=name,  # same name as the leaf -> collides on insert
            root_type="Asset",
            company=self.company,
            dry_run=False,
            created_groups={},
            groups_created=groups_created,
        )
        self.assertIsNone(result)
        self.assertEqual(groups_created, [])


# ---------------------------------------------------------------------------
# reorganize_account_hierarchy (dry-run + guards)
# ---------------------------------------------------------------------------
class TestReorganizeAccountHierarchy(_AccountHierarchyBase):
    LIQUIDE = {
        "group_code": "001",
        "group_name": "Liquide middelen",
        "root_type": "Asset",
        "account_type": "Bank",
    }

    def test_error_when_no_default_company(self):
        self._persist_settings("", [self.LIQUIDE])
        result = reorganize_account_hierarchy(dry_run=True)
        self.assertFalse(result["success"])
        self.assertIn("Default company", result["error"])

    def test_error_when_no_mappings(self):
        self._persist_settings(self.company, [])
        result = reorganize_account_hierarchy(dry_run=True)
        self.assertFalse(result["success"])
        self.assertIn("No group type mappings", result["error"])

    def test_dry_run_would_move_matching_account(self):
        name = _uniq("Triodos Bank Rekening")
        leaf = self._make_leaf_account(name, "Asset")
        self._persist_settings(self.company, [self.LIQUIDE])

        result = reorganize_account_hierarchy(dry_run=True)
        self.assertTrue(result["success"])
        self.assertTrue(result["dry_run"])

        change = self._find_change(result["changes"], name)
        self.assertIsNotNone(change, "matched account missing from changes")
        self.assertEqual(change["status"], "would_move")
        self.assertEqual(change["group_code"], "001")
        self.assertEqual(change["new_parent_name"], "Liquide middelen")
        self.assertEqual(change["old_parent"], leaf.parent_account)
        # dry-run must not actually re-parent the account.
        self.assertEqual(frappe.db.get_value("Account", leaf.name, "parent_account"), leaf.parent_account)

    def test_dry_run_skips_root_type_mismatch(self):
        # Name matches an Asset group ("rabobank") but the account itself is
        # Expense, so re-homing it would change its root_type -> must be skipped.
        # (Avoid "kosten"/"vergoeding" which are in Liquide middelen's
        # EXCLUDE_PATTERNS and would suppress the match entirely.)
        name = _uniq("Rabobank betaalrekening")
        self._make_leaf_account(name, "Expense")
        self._persist_settings(self.company, [self.LIQUIDE])

        result = reorganize_account_hierarchy(dry_run=True)
        self.assertTrue(result["success"])
        change = self._find_change(result["changes"], name)
        self.assertIsNotNone(change)
        self.assertEqual(change["status"], "skipped")
        self.assertIn("Would change root_type", change["reason"])

    @staticmethod
    def _find_change(changes, account_name):
        for c in changes:
            if c.get("account_name") == account_name:
                return c
        return None


# ---------------------------------------------------------------------------
# reclassify_accounts_by_group_mappings (dry-run + guards)
# ---------------------------------------------------------------------------
class TestReclassifyAccountsByGroupMappings(_AccountHierarchyBase):
    VORDERINGEN = {
        "group_code": "002",
        "group_name": "Vorderingen",
        "root_type": "Asset",
        "account_type": "Receivable",
    }

    def test_error_when_no_default_company(self):
        self._persist_settings("", [self.VORDERINGEN])
        result = reclassify_accounts_by_group_mappings(dry_run=True)
        self.assertFalse(result["success"])
        self.assertIn("Default company", result["error"])

    def test_error_when_no_mappings(self):
        self._persist_settings(self.company, [])
        result = reclassify_accounts_by_group_mappings(dry_run=True)
        self.assertFalse(result["success"])
        self.assertIn("No group type mappings", result["error"])

    def test_dry_run_would_update_account_type(self):
        # Same root_type (Asset) but no account_type yet -> mapping assigns
        # Receivable, so a change is proposed.
        name = _uniq("Debiteuren binnenland")
        leaf = self._make_leaf_account(name, "Asset", account_type="")
        self._persist_settings(self.company, [self.VORDERINGEN])

        result = reclassify_accounts_by_group_mappings(dry_run=True)
        self.assertTrue(result["success"])
        self.assertTrue(result["dry_run"])

        change = self._find_change(result["changes"], name)
        self.assertIsNotNone(change)
        self.assertEqual(change["status"], "would_update")
        self.assertEqual(change["group_code"], "002")
        self.assertEqual(change["new_account_type"], "Receivable")
        self.assertEqual(change["new_root_type"], "Asset")
        # dry-run must not persist the account_type change.
        self.assertFalse(frappe.db.get_value("Account", leaf.name, "account_type"))

    def test_dry_run_skips_root_type_mismatch(self):
        # "debiteuren" matches Vorderingen (Asset) but account is Expense ->
        # reclassify would change root_type -> skipped.
        name = _uniq("Debiteuren als kosten")
        self._make_leaf_account(name, "Expense")
        self._persist_settings(self.company, [self.VORDERINGEN])

        result = reclassify_accounts_by_group_mappings(dry_run=True)
        self.assertTrue(result["success"])
        change = self._find_change(result["changes"], name)
        self.assertIsNotNone(change)
        self.assertEqual(change["status"], "skipped")
        self.assertIn("Would change root_type", change["reason"])

    @staticmethod
    def _find_change(changes, account_name):
        for c in changes:
            if c.get("account_name") == account_name:
                return c
        return None
