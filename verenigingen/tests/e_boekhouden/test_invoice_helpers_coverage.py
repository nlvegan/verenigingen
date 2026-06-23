"""
Gap-filling coverage tests for
verenigingen/e_boekhouden/utils/invoice_helpers.py

Companion to test_invoice_helpers.py: that module already covers the pure
helpers, the raise paths, and the happy direct-name / ledger-mapping account
resolution. THIS module targets the BRANCHES the existing test leaves cold:

- determine_item_group: the VAT-hint (Priority 2) branch + price>equipment branch.
- get_or_create_item_from_description: the item_code-already-exists short-circuit,
  the stock-item configuration branch (Products/Office Supplies), and the
  suggested-UOM-from-category branch.
- get_or_create_payment_terms: the Dutch-description override branch (7/14/21/45/60).
- add_tax_lines: the real tax-line append path (rate>0, taxable>0, account found)
  incl. the cost-center attachment, plus the "no tax account found" warning branch.
- get_tax_account: the account_fallback branch and the final-fallback branch.
- process_line_items: the is_return credit-note branch, the missing-account
  frappe.throw branch, and the per-line KostenplaatsId cost-center branch.

OUT OF SCOPE (live eBoekhouden HTTP — enforcer bans mocking that seam):
  auto_create_ledger_mapping, fetch_relation_details.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_invoice_helpers_coverage
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils import invoice_helpers as ih
from verenigingen.e_boekhouden.utils.invoice_helpers import (
    add_tax_lines,
    determine_item_group,
    get_or_create_item_from_description,
    get_or_create_payment_terms,
    get_tax_account,
    process_line_items,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


class _InvoiceStub:
    """Minimal stand-in for an ERPNext invoice doc: collects appended rows.

    Mirrors the collector used by the sibling test_invoice_helpers.py so the
    table-appending functions (process_line_items / add_tax_lines) run unchanged.
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
# determine_item_group: branches the sibling test does not reach
# ---------------------------------------------------------------------------
class TestDetermineItemGroupGaps(unittest.TestCase):
    """The sibling covers keyword / account-code / price-consumable / default.
    Here we hit the BTW (Priority 2) branch and the price>equipment branch."""

    def test_vat_hint_branch_maps_to_products(self):
        # No keyword match -> Priority 2: btw_code in VAT_CATEGORY_HINTS.
        # HOOG_VERK_21 -> "product" -> DEFAULT_ITEM_GROUPS["product"] == "Products".
        self.assertEqual(
            determine_item_group("nondescript xyz", btw_code="HOOG_VERK_21"), "Products"
        )

    def test_vat_hint_service_branch(self):
        # GEEN -> "service" -> "Services". Distinct from the default-Services path
        # because it must short-circuit BEFORE the price/account fall-through.
        self.assertEqual(determine_item_group("nondescript xyz", btw_code="GEEN"), "Services")

    def test_vat_hint_utility_branch(self):
        # LAAG_VERK_6 -> "utility" -> "Services".
        self.assertEqual(determine_item_group("nondescript xyz", btw_code="LAAG_VERK_6"), "Services")

    def test_unknown_btw_code_falls_through_to_price(self):
        # A btw_code NOT in VAT_CATEGORY_HINTS must skip Priority 2 and reach the
        # price branch; price 2000 (> equipment upper bound) -> "Products".
        self.assertEqual(
            determine_item_group("nondescript xyz", btw_code="UNMAPPED", price=2000), "Products"
        )

    def test_price_above_equipment_lower_bound_products(self):
        # Distinct from the sibling's price=25 (consumable) test: price 500 is
        # > equipment[0]==50, so the elif price>equipment[0] branch -> "Products".
        self.assertEqual(determine_item_group("nondescript xyz", price=500), "Products")


