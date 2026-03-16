"""
Ponto DocType Coverage Tests

Tests 4 Ponto integration DocTypes:
- Ponto Settings (singleton, OAuth2 credentials, sync interval)
- Ponto Payment Link (SEPA payment requests, currency/IBAN validation)
- Ponto Payment Request (outbound payments, IBAN validation)
- Ponto Sync Log (sync tracking, duration calculation)

External HTTP calls are mocked via @patch on client/service imports.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import now_datetime, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPontoSettings(EnhancedTestCase):
    """Tests for Ponto Settings singleton — credential validation, sync interval."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        # Ensure we're in test mode so test credential validation is skipped
        self._original_in_test = frappe.flags.in_test
        frappe.flags.in_test = True

    def tearDown(self):
        frappe.flags.in_test = self._original_in_test
        super().tearDown()

    def test_settings_singleton_exists(self):
        """Ponto Settings singleton should be accessible."""
        settings = frappe.get_single("Ponto Settings")
        self.assertIsNotNone(settings)

    def test_sandbox_mode_requires_sandbox_client_id(self):
        """Enabling sandbox mode without client ID should throw."""
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_mode = 1
        settings.sandbox_client_id = ""
        settings.production_client_id = ""
        with self.assertRaises(frappe.ValidationError):
            settings.validate_credentials_configured()

    def test_production_mode_requires_production_client_id(self):
        """Disabling sandbox mode without production client ID should throw."""
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_mode = 0
        settings.production_client_id = ""
        with self.assertRaises(frappe.ValidationError):
            settings.validate_credentials_configured()

    def test_sandbox_mode_with_client_id_passes(self):
        """Sandbox mode with valid client ID should pass validation."""
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_mode = 1
        settings.sandbox_client_id = "valid-sandbox-id"
        settings.validate_credentials_configured()  # Should not raise

    def test_sync_interval_too_short_throws(self):
        """Sync interval under 1 hour should throw."""
        settings = frappe.get_single("Ponto Settings")
        settings.auto_sync_enabled = 1
        settings.sync_interval_hours = 0.5
        with self.assertRaises(frappe.ValidationError):
            settings.validate_sync_interval()

    def test_sync_interval_too_long_throws(self):
        """Sync interval over 168 hours should throw."""
        settings = frappe.get_single("Ponto Settings")
        settings.auto_sync_enabled = 1
        settings.sync_interval_hours = 200
        with self.assertRaises(frappe.ValidationError):
            settings.validate_sync_interval()

    def test_sync_interval_valid(self):
        """Valid sync interval should pass."""
        settings = frappe.get_single("Ponto Settings")
        settings.auto_sync_enabled = 1
        settings.sync_interval_hours = 6
        settings.validate_sync_interval()  # Should not raise

    def test_webhook_url_generated_when_enabled(self):
        """Webhook URL should be auto-generated when webhooks enabled."""
        settings = frappe.get_single("Ponto Settings")
        settings.enable_webhooks = 1
        settings.update_webhook_url()
        self.assertIn("/api/method/", settings.webhook_url)
        self.assertIn("ponto", settings.webhook_url)

    def test_get_active_client_id_sandbox(self):
        """Should return sandbox client ID when in sandbox mode."""
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_mode = 1
        settings.sandbox_client_id = "sandbox-123"
        settings.production_client_id = "prod-456"
        self.assertEqual(settings.get_active_client_id(), "sandbox-123")

    def test_get_active_client_id_production(self):
        """Should return production client ID when in production mode."""
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_mode = 0
        settings.production_client_id = "prod-456"
        settings.sandbox_client_id = "sandbox-123"
        self.assertEqual(settings.get_active_client_id(), "prod-456")

    def test_get_mapping_for_unknown_account(self):
        """Should return None for unknown Ponto account."""
        settings = frappe.get_single("Ponto Settings")
        result = settings.get_mapping_for_ponto_account("nonexistent-uuid")
        self.assertIsNone(result)

    def test_get_enabled_account_mappings_empty(self):
        """Should return empty list when no enabled mappings."""
        settings = frappe.get_single("Ponto Settings")
        # Clear mappings for test
        original_mappings = settings.bank_account_mappings
        settings.bank_account_mappings = []
        result = settings.get_enabled_account_mappings()
        self.assertEqual(len(result), 0)
        settings.bank_account_mappings = original_mappings

    def test_cleanup_duplicate_mappings(self):
        """Should remove duplicate IBAN mappings."""
        settings = frappe.get_single("Ponto Settings")
        # Save original and test with temporary data
        original_mappings = list(settings.bank_account_mappings or [])

        settings.bank_account_mappings = []
        settings.append(
            "bank_account_mappings",
            {"ponto_iban": "NL91ABNA0417164300", "enabled": 1, "ponto_account_id": "a1"},
        )
        settings.append(
            "bank_account_mappings",
            {"ponto_iban": "NL91ABNA0417164300", "enabled": 1, "ponto_account_id": "a2"},
        )
        settings.append(
            "bank_account_mappings",
            {"ponto_iban": "NL18RABO0123456789", "enabled": 1, "ponto_account_id": "b1"},
        )

        removed = settings.cleanup_duplicate_mappings()
        self.assertEqual(removed, 1)
        self.assertEqual(len(settings.bank_account_mappings), 2)

        # Restore
        settings.bank_account_mappings = original_mappings

    def test_test_credentials_blocked_outside_test_mode(self):
        """Test credentials should be blocked when not in test mode."""
        frappe.flags.in_test = False
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_client_id = "test_client_abc"
        settings.sandbox_mode = 1
        with self.assertRaises(frappe.ValidationError):
            settings.validate_no_test_credentials()


