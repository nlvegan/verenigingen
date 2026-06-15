"""
Unit / integration tests for
verenigingen/e_boekhouden/utils/eboekhouden_improved_item_naming.py

Covers the pure helpers (map_unit_of_measure, determine_smart_item_group,
clean_item_name, _is_event_ticket_row, _is_bank_cost_transaction) and the
DB-backed master-data helpers (_ensure_item_group_exists, get_or_create_*_item)
that do NOT require a live eBoekhouden HTTP connection.

Run with:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_item_naming
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_improved_item_naming import (
    _ensure_item_group_exists,
    _is_bank_cost_transaction,
    _is_event_ticket_row,
    clean_item_name,
    determine_smart_item_group,
    get_or_create_bank_cost_item,
    get_or_create_event_ticket_item,
    get_or_create_generic_item,
    map_unit_of_measure,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# ---------------------------------------------------------------------------
# Pure helpers (no DB)
# ---------------------------------------------------------------------------
class TestMapUnitOfMeasure(unittest.TestCase):
    def test_dutch_mappings(self):
        self.assertEqual(map_unit_of_measure("Uur"), "Hour")
        self.assertEqual(map_unit_of_measure("Dag"), "Day")
        self.assertEqual(map_unit_of_measure("Maand"), "Month")
        self.assertEqual(map_unit_of_measure("Jaar"), "Year")
        self.assertEqual(map_unit_of_measure("Stuks"), "Unit")

    def test_passthrough_known(self):
        self.assertEqual(map_unit_of_measure("Kg"), "Kg")
        self.assertEqual(map_unit_of_measure("Liter"), "Litre")
        self.assertEqual(map_unit_of_measure("Meter"), "Meter")

    def test_unknown_defaults_to_unit(self):
        self.assertEqual(map_unit_of_measure("blah"), "Unit")
        self.assertEqual(map_unit_of_measure(None), "Unit")


class TestDetermineSmartItemGroup(unittest.TestCase):
    def test_keyword_travel(self):
        self.assertEqual(determine_smart_item_group("Treinreis naar Utrecht"), "Expense Items")

    def test_keyword_office(self):
        self.assertEqual(determine_smart_item_group("Kantoor supplies"), "Consumable")

    def test_keyword_finance(self):
        self.assertEqual(determine_smart_item_group("Bank transaction fee"), "Services")

    def test_keyword_catering(self):
        self.assertEqual(determine_smart_item_group("Lunch catering"), "Services")

    def test_no_signal_defaults_services(self):
        self.assertEqual(determine_smart_item_group("Generic widget"), "Services")

    def test_account_info_income(self):
        acct = frappe._dict({"root_type": "Income"})
        self.assertEqual(determine_smart_item_group("nondescript", account_info=acct), "Services")

    def test_account_info_expense(self):
        acct = frappe._dict({"root_type": "Expense"})
        self.assertEqual(determine_smart_item_group("nondescript", account_info=acct), "Expense Items")

    def test_account_info_asset(self):
        acct = frappe._dict({"root_type": "Asset"})
        self.assertEqual(determine_smart_item_group("nondescript", account_info=acct), "Products")

    def test_price_small_consumable(self):
        self.assertEqual(determine_smart_item_group("nondescript", price=20), "Consumable")

    def test_price_large_products(self):
        self.assertEqual(determine_smart_item_group("nondescript", price=900), "Products")

    def test_keyword_beats_account_info(self):
        # Description keyword (Priority 1) wins over account_info (Priority 2)
        acct = frappe._dict({"root_type": "Expense"})
        self.assertEqual(determine_smart_item_group("hotel travel", account_info=acct), "Expense Items")

    def test_empty_description_uses_price(self):
        self.assertEqual(determine_smart_item_group("", price=10), "Consumable")


class TestCleanItemName(unittest.TestCase):
    def test_strip_account_number_prefix(self):
        self.assertEqual(clean_item_name("8000 - Sales Revenue"), "Sales Revenue")

    def test_strip_company_abbr_suffix(self):
        self.assertEqual(clean_item_name("Sales Revenue - NVV"), "Sales Revenue")

    def test_strip_ebh_prefix(self):
        self.assertEqual(clean_item_name("EBH-Hosting"), "Hosting")

    def test_colon_extracts_description_part(self):
        result = clean_item_name("Virtual Server: Production hosting plan")
        self.assertIn("Production hosting plan", result)

    def test_removes_id_patterns(self):
        result = clean_item_name("Server: Virtual Server ID: 12381564, hosting")
        self.assertNotIn("12381564", result)

    def test_length_capped(self):
        long_name = "A" * 200
        self.assertLessEqual(len(clean_item_name(long_name)), 100)

    def test_simple_name_unchanged(self):
        self.assertEqual(clean_item_name("Consulting"), "Consulting")


class TestIsEventTicketRow(unittest.TestCase):
    def test_none_description_false(self):
        self.assertFalse(_is_event_ticket_row(None, "8000", 100))

    def test_non_woocommerce_false(self):
        self.assertFalse(_is_event_ticket_row("Regular sale", "8000", 100))

    def test_woocommerce_high_price_true(self):
        self.assertTrue(_is_event_ticket_row("WooCommerce order #123", "8000", 50))

    def test_woocommerce_low_price_true(self):
        # Even small WooCommerce amounts count
        self.assertTrue(_is_event_ticket_row("WooCommerce ticket", "8000", 0.5))

    def test_woocommerce_no_price_true(self):
        self.assertTrue(_is_event_ticket_row("WooCommerce ticket", "8000", None))

    def test_bank_cost_woocommerce_excluded(self):
        # If the description matches bank cost patterns, it is NOT an event ticket
        self.assertFalse(_is_event_ticket_row("WooCommerce bankkosten", "8000", 100))


class TestIsBankCostTransactionByDescription(unittest.TestCase):
    """Description-based detection needs no DB."""

    def test_bankkosten(self):
        self.assertTrue(_is_bank_cost_transaction("Maandelijkse bankkosten", None))

    def test_bank_charges(self):
        self.assertTrue(_is_bank_cost_transaction("Bank charges Q1", None))

    def test_transaction_fee(self):
        self.assertTrue(_is_bank_cost_transaction("transaction fee Mollie", None))

    def test_normal_description_false(self):
        self.assertFalse(_is_bank_cost_transaction("Consulting services", None))

    def test_both_none_false(self):
        self.assertFalse(_is_bank_cost_transaction(None, None))


# ---------------------------------------------------------------------------
# DB-backed master-data helpers
# ---------------------------------------------------------------------------
class TestItemGroupAndItemCreation(EnhancedTestCase):
    """Exercises master-data creation helpers against the real DB."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST EBkh ItemNaming Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TEIN"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def test_ensure_item_group_existing(self):
        # "Services" should already exist in a standard ERPNext install
        self.assertEqual(_ensure_item_group_exists("Services"), "Services")

    def test_ensure_item_group_empty_falls_back(self):
        self.assertEqual(_ensure_item_group_exists(""), "Services")
        self.assertEqual(_ensure_item_group_exists(None), "Services")

    def test_ensure_item_group_creates_new(self):
        group_name = "EBkh Test Group ItemNaming"
        frappe.db.delete("Item Group", {"item_group_name": group_name})
        result = _ensure_item_group_exists(group_name)
        self.assertEqual(result, group_name)
        self.assertTrue(frappe.db.exists("Item Group", group_name))

    def test_get_or_create_generic_item(self):
        result = get_or_create_generic_item(self.company)
        self.assertEqual(result, "General Service")
        self.assertTrue(frappe.db.exists("Item", "General Service"))

    def test_get_or_create_generic_item_idempotent(self):
        first = get_or_create_generic_item(self.company)
        second = get_or_create_generic_item(self.company)
        self.assertEqual(first, second)

    def test_get_or_create_bank_cost_item(self):
        result = get_or_create_bank_cost_item(self.company)
        # Either the standardized Bank-Costs item or a generic fallback
        self.assertTrue(frappe.db.exists("Item", result))

    def test_get_or_create_bank_cost_item_idempotent(self):
        first = get_or_create_bank_cost_item(self.company)
        second = get_or_create_bank_cost_item(self.company)
        self.assertEqual(first, second)

    def test_get_or_create_event_ticket_item(self):
        result = get_or_create_event_ticket_item(self.company)
        self.assertTrue(frappe.db.exists("Item", result))

    def test_get_or_create_event_ticket_item_idempotent(self):
        first = get_or_create_event_ticket_item(self.company)
        second = get_or_create_event_ticket_item(self.company)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
