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
    _determine_account_type_for_transaction,
    add_tax_lines,
    create_customer_from_relation,
    create_single_line_fallback,
    determine_item_group,
    generate_item_code,
    get_cost_center,
    get_default_account,
    get_or_create_item_from_description,
    get_or_create_payment_terms,
    get_tax_account,
    map_grootboek_to_erpnext_account,
    map_unit_of_measure,
    process_line_items,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _InvoiceStub:
    """Minimal stand-in for an ERPNext invoice doc: collects appended rows.

    Supports both the ``taxes`` table (add_tax_lines) and the ``items`` table
    (process_line_items / create_single_line_fallback). ``doctype`` and
    ``is_return`` mirror the real invoice attributes those functions read.
    """

    def __init__(self, company, cost_center=None, doctype="Sales Invoice", is_return=False):
        self.company = company
        self.cost_center = cost_center
        self.doctype = doctype
        self.is_return = is_return
        self.taxes = []
        self.items = []

    def append(self, table, row):
        getattr(self, table).append(frappe._dict(row))
        return getattr(self, table)[-1]


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
        # The created child term must carry the requested credit_days, not a default.
        template = frappe.get_doc("Payment Terms Template", result)
        self.assertEqual(len(template.terms), 1)
        self.assertEqual(template.terms[0].credit_days, 17)
        self.assertEqual(template.terms[0].invoice_portion, 100.0)

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
        # No duplicate template may be created on the second call.
        self.assertEqual(
            frappe.db.count("Payment Terms Template", {"name": first}),
            1,
            "Second call must reuse the existing template, not create a duplicate",
        )

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


# ---------------------------------------------------------------------------
# DB-backed account mapping / line-item construction (no live API)
# ---------------------------------------------------------------------------
class _AccountFixtureBase(EnhancedTestCase):
    """Dedicated company with real income / expense leaf accounts and a ledger
    mapping, so the account-resolution and line-building paths run end to end."""

    COMPANY = "TEST EBkh InvLines Co"
    ABBR = "TEIL"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_company()
        # A Dutch-named expense GROUP typed "Expense Account" mirrors a real NVV CoA
        # so _determine_account_type_for_transaction's purchase parent lookup
        # ("%Kosten%" + is_group + Expense Account) resolves instead of returning None.
        cls.kosten_group = cls._persist_account("Kosten Groep", "Expense Account", "Expense", is_group=1)
        cls.income_account = cls._persist_account("InvLines Income", "Income Account", "Income")
        cls.expense_account = cls._persist_account(
            "InvLines Expense", "Expense Account", "Expense", parent=cls.kosten_group
        )
        # Account whose NAME starts with the grootboek code -> direct-name match path.
        cls.coded_income = cls._persist_account("80100 - Omzet algemeen", "Income Account", "Income")

    @classmethod
    def _persist_company(cls):
        if frappe.db.exists("Company", cls.COMPANY):
            return cls.COMPANY
        doc = frappe.new_doc("Company")
        doc.company_name = cls.COMPANY
        doc.abbr = cls.ABBR
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return cls.COMPANY

    @classmethod
    def _persist_account(cls, acct_name, account_type, root_type, is_group=0, parent=None):
        full = f"{acct_name} - {cls.ABBR}"
        if frappe.db.exists("Account", full):
            return full
        if parent is None:
            parent = frappe.db.get_value(
                "Account", {"company": cls.COMPANY, "root_type": root_type, "is_group": 1}, "name"
            )
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = cls.COMPANY
        doc.parent_account = parent
        doc.account_type = account_type
        doc.root_type = root_type
        doc.is_group = is_group
        doc.insert(ignore_permissions=True)
        return doc.name

    def _persist_ledger_mapping(self, ledger_id, ledger_code, account):
        if frappe.db.exists("E-Boekhouden Ledger Mapping", str(ledger_id)):
            return str(ledger_id)
        m = frappe.new_doc("E-Boekhouden Ledger Mapping")
        m.ledger_id = str(ledger_id)
        m.ledger_code = str(ledger_code)
        m.ledger_name = f"Test ledger {ledger_code}"
        m.erpnext_account = account
        m.insert(ignore_permissions=True)
        return m.name


