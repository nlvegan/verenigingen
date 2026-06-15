"""
Integration tests for the Ponto bank-account creator.

These are REAL-INTEGRATION tests: they feed realistic ``PontoAccount`` dicts
to ``create_ponto_bank_account`` and assert it creates real Frappe
Bank / Account (GL) / Bank Account documents under a real EUR test company,
and that re-running is idempotent. No HTTP / API mocking is involved -- this
module exercises only the local document-creation logic.

IBAN note: ERPNext's Bank Account insert applies a strict IBAN validator.
Only the ``ABN_AMRO_*`` and ``ING_*`` fixture IBANs pass it, so this module
sticks to those (RABO/SNS/TRIODOS fixture IBANs have invalid checksums for the
strict validator and are intentionally avoided here).

Usage:
    bench --site test_site_3 run-tests --app verenigingen \
        --module verenigingen.tests.sepa.test_ponto_bank_account_creator
"""

import unittest
from decimal import Decimal

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.ponto_test_data_factory import TestIBAN
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.ponto.core.ponto_models import PontoAccount
from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError
from verenigingen.verenigingen_payments.ponto.utils.bank_account_creator import (
    create_ponto_bank_account,
    get_or_create_bank,
    identify_bank_from_iban,
)


def _ponto_account(iban, account_id="acc-1", description="Ponto Test Account", holder="Test Org BV"):
    return PontoAccount(
        id=account_id,
        reference=iban,
        reference_type="IBAN",
        currency="EUR",
        current_balance=Decimal("0"),
        available_balance=Decimal("0"),
        description=description,
        holder_name=holder,
    )


class TestIdentifyBankFromIban(FrappeTestCase):
    """Pure logic: bank identification from IBAN (no DB)."""

    def test_identifies_abn_amro(self):
        info = identify_bank_from_iban(TestIBAN.ABN_AMRO_1)
        self.assertEqual(info["bank_name"], "ABN AMRO")
        self.assertEqual(info["bank_code"], "ABNA")
        self.assertEqual(info["swift_code"], "ABNANL2A")

    def test_identifies_ing(self):
        info = identify_bank_from_iban(TestIBAN.ING_1)
        self.assertEqual(info["bank_name"], "ING Bank")
        self.assertEqual(info["swift_code"], "INGBNL2A")

    def test_unknown_bank_code_falls_back(self):
        info = identify_bank_from_iban("NL00XXXX0123456789")
        self.assertEqual(info["bank_code"], "XXXX")
        self.assertIn("XXXX", info["bank_name"])
        self.assertIsNone(info["swift_code"])

    def test_too_short_iban_is_unknown(self):
        info = identify_bank_from_iban("NL00")
        self.assertEqual(info["bank_name"], "Unknown Bank")
        self.assertIsNone(info["bank_code"])

    def test_empty_iban_is_unknown(self):
        info = identify_bank_from_iban("")
        self.assertEqual(info["bank_name"], "Unknown Bank")


class TestGetOrCreateBank(FrappeTestCase):
    """Bank record creation + idempotency (real Bank docs)."""

    def test_creates_and_reuses_bank(self):
        info = identify_bank_from_iban(TestIBAN.ABN_AMRO_1)
        name1 = get_or_create_bank(info)
        self.assertTrue(frappe.db.exists("Bank", name1))
        self.assertEqual(frappe.db.get_value("Bank", name1, "swift_number"), "ABNANL2A")

        # Second call must return the same record, not create a duplicate.
        name2 = get_or_create_bank(info)
        self.assertEqual(name1, name2)


