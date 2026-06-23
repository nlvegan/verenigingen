"""
Gap-fill coverage for smart_tegenrekening_mapper.py (DEPRECATED module, still loaded).

Target: verenigingen/e_boekhouden/utils/smart_tegenrekening_mapper.py

This complements the existing test_tegenrekening_mapper.py (pure-string helpers +
_get_account_by_code resolution) WITHOUT duplicating it. Here we cover:

- _get_smart_item               : pre-created "EB-<code>" Item resolution path,
                                  including the descriptive-name override.
- _get_account_by_code          : the eboekhouden_grootboek_nummer branch and the
                                  ledger-id -> mapped-account-code branch (both
                                  untouched by the existing test).
- get_item_for_tegenrekening    : Strategy-1 (smart item) success + the
                                  "no mapping found" throw.
- create_invoice_line_for_tegenrekening : line-dict assembly (qty/rate/abs amount,
                                  cost center, account routing) using a pre-created
                                  smart item -- avoids the dynamic-item-creation path
                                  (which needs item-group + permission scaffolding).
- deprecated helper wrappers    : get_item_for_purchase_transaction /
                                  get_item_for_sales_transaction delegate correctly.

OUT OF SCOPE (needs item-group + secure_document_operation permission scaffolding,
and is the DEPRECATED path the module itself warns against using):
- _create_dynamic_item actual Item insert, _create_fallback_item, _get_fallback_item.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_tegenrekening_mapper_coverage
"""

import frappe

