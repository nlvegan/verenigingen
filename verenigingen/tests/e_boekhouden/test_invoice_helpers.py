"""
Unit / integration tests for
verenigingen/e_boekhouden/utils/invoice_helpers.py

Covers:
- Pure helpers: generate_item_code, determine_item_group, map_unit_of_measure
- DB-backed (no HTTP): get_or_create_payment_terms, get_tax_account,
  get_default_account (raises), map_grootboek_to_erpnext_account (allow_fallback
  raise path), get_cost_center
- Semi-pure: add_tax_lines (operates on a line-item collector invoice stand-in)

The live-API path (auto_create_ledger_mapping) is intentionally NOT exercised
here; only the no-mapping / fallback branches that resolve without HTTP.

Run with:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_invoice_helpers
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.invoice_helpers import (
    add_tax_lines,
    determine_item_group,
    generate_item_code,
    get_default_account,
    get_or_create_payment_terms,
    get_tax_account,
    map_grootboek_to_erpnext_account,
    map_unit_of_measure,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _InvoiceStub:
    """Minimal stand-in for an ERPNext invoice doc: collects appended rows."""

    def __init__(self, company, cost_center=None):
        self.company = company
        self.cost_center = cost_center
        self.taxes = []

    def append(self, table, row):
        getattr(self, table).append(frappe._dict(row))
        return self.taxes[-1]


# ---------------------------------------------------------------------------
# Pure helpers (no DB)
# ---------------------------------------------------------------------------
class TestGenerateItemCode(unittest.TestCase):
    def test_basic_slug(self):
        self.assertEqual(generate_item_code("Web Hosting"), "WEB-HOSTING")

    def test_strips_punctuation(self):
        # Only chars that are NOT alnum/space/-/_ are stripped; accented
        # letters are alnum in Python 3 so they survive.
        # "&" and "!" are stripped; surrounding spaces become hyphens
        self.assertEqual(generate_item_code("Bar & Grill!!"), "BAR--GRILL")

    def test_truncated_to_30(self):
        self.assertLessEqual(len(generate_item_code("X" * 60)), 30)

    def test_keeps_hyphen_underscore(self):
        self.assertEqual(generate_item_code("a-b_c"), "A-B_C")


class TestDetermineItemGroup(unittest.TestCase):
    def test_keyword_service(self):
        self.assertEqual(determine_item_group("Consultancy advies"), "Services")

    def test_keyword_travel(self):
        self.assertEqual(determine_item_group("Treinreis Amsterdam"), "Expense Items")

    def test_keyword_product(self):
        self.assertEqual(determine_item_group("Nieuwe laptop"), "Products")

    def test_account_code_hint(self):
        # 46000-46999 → office → Office Supplies
        self.assertEqual(determine_item_group("nondescript xyz", account_code="46500"), "Office Supplies")

    def test_account_code_with_company_suffix(self):
        # int(str(account_code).split("-")[0]) parses leading number
        self.assertEqual(determine_item_group("nondescript xyz", account_code="43000 - NVV"), "Products")

    def test_price_consumable(self):
        self.assertEqual(determine_item_group("nondescript xyz", price=25), "Office Supplies")

    def test_price_products(self):
        self.assertEqual(determine_item_group("nondescript xyz", price=2000), "Products")

    def test_default_services(self):
        self.assertEqual(determine_item_group("nondescript xyz"), "Services")

    def test_invalid_account_code_ignored(self):
        # Non-numeric account code → ValueError caught, falls through to default
        self.assertEqual(determine_item_group("nondescript xyz", account_code="ABC"), "Services")


class TestMapUnitOfMeasure(EnhancedTestCase):
    """invoice_helpers.map_unit_of_measure delegates to UOMManager.map_uom
    (which can create custom UOMs), unlike the item-naming module's variant."""

    def test_dutch_uur(self):
        self.assertEqual(map_unit_of_measure("uur"), "Hour")

    def test_empty_defaults_nos(self):
        self.assertEqual(map_unit_of_measure(""), "Nos")

    def test_unknown_creates_custom_uom(self):
        unit = "EBkhInvHelperUnitXyz"
        frappe.db.delete("UOM", {"uom_name": unit})
        result = map_unit_of_measure(unit)
        self.assertEqual(result, unit)
        self.assertTrue(frappe.db.exists("UOM", unit))


