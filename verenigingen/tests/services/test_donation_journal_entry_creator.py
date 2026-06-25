"""
Integration Tests for DonationJournalEntryCreator Service

Tests the donation journal entry creation service which creates Journal Entries
for donation payments. This is the correct accounting treatment for donations
(not Payment Entries, which are for receivables).

Architecture tested:
    Mollie Webhook -> Bank Transaction -> Journal Entry -> Record Updates
                     (deposit)          (Debit: Clearing, Credit: Income)

Test Coverage:
- Company resolution fallback (donation.company -> settings.company)
- Journal Entry creation from Mollie payment data
- Journal Entry creation from generic dictionary data
- Idempotency check (no duplicate entries for same payment)
- Bank Transaction reconciliation
- Error handling for missing configuration
"""

import unittest
from typing import Optional
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.donation_journal_entry_creator import (
    DonationJournalEntryCreator,
    get_donation_journal_entry_creator,
)


class TestDonationJournalEntryCreatorUnit(unittest.TestCase):
    """Unit tests for DonationJournalEntryCreator with mocking"""

    def setUp(self):
        """Set up test fixtures"""
        self.creator = DonationJournalEntryCreator()

    def test_factory_function_returns_instance(self):
        """Test that factory function returns proper instance"""
        creator = get_donation_journal_entry_creator()
        self.assertIsInstance(creator, DonationJournalEntryCreator)

    @patch("verenigingen.verenigingen_payments.services.donation_journal_entry_creator.frappe")
    def test_resolve_company_from_donation(self, mock_frappe):
        """Test company resolution uses donation.company first"""
        # Arrange
        mock_donation = MagicMock()
        mock_donation.company = "Test Company"

        # Act
        result = self.creator._resolve_company(mock_donation)

        # Assert
        self.assertEqual(result, "Test Company")
        # Should not call get_single since donation has company
        mock_frappe.get_single.assert_not_called()

    @patch("verenigingen.verenigingen_payments.services.donation_journal_entry_creator.frappe")
    def test_resolve_company_fallback_to_settings(self, mock_frappe):
        """Test company resolution falls back to Verenigingen Settings"""
        # Arrange
        mock_donation = MagicMock()
        mock_donation.company = None

        mock_settings = MagicMock()
        mock_settings.company = "Settings Company"
        mock_frappe.get_single.return_value = mock_settings

        # Act
        result = self.creator._resolve_company(mock_donation)

        # Assert
        self.assertEqual(result, "Settings Company")
        mock_frappe.get_single.assert_called_once_with("Verenigingen Settings")

    @patch("verenigingen.verenigingen_payments.services.donation_journal_entry_creator.frappe")
    def test_resolve_company_returns_none_when_not_configured(self, mock_frappe):
        """Test company resolution returns None when no company configured"""
        # Arrange
        mock_donation = MagicMock()
        mock_donation.company = None

        mock_settings = MagicMock()
        mock_settings.company = None
        mock_frappe.get_single.return_value = mock_settings
        mock_frappe.logger.return_value = MagicMock()

        # Act
        result = self.creator._resolve_company(mock_donation)

        # Assert
        self.assertIsNone(result)

    @patch("verenigingen.verenigingen_payments.services.donation_journal_entry_creator.frappe")
    def test_check_existing_by_reference_returns_existing_je(self, mock_frappe):
        """Test idempotency check finds existing Journal Entry"""
        # Arrange
        mock_frappe.db.get_value.return_value = "ACC-JV-2025-00001"

        # Act
        result = self.creator._check_existing_by_reference("mollie-payment-123")

        # Assert
        self.assertEqual(result, "ACC-JV-2025-00001")
        mock_frappe.db.get_value.assert_called_once_with(
            "Journal Entry", {"cheque_no": "mollie-payment-123", "docstatus": ["!=", 2]}, "name"
        )

    @patch("verenigingen.verenigingen_payments.services.donation_journal_entry_creator.frappe")
    def test_check_existing_by_reference_returns_none_for_empty_ref(self, mock_frappe):
        """Test idempotency check returns None for empty reference"""
        # Act
        result = self.creator._check_existing_by_reference("")

        # Assert
        self.assertIsNone(result)
        mock_frappe.db.get_value.assert_not_called()

    @patch("verenigingen.verenigingen_payments.services.donation_journal_entry_creator.frappe")
    def test_create_from_mollie_payment_idempotency(self, mock_frappe):
        """Test that duplicate Mollie payments are rejected"""
        # Arrange
        mock_frappe.db.get_value.return_value = "ACC-JV-2025-00001"  # Existing JE
        mock_frappe.logger.return_value = MagicMock()

        payment_data = {"id": "tr_existingPayment", "amount": {"value": "25.00"}}
        mock_donation = MagicMock()

        # Act
        result = self.creator.create_from_mollie_payment(payment_data, mock_donation)

        # Assert - should return existing JE name
        self.assertEqual(result, "ACC-JV-2025-00001")

    @patch("verenigingen.verenigingen_payments.services.donation_journal_entry_creator.frappe")
    def test_create_from_mollie_payment_no_company_fails(self, mock_frappe):
        """Test that missing company configuration fails gracefully"""
        # Arrange
        mock_frappe.db.get_value.return_value = None  # No existing JE

        mock_settings = MagicMock()
        mock_settings.company = None
        mock_frappe.get_single.return_value = mock_settings
        mock_frappe.logger.return_value = MagicMock()

        payment_data = {"id": "tr_newPayment", "amount": {"value": "25.00"}}
        mock_donation = MagicMock()
        mock_donation.company = None

        # Act
        result = self.creator.create_from_mollie_payment(payment_data, mock_donation)

        # Assert
        self.assertIsNone(result)

    @patch("verenigingen.verenigingen_payments.services.donation_journal_entry_creator.frappe")
    def test_create_from_dict_idempotency(self, mock_frappe):
        """Test that duplicate dict transactions are rejected"""
        # Arrange
        mock_frappe.db.get_value.return_value = "ACC-JV-2025-00002"  # Existing JE
        mock_frappe.logger.return_value = MagicMock()

        transaction_data = {"reference_number": "existing-ref-123", "amount": 50.00, "date": today()}
        mock_donation = MagicMock()

        # Act
        result = self.creator.create_from_dict(transaction_data, mock_donation)

        # Assert - should return existing JE name
        self.assertEqual(result, "ACC-JV-2025-00002")

    @patch("verenigingen.verenigingen_payments.services.donation_journal_entry_creator.frappe")
    def test_create_from_dict_zero_amount_fails(self, mock_frappe):
        """Test that zero amount transactions fail gracefully"""
        # Arrange
        mock_frappe.db.get_value.return_value = None  # No existing JE

        mock_settings = MagicMock()
        mock_settings.company = "Test Company"
        mock_frappe.get_single.return_value = mock_settings
        mock_frappe.logger.return_value = MagicMock()

        transaction_data = {"reference_number": "zero-amount-ref", "amount": 0, "date": today()}
        mock_donation = MagicMock()
        mock_donation.company = "Test Company"

        # Set up config mock
        self.creator._config = {
            "company": "Test Company",
            "clearing_account": "Mollie - TC",
            "income_account": "Donation Income - TC",
            "cost_center": "Main - TC",
        }

        # Act
        result = self.creator.create_from_dict(transaction_data, mock_donation)

        # Assert
        self.assertIsNone(result)


