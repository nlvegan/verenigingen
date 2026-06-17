"""
Integration coverage (Tier-2) for Mollie audit logging — utils/audit.py.

The audit logger writes real `Mollie Audit Log` DocTypes via the framework, so
these tests run against the real DB with no Mollie credentials and no mocks of
the logic under test. Each test asserts that the audit row is actually persisted
with the expected event_type / category / severity / sanitised payload, so a
regression that drops a field or stops writing the row would fail here.

Targets (verenigingen/verenigingen_payments/mollie/utils/audit.py):
  MollieAuditLogger
    - _create_audit_log               (the shared sink: persistence + system-log
                                       escalation on error/critical)
    - log_payment_created / completed / failed
    - log_subscription_created / canceled
    - log_webhook_received (header sanitisation + detailed-logging gate)
    - log_api_call (sensitive-data sanitisation + gate)
    - log_security_event
    - log_configuration_change (secret/key value redaction)
    - _sanitize_api_data (recursive)
    - the enable_audit_logging / log_api_calls / log_webhooks gates
  Module convenience functions:
    - log_mollie_payment_event / log_mollie_webhook_event / log_mollie_security_event
"""

import json

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.utils.audit import (
    MollieAuditLogger,
    log_mollie_payment_event,
    log_mollie_security_event,
    log_mollie_webhook_event,
)


def _latest_log(event_type):
    """Return the most recent Mollie Audit Log row for an event_type, or None."""
    rows = frappe.get_all(
        "Mollie Audit Log",
        filters={"event_type": event_type},
        fields=["name", "event_category", "severity", "description", "event_data", "user"],
        order_by="creation desc",
        limit=1,
    )
    return rows[0] if rows else None


class TestMollieAuditCreateAndGate(EnhancedTestCase):
    """The shared _create_audit_log sink and the settings gates."""

    def _logger_with_settings(self, **overrides):
        """A MollieAuditLogger whose settings are forced (independent of the
        site's Mollie Settings), exercising the gate branches deterministically."""
        logger = MollieAuditLogger()
        base = {
            "enable_audit_logging": True,
            "log_api_calls": True,
            "log_webhooks": True,
            "log_retention_days": 90,
            "detailed_logging": False,
        }
        base.update(overrides)
        logger.log_settings = base
        return logger

    def test_create_audit_log_persists_row(self):
        token = frappe.generate_hash()[:10]
        ev = f"unit_persist_{token}"
        logger = self._logger_with_settings()
        logger._create_audit_log(
            event_type=ev,
            event_category="payment",
            description=f"persist {token}",
            data={"payment_id": f"tr_{token}", "amount": "10.00"},
            severity="info",
        )
        row = _latest_log(ev)
        self.assertIsNotNone(row, "audit row should be persisted")
        self.assertEqual(row.event_category, "payment")
        self.assertEqual(row.severity, "info")
        self.assertIn(token, row.description)
        # event_data is JSON-serialised and round-trips the payload
        payload = json.loads(row.event_data)
        self.assertEqual(payload["payment_id"], f"tr_{token}")
        # user is recorded from the session
        self.assertTrue(row.user)

    def test_payment_created_gate_blocks_when_disabled(self):
        token = frappe.generate_hash()[:10]
        pid = f"tr_disabled_{token}"
        logger = self._logger_with_settings(enable_audit_logging=False)
        logger.log_payment_created({"id": pid, "amount": "5.00"})
        # No payment_created row should exist for this id
        rows = frappe.get_all(
            "Mollie Audit Log",
            filters={"event_type": "payment_created", "event_data": ("like", f"%{pid}%")},
        )
        self.assertEqual(rows, [], "disabled audit logging must not persist a row")

    def test_error_severity_escalates_to_system_log(self):
        """Severity 'error' both persists the audit row and writes an Error Log."""
        token = frappe.generate_hash()[:10]
        ev = f"unit_err_{token}"
        before = frappe.db.count("Error Log", {"error": ("like", f"%{token}%")})
        logger = self._logger_with_settings()
        logger._create_audit_log(
            event_type=ev,
            event_category="payment",
            description=f"boom {token}",
            data={"marker": token},
            severity="error",
        )
        # Audit row persisted
        self.assertIsNotNone(_latest_log(ev))
        # And an Error Log was written carrying the marker
        after = frappe.db.count("Error Log", {"error": ("like", f"%{token}%")})
        self.assertGreater(after, before, "error severity should escalate to Error Log")