class TestGetCostCenter(_AccountFixtureBase):
    def test_returns_company_default_cost_center(self):
        # A freshly-created company has a default cost center configured.
        default_cc = frappe.db.get_value("Company", self.company, "cost_center")
        self.assertTrue(default_cc)
        self.assertEqual(get_cost_center("ignored-id", company=self.company), default_cc)

    def _setup_settings_default_company(self, company):
        """Point E-Boekhouden Settings.default_company at ``company`` and return the
        previous value so the caller can restore it.

        Uses non-committed ``set_single_value`` rather than ``settings.save()``:
        production reads ``default_company`` via ``frappe.get_single`` in the same
        transaction, the change rolls back at test end, and it bypasses full-document
        validation (avoiding the shard-race ``MandatoryError`` when a prior test has
        emptied the mandatory ``api_token``)."""
        prev = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")
        frappe.db.set_single_value("E-Boekhouden Settings", "default_company", company)
        return prev

    def test_resolves_company_from_settings_when_omitted(self):
        # With no company arg, get_cost_center falls back to E-Boekhouden Settings'
        # default_company (a mandatory field). Point it at our test company and
        # assert the resolved cost center belongs to it.
        prev = self._setup_settings_default_company(self.company)
        try:
            cc = get_cost_center("ignored-id")
            self.assertEqual(frappe.db.get_value("Cost Center", cc, "company"), self.company)
        finally:
            self._setup_settings_default_company(prev)

    def test_no_cost_center_for_company_raises(self):
        # A company argument that has no default cost center and no matching
        # "Main"/any Cost Center rows exhausts every lookup branch and must raise
        # the final "No cost center found" ValidationError rather than returning
        # None. An unknown company name reproduces this state offline: all three
        # frappe.db.get_value lookups return None.
        bogus_company = "ZZ Nonexistent Company For CC Test"
        self.assertFalse(frappe.db.exists("Company", bogus_company))
        with self.assertRaises(frappe.ValidationError) as ctx:
            get_cost_center("ignored-id", company=bogus_company)
        self.assertIn("No cost center found for company", str(ctx.exception))


class TestMapGrootboekSuccess(_AccountFixtureBase):
    def test_direct_account_name_match(self):
        # grootboek "80100" -> account named "80100 - Omzet algemeen - TEIL" via the
        # "<code> - % - <abbr>" wildcard pattern. No ledger mapping needed.
        debug = []
        result = map_grootboek_to_erpnext_account("80100", "sales", self.company, debug)
        self.assertEqual(result, self.coded_income)
        self.assertTrue(any("direct account match" in m for m in debug))

    def test_ledger_mapping_match(self):
        # No direct name match for this code, but a ledger mapping resolves it.
        self._persist_ledger_mapping(ledger_id="77001", ledger_code="55500", account=self.expense_account)
        debug = []
        result = map_grootboek_to_erpnext_account("77001", "purchase", self.company, debug)
        self.assertEqual(result, self.expense_account)
        self.assertTrue(any("ledger mapping" in m for m in debug))


class TestDetermineAccountType(_AccountFixtureBase):
    def test_sales_returns_income_account_and_parent(self):
        debug = []
        account_type, parent = _determine_account_type_for_transaction(
            "80100", "Omzet", "OMS", "sales", self.company, debug
        )
        self.assertEqual(account_type, "Income Account")
        self.assertTrue(parent)
        self.assertEqual(frappe.db.get_value("Account", parent, "root_type"), "Income")

    def test_purchase_returns_expense_account_and_parent(self):
        debug = []
        account_type, parent = _determine_account_type_for_transaction(
            "44000", "Kosten", "KOS", "purchase", self.company, debug
        )
        self.assertEqual(account_type, "Expense Account")
        self.assertTrue(parent)
        self.assertEqual(frappe.db.get_value("Account", parent, "root_type"), "Expense")


class TestGetTaxAccountSuccess(_AccountFixtureBase):
    def _persist_named_account(self, full_name, root_type="Liability"):
        """Materialise an Account whose full name (incl. " - <abbr>") equals
        ``full_name`` on this test company, so get_tax_account's
        frappe.db.exists("Account", <mapped name>) lookup hits it."""
        if frappe.db.exists("Account", full_name):
            return full_name
        # The mapped BTW account name is fully qualified; recreating it verbatim on
        # our own company requires the leaf name to end with our abbr.
        parent = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": root_type, "is_group": 1}, "name"
        )
        doc = frappe.new_doc("Account")
        doc.account_name = full_name.rsplit(" - ", 1)[0]
        doc.company = self.company
        doc.parent_account = parent
        doc.root_type = root_type
        doc.is_group = 0
        doc.insert(ignore_permissions=True)
        return doc.name

    def test_returns_account_when_mapped_btw_account_exists(self):
        # Use a synthetic BTW code mapped to an account name that ends with OUR abbr,
        # materialise that exact account, and assert get_tax_account returns it.
        from verenigingen.e_boekhouden.utils import invoice_helpers as ih

        mapped_name = f"EBkh BTW Test Account - {self.ABBR}"
        self._persist_named_account(mapped_name)
        self.assertTrue(frappe.db.exists("Account", mapped_name))

        code = "EBKHTEST21"
        original_map = dict(ih.BTW_CODE_MAP)
        ih.BTW_CODE_MAP[code] = {"account_name": mapped_name, "rate": 21}
        try:
            debug = []
            result = get_tax_account(code, "sales", self.company, debug)
            self.assertEqual(result, mapped_name)
            self.assertTrue(any("primary tax account" in m for m in debug))
        finally:
            ih.BTW_CODE_MAP.clear()
            ih.BTW_CODE_MAP.update(original_map)