class TestPontoPaymentLink(EnhancedTestCase):
    """Tests for Ponto Payment Link — SEPA payment request validation."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_link(self, **kwargs):
        """Create a Ponto Payment Link with defaults."""
        doc = frappe.new_doc("Ponto Payment Link")
        doc.payment_type = kwargs.pop("payment_type", "One-off")
        doc.amount = kwargs.pop("amount", 25.00)
        doc.currency = kwargs.pop("currency", "EUR")
        doc.description = kwargs.pop("description", "Test payment")
        doc.creditor_name = kwargs.pop("creditor_name", "Test Association")
        doc.creditor_iban = kwargs.pop("creditor_iban", "NL91ABNA0417164300")
        doc.update(kwargs)
        return doc

    def test_create_payment_link(self):
        """Payment link with valid data should save."""
        link = self._create_link()
        link.insert()
        self.assertTrue(link.name)
        self.assertEqual(link.currency, "EUR")

    def test_non_eur_currency_throws(self):
        """Non-EUR currency should throw for SEPA payments."""
        link = self._create_link(currency="USD")
        with self.assertRaises(frappe.ValidationError):
            link.insert()

    def test_zero_amount_throws(self):
        """Zero amount should throw validation error."""
        link = self._create_link(amount=0)
        with self.assertRaises(frappe.ValidationError):
            link.insert()

    def test_negative_amount_throws(self):
        """Negative amount should throw validation error."""
        link = self._create_link(amount=-10)
        with self.assertRaises(frappe.ValidationError):
            link.insert()

    def test_missing_creditor_name_throws(self):
        """Missing creditor name should throw."""
        link = self._create_link(creditor_name="")
        with self.assertRaises(frappe.ValidationError):
            link.insert()

    def test_missing_creditor_iban_throws(self):
        """Missing creditor IBAN should throw."""
        link = self._create_link(creditor_iban="")
        # set_defaults_from_settings may fill this from settings, so clear it
        link.creditor_iban = ""
        with self.assertRaises(frappe.ValidationError):
            link.validate_creditor()

    def test_invalid_iban_format_throws(self):
        """Invalid IBAN format should throw."""
        link = self._create_link(creditor_iban="12345")
        with self.assertRaises(frappe.ValidationError):
            link.validate_creditor()

    def test_iban_normalized(self):
        """IBAN should be normalized (uppercase, no spaces)."""
        link = self._create_link(creditor_iban="nl91 abna 0417 1643 00")
        link.insert()
        self.assertEqual(link.creditor_iban, "NL91ABNA0417164300")

    def test_periodic_type_throws(self):
        """Periodic payment type should throw (not supported by Ponto)."""
        link = self._create_link(payment_type="Periodic")
        with self.assertRaises(frappe.ValidationError):
            link.insert()

    def test_update_status_from_webhook(self):
        """Webhook status update should change status."""
        link = self._create_link()
        link.insert()
        link.update_status_from_webhook("Executed")
        link.reload()
        self.assertEqual(link.status, "Executed")

    def test_update_status_with_debtor_info(self):
        """Webhook should update debtor info when provided."""
        link = self._create_link()
        link.insert()
        link.update_status_from_webhook(
            "Authorized",
            debtor_info={
                "name": "Jan de Vries",
                "iban": "NL18RABO0123456789",
                "bank": "RABOBANK",
            },
        )
        link.reload()
        self.assertEqual(link.debtor_name, "Jan de Vries")
        self.assertEqual(link.debtor_iban, "NL18RABO0123456789")

    def test_increment_payment_count_periodic(self):
        """Periodic payment counter logic should increment correctly.

        Since Periodic type is blocked by validation, we test the counter logic
        directly without going through save().
        """
        link = self._create_link()
        link.insert()
        # Test the counter logic directly: if payment_type were Periodic
        link.payment_type = "Periodic"
        link.total_payments_collected = 0
        # Call the method but mock save to avoid re-validation
        from unittest.mock import patch

        with patch.object(link, "save"):
            link.increment_payment_count()
        self.assertEqual(link.total_payments_collected, 1)


class TestPontoPaymentRequest(EnhancedTestCase):
    """Tests for Ponto Payment Request — outbound SEPA payment validation."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_request(self, **kwargs):
        """Create a Ponto Payment Request with defaults."""
        doc = frappe.new_doc("Ponto Payment Request")
        doc.ponto_account = kwargs.pop("ponto_account", "test-account-uuid")
        doc.amount = kwargs.pop("amount", 50.00)
        doc.currency = kwargs.pop("currency", "EUR")
        doc.creditor_name = kwargs.pop("creditor_name", "Test Supplier")
        doc.creditor_iban = kwargs.pop("creditor_iban", "DE89370400440532013000")
        doc.remittance_info = kwargs.pop("remittance_info", "Invoice payment")
        doc.update(kwargs)
        return doc

    def test_create_payment_request(self):
        """Payment request with valid data should save."""
        req = self._create_request()
        req.insert()
        self.assertTrue(req.name)

    def test_non_eur_currency_throws(self):
        """Non-EUR currency should throw."""
        req = self._create_request(currency="GBP")
        with self.assertRaises(frappe.ValidationError):
            req.insert()

    def test_zero_amount_throws(self):
        """Zero amount should throw."""
        req = self._create_request(amount=0)
        with self.assertRaises(frappe.ValidationError):
            req.insert()

    def test_missing_iban_throws(self):
        """Missing creditor IBAN should throw."""
        req = self._create_request(creditor_iban="")
        with self.assertRaises(frappe.ValidationError):
            req.insert()

    def test_invalid_iban_throws(self):
        """Short/invalid IBAN should throw."""
        req = self._create_request(creditor_iban="XX12")
        with self.assertRaises(frappe.ValidationError):
            req.insert()

    def test_iban_normalized(self):
        """IBAN should be normalized to uppercase no spaces."""
        req = self._create_request(creditor_iban="de89 3704 0044 0532 0130 00")
        req.insert()
        self.assertEqual(req.creditor_iban, "DE89370400440532013000")

    def test_update_status_from_webhook(self):
        """Webhook status update should change document status."""
        req = self._create_request()
        req.insert()
        req.update_status_from_webhook("Executed")
        req.reload()
        self.assertEqual(req.status, "Executed")

    def test_on_cancel_sets_cancelled(self):
        """Cancel should set status to Cancelled."""
        req = self._create_request()
        req.insert()
        req.on_cancel()
        self.assertEqual(req.status, "Cancelled")