class TestMolliePaymentEvents(EnhancedTestCase):
    """log_payment_* event helpers persist categorised rows."""

    def test_payment_created_records_fields(self):
        token = frappe.generate_hash()[:10]
        pid = f"tr_created_{token}"
        MollieAuditLogger().log_payment_created(
            {"id": pid, "amount": "12.50", "currency": "EUR", "customer_id": f"cst_{token}"},
            context={"source": "unit"},
        )
        row = _latest_log("payment_created")
        self.assertIsNotNone(row)
        payload = json.loads(row.event_data)
        self.assertEqual(payload["payment_id"], pid)
        self.assertEqual(payload["currency"], "EUR")
        self.assertEqual(payload["context"]["source"], "unit")

    def test_payment_failed_is_error_severity(self):
        token = frappe.generate_hash()[:10]
        pid = f"tr_failed_{token}"
        # log_payment_failed has no enable gate and always uses severity="error"
        MollieAuditLogger().log_payment_failed(pid, "card_declined", {"code": 422})
        row = _latest_log("payment_failed")
        self.assertIsNotNone(row)
        self.assertEqual(row.severity, "error")
        payload = json.loads(row.event_data)
        self.assertEqual(payload["payment_id"], pid)
        self.assertEqual(payload["failure_reason"], "card_declined")


class TestMollieSubscriptionEvents(EnhancedTestCase):
    def test_subscription_created_and_canceled(self):
        token = frappe.generate_hash()[:10]
        sid = f"sub_{token}"
        MollieAuditLogger().log_subscription_created(
            {"id": sid, "customer_id": f"cst_{token}", "amount": "25.00", "interval": "1 month"}
        )
        created = _latest_log("subscription_created")
        self.assertIsNotNone(created)
        self.assertEqual(created.event_category, "subscription")
        self.assertEqual(json.loads(created.event_data)["subscription_id"], sid)

        MollieAuditLogger().log_subscription_canceled(sid, "member_request")
        canceled = _latest_log("subscription_canceled")
        self.assertIsNotNone(canceled)
        self.assertEqual(json.loads(canceled.event_data)["cancellation_reason"], "member_request")


class TestMollieWebhookAndApiSanitisation(EnhancedTestCase):
    def _logger(self, **overrides):
        logger = MollieAuditLogger()
        base = {
            "enable_audit_logging": True,
            "log_api_calls": True,
            "log_webhooks": True,
            "log_retention_days": 90,
            "detailed_logging": False,
        }
        base.update(overrides)
        logger.log_settings = base
        return logger

    def test_webhook_received_sanitises_sensitive_headers(self):
        token = frappe.generate_hash()[:10]
        self._logger().log_webhook_received(
            {"id": f"tr_wh_{token}", "secretpayload": "x"},
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer should-not-leak",
                "X-Mollie-Signature": "sig-should-not-leak",
            },
        )
        row = _latest_log("webhook_received")
        self.assertIsNotNone(row)
        payload = json.loads(row.event_data)
        # Sensitive headers stripped entirely (not present)
        self.assertIn("Content-Type", payload["headers"])
        self.assertNotIn("Authorization", payload["headers"])
        self.assertNotIn("X-Mollie-Signature", payload["headers"])
        # Non-detailed logging: only id retained from webhook_data
        self.assertEqual(payload["webhook_data"], {"id": f"tr_wh_{token}"})

    def test_webhook_received_gate_blocks_when_disabled(self):
        token = frappe.generate_hash()[:10]
        wid = f"tr_wh_off_{token}"
        self._logger(log_webhooks=False).log_webhook_received({"id": wid}, headers={})
        rows = frappe.get_all(
            "Mollie Audit Log",
            filters={"event_type": "webhook_received", "event_data": ("like", f"%{wid}%")},
        )
        self.assertEqual(rows, [])

    def test_api_call_sanitises_nested_secrets(self):
        token = frappe.generate_hash()[:10]
        # detailed_logging=True so request/response payloads are actually recorded
        self._logger(detailed_logging=True).log_api_call(
            method="POST",
            endpoint=f"/v2/payments?marker={token}",
            request_data={"amount": "1.00", "api_key": "live_secretkey", "nested": {"token": "abc"}},
            response_data={"id": f"tr_{token}"},
        )
        row = _latest_log("api_call")
        self.assertIsNotNone(row)
        payload = json.loads(row.event_data)
        req = payload["request_data"]
        self.assertEqual(req["amount"], "1.00")
        self.assertEqual(req["api_key"], "***")
        # Recursive sanitisation of nested dicts
        self.assertEqual(req["nested"]["token"], "***")

    def test_sanitize_api_data_recursive_direct(self):
        logger = MollieAuditLogger()
        out = logger._sanitize_api_data({"password": "p", "ok": "v", "deep": {"secret": "s", "fine": 1}})
        self.assertEqual(out["password"], "***")
        self.assertEqual(out["ok"], "v")
        self.assertEqual(out["deep"]["secret"], "***")
        self.assertEqual(out["deep"]["fine"], 1)
        # Non-dict input is returned as-is
        self.assertEqual(logger._sanitize_api_data("not-a-dict"), "not-a-dict")