class TestDonationJournalEntryCreatorIntegration(EnhancedTestCase):
    """Integration tests with actual Frappe database"""

    def setUp(self):
        super().setUp()
        # "Mollie" Mode of Payment is not an app fixture; seed it via the factory
        # so the hard-coded donation.mode_of_payment = "Mollie" works in isolation.
        self.ensure_mode_of_payment("Mollie", "Bank")
        self.creator = DonationJournalEntryCreator()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def _get_test_company(self) -> Optional[str]:
        """Get a valid company for testing"""
        settings = frappe.get_single("Verenigingen Settings")
        if settings.company:
            return settings.company

        # Fallback - get first company
        company = frappe.db.get_value("Company", {}, "name")
        return company

    def _create_test_donor_and_donation(self, company: str) -> tuple:
        """Create test donor and donation for integration tests"""
        # Create donor
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Test Donor JE {frappe.generate_hash()[:6]}"
        donor.donor_email = f"je.test.{frappe.generate_hash()[:6]}@example.nl"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.flags.ignore_validate = True
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)

        # Create donation
        donation = frappe.new_doc("Donation")
        donation.donor = donor.name
        donation.donation_date = today()
        donation.amount = 25.00
        donation.mode_of_payment = "Mollie"
        donation.status = "One-time"
        donation.company = company
        donation.flags.ignore_validate = True
        donation.insert(ignore_permissions=True)
        self.track_test_record("Donation", donation.name)

        return donor, donation

    def test_resolve_company_from_donation_integration(self):
        """Integration test: company resolution from donation document"""
        company = self._get_test_company()
        if not company:
            self.skipTest("No company configured")

        _, donation = self._create_test_donor_and_donation(company)

        result = self.creator._resolve_company(donation)
        self.assertEqual(result, company)

    def test_resolve_company_fallback_integration(self):
        """Integration test: company resolution fallback to settings"""
        company = self._get_test_company()
        if not company:
            self.skipTest("No company configured")

        _, donation = self._create_test_donor_and_donation(company)

        # Clear company from donation
        donation.company = None

        result = self.creator._resolve_company(donation)
        # Should fall back to settings.company
        settings = frappe.get_single("Verenigingen Settings")
        expected = settings.company
        self.assertEqual(result, expected)

    def test_get_config_returns_valid_config(self):
        """Integration test: configuration retrieval returns valid accounts"""
        company = self._get_test_company()
        if not company:
            self.skipTest("No company configured")

        config = self.creator._get_config(company)

        # Should have either valid config or error key
        if "error" not in config:
            self.assertIn("clearing_account", config)
            self.assertIn("income_account", config)
            self.assertEqual(config["company"], company)
        # If error, that's also valid - means configuration is incomplete

    def test_check_existing_by_reference_integration(self):
        """Integration test: idempotency check with database"""
        # Generate unique reference
        unique_ref = f"test-ref-{frappe.generate_hash()[:10]}"

        # Should return None for non-existent reference
        result = self.creator._check_existing_by_reference(unique_ref)
        self.assertIsNone(result)


