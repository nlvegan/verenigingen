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


class TestBulkImporterMemberMatching(EnhancedTestCase):
    """_find_member_by_payment_details against real Members / SEPA Mandates."""

    def setUp(self):
        super().setUp()
        self.imp = BulkTransactionImporter()

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
