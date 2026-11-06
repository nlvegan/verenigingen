"""
Notification Log writers that set ``for_user`` by hand address a User NAME and never Administrator (#2107).

Reference fix: #1958 (``create_system_notification``). Five writers are covered here (the sixth, the stuck
dues schedule alert, is in tests/billing/test_fix_stuck_dues_schedule_api.py next to its fixtures).

Real Users, real Notification Log rows; nothing is mocked. Administrator's email is set to a value that is
not a User name, as on a real site (``admin@example.com``). Probe shortcut: the user whose name differs from
their email is made by writing the email column directly (``db.set_value``), because Frappe's User.validate
forces name == email for every ordinary user.

Run:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.test_notification_log_for_user_2107
"""

import frappe

from verenigingen.services.billing.dues_schedule_creation_service import DuesScheduleCreationService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_sepa_literal_recipients import (
    _put_key_row,
    _restore_rows,
    _snapshot_rows,
)
from verenigingen.utils.constants import Roles
from verenigingen.verenigingen_payments.api import (
    dd_batch_scheduler as sched,
    sepa_batch_notifications as sbn,
)
from verenigingen.verenigingen_payments.utils.sepa_notification_manager import SEPANotificationManager

KEY = "sepa_batch_scheduler_alert"


def _log_users(subject):
    return frappe.get_all("Notification Log", filters={"subject": subject}, pluck="for_user")


