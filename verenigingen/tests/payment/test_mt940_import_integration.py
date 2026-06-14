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

    def test_iban_mismatch_rejected(self):
        """A statement IBAN that does not match the Bank Account must be refused.

        (Only triggers when the library populates account_identification; the
        samples do not, so this asserts the import still succeeds without a
        false-positive mismatch.)
        """
        result = M.process_mt940_document(S.SEPA_INCOMING_CREDIT, self.bank_account, self.company)
        self.assertTrue(result["success"])

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