# ---------------------------------------------------------------------------
# get_or_create_payment_terms: the Dutch-description override branch
# ---------------------------------------------------------------------------
class TestPaymentTermsDescriptionBranch(EnhancedTestCase):
    def _reset_template(self, name):
        # Payment Terms Template Detail is the child table; deleting the parent
        # template cascades, but purge explicitly to be safe across reruns.
        frappe.db.delete("Payment Terms Template Detail", {"parent": name})
        frappe.db.delete("Payment Terms Template", name)
        frappe.db.commit()

    def test_known_days_set_dutch_description(self):
        # days=14 is in BOTH DEFAULT_PAYMENT_TERMS and the descriptions dict, so
        # the created term's description must be the Dutch phrase, not the generic
        # "Full payment due ..." string. Exercises the `if days in descriptions`
        # branch that the sibling's custom-days(17) test skips.
        name = "Netto 14 dagen"
        self._reset_template(name)

        with self.assertNoErrorLog():
            result = get_or_create_payment_terms(14)
        self.assertEqual(result, name)
        template = frappe.get_doc("Payment Terms Template", result)
        self.assertEqual(template.terms[0].credit_days, 14)
        self.assertEqual(template.terms[0].description, "Betaling binnen 14 dagen")

    def test_custom_days_keep_generic_description(self):
        # days=23 is NOT in the descriptions dict -> the generic description
        # survives (the `if days in descriptions` branch is NOT taken).
        name = "Netto 23 dagen"
        self._reset_template(name)

        with self.assertNoErrorLog():
            result = get_or_create_payment_terms(23)
        self.assertEqual(result, name)
        template = frappe.get_doc("Payment Terms Template", result)
        self.assertEqual(
            template.terms[0].description, "Full payment due 23 days after invoice date"
        )


# ---------------------------------------------------------------------------
# Shared account/company fixture for the tax + line-item branch tests
# ---------------------------------------------------------------------------
class _TaxFixtureBase(EnhancedTestCase):
    """Dedicated company plus real income/expense leaf accounts and a BTW
    liability account so the tax-line append and account-resolution branches run
    end to end without touching the live API."""

    COMPANY = "TEST EBkh InvCov Co"
    ABBR = "TEIC"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_company()
        cls.income_account = cls._persist_account("InvCov Income", "Income Account", "Income")
        cls.expense_account = cls._persist_account("InvCov Expense", "Expense Account", "Expense")
        # Account whose NAME starts with the grootboek code -> direct-name match path.
        cls.coded_income = cls._persist_account("80100 - InvCov Omzet", "Income Account", "Income")
        # A BTW liability leaf account on THIS company, used as a tax-line head.
        cls.btw_account = cls._persist_account(
            "InvCov BTW af te dragen", "Tax", "Liability"
        )

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


