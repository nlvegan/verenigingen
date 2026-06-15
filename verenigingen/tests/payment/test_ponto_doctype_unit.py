"""
Ponto DocType Unit Tests (Tier-1, HTTP boundary stubbed)

These cover controller branches that make outbound Ponto/Ibanity API calls.
Per project policy, the ONLY thing stubbed is the HTTP boundary — the Ponto
API client factory functions / client classes. All business logic (validation,
status mapping, document persistence) runs for real.

Stubbed boundaries:
- ``get_betaalverzoek_client`` (Ponto Payment Link)
- ``get_payment_client``      (Ponto Payment Request)
- ``PontoAccountsClient`` / ``PontoClient`` and token manager (Ponto Settings)

File is named ``*_unit.py`` so the test-quality-enforcer treats HTTP-boundary
patching as Tier-1 (allowed).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

LINK_CLIENT = (
    "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
)
PAY_CLIENT = "verenigingen.verenigingen_payments.ponto.clients.payment_client.get_payment_client"


class TestPontoPaymentLinkApi(EnhancedTestCase):
    """API-calling branches of Ponto Payment Link with the client stubbed."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_link(self, **kwargs):
        doc = frappe.new_doc("Ponto Payment Link")
        doc.payment_type = kwargs.pop("payment_type", "One-Time")
        doc.amount = kwargs.pop("amount", 25.00)
        doc.currency = kwargs.pop("currency", "EUR")
        doc.description = kwargs.pop("description", "Test payment")
        doc.creditor_name = kwargs.pop("creditor_name", "Test Association")
        doc.creditor_iban = kwargs.pop("creditor_iban", "NL91ABNA0417164300")
        doc.update(kwargs)
        return doc

    def test_submit_creates_ponto_request(self):
        """before_submit calls the API and stores request id + redirect link."""
        fake_client = MagicMock()
        fake_client.create_payment_request.return_value = SimpleNamespace(
            id="ponto-req-123",
            redirect_link="https://myponto.example/authorize/abc",
        )
        link = self._create_link()
        link.insert()
        with patch(LINK_CLIENT, return_value=fake_client):
            link.submit()
        link.reload()
        self.assertEqual(link.ponto_request_id, "ponto-req-123")
        self.assertEqual(link.redirect_link, "https://myponto.example/authorize/abc")
        self.assertEqual(link.status, "Pending Authorization")
        fake_client.create_payment_request.assert_called_once()

    def test_create_ponto_payment_request_api_error_throws(self):
        """API failure during creation is surfaced as a ValidationError."""
        fake_client = MagicMock()
        fake_client.create_payment_request.side_effect = RuntimeError("ponto down")
        link = self._create_link()
        link.insert()
        with patch(LINK_CLIENT, return_value=fake_client):
            with self.assertRaises(frappe.ValidationError):
                link.submit()

    def test_refresh_status_maps_signed_to_authorized(self):
        """refresh_status maps Ponto 'signed' to our 'Authorized' status."""
        fake_client = MagicMock()
        fake_client.get_payment_request.return_value = SimpleNamespace(
            status="signed",
            debtor_name="Jan de Vries",
            debtor_iban="NL53RABO0123456789",
            debtor_bank="RABOBANK",
        )
        link = self._create_link()
        link.insert()
        link.db_set("ponto_request_id", "ponto-req-123")
        link.reload()
        with patch(LINK_CLIENT, return_value=fake_client):
            result = link.refresh_status()
        self.assertEqual(result["status"], "Authorized")
        link.reload()
        self.assertEqual(link.status, "Authorized")
        self.assertEqual(link.debtor_name, "Jan de Vries")
        self.assertEqual(link.debtor_iban, "NL53RABO0123456789")

    def test_refresh_status_unknown_status_keeps_current(self):
        """An unmapped Ponto status leaves our status unchanged."""
        fake_client = MagicMock()
        fake_client.get_payment_request.return_value = SimpleNamespace(
            status="someNewStatus", debtor_name=None, debtor_iban=None, debtor_bank=None
        )
        link = self._create_link()
        link.insert()
        link.db_set("ponto_request_id", "ponto-req-123")
        link.db_set("status", "Pending Authorization")
        link.reload()
        with patch(LINK_CLIENT, return_value=fake_client):
            result = link.refresh_status()
        self.assertEqual(result["status"], "Pending Authorization")

    def test_refresh_status_no_request_id_throws(self):
        """refresh_status without a Ponto request id throws."""
        link = self._create_link()
        link.insert()
        link.ponto_request_id = None
        with self.assertRaises(frappe.ValidationError):
            link.refresh_status()

    def test_cancel_ponto_request_calls_delete(self):
        """cancel_ponto_request deletes the request via the API."""
        fake_client = MagicMock()
        link = self._create_link()
        link.insert()
        link.ponto_request_id = "ponto-req-123"
        with patch(LINK_CLIENT, return_value=fake_client):
            link.cancel_ponto_request()
        fake_client.delete_payment_request.assert_called_once_with("ponto-req-123")

    def test_cancel_ponto_request_swallows_api_error(self):
        """A delete failure is logged, not raised (may already be authorized)."""
        fake_client = MagicMock()
        fake_client.delete_payment_request.side_effect = RuntimeError("already signed")
        link = self._create_link()
        link.insert()
        link.ponto_request_id = "ponto-req-123"
        with patch(LINK_CLIENT, return_value=fake_client):
            # Should NOT raise
            link.cancel_ponto_request()


