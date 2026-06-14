"""
End-to-end integration tests for the MT940 import pipeline.

Drives process_mt940_document() with real MT940 statement text against a real
Company + Bank Account on the test site, then asserts that real Bank
Transaction documents are created with the right amounts, directions,
descriptions and SEPA-derived references. No mocking - this is the supported
production import path.

Covers verenigingen/verenigingen_payments/utils/mt940_import.py:
    - process_mt940_document (parse, dedup, savepoint, date range)
    - create_enhanced_bank_transaction_from_mt940 (deposit/withdrawal split,
      description cleaning, transaction_id, party fields)
    - import_mt940_file (whitelisted wrapper: base64 decode, validation)
    - find_party_by_iban_or_name (Member-by-IBAN matching)
    - batch_preload_party_lookups
"""

import frappe

from verenigingen.tests.fixtures import mt940_sample_statements as S
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import mt940_import as M


class TestMT940ImportIntegration(EnhancedTestCase):
    """Full MT940 import against real Bank Account / Company."""

    def setUp(self):
        super().setUp()
        self.company = frappe.get_list("Company", limit=1)[0].name
        self.bank_account = self._ensure_bank_account()
        # The MT940 import path commits mid-transaction (the API security audit
        # logger commits unconditionally), so Bank Transactions it creates survive
        # FrappeTestCase's per-test rollback. Scrub any committed survivors from a
        # previous test in this class before each test so counts are deterministic.
        self._cleanup_bank_transactions()

    def _ensure_bank_account(self):
        """Create (idempotently) a Bank Account whose IBAN matches the samples."""
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        bank = get_or_create_unknown_bank()
        iban = "NL02ABNA0123456789"
        existing = frappe.db.get_value("Bank Account", {"bank_account_no": iban}, "name")
        if existing:
            return existing
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"MT940 Test Account {self.uid}"
        ba.bank = bank
        ba.company = self.company
        ba.bank_account_no = iban
        ba.iban = iban
        ba.insert(ignore_permissions=True)
        self.created_records.append(("Bank Account", ba.name))
        return ba.name

    def _cleanup_bank_transactions(self):
        """Remove any (committed) Bank Transactions for the test bank account."""
        for bt in frappe.get_all(
            "Bank Transaction", filters={"bank_account": self.bank_account}, fields=["name", "docstatus"]
        ):
            doc = frappe.get_doc("Bank Transaction", bt.name)
            if doc.docstatus == 1:
                doc.cancel()
            doc.delete(ignore_permissions=True)
        # Commit the cleanup because the rows being removed were themselves committed
        # by the import's nested audit-log commit and would otherwise reappear.
        frappe.db.commit()

    def tearDown(self):
        self._cleanup_bank_transactions()
        super().tearDown()

    # ------------------------------------------------------------------ #

    def test_single_incoming_credit_creates_deposit(self):
        result = M.process_mt940_document(S.SEPA_INCOMING_CREDIT, self.bank_account, self.company)
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertEqual(result["transactions_created"], 1)

        bts = frappe.get_all(
            "Bank Transaction",
            filters={"bank_account": self.bank_account},
            fields=["name", "deposit", "withdrawal", "description", "reference_number", "bank_party_iban"],
        )
        self.assertEqual(len(bts), 1)
        bt = bts[0]
        self.assertEqual(float(bt.deposit), 150.00)
        self.assertEqual(float(bt.withdrawal), 0.0)
        self.assertEqual(bt.reference_number, "INV-2024-0001")
        self.assertEqual(bt.bank_party_iban, "NL44RABO0123456789")
        self.assertIn("Contributie", bt.description)

    def test_single_outgoing_debit_creates_withdrawal(self):
        result = M.process_mt940_document(S.SEPA_OUTGOING_DEBIT, self.bank_account, self.company)
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertEqual(result["transactions_created"], 1)

        bt = frappe.get_all(
            "Bank Transaction",
            filters={"bank_account": self.bank_account},
            fields=["deposit", "withdrawal", "reference_number"],
        )[0]
        self.assertEqual(float(bt.withdrawal), 75.50)
        self.assertEqual(float(bt.deposit), 0.0)
        self.assertEqual(bt.reference_number, "E2E-9988")

    def test_multi_transaction_statement_creates_all(self):
        result = M.process_mt940_document(S.MULTI_TRANSACTION, self.bank_account, self.company)
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertEqual(result["transactions_created"], 3)
        self.assertEqual(frappe.db.count("Bank Transaction", {"bank_account": self.bank_account}), 3)

    def test_duplicate_within_import_skipped(self):
        """Two byte-identical entries should produce a single Bank Transaction."""
        result = M.process_mt940_document(S.DUPLICATE_ENTRIES, self.bank_account, self.company)
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertEqual(result["transactions_created"], 1)

    def test_reimport_skips_already_existing(self):
        """Re-running the same import must not create duplicate Bank Transactions."""
        first = M.process_mt940_document(S.SEPA_INCOMING_CREDIT, self.bank_account, self.company)
        self.assertEqual(first["transactions_created"], 1)

        second = M.process_mt940_document(S.SEPA_INCOMING_CREDIT, self.bank_account, self.company)
        self.assertTrue(second["success"])
        self.assertEqual(second["transactions_created"], 0)
        self.assertEqual(second["transactions_skipped"], 1)
        self.assertEqual(frappe.db.count("Bank Transaction", {"bank_account": self.bank_account}), 1)

    def test_matching_statement_iban_imports_successfully(self):
        """When the statement's :25: account identification matches the selected
        Bank Account's IBAN, the guard passes and the import proceeds. The sample's
        container carries :25: NL02ABNA0123456789, equal to self.bank_account's
        IBAN, so this proves the guard ALLOWS a matching statement (not merely that
        the field was absent)."""
        result = M.process_mt940_document(S.SEPA_INCOMING_CREDIT, self.bank_account, self.company)
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertEqual(result["transactions_created"], 1)

    def test_statement_iban_mismatch_rejected(self):
        """A statement whose :25: account identification differs from the selected
        Bank Account's IBAN must be rejected before any Bank Transaction is created.

        Uses a REAL sample (its container :25: is NL02ABNA0123456789) imported
        against a DIFFERENT Bank Account (NL91ABNA0417164300), so the guard reads
        the genuine library-produced account identification — no monkeypatching of
        the parser. This is the path mt940_import.py validates before the import
        savepoint.
        """
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        other_iban = "NL91ABNA0417164300"  # != the sample's :25: NL02ABNA0123456789
        other_ba = frappe.new_doc("Bank Account")
        other_ba.account_name = f"MT940 Mismatch Account {self.uid}"
        other_ba.bank = get_or_create_unknown_bank()
        other_ba.company = self.company
        other_ba.bank_account_no = other_iban
        other_ba.iban = other_iban
        other_ba.insert()
        self.created_records.append(("Bank Account", other_ba.name))

        result = M.process_mt940_document(S.SEPA_INCOMING_CREDIT, other_ba.name, self.company)

        self.assertFalse(result["success"])
        self.assertIn("IBAN mismatch", result["message"])
        self.assertIn("NL02ABNA0123456789", result["message"])  # the statement IBAN
        # Rejected before any row is written for the mismatched account.
        self.assertEqual(frappe.db.count("Bank Transaction", {"bank_account": other_ba.name}), 0)

    def test_internal_transfer_not_linked_to_external_party(self):
        """An ING internal-account-reference (L+digits) counterparty that matches a
        company-owned Bank Account is treated as an internal transfer: no external
        party is set and the description is flagged as an internal transfer.

        Drives Priority-0 is_internal_transfer in find_party_by_iban_or_name via
        the real ING_INTERNAL_TRANSFER sample. The /CNTP/L96981341/ ref is stored
        as counterparty_account_ref; we seed a company Bank Account whose
        bank_account_no is that reference so find_own_bank_account_by_reference
        matches it.
        """
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        internal_ref = "L96981341"  # matches /CNTP/L96981341/ in ING_INTERNAL_TRANSFER
        own_account = frappe.new_doc("Bank Account")
        own_account.account_name = f"Spaarrekening {self.uid}"
        own_account.bank = get_or_create_unknown_bank()
        own_account.company = self.company
        own_account.bank_account_no = internal_ref
        # find_own_bank_account_by_reference matches on (is_company_account=1 OR
        # company=<company>); matching by company avoids the GL-account that
        # is_company_account=1 would make mandatory.
        own_account.insert()
        self.created_records.append(("Bank Account", own_account.name))

        result = M.process_mt940_document(S.ING_INTERNAL_TRANSFER, self.bank_account, self.company)
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertEqual(result["transactions_created"], 1)

        bt = frappe.get_all(
            "Bank Transaction",
            filters={"bank_account": self.bank_account},
            fields=["name", "party", "party_type", "description", "withdrawal"],
        )[0]
        # Internal transfer: no external Customer/Supplier party assigned.
        self.assertFalse(bt.party)
        self.assertFalse(bt.party_type)
        # And the description is marked as an internal transfer.
        self.assertIn("Internal transfer", bt.description)
        self.assertEqual(float(bt.withdrawal), 500.00)

    def test_internal_transfer_party_lookup_priority_zero(self):
        """Unit-level assertion on find_party_by_iban_or_name's Priority-0 branch.

        Directly verifies that an internal_account_ref matching a company Bank
        Account returns is_internal_transfer=True with no party, independent of
        the full import pipeline.
        """
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        internal_ref = "L55500001"
        own_account = frappe.new_doc("Bank Account")
        own_account.account_name = f"Internal Savings {self.uid}"
        own_account.bank = get_or_create_unknown_bank()
        own_account.company = self.company
        own_account.bank_account_no = internal_ref
        own_account.insert()
        self.created_records.append(("Bank Account", own_account.name))

        result = M.find_party_by_iban_or_name(
            iban="",
            counterparty_name="Spaarrekening",
            is_incoming=False,
            internal_account_ref=internal_ref,
            company=self.company,
        )
        self.assertTrue(result["is_internal_transfer"])
        self.assertEqual(result["internal_bank_account"], own_account.name)
        self.assertIsNone(result["party"])

    def test_import_mt940_file_wrapper_decodes_base64(self):
        result = M.import_mt940_file(self.bank_account, S.as_base64(S.SEPA_INCOMING_CREDIT))
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertEqual(result["transactions_created"], 1)

    def test_import_mt940_file_missing_bank_account(self):
        result = M.import_mt940_file("", S.as_base64(S.SEPA_INCOMING_CREDIT))
        self.assertFalse(result["success"])

    def test_import_mt940_file_bad_base64(self):
        result = M.import_mt940_file(self.bank_account, "@@not base64@@")
        self.assertFalse(result["success"])


