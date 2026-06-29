"""
Coverage sweep for the orchestration + creation paths of
verenigingen/e_boekhouden/utils/eboekhouden_coa_import.py

The sibling module ``test_coa_import.py`` already covers the pure string/regex
helpers and the reporting/validation helpers. This module deliberately targets
the remaining uncovered blocks:

  * ``create_bank_accounts_from_coa`` (scan imported CoA, create Bank Accounts)
  * ``create_bank_accounts_for_existing_coa`` (settings-driven variant)
  * ``coa_import_with_bank_accounts`` error path
  * ``create_bank_account_record`` account-number-only / account-holder branches

Every test asserts a concrete side effect (a persisted Bank Account, a returned
count, a specific error string), not merely "does not raise".

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_coa_import_sweep
"""

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_coa_import import (
    coa_import_with_bank_accounts,
    create_bank_account_record,
    create_bank_accounts_for_existing_coa,
    create_bank_accounts_from_coa,
    extract_bank_info_from_account_name,
    get_or_create_bank,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _CoaSweepBase(EnhancedTestCase):
    """A dedicated EUR company plus a Bank-type leaf CoA account whose name
    encodes a Triodos account number, so the scan/create flow has real data."""

    COMPANY = "TEST CoA Sweep Co"
    ABBR = "TCSW"
    LABEL = "Triodos - 19.83.96.716 - Algemeen"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_company()
        cls.bank_gl_account = cls._persist_account(cls.LABEL, "Bank")

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
    def _persist_account(cls, acct_name, account_type, root_type="Asset"):
        full = f"{acct_name} - {cls.ABBR}"
        if frappe.db.exists("Account", full):
            return full
        parent = frappe.db.get_value(
            "Account", {"company": cls.COMPANY, "root_type": root_type, "is_group": 1}, "name"
        )
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = cls.COMPANY
        doc.parent_account = parent
        doc.account_type = account_type
        doc.root_type = root_type
        doc.is_group = 0
        doc.insert(ignore_permissions=True)
        return doc.name

    def _clear_bank_accounts_on(self, gl_account):
        """Remove any Bank Account mapped to ``gl_account`` AND any that collide on
        the extracted account number / IBAN. veg11 is not reset between runs, so a
        prior run may have left a Bank Account whose ``bank_account_no``/``iban``
        matches -- the production dedup check would then skip creation."""
        names = set(frappe.get_all("Bank Account", filters={"account": gl_account}, pluck="name"))
        label = frappe.db.get_value("Account", gl_account, "account_name")
        if label:
            info = extract_bank_info_from_account_name(label)
            if info.get("account_number"):
                names |= set(
                    frappe.get_all(
                        "Bank Account",
                        filters={"bank_account_no": info["account_number"]},
                        pluck="name",
                    )
                )
            if info.get("iban"):
                names |= set(
                    frappe.get_all("Bank Account", filters={"iban": info["iban"]}, pluck="name")
                )
        for existing in names:
            frappe.delete_doc("Bank Account", existing, force=True, ignore_permissions=True)
        frappe.db.commit()


class TestCreateBankAccountsFromCoa(_CoaSweepBase):
    def test_creates_bank_account_from_scanned_coa(self):
        self._clear_bank_accounts_on(self.bank_gl_account)

        migration_doc = frappe._dict({"company": self.company})
        result = create_bank_accounts_from_coa(migration_doc)

        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["created"], 1)
        self.assertEqual(result["errors"], [])
        # A Bank Account must now be mapped to the seeded Bank GL account.
        ba = frappe.db.get_value("Bank Account", {"account": self.bank_gl_account}, "bank_account_no")
        self.assertEqual(ba, "19.83.96.716")

    def test_idempotent_skips_already_created(self):
        # First call creates it, second call must detect the existing Bank Account
        # (by bank_account_no) and create nothing more.
        self._clear_bank_accounts_on(self.bank_gl_account)
        migration_doc = frappe._dict({"company": self.company})

        first = create_bank_accounts_from_coa(migration_doc)
        self.assertGreaterEqual(first["created"], 1)

        second = create_bank_accounts_from_coa(migration_doc)
        self.assertTrue(second["success"])
        self.assertEqual(second["created"], 0)

    def test_no_company_returns_error(self):
        # migration_doc has no company AND settings default is blank -> explicit error.
        prev = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")
        frappe.db.set_single_value("E-Boekhouden Settings", "default_company", "")
        try:
            result = create_bank_accounts_from_coa(frappe._dict({"company": None}))
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "No company specified")
        finally:
            frappe.db.set_single_value("E-Boekhouden Settings", "default_company", prev)


