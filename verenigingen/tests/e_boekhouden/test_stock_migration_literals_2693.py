"""#2693: document literals in StockTransactionMigrator lacked the f prefix, so every
account shared one Item named literally ``MIGR-{account_code}`` and every Stock Entry
carried literal braces in its remarks."""

from unittest.mock import patch

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.migration.stock_migration import StockTransactionMigrator

MOD = "verenigingen.utils.migration.stock_migration"


class TestStockMigrationDocumentLiterals(EnhancedTestCase):
    def _item_doc_for(self, account_code, account_name):
        migrator = StockTransactionMigrator(frappe._dict())
        captured = {}

        def capture(doc_dict):
            captured.update(doc_dict)
            return frappe._dict(insert=lambda **kw: None, item_code=doc_dict["item_code"])

        with (
            # Mock justified: forces the "item absent" branch so the literal handed to the Item doc is observed.
            patch(f"{MOD}.frappe.db.exists", return_value=False),
            patch.object(migrator, "get_or_create_migration_item_group", return_value="IG"),
            # Mock justified: captures the Item dict without inserting a real Item on the shared site.
            patch(f"{MOD}.frappe.get_doc", side_effect=capture),
        ):
            returned = migrator.get_or_create_migration_item(account_code, account_name)
        return returned, captured

    def test_item_is_per_account_with_real_values(self):
        returned, doc = self._item_doc_for("13000", "Voorraad Noord")
        self.assertEqual(returned, "MIGR-13000")
        self.assertEqual(doc["item_code"], "MIGR-13000")
        self.assertEqual(doc["item_name"], "Migration Item - Voorraad Noord")
        self.assertIn("account 13000 - Voorraad Noord", doc["description"])

    def test_two_accounts_get_two_items(self):
        first, _ = self._item_doc_for("13000", "A")
        second, _ = self._item_doc_for("14000", "B")
        self.assertNotEqual(first, second)

    def test_existing_item_is_reused_only_for_the_same_account(self):
        """The exists() shortcut must look up the per-account code, not one shared literal."""
        migrator = StockTransactionMigrator(frappe._dict())
        existing = {"MIGR-13000"}
        # Mock justified: stands in for the Item table so "exists for 13000 only" is exact.
        with patch(f"{MOD}.frappe.db.exists", side_effect=lambda dt, name: name in existing):
            self.assertEqual(migrator.get_or_create_migration_item("13000", "A"), "MIGR-13000")
            fake_get_doc = lambda d: frappe._dict(insert=lambda **kw: None, item_code=d["item_code"])  # noqa: E731
            # Mock justified: the absent-item branch would otherwise insert a real Item on the shared site.
            with patch.object(migrator, "get_or_create_migration_item_group", return_value="IG"), patch(
                f"{MOD}.frappe.get_doc", side_effect=fake_get_doc
            ):
                self.assertEqual(migrator.get_or_create_migration_item("14000", "B"), "MIGR-14000")

    def test_stock_entry_remarks_carry_real_values(self):
        migrator = StockTransactionMigrator(frappe._dict())
        settings = frappe._dict(default_company="Stub Co", default_cost_center="Stub CC")
        seen = {}

        def capture_insert(doc, *args, **kwargs):
            seen["remarks"] = doc.remarks
            raise frappe.ValidationError("stop here")

        with (
            patch(f"{MOD}.frappe.get_single", return_value=settings),
            patch.object(StockEntry, "insert", autospec=True, side_effect=capture_insert),
            patch.object(migrator, "get_or_create_migration_warehouse", return_value="WH"),
            patch.object(migrator, "get_or_create_migration_item", return_value="MIGR-13000"),
            patch("frappe.log_error"),
        ):
            migrator.create_stock_entry(
                "2026-01-01", "Material Receipt", "13000", "Voorraad Noord", 1, 12.5, "L77", {}
            )
        self.assertEqual(
            seen["remarks"], "Migrated from e-Boekhouden: Ledger L77 | Account: 13000 - Voorraad Noord"
        )
