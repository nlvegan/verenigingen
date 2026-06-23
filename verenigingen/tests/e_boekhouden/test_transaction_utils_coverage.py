"""
Gap-fill coverage for
verenigingen/e_boekhouden/utils/transaction_utils.py

The existing test_transaction_utils.py covers create_customer_impl /
create_supplier_impl / get_mapped_account_impl / get_suspense_account_impl.
This module adds the uncovered transaction builders:

    * create_journal_entry_impl  - balanced + auto-balancing-to-suspense paths,
      submitted JE (needs a current Fiscal Year).
    * create_sales_invoice_impl / create_purchase_invoice_impl - the early
      validation guards (missing / invalid Relatie) which are PURE and assert
      a structured error without touching the live eBoekhouden REST API.

The full SI/PI happy paths import eBoekhouden item-naming + credit-note helpers
from eboekhouden_rest_full_migration and resolve ledger IDs via the REST layer;
those are exercised by the REST migration suites and are out of scope here.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_transaction_utils_coverage
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.transaction_utils import (
    create_journal_entry_impl,
    create_purchase_invoice_impl,
    create_sales_invoice_impl,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _persist_eur_company():
    name = "EBkh TxCov Co"
    if frappe.db.exists("Company", name):
        return name
    company = frappe.new_doc("Company")
    company.company_name = name
    company.abbr = "ETXC"
    company.default_currency = "EUR"
    company.country = "Netherlands"
    company.insert(ignore_permissions=True)
    return company.name


def _ensure_current_fiscal_year():
    """Make the current calendar FY apply to all companies (so JE submit works)."""
    from verenigingen.tests.setup import ensure_test_fiscal_year_for_all_companies

    ensure_test_fiscal_year_for_all_companies()
    d = frappe.utils.getdate(frappe.utils.today())
    covering = frappe.db.sql(
        """
        SELECT name FROM `tabFiscal Year`
        WHERE %s BETWEEN year_start_date AND year_end_date AND disabled = 0
        """,
        (d,),
        pluck=True,
    )
    for fy_name in covering:
        if frappe.db.exists("Fiscal Year Company", {"parent": fy_name}):
            frappe.db.delete("Fiscal Year Company", {"parent": fy_name})
    frappe.db.commit()
    frappe.cache().delete_value("fiscal_years")


class _JEMigrationDocStub:
    """Migration-doc stand-in supplying exactly what create_journal_entry_impl
    touches: a company plus account-resolution helpers backed by real CoA rows."""

    def __init__(self, company, mapped_accounts):
        self.company = company
        # map: eboekhouden code -> ERPNext account name
        self._mapped = mapped_accounts
        self._suspense = None

    def get_mapped_account(self, code):
        return self._mapped.get(code)

    def get_parent_account(self, account_type, root_type, company):
        return frappe.db.get_value(
            "Account", {"company": company, "root_type": root_type, "is_group": 1}, "name"
        )

    def get_suspense_account(self, company):
        if self._suspense:
            return self._suspense
        from verenigingen.e_boekhouden.utils.transaction_utils import get_suspense_account_impl

        self._suspense = get_suspense_account_impl(self, company)
        return self._suspense


class _TxCovBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()
        _ensure_current_fiscal_year()

    def _make_leaf_account(self, account_name, root_type="Expense"):
        parent = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": root_type, "is_group": 1}, "name"
        )
        full = f"{account_name} - ETXC"
        if frappe.db.exists("Account", full):
            return full
        doc = frappe.new_doc("Account")
        doc.account_name = account_name
        doc.company = self.company
        doc.parent_account = parent
        doc.root_type = root_type
        doc.insert(ignore_permissions=True)
        return doc.name


class TestCreateJournalEntry(_TxCovBase):
    def test_balanced_two_line_entry_submits(self):
        # Use balance-sheet accounts (Asset/Liability): P&L accounts additionally
        # require a Cost Center, which create_journal_entry_impl does not set
        # (the production caller supplies cost_center via the row line itself).
        debit_acct = self._make_leaf_account("TxCov Debtors A", "Asset")
        credit_acct = self._make_leaf_account("TxCov Bank A", "Asset")
        stub = _JEMigrationDocStub(self.company, {"EXP": debit_acct, "BNK": credit_acct})
        data = {
            "Datum": "2025-03-15",
            "Omschrijving": "TxCov balanced JE",
            "MutatieNr": "JE-COV-1",
            "Regels": [
                {"TegenrekeningCode": "EXP", "BedragExclBTW": 100, "Omschrijving": "expense line"},
                {"TegenrekeningCode": "BNK", "BedragExclBTW": -100, "Omschrijving": "bank line"},
            ],
        }
        with self.assertNoErrorLog():
            result = create_journal_entry_impl(stub, data)
        self.assertTrue(result["success"], result.get("error"))
        je_name = result["journal_entry"]
        je = frappe.get_doc("Journal Entry", je_name)
        self.assertEqual(je.docstatus, 1)
        self.assertEqual(je.eboekhouden_mutation_nr, "JE-COV-1")
        # Two lines, balanced -> no suspense balancing row appended
        self.assertEqual(len(je.accounts), 2)
        self.assertAlmostEqual(float(je.total_debit), 100.0, places=2)
        self.assertAlmostEqual(float(je.total_credit), 100.0, places=2)

    def test_unbalanced_entry_gets_suspense_balancing_row(self):
        debit_acct = self._make_leaf_account("TxCov Debtors B", "Asset")
        stub = _JEMigrationDocStub(self.company, {"EXP": debit_acct})
        data = {
            "Datum": "2025-03-16",
            "Omschrijving": "TxCov unbalanced JE",
            "MutatieNr": "JE-COV-2",
            # Single debit line of 250 with no offsetting credit -> needs balancing
            "Regels": [
                {"TegenrekeningCode": "EXP", "BedragExclBTW": 250, "Omschrijving": "only debit"},
            ],
        }
        with self.assertNoErrorLog():
            result = create_journal_entry_impl(stub, data)
        self.assertTrue(result["success"], result.get("error"))
        je = frappe.get_doc("Journal Entry", result["journal_entry"])
        # 1 real line + 1 suspense balancing line
        self.assertEqual(len(je.accounts), 2)
        suspense = frappe.db.get_value(
            "Account", {"company": self.company, "account_name": "E-Boekhouden Suspense"}, "name"
        )
        balancing = [a for a in je.accounts if a.account == suspense]
        self.assertEqual(len(balancing), 1)
        # The suspense line carries a 250 credit to offset the 250 debit
        self.assertAlmostEqual(float(balancing[0].credit_in_account_currency), 250.0, places=2)
        self.assertAlmostEqual(float(je.total_debit), float(je.total_credit), places=2)

    def test_unmapped_code_routes_line_to_suspense(self):
        stub = _JEMigrationDocStub(self.company, {})  # no mappings at all
        data = {
            "Datum": "2025-03-17",
            "Omschrijving": "TxCov unmapped JE",
            "MutatieNr": "JE-COV-3",
            "Regels": [
                {"TegenrekeningCode": "UNKNOWN", "BedragExclBTW": 50, "Omschrijving": "orphan"},
            ],
        }
        with self.assertNoErrorLog():
            result = create_journal_entry_impl(stub, data)
        self.assertTrue(result["success"], result.get("error"))
        je = frappe.get_doc("Journal Entry", result["journal_entry"])
        suspense = frappe.db.get_value(
            "Account", {"company": self.company, "account_name": "E-Boekhouden Suspense"}, "name"
        )
        # The single unmapped line is posted to suspense, and a second suspense
        # balancing line offsets it -> every line is the suspense account.
        self.assertTrue(all(a.account == suspense for a in je.accounts))

    def test_bad_date_returns_structured_error(self):
        # getdate() raises on an unparseable date; the function's own try/except
        # converts it to a structured error (no Error Log is written).
        stub = _JEMigrationDocStub(self.company, {})
        result = create_journal_entry_impl(
            stub, {"Datum": "not-a-date", "Regels": [], "MutatieNr": "JE-COV-BAD"}
        )
        self.assertFalse(result["success"])
        self.assertIn("error", result)


class TestInvoiceValidationGuards(_TxCovBase):
    """The SI/PI builders validate Relatie up-front before any REST call.
    These guards are pure and must return a structured error (the frappe.throw
    is caught by the function's own try/except)."""

    def test_sales_invoice_missing_relatie(self):
        stub = _JEMigrationDocStub(self.company, {})
        result = create_sales_invoice_impl(stub, {"Datum": "2025-03-15", "Regels": []})
        self.assertFalse(result["success"])
        self.assertIn("Relatie", result["error"])

    def test_sales_invoice_relatie_not_a_dict(self):
        stub = _JEMigrationDocStub(self.company, {})
        result = create_sales_invoice_impl(
            stub, {"Datum": "2025-03-15", "Relatie": "oops", "Regels": []}
        )
        self.assertFalse(result["success"])
        self.assertIn("Relatie", result["error"])

    def test_sales_invoice_missing_customer_id(self):
        stub = _JEMigrationDocStub(self.company, {})
        result = create_sales_invoice_impl(
            stub, {"Datum": "2025-03-15", "Relatie": {"Bedrijf": "X"}, "Regels": []}
        )
        self.assertFalse(result["success"])
        self.assertIn("customer ID", result["error"])

    def test_purchase_invoice_missing_relatie(self):
        stub = _JEMigrationDocStub(self.company, {})
        result = create_purchase_invoice_impl(stub, {"Datum": "2025-03-15", "Regels": []})
        self.assertFalse(result["success"])
        self.assertIn("Relatie", result["error"])

    def test_purchase_invoice_missing_supplier_id(self):
        stub = _JEMigrationDocStub(self.company, {})
        result = create_purchase_invoice_impl(
            stub, {"Datum": "2025-03-15", "Relatie": {"Bedrijf": "X"}, "Regels": []}
        )
        self.assertFalse(result["success"])
        self.assertIn("supplier ID", result["error"])


if __name__ == "__main__":
    unittest.main()
