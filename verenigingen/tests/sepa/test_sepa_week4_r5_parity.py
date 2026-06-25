"""Parity tests for Task R5 — Week-4 monitoring DRY consolidation.

These tests pin the behavior that changed when the Week-4 monitoring cluster's
duplicated recipient-resolution, DB-boilerplate, email-dispatch, and severity-enum
code was routed through the Wave-0 shared helpers. They are REFACTOR-PARITY tests:
each asserts that the consolidated path produces the same observable result as the
pre-refactor code.

Scope:
- Severity enum aliasing (exact .value strings + type identity preserved).
- Recipient resolution via the shared resolver (role groups + direct-email merge).
- DB boilerplate: tracking tables created on init + audit rows via insert_audit_row.
- Email dispatch routed through the unified EmailService (an email is queued).
"""

import uuid

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles
from verenigingen.verenigingen_payments.utils.sepa_alerting_system import (
    AlertSeverity,
    SEPAAlertingSystem,
)
from verenigingen.verenigingen_payments.utils.sepa_notification_manager import (
    NotificationPriority,
    NotificationRule,
    SEPANotificationManager,
)
from verenigingen.verenigingen_payments.utils.sepa_rollback_manager import (
    RollbackReason,
    SEPARollbackManager,
)
from verenigingen.verenigingen_payments.utils.shared.recipient_resolver import (
    get_recipients_by_roles,
)
from verenigingen.verenigingen_payments.utils.shared.severity import (
    PriorityLevel,
    Severity,
)


class TestR5SeverityEnumParity(EnhancedTestCase):
    """The aliased enums keep their historical string values and type identity."""

    def test_alert_severity_is_canonical_severity(self):
        # Alias, not a copy: AlertSeverity IS Severity.
        self.assertIs(AlertSeverity, Severity)

    def test_notification_priority_is_canonical_priority(self):
        self.assertIs(NotificationPriority, PriorityLevel)

    def test_alert_severity_values_unchanged(self):
        self.assertEqual(AlertSeverity.INFO.value, "info")
        self.assertEqual(AlertSeverity.WARNING.value, "warning")
        self.assertEqual(AlertSeverity.CRITICAL.value, "critical")
        self.assertEqual(AlertSeverity.EMERGENCY.value, "emergency")
        # Round-trips like the whitelisted get_active_alerts(severity=...) does.
        self.assertEqual(AlertSeverity("critical"), AlertSeverity.CRITICAL)

    def test_notification_priority_values_unchanged(self):
        self.assertEqual(NotificationPriority.LOW.value, "low")
        self.assertEqual(NotificationPriority.MEDIUM.value, "medium")
        self.assertEqual(NotificationPriority.HIGH.value, "high")
        self.assertEqual(NotificationPriority.CRITICAL.value, "critical")
        self.assertEqual(NotificationPriority("high"), NotificationPriority.HIGH)


class TestR5RecipientParity(EnhancedTestCase):
    """Recipient resolution now delegates to get_recipients_by_roles."""

    def test_rule_recipients_resolves_role_group(self):
        # Administrator holds System Manager on a standard site, so the
        # "system_managers" group resolves to at least one enabled email.
        mgr = SEPANotificationManager()
        rule = NotificationRule(
            rule_id="r5_test",
            name="R5 Test",
            conditions={},
            template_id="batch_success",
            recipients=["system_managers"],
        )
        recipients = mgr._get_rule_recipients(rule)
        expected = get_recipients_by_roles([Roles.SYSTEM_MANAGER])
        self.assertEqual(set(recipients), set(expected))
        for r in recipients:
            self.assertIn("@", r)

    def test_rule_recipients_merges_direct_email(self):
        # A literal email entry is preserved alongside resolved role emails.
        mgr = SEPANotificationManager()
        rule = NotificationRule(
            rule_id="r5_direct",
            name="R5 Direct",
            conditions={},
            template_id="batch_success",
            recipients=["system_managers", "ops@example.com"],
        )
        recipients = mgr._get_rule_recipients(rule)
        self.assertIn("ops@example.com", recipients)
        # No duplicates.
        self.assertEqual(len(recipients), len(set(recipients)))

    def test_rule_recipients_ignores_unknown_non_email_group(self):
        mgr = SEPANotificationManager()
        rule = NotificationRule(
            rule_id="r5_unknown",
            name="R5 Unknown",
            conditions={},
            template_id="batch_success",
            recipients=["not_a_group_or_email"],
        )
        self.assertEqual(mgr._get_rule_recipients(rule), [])

    def test_rollback_recipients_returns_role_emails(self):
        mgr = SEPARollbackManager()
        recipients = mgr._get_notification_recipients(RollbackReason.BANK_REJECTION)
        expected = get_recipients_by_roles([Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN])
        self.assertEqual(set(recipients), set(expected))
        for r in recipients:
            self.assertIn("@", r)


