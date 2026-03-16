"""
ING Checkout DocType Coverage Tests

Tests 3 ING Checkout (Pay.nl) integration DocTypes:
- ING Checkout Mandate (SEPA Direct Debit mandates, IBAN validation)
- ING Checkout Transaction (payment tracking, status mapping)
- ING Checkout Settings (singleton, credential validation)
"""

from datetime import date
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_months, flt, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestINGCheckoutMandate(EnhancedTestCase):
    """Tests for ING Checkout Mandate — SEPA Direct Debit mandate management."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_mandate(self, **kwargs):
        """Create an ING Checkout Mandate with defaults."""
        doc = frappe.new_doc("ING Checkout Mandate")
        doc.mandate_id = kwargs.pop("mandate_id", f"MANDATE-{frappe.generate_hash(length=8)}")
        doc.mandate_type = kwargs.pop("mandate_type", "flexible")
        doc.status = kwargs.pop("status", "Pending")
        doc.debtor_name = kwargs.pop("debtor_name", "Jan de Vries")
        doc.debtor_iban = kwargs.pop("debtor_iban", "NL91ABNA0417164300")
        doc.update(kwargs)
        return doc

    def test_create_mandate(self):
        """Mandate with valid data should save."""
        mandate = self._create_mandate()
        mandate.insert(ignore_permissions=True)
        self.assertTrue(mandate.name)
        self.assertEqual(mandate.mandate_type, "flexible")

    def test_iban_normalized(self):
        """IBAN should be normalized to uppercase no spaces."""
        mandate = self._create_mandate(debtor_iban="nl91 abna 0417 1643 00")
        mandate.insert(ignore_permissions=True)
        self.assertEqual(mandate.debtor_iban, "NL91ABNA0417164300")

    def test_iban_too_short_throws(self):
        """IBAN shorter than 15 chars should throw."""
        mandate = self._create_mandate(debtor_iban="NL91ABNA")
        with self.assertRaises(frappe.ValidationError):
            mandate.insert(ignore_permissions=True)

    def test_iban_too_long_throws(self):
        """IBAN longer than 34 chars should throw."""
        mandate = self._create_mandate(debtor_iban="NL" + "1" * 33)
        with self.assertRaises(frappe.ValidationError):
            mandate.insert(ignore_permissions=True)

    def test_single_mandate_requires_amount(self):
        """Single-use mandate should require an amount."""
        mandate = self._create_mandate(mandate_type="single", amount=None)
        # amount defaults to 0 in Frappe, check validation
        mandate.amount = None
        with self.assertRaises(frappe.ValidationError):
            mandate._validate_type()

    def test_single_mandate_with_amount_passes(self):
        """Single-use mandate with amount should pass."""
        mandate = self._create_mandate(mandate_type="single")
        mandate.amount = 50.0
        mandate._validate_type()  # Should not raise

    def test_expiry_date_auto_set(self):
        """Expiry date should be auto-set to 36 months from creation."""
        mandate = self._create_mandate()
        mandate.created_date = "2026-01-01"
        mandate.expiry_date = None
        mandate.insert(ignore_permissions=True)
        expected = add_months(getdate("2026-01-01"), 36)
        self.assertEqual(getdate(mandate.expiry_date), expected)

    def test_expiry_date_defaults_to_today_plus_36(self):
        """Without created_date, expiry should be 36 months from today."""
        mandate = self._create_mandate()
        mandate.created_date = None
        mandate.expiry_date = None
        mandate._set_expiry_date()
        expected = add_months(getdate(today()), 36)
        self.assertEqual(getdate(mandate.expiry_date), expected)

    def test_expiry_date_preserved_if_set(self):
        """Explicit expiry date should not be overwritten."""
        mandate = self._create_mandate()
        mandate.created_date = "2026-01-01"
        mandate.expiry_date = "2027-06-01"
        mandate._set_expiry_date()
        self.assertEqual(getdate(mandate.expiry_date), getdate("2027-06-01"))

    def test_update_from_webhook(self):
        """Webhook data should update mandate status and dates."""
        mandate = self._create_mandate()
        mandate.insert(ignore_permissions=True)

        webhook_data = {
            "object": {
                "status": "active",
                "firstCollectionDate": "2026-04-01",
                "lastCollectionDate": "2026-12-01",
            }
        }
        mandate.update_from_webhook(webhook_data)
        mandate.reload()

        self.assertEqual(mandate.status, "Active")
        self.assertEqual(str(mandate.first_collection_date), "2026-04-01")

    def test_update_from_webhook_unknown_status(self):
        """Unknown webhook status should not change mandate status."""
        mandate = self._create_mandate(status="Active")
        mandate.insert(ignore_permissions=True)
        original_status = mandate.status

        webhook_data = {"object": {"status": "unknown_status"}}
        mandate.update_from_webhook(webhook_data)
        mandate.reload()
        self.assertEqual(mandate.status, original_status)

    def test_execute_debit_requires_active(self):
        """Execute debit should require Active status."""
        mandate = self._create_mandate(status="Pending")
        mandate.insert(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            mandate.execute_debit(25.00, "Test collection")

    def test_execute_debit_blocks_single_type(self):
        """Single-use mandate should block manual debit execution."""
        mandate = self._create_mandate(
            mandate_type="single", status="Active"
        )
        mandate.amount = 25.0
        mandate.insert(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            mandate.execute_debit(25.00, "Test collection")

    def test_cancel_mandate_already_cancelled(self):
        """Cancelling already-cancelled mandate should throw."""
        mandate = self._create_mandate(status="Cancelled")
        mandate.insert(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            mandate.cancel()

    def test_cancel_mandate_expired(self):
        """Cancelling expired mandate should throw."""
        mandate = self._create_mandate(status="Expired")
        mandate.insert(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            mandate.cancel()

    def test_get_or_create_mandate_creates_new(self):
        """get_or_create_mandate should create new mandate."""
        from verenigingen.verenigingen_payments.doctype.ing_checkout_mandate.ing_checkout_mandate import (
            get_or_create_mandate,
        )

        mandate_id = f"NEW-{frappe.generate_hash(length=8)}"
        mandate = get_or_create_mandate(
            mandate_id=mandate_id,
            mandate_type="flexible",
            debtor_name="Test User",
            debtor_iban="NL91ABNA0417164300",
        )
        self.assertEqual(mandate.mandate_id, mandate_id)
        self.assertEqual(mandate.status, "Pending")

    def test_get_or_create_mandate_returns_existing(self):
        """get_or_create_mandate should return existing mandate."""
        from verenigingen.verenigingen_payments.doctype.ing_checkout_mandate.ing_checkout_mandate import (
            get_or_create_mandate,
        )

        mandate_id = f"EXIST-{frappe.generate_hash(length=8)}"
        first = get_or_create_mandate(
            mandate_id=mandate_id,
            debtor_name="Test User",
            debtor_iban="NL91ABNA0417164300",
        )
        second = get_or_create_mandate(mandate_id=mandate_id)
        self.assertEqual(first.name, second.name)


class TestINGCheckoutTransaction(EnhancedTestCase):
    """Tests for ING Checkout Transaction — payment tracking."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_transaction(self, **kwargs):
        """Create an ING Checkout Transaction with defaults."""
        doc = frappe.new_doc("ING Checkout Transaction")
        doc.transaction_id = kwargs.pop(
            "transaction_id", f"TXN-{frappe.generate_hash(length=8)}"
        )
        doc.status = kwargs.pop("status", "Pending")
        doc.amount = kwargs.pop("amount", 25.00)
        doc.update(kwargs)
        return doc

    def test_create_transaction(self):
        """Transaction with valid data should save."""
        txn = self._create_transaction()
        txn.insert(ignore_permissions=True)
        self.assertTrue(txn.name)

    def test_negative_amount_throws(self):
        """Negative amount should throw validation error."""
        txn = self._create_transaction(amount=-10)
        with self.assertRaises(frappe.ValidationError):
            txn.insert(ignore_permissions=True)

    def test_zero_amount_allowed(self):
        """Zero amount should be allowed (e.g., pre-authorization)."""
        txn = self._create_transaction(amount=0)
        txn.insert(ignore_permissions=True)
        self.assertEqual(flt(txn.amount), 0)

    def test_update_from_webhook_paid(self):
        """Webhook with paid status should update transaction."""
        txn = self._create_transaction()
        txn.insert(ignore_permissions=True)

        webhook_data = {
            "object": {
                "status": {"code": 100},
                "payments": [
                    {
                        "customerMethod": {
                            "name": "Jan de Vries",
                            "iban": "NL91ABNA0417164300",
                            "bic": "ABNANL2A",
                        }
                    }
                ],
            }
        }

        # Mock the service to avoid Payment Entry creation
        with patch(
            "verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction"
            ".INGCheckoutTransaction._create_payment_entry_with_savepoint"
        ):
            txn.update_from_webhook(webhook_data)

        txn.reload()
        self.assertEqual(txn.status, "Paid")
        self.assertEqual(txn.customer_name, "Jan de Vries")
        self.assertEqual(txn.customer_iban, "NL91ABNA0417164300")

    def test_update_from_webhook_cancelled(self):
        """Webhook with cancelled status should update transaction."""
        txn = self._create_transaction()
        txn.insert(ignore_permissions=True)

        webhook_data = {
            "object": {
                "status": {"code": -90},
                "payments": [],
            }
        }
        txn.update_from_webhook(webhook_data)
        txn.reload()
        self.assertEqual(txn.status, "Cancelled")

    def test_update_from_webhook_denied(self):
        """Webhook with denied status code should map correctly."""
        txn = self._create_transaction()
        txn.insert(ignore_permissions=True)

        webhook_data = {
            "object": {
                "status": {"code": -63},
                "payments": [],
            }
        }
        txn.update_from_webhook(webhook_data)
        txn.reload()
        self.assertEqual(txn.status, "Denied")

    def test_status_map_coverage(self):
        """All known status codes should be in STATUS_MAP."""
        from verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction import (
            STATUS_MAP,
        )

        expected_codes = {20, 25, 100, -90, -63, -64, -81}
        self.assertEqual(set(STATUS_MAP.keys()), expected_codes)

    def test_get_or_create_transaction_creates_new(self):
        """get_or_create_transaction should create new transaction."""
        from verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction import (
            get_or_create_transaction,
        )

        txn_id = f"NEW-TXN-{frappe.generate_hash(length=8)}"
        txn = get_or_create_transaction(
            transaction_id=txn_id,
            amount=42.50,
            payment_method="iDEAL",
        )
        self.assertEqual(txn.transaction_id, txn_id)
        self.assertEqual(flt(txn.amount), 42.50)

    def test_get_or_create_transaction_returns_existing(self):
        """get_or_create_transaction should return existing transaction."""
        from verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction import (
            get_or_create_transaction,
        )

        txn_id = f"EXIST-TXN-{frappe.generate_hash(length=8)}"
        first = get_or_create_transaction(transaction_id=txn_id, amount=10)
        second = get_or_create_transaction(transaction_id=txn_id, amount=10)
        self.assertEqual(first.name, second.name)


