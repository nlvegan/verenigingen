"""
Integration tests for the E-Boekhouden Account Mapping configuration API.

Target: verenigingen/e_boekhouden/doctype/e_boekhouden_account_mapping/api.py

Focus:
- suggest_account_type (pure: category + code-range classification)
- staged-data cache helpers (get_migration_config_status, get_staged_data_summary,
  suggest_account_mappings, preview_migration_impact) driven by a cache fixture
- add/update/remove/clear mapping CRUD against the real DocType

We stub ONLY the eBoekhouden HTTP boundary by writing realistic "staged data"
straight into frappe.cache() (the exact shape stage_eboekhouden_data produces),
so no live REST connection is needed.

Run with:
    bench --site test_site_3 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_account_mapping_api
"""

import unittest

import frappe

from verenigingen.e_boekhouden.doctype.e_boekhouden_account_mapping.api import (
    add_account_mapping,
    clear_all_mappings,
    get_migration_config_status,
    get_staged_data_summary,
    preview_migration_impact,
    remove_account_mapping,
    suggest_account_mappings,
    suggest_account_type,
    update_account_mapping,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

CACHE_KEY = "ebh_staged_data"
LAST_KEY = "ebh_last_staging_date"


def _make_staged_cache():
    """Write a realistic staged-data blob into cache (mimics stage_eboekhouden_data)."""
    staged = {
        "transactions": [
            {"description": "BTW aangifte Q1", "account": {"code": "1500", "name": "BTW"}},
            {"description": "Salaris januari", "account": {"code": "4000", "name": "Lonen"}},
            {"description": "Contributie leden", "account": {"code": "8000", "name": "Contributie"}},
            {"description": "Donatie particulier", "account": {"code": "8005", "name": "Donaties"}},
            {"description": "Bankkosten Triodos", "account": {"code": "1000", "name": "Triodos"}},
            {"description": "Kantoorartikelen", "account": {"code": "4500", "name": "Kantoor"}},
        ],
        "accounts": [
            {"code": "1000", "name": "Triodos Bank", "category": "FIN", "count": 5, "total": 100.0},
            {"code": "1500", "name": "BTW af te dragen", "category": "BTW", "count": 3, "total": 50.0},
            {"code": "8000", "name": "Contributie leden", "category": "OMS", "count": 10, "total": 500.0},
            {"code": "4500", "name": "Kantoorkosten", "category": None, "count": 2, "total": 30.0},
        ],
        "from_date": "2024-01-01",
        "to_date": "2024-03-31",
        "staging_time": "2024-04-01T00:00:00",
    }
    frappe.cache().set_value(CACHE_KEY, staged, expires_in_sec=3600)
    frappe.cache().set_value(LAST_KEY, "2024-04-01T00:00:00")
    return staged


def _clear_staged_cache():
    frappe.cache().delete_value(CACHE_KEY)
    frappe.cache().delete_value(LAST_KEY)


# ---------------------------------------------------------------------------
# suggest_account_type - pure classifier
# ---------------------------------------------------------------------------
class TestSuggestAccountType(unittest.TestCase):
    def test_category_fin_exact(self):
        self.assertEqual(suggest_account_type("1000", "Triodos", "FIN"), ("Bank", "high"))

    def test_category_deb(self):
        self.assertEqual(suggest_account_type("1300", "Debiteuren", "DEB"), ("Receivable", "high"))

    def test_category_lowercase_normalized(self):
        self.assertEqual(suggest_account_type("8000", "Omzet", "oms"), ("Income Account", "high"))

    def test_category_prefix_match_medium(self):
        # "FINX" not exact but startswith "FIN" -> medium confidence
        acc_type, conf = suggest_account_type("1000", "Bank", "FINX")
        self.assertEqual(acc_type, "Bank")
        self.assertEqual(conf, "medium")

    def test_code_range_zero_fixed_asset(self):
        self.assertEqual(suggest_account_type("0100", "Inventaris"), ("Fixed Asset", "medium"))

    def test_code_range_10_bank(self):
        self.assertEqual(suggest_account_type("1050", "Kas"), ("Bank", "medium"))

    def test_code_range_13_receivable(self):
        self.assertEqual(suggest_account_type("1300", "Debiteuren"), ("Receivable", "medium"))

    def test_code_range_1_other_current_asset(self):
        self.assertEqual(suggest_account_type("1450", "Vooruit"), ("Current Asset", "low"))

    def test_code_range_4_btw_is_tax(self):
        self.assertEqual(suggest_account_type("4999", "BTW hoog"), ("Tax", "medium"))

    def test_code_range_4_income(self):
        self.assertEqual(suggest_account_type("4100", "Verkopen"), ("Income Account", "low"))

    def test_code_range_5_expense(self):
        self.assertEqual(suggest_account_type("5000", "Kosten"), ("Expense Account", "low"))

    def test_code_range_8_income(self):
        self.assertEqual(suggest_account_type("8000", "Contributie"), ("Income Account", "low"))

    def test_code_range_3_equity(self):
        self.assertEqual(suggest_account_type("3000", "Eigen vermogen"), ("Equity", "medium"))

    def test_unknown_code_none(self):
        self.assertEqual(suggest_account_type("X999", "Mystery"), (None, "low"))

    def test_category_takes_priority_over_code(self):
        # code 5xxx would be Expense, but FIN category wins
        self.assertEqual(suggest_account_type("5000", "Iets", "FIN"), ("Bank", "high"))


# ---------------------------------------------------------------------------
# Cache-driven reporting endpoints (HTTP boundary stubbed via cache)
# ---------------------------------------------------------------------------
class TestStagedDataEndpoints(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        _make_staged_cache()

    def tearDown(self):
        _clear_staged_cache()
        super().tearDown()

    def test_config_status_returns_staged_data_and_mappings(self):
        # Regression for the missing-column bug: get_migration_config_status()
        # used to SELECT `category`/`confidence` (not real columns) and crash
        # with MySQL 1054 on every call. It must now return the staged-data
        # summary plus the real mappings list. api.py:31-42.
        result = get_migration_config_status()
        self.assertTrue(result["staged_data_exists"])
        self.assertEqual(result["staged_count"], 6)
        self.assertIsInstance(result["mappings"], list)
        self.assertEqual(result["mappings_count"], len(result["mappings"]))

    def test_staged_data_summary_categorizes_transactions(self):
        summary = get_staged_data_summary()
        types = summary["transaction_types"]
        self.assertEqual(types.get("Tax/VAT"), 1)
        self.assertEqual(types.get("Wages/Salary"), 1)
        self.assertEqual(types.get("Contribution"), 1)
        self.assertEqual(types.get("Donation"), 1)
        self.assertEqual(types.get("Banking"), 1)
        self.assertEqual(types.get("Other"), 1)
        self.assertEqual(summary["total_transactions"], 6)

    def test_staged_data_summary_adds_suggested_type(self):
        summary = get_staged_data_summary()
        by_code = {a["code"]: a for a in summary["accounts"]}
        # MINOR BUG / inconsistency: get_staged_data_summary calls
        # suggest_account_type(code, name) WITHOUT passing the available
        # `category`, so the high-confidence category path is skipped and the
        # code-range fallback gives ("Bank", "medium") instead of ("Bank", "high").
        # suggest_account_mappings() (tested below) DOES pass category. api.py:186.
        self.assertEqual(by_code["1000"]["suggested_type"], ("Bank", "medium"))

    def test_suggest_account_mappings_uses_category(self):
        result = suggest_account_mappings()
        self.assertTrue(result["success"])
        suggestions = {s["account_code"]: s for s in result["suggestions"]}
        self.assertEqual(suggestions["1000"]["suggested_type"], "Bank")
        self.assertEqual(suggestions["1000"]["confidence"], "high")
        # sorted by transaction_count desc: 8000 (count 10) should appear before 4500 (count 2)
        codes_in_order = [s["account_code"] for s in result["suggestions"]]
        self.assertLess(codes_in_order.index("8000"), codes_in_order.index("4500"))

    def test_preview_migration_impact_counts_unmapped_as_journal_entries(self):
        # Regression for the missing-column bug: preview_migration_impact() used
        # to SELECT `category` (not a real column) and read
        # mapping.get("target_document_type") (also not real), crashing with 1054.
        # With all mappings cleared, every staged transaction is unmapped and must
        # be counted as a journal entry, none as purchase invoices. api.py:275-291.
        clear_all_mappings()
        result = preview_migration_impact()
        self.assertEqual(result["total_transactions"], 6)
        self.assertEqual(result["purchase_invoices"], 0)
        self.assertEqual(result["journal_entries"], result["total_transactions"])

    def test_summary_without_staged_throws(self):
        _clear_staged_cache()
        with self.assertRaises(frappe.ValidationError):
            get_staged_data_summary()


# ---------------------------------------------------------------------------
# Mapping CRUD against the real DocType
# ---------------------------------------------------------------------------
class TestMappingCrud(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # Remove any mapping for our test code to keep tests independent
        for code in ("99001", "99002"):
            existing = frappe.db.exists("E-Boekhouden Account Mapping", {"account_code": code})
            if existing:
                frappe.delete_doc("E-Boekhouden Account Mapping", existing, force=True)

    def test_add_new_mapping(self):
        result = add_account_mapping("99001", "Purchase Invoice", notes="manual test")
        self.assertTrue(result["success"])
        self.assertEqual(result["mapping"]["account_code"], "99001")
        self.assertEqual(result["mapping"]["account_type"], "Purchase Invoice")
        self.assertEqual(result["mapping"]["notes"], "manual test")
        # priority defaulted to 100 for manual
        doc = frappe.get_doc("E-Boekhouden Account Mapping", result["mapping"]["id"])
        self.assertEqual(doc.priority, 100)

    def test_add_existing_updates(self):
        first = add_account_mapping("99002", "Journal Entry")
        first_id = first["mapping"]["id"]
        second = add_account_mapping("99002", "Sales Invoice", notes="updated")
        # Same record updated, not a new one
        self.assertEqual(second["mapping"]["id"], first_id)
        self.assertEqual(second["mapping"]["account_type"], "Sales Invoice")
        self.assertEqual(second["mapping"]["notes"], "updated")

    def test_update_account_mapping(self):
        created = add_account_mapping("99001", "Purchase Invoice")
        mapping_id = created["mapping"]["id"]
        result = update_account_mapping(mapping_id, "Journal Entry", notes="changed")
        self.assertTrue(result["success"])
        self.assertEqual(result["mapping"]["account_type"], "Journal Entry")
        self.assertEqual(result["mapping"]["notes"], "changed")

    def test_remove_account_mapping(self):
        created = add_account_mapping("99001", "Purchase Invoice")
        mapping_id = created["mapping"]["id"]
        result = remove_account_mapping(mapping_id)
        self.assertTrue(result["success"])
        self.assertFalse(frappe.db.exists("E-Boekhouden Account Mapping", mapping_id))

    def test_clear_all_mappings(self):
        add_account_mapping("99001", "Purchase Invoice")
        add_account_mapping("99002", "Journal Entry")
        result = clear_all_mappings()
        self.assertTrue(result["success"])
        self.assertEqual(frappe.db.count("E-Boekhouden Account Mapping"), 0)


if __name__ == "__main__":
    unittest.main()
