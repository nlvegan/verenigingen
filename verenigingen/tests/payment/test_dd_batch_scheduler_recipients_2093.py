"""
The SEPA batch-scheduler alert goes to Verenigingen Financial Manager holders, never Administrator (#2093).

Mock justification: EmailService is the outgoing-mail boundary; recipient resolution runs against real
Verenigingen Email Configuration rows and real Users.

Run:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_dd_batch_scheduler_recipients_2093
"""

import importlib
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import now_datetime

from verenigingen.notification_registry import NOTIFICATION_KEYS
from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_sepa_literal_recipients import (
    _put_key_row,
    _restore_rows,
    _snapshot_rows,
)
from verenigingen.utils.constants import Roles
from verenigingen.verenigingen_payments.api.dd_batch_scheduler import send_batch_creation_notification
from verenigingen.verenigingen_payments.utils import sepa_alerting_system as sas

KEY = "sepa_batch_scheduler_alert"
CONFIG = "Verenigingen Email Configuration"
PATCH = "verenigingen.patches.v2_2.move_scheduler_alert_to_financial_manager"
OLD_STOCK_ROLES = "System Manager, Verenigingen Administrator"


def _key_row():
    return next(r for r in frappe.get_single(CONFIG).notification_types if r.notification_key == KEY)