# ---------------------------------------------------------------------------
# add_tax_lines: the real tax-line append path + warning branch
# ---------------------------------------------------------------------------
class TestAddTaxLinesAppend(_TaxFixtureBase):
    def _patch_btw(self, code, account_name):
        """Point a synthetic 21% BTW code at ``account_name`` for one test."""
        original = dict(ih.BTW_CODE_MAP)
        ih.BTW_CODE_MAP[code] = {
            "rate": 21,
            "type": "Output VAT",
            "account_name": account_name,
            "account_fallback": None,
            "description": "InvCov Test BTW 21%",
        }
        self.addCleanup(lambda: (ih.BTW_CODE_MAP.clear(), ih.BTW_CODE_MAP.update(original)))

    def test_tax_line_appended_with_correct_amount(self):
        # rate>0 and taxable>0 and tax_account found -> a tax row is appended.
        code = "INVCOV21"
        self._patch_btw(code, self.btw_account)
        invoice = _InvoiceStub(self.company)
        regels = [{"amount": 100, "quantity": 1, "BTWCode": code, "Omschrijving": "x"}]

        with self.assertNoErrorLog():
            result = add_tax_lines(invoice, regels, "sales", [])

        self.assertEqual(result["net_amount"], 100)
        self.assertEqual(result["tax_amount"], 21.0)
        self.assertEqual(len(invoice.taxes), 1)
        tax = invoice.taxes[0]
        self.assertEqual(tax["account_head"], self.btw_account)
        self.assertEqual(tax["tax_amount"], 21.0)
        self.assertEqual(tax["charge_type"], "Actual")
        self.assertIn("21%", tax["description"])
        # No cost_center on this invoice stub -> the cost_center key is omitted.
        self.assertNotIn("cost_center", tax)

    def test_tax_line_carries_invoice_cost_center(self):
        # When invoice.cost_center is set, the tax row must inherit it.
        code = "INVCOVCC21"
        self._patch_btw(code, self.btw_account)
        default_cc = frappe.db.get_value("Company", self.company, "cost_center")
        self.assertTrue(default_cc)
        invoice = _InvoiceStub(self.company, cost_center=default_cc)
        regels = [{"amount": 200, "quantity": 1, "BTWCode": code, "Omschrijving": "y"}]

        with self.assertNoErrorLog():
            result = add_tax_lines(invoice, regels, "sales", [])

        self.assertEqual(result["tax_amount"], 42.0)
        self.assertEqual(invoice.taxes[0]["cost_center"], default_cc)

    def test_taxable_btw_resolves_via_final_fallback(self):
        # Primary account_name points nowhere, so get_tax_account falls through to
        # its hardcoded final fallback for "sales" ("1500 - BTW af te dragen 21% -
        # NVV"). The tax amount is always computed; whether a tax LINE is appended
        # depends on that fallback account existing (it does on the canonical site,
        # not on bare CI test sites). Both branches are asserted.
        sales_final_fallback = "1500 - BTW af te dragen 21% - NVV"
        code = "INVCOVFINAL21"
        self._patch_btw(code, "Primary Nonexistent Account - ZZZ")
        invoice = _InvoiceStub(self.company)
        regels = [{"amount": 100, "quantity": 1, "BTWCode": code, "Omschrijving": "z"}]
        debug = []

        with self.assertNoErrorLog():
            result = add_tax_lines(invoice, regels, "sales", debug)

        self.assertEqual(result["tax_amount"], 21.0)
        if frappe.db.exists("Account", sales_final_fallback):
            self.assertEqual(len(invoice.taxes), 1)
            self.assertEqual(invoice.taxes[0]["account_head"], sales_final_fallback)
            self.assertTrue(any("final fallback tax account" in m for m in debug))
        else:
            # No resolvable tax account -> no tax line appended.
            self.assertEqual(len(invoice.taxes), 0)
            self.assertTrue(any("No tax account found" in m for m in debug))


# ---------------------------------------------------------------------------
# get_tax_account: account_fallback branch + final-fallback branch
# ---------------------------------------------------------------------------
class TestGetTaxAccountFallbacks(_TaxFixtureBase):
    def test_account_fallback_branch(self):
        # Primary account_name does not exist, but account_fallback DOES -> the
        # fallback branch returns it. (Sibling only covers primary + unknown.)
        from verenigingen.e_boekhouden.utils import invoice_helpers as mod

        code = "INVCOVFB"
        original = dict(mod.BTW_CODE_MAP)
        mod.BTW_CODE_MAP[code] = {
            "rate": 21,
            "account_name": "Primary Missing Acct - ZZZ",
            "account_fallback": self.btw_account,
            "description": "fb",
        }
        try:
            debug = []
            result = get_tax_account(code, "sales", self.company, debug)
            self.assertEqual(result, self.btw_account)
            self.assertTrue(any("fallback tax account" in m for m in debug))
        finally:
            mod.BTW_CODE_MAP.clear()
            mod.BTW_CODE_MAP.update(original)

    def test_final_fallback_branch_purchase(self):
        # Primary + account_fallback both missing -> the hardcoded final fallback
        # for "purchase" ("1530 - BTW te vorderen - NVV", present on veg11) is
        # returned. Exercises the invoice_type=="purchase" final-fallback branch
        # (the sibling never reaches the final-fallback block at all).
        from verenigingen.e_boekhouden.utils import invoice_helpers as mod

        purchase_final_fallback = "1530 - BTW te vorderen - NVV"
        code = "INVCOVPURCH"
        original = dict(mod.BTW_CODE_MAP)
        mod.BTW_CODE_MAP[code] = {
            "rate": 21,
            "account_name": "Primary Missing - ZZZ",
            "account_fallback": "Fallback Missing - ZZZ",
            "description": "purch",
        }
        try:
            debug = []
            result = get_tax_account(code, "purchase", self.company, debug)
            # The hardcoded final fallback is returned only when it exists (canonical
            # site); otherwise get_tax_account exhausts all options and returns None.
            if frappe.db.exists("Account", purchase_final_fallback):
                self.assertEqual(result, purchase_final_fallback)
                self.assertTrue(any("final fallback tax account" in m for m in debug))
            else:
                self.assertIsNone(result)
                self.assertTrue(any("No suitable tax account" in m for m in debug))
        finally:
            mod.BTW_CODE_MAP.clear()
            mod.BTW_CODE_MAP.update(original)