class TestCreateBankAccountsForExistingCoa(_CoaSweepBase):
    def _with_settings_company(self, company, fn):
        prev = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")
        frappe.db.set_single_value("E-Boekhouden Settings", "default_company", company)
        try:
            return fn()
        finally:
            frappe.db.set_single_value("E-Boekhouden Settings", "default_company", prev)

    def test_creates_for_existing_coa(self):
        self._clear_bank_accounts_on(self.bank_gl_account)

        result = self._with_settings_company(self.company, create_bank_accounts_for_existing_coa)

        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["created"], 1)
        self.assertGreaterEqual(result["processed"], 1)
        self.assertTrue(frappe.db.exists("Bank Account", {"account": self.bank_gl_account}))

    def test_no_default_company_returns_error(self):
        result = self._with_settings_company("", create_bank_accounts_for_existing_coa)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "No default company set")


class TestCoaImportOrchestrationError(EnhancedTestCase):
    def test_nonexistent_migration_returns_error(self):
        # get_doc on a missing migration raises -> caught -> error result + log_error.
        self.expectErrorLog("Enhanced CoA")
        result = coa_import_with_bank_accounts("NO-SUCH-MIGRATION-DOC")
        self.assertFalse(result["success"])
        self.assertIn("error", result)


class TestCreateBankAccountRecordBranches(_CoaSweepBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create the extra leaf accounts ONCE here (committed) rather than inside
        # test methods: per-test Account inserts mix with savepoints/commits and
        # contend on the large veg11 nested-set tree (rgt rebalancing deadlocks).
        cls.gl_number_only = cls._persist_account("ING - 1234567890", "Bank")
        cls.gl_paypal = cls._persist_account("PayPal account", "Bank")

    def test_account_number_only_name(self):
        # bank_info with account_number but NO description -> "<bank> - <number>".
        gl = self.gl_number_only
        self._clear_bank_accounts_on(gl)
        account_doc = frappe.get_doc("Account", gl)
        bank_info = {
            "bank_name": "ING Bank",
            "account_number": "1234567890",
            "description": None,
            "iban": None,
        }
        bank_name = get_or_create_bank(bank_info)
        created = create_bank_account_record(
            account=account_doc, bank_name=bank_name, bank_info=bank_info, company=self.company
        )
        self.assertIsNotNone(created)
        self.assertEqual(
            frappe.db.get_value("Bank Account", created, "account_name"), "ING Bank - 1234567890"
        )
        self.assertEqual(frappe.db.get_value("Bank Account", created, "bank_account_no"), "1234567890")

    def test_account_holder_sets_party(self):
        # PayPal-style: account_holder present -> party_type Company, party = company.
        gl = self.gl_paypal
        self._clear_bank_accounts_on(gl)
        # The synthetic account number here is the email, which is not derivable
        # from the GL account name -- clear any prior collision explicitly.
        for nm in frappe.get_all(
            "Bank Account", filters={"bank_account_no": "info@veganisme.org"}, pluck="name"
        ):
            frappe.delete_doc("Bank Account", nm, force=True, ignore_permissions=True)
        frappe.db.commit()
        account_doc = frappe.get_doc("Account", gl)
        bank_info = extract_bank_info_from_account_name("PayPal - info@veganisme.org")
        self.assertEqual(bank_info["account_holder"], "info@veganisme.org")
        bank_name = get_or_create_bank(bank_info)
        created = create_bank_account_record(
            account=account_doc, bank_name=bank_name, bank_info=bank_info, company=self.company
        )
        self.assertIsNotNone(created)
        self.assertEqual(frappe.db.get_value("Bank Account", created, "party_type"), "Company")
        self.assertEqual(frappe.db.get_value("Bank Account", created, "party"), self.company)