class TestPontoSyncLog(EnhancedTestCase):
    """Tests for Ponto Sync Log — sync tracking and duration calculation."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_sync_log(self, **kwargs):
        """Create a Ponto Sync Log."""
        doc = frappe.new_doc("Ponto Sync Log")
        doc.sync_type = kwargs.get("sync_type", "Manual")
        doc.status = kwargs.get("status", "Pending")
        doc.update(kwargs)
        return doc

    def test_create_sync_log(self):
        """Sync log should save with valid data."""
        log = self._create_sync_log()
        log.insert(ignore_permissions=True)
        self.assertTrue(log.name)

    def test_create_sync_log_helper_function(self):
        """Helper function should create and insert sync log."""
        from verenigingen.verenigingen_payments.doctype.ponto_sync_log.ponto_sync_log import (
            create_sync_log,
        )

        log = create_sync_log(
            sync_type="Automatic",
            account_id="test-account-uuid",
        )
        self.assertTrue(log.name)
        self.assertEqual(log.sync_type, "Automatic")
        self.assertEqual(log.status, "Pending")

    def test_duration_calculation(self):
        """Duration should be calculated from start and end times."""
        log = self._create_sync_log()
        log.start_time = datetime(2026, 3, 16, 10, 0, 0)
        log.end_time = datetime(2026, 3, 16, 10, 0, 30)
        log.calculate_duration()
        self.assertAlmostEqual(log.duration_seconds, 30.0, places=1)

    def test_duration_with_string_datetimes(self):
        """Duration calculation should handle string datetimes."""
        log = self._create_sync_log()
        log.start_time = "2026-03-16 10:00:00"
        log.end_time = "2026-03-16 10:01:00"
        log.calculate_duration()
        self.assertAlmostEqual(log.duration_seconds, 60.0, places=1)

    def test_start_sync(self):
        """start_sync should set status and start_time."""
        log = self._create_sync_log()
        log.insert(ignore_permissions=True)
        log.start_sync()
        self.assertEqual(log.status, "In Progress")
        self.assertIsNotNone(log.start_time)

    def test_complete_sync_success(self):
        """complete_sync should set status to Completed when no failures."""
        log = self._create_sync_log()
        log.insert(ignore_permissions=True)
        log.start_sync()
        log.complete_sync(imported=10, skipped=2, failed=0)
        self.assertEqual(log.status, "Completed")
        self.assertEqual(log.transactions_imported, 10)
        self.assertEqual(log.transactions_skipped, 2)
        self.assertIsNotNone(log.end_time)

    def test_complete_sync_with_failures(self):
        """complete_sync should set status to Failed when there are failures."""
        log = self._create_sync_log()
        log.insert(ignore_permissions=True)
        log.start_sync()
        log.complete_sync(
            imported=5,
            failed=3,
            errors=[
                {"error_type": "validation", "error_message": "bad data"},
                {"error_type": "api", "error_message": "timeout"},
            ],
        )
        self.assertEqual(log.status, "Failed")
        self.assertEqual(log.transactions_failed, 3)
        self.assertIn("2 errors", log.error_summary)

    def test_fail_sync(self):
        """fail_sync should record error details."""
        log = self._create_sync_log()
        log.insert(ignore_permissions=True)
        log.start_sync()
        log.fail_sync("Connection refused", {"host": "api.ibanity.com"})
        self.assertEqual(log.status, "Failed")
        self.assertEqual(log.error_summary, "Connection refused")
        self.assertIsNotNone(log.error_details)

    def test_get_bank_transaction_list(self):
        """Should parse stored bank transaction list."""
        log = self._create_sync_log()
        log.insert(ignore_permissions=True)
        log.start_sync()
        log.complete_sync(
            imported=2,
            bank_transactions=["BT-001", "BT-002"],
        )
        result = log.get_bank_transaction_list()
        self.assertEqual(result, ["BT-001", "BT-002"])

    def test_get_bank_transaction_list_empty(self):
        """Should return empty list when no transactions stored."""
        log = self._create_sync_log()
        result = log.get_bank_transaction_list()
        self.assertEqual(result, [])

    def test_get_error_list(self):
        """Should parse stored error list."""
        log = self._create_sync_log()
        log.insert(ignore_permissions=True)
        log.start_sync()
        log.complete_sync(
            imported=0,
            failed=1,
            errors=[{"error_type": "api", "error_message": "500 Internal Server Error"}],
        )
        errors = log.get_error_list()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["error_type"], "api")

    def test_get_latest_sync_log(self):
        """Should return most recent sync log."""
        from verenigingen.verenigingen_payments.doctype.ponto_sync_log.ponto_sync_log import (
            create_sync_log,
            get_latest_sync_log,
        )

        log = create_sync_log(sync_type="Manual", account_id="test-latest")
        latest = get_latest_sync_log(account_id="test-latest")
        self.assertIsNotNone(latest)
        self.assertEqual(latest.name, log.name)

    def test_error_summary_single(self):
        """Single error summary should show the error message."""
        log = self._create_sync_log()
        errors = [{"error_type": "api", "error_message": "Timeout connecting to Ibanity"}]
        summary = log._build_error_summary(errors)
        self.assertIn("1 error", summary)
        self.assertIn("Timeout", summary)

    def test_error_summary_grouped(self):
        """Multiple errors should be grouped by type."""
        log = self._create_sync_log()
        errors = [
            {"error_type": "validation", "error_message": "bad IBAN"},
            {"error_type": "validation", "error_message": "bad amount"},
            {"error_type": "api", "error_message": "timeout"},
        ]
        summary = log._build_error_summary(errors)
        self.assertIn("3 errors", summary)
        self.assertIn("validation", summary)
        self.assertIn("api", summary)