class TestMollieSecurityAndConfigEvents(EnhancedTestCase):
    def test_security_event_severity_passthrough(self):
        token = frappe.generate_hash()[:10]
        MollieAuditLogger().log_security_event(
            "signature_mismatch", f"bad sig {token}", {"marker": token}, severity="critical"
        )
        row = _latest_log("security_signature_mismatch")
        self.assertIsNotNone(row)
        self.assertEqual(row.event_category, "security")
        self.assertEqual(row.severity, "critical")

    def test_configuration_change_redacts_secret_values(self):
        token = frappe.generate_hash()[:10]
        MollieAuditLogger().log_configuration_change(
            setting_name="secret_key", old_value="old-secret", new_value="new-secret", user="tester"
        )
        row = _latest_log("configuration_change")
        self.assertIsNotNone(row)
        payload = json.loads(row.event_data)
        self.assertEqual(payload["old_value"], "***")
        self.assertEqual(payload["new_value"], "***")
        self.assertEqual(payload["changed_by"], "tester")

    def test_configuration_change_keeps_plain_values(self):
        token = frappe.generate_hash()[:10]
        MollieAuditLogger().log_configuration_change(
            setting_name=f"webhook_url_{token}", old_value="http://a", new_value="http://b"
        )
        row = _latest_log("configuration_change")
        payload = json.loads(row.event_data)
        # Non-secret setting names keep real values
        self.assertEqual(payload["new_value"], "http://b")


class TestMollieAuditConvenienceFunctions(EnhancedTestCase):
    def test_log_mollie_payment_event_completed(self):
        token = frappe.generate_hash()[:10]
        pid = f"tr_conv_{token}"
        log_mollie_payment_event("completed", {"id": pid, "amount": "9.99", "method": "ideal"})
        row = _latest_log("payment_completed")
        self.assertIsNotNone(row)
        self.assertEqual(json.loads(row.event_data)["payment_id"], pid)

    def test_log_mollie_webhook_event_error(self):
        token = frappe.generate_hash()[:10]
        log_mollie_webhook_event("error", {"id": f"tr_we_{token}"}, error=f"boom {token}")
        row = _latest_log("webhook_error")
        self.assertIsNotNone(row)
        self.assertEqual(row.severity, "error")
        self.assertIn(token, json.loads(row.event_data)["error_message"])

    def test_log_mollie_security_event_convenience(self):
        token = frappe.generate_hash()[:10]
        log_mollie_security_event("rate_limit", f"too many {token}", {"marker": token})
        row = _latest_log("security_rate_limit")
        self.assertIsNotNone(row)
        # default severity is "warning"
        self.assertEqual(row.severity, "warning")