# ---------------------------------------------------------------------------
# process_line_items: credit-note (is_return), missing-account throw, Kostenplaats
# ---------------------------------------------------------------------------
class TestProcessLineItemsBranches(_TaxFixtureBase):
    def test_is_return_credit_note_negative_qty(self):
        # invoice.is_return=True -> the credit-note branch: qty defaults to -1,
        # rate is abs(amount). Distinct from the sibling's negative-amount path
        # (which goes through the non-return branch).
        invoice = _InvoiceStub(self.company, doctype="Sales Invoice", is_return=True)
        regels = [
            {"ledgerId": "80100", "amount": 100.0, "quantity": None, "Omschrijving": "Retour", "BTWCode": ""}
        ]
        # The item-naming helper logs a benign "Account Not Found ... Using fallback
        # naming" Error Log because our synthetic "80100 - InvCov Omzet" account has
        # no eboekhouden_grootboek_nummer. That fallback is expected; any OTHER error
        # still trips the guard.
        with self.assertNoErrorLog(ignore=["Account Not Found"]):
            result = process_line_items(invoice, regels, "sales", None, [])
        self.assertTrue(result)
        line = invoice.items[0]
        self.assertEqual(line["qty"], -1)
        self.assertEqual(line["rate"], 100.0)
        self.assertEqual(line["income_account"], self.coded_income)

    def test_is_return_with_explicit_quantity(self):
        # is_return with a provided quantity -> qty = flt(raw_quantity) (the
        # `quantity = flt(raw_quantity) if raw_quantity else -1` truthy side).
        invoice = _InvoiceStub(self.company, doctype="Sales Invoice", is_return=True)
        regels = [
            {"ledgerId": "80100", "amount": 60.0, "quantity": 3, "Omschrijving": "Retour3", "BTWCode": ""}
        ]
        with self.assertNoErrorLog(ignore=["Account Not Found"]):
            process_line_items(invoice, regels, "sales", None, [])
        self.assertEqual(invoice.items[0]["qty"], 3)
        self.assertEqual(invoice.items[0]["rate"], 60.0)

    def test_missing_account_mapping_throws(self):
        # A ledger code with neither a direct-name account nor a ledger mapping ->
        # map_grootboek_to_erpnext_account(allow_fallback=False) returns None ->
        # process_line_items raises the "Account Mapping Required" throw.
        invoice = _InvoiceStub(self.company, doctype="Sales Invoice")
        regels = [
            {"ledgerId": "99999999", "amount": 10.0, "quantity": 1, "Omschrijving": "Orphan", "BTWCode": ""}
        ]
        with self.assertRaises(frappe.ValidationError):
            process_line_items(invoice, regels, "sales", None, [])

    def _ensure_resolution_company_cost_center(self):
        # process_line_items calls get_cost_center WITHOUT a company arg, so it
        # resolves against E-Boekhouden Settings.default_company. Make sure that
        # company has a usable (non-group) cost center, otherwise get_cost_center
        # throws on bare CI test companies that ship without one. Rolled back by
        # FrappeTestCase, so this never mutates shared state permanently.
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company
        if not company:
            self.skipTest("No E-Boekhouden Settings default_company configured")
        if frappe.db.get_value("Company", company, "cost_center"):
            return
        if frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name"):
            return
        root = frappe.db.get_value("Cost Center", {"company": company, "is_group": 1}, "name")
        if not root:
            self.skipTest(f"{company} has no root cost center group to attach to")
        cc = frappe.new_doc("Cost Center")
        cc.cost_center_name = "Main"
        cc.company = company
        cc.parent_cost_center = root
        cc.is_group = 0
        cc.insert(ignore_permissions=True)

    def test_kostenplaats_sets_line_cost_center(self):
        # A regel carrying KostenplaatsId triggers the per-line cost-center branch:
        # line_item["cost_center"] = get_cost_center(KostenplaatsId).
        #
        # NOTE on existing behavior: process_line_items calls get_cost_center WITHOUT
        # a company arg (invoice_helpers.py:208), so it resolves against E-Boekhouden
        # Settings.default_company, NOT invoice.company. We assert the branch ran and
        # produced a real, valid Cost Center, without coupling to which company owns
        # it (that depends on the live settings default_company).
        self._ensure_resolution_company_cost_center()
        invoice = _InvoiceStub(self.company, doctype="Sales Invoice")
        regels = [
            {
                "ledgerId": "80100",
                "amount": 40.0,
                "quantity": 1,
                "Omschrijving": "WithCC",
                "BTWCode": "",
                "KostenplaatsId": "anything",
            }
        ]
        with self.assertNoErrorLog(ignore=["Account Not Found"]):
            process_line_items(invoice, regels, "sales", None, [])
        resolved_cc = invoice.items[0]["cost_center"]
        self.assertTrue(resolved_cc)
        # The branch resolved a genuine Cost Center record (not the passed-in None).
        self.assertTrue(frappe.db.exists("Cost Center", resolved_cc))