class TestCreatePontoBankAccount(FrappeTestCase):
    """Full create_ponto_bank_account flow against a real EUR company."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def test_creates_bank_gl_account_and_bank_account(self):
        account = _ponto_account(TestIBAN.ABN_AMRO_1, account_id="acc-create-1")

        result = create_ponto_bank_account(account, self.company)

        self.assertTrue(result["success"], msg=result.get("error"))

        # 1. Bank record
        self.assertTrue(frappe.db.exists("Bank", result["bank"]))
        self.assertEqual(result["bank"], "ABN AMRO")

        # 2. GL Account (Chart of Accounts) -- real Bank-type leaf account
        gl = frappe.get_doc("Account", result["gl_account"])
        self.assertEqual(gl.account_type, "Bank")
        self.assertEqual(gl.company, self.company)
        self.assertEqual(gl.account_currency, "EUR")
        self.assertEqual(gl.is_group, 0)

        # 3. Bank Account doc, linked to the GL account + Bank + company
        ba = frappe.get_doc("Bank Account", result["bank_account"])
        self.assertEqual(ba.iban, TestIBAN.ABN_AMRO_1)
        self.assertEqual(ba.account, result["gl_account"])
        self.assertEqual(ba.bank, result["bank"])
        self.assertEqual(ba.company, self.company)
        self.assertEqual(ba.is_company_account, 1)

    def test_is_idempotent_on_rerun(self):
        account = _ponto_account(TestIBAN.ING_1, account_id="acc-idem-1")

        first = create_ponto_bank_account(account, self.company)
        self.assertTrue(first["success"], msg=first.get("error"))

        second = create_ponto_bank_account(account, self.company)
        self.assertTrue(second["success"], msg=second.get("error"))

        # Same documents returned both times -- no duplicates.
        self.assertEqual(first["bank"], second["bank"])
        self.assertEqual(first["gl_account"], second["gl_account"])
        self.assertEqual(first["bank_account"], second["bank_account"])

        # Exactly one Bank Account exists for the IBAN.
        self.assertEqual(
            frappe.db.count("Bank Account", {"iban": TestIBAN.ING_1}),
            1,
        )

    def test_account_name_uses_description(self):
        account = _ponto_account(
            TestIBAN.ABN_AMRO_2, account_id="acc-name-1", description="Operating Account"
        )
        result = create_ponto_bank_account(account, self.company)
        self.assertTrue(result["success"], msg=result.get("error"))
        self.assertIn("Operating Account", result["gl_account"])
        self.assertIn("ABN AMRO", result["gl_account"])

    def test_account_name_falls_back_to_holder_then_iban(self):
        account = PontoAccount(
            id="acc-name-2",
            reference=TestIBAN.ABN_AMRO_2,
            reference_type="IBAN",
            currency="EUR",
            current_balance=Decimal("0"),
            available_balance=Decimal("0"),
            description="",
            holder_name="Stichting Vegan",
        )
        result = create_ponto_bank_account(account, self.company)
        self.assertTrue(result["success"], msg=result.get("error"))
        self.assertIn("Stichting Vegan", result["gl_account"])

    def test_explicit_parent_account_is_used(self):
        parent = frappe.db.get_value(
            "Account",
            {"company": self.company, "is_group": 1, "account_type": "Bank"},
            "name",
        )
        self.assertTrue(parent, "EUR test company must have a Bank group account")

        account = _ponto_account(TestIBAN.ABN_AMRO_1, account_id="acc-parent-1")
        result = create_ponto_bank_account(account, self.company, parent_account=parent)

        self.assertTrue(result["success"], msg=result.get("error"))
        self.assertEqual(
            frappe.db.get_value("Account", result["gl_account"], "parent_account"),
            parent,
        )

    def test_returns_error_dict_on_failure_not_raise(self):
        """A bad parent account must surface as {'success': False, ...}, not raise.

        Uses a unique description so the GL account does not already exist (which
        would short-circuit before the bad parent is ever used)."""
        account = _ponto_account(
            TestIBAN.ABN_AMRO_1,
            account_id="acc-fail-1",
            description="Unique Failing Account 9f3a",
        )
        result = create_ponto_bank_account(
            account, self.company, parent_account="Nonexistent Parent - ZZZ"
        )
        self.assertFalse(result["success"])
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