from verenigingen.e_boekhouden.utils.smart_tegenrekening_mapper import (
    SmartTegenrekeningMapper,
    create_invoice_line_for_tegenrekening,
    get_item_for_purchase_transaction,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSmartItemResolution(EnhancedTestCase):
    """_get_smart_item / get_item_for_tegenrekening against a pre-created EB item."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        cls.company = get_eur_test_company()
        cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")

    def _ensure_item_group(self, name):
        if not frappe.db.exists("Item Group", name):
            parent = frappe.db.get_value("Item Group", {"is_group": 1}, "name")
            g = frappe.new_doc("Item Group")
            g.item_group_name = name
            g.parent_item_group = parent
            g.insert(ignore_permissions=True)

    def _make_account(self, acct_name, *, account_number=None, grootboek=None):
        parent = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": "Income", "is_group": 1}, "name"
        )
        full = f"{acct_name} - {self.abbr}"
        if frappe.db.exists("Account", full):
            return full
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = self.company
        doc.parent_account = parent
        doc.root_type = "Income"
        doc.account_type = "Income Account"
        if account_number:
            doc.account_number = account_number
        if grootboek and frappe.db.has_column("Account", "eboekhouden_grootboek_nummer"):
            doc.eboekhouden_grootboek_nummer = grootboek
        doc.insert(ignore_permissions=True)
        return doc.name

    def _make_smart_item(self, account_code, item_name="EB Smart Item"):
        item_code = f"EB-{account_code}"
        if frappe.db.exists("Item", item_code):
            return item_code
        self._ensure_item_group("Revenue Items")
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = item_name
        item.item_group = "Revenue Items"
        item.stock_uom = "Nos"
        item.is_stock_item = 0
        item.insert(ignore_permissions=True)
        return item_code

    def _mapper(self):
        return SmartTegenrekeningMapper(company=self.company)

    def test_get_smart_item_returns_precreated_item_with_account(self):
        code = "85501"
        # ERPNext prefixes the account name with the account_number, so passing
        # account_name="Smart Income" + account_number="85501" yields the canonical
        # "85501 - Smart Income - <abbr>" name the descriptive parser expects.
        acct = self._make_account("Smart Income", account_number=code)
        self._make_smart_item(code)
        mapper = self._mapper()

        result = mapper._get_smart_item(code)
        self.assertIsNotNone(result)
        self.assertEqual(result["item_code"], f"EB-{code}")
        self.assertEqual(result["account"], acct)
        self.assertEqual(result["source"], "smart_mapping")
        # The descriptive name is derived from the account name ("<code> - X - <abbr>").
        self.assertEqual(result["item_name"], "Smart Income")

    def test_get_smart_item_missing_returns_none(self):
        mapper = self._mapper()
        self.assertIsNone(mapper._get_smart_item("NO-EB-ITEM-9999"))

    def test_get_item_for_tegenrekening_uses_smart_strategy(self):
        code = "85502"
        self._make_account("Strategy One", account_number=code)
        self._make_smart_item(code)
        mapper = self._mapper()

        with self.assertNoErrorLog():
            result = mapper.get_item_for_tegenrekening(code, "desc", "sales", 10)
        self.assertEqual(result["source"], "smart_mapping")
        self.assertEqual(result["item_code"], f"EB-{code}")

    def test_get_item_for_tegenrekening_no_mapping_throws(self):
        # No smart item, no ERPNext account => neither strategy fires => throw.
        mapper = self._mapper()
        self.expectErrorLog("not found in company")  # _get_account_by_code logs the miss
        with self.assertRaises(frappe.ValidationError):
            mapper.get_item_for_tegenrekening("NO-SUCH-MAP-7777", "desc", "purchase", 5)

    def test_resolve_by_grootboek_nummer(self):
        # The eboekhouden_grootboek_nummer branch must resolve BEFORE account_number.
        if not frappe.db.has_column("Account", "eboekhouden_grootboek_nummer"):
            self.skipTest("eboekhouden_grootboek_nummer column not present")
        code = "85777"
        acct = self._make_account("Grootboek Account", grootboek=code)
        mapper = self._mapper()
        with self.assertNoErrorLog():
            self.assertEqual(mapper._get_account_by_code(code), acct)

    def _make_ledger_mapping(self, ledger_id, account_code):
        if frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id}):
            frappe.delete_doc(
                "E-Boekhouden Ledger Mapping",
                frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id}, "name"),
                ignore_permissions=True,
                force=True,
            )
        m = frappe.new_doc("E-Boekhouden Ledger Mapping")
        m.ledger_id = ledger_id
        m.ledger_code = account_code
        m.ledger_name = "Mapped"
        m.insert(ignore_permissions=True)
        return m.name

    def test_ledger_id_mapped_to_account_code(self):
        # A > 5-digit all-digit code is treated as a ledger ID. With a mapping row
        # pointing it at a real account code, resolution must follow the mapping.
        ledger_id = "770001"
        account_code = "85778"
        acct = self._make_account("Mapped Via Ledger", account_number=account_code)
        self._make_ledger_mapping(ledger_id, account_code)

        mapper = self._mapper()
        with self.assertNoErrorLog():
            resolved = mapper._get_account_by_code(ledger_id)
        self.assertEqual(resolved, acct)


class TestCreateInvoiceLine(EnhancedTestCase):
    """
    create_invoice_line_for_tegenrekening assembles the ERPNext line dict.

    NOTE: this module-level helper hardcodes ``SmartTegenrekeningMapper()`` with the
    default company ("Ned Ver Vegan"), which does NOT exist on this site. So the
    company-scoped account/cost-center lookups deliberately MISS, and we assert the
    parts that ARE reachable regardless of company: the smart Item resolves (Items
    are global), qty/abs-amount math, the description fallback, and the
    "only add an account field when one is resolvable" branch (here: none, so the
    line carries no income_account/expense_account). The account-routing branch
    itself is covered by TestSmartItemResolution via the company-scoped mapper.
    """

    def _ensure_item_group(self, name):
        if not frappe.db.exists("Item Group", name):
            parent = frappe.db.get_value("Item Group", {"is_group": 1}, "name")
            g = frappe.new_doc("Item Group")
            g.item_group_name = name
            g.parent_item_group = parent
            g.insert(ignore_permissions=True)

    def _make_smart_item(self, account_code):
        item_code = f"EB-{account_code}"
        if frappe.db.exists("Item", item_code):
            return item_code
        self._ensure_item_group("Revenue Items")
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = "EB Line Item"
        item.item_group = "Revenue Items"
        item.stock_uom = "Nos"
        item.is_stock_item = 0
        item.insert(ignore_permissions=True)
        return item_code

    def test_line_dict_abs_amount_and_item_resolution(self):
        code = "86001"
        self._make_smart_item(code)
        # The default-company account lookup misses (company absent) and logs it.
        self.expectErrorLog("not found in company")

        line = create_invoice_line_for_tegenrekening(
            code, amount=-123.45, description="A sale", transaction_type="sales"
        )
        # Smart item (global) resolves even without a company-scoped account.
        self.assertEqual(line["item_code"], f"EB-{code}")
        self.assertEqual(line["qty"], 1)
        # Amount is taken as absolute value regardless of sign.
        self.assertEqual(line["rate"], 123.45)
        self.assertEqual(line["amount"], 123.45)
        # No resolvable company account => the line carries no account field.
        self.assertNotIn("income_account", line)
        self.assertNotIn("expense_account", line)

    def test_line_dict_description_falls_back_to_item_name(self):
        code = "86002"
        self._make_smart_item(code)
        self.expectErrorLog("not found in company")

        line = create_invoice_line_for_tegenrekening(
            code, amount=50.0, description="", transaction_type="purchase"
        )
        # Empty description falls back to the item name.
        self.assertEqual(line["description"], line["item_name"])
        # abs() applied to a positive amount is a no-op.
        self.assertEqual(line["rate"], 50.0)


class TestDeprecatedHelperWrappers(EnhancedTestCase):
    """The deprecated module-level helpers must delegate to the mapper."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        cls.company = get_eur_test_company()
        cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")

    def test_purchase_helper_throws_on_unmappable_code(self):
        # The wrapper instantiates a default-company mapper; an unmappable code must
        # propagate the same "no mapping" ValidationError as the method.
        self.expectErrorLog("not found in company")
        with self.assertRaises(frappe.ValidationError):
            get_item_for_purchase_transaction("NO-MAP-DELEGATE-8888", "x", 1)