class TestGetOrCreateItemFromDescription(_AccountFixtureBase):
    def test_creates_and_is_idempotent(self):
        desc = "EBkh InvHelper Widget Service Unique"
        frappe.db.delete("Item", {"description": desc})
        frappe.db.commit()
        debug = []
        code1 = get_or_create_item_from_description(desc, debug_info=debug)
        self.assertTrue(frappe.db.exists("Item", code1))
        # Second call must reuse the existing item (found by description).
        code2 = get_or_create_item_from_description(desc, debug_info=[])
        self.assertEqual(code1, code2)

    def test_item_group_follows_keyword(self):
        desc = "Consultancy advies EBkh unique xyz"
        frappe.db.delete("Item", {"description": desc})
        frappe.db.commit()
        code = get_or_create_item_from_description(desc, debug_info=[])
        self.assertEqual(frappe.db.get_value("Item", code, "item_group"), "Services")


class TestCreateCustomerFromRelation(_AccountFixtureBase):
    def test_creates_customer_and_sets_relation_code(self):
        relation = {"id": "EBKH-REL-9001", "name": "EBkh Relation Co BV", "email": "rel9001@example.org"}
        debug = []
        party = create_customer_from_relation(relation, debug)
        self.assertTrue(frappe.db.exists("Customer", party))
        # Re-running with the same name resolves to the same party (find branch).
        again = create_customer_from_relation(relation, [])
        self.assertEqual(party, again)


class TestProcessLineItems(_AccountFixtureBase):
    def test_appends_items_resolving_account_via_direct_name(self):
        invoice = _InvoiceStub(self.company, doctype="Sales Invoice")
        regels = [
            {"ledgerId": "80100", "amount": 100.0, "quantity": 1, "Omschrijving": "Service A", "BTWCode": ""}
        ]
        debug = []
        result = process_line_items(invoice, regels, "sales", None, debug)
        self.assertTrue(result)
        self.assertEqual(len(invoice.items), 1)
        line = invoice.items[0]
        self.assertEqual(line["income_account"], self.coded_income)
        self.assertEqual(line["rate"], 100.0)
        self.assertEqual(line["qty"], 1)

    def test_negative_amount_yields_credit_line(self):
        invoice = _InvoiceStub(self.company, doctype="Sales Invoice")
        regels = [
            {"ledgerId": "80100", "amount": -50.0, "quantity": None, "Omschrijving": "Korting", "BTWCode": ""}
        ]
        result = process_line_items(invoice, regels, "sales", None, [])
        self.assertTrue(result)
        line = invoice.items[0]
        # Negative amount -> qty = -1, rate is the absolute value.
        self.assertEqual(line["qty"], -1)
        self.assertEqual(line["rate"], 50.0)

    def test_no_regels_returns_false(self):
        invoice = _InvoiceStub(self.company)
        self.assertFalse(process_line_items(invoice, [], "sales", None, []))


class TestCreateSingleLineFallback(_AccountFixtureBase):
    def test_appends_single_fallback_line(self):
        # Map a ledger id to the coded income account so fallback resolves cleanly.
        self._persist_ledger_mapping(ledger_id="88010", ledger_code="80100", account=self.coded_income)
        invoice = _InvoiceStub(self.company, doctype="Sales Invoice")
        mutation_detail = {
            "id": "EBKH-FALLBACK-1",
            "description": "Single line fallback service",
            "amount": 75.0,
            "ledgerId": "88010",
        }
        debug = []
        create_single_line_fallback(invoice, mutation_detail, None, debug)
        self.assertEqual(len(invoice.items), 1)
        line = invoice.items[0]
        self.assertEqual(line["rate"], 75.0)
        # The fallback must resolve to the account the ledger mapping points at,
        # not merely set the key. (Catches a regression dropping the mapping.)
        self.assertEqual(line["income_account"], self.coded_income)


if __name__ == "__main__":
    unittest.main()
