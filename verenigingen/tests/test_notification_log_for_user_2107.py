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


def _users_logged_2107(subject):
    return frappe.get_all("Notification Log", filters={"subject": subject}, pluck="for_user")


class _Base(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        old_email = frappe.db.get_value("User", "Administrator", "email")
        self.addCleanup(frappe.db.set_value, "User", "Administrator", "email", old_email, update_modified=False)
        self.admin_email = "administrator-2107@example.org"
        frappe.db.set_value("User", "Administrator", "email", self.admin_email, update_modified=False)
        self.suffix = frappe.generate_hash(length=6)

    def _user_2107(self, label, roles):
        email = f"{label}-2107-{self.suffix}@example.org".lower()
        self.create_test_user(email, roles=roles)
        return email

    def _make_drifted_user(self, roles):
        """Probe shortcut (see module docstring): a user whose email differs from their name."""
        name = self._user_2107("drift", roles)
        drifted_email = f"other-2107-{self.suffix}@example.org"
        frappe.db.set_value("User", name, "email", drifted_email, update_modified=False)
        self.assertNotEqual(frappe.db.get_value("User", name, "email"), name, "control: email != name")
        return name, drifted_email


class TestSepaNotificationManagerSystemChannel(_Base):
    def _deliver_2107(self, recipients):
        subject = f"sepa2107 {frappe.generate_hash(length=8)}"
        result = SEPANotificationManager()._create_system_notification(
            {"subject": subject, "message": "m"}, recipients, {}
        )
        return subject, result

    def test_every_recipient_form_lands_on_a_user_name_and_administrator_gets_none(self):
        user = self._user_2107("plain", [Roles.FINANCIAL_MANAGER])
        drifted_name, drifted_email = self._make_drifted_user([Roles.FINANCIAL_MANAGER])
        subject, result = self._deliver_2107([user, drifted_email, "Administrator", self.admin_email])
        self.assertCountEqual(_users_logged_2107(subject), [user, drifted_name])
        self.assertTrue(result["success"], result)
        self.assertEqual(result["recipients_count"], 2, result)

    def test_only_administrator_creates_nothing(self):
        subject, result = self._deliver_2107(["Administrator", self.admin_email])
        self.assertEqual(_users_logged_2107(subject), [])
        self.assertFalse(result["success"], result)


class TestAnalyticsAlertRuleSystemNotification(_Base):
    def _analytics_rule_2107(self, *recipients):
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
        user = self._user_2107("plain", [Roles.FINANCIAL_MANAGER])
        drifted_name, _ = self._make_drifted_user([Roles.FINANCIAL_MANAGER])
        rule = self._analytics_rule_2107(user, drifted_name, "Administrator")
        rule.send_notifications({"metric": "Total Members", "value": 5, "threshold": 0})
        self.assertCountEqual(_users_logged_2107(f"Analytics Alert: {rule.rule_name}"), [user, drifted_name])


class TestDuesScheduleFailureAlert(_Base):
    """The alert goes to the registered key's own audience (#2107, ruling of 2026-11-01), by User name."""

    DUES_KEY = "dues_schedule_creation_failed"

    def setUp(self):
        super().setUp()
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        # A role made for this test: the audience is exactly its enabled holders, whatever the site holds.
        self.role = f"Dues2107 {self.suffix}"
        frappe.get_doc({"doctype": "Role", "role_name": self.role}).insert()
        self.track_doc("Role", self.role)
        _put_key_row(self.DUES_KEY, "Role-Based", recipient_roles=self.role)
        self.member = f"MEM-2107-{self.suffix}"
        self.membership = f"MS-2107-{self.suffix}"
        self.subject = f"Dues Schedule Creation Failed - {self.member}"
        self.addCleanup(frappe.db.delete, "Staff Alert Event", {"reference_name": self.membership})

    def _raise_failure_alert_2107(self):
        DuesScheduleCreationService()._create_failure_alert(self.member, self.membership, "boom", "Validation", 3)

    def _event_outcomes(self):
        return frappe.get_all(
            "Staff Alert Event", filters={"reference_name": self.membership}, pluck="outcome"
        )

    def test_exactly_the_key_audience_by_name_and_never_administrator(self):
        plain = self._user_2107("dues", [self.role])
        drifted_name, _ = self._make_drifted_user([self.role])
        decoy = self._user_2107("decoy", [Roles.SYSTEM_MANAGER])
        gone = f"dues-gone-2107-{self.suffix}@example.org"
        self.create_test_user(gone, roles=[self.role], enabled=0)
        admin = frappe.get_doc("User", "Administrator")
        admin.append("roles", {"role": self.role})
        admin.save()
        self.addCleanup(frappe.db.delete, "Has Role", {"parent": "Administrator", "role": self.role})
        holders = frappe.get_all("Has Role", filters={"role": self.role, "parenttype": "User"}, pluck="parent")
        self.assertCountEqual(holders, [plain, drifted_name, gone, "Administrator"], "control: the audience")
        self.assertIn(decoy, frappe.get_all("Has Role", filters={"role": Roles.SYSTEM_MANAGER}, pluck="parent"))
        self._raise_failure_alert_2107()
        self.assertCountEqual(_users_logged_2107(self.subject), [plain, drifted_name])
        self.assertEqual(self._event_outcomes(), ["Delivered"])

    def test_a_key_with_no_holders_falls_back_to_the_admin_roles_without_administrator(self):
        decoy = self._user_2107("fallback", [Roles.SYSTEM_MANAGER])
        expected = [
            name
            for name in frappe.get_all(
                "User",
                filters={"enabled": 1, "name": ["!=", "Administrator"]},
                pluck="name",
            )
            if set(frappe.get_roles(name)) & set(Roles.ADMIN_PAIR)
        ]
        self.assertIn(decoy, expected, "control: the fixture user is eligible")
        self._raise_failure_alert_2107()
        self.assertCountEqual(_users_logged_2107(self.subject), expected)

    def test_nobody_resolving_leaves_a_trace_not_silence(self):
        """Staff Alert Event (MyISAM) is the trace: outcome 'No recipient', and the alert needs action."""
        frappe.db.delete("Has Role", {"role": ["in", [self.role, *Roles.ADMIN_PAIR]]})
        self._raise_failure_alert_2107()
        self.assertEqual(_users_logged_2107(self.subject), [])
        self.assertEqual(self._event_outcomes(), ["No recipient"])
        self.assertEqual(
            frappe.get_all("Staff Alert Event", filters={"reference_name": self.membership}, pluck="requires_action"),
            [1],
        )


class TestDdBatchSchedulerRecipients(_Base):
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

    def _batch_result_2107(self):
        return {"batches_created": self.count, "total_invoices": 1, "batch_names": ["DD-2107"]}

    def _no_recipient_rows(self):
        return frappe.db.count("Error Log", {"method": sbn.NO_RECIPIENTS_LOG_TITLE})

    def test_nobody_resolving_leaves_one_error_log_row_not_silence(self):
        frappe.db.delete("Has Role", {"role": Roles.FINANCIAL_MANAGER})
        before = self._no_recipient_rows()
        self.expectErrorLog(sbn.NO_RECIPIENTS_LOG_TITLE)
        with self.assertErrorLog(sbn.NO_RECIPIENTS_LOG_TITLE):
            sched.send_batch_creation_notification(self._batch_result_2107())
        self.assertEqual(self._no_recipient_rows(), before + 1)

    def test_a_disabled_key_with_nobody_resolving_is_not_an_error(self):
        _put_key_row(KEY, "Role-Based", recipient_roles=Roles.FINANCIAL_MANAGER, enabled=0)
        frappe.db.delete("Has Role", {"role": Roles.FINANCIAL_MANAGER})
        before = self._no_recipient_rows()
        sched.send_batch_creation_notification(self._batch_result_2107())
        self.assertEqual(self._no_recipient_rows(), before)
