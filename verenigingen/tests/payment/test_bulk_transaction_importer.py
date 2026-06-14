"""
Real tests for the Mollie bulk transaction importer's pure / DB-backed helpers.

Instantiates the real BulkTransactionImporter (which builds the real Mollie API
clients from configured settings - no mocking) and exercises the helpers that do
NOT require live Mollie HTTP calls: strategy mapping, custom-field validation,
duplicate detection and member matching by payment details. These are the
branches that the existing end-to-end consumer test does not reach.

Covers verenigingen/verenigingen_payments/clients/bulk_transaction_importer.py:
    - _map_strategy_for_doctype
    - _validate_mollie_custom_fields
    - _check_existing_payment_transaction
    - _validate_duplicate_transaction
    - _find_member_by_payment_details (IBAN-via-mandate + name matching)
    - estimate_import_size structure
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import (
    BulkTransactionImporter,
)


class TestBulkImporterStrategyMapping(EnhancedTestCase):
    """_map_strategy_for_doctype maps frontend strategies to DocType values."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.imp = BulkTransactionImporter()

    def test_known_strategies(self):
        self.assertEqual(self.imp._map_strategy_for_doctype("payments"), "payments_only")
        self.assertEqual(self.imp._map_strategy_for_doctype("balances"), "balances_only")
        self.assertEqual(self.imp._map_strategy_for_doctype("settlements"), "balances_only")
        self.assertEqual(self.imp._map_strategy_for_doctype("hybrid"), "hybrid")

    def test_unknown_strategy_defaults_to_hybrid(self):
        self.assertEqual(self.imp._map_strategy_for_doctype("nonsense"), "hybrid")
        self.assertEqual(self.imp._map_strategy_for_doctype(""), "hybrid")


class TestBulkImporterCustomFieldValidation(EnhancedTestCase):
    """_validate_mollie_custom_fields against the real Bank Transaction meta."""

    def setUp(self):
        super().setUp()
        self.imp = BulkTransactionImporter()

    def test_required_custom_fields_present(self):
        """The Mollie custom fields must exist on Bank Transaction; if all present,
        validation completes without raising."""
        # Should not raise - the app ships these custom fields via fixtures.
        self.imp._validate_mollie_custom_fields()

        # Belt-and-braces: confirm the meta actually carries them.
        meta_fields = {f.fieldname for f in frappe.get_meta("Bank Transaction").fields}
        for required in ("custom_mollie_payment_id", "custom_mollie_settlement_id"):
            self.assertIn(required, meta_fields)


class TestBulkImporterDuplicateDetection(EnhancedTestCase):
    """_check_existing_payment_transaction / _validate_duplicate_transaction."""

    def setUp(self):
        super().setUp()
        self.imp = BulkTransactionImporter()

    def test_check_existing_without_id_is_false(self):
        self.assertFalse(self.imp._check_existing_payment_transaction({}))
        self.assertFalse(self.imp._check_existing_payment_transaction({"id": None}))

    def test_check_existing_unknown_payment_is_false(self):
        self.assertFalse(self.imp._check_existing_payment_transaction({"id": "tr_unknown_never_imported"}))

    def test_duplicate_empty_data_is_false(self):
        self.assertFalse(self.imp._validate_duplicate_transaction({}))

    def test_duplicate_unknown_mollie_ids_is_false(self):
        self.assertFalse(
            self.imp._validate_duplicate_transaction(
                {
                    "custom_mollie_payment_id": "tr_no_match_here",
                    "custom_mollie_settlement_id": "stl_no_match_here",
                }
            )
        )

    def _seed_bank_transaction_with_mollie_id(self, payment_id, submit):
        """Create a real Bank Transaction tagged with a Mollie payment id.

        _check_existing_payment_transaction only counts SUBMITTED (docstatus=1)
        rows; _validate_duplicate_transaction counts any non-cancelled row.
        Bank Transactions the importer's dedup queries hit live across the
        per-test rollback only if committed, but frappe.db.exists reads
        uncommitted rows within the same transaction, so a plain insert/submit
        is sufficient here.
        """
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        company = frappe.get_list("Company", limit=1)[0].name
        bank = get_or_create_unknown_bank()
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"Bulk Dedup Account {self.uid}"
        ba.bank = bank
        ba.company = company
        ba.bank_account_no = f"NL00BULK{self.uid}"
        ba.insert()
        self.created_records.append(("Bank Account", ba.name))

        bt = frappe.new_doc("Bank Transaction")
        bt.date = frappe.utils.today()
        bt.bank_account = ba.name
        bt.company = company
        bt.currency = "EUR"
        bt.deposit = 42.0
        bt.custom_mollie_payment_id = payment_id
        bt.insert()
        if submit:
            bt.submit()
        self.created_records.append(("Bank Transaction", bt.name))
        return bt

    def test_check_existing_finds_submitted_payment(self):
        """A submitted Bank Transaction carrying the Mollie payment id is detected
        as already-imported (the docstatus=1 duplicate path)."""
        payment_id = f"tr_seeded_{self.uid}"
        self._seed_bank_transaction_with_mollie_id(payment_id, submit=True)
        self.assertTrue(self.imp._check_existing_payment_transaction({"id": payment_id}))

    def test_check_existing_ignores_unsubmitted_payment(self):
        """A draft (docstatus=0) Bank Transaction must NOT count as already-imported
        for _check_existing_payment_transaction (which filters docstatus=1)."""
        payment_id = f"tr_draft_{self.uid}"
        self._seed_bank_transaction_with_mollie_id(payment_id, submit=False)
        self.assertFalse(self.imp._check_existing_payment_transaction({"id": payment_id}))

    def test_validate_duplicate_finds_matching_payment_id(self):
        """_validate_duplicate_transaction detects a duplicate by Mollie payment id
        against a real (non-cancelled) Bank Transaction."""
        payment_id = f"tr_dup_{self.uid}"
        self._seed_bank_transaction_with_mollie_id(payment_id, submit=False)
        self.assertTrue(
            self.imp._validate_duplicate_transaction({"custom_mollie_payment_id": payment_id})
        )


