"""
Tests for MollieWebhookParser.

Covers the modern JSON event format and the legacy form-data format, plus the
convenience extraction helpers and ping handling. The parser is pure logic
(no external calls) so these assert directly on the returned dict structure.

Target: verenigingen/verenigingen_payments/mollie/utils/webhook_parser.py
"""

import unittest

from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.mollie.utils.webhook_parser import (
    MollieWebhookParser,
    get_webhook_parser,
)


class TestMollieWebhookParser(FrappeTestCase):
    """Test the centralized Mollie webhook parser."""

    # ---------------------------------------------------------------- JSON event
    def test_json_payment_event_extracts_payment_id(self):
        data = {"resource": "event", "type": "payment.paid", "entityId": "tr_abc123"}
        result = MollieWebhookParser.parse_webhook_data(data)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["raw_format"], "json_event")
        self.assertEqual(result["event_type"], "payment")
        self.assertEqual(result["payment_id"], "tr_abc123")
        self.assertIsNone(result["subscription_id"])
        self.assertFalse(result["is_ping"])

    def test_json_payment_event_extracts_embedded_subscription(self):
        data = {
            "resource": "event",
            "type": "payment.paid",
            "entityId": "tr_abc123",
            "_embedded": {"entity": {"subscriptionId": "sub_xyz"}},
        }
        result = MollieWebhookParser.parse_webhook_data(data)

        self.assertEqual(result["payment_id"], "tr_abc123")
        self.assertEqual(result["subscription_id"], "sub_xyz")

    def test_json_subscription_event(self):
        data = {"resource": "event", "type": "subscription.canceled", "entityId": "sub_999"}
        result = MollieWebhookParser.parse_webhook_data(data)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["event_type"], "subscription")
        self.assertEqual(result["subscription_id"], "sub_999")
        self.assertIsNone(result["payment_id"])

    def test_json_ping_event(self):
        data = {"resource": "event", "type": "hook.ping", "entityId": "ping_1"}
        result = MollieWebhookParser.parse_webhook_data(data)

        self.assertTrue(result["is_ping"])
        self.assertEqual(result["status"], "success")
        self.assertIn("ping", result["message"].lower())
        # Ping must not be treated as a payment
        self.assertIsNone(result["payment_id"])

    def test_json_event_missing_entity_id_is_error(self):
        data = {"resource": "event", "type": "payment.paid"}
        result = MollieWebhookParser.parse_webhook_data(data)

        self.assertEqual(result["status"], "error")
        self.assertIn("entityId", result["message"])
        self.assertIsNone(result["payment_id"])

    def test_json_event_unsupported_type_is_error(self):
        data = {"resource": "event", "type": "order.created", "entityId": "ord_1"}
        result = MollieWebhookParser.parse_webhook_data(data)

        self.assertEqual(result["status"], "error")
        self.assertIn("Unsupported event type", result["message"])

    # -------------------------------------------------------------- legacy format
    def test_legacy_payment_id(self):
        result = MollieWebhookParser.parse_webhook_data({"id": "tr_legacy1"})

        self.assertEqual(result["raw_format"], "form_data")
        self.assertEqual(result["event_type"], "payment")
        self.assertEqual(result["payment_id"], "tr_legacy1")

    def test_legacy_subscription_id(self):
        result = MollieWebhookParser.parse_webhook_data({"id": "sub_legacy1"})

        self.assertEqual(result["event_type"], "subscription")
        self.assertEqual(result["subscription_id"], "sub_legacy1")

    def test_legacy_missing_id_is_error(self):
        result = MollieWebhookParser.parse_webhook_data({})

        self.assertEqual(result["status"], "error")
        self.assertIn("Missing ID", result["message"])

    def test_legacy_unsupported_id_prefix_is_error(self):
        result = MollieWebhookParser.parse_webhook_data({"id": "weird_123"})

        self.assertEqual(result["status"], "error")
        self.assertIn("Unsupported webhook ID format", result["message"])

    def test_parse_handles_non_dict_gracefully(self):
        # webhook_data without .get raises inside try -> caught and returned as error
        result = MollieWebhookParser.parse_webhook_data(None)
        self.assertEqual(result["status"], "error")
        self.assertIn("parsing failed", result["message"].lower())

    # ------------------------------------------------------------ convenience API
    def test_get_payment_id_from_webhook(self):
        data = {"resource": "event", "type": "payment.paid", "entityId": "tr_conv"}
        self.assertEqual(MollieWebhookParser.get_payment_id_from_webhook(data), "tr_conv")

    def test_get_payment_id_returns_none_on_ping(self):
        data = {"resource": "event", "type": "hook.ping", "entityId": "ping"}
        self.assertIsNone(MollieWebhookParser.get_payment_id_from_webhook(data))

    def test_get_payment_id_returns_none_on_error(self):
        self.assertIsNone(MollieWebhookParser.get_payment_id_from_webhook({"id": "weird"}))

    def test_get_subscription_id_from_webhook(self):
        data = {"resource": "event", "type": "subscription.created", "entityId": "sub_conv"}
        self.assertEqual(MollieWebhookParser.get_subscription_id_from_webhook(data), "sub_conv")

    def test_get_subscription_id_returns_none_on_ping(self):
        data = {"resource": "event", "type": "hook.ping", "entityId": "ping"}
        self.assertIsNone(MollieWebhookParser.get_subscription_id_from_webhook(data))

    def test_is_ping_event_true(self):
        self.assertTrue(
            MollieWebhookParser.is_ping_event({"resource": "event", "type": "hook.ping"})
        )

    def test_is_ping_event_false_for_payment(self):
        self.assertFalse(
            MollieWebhookParser.is_ping_event({"resource": "event", "type": "payment.paid"})
        )

    def test_is_ping_event_false_for_legacy(self):
        self.assertFalse(MollieWebhookParser.is_ping_event({"id": "tr_1"}))

    def test_create_ping_response(self):
        resp = MollieWebhookParser.create_ping_response()
        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["event_type"], "ping")

    def test_factory_returns_parser(self):
        self.assertIsInstance(get_webhook_parser(), MollieWebhookParser)


if __name__ == "__main__":
    unittest.main()