class TestR5DbHelperParity(EnhancedTestCase):
    """Tracking tables still created on init; audit rows via insert_audit_row."""

    def setUp(self):
        super().setUp()
        self._audit_ids = []

    def tearDown(self):
        for op_id in self._audit_ids:
            frappe.db.sql("DELETE FROM `tabSEPA_Rollback_Audit` WHERE operation_id = %s", (op_id,))
        frappe.db.commit()
        super().tearDown()

    def test_rollback_tables_created_on_init(self):
        # _ensure_rollback_tables runs in __init__ (kept inline for parity).
        SEPARollbackManager()
        for table in (
            "tabSEPA_Rollback_Operation",
            "tabSEPA_Compensation_Transaction",
            "tabSEPA_Rollback_Audit",
        ):
            exists = frappe.db.sql(f"SHOW TABLES LIKE '{table}'")  # noqa: S608
            self.assertTrue(exists, f"{table} should exist after manager init")

    def test_notification_tables_created_on_init(self):
        SEPANotificationManager()
        for table in (
            "tabSEPA_Notification_Log",
            "tabSEPA_Notification_Preferences",
        ):
            exists = frappe.db.sql(f"SHOW TABLES LIKE '{table}'")  # noqa: S608
            self.assertTrue(exists, f"{table} should exist after manager init")

    def test_audit_entry_inserted_via_helper(self):
        # _create_audit_entry now delegates to insert_audit_row; the row persists.
        mgr = SEPARollbackManager()
        op_id = f"R5_PARITY_{uuid.uuid4().hex[:8].upper()}"
        self._audit_ids.append(op_id)
        mgr._create_audit_entry(operation_id=op_id, action="r5_parity_action", details={"k": "v"})
        frappe.db.commit()
        rows = frappe.db.sql(
            "SELECT action, details FROM `tabSEPA_Rollback_Audit` WHERE operation_id = %s",
            (op_id,),
            as_dict=True,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].action, "r5_parity_action")
        self.assertEqual(frappe.parse_json(rows[0].details), {"k": "v"})


class TestR5EmailDispatchParity(EnhancedTestCase):
    """Alerting email dispatch is routed through the unified EmailService."""

    def test_send_email_notification_uses_email_service(self):
        # Parity: _send_email_notification must route through the unified
        # EmailService.send_simple_email (the cluster norm) with the same
        # recipient / subject / body / SEPA-Alert reference the old make() used.
        # Patching the EmailService is an external-boundary (email side-effect)
        # stub, not a business-logic mock -- the method swallows exceptions, so
        # asserting the call args is the only way to pin real behavior.
        from unittest.mock import MagicMock, patch

        system = SEPAAlertingSystem()
        notification_data = {
            "subject": "R5 parity alert",
            "message": "body",
            "alert_data": {"alert_id": "R5_ALERT_PARITY"},
            "severity": "warning",
        }

        fake_service = MagicMock()
        with patch(
            "verenigingen.verenigingen_payments.utils.sepa_alerting_system.get_email_service",
            return_value=fake_service,
        ):
            system._send_email_notification("ops@example.com", notification_data)

        fake_service.send_simple_email.assert_called_once_with(
            recipients=["ops@example.com"],
            subject="R5 parity alert",
            message="body",
            reference_doctype="SEPA Alert",
            reference_name="R5_ALERT_PARITY",
        )