class _Base(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        old_email = frappe.db.get_value("User", "Administrator", "email")
        self.addCleanup(frappe.db.set_value, "User", "Administrator", "email", old_email, update_modified=False)
        self.admin_email = "administrator-2107@example.org"
        frappe.db.set_value("User", "Administrator", "email", self.admin_email, update_modified=False)
        self.suffix = frappe.generate_hash(length=6)

    def _make_user(self, label, roles):
        email = f"{label}-2107-{self.suffix}@example.org".lower()
        self.create_test_user(email, roles=roles)
        return email

    def _make_drifted_user(self, roles):
        """Probe shortcut (see module docstring): a user whose email differs from their name."""
        name = self._make_user("drift", roles)
        drifted_email = f"other-2107-{self.suffix}@example.org"
        frappe.db.set_value("User", name, "email", drifted_email, update_modified=False)
        self.assertNotEqual(frappe.db.get_value("User", name, "email"), name, "control: email != name")
        return name, drifted_email


class TestSepaNotificationManagerSystemChannel(_Base):
    def _deliver(self, recipients):
        subject = f"sepa2107 {frappe.generate_hash(length=8)}"
        result = SEPANotificationManager()._create_system_notification(
            {"subject": subject, "message": "m"}, recipients, {}
        )
        return subject, result

    def test_every_recipient_form_lands_on_a_user_name_and_administrator_gets_none(self):
        user = self._make_user("plain", [Roles.FINANCIAL_MANAGER])
        drifted_name, drifted_email = self._make_drifted_user([Roles.FINANCIAL_MANAGER])
        subject, result = self._deliver([user, drifted_email, "Administrator", self.admin_email])
        self.assertCountEqual(_log_users(subject), [user, drifted_name])
        self.assertTrue(result["success"], result)
        self.assertEqual(result["recipients_count"], 2, result)

    def test_only_administrator_creates_nothing(self):
        subject, result = self._deliver(["Administrator", self.admin_email])
        self.assertEqual(_log_users(subject), [])
        self.assertFalse(result["success"], result)


class TestAnalyticsAlertRuleSystemNotification(_Base):
    def _rule(self, *recipients):
        rule = frappe.get_doc(
            {
                "doctype": "Analytics Alert Rule",
                "rule_name": f"AAR 2107 {frappe.generate_hash(length=6)}",
                "alert_type": "Threshold",
                "metric": "Total Members",
                "condition": "Greater Than",
                "threshold_value": 0,
                "check_frequency": "Daily",
                "is_active": 1,
                "send_email": 0,
                "send_system_notification": 1,
            }
        )
        for recipient in recipients:
            rule.append("alert_recipients", {"recipient": recipient, "recipient_type": "User"})
        rule.insert()
        self.track_doc("Analytics Alert Rule", rule.name)
        return rule

    def test_recipients_by_name_reach_users_and_administrator_gets_none(self):
        user = self._make_user("plain", [Roles.FINANCIAL_MANAGER])
        drifted_name, _ = self._make_drifted_user([Roles.FINANCIAL_MANAGER])
        rule = self._rule(user, drifted_name, "Administrator")
        rule.send_notifications({"metric": "Total Members", "value": 5, "threshold": 0})
        self.assertCountEqual(_log_users(f"Analytics Alert: {rule.rule_name}"), [user, drifted_name])


class TestDuesScheduleFailureAlert(_Base):
    def _alert(self):
        member = f"MEM-2107-{self.suffix}"
        DuesScheduleCreationService()._create_failure_alert(member, "MS-2107", "boom", "Validation", 3)
        return f"Dues Schedule Creation Failed - {member}"

    def _eligible(self):
        holders = frappe.get_all(
            "Has Role",
            filters={"role": ["in", [Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN]], "parenttype": "User"},
            pluck="parent",
        )
        return frappe.get_all(
            "User",
            filters={"enabled": 1, "user_type": "System User", "name": ["in", holders or [""]]},
            pluck="name",
        )

    def test_the_alert_reaches_role_holders_and_not_administrator(self):
        user = self._make_user("sysmgr", [Roles.SYSTEM_MANAGER])
        eligible = self._eligible()
        self.assertIn("Administrator", eligible, "control: Administrator is a candidate")
        self.assertIn(user, eligible, "control: the fixture user is a candidate")
        recipients = _log_users(self._alert())
        self.assertNotIn("Administrator", recipients)
        self.assertTrue(set(recipients) <= set(eligible), recipients)
        # Capped at 5 (spam guard). The old query (frappe.get_roles(<role>)) matched nobody at all.
        self.assertTrue(1 <= len(recipients) <= 5, recipients)


class TestDdBatchSchedulerSystemNotification(_Base):
    def setUp(self):
        super().setUp()
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        cache_key = f"{sbn.NO_RECIPIENTS_CACHE_PREFIX}:{KEY}"
        self.addCleanup(frappe.cache().delete_value, cache_key)
        frappe.cache().delete_value(cache_key)
        frappe.db.set_single_value("Verenigingen Email Configuration", "admin_notification_emails", "")
        frappe.db.set_single_value("Verenigingen Payments Settings", "financial_admin_emails", "")
        frappe.clear_cache(doctype="Verenigingen Payments Settings")
        _put_key_row(KEY, "Role-Based", recipient_roles=Roles.FINANCIAL_MANAGER)
        self.count = 7000 + int(self.suffix[:3], 16) % 1000
        self.subject = f"Auto-created {self.count} DD batches"

    def _result(self):
        return {"batches_created": self.count, "total_invoices": 1, "batch_names": ["DD-2107"]}

    def _no_recipient_rows(self):
        return frappe.db.count("Error Log", {"method": sbn.NO_RECIPIENTS_LOG_TITLE})

    def test_notifies_enabled_financial_managers_by_name_never_administrator_or_disabled(self):
        finance = self._make_user("fm", [Roles.FINANCIAL_MANAGER])
        gone = f"fm-gone-2107-{self.suffix}@example.org"
        self.create_test_user(gone, roles=[Roles.FINANCIAL_MANAGER], enabled=0)
        admin = frappe.get_doc("User", "Administrator")
        admin.append("roles", {"role": Roles.FINANCIAL_MANAGER})
        admin.save()
        self.addCleanup(frappe.db.delete, "Has Role", {"parent": "Administrator", "role": Roles.FINANCIAL_MANAGER})
        self.assertIn(
            "Administrator",
            frappe.get_all("Has Role", filters={"role": Roles.FINANCIAL_MANAGER}, pluck="parent"),
            "control: Administrator holds the role",
        )
        sched.create_system_notification(self._result())
        self.assertIn(finance, _log_users(self.subject))
        self.assertNotIn("Administrator", _log_users(self.subject))
        self.assertNotIn(gone, _log_users(self.subject))

    def test_nobody_resolving_leaves_one_error_log_row_not_silence(self):
        frappe.db.delete("Has Role", {"role": Roles.FINANCIAL_MANAGER})
        before = self._no_recipient_rows()
        self.expectErrorLog(sbn.NO_RECIPIENTS_LOG_TITLE)
        with self.assertErrorLog(sbn.NO_RECIPIENTS_LOG_TITLE):
            sched.create_system_notification(self._result())
        self.assertEqual(_log_users(self.subject), [])
        self.assertEqual(self._no_recipient_rows(), before + 1)

    def test_the_email_path_also_says_so_when_nobody_resolves(self):
        frappe.db.delete("Has Role", {"role": Roles.FINANCIAL_MANAGER})
        before = self._no_recipient_rows()
        self.expectErrorLog(sbn.NO_RECIPIENTS_LOG_TITLE)
        with self.assertErrorLog(sbn.NO_RECIPIENTS_LOG_TITLE):
            sched.send_batch_creation_notification(self._result())
        self.assertEqual(self._no_recipient_rows(), before + 1)
