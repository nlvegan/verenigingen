"""
Coverage tests for
verenigingen/e_boekhouden/utils/eboekhouden_migration_config.py

Exercises the payment-account classification helpers (``is_payment_account``,
``get_payment_account_info``) against the hardcoded PAYMENT_ACCOUNT_CONFIG and
against real ``E-Boekhouden Payment Mapping`` rows, plus the whitelisted setup
and validation entrypoints (``setup_payment_modes``, ``validate_migration_setup``).

All real DB, no live eBoekhouden HTTP. Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_config_coverage
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_migration_config import (
    get_payment_account_info,
    is_payment_account,
    setup_payment_modes,
    validate_migration_setup,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _persist_eur_company():
    """Dedicated EUR company for these tests (self-contained fixture chain)."""
    name = "EBkh MigConfig Co"
    if frappe.db.exists("Company", name):
        return name
    company = frappe.new_doc("Company")
    company.company_name = name
    company.abbr = "EMCC"
    company.default_currency = "EUR"
    company.country = "Netherlands"
    company.insert(ignore_permissions=True)
    return company.name


class _ConfigBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()

    def _leaf_account(self, root_type="Expense"):
        return frappe.db.get_value(
            "Account", {"company": self.company, "root_type": root_type, "is_group": 0}, "name"
        )

    def _make_payment_mapping(self, account_code, erpnext_account, active=1, account_type="Bank"):
        """Create a real E-Boekhouden Payment Mapping row for this company."""
        existing = frappe.db.exists(
            "E-Boekhouden Payment Mapping",
            {"company": self.company, "eboekhouden_account_code": account_code},
        )
        if existing:
            return existing
        doc = frappe.new_doc("E-Boekhouden Payment Mapping")
        doc.company = self.company
        doc.mapping_type = "Specific Account"
        doc.eboekhouden_account_code = account_code
        doc.account_name = f"Mapping {account_code}"
        doc.erpnext_account = erpnext_account
        doc.account_type = account_type
        doc.mode_of_payment = "Bank Transfer"
        doc.active = active
        doc.insert(ignore_permissions=True)
        return doc.name


class TestIsPaymentAccount(_ConfigBase):
    def test_empty_code_is_false(self):
        self.assertFalse(is_payment_account(""))
        self.assertFalse(is_payment_account(None))

    def test_hardcoded_bank_account(self):
        # 10440 is a Triodos bank account in PAYMENT_ACCOUNT_CONFIG
        self.assertTrue(is_payment_account("10440"))

    def test_hardcoded_cash_account(self):
        # 10000 is "Kas" in PAYMENT_ACCOUNT_CONFIG
        self.assertTrue(is_payment_account("10000"))

    def test_unknown_code_without_company_is_false(self):
        self.assertFalse(is_payment_account("99999"))

    def test_db_mapping_takes_precedence(self):
        """A code not in the hardcoded config but present as an active DB mapping
        must be classified as a payment account when company is supplied."""
        acct = self._leaf_account()
        self._make_payment_mapping("88001", acct, active=1)
        # Without company: not in hardcoded config -> False
        self.assertFalse(is_payment_account("88001"))
        # With company: active DB mapping -> True
        with self.assertNoErrorLog():
            self.assertTrue(is_payment_account("88001", company=self.company))

    def test_inactive_db_mapping_is_not_matched(self):
        acct = self._leaf_account()
        self._make_payment_mapping("88002", acct, active=0)
        # Inactive mapping must NOT classify as payment account; falls through to
        # hardcoded config which also lacks 88002 -> False.
        self.assertFalse(is_payment_account("88002", company=self.company))


class TestGetPaymentAccountInfo(_ConfigBase):
    def test_hardcoded_bank_info(self):
        info = get_payment_account_info("10440")
        self.assertEqual(info["type"], "Bank")
        self.assertEqual(info["mode_of_payment"], "Bank Transfer")
        self.assertIn("Triodos", info["name"])

    def test_hardcoded_cash_info(self):
        info = get_payment_account_info("10000")
        self.assertEqual(info["type"], "Cash")
        self.assertEqual(info["mode_of_payment"], "Cash")

    def test_unknown_returns_none(self):
        self.assertIsNone(get_payment_account_info("77777"))

    def test_db_mapping_info_takes_precedence(self):
        acct = self._leaf_account()
        self._make_payment_mapping("88003", acct, active=1)
        with self.assertNoErrorLog():
            info = get_payment_account_info("88003", company=self.company)
        self.assertIsNotNone(info)
        self.assertEqual(info["erpnext_account"], acct)
        self.assertEqual(info["type"], "Bank")

    def test_company_provided_but_no_db_mapping_falls_back_to_hardcoded(self):
        # 10440 has no DB mapping for this company, but company is provided;
        # function must still fall back to the hardcoded bank config.
        info = get_payment_account_info("10440", company=self.company)
        self.assertEqual(info["type"], "Bank")


class TestSetupPaymentModes(_ConfigBase):
    def test_creates_required_modes_and_message_is_formatted(self):
        result = setup_payment_modes()
        self.assertTrue(result["success"])
        # All four required modes must exist after setup
        for mode in ["Bank Transfer", "PayPal", "Cash", "SEPA Direct Debit"]:
            self.assertTrue(frappe.db.exists("Mode of Payment", mode), f"{mode} missing")
        # REGRESSION GUARD: the summary message must be an actual count, not the
        # literal template string "Created {len(created)} modes of payment".
        self.assertNotIn("{len(created)}", result["message"])
        self.assertIn("modes of payment", result["message"])

    def test_idempotent(self):
        setup_payment_modes()
        result = setup_payment_modes()
        self.assertTrue(result["success"])
        # On a second run nothing new should be created
        self.assertEqual(result["created"], [])


class TestValidateMigrationSetup(_ConfigBase):
    def test_returns_structured_report(self):
        with self.assertNoErrorLog():
            report = validate_migration_setup()
        self.assertIn("success", report)
        self.assertIn("issues", report)
        self.assertIn("warnings", report)
        self.assertIn("summary", report)
        self.assertIsInstance(report["warnings"], list)
        self.assertIn("customers", report["summary"])
        self.assertIn("suppliers", report["summary"])
        # success is the inverse of having any issues
        self.assertEqual(report["success"], len(report["issues"]) == 0)

    def test_mode_of_payment_warning_is_formatted(self):
        """REGRESSION GUARD: when a required Mode of Payment is missing the
        warning must name the mode, not emit the broken literal
        "Mode of Payment f'{mode}' not found"."""
        # Guarantee a required mode is absent so the warning branch actually
        # fires. db.delete bypasses link validation and is rolled back by
        # FrappeTestCase, so this never mutates shared state. "PayPal" is one of
        # validate_migration_setup's hardcoded required_modes.
        frappe.db.delete("Mode of Payment", {"name": "PayPal"})
        self.assertFalse(frappe.db.exists("Mode of Payment", "PayPal"))

        report = validate_migration_setup()
        mode_warnings = [w for w in report["warnings"] if "Mode of Payment" in w]
        self.assertTrue(mode_warnings, "expected a missing-Mode-of-Payment warning")
        # Interpolation actually happened: the mode name appears, the template does not.
        self.assertTrue(
            any("PayPal" in w for w in mode_warnings),
            "warning should name the missing mode",
        )
        for w in mode_warnings:
            self.assertNotIn("{mode}", w, "broken f-string leaked into warning")


if __name__ == "__main__":
    unittest.main()