# ---------------------------------------------------------------------------
# get_or_create_item_from_description: short-circuit + stock + suggested-UOM
# ---------------------------------------------------------------------------
class TestGetOrCreateItemBranches(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def test_existing_item_code_short_circuit(self):
        # Two DIFFERENT descriptions slugging to the SAME item_code: the first
        # creates the Item; the second finds no description match but hits the
        # `frappe.db.exists("Item", item_code)` short-circuit (line 335) and
        # returns the existing code WITHOUT creating a duplicate.
        # generate_item_code truncates to 30 chars, so both descriptions must share
        # an identical first-30-char prefix and differ only beyond it.
        from verenigingen.e_boekhouden.utils.invoice_helpers import generate_item_code

        prefix = "WidgetCov Shared Prefix Abcde"  # 29 chars -> slug stays <=30
        desc1 = prefix + " ALPHA distinct tail one"
        desc2 = prefix + " BETA distinct tail two"
        code = generate_item_code(desc1)
        self.assertEqual(code, generate_item_code(desc2))
        self.assertNotEqual(desc1, desc2)
        frappe.db.delete("Item", {"item_code": code})
        frappe.db.delete("Item", {"description": desc1})
        frappe.db.delete("Item", {"description": desc2})
        frappe.db.commit()

        debug = []
        with self.assertNoErrorLog():
            c1 = get_or_create_item_from_description(desc1, debug_info=debug)
            c2 = get_or_create_item_from_description(desc2, debug_info=debug)
        self.assertEqual(c1, code)
        self.assertEqual(c2, code)
        self.assertEqual(frappe.db.count("Item", {"item_code": code}), 1)
        self.assertTrue(any("Item code already exists" in m for m in debug))

    def test_product_keyword_is_stock_item(self):
        # description keyword "laptop" -> "Products" item group -> the stock-item
        # configuration branch (is_stock_item=1, FIFO). Asserts the branch's side
        # effect on the created Item.
        desc = "Nieuwe laptop EBkhCov stock unique zzz"
        frappe.db.delete("Item", {"description": desc})
        frappe.db.commit()
        with self.assertNoErrorLog():
            code = get_or_create_item_from_description(desc, debug_info=[])
        item = frappe.get_doc("Item", code)
        self.assertEqual(item.item_group, "Products")
        self.assertEqual(item.is_stock_item, 1)
        self.assertEqual(item.valuation_method, "FIFO")

    def test_service_default_is_non_stock_with_suggested_uom(self):
        # No unit + a Services-group description -> non-stock branch AND the
        # suggested-UOM-from-category branch (mapped "Nos" + unit in ["Nos",None,""]
        # -> UOMManager.get_uom_for_category("Services") == "Hour").
        desc = "Consultancy advies EBkhCov suggested uom unique zzz"
        frappe.db.delete("Item", {"description": desc})
        frappe.db.commit()
        with self.assertNoErrorLog():
            code = get_or_create_item_from_description(desc, unit="", debug_info=[])
        item = frappe.get_doc("Item", code)
        self.assertEqual(item.item_group, "Services")
        self.assertEqual(item.is_stock_item, 0)
        self.assertEqual(item.stock_uom, "Hour")


if __name__ == "__main__":
    unittest.main()