class _Base(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        old_email = frappe.db.get_value("User", "Administrator", "email")
        self.addCleanup(frappe.db.set_value, "User", "Administrator", "email", old_email, update_modified=False)
        self.admin_email = "administrator-2093s@example.org"
        frappe.db.set_value("User", "Administrator", "email", self.admin_email, update_modified=False)
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", "")
        frappe.db.set_single_value("Verenigingen Payments Settings", "financial_admin_emails", "")
        frappe.clear_cache(doctype="Verenigingen Payments Settings")


class TestSchedulerAlertRecipients(_Base):
    def setUp(self):
        super().setUp()
        suffix = frappe.generate_hash(length=5)
        self.finance = f"fm-live-2093-{suffix}@example.org"
        self.create_test_user(self.finance, roles=[Roles.FINANCIAL_MANAGER])
        self.finance_gone = f"fm-gone-2093-{suffix}@example.org"
        self.create_test_user(self.finance_gone, roles=[Roles.FINANCIAL_MANAGER], enabled=0)
        self.sysmgr = f"sm-only-2093-{suffix}@example.org"
        self.create_test_user(self.sysmgr, roles=[Roles.SYSTEM_MANAGER])
        # Administrator holds the Financial Manager role here, so only the exclusion can keep it out.
        admin = frappe.get_doc("User", "Administrator")
        had_role = any(r.role == Roles.FINANCIAL_MANAGER for r in admin.roles)
        if not had_role:
            admin.append("roles", {"role": Roles.FINANCIAL_MANAGER})
            admin.save(ignore_permissions=True)
            self.addCleanup(self._drop_admin_role)

    def _drop_admin_role(self):
        frappe.db.delete("Has Role", {"parent": "Administrator", "role": Roles.FINANCIAL_MANAGER})

    def _alert_recipients(self):
        result = {"batches_created": 1, "total_invoices": 1}
        # Mock justified: EmailService is the outgoing-mail boundary; recipient resolution runs for real.
        with patch(
            "verenigingen.verenigingen_payments.api.dd_batch_scheduler.get_email_service"
        ) as get_service:
            get_service.return_value = MagicMock()
            send_batch_creation_notification(result)
        send = get_service.return_value.send_simple_email
        self.assertTrue(send.called, "the alert must still be sent when staff resolve")
        for call in send.call_args_list:
            self.assertEqual(call.kwargs["notification_key"], KEY)
        return [r for call in send.call_args_list for r in call.kwargs["recipients"]]

    def test_fresh_seeded_row_reaches_enabled_financial_managers_only(self):
        config = frappe.get_single(CONFIG)
        config.set("notification_types", [r for r in config.notification_types if r.notification_key != KEY])
        config.save()
        ensure_notification_registry_rows()  # the fresh-install / migrate seed
        recipients = self._alert_recipients()
        self.assertIn(self.finance, recipients)  # control: a real enabled holder is reached
        self.assertNotIn(self.finance_gone, recipients)
        self.assertNotIn(self.admin_email, recipients)
        self.assertNotIn("Administrator", recipients)
        self.assertNotIn(self.sysmgr, recipients)  # the seeded audience is Financial Manager, not the admin pair
        self.assertTrue(all("@" in r for r in recipients), recipients)

    def test_configured_key_recipients_win(self):
        _put_key_row(KEY, "Fixed", fixed_recipients="board-2093s@example.org")
        self.assertEqual(self._alert_recipients(), ["board-2093s@example.org"])

    def test_no_row_still_reaches_financial_managers(self):
        """With no row for the key the resolver falls to default_roles, which must be Financial Manager."""
        config = frappe.get_single(CONFIG)
        config.set("notification_types", [r for r in config.notification_types if r.notification_key != KEY])
        config.save()
        recipients = self._alert_recipients()
        self.assertIn(self.finance, recipients)
        self.assertNotIn(self.sysmgr, recipients)
        self.assertNotIn(self.admin_email, recipients)


class TestSeedAndPatch(_Base):
    def _set_row(self, policy, roles, fixed=None):
        _put_key_row(KEY, policy, recipient_roles=roles, fixed_recipients=fixed)

    def test_registry_names_financial_manager_for_the_key(self):
        self.assertEqual(NOTIFICATION_KEYS[KEY].get("recipient_roles"), Roles.FINANCIAL_MANAGER)

    def test_patch_moves_an_untouched_stock_row(self):
        self._set_row("Role-Based", OLD_STOCK_ROLES)
        importlib.import_module(PATCH).execute()
        frappe.clear_document_cache(CONFIG, CONFIG)
        self.assertEqual(_key_row().recipient_roles, Roles.FINANCIAL_MANAGER)

    def test_patch_leaves_a_customised_row_alone(self):
        self._set_row("Role-Based", "Chapter Board Member")
        importlib.import_module(PATCH).execute()
        frappe.clear_document_cache(CONFIG, CONFIG)
        self.assertEqual(_key_row().recipient_roles, "Chapter Board Member")

    def test_patch_leaves_a_fixed_row_alone(self):
        self._set_row("Fixed", OLD_STOCK_ROLES, fixed="board-2093s@example.org")
        importlib.import_module(PATCH).execute()
        frappe.clear_document_cache(CONFIG, CONFIG)
        row = _key_row()
        self.assertEqual((row.recipient_policy, row.recipient_roles), ("Fixed", OLD_STOCK_ROLES))

    def test_patch_leaves_other_keys_with_the_old_stock_roles_alone(self):
        """sepa_batch_error legitimately keeps the admin pair; only the scheduler key moves."""
        self._set_row("Role-Based", OLD_STOCK_ROLES)
        _put_key_row("sepa_batch_error", "Role-Based", recipient_roles=OLD_STOCK_ROLES)
        importlib.import_module(PATCH).execute()
        frappe.clear_document_cache(CONFIG, CONFIG)
        other = next(r for r in frappe.get_single(CONFIG).notification_types if r.notification_key == "sepa_batch_error")
        self.assertEqual(other.recipient_roles, OLD_STOCK_ROLES)
        self.assertEqual(_key_row().recipient_roles, Roles.FINANCIAL_MANAGER)  # control: the target did move

    def test_patch_is_idempotent_and_is_registered(self):
        self._set_row("Role-Based", OLD_STOCK_ROLES)
        patch_module = importlib.import_module(PATCH)
        patch_module.execute()
        patch_module.execute()
        frappe.clear_document_cache(CONFIG, CONFIG)
        self.assertEqual(_key_row().recipient_roles, Roles.FINANCIAL_MANAGER)
        from pathlib import Path

        listing = (Path(frappe.get_app_path("verenigingen")) / "patches.txt").read_text()
        self.assertIn(PATCH, listing)


class TestMonitoringAlertsKeepTheAdminAudience(_Base):
    """The SEPA alerting system (monitoring alerts, escalations, security incidents) is NOT the batch
    scheduler's alert: it has its own key, seeded with the admin pair, so the scheduler's move to
    Financial Managers does not drag it along (#2093 ruling)."""

    def setUp(self):
        super().setUp()
        suffix = frappe.generate_hash(length=5)
        self.finance_only = f"fm-only-2093-{suffix}@example.org"
        self.create_test_user(self.finance_only, roles=[Roles.FINANCIAL_MANAGER])
        self.sysmgr = f"sm-live-2093-{suffix}@example.org"
        self.create_test_user(self.sysmgr, roles=[Roles.SYSTEM_MANAGER])
        self.sysmgr_gone = f"sm-gone-2093-{suffix}@example.org"
        self.create_test_user(self.sysmgr_gone, roles=[Roles.SYSTEM_MANAGER], enabled=0)

    def _recipients(self):
        alert = sas.SEPAAlert(
            alert_id="2093-a",
            alert_type="t",
            severity=sas.AlertSeverity.WARNING,
            title="t",
            message="m",
            details={},
            timestamp=now_datetime(),
        )
        return sas.SEPAAlertingSystem()._get_notification_recipients(alert)

    def test_the_alerting_system_has_its_own_key(self):
        self.assertNotEqual(sas.SEPA_ALERT_NOTIFICATION_KEY, KEY)
        self.assertIn(sas.SEPA_ALERT_NOTIFICATION_KEY, NOTIFICATION_KEYS)

    def test_fresh_seeded_row_is_the_admin_pair_never_finance_only_or_administrator(self):
        config = frappe.get_single(CONFIG)
        config.set(
            "notification_types",
            [r for r in config.notification_types if r.notification_key != sas.SEPA_ALERT_NOTIFICATION_KEY],
        )
        config.save()
        ensure_notification_registry_rows()  # the fresh-install / migrate seed creates the missing row
        row = next(
            r for r in frappe.get_single(CONFIG).notification_types if r.notification_key == sas.SEPA_ALERT_NOTIFICATION_KEY
        )
        self.assertEqual(set(row.recipient_roles.split(", ")), set(Roles.ADMIN_PAIR))
        recipients = self._recipients()
        self.assertIn(self.sysmgr, recipients)  # control: a real enabled holder is reached
        self.assertNotIn(self.sysmgr_gone, recipients)
        self.assertNotIn(self.finance_only, recipients)
        self.assertNotIn(self.admin_email, recipients)
        self.assertNotIn("Administrator", recipients)

    def test_a_fixed_row_on_the_monitoring_key_wins(self):
        _put_key_row(sas.SEPA_ALERT_NOTIFICATION_KEY, "Fixed", fixed_recipients="ops-2093@example.org")
        self.assertEqual(self._recipients(), ["ops-2093@example.org"])
