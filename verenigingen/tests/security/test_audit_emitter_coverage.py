"""
Coverage tests for verenigingen/utils/security/audit_emitter.py

AuditEmitter is the simplified facade the API security framework uses. These
tests assert the should_log_operation decision matrix (read-only skip rules,
SKIP_AUDIT_FUNCTIONS, always-log-on-failure) AND that each log_* method emits a
correctly-typed/severitied row into API Audit Log via the real SEPAAuditLogger
(no mocking of the function under test).

Run on test_site_2:
    bench --site test_site_2 run-tests --app verenigingen \
        --module verenigingen.tests.security.test_audit_emitter_coverage
"""

import json

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.audit_emitter import AuditEmitter, get_audit_emitter
from verenigingen.utils.security.types import SecurityLevel


def _latest_api_log(event_type):
    rows = frappe.get_all(
        "API Audit Log",
        filters={"event_type": event_type},
        fields=["event_id", "severity", "user", "details"],
        order_by="creation desc",
        limit=1,
    )
    return rows[0] if rows else None


# Plain module-level functions used as the `func` arg (real callables, real names)
def get_member_profile():
    pass


def export_member_data():
    pass


def can_suspend_member():
    pass


def delete_member():
    pass


class TestShouldLogOperation(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.emitter = get_audit_emitter()

    def test_get_audit_emitter_singleton(self):
        self.assertIsInstance(get_audit_emitter(), AuditEmitter)
        self.assertIs(get_audit_emitter(), get_audit_emitter())

    def test_failed_operation_always_logged(self):
        # Even a read-only, low-security, normally-skipped call logs on failure.
        self.assertTrue(
            self.emitter.should_log_operation(get_member_profile, SecurityLevel.LOW, success=False)
        )
        self.assertTrue(
            self.emitter.should_log_operation(can_suspend_member, SecurityLevel.LOW, success=False)
        )

    def test_skip_audit_function_not_logged_on_success(self):
        self.assertFalse(
            self.emitter.should_log_operation(can_suspend_member, SecurityLevel.HIGH, success=True)
        )

    def test_read_only_skipped_at_low_medium(self):
        self.assertFalse(
            self.emitter.should_log_operation(get_member_profile, SecurityLevel.LOW, success=True)
        )
        self.assertFalse(
            self.emitter.should_log_operation(get_member_profile, SecurityLevel.MEDIUM, success=True)
        )

    def test_read_only_logged_at_high_critical(self):
        self.assertTrue(
            self.emitter.should_log_operation(get_member_profile, SecurityLevel.HIGH, success=True)
        )
        self.assertTrue(
            self.emitter.should_log_operation(get_member_profile, SecurityLevel.CRITICAL, success=True)
        )

    def test_write_operation_always_logged(self):
        for level in (SecurityLevel.LOW, SecurityLevel.MEDIUM, SecurityLevel.HIGH, SecurityLevel.CRITICAL):
            self.assertTrue(
                self.emitter.should_log_operation(delete_member, level, success=True),
                f"write op should log at {level}",
            )


class TestEmitterLogMethods(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.emitter = get_audit_emitter()

    def test_log_access_granted(self):
        with self.assertNoErrorLog():
            self.emitter.log_access_granted(
                user="Administrator",
                operation="export_member_data",
                auth_path="role_profile:Verenigingen Administrator",
                security_level=SecurityLevel.HIGH,
                execution_time=0.123,
                extra_field="ctx",
            )
        row = _latest_api_log("api_call_success")
        self.assertIsNotNone(row)
        self.track_doc("API Audit Log", row.event_id)
        self.assertEqual(row.severity, "info")
        details = json.loads(row.details)
        self.assertEqual(details["operation"], "export_member_data")
        self.assertEqual(details["security_level"], "high")
        self.assertEqual(details["auth_path"], "role_profile:Verenigingen Administrator")
        self.assertEqual(details["execution_time_ms"], 123.0)
        self.assertEqual(details["extra_field"], "ctx")

    def test_log_access_denied(self):
        with self.assertNoErrorLog():
            self.emitter.log_access_denied(
                user="Administrator",
                operation="delete_member",
                reason="insufficient_role",
                security_level=SecurityLevel.CRITICAL,
            )
        row = _latest_api_log("unauthorized_access_attempt")
        self.assertIsNotNone(row)
        self.track_doc("API Audit Log", row.event_id)
        self.assertEqual(row.severity, "warning")
        details = json.loads(row.details)
        self.assertEqual(details["denial_reason"], "insufficient_role")
        self.assertEqual(details["security_level"], "critical")

    def test_log_rate_limit_exceeded(self):
        with self.assertNoErrorLog():
            self.emitter.log_rate_limit_exceeded(
                user="Administrator",
                operation="export_member_data",
                current_count=11,
                max_calls=10,
            )
        row = _latest_api_log("rate_limit_exceeded")
        self.assertIsNotNone(row)
        self.track_doc("API Audit Log", row.event_id)
        self.assertEqual(row.severity, "warning")
        details = json.loads(row.details)
        self.assertEqual(details["current_count"], 11)
        self.assertEqual(details["max_calls"], 10)

    def test_log_validation_failure_persists_event(self):
        # Regression: log_validation_failure referenced
        # AuditEventType.VALIDATION_FAILED, which did not exist in the enum
        # (types.py only defined CSRF_VALIDATION_FAILED) -> AttributeError on
        # every call. The enum value + matching API Audit Log Select option were
        # added; the failure now lands as a durable validation_failed event.
        with self.assertNoErrorLog():
            self.emitter.log_validation_failure(
                user="Administrator",
                operation="create_member",
                errors=["bad email", "missing name"],
            )
        row = _latest_api_log("validation_failed")
        self.assertIsNotNone(row)
        self.track_doc("API Audit Log", row.event_id)
        self.assertEqual(row.severity, "warning")
        details = json.loads(row.details)
        self.assertEqual(details["error_count"], 2)
        self.assertEqual(details["operation"], "create_member")

    def test_log_csrf_failure(self):
        with self.assertNoErrorLog():
            self.emitter.log_csrf_failure(
                user="Administrator",
                operation="submit_form",
                error="missing token",
            )
        row = _latest_api_log("csrf_validation_failed")
        self.assertIsNotNone(row)
        self.track_doc("API Audit Log", row.event_id)
        self.assertEqual(row.severity, "warning")
        details = json.loads(row.details)
        self.assertEqual(details["error"], "missing token")
        self.assertIn("method", details)
        self.assertIn("ip", details)

    def test_log_api_call_success_path(self):
        with self.assertNoErrorLog():
            self.emitter.log_api_call(
                func=delete_member,  # write op -> always logged
                security_level=SecurityLevel.HIGH,
                success=True,
                execution_time=0.05,
            )
        row = _latest_api_log("api_call_success")
        self.assertIsNotNone(row)
        self.track_doc("API Audit Log", row.event_id)
        details = json.loads(row.details)
        self.assertEqual(details["function"], "delete_member")
        self.assertEqual(details["execution_time_ms"], 50.0)

    def test_log_api_call_failure_path(self):
        with self.assertNoErrorLog():
            self.emitter.log_api_call(
                func=get_member_profile,  # read-only but failure -> logged
                security_level=SecurityLevel.LOW,
                success=False,
                error="boom",
            )
        row = _latest_api_log("api_call_failed")
        self.assertIsNotNone(row)
        self.track_doc("API Audit Log", row.event_id)
        self.assertEqual(row.severity, "error")
        details = json.loads(row.details)
        self.assertEqual(details["error"], "boom")
        self.assertEqual(details["function"], "get_member_profile")

    def test_log_api_call_skipped_produces_no_row(self):
        # read-only + low + success -> should_log_operation False -> no emit
        before = frappe.db.count("API Audit Log", {"event_type": "api_call_success"})
        self.emitter.log_api_call(
            func=get_member_profile,
            security_level=SecurityLevel.LOW,
            success=True,
        )
        after = frappe.db.count("API Audit Log", {"event_type": "api_call_success"})
        self.assertEqual(after, before, "skipped operation must not write an audit row")
