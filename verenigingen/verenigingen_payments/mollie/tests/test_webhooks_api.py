"""
LIVE tests for mollie/api/webhooks.py (the thin HTTP endpoint layer).

webhooks.py is the public webhook surface: integrations/mollie/__init__.py exports
handle_mollie_payment_webhook, core/client builds URLs to these endpoints, and
mollie_settings builds a fallback webhook URL to mollie_payment_webhook. These
endpoints delegate to unified_payment_api.handle_payment_webhook; here we pin the
thin layer's own contract: health checks, GET-as-healthcheck, the error->status
mapping, and backward-compat routing.

The delegate (handle_payment_webhook) is stubbed at the import boundary so we test
THIS module's wiring, not the already-covered unified handler.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.api import webhooks
from verenigingen.verenigingen_payments.mollie.exceptions import MollieSecurityError, MollieWebhookError
from verenigingen.verenigingen_payments.mollie.tests.fixtures.webhook_fixtures import install_fake_request

DELEGATE = "verenigingen.verenigingen_payments.mollie.api.unified_payment_api.handle_payment_webhook"


class TestHandleMolliePaymentWebhook(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.local.response = frappe._dict()

    def test_delegates_to_unified_handler(self):
        """handle_mollie_payment_webhook returns the unified handler's result."""
        expected = {"status": "success", "message": "ok"}
        with patch(DELEGATE, return_value=expected):
            out = webhooks.handle_mollie_payment_webhook()
        self.assertEqual(out, expected)

    def test_delegate_exception_maps_to_500(self):
        """If the delegate raises, the endpoint catches it, sets 500, and returns
        a safe generic message (no internal detail leaked)."""
        with patch(DELEGATE, side_effect=RuntimeError("internal boom")):
            out = webhooks.handle_mollie_payment_webhook()
        self.assertEqual(out["status"], "error")
        self.assertEqual(frappe.local.response.http_status_code, 500)
        self.assertEqual(out["message"], "Internal server error processing webhook")

    def test_backward_compat_aliases_route_to_main(self):
        """mollie_payment_webhook and mollie_subscription_webhook both delegate to
        the main handler (backward-compatibility endpoints)."""
        expected = {"status": "success"}
        with patch(DELEGATE, return_value=expected):
            self.assertEqual(webhooks.mollie_payment_webhook(), expected)
            self.assertEqual(webhooks.mollie_subscription_webhook(), expected)


class TestHandleUnifiedWebhook(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.local.response = frappe._dict()

    def test_get_request_is_health_check(self):
        """A GET request short-circuits to a healthy status payload without
        invoking the payment handler."""
        with install_fake_request("", method="GET"):
            with patch(DELEGATE) as delegate:
                out = webhooks.handle_unified_webhook()
        self.assertEqual(out["status"], "healthy")
        self.assertEqual(out["service"], "Mollie Webhook Handler")
        delegate.assert_not_called()

    def test_post_request_delegates(self):
        expected = {"status": "success", "message": "processed"}
        with install_fake_request('{"id":"tr_unified_1"}', method="POST"):
            with patch(DELEGATE, return_value=expected):
                out = webhooks.handle_unified_webhook()
        self.assertEqual(out, expected)

    def test_security_error_maps_to_403(self):
        with install_fake_request('{"id":"tr_unified_sec"}', method="POST"):
            with patch(DELEGATE, side_effect=MollieSecurityError("bad sig")):
                out = webhooks.handle_unified_webhook()
        self.assertEqual(frappe.local.response.http_status_code, 403)
        self.assertEqual(out["status"], "error")

    def test_webhook_error_maps_to_400(self):
        with install_fake_request('{"id":"tr_unified_we"}', method="POST"):
            with patch(DELEGATE, side_effect=MollieWebhookError("bad webhook")):
                out = webhooks.handle_unified_webhook()
        self.assertEqual(frappe.local.response.http_status_code, 400)
        self.assertEqual(out["status"], "error")

    def test_unexpected_error_maps_to_500(self):
        with install_fake_request('{"id":"tr_unified_500"}', method="POST"):
            with patch(DELEGATE, side_effect=RuntimeError("kaboom")):
                out = webhooks.handle_unified_webhook()
        self.assertEqual(frappe.local.response.http_status_code, 500)
        self.assertEqual(out["status"], "error")


class TestWebhookHealthCheck(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.local.response = frappe._dict()

    def test_health_check_returns_structured_status(self):
        """The health check always returns a structured dict with a timestamp and
        never raises out to the caller."""
        out = webhooks.webhook_health_check()
        self.assertIn(out["status"], ("healthy", "degraded", "unhealthy"))
        self.assertIn("timestamp", out)

    def test_health_check_reports_configuration_when_keys_present(self):
        """When the api-key read succeeds, the health check produces the
        configuration + services blocks rather than crashing to 'unhealthy'.

        REGRESSION GUARD: the configuration block read `mollie_settings.webhook_url`,
        a field that does not exist on Mollie Settings (it is stored per-mode as
        testing_webhook_url / live_webhook_url), so the body raised AttributeError
        on EVERY call and the endpoint could only ever return 'unhealthy'. This
        test only stubs the api-key read seam (no key configured on the test site);
        against the pre-fix code it still reports 'unhealthy', and passes after the
        webhook_url field fix."""
        settings = frappe.get_single("Mollie Settings")
        with patch.object(type(settings), "get_active_api_key", return_value="test_key_abc"):
            with patch("frappe.get_single", return_value=settings):
                out = webhooks.webhook_health_check()
        self.assertIn(out["status"], ("healthy", "degraded"))
        self.assertEqual(out["service"], "Mollie Webhook Service")
        cfg = out["configuration"]
        self.assertIn("webhook_url_configured", cfg)
        self.assertTrue(cfg["api_key_configured"])
        self.assertIn("test_mode", cfg)
        self.assertEqual(out["services"].get("webhook_service"), "available")