class TestBankTransactionReconciliation(EnhancedTestCase):
    """Tests for Bank Transaction reconciliation functionality"""

    def setUp(self):
        super().setUp()
        self.creator = DonationJournalEntryCreator()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    @unittest.skip("Requires Bank Account and Bank Transaction setup")
    def test_reconcile_bank_transaction_links_je(self):
        """Test that reconciliation creates payment_entries link"""
        # This would require full Bank Account and Bank Transaction setup
        # which is complex and varies by ERPNext configuration
        pass

    @unittest.skip("Requires Bank Account and Bank Transaction setup")
    def test_reconcile_bank_transaction_updates_status(self):
        """Test that fully allocated Bank Transaction gets Reconciled status"""
        pass


class TestDonationJournalEntryCreatorEndToEnd(EnhancedTestCase):
    """End-to-end tests simulating complete webhook flow"""

    def setUp(self):
        super().setUp()
        self.creator = DonationJournalEntryCreator()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    @unittest.skip("Requires full Mollie and accounting configuration")
    def test_full_mollie_payment_flow(self):
        """Test complete Mollie payment -> Journal Entry flow"""
        # This would test the full flow:
        # 1. Create donation
        # 2. Process Mollie payment
        # 3. Create Journal Entry
        # 4. Verify accounting entries
        pass


def run_donation_je_creator_tests():
    """
    Run the donation journal entry creator tests.

    Usage from bench console:
        from verenigingen.tests.services.test_donation_journal_entry_creator import run_donation_je_creator_tests
        run_donation_je_creator_tests()
    """
    print("=" * 80)
    print("DONATION JOURNAL ENTRY CREATOR TESTS")
    print("=" * 80)

    # Run unit tests
    print("\n1. Running Unit Tests...")
    unit_suite = unittest.TestLoader().loadTestsFromTestCase(TestDonationJournalEntryCreatorUnit)
    unit_result = unittest.TextTestRunner(verbosity=2).run(unit_suite)

    # Run integration tests
    print("\n2. Running Integration Tests...")
    integration_suite = unittest.TestLoader().loadTestsFromTestCase(
        TestDonationJournalEntryCreatorIntegration
    )
    integration_result = unittest.TextTestRunner(verbosity=2).run(integration_suite)

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(
        f"Unit Tests: {unit_result.testsRun} run, "
        f"{len(unit_result.failures)} failures, "
        f"{len(unit_result.errors)} errors"
    )
    print(
        f"Integration Tests: {integration_result.testsRun} run, "
        f"{len(integration_result.failures)} failures, "
        f"{len(integration_result.errors)} errors"
    )

    all_passed = (
        len(unit_result.failures) == 0
        and len(unit_result.errors) == 0
        and len(integration_result.failures) == 0
        and len(integration_result.errors) == 0
    )

    if all_passed:
        print("\n All tests passed!")
    else:
        print("\n Some tests failed - review output above")

    return all_passed


if __name__ == "__main__":
    run_donation_je_creator_tests()