class TestMT940PartyMatching(EnhancedTestCase):
    """find_party_by_iban_or_name + batch_preload_party_lookups against real data."""

    def setUp(self):
        super().setUp()
        self.company = frappe.get_list("Company", limit=1)[0].name

    def _create_linked_customer(self, member_name):
        """Factory helper: create a Customer and link it to the given Member.

        Runs as Administrator (set by EnhancedTestCase.setUp) so no permission
        bypass is needed.
        """
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"MT940 Payer {self.uid}"
        customer.customer_type = "Individual"
        customer.insert()
        self.created_records.append(("Customer", customer.name))
        frappe.db.set_value("Member", member_name, "customer", customer.name)
        return customer

    def test_member_matched_by_iban(self):
        """A Member with a linked Customer and matching IBAN is found by IBAN."""
        iban = "NL21INGB0987654321"
        member = self.create_test_member(
            first_name="Mt940",
            last_name=f"Payer{self.uid}",
            email=f"mt940.payer.{self.uid}@example.com",
            iban=iban,
        )
        # Ensure the member has a linked Customer (party matching requires it).
        customer = self._create_linked_customer(member.name)

        result = M.find_party_by_iban_or_name(
            iban=iban,
            counterparty_name="Mt940 Payer",
            is_incoming=True,
            company=self.company,
        )
        self.assertEqual(result["party_type"], "Customer")
        self.assertEqual(result["party"], customer.name)
        self.assertFalse(result["is_internal_transfer"])

    def test_batch_preload_returns_structure(self):
        result = M.batch_preload_party_lookups(["NL00BANK0000000000"])
        self.assertIn("member_by_iban", result)
        self.assertIn("mandate_by_iban", result)
        self.assertIn("bank_account_by_iban", result)

    def test_batch_preload_empty_list(self):
        result = M.batch_preload_party_lookups([])
        self.assertEqual(result["member_by_iban"], {})

    def test_no_iban_no_name_returns_empty_match(self):
        result = M.find_party_by_iban_or_name(
            iban="", counterparty_name="", is_incoming=True, company=self.company
        )
        self.assertIsNone(result["party"])
        self.assertIsNone(result["party_type"])