class TestINGCheckoutSettings(EnhancedTestCase):
    """Tests for ING Checkout Settings singleton — credential validation."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_settings_singleton_exists(self):
        """ING Checkout Settings singleton should be accessible."""
        settings = frappe.get_single("ING Checkout Settings")
        self.assertIsNotNone(settings)

    def test_enabled_requires_service_id(self):
        """Enabling without service_id should throw."""
        settings = frappe.get_single("ING Checkout Settings")
        settings.enabled = 1
        settings.service_id = ""
        settings.token_code = "AT-1234-5678"
        settings.api_token = "secret"
        with self.assertRaises(frappe.ValidationError):
            settings._validate_credentials()

    def test_enabled_requires_token_code(self):
        """Enabling without token_code should throw."""
        settings = frappe.get_single("ING Checkout Settings")
        settings.enabled = 1
        settings.service_id = "SL-1234-5678"
        settings.token_code = ""
        settings.api_token = "secret"
        with self.assertRaises(frappe.ValidationError):
            settings._validate_credentials()

    def test_enabled_requires_api_token(self):
        """Enabling without api_token should throw."""
        settings = frappe.get_single("ING Checkout Settings")
        settings.enabled = 1
        settings.service_id = "SL-1234-5678"
        settings.token_code = "AT-1234-5678"
        settings.api_token = ""
        with self.assertRaises(frappe.ValidationError):
            settings._validate_credentials()

    def test_service_id_format(self):
        """Service ID must start with 'SL-'."""
        settings = frappe.get_single("ING Checkout Settings")
        settings.enabled = 1
        settings.service_id = "XX-1234-5678"
        settings.token_code = "AT-1234-5678"
        settings.api_token = "secret"
        with self.assertRaises(frappe.ValidationError):
            settings._validate_credentials()

    def test_token_code_format(self):
        """Token code must start with 'AT-'."""
        settings = frappe.get_single("ING Checkout Settings")
        settings.enabled = 1
        settings.service_id = "SL-1234-5678"
        settings.token_code = "XX-1234-5678"
        settings.api_token = "secret"
        with self.assertRaises(frappe.ValidationError):
            settings._validate_credentials()

    def test_valid_credentials_pass(self):
        """Valid credentials should pass validation."""
        settings = frappe.get_single("ING Checkout Settings")
        settings.enabled = 1
        settings.service_id = "SL-1234-5678"
        settings.token_code = "AT-1234-5678"
        settings.api_token = "secret"
        settings._validate_credentials()  # Should not raise

    def test_disabled_skips_credential_validation(self):
        """Disabled settings should skip credential validation."""
        settings = frappe.get_single("ING Checkout Settings")
        settings.enabled = 0
        settings.service_id = ""
        settings.token_code = ""
        settings.api_token = ""
        settings.validate()  # Should not raise (skips _validate_credentials)

    def test_webhook_url_generated(self):
        """Webhook URL should be auto-generated."""
        settings = frappe.get_single("ING Checkout Settings")
        settings._generate_webhook_url()
        self.assertIn("/api/method/", settings.webhook_url)
        self.assertIn("ing_checkout", settings.webhook_url)

    def test_get_base_url(self):
        """Base URL should be the Pay.nl connect URL."""
        settings = frappe.get_single("ING Checkout Settings")
        self.assertEqual(settings.get_base_url(), "https://connect.pay.nl")

    def test_get_rest_url(self):
        """REST URL should be the Pay.nl REST API URL."""
        settings = frappe.get_single("ING Checkout Settings")
        self.assertEqual(settings.get_rest_url(), "https://rest.pay.nl")

    def test_get_api_credentials_when_disabled_throws(self):
        """Getting credentials when disabled should throw."""
        settings = frappe.get_single("ING Checkout Settings")
        settings.enabled = 0
        with self.assertRaises(frappe.ValidationError):
            settings.get_api_credentials()

    def test_is_ing_checkout_enabled_api(self):
        """Public API should return enabled status."""
        from verenigingen.verenigingen_payments.doctype.ing_checkout_settings.ing_checkout_settings import (
            is_ing_checkout_enabled,
        )

        result = is_ing_checkout_enabled()
        self.assertIn("enabled", result)
        self.assertIsInstance(result["enabled"], bool)
