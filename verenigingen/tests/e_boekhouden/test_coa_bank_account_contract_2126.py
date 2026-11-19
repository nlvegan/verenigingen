"""
#2126: caller-visible contracts of the e-Boekhouden CoA bank-account flow and of the
Ponto bank-account creator, which now share one Bank / Bank Account creator
(``verenigingen/utils/bank_account_creation.py``).

The refactor is meant to change no caller's visible behaviour, so most tests here are
CHARACTERISATION tests (green on develop before the refactor, green after): created
counts, None from the service, continue-on-error in the loop callers, Ponto raising
``PontoIntegrationError``. The new behaviour (a currency that disagrees with the GL
account is refused; the real reason reaches the callers' error lists) is in
``TestSharedCreatorNewBehaviour2126``.

Usage:
    bench --site test_site_10 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_coa_bank_account_contract_2126
"""

import random

import frappe

from verenigingen.e_boekhouden.services.account_migration_service import AccountMigrationService
from verenigingen.e_boekhouden.utils.eboekhouden_coa_import import create_missing_bank_accounts
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError
from verenigingen.verenigingen_payments.ponto.utils.bank_account_creator import (
    create_bank_account_record as ponto_create_bank_account_record,
    get_or_create_bank as ponto_get_or_create_bank,
)

# A Bank Account autonames "<account_name> - <bank>" into a 140-char name, so a description
# this long makes the Bank Account insert fail while the GL account itself still fits.
LONG_DESCRIPTION = "Zakelijk " + "x" * 91


class _CoaBankBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def _gl_account(self, description, currency="EUR"):
        """A Bank-type CoA leaf whose name encodes a unique Triodos account number."""
        digits = "".join(random.choice("0123456789") for _ in range(7))
        label = f"Triodos - 55.{digits[:2]}.{digits[2:4]}.{digits[4:]} - {description}"
        parent = frappe.db.get_value(
            "Account", {"company": self.company, "account_type": "Bank", "is_group": 1}, "name"
        )
        doc = frappe.new_doc("Account")
        doc.account_name = label
        doc.company = self.company
        doc.parent_account = parent
        doc.account_type = "Bank"
        doc.account_currency = currency
        doc.insert()
        return doc, label


class TestCoaCallerContracts2126(_CoaBankBase):
    def test_service_returns_the_bank_account_name_on_success(self):
        gl, label = self._gl_account("Algemeen")
        created = AccountMigrationService(company=self.company).create_bank_account_for_coa_account(gl, label)
        self.assertEqual(frappe.db.get_value("Bank Account", created, "account"), gl.name)

    def test_service_returns_none_and_does_not_raise_when_creation_fails(self):
        self.expectErrorLog("Bank")
        gl, label = self._gl_account(LONG_DESCRIPTION)
        result = AccountMigrationService(company=self.company).create_bank_account_for_coa_account(gl, label)
        self.assertIsNone(result)
        self.assertFalse(frappe.db.exists("Bank Account", {"account": gl.name}))

    def test_create_missing_continues_past_a_failure_and_counts_the_rest(self):
        self.expectErrorLog("Bank")
        good, _ = self._gl_account("Algemeen")
        bad, _ = self._gl_account(LONG_DESCRIPTION)

        result = create_missing_bank_accounts(self.company)

        self.assertTrue(result["success"])
        created_for = {row["account"] for row in result["created_accounts"]}
        self.assertIn(good.name, created_for)
        self.assertNotIn(bad.name, created_for)
        self.assertEqual(result["total_created"], len(result["created_accounts"]))
        self.assertEqual(result["total_errors"], len(result["errors"]))
        self.assertTrue(any(bad.name in error for error in result["errors"]), result["errors"])
        self.assertTrue(frappe.db.exists("Bank Account", {"account": good.name}))
        self.assertFalse(frappe.db.exists("Bank Account", {"account": bad.name}))


class TestPontoCreatorContract2126(_CoaBankBase):
    def test_get_or_create_bank_raises_ponto_error_on_failure(self):
        self.expectErrorLog("Bank")
        with self.assertRaises(PontoIntegrationError):
            ponto_get_or_create_bank({"bank_name": "B" * 300})

    def test_create_bank_account_record_raises_ponto_error_on_failure(self):
        self.expectErrorLog("Bank")
        gl, _ = self._gl_account("Algemeen")
        with self.assertRaises(PontoIntegrationError):
            ponto_create_bank_account_record(
                gl_account=gl.name,
                bank_name="No Such Bank 2126",
                iban="",
                account_name=f"Contract 2126 {frappe.generate_hash(length=6)}",
                company=self.company,
                currency="EUR",
            )


class TestSharedCreatorNewBehaviour2126(_CoaBankBase):
    """What changed on purpose: a currency that disagrees with the GL account is refused,
    and the real failure reason reaches the loop callers' error lists."""

    def test_currency_that_differs_from_the_gl_account_is_refused(self):
        from verenigingen.utils.bank_account_creation import BankAccountCreationError, create_bank_account

        foreign = "USD" if frappe.db.get_value("Company", self.company, "default_currency") != "USD" else "GBP"
        gl, _ = self._gl_account("Dollar", currency=foreign)
        gl_currency = frappe.db.get_value("Account", gl.name, "account_currency")
        asked = "EUR" if gl_currency != "EUR" else "USD"
        self.expectErrorLog("Bank")

        with self.assertRaises(BankAccountCreationError) as ctx:
            create_bank_account(
                gl_account=gl.name, bank="Triodos Bank", account_name=f"Mismatch 2126 {frappe.generate_hash(length=6)}",
                company=self.company, currency=asked,
            )
        self.assertIn(gl_currency, str(ctx.exception))
        self.assertIn(asked, str(ctx.exception))
        self.assertFalse(frappe.db.exists("Bank Account", {"account": gl.name}))

    def test_ponto_helper_refuses_a_currency_the_gl_account_does_not_have(self):
        gl, _ = self._gl_account("Dollar", currency="USD")
        with self.assertRaises(PontoIntegrationError) as ctx:
            ponto_create_bank_account_record(
                gl_account=gl.name, bank_name="Triodos Bank", iban="",
                account_name=f"Mismatch 2126 {frappe.generate_hash(length=6)}",
                company=self.company, currency="EUR",
            )
        self.assertIn("USD", ctx.exception.message)

    def test_the_gl_currency_is_accepted_for_a_foreign_currency_account(self):
        gl, label = self._gl_account("Dollar", currency="USD")
        created = AccountMigrationService(company=self.company).create_bank_account_for_coa_account(gl, label)
        self.assertEqual(frappe.db.get_value("Bank Account", created, "account"), gl.name)

    def test_create_missing_reports_the_real_reason_not_a_generic_failure(self):
        bad, _ = self._gl_account(LONG_DESCRIPTION)
        self.expectErrorLog("Bank")

        result = create_missing_bank_accounts(self.company)

        mine = [error for error in result["errors"] if bad.name in error]
        self.assertEqual(len(mine), 1, result["errors"])
        self.assertIn("Data too long", mine[0])