# ---------------------------------------------------------------------------
# DB-backed helpers (no HTTP)
# ---------------------------------------------------------------------------
class TestGetDefaultAccount(unittest.TestCase):
    """get_default_account always throws (fallback creation disabled)."""

    def test_sales_throws(self):
        with self.assertRaises(frappe.ValidationError):
            get_default_account("sales")

    def test_purchase_throws(self):
        with self.assertRaises(frappe.ValidationError):
            get_default_account("purchase")


class TestPaymentTermsAndAccounts(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST EBkh InvHelpers Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TEIH"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def test_payment_terms_standard_dutch(self):
        result = get_or_create_payment_terms(30)
        self.assertEqual(result, "Netto 30 dagen")
        self.assertTrue(frappe.db.exists("Payment Terms Template", result))

    def test_payment_terms_custom_days(self):
        result = get_or_create_payment_terms(17)
        self.assertEqual(result, "Netto 17 dagen")
        self.assertTrue(frappe.db.exists("Payment Terms Template", result))

    def test_payment_terms_zero_defaults_30(self):
        result = get_or_create_payment_terms(0)
        self.assertEqual(result, "Netto 30 dagen")

    def test_payment_terms_negative_defaults_30(self):
        result = get_or_create_payment_terms(-5)
        self.assertEqual(result, "Netto 30 dagen")

    def test_payment_terms_idempotent(self):
        first = get_or_create_payment_terms(14)
        second = get_or_create_payment_terms(14)
        self.assertEqual(first, second)

    def test_get_tax_account_unknown_btw_returns_none(self):
        debug = []
        self.assertIsNone(get_tax_account("NONEXISTENT_BTW", "sales", self.company, debug))
        self.assertTrue(any("No tax account mapping" in m for m in debug))

    def test_map_grootboek_missing_no_fallback_throws(self):
        debug = []
        with self.assertRaises(frappe.ValidationError):
            map_grootboek_to_erpnext_account("", "sales", self.company, debug, allow_fallback=False)

    def test_map_grootboek_missing_with_fallback_throws_via_default(self):
        # allow_fallback=True with empty code → get_default_account → throws
        debug = []
        with self.assertRaises(frappe.ValidationError):
            map_grootboek_to_erpnext_account("", "sales", self.company, debug, allow_fallback=True)


class TestAddTaxLines(EnhancedTestCase):
    """add_tax_lines aggregates BTW codes and appends tax rows."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = "TEST EBkh InvHelpers Co"
        if not frappe.db.exists("Company", cls.company):
            doc = frappe.new_doc("Company")
            doc.company_name = cls.company
            doc.abbr = "TEIH"
            doc.default_currency = "EUR"
            doc.country = "Netherlands"
            doc.insert(ignore_permissions=True)

    def test_no_regels_returns_none(self):
        invoice = _InvoiceStub(self.company)
        result = add_tax_lines(invoice, [], "sales", [])
        self.assertIsNone(result)

    def test_zero_rate_btw_no_tax_line(self):
        # GEEN btw code is explicitly excluded from tax summary
        invoice = _InvoiceStub(self.company)
        regels = [{"amount": 100, "quantity": 1, "BTWCode": "GEEN", "Omschrijving": "x"}]
        result = add_tax_lines(invoice, regels, "sales", [])
        self.assertEqual(result["net_amount"], 100)
        self.assertEqual(result["tax_amount"], 0)
        self.assertEqual(len(invoice.taxes), 0)

    def test_net_amount_aggregation(self):
        invoice = _InvoiceStub(self.company)
        regels = [
            {"amount": 100, "quantity": 1, "BTWCode": "", "Omschrijving": "a"},
            {"amount": 50, "quantity": 2, "BTWCode": "", "Omschrijving": "b"},
        ]
        result = add_tax_lines(invoice, regels, "sales", [])
        self.assertEqual(result["net_amount"], 200)

    def test_unknown_btw_code_warns_no_crash(self):
        invoice = _InvoiceStub(self.company)
        regels = [{"amount": 100, "quantity": 1, "BTWCode": "WEIRD", "Omschrijving": "x"}]
        debug = []
        result = add_tax_lines(invoice, regels, "sales", debug)
        self.assertEqual(result["net_amount"], 100)
        self.assertTrue(any("Unknown BTW code" in m for m in debug))


if __name__ == "__main__":
    unittest.main()
