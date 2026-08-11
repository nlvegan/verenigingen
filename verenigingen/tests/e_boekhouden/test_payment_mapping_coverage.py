"""
Coverage tests for
verenigingen/e_boekhouden/utils/eboekhouden_payment_mapping.py

Exercises payment-account mapping resolution against real
``E-Boekhouden Payment Mapping`` rows and the default-account fallback:
    * get_default_payment_mappings  - account-type / root-type defaults from CoA
    * get_payment_account_mappings  - DB rows by mapping_type, with fallback
    * get_mapped_account            - specific / pattern / type resolution
    * setup_default_payment_mappings - whitelisted setup entrypoint

All real DB, no live eBoekhouden HTTP. Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_payment_mapping_coverage
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_payment_mapping import (
    get_default_payment_mappings,
    get_mapped_account,
    get_payment_account_mappings,
    setup_default_payment_mappings,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.select_options import get_select_options


def _ensure_mode_of_payment(name):
    """Ensure a Mode of Payment master exists (mode_of_payment is a Link field)."""
    if not frappe.db.exists("Mode of Payment", name):
        mode = frappe.new_doc("Mode of Payment")
        mode.mode_of_payment = name
        mode.type = "Bank"
        mode.insert(ignore_permissions=True)
    return name


def _persist_eur_company():
    """Dedicated EUR company with a real Chart of Accounts for these tests."""
    name = "EBkh PayMap Co"
    if frappe.db.exists("Company", name):
        return name
    company = frappe.new_doc("Company")
    company.company_name = name
    company.abbr = "EPMC"
    company.default_currency = "EUR"
    company.country = "Netherlands"
    company.insert(ignore_permissions=True)
    return company.name


class _PayMapBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()
        # mode_of_payment is a Link field; ensure the masters the setup entrypoint
        # references exist.
        _ensure_mode_of_payment("Bank Transfer")
        _ensure_mode_of_payment("Cash")

    def setUp(self):
        super().setUp()
        # Clean any mappings left committed by a prior run of the setup entrypoint
        # (setup_default_payment_mappings calls frappe.db.commit()).
        frappe.db.delete("E-Boekhouden Payment Mapping", {"company": self.company})
        frappe.db.commit()

    def _leaf_account(self, root_type="Expense"):
        return frappe.db.get_value(
            "Account", {"company": self.company, "root_type": root_type, "is_group": 0}, "name"
        )

    def _make_mapping(self, **kwargs):
        defaults = {
            "company": self.company,
            "mapping_type": "Specific Account",
            "account_type": "Bank",
            "mode_of_payment": _ensure_mode_of_payment("Bank Transfer"),
            "active": 1,
            "priority": 100,
        }
        defaults.update(kwargs)
        # account_name and eboekhouden_account_code are mandatory on the doctype
        defaults.setdefault("account_name", defaults.get("erpnext_account") or "Mapping")
        defaults.setdefault(
            "eboekhouden_account_code",
            kwargs.get("eboekhouden_account_code") or f"AUTO-{defaults['account_type']}",
        )
        doc = frappe.new_doc("E-Boekhouden Payment Mapping")
        doc.update(defaults)
        doc.insert(ignore_permissions=True)
        return doc.name


class TestGetDefaultPaymentMappings(_PayMapBase):
    def test_includes_expense_and_income_defaults(self):
        mappings = get_default_payment_mappings(self.company)
        # A freshly created company has a standard CoA with Expense/Income roots
        self.assertIn("expense_account", mappings)
        self.assertIn("income_account", mappings)
        # The returned accounts must really belong to this company and be leaves
        for key in ("expense_account", "income_account"):
            acct = mappings[key]
            self.assertEqual(frappe.db.get_value("Account", acct, "company"), self.company)
            self.assertEqual(frappe.db.get_value("Account", acct, "is_group"), 0)

    def test_receivable_and_payable_resolved_when_present(self):
        mappings = get_default_payment_mappings(self.company)
        # Standard CoA ships Debtors (Receivable) and Creditors (Payable)
        if "receivable_account" in mappings:
            self.assertEqual(
                frappe.db.get_value("Account", mappings["receivable_account"], "account_type"),
                "Receivable",
            )
        if "payable_account" in mappings:
            self.assertEqual(
                frappe.db.get_value("Account", mappings["payable_account"], "account_type"),
                "Payable",
            )

    def test_unknown_company_returns_empty(self):
        self.assertEqual(get_default_payment_mappings("Nonexistent Company XYZ"), {})


class TestGetPaymentAccountMappings(_PayMapBase):
    def test_falls_back_to_defaults_when_no_db_rows(self):
        # No mappings exist for this company -> must return default-account map,
        # which includes expense/income (not the DB-derived keys).
        result = get_payment_account_mappings(self.company)
        self.assertIn("expense_account", result)

    def test_specific_account_mapping_keyed_by_code(self):
        acct = self._leaf_account()
        self._make_mapping(
            mapping_type="Specific Account", eboekhouden_account_code="77123", erpnext_account=acct
        )
        result = get_payment_account_mappings(self.company)
        self.assertEqual(result.get("eboekhouden_77123"), acct)

    def test_account_type_mapping_keyed_by_lowercase_type(self):
        acct = self._leaf_account(root_type="Asset")
        self._make_mapping(mapping_type="Account Type", account_type="Bank", erpnext_account=acct)
        result = get_payment_account_mappings(self.company)
        self.assertEqual(result.get("bank_account"), acct)

    def test_pattern_mapping_keyed_by_pattern(self):
        acct = self._leaf_account()
        self._make_mapping(
            mapping_type="Account Number Pattern", account_pattern="7%", erpnext_account=acct
        )
        result = get_payment_account_mappings(self.company)
        self.assertEqual(result.get("pattern_7%"), acct)


class TestGetMappedAccount(_PayMapBase):
    def test_specific_code_match(self):
        acct = self._leaf_account()
        self._make_mapping(
            mapping_type="Specific Account", eboekhouden_account_code="77500", erpnext_account=acct
        )
        self.assertEqual(get_mapped_account(self.company, eboekhouden_account_code="77500"), acct)

    def test_pattern_prefix_match(self):
        acct = self._leaf_account()
        self._make_mapping(
            mapping_type="Account Number Pattern", account_pattern="46%", erpnext_account=acct
        )
        # 46123 starts with pattern "46" -> matches
        self.assertEqual(get_mapped_account(self.company, eboekhouden_account_code="46123"), acct)

    def test_account_type_match(self):
        acct = self._leaf_account(root_type="Asset")
        self._make_mapping(mapping_type="Account Type", account_type="Cash", erpnext_account=acct)
        self.assertEqual(get_mapped_account(self.company, account_type="Cash"), acct)

    def test_no_match_returns_none(self):
        # No mappings beyond defaults; a random code with no type must miss.
        self.assertIsNone(get_mapped_account(self.company, eboekhouden_account_code="00000nope"))


class TestSetupDefaultPaymentMappings(_PayMapBase):
    def test_creates_account_type_mappings_and_message_formatted(self):
        result = setup_default_payment_mappings(self.company)
        self.assertTrue(result["success"], result.get("error"))
        # At least the expense/income defaults exist, so Receivable/Payable/Bank/Cash
        # mappings are created when those default accounts resolve.
        rows = frappe.get_all(
            "E-Boekhouden Payment Mapping",
            filters={"company": self.company, "mapping_type": "Account Type"},
            fields=["account_type", "erpnext_account"],
        )
        # REGRESSION GUARD: message must be a real count, not the literal template.
        self.assertNotIn("{len(created_mappings)}", result["message"])
        # And each entry in the returned mappings list must be a formatted arrow,
        # not the literal template "{account_type} → {defaults[key]}".
        for entry in result["mappings"]:
            self.assertNotIn("{account_type}", entry)
            self.assertNotIn("{defaults[key]}", entry)
        # If any Account-Type mapping was created, the erpnext_account is real.
        for row in rows:
            self.assertEqual(frappe.db.get_value("Account", row.erpnext_account, "company"), self.company)

    def test_idempotent_does_not_duplicate(self):
        setup_default_payment_mappings(self.company)
        before = frappe.db.count("E-Boekhouden Payment Mapping", {"company": self.company})
        setup_default_payment_mappings(self.company)
        after = frappe.db.count("E-Boekhouden Payment Mapping", {"company": self.company})
        self.assertEqual(before, after)


class TestPaymentMappingAccountTypeOptions(VereningingenTestCase):
    """
    setup_default_payment_mappings() builds mappings for four account types, but the
    account_type Select only offered Bank and Cash — so the very first insert
    (Receivable) was rejected and no defaults were ever created, for any company.

    On VereningingenTestCase rather than EnhancedTestCase deliberately: the latter
    sets frappe.flags.in_import, which skips _validate_selects() entirely, so a test
    on that harness cannot see this class of defect at all.
    """

    def test_every_configured_account_type_is_a_declared_option(self):
        options = get_select_options("E-Boekhouden Payment Mapping", "account_type")
        for account_type in ("Bank", "Cash", "Receivable", "Payable"):
            self.assertIn(account_type, options)

    def test_receivable_mapping_can_be_saved(self):
        company = _persist_eur_company()
        account = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
        )
        doc = frappe.new_doc("E-Boekhouden Payment Mapping")
        doc.update(
            {
                "company": company,
                "mapping_type": "Account Type",
                "account_type": "Receivable",
                "erpnext_account": account,
                "mode_of_payment": _ensure_mode_of_payment("Bank Transfer"),
                "account_name": "Receivable default",
                "eboekhouden_account_code": f"RECV-{frappe.generate_hash(length=6)}",
                "active": 1,
                "priority": 100,
            }
        )
        doc.insert()
        self.track_doc("E-Boekhouden Payment Mapping", doc.name)
        self.assertEqual(
            frappe.db.get_value("E-Boekhouden Payment Mapping", doc.name, "account_type"), "Receivable"
        )


if __name__ == "__main__":
    unittest.main()
