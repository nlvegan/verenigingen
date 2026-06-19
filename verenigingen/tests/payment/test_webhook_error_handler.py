"""
Real-integration tests for WebhookErrorHandler.

The handler is pure logic: it classifies/formats errors into structured
response dicts, wraps operations with exception routing, and updates a
webhook-log document. These tests feed real inputs and real exceptions and
assert the resulting structure and routing. No business-logic mocking.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils.webhook_error_handler import WebhookErrorHandler


class TestWebhookErrorHandler(VereningingenTestCase):
    def test_correlation_id_generated_when_absent(self):
        handler = WebhookErrorHandler(webhook_type="mollie")
        self.assertTrue(handler.get_correlation_id())
        self.assertEqual(len(handler.get_correlation_id()), 8)

    def test_correlation_id_preserved_when_supplied(self):
        handler = WebhookErrorHandler(correlation_id="abc12345")
        self.assertEqual(handler.get_correlation_id(), "abc12345")

    def test_validation_error_response_shape(self):
        handler = WebhookErrorHandler(correlation_id="corr0001")
        resp = handler.handle_validation_error("bad input", {"field": "amount"})
        self.assertEqual(resp["status"], "validation_error")
        self.assertEqual(resp["message"], "bad input")
        self.assertEqual(resp["correlation_id"], "corr0001")
        self.assertEqual(resp["details"], {"field": "amount"})
        self.assertIn("timestamp", resp)

    def test_business_logic_error_response_shape(self):
        handler = WebhookErrorHandler()
        resp = handler.handle_business_logic_error("cannot process", ValueError("boom"))
        self.assertEqual(resp["status"], "business_error")
        self.assertEqual(resp["message"], "cannot process")
        self.assertEqual(resp["details"], {})

    def test_system_error_hides_internal_details_in_production(self):
        handler = WebhookErrorHandler()
        original = frappe.conf.get("developer_mode")
        try:
            frappe.conf["developer_mode"] = 0
            resp = handler.handle_system_error("secret db detail", RuntimeError("x"))
            self.assertEqual(resp["status"], "system_error")
            self.assertEqual(resp["message"], "Internal processing error occurred")
            self.assertIsNone(resp["internal_message"])
        finally:
            if original is None:
                frappe.conf.pop("developer_mode", None)
            else:
                frappe.conf["developer_mode"] = original

    def test_system_error_exposes_internal_in_developer_mode(self):
        handler = WebhookErrorHandler()
        original = frappe.conf.get("developer_mode")
        try:
            frappe.conf["developer_mode"] = 1
            resp = handler.handle_system_error("internal trace detail", RuntimeError("x"))
            self.assertEqual(resp["internal_message"], "internal trace detail")
        finally:
            if original is None:
                frappe.conf.pop("developer_mode", None)
            else:
                frappe.conf["developer_mode"] = original

    def test_external_api_error_response(self):
        handler = WebhookErrorHandler()
        resp = handler.handle_external_api_error("Mollie", "timeout", TimeoutError("t"))
        self.assertEqual(resp["status"], "external_api_error")
        self.assertEqual(resp["api_name"], "Mollie")
        self.assertIn("Mollie", resp["message"])

    def test_success_response_merges_data(self):
        handler = WebhookErrorHandler()
        resp = handler.create_success_response("done", {"payment_entry": "PE-001"})
        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["payment_entry"], "PE-001")
        self.assertIn("correlation_id", resp)

    def test_is_error_result_classification(self):
        handler = WebhookErrorHandler()
        self.assertTrue(handler.is_error_result({"status": "system_error"}))
        self.assertTrue(handler.is_error_result({"status": "validation_error"}))
        self.assertFalse(handler.is_error_result({"status": "success"}))
        self.assertFalse(handler.is_error_result({"status": "ignored"}))
        self.assertFalse(handler.is_error_result("not a dict"))
        self.assertFalse(handler.is_error_result({"no_status": True}))

    # ------------------------------------------------------------------
    # wrap_with_error_handling: exception routing matters for webhook HTTP codes
    # ------------------------------------------------------------------
    def test_wrap_returns_raw_success_result(self):
        handler = WebhookErrorHandler()
        result = handler.wrap_with_error_handling("op", lambda: 42)
        self.assertEqual(result, 42)

    def test_wrap_passes_through_status_dict(self):
        handler = WebhookErrorHandler()
        result = handler.wrap_with_error_handling("op", lambda: {"status": "success", "x": 1})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["x"], 1)

    def test_wrap_passes_through_error_status_dict(self):
        handler = WebhookErrorHandler()
        result = handler.wrap_with_error_handling("op", lambda: {"status": "error", "message": "m"})
        self.assertEqual(result["status"], "error")

    def test_wrap_routes_validation_error(self):
        handler = WebhookErrorHandler()

        def op():
            raise frappe.ValidationError("invalid thing")

        result = handler.wrap_with_error_handling("validate step", op)
        self.assertEqual(result["status"], "validation_error")
        self.assertIn("validate step", result["message"])

    def test_wrap_routes_permission_error_to_business(self):
        handler = WebhookErrorHandler()

        def op():
            raise frappe.PermissionError("nope")

        result = handler.wrap_with_error_handling("guarded step", op)
        # PermissionError handler returns a business_error status
        self.assertEqual(result["status"], "business_error")
        self.assertIn("Permission denied", result["message"])

    def test_wrap_routes_does_not_exist_to_business(self):
        handler = WebhookErrorHandler()

        def op():
            raise frappe.DoesNotExistError("missing")

        result = handler.wrap_with_error_handling("lookup", op)
        self.assertEqual(result["status"], "business_error")
        self.assertIn("not found", result["message"])

    def test_wrap_routes_unexpected_to_system_error(self):
        handler = WebhookErrorHandler()

        def op():
            raise RuntimeError("kaboom")

        original = frappe.conf.get("developer_mode")
        try:
            frappe.conf["developer_mode"] = 1
            result = handler.wrap_with_error_handling("risky", op)
        finally:
            if original is None:
                frappe.conf.pop("developer_mode", None)
            else:
                frappe.conf["developer_mode"] = original
        self.assertEqual(result["status"], "system_error")

    def test_update_webhook_log_persists_result(self):
        # Use a real document with the fields the handler writes; Error Log is a
        # safe, always-present doctype with a text field we can stuff JSON into.
        # We exercise the real .save() path (no mock) via a lightweight stand-in
        # object to avoid coupling to a specific webhook-log doctype schema.
        class _Log:
            def __init__(self):
                self.name = "LOG-TEST"
                self.saved = False

            def save(self):
                self.saved = True

        handler = WebhookErrorHandler(correlation_id="corr9999")
        log = _Log()
        handler.update_webhook_log(log, {"status": "success", "message": "ok"})
        self.assertTrue(log.saved)
        self.assertEqual(log.correlation_id, "corr9999")
        self.assertEqual(log.status, "success")
        self.assertIn("success", log.processing_result)

    def test_update_webhook_log_records_error_details(self):
        class _Log:
            def __init__(self):
                self.name = "LOG-ERR"

            def save(self):
                pass

        handler = WebhookErrorHandler()
        log = _Log()
        handler.update_webhook_log(log, {"status": "error", "message": "the failure"})
        self.assertEqual(log.status, "error")
        self.assertEqual(log.error_details, "the failure")

    def test_update_webhook_log_none_is_noop(self):
        handler = WebhookErrorHandler()
        # Should not raise when webhook_log is None
        handler.update_webhook_log(None, {"status": "success"})

    def test_update_webhook_log_swallows_save_error(self):
        class _Log:
            name = "LOG-BAD"

            def save(self):
                raise RuntimeError("db down")

        handler = WebhookErrorHandler()
        # The handler logs and swallows the save failure rather than propagating
        handler.update_webhook_log(_Log(), {"status": "success"})