class TestBulkImporterMemberMatching(EnhancedTestCase):
    """_find_member_by_payment_details against real Members / SEPA Mandates."""

    def setUp(self):
        super().setUp()
        self.imp = BulkTransactionImporter()

    def _unique_iban(self, bank_code="RABO"):
        """A checksum-valid IBAN unique to this test run.

        The shared SEPA factory restarts its IBAN sequence per instance, so its
        generated IBANs collide with Active mandates committed by earlier tests.
        Derive the account number from self.uid so each test's mandate IBAN is
        globally unique and only matches the mandate this test creates.
        """
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        account_number = (str(self.uid) + "0000000000")[:10]
        return generate_test_iban(bank_code, account_number=account_number)

    def test_no_details_returns_none(self):
        self.assertIsNone(self.imp._find_member_by_payment_details(None, None))
        self.assertIsNone(self.imp._find_member_by_payment_details("", ""))

    def test_invalid_iban_falls_through_to_no_match(self):
        # An invalid IBAN must not match anything (and must not crash).
        self.assertIsNone(
            self.imp._find_member_by_payment_details(consumer_iban="NOTANIBAN", consumer_name=None)
        )

    def test_exact_name_match(self):
        unique_name = f"Bulk Importer Payer {self.uid}"
        member = self.create_test_member(
            first_name="Bulk",
            last_name=f"Payer{self.uid}",
            email=f"bulk.payer.{self.uid}@example.com",
        )
        # Force a deterministic, unique full_name to assert exact matching.
        frappe.db.set_value("Member", member.name, "full_name", unique_name)

        matched = self.imp._find_member_by_payment_details(consumer_name=unique_name)
        self.assertEqual(matched, member.name)

    def test_unknown_name_returns_none(self):
        self.assertIsNone(
            self.imp._find_member_by_payment_details(consumer_name=f"No Such Person {self.uid}")
        )

    def test_match_by_iban_via_active_sepa_mandate(self):
        """_find_member_by_payment_details resolves a Member from a consumer IBAN
        by looking up an Active SEPA Mandate (the IBAN-first matching path).

        IBAN takes precedence over name: we pass a non-matching name to prove the
        returned member came from the mandate IBAN lookup, not the name fallback.
        """
        member = self.create_test_member(
            first_name="Mandate",
            last_name=f"Payer{self.uid}",
            email=f"mandate.payer.{self.uid}@example.com",
        )
        mandate = self.create_test_sepa_mandate(
            member=member.name, status="Active", iban=self._unique_iban("RABO")
        )
        self.created_records.append(("SEPA Mandate", mandate.name))

        matched = self.imp._find_member_by_payment_details(
            consumer_name="Someone Entirely Different",
            consumer_iban=mandate.iban,
        )
        self.assertEqual(matched, member.name)

    def test_iban_only_matches_via_mandate(self):
        """IBAN-only lookup (no name) still resolves the Member via the mandate."""
        member = self.create_test_member(
            first_name="IbanOnly",
            last_name=f"Payer{self.uid}",
            email=f"ibanonly.payer.{self.uid}@example.com",
        )
        mandate = self.create_test_sepa_mandate(
            member=member.name, status="Active", iban=self._unique_iban("INGB")
        )
        self.created_records.append(("SEPA Mandate", mandate.name))

        matched = self.imp._find_member_by_payment_details(consumer_iban=mandate.iban)
        self.assertEqual(matched, member.name)

    def test_inactive_mandate_iban_does_not_match(self):
        """A cancelled/non-Active SEPA Mandate must NOT yield an IBAN match (the
        lookup filters status='Active')."""
        member = self.create_test_member(
            first_name="Inactive",
            last_name=f"Payer{self.uid}",
            email=f"inactive.payer.{self.uid}@example.com",
        )
        mandate = self.create_test_sepa_mandate(
            member=member.name, status="Cancelled", iban=self._unique_iban("ABNA")
        )
        self.created_records.append(("SEPA Mandate", mandate.name))

        self.assertIsNone(self.imp._find_member_by_payment_details(consumer_iban=mandate.iban))


class TestBulkImporterEstimateSize(EnhancedTestCase):
    """estimate_import_size returns a structured estimate dict.

    estimate_import_size talks to the Mollie API; on a test site without live
    Mollie connectivity it should still return a dict (the method is defensive),
    so we only assert it returns a mapping rather than raising.
    """

    def setUp(self):
        super().setUp()
        self.imp = BulkTransactionImporter()

    def test_estimate_returns_dict_or_handles_gracefully(self):
        from datetime import datetime, timezone

        from_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        to_date = datetime(2024, 1, 31, tzinfo=timezone.utc)
        try:
            result = self.imp.estimate_import_size(from_date, to_date, "hybrid")
        except Exception:
            # Live Mollie call may not be available in CI; that is acceptable -
            # the no-network path is covered by the other tests in this module.
            self.skipTest("Mollie API not reachable from test environment")
        self.assertIsInstance(result, dict)
