"""
Integration tests for
verenigingen/e_boekhouden/utils/transaction_utils.py

These create_*_impl / get_*_impl functions take a `migration_doc` (an
E-Boekhouden Migration controller) plus eBoekhouden record data. We exercise
them with a lightweight migration-doc stand-in that supplies only the
attributes/methods the functions touch (company + a handful of helper methods),
and real DB master data. No live eBoekhouden HTTP connection is involved.

Run with:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_transaction_utils
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.transaction_utils import (
    create_customer_impl,
    create_supplier_impl,
    get_mapped_account_impl,
    get_suspense_account_impl,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _MigrationDocStub:
    """Stand-in for the E-Boekhouden Migration controller.

    Supplies only the attributes/methods transaction_utils touches. Contact and
    address creation are no-ops (those paths have their own coverage and need a
    fully wired migration doc)."""

    def __init__(self, company):
        self.company = company

    def get_parent_account(self, account_type, root_type, company):
        return frappe.db.get_value(
            "Account", {"company": company, "root_type": root_type, "is_group": 1}, "name"
        )

    def get_proper_territory_for_customer(self, customer_data):
        return frappe.db.get_value("Territory", {"is_group": 0}, "name")

    def create_contact_for_customer(self, *args, **kwargs):
        return None

    def create_address_for_customer(self, *args, **kwargs):
        return None

    def create_contact_for_supplier(self, *args, **kwargs):
        return None

    def create_address_for_supplier(self, *args, **kwargs):
        return None


class _TxUtilsBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()
        cls.migration_doc = _MigrationDocStub(cls.company)

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST EBkh TxUtils Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TETX"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def _persist_account_with_number(self, acct_name, account_number, root_type="Expense"):
        parent = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": root_type, "is_group": 1}, "name"
        )
        full = f"{acct_name} - TETX"
        if frappe.db.exists("Account", full):
            return full
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = self.company
        doc.parent_account = parent
        doc.account_number = account_number
        doc.root_type = root_type
        doc.insert(ignore_permissions=True)
        return doc.name


class TestGetMappedAccount(_TxUtilsBase):
    def test_unmapped_returns_none(self):
        self.assertIsNone(get_mapped_account_impl(self.migration_doc, "DOESNOTEXIST999"))

    def test_lookup_by_account_number(self):
        acct = self._persist_account_with_number("TxUtils Mapped Acct", "47123")
        result = get_mapped_account_impl(self.migration_doc, "47123")
        self.assertEqual(result, acct)

    def _persist_ledger_mapping(self, ledger_id, code, account):
        if frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_code": code}):
            return
        m = frappe.new_doc("E-Boekhouden Ledger Mapping")
        m.ledger_id = ledger_id
        m.ledger_code = code
        m.ledger_name = "TxUtils Ledger"
        m.erpnext_account = account
        m.insert(ignore_permissions=True)

    def test_lookup_via_ledger_mapping(self):
        acct = self._persist_account_with_number("TxUtils Ledger Acct", "47999")
        code = "EBKHTX-LEDGER-1"
        self._persist_ledger_mapping("70001", code, acct)
        result = get_mapped_account_impl(self.migration_doc, code)
        self.assertEqual(result, acct)


class TestGetSuspenseAccount(_TxUtilsBase):
    def test_creates_suspense_account(self):
        result = get_suspense_account_impl(self.migration_doc, self.company)
        self.assertTrue(result)
        self.assertTrue(frappe.db.exists("Account", result))
        self.assertIn("E-Boekhouden Suspense", result)

    def test_idempotent(self):
        first = get_suspense_account_impl(self.migration_doc, self.company)
        second = get_suspense_account_impl(self.migration_doc, self.company)
        self.assertEqual(first, second)


class TestCreateCustomer(_TxUtilsBase):
    def test_company_and_contact_name(self):
        result = create_customer_impl(
            self.migration_doc, {"Bedrijf": "TxUtils Acme BV", "Contactpersoon": "Jan", "ID": "5001"}
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["created"])
        self.assertEqual(result["customer"], "TxUtils Acme BV (Jan)")
        self.assertEqual(frappe.db.get_value("Customer", result["customer"], "customer_type"), "Company")

    def test_company_only(self):
        result = create_customer_impl(
            self.migration_doc, {"Bedrijf": "TxUtils SoloCo BV", "Contactpersoon": "", "ID": "5002"}
        )
        self.assertEqual(result["customer"], "TxUtils SoloCo BV")

    def test_contact_only_is_individual(self):
        result = create_customer_impl(
            self.migration_doc, {"Bedrijf": "", "Contactpersoon": "Pietje Puk", "ID": "5003"}
        )
        self.assertEqual(result["customer"], "Pietje Puk")
        self.assertEqual(frappe.db.get_value("Customer", result["customer"], "customer_type"), "Individual")

    def test_no_name_uses_id(self):
        result = create_customer_impl(self.migration_doc, {"Bedrijf": "", "Contactpersoon": "", "ID": "5004"})
        self.assertEqual(result["customer"], "Customer 5004")

    def test_existing_customer_not_recreated(self):
        data = {"Bedrijf": "TxUtils Dup BV", "Contactpersoon": "", "ID": "5005"}
        first = create_customer_impl(self.migration_doc, data)
        self.assertTrue(first["created"])
        second = create_customer_impl(self.migration_doc, data)
        self.assertFalse(second["created"])
        self.assertEqual(first["customer"], second["customer"])


class TestCreateSupplier(_TxUtilsBase):
    def test_company_name(self):
        result = create_supplier_impl(
            self.migration_doc, {"Bedrijf": "TxUtils Vendor BV", "Contactpersoon": "", "ID": "6001"}
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["created"])
        self.assertEqual(result["supplier"], "TxUtils Vendor BV")

    def test_company_and_contact(self):
        result = create_supplier_impl(
            self.migration_doc, {"Bedrijf": "TxUtils Vendor2 BV", "Contactpersoon": "Klaas", "ID": "6002"}
        )
        self.assertEqual(result["supplier"], "TxUtils Vendor2 BV (Klaas)")

    def test_no_name_uses_id(self):
        result = create_supplier_impl(self.migration_doc, {"Bedrijf": "", "Contactpersoon": "", "ID": "6003"})
        self.assertEqual(result["supplier"], "Supplier 6003")

    def test_existing_supplier_not_recreated(self):
        data = {"Bedrijf": "TxUtils SupDup BV", "Contactpersoon": "", "ID": "6004"}
        first = create_supplier_impl(self.migration_doc, data)
        second = create_supplier_impl(self.migration_doc, data)
        self.assertFalse(second["created"])
        self.assertEqual(first["supplier"], second["supplier"])


if __name__ == "__main__":
    unittest.main()
