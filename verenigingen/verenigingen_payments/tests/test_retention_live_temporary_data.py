"""The single live-capable path: temporary_data deletes aged webhook_validation
Mollie Audit Log rows (and only those) when fully enabled. This is the one
destructive path this project ships; it must be proven end-to-end."""

import frappe
from frappe.utils import add_days, now_datetime

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    DataCategory,
    DataRetentionPolicy,
)


class TestRetentionLiveTemporaryData(VereningingenTestCase):
    def _make_audit_row(self, action, age_days):
        doc = frappe.get_doc(
            {
                "doctype": "Mollie Audit Log",
                "event_type": "webhook_received",
                # "webhook" is not a valid Event Category option (Select field
                # options: payment/subscription/webhook_processing/security/
                # reconciliation/configuration) -- use the valid option.
                "event_category": "webhook_processing",
                "severity": "info",
                "action": action,
                "status": "success",
                "description": "retention test row",
            }
        )
        # Security: test fixture row, no user context.
        doc.insert(ignore_permissions=True)
        # timestamp drives retention; force it directly.
        frappe.db.set_value("Mollie Audit Log", doc.name, "timestamp", add_days(now_datetime(), -age_days))
        self.track_doc("Mollie Audit Log", doc.name)
        return doc.name

    def _policy_live_for_temporary(self):
        policy = DataRetentionPolicy()
        policy.retention_periods[DataCategory.TEMPORARY_DATA] = 30
        policy.category_live_flags = {DataCategory.TEMPORARY_DATA: True}
        return policy

    def test_dry_run_deletes_nothing(self):
        aged = self._make_audit_row("webhook_validation", age_days=60)
        policy = self._policy_live_for_temporary()
        policy.apply_retention_policies(dry_run=True)  # global dry-run wins
        self.assertTrue(frappe.db.exists("Mollie Audit Log", aged))

    def test_live_deletes_only_aged_webhook_validation_rows(self):
        aged = self._make_audit_row("webhook_validation", age_days=60)
        recent = self._make_audit_row("webhook_validation", age_days=1)
        other = self._make_audit_row("payment_created", age_days=60)
        policy = self._policy_live_for_temporary()
        policy.apply_retention_policies(dry_run=False)
        self.assertFalse(frappe.db.exists("Mollie Audit Log", aged))  # purged
        self.assertTrue(frappe.db.exists("Mollie Audit Log", recent))  # too new
        self.assertTrue(frappe.db.exists("Mollie Audit Log", other))  # wrong action
