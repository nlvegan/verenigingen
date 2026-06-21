"""
Unit / integration tests for the Chart-of-Accounts import helpers in
verenigingen/e_boekhouden/utils/eboekhouden_coa_import.py

Focus: the pure string/pattern helpers (bank detection, bank-info extraction,
bank-name/code identification, Dutch IBAN generation) plus a couple of
DB-backed reporting helpers that work without a live eBoekhouden connection.

Run with:
    bench --site test_site_3 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_coa_import
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_coa_import import (
    cleanup_duplicate_bank_accounts,
    create_bank_account_record,
    create_missing_bank_accounts,
    discover_missing_bank_accounts,
    extract_bank_info_from_account_name,
    find_bank_accounts_in_coa,
    fix_bank_account_mappings,
    generate_dutch_iban,
    generate_iban_if_possible,
    get_or_create_bank,
    has_account_number_pattern,
    identify_bank_code_from_name,
    identify_bank_name,
    identify_bank_name_enhanced,
    is_potential_bank_account,
    validate_bank_account_mappings,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# ---------------------------------------------------------------------------
# Pure helpers - no DB access
# ---------------------------------------------------------------------------
class TestIsPotentialBankAccount(unittest.TestCase):
    def test_bank_keyword(self):
        self.assertTrue(is_potential_bank_account("Triodos Bankrekening"))

    def test_iban_in_name(self):
        self.assertTrue(is_potential_bank_account("Saldo NL02ABNA0123456789"))

    def test_email_paypal(self):
        self.assertTrue(is_potential_bank_account("PayPal info@example.org"))

    def test_old_ten_digit_number(self):
        self.assertTrue(is_potential_bank_account("Rekening 1234567890"))

    def test_group_code_002(self):
        self.assertTrue(is_potential_bank_account("Some random name", account_code="002001"))

    def test_group_code_fin(self):
        self.assertTrue(is_potential_bank_account("Some random name", account_code="FIN001"))

    def test_plain_expense_name_not_bank(self):
        self.assertFalse(is_potential_bank_account("Algemene kosten advies"))

    def test_no_keyword_no_number(self):
        self.assertFalse(is_potential_bank_account("Donaties", account_code="80001"))


class TestHasAccountNumberPattern(unittest.TestCase):
    def test_triodos_dotted(self):
        self.assertTrue(has_account_number_pattern("Triodos - 19.83.96.716 - Algemeen"))

    def test_rabo_dotted(self):
        self.assertTrue(has_account_number_pattern("Rabo - 1234.56.789"))

    def test_ten_digit(self):
        self.assertTrue(has_account_number_pattern("ING 1234567890"))

    def test_seven_to_nine_digit(self):
        self.assertTrue(has_account_number_pattern("Giro 1234567"))

    def test_full_iban(self):
        self.assertTrue(has_account_number_pattern("NL02ABNA0123456789"))

    def test_email(self):
        self.assertTrue(has_account_number_pattern("paypal user@host.com"))

    def test_no_pattern(self):
        self.assertFalse(has_account_number_pattern("Algemene kosten"))


class TestIdentifyBankName(unittest.TestCase):
    def test_triodos(self):
        self.assertEqual(identify_bank_name("Triodos"), "Triodos Bank")

    def test_ing(self):
        self.assertEqual(identify_bank_name("ING zakelijk"), "ING Bank")

    def test_rabo(self):
        self.assertEqual(identify_bank_name("Rabobank"), "Rabobank")

    def test_unknown_returns_original(self):
        self.assertEqual(identify_bank_name("Mystery Co"), "Mystery Co")


class TestIdentifyBankNameEnhanced(unittest.TestCase):
    def test_knab_standalone(self):
        self.assertEqual(identify_bank_name_enhanced("Knab spaargeld"), "Knab")

    def test_bng(self):
        self.assertEqual(identify_bank_name_enhanced("BNG saldo"), "BNG Bank")

    def test_extracts_first_part_with_bank_word(self):
        # No known pattern, but first part contains "bank"
        self.assertEqual(identify_bank_name_enhanced("Mijn Bank Speciaal - 1234567890"), "Mijn Bank Speciaal")

    def test_default_unknown(self):
        self.assertEqual(identify_bank_name_enhanced("Donaties direct"), "Unknown Bank")

    def test_rekening_substring_does_not_misclassify_as_ing(self):
        # Guards the existing word-boundary behavior: "betaalrekening" contains the
        # substring "ing", which under naive substring matching would hit the
        # "ing" -> "ING Bank" pattern and misclassify a Knab account. _matches_bank_keyword
        # requires "ing" to start a word, so the specific "knab" keyword wins instead.
        # A regression to substring matching would break this.
        # eboekhouden_coa_import.py (identify_bank_name_enhanced + _matches_bank_keyword).
        self.assertEqual(identify_bank_name_enhanced("Knab betaalrekening"), "Knab")
        # A genuine ING name still resolves to ING Bank.
        self.assertEqual(identify_bank_name_enhanced("ING betaalrekening"), "ING Bank")


class TestIdentifyBankCode(unittest.TestCase):
    def test_triodos(self):
        self.assertEqual(identify_bank_code_from_name("Triodos Bank"), "TRIO")

    def test_ing(self):
        self.assertEqual(identify_bank_code_from_name("ING Bank"), "INGB")

    def test_unknown_returns_none(self):
        self.assertIsNone(identify_bank_code_from_name("Mystery Bank"))


class TestGenerateDutchIban(unittest.TestCase):
    """generate_dutch_iban: MOD-97 check-digit IBAN construction."""

    def test_structure_and_length(self):
        iban = generate_dutch_iban("0417164300", "TRIO")
        self.assertTrue(iban.startswith("NL"))
        self.assertIn("TRIO", iban)
        # NL + 2 check + 4 bank + 10 account = 18 chars
        self.assertEqual(len(iban), 18)

    def test_check_digits_valid_mod97(self):
        # A correctly-generated IBAN satisfies the MOD-97 == 1 rule
        iban = generate_dutch_iban("1234567890", "INGB")
        rearranged = iban[4:] + iban[:4]
        numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
        self.assertEqual(int(numeric) % 97, 1)

    def test_pads_short_account_number(self):
        iban = generate_dutch_iban("12345", "RABO")
        # Account portion should be zero-padded to 10 digits
        self.assertTrue(iban.endswith("0000012345"))

    def test_strips_dots(self):
        # "19.83.96.716" -> "198396716" (9 digits) -> zero-padded to "0198396716"
        iban = generate_dutch_iban("19.83.96.716", "TRIO")
        self.assertEqual(len(iban), 18)
        self.assertTrue(iban.endswith("0198396716"))


class TestGenerateIbanIfPossible(unittest.TestCase):
    def test_known_bank_returns_iban(self):
        iban = generate_iban_if_possible("1234567890", "Triodos Bank")
        self.assertIsNotNone(iban)
        self.assertTrue(iban.startswith("NL"))
        self.assertIn("TRIO", iban)

    def test_unknown_bank_returns_none(self):
        self.assertIsNone(generate_iban_if_possible("1234567890", "Mystery Bank"))


class TestExtractBankInfoFromAccountName(unittest.TestCase):
    """extract_bank_info_from_account_name: the central parser."""

    def test_triodos_full(self):
        info = extract_bank_info_from_account_name("Triodos - 19.83.96.716 - Algemeen")
        self.assertEqual(info["account_number"], "19.83.96.716")
        self.assertEqual(info["bank_name"], "Triodos Bank")
        self.assertEqual(info["description"], "Algemeen")

    def test_ing_simple(self):
        info = extract_bank_info_from_account_name("ING - 123456789")
        self.assertEqual(info["account_number"], "123456789")
        self.assertEqual(info["bank_name"], "ING Bank")

    def test_paypal_email_becomes_account_number(self):
        info = extract_bank_info_from_account_name("PayPal - info@veganisme.org")
        self.assertEqual(info["bank_name"], "PayPal")
        self.assertEqual(info["account_holder"], "info@veganisme.org")
        self.assertEqual(info["account_number"], "info@veganisme.org")

    def test_iban_extracted(self):
        info = extract_bank_info_from_account_name("ABN - NL02ABNA0123456789")
        self.assertEqual(info["iban"], "NL02ABNA0123456789")
        # account number = last 10 digits of IBAN
        self.assertEqual(info["account_number"], "0123456789")

    def test_spaarrekening_description(self):
        info = extract_bank_info_from_account_name("Triodos Spaarrekening - 1234567890")
        self.assertIn("Spaarrekening", info["description"])

    def test_betaalrekening_description(self):
        info = extract_bank_info_from_account_name("ING Betaalrekening - 1234567890")
        self.assertIn("Betaalrekening", info["description"])

    def test_iban_generated_when_possible(self):
        # Known bank + account number but no IBAN in name => IBAN is synthesized
        info = extract_bank_info_from_account_name("Triodos - 1234567890")
        self.assertIsNotNone(info["iban"])
        self.assertTrue(info["iban"].startswith("NL"))

    def test_no_account_number_two_parts_description(self):
        # Use a description without "rekening" to avoid the "ing" substring bug.
        info = extract_bank_info_from_account_name("Rabobank - Zakelijk")
        self.assertIsNone(info["account_number"])
        self.assertEqual(info["bank_name"], "Rabobank")
        self.assertEqual(info["description"], "Zakelijk")

    def test_rekening_substring_does_not_misclassify_rabobank_as_ing(self):
        # Guards existing behavior (same root cause as identify_bank_name_enhanced): a
        # Rabobank account named "... rekening" would, under substring matching, hit the
        # "ing" substring and be misidentified as ING Bank. Word-boundary matching
        # resolves it to Rabobank via the "rabo" keyword. eboekhouden_coa_import.py.
        info = extract_bank_info_from_account_name("Rabobank - Zakelijke rekening")
        self.assertEqual(info["bank_name"], "Rabobank")


# ---------------------------------------------------------------------------
# DB-backed reporting helper (no live API)
# ---------------------------------------------------------------------------
class TestValidateBankAccountMappings(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST CoA Validate Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TCVC"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def _persist_account(self, acct_name, account_type, root_type="Asset"):
        parent = frappe.db.get_value(
            "Account",
            {"company": self.company, "root_type": root_type, "is_group": 1},
            "name",
        )
        full = f"{acct_name} - TCVC"
        if frappe.db.exists("Account", full):
            return full
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = self.company
        doc.parent_account = parent
        doc.account_type = account_type
        doc.root_type = root_type
        doc.insert(ignore_permissions=True)
        return doc.name

    def _persist_bank_account_mapped_to(self, gl_account):
        """Create a Bank Account record mapped to an arbitrary GL account.

        The Bank Account ``account`` field is filtered to Bank-type accounts only
        on the client side (a get_query filter), not on the server, so an
        intentionally mismatched mapping can be persisted to exercise the
        validator's account-type check.
        """
        bank = frappe.db.get_value("Bank", {}, "name")
        if not bank:
            bank = frappe.new_doc("Bank")
            bank.bank_name = "EBKH Test Bank"
            bank.insert(ignore_permissions=True)
            bank = bank.name
        ba = frappe.new_doc("Bank Account")
        ba.account_name = "EBKH Mismatched BA"
        ba.bank = bank
        ba.account = gl_account
        ba.company = self.company
        ba.insert(ignore_permissions=True)
        return ba.name

    def test_validate_returns_success_and_structure_for_company(self):
        # Passes an explicit company so we don't depend on settings default.
        result = validate_bank_account_mappings(company=self.company)
        self.assertTrue(result["success"])
        for key in (
            "total_bank_accounts",
            "valid_accounts",
            "issues_found",
            "issues",
            "valid_account_names",
        ):
            self.assertIn(key, result)
        self.assertIsInstance(result["issues"], list)

    def test_non_bank_type_mapping_reported_as_issue(self):
        # Map a Bank Account to a Receivable GL account; the validator must flag
        # the wrong account_type (product eboekhouden_coa_import.py ~L749-754).
        recv = self._persist_account("EBKH CoA Recv", "Receivable")
        self.assertEqual(frappe.db.get_value("Account", recv, "account_type"), "Receivable")
        ba_name = self._persist_bank_account_mapped_to(recv)

        result = validate_bank_account_mappings(company=self.company)
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["issues_found"], 1)

        ours = [i for i in result["issues"] if i["bank_account"] == ba_name]
        self.assertTrue(ours, msg=f"seeded bank account not reported: {result['issues']}")
        self.assertIn(
            "Chart of Accounts account should be type 'Bank', got 'Receivable'",
            ours[0]["issues"],
        )
        # A genuinely mismapped account must NOT be counted as valid.
        self.assertNotIn(ba_name, result["valid_account_names"])


# ---------------------------------------------------------------------------
# DB-backed bank creation / discovery flow (no live API)
# ---------------------------------------------------------------------------
class _BankFlowBase(EnhancedTestCase):
    """Dedicated company + a Bank-type CoA leaf account whose name encodes a
    Triodos account number, so the discovery/creation flow has real data."""

    COMPANY = "TEST CoA BankFlow Co"
    ABBR = "TCBF"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_company()
        cls.bank_account_label = "Triodos - 19.83.96.716 - Algemeen"
        cls.bank_gl_account = cls._persist_bank_gl_account(cls.bank_account_label)

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
    def _persist_bank_gl_account(cls, account_name):
        full = f"{account_name} - {cls.ABBR}"
        if frappe.db.exists("Account", full):
            return full
        parent = frappe.db.get_value(
            "Account", {"company": cls.COMPANY, "root_type": "Asset", "is_group": 1}, "name"
        )
        doc = frappe.new_doc("Account")
        doc.account_name = account_name
        doc.company = cls.COMPANY
        doc.parent_account = parent
        doc.account_type = "Bank"
        doc.root_type = "Asset"
        doc.is_group = 0
        doc.insert(ignore_permissions=True)
        return doc.name

    def _insert_account(self, acct_name, account_type, root_type="Asset"):
        full = f"{acct_name} - {self.ABBR}"
        if frappe.db.exists("Account", full):
            return full
        parent = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": root_type, "is_group": 1}, "name"
        )
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = self.company
        doc.parent_account = parent
        doc.account_type = account_type
        doc.root_type = root_type
        doc.is_group = 0
        doc.insert(ignore_permissions=True)
        return doc.name

    def _insert_bank_account_mapped_to(self, account_name, label):
        bank = frappe.db.get_value("Bank", {}, "name") or get_or_create_bank({"bank_name": "Unknown Bank"})
        ba = frappe.new_doc("Bank Account")
        ba.account_name = label
        ba.bank = bank
        ba.account = account_name
        ba.company = self.company
        ba.insert(ignore_permissions=True)
        frappe.db.commit()
        return ba.name


class TestGetOrCreateBank(EnhancedTestCase):
    def test_creates_bank_with_swift_for_triodos(self):
        # Remove any pre-existing Triodos Bank so we exercise the create branch.
        frappe.db.delete("Bank", {"bank_name": "Triodos Bank"})
        frappe.db.commit()
        name = get_or_create_bank({"bank_name": "Triodos Bank"})
        self.assertEqual(name, "Triodos Bank")
        self.assertEqual(frappe.db.get_value("Bank", name, "swift_number"), "TRIONL2U")

    def test_idempotent_returns_existing(self):
        first = get_or_create_bank({"bank_name": "ING Bank"})
        second = get_or_create_bank({"bank_name": "ING Bank"})
        self.assertEqual(first, second)
        self.assertEqual(frappe.db.count("Bank", {"bank_name": "ING Bank"}), 1)

    def test_missing_bank_name_defaults_to_unknown(self):
        name = get_or_create_bank({})
        self.assertEqual(name, "Unknown Bank")
        self.assertTrue(frappe.db.exists("Bank", "Unknown Bank"))


class TestCreateBankAccountRecord(_BankFlowBase):
    def test_creates_bank_account_mapped_to_coa(self):
        account_doc = frappe.get_doc("Account", self.bank_gl_account)
        bank_info = extract_bank_info_from_account_name(self.bank_account_label)
        bank_name = get_or_create_bank(bank_info)

        # Clear any prior Bank Account on this GL account so we hit the create path.
        for existing in frappe.get_all(
            "Bank Account", filters={"account": self.bank_gl_account}, pluck="name"
        ):
            frappe.delete_doc("Bank Account", existing, force=True, ignore_permissions=True)
        frappe.db.commit()

        created = create_bank_account_record(
            account=account_doc, bank_name=bank_name, bank_info=bank_info, company=self.company
        )
        self.assertIsNotNone(created)
        # The new Bank Account must be mapped to the CoA account and carry currency.
        self.assertEqual(frappe.db.get_value("Bank Account", created, "account"), self.bank_gl_account)
        self.assertEqual(frappe.db.get_value("Bank Account", created, "company"), self.company)
        self.assertEqual(frappe.db.get_value("Bank Account", created, "bank_account_no"), "19.83.96.716")

    def test_returns_none_for_nonexistent_coa_account(self):
        # account.name points at a CoA account that does not exist -> guarded None.
        fake = frappe._dict({"name": "NO-SUCH-ACCOUNT - TCBF", "account_name": "Ghost"})
        result = create_bank_account_record(
            account=fake,
            bank_name="Unknown Bank",
            bank_info={"bank_name": "Unknown Bank"},
            company=self.company,
        )
        self.assertIsNone(result)


class TestFindAndDiscoverBankAccounts(_BankFlowBase):
    def test_find_bank_accounts_in_coa_detects_seeded_account(self):
        # find_bank_accounts_in_coa() reads its company from E-Boekhouden Settings.
        result = _setup_find_in_coa(self.company)
        self.assertTrue(result["success"])
        names = [a["account"]["name"] for a in result["accounts"]]
        self.assertIn(self.bank_gl_account, names)

    def test_discover_missing_bank_accounts(self):
        # Ensure the seeded Bank GL account has NO Bank Account record -> reported missing.
        for existing in frappe.get_all(
            "Bank Account", filters={"account": self.bank_gl_account}, pluck="name"
        ):
            frappe.delete_doc("Bank Account", existing, force=True, ignore_permissions=True)
        frappe.db.commit()

        result = discover_missing_bank_accounts(company=self.company)
        self.assertTrue(result["success"])
        missing_names = [m["account"] for m in result["missing_bank_accounts"]]
        self.assertIn(self.bank_gl_account, missing_names)

    def test_create_missing_bank_accounts_then_idempotent(self):
        for existing in frappe.get_all(
            "Bank Account", filters={"account": self.bank_gl_account}, pluck="name"
        ):
            frappe.delete_doc("Bank Account", existing, force=True, ignore_permissions=True)
        frappe.db.commit()

        result = create_missing_bank_accounts(company=self.company)
        self.assertTrue(result["success"])
        # The seeded account must now have a Bank Account record.
        self.assertTrue(frappe.db.exists("Bank Account", {"account": self.bank_gl_account}))
        created_names = [c["account"] for c in result["created_accounts"]]
        self.assertIn(self.bank_gl_account, created_names)

        # Re-running discovery must no longer report it missing.
        again = discover_missing_bank_accounts(company=self.company)
        self.assertNotIn(self.bank_gl_account, [m["account"] for m in again["missing_bank_accounts"]])


class TestFixBankAccountMappings(_BankFlowBase):
    def test_fixes_non_bank_account_type(self):
        # Seed a Receivable GL account and map a Bank Account to it (wrong type),
        # then assert fix_bank_account_mappings flips it to type 'Bank'.
        recv_name = self._insert_account("BankFlow Recv", "Receivable", "Asset")
        self._insert_bank_account_mapped_to(recv_name, "BankFlow Mismatch BA")
        self.assertEqual(frappe.db.get_value("Account", recv_name, "account_type"), "Receivable")

        result = fix_bank_account_mappings(company=self.company)
        self.assertTrue(result["success"])
        # The Receivable account must have been switched to Bank.
        self.assertEqual(frappe.db.get_value("Account", recv_name, "account_type"), "Bank")
        fixed_accounts = [f["account"] for f in result["fixed_accounts"]]
        self.assertIn(recv_name, fixed_accounts)


class TestCleanupDuplicateBankAccounts(_BankFlowBase):
    def _insert_unmapped_bank_account(self, label):
        bank = frappe.db.get_value("Bank", {}, "name") or get_or_create_bank({"bank_name": "Unknown Bank"})
        ba = frappe.new_doc("Bank Account")
        ba.account_name = label
        ba.bank = bank
        ba.company = self.company
        ba.insert(ignore_permissions=True)
        frappe.db.commit()
        return ba.name

    def test_deletes_problematic_named_accounts(self):
        ba_name = self._insert_unmapped_bank_account("Unknown Bank - None")
        self.assertTrue(frappe.db.exists("Bank Account", ba_name))

        result = cleanup_duplicate_bank_accounts()
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["deleted_count"], 1)
        self.assertFalse(frappe.db.exists("Bank Account", ba_name))


def _setup_find_in_coa(company):
    """find_bank_accounts_in_coa reads company from E-Boekhouden Settings, so set
    it temporarily for the duration of the call.

    Uses non-committed ``set_single_value`` rather than ``settings.save()`` to
    configure the Single: production reads ``default_company`` via
    ``frappe.get_single`` in the same transaction, the change rolls back at test
    end, and it bypasses full-document validation (avoiding the shard-race
    ``MandatoryError`` when a prior test has emptied the mandatory ``api_token``)."""
    prev = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")
    frappe.db.set_single_value("E-Boekhouden Settings", "default_company", company)
    try:
        return find_bank_accounts_in_coa()
    finally:
        frappe.db.set_single_value("E-Boekhouden Settings", "default_company", prev)


if __name__ == "__main__":
    unittest.main()