class TestPontoPaymentRequestApi(EnhancedTestCase):
    """API-calling branches of Ponto Payment Request with the client stubbed."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_request(self, **kwargs):
        doc = frappe.new_doc("Ponto Payment Request")
        doc.ponto_account = kwargs.pop("ponto_account", "test-account-uuid")
        doc.amount = kwargs.pop("amount", 50.00)
        doc.currency = kwargs.pop("currency", "EUR")
        doc.creditor_name = kwargs.pop("creditor_name", "Test Supplier")
        doc.creditor_iban = kwargs.pop("creditor_iban", "DE89370400440532013000")
        doc.remittance_info = kwargs.pop("remittance_info", "Invoice payment")
        doc.update(kwargs)
        return doc

    def test_submit_creates_ponto_payment(self):
        """before_submit calls the API and stores payment id + redirect link."""
        fake_client = MagicMock()
        fake_client.create_payment.return_value = SimpleNamespace(
            id="ponto-pay-456",
            redirect_link="https://myponto.example/sign/xyz",
        )
        req = self._create_request()
        req.insert()
        with patch(PAY_CLIENT, return_value=fake_client):
            req.submit()
        req.reload()
        self.assertEqual(req.ponto_payment_id, "ponto-pay-456")
        self.assertEqual(req.redirect_link, "https://myponto.example/sign/xyz")
        self.assertEqual(req.status, "Pending")
        fake_client.create_payment.assert_called_once()

    def test_create_ponto_payment_api_error_throws(self):
        """API failure during creation surfaces as ValidationError."""
        fake_client = MagicMock()
        fake_client.create_payment.side_effect = RuntimeError("ponto down")
        req = self._create_request()
        req.insert()
        with patch(PAY_CLIENT, return_value=fake_client):
            with self.assertRaises(frappe.ValidationError):
                req.submit()

    def test_refresh_status_maps_signed(self):
        """refresh_status maps Ponto 'signed' to our 'Signed' status."""
        fake_client = MagicMock()
        fake_client.get_payment.return_value = SimpleNamespace(status="signed")
        req = self._create_request()
        req.insert()
        req.db_set("ponto_payment_id", "ponto-pay-456")
        req.reload()
        with patch(PAY_CLIENT, return_value=fake_client):
            result = req.refresh_status()
        self.assertEqual(result["status"], "Signed")
        req.reload()
        self.assertEqual(req.status, "Signed")

    def test_refresh_status_no_payment_id_throws(self):
        """refresh_status without a Ponto payment id throws."""
        req = self._create_request()
        req.insert()
        req.ponto_payment_id = None
        with self.assertRaises(frappe.ValidationError):
            req.refresh_status()

    def test_cancel_ponto_payment_calls_delete(self):
        """cancel_ponto_payment deletes the payment via the API."""
        fake_client = MagicMock()
        req = self._create_request()
        req.insert()
        req.ponto_payment_id = "ponto-pay-456"
        with patch(PAY_CLIENT, return_value=fake_client):
            req.cancel_ponto_payment()
        fake_client.delete_payment.assert_called_once_with(
            account_id="test-account-uuid", payment_id="ponto-pay-456"
        )

    def test_cancel_ponto_payment_swallows_api_error(self):
        """Delete failure is logged, not raised."""
        fake_client = MagicMock()
        fake_client.delete_payment.side_effect = RuntimeError("already signed")
        req = self._create_request()
        req.insert()
        req.ponto_payment_id = "ponto-pay-456"
        with patch(PAY_CLIENT, return_value=fake_client):
            req.cancel_ponto_payment()


class TestPontoSettingsApi(EnhancedTestCase):
    """API-calling branches of Ponto Settings with clients stubbed."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._original_in_test = frappe.flags.in_test
        frappe.flags.in_test = True

    def tearDown(self):
        frappe.flags.in_test = self._original_in_test
        super().tearDown()

    def test_test_connection_success(self):
        """test_connection returns success + account count when API works."""
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_mode = 1
        settings.sandbox_client_id = "sandbox-id"
        fake_accounts_client = MagicMock()
        fake_accounts_client.list_accounts.return_value = [object(), object()]
        with patch.object(settings, "validate_credentials", return_value=True), patch(
            "verenigingen.verenigingen_payments.ponto.clients.accounts_client.PontoAccountsClient",
            return_value=fake_accounts_client,
        ):
            result = settings.test_connection()
        self.assertTrue(result["success"])
        self.assertEqual(result["accounts_found"], 2)

    def test_test_connection_failure_returns_error(self):
        """test_connection catches API errors and returns success=False."""
        settings = frappe.get_single("Ponto Settings")
        with patch.object(
            settings, "validate_credentials", side_effect=RuntimeError("bad creds")
        ):
            result = settings.test_connection()
        self.assertFalse(result["success"])
        self.assertIn("bad creds", result["message"])

    def test_refresh_user_info_updates_activation_fields(self):
        """refresh_user_info maps /userinfo response onto activation fields."""
        from verenigingen.tests.fixtures.singleton_backup import singleton_backup

        fake_client = MagicMock()
        fake_client.BASE_URL = "https://api.ibanity.com/ponto-connect"
        fake_client._use_mtls = True
        fake_client.get.return_value = {
            "name": "Vegan Org BV",
            "sub": "org-uuid-1",
            "onboardingComplete": True,
            "paymentsActivated": False,
            "paymentRequestsActivated": True,
            "paymentsActivationRequested": True,
            "paymentRequestsActivationRequested": False,
        }
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            with patch(
                "verenigingen.verenigingen_payments.ponto.core.ponto_client.PontoClient",
                return_value=fake_client,
            ):
                result = settings.refresh_user_info()
            self.assertTrue(result["success"])
            self.assertEqual(result["organization_name"], "Vegan Org BV")
            self.assertTrue(result["onboarding_complete"])
            self.assertFalse(result["payments_activated"])
            self.assertTrue(result["payment_requests_activated"])
            self.assertTrue(result["payments_activation_requested"])

    def test_refresh_user_info_api_error_throws(self):
        """A failed /userinfo call (mTLS path) surfaces as ValidationError."""
        fake_client = MagicMock()
        fake_client.BASE_URL = "https://api.ibanity.com/ponto-connect"
        fake_client._use_mtls = True
        fake_client.get.side_effect = RuntimeError("userinfo 500")
        settings = frappe.get_single("Ponto Settings")
        with patch(
            "verenigingen.verenigingen_payments.ponto.core.ponto_client.PontoClient",
            return_value=fake_client,
        ):
            with self.assertRaises(frappe.ValidationError):
                settings.refresh_user_info()
