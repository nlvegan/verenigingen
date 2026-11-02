"""#2000: monitoring alerts and the daily report go to the users holding the
Verenigingen System Administrator role profile, never to a literal address.

Fixture shortcut, stated: users are given the profile through
``grant_matching_role_profiles`` (the real ``role_profiles`` child-table write);
pre-existing holders on the site are disabled with ``db.set_value`` only so the
expected recipient set is exactly the fixture's. Teardown rolls that back.
"""

import frappe
from frappe.utils import now

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles
from verenigingen.utils.alert_manager import ALERT_RECIPIENT_ROLE_PROFILE, AlertManager

NO_RECIPIENT_TITLE = "Monitoring alert not sent: no recipients"


class TestAlertManagerRecipients(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # EmailService refuses to queue without a default outgoing Email Account.
        if not frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}):
            account = frappe.new_doc("Email Account")
            account.email_account_name = "Test Outgoing"
            account.email_id = "test-outgoing@example.com"
            account.enable_outgoing = 1
            account.default_outgoing = 1
            account.smtp_server = "localhost"
            account.smtp_port = 25
            account.flags.ignore_validate = True
            account.insert(ignore_permissions=True)
        self.uid = frappe.generate_hash(length=8).lower()
        # Only the fixture users hold the profile; the site may carry others.
        for holder in frappe.get_all(
            "User Role Profile",
            filters={"role_profile": ALERT_RECIPIENT_ROLE_PROFILE, "parenttype": "User"},
            pluck="parent",
        ):
            frappe.db.set_value("User", holder, "enabled", 0)

    def _make_alert_user(self, label, profile=None, enabled=1):
        email = f"alert-{label}-{self.uid}@test.invalid"
        user = self.create_test_user(email, roles=["System Manager"], enabled=enabled)
        if profile:
            grant_matching_role_profiles(email, profile)
            # a disabled holder: the save above re-enables nothing, so set it last
            frappe.db.set_value("User", email, "enabled", enabled)
        return user.email

    def _sent_to(self):
        recipients = []
        for mail in self.captured_emails:
            recipients.extend(mail["recipients"] or [])
        return recipients

    def _no_recipient_logs(self, since):
        return frappe.get_all(
            "Error Log",
            filters={"creation": [">=", since], "method": NO_RECIPIENT_TITLE},
            pluck="name",
        )

    def test_profile_holder_receives_and_others_do_not(self):
        holder = self._make_alert_user("holder", ALERT_RECIPIENT_ROLE_PROFILE)
        other_profile = self._make_alert_user("vadmin", "Verenigingen Administrator")
        no_profile = self._make_alert_user("plain")

        recipients = AlertManager().get_alert_recipients()

        self.assertIn(holder, recipients)
        self.assertNotIn(other_profile, recipients)
        self.assertNotIn(no_profile, recipients)
        self.assertEqual(sorted(recipients), [holder])

    def test_disabled_holder_does_not_receive(self):
        enabled_holder = self._make_alert_user("on", ALERT_RECIPIENT_ROLE_PROFILE)
        disabled_holder = self._make_alert_user("off", ALERT_RECIPIENT_ROLE_PROFILE, enabled=0)

        recipients = AlertManager().get_alert_recipients()

        self.assertIn(enabled_holder, recipients)
        self.assertNotIn(disabled_holder, recipients)

    def _assert_sent_only_to(self, holder, other_profile, subject_part):
        subjects = [mail["subject"] for mail in self.captured_emails]
        self.assertTrue(any(subject_part in s for s in subjects), subjects)
        sent_to = self._sent_to()
        self.assertEqual(set(sent_to), {holder})
        self.assertNotIn(other_profile, sent_to)
        self.assertFalse([r for r in sent_to if "dev.veganisme.net" in r])

    def test_send_alert_goes_to_the_holder_only(self):
        holder = self._make_alert_user("holder", ALERT_RECIPIENT_ROLE_PROFILE)
        other_profile = self._make_alert_user("vadmin", "Verenigingen Administrator")

        AlertManager().send_alert("TEST_ALERT", "LOW", f"probe {self.uid}")

        self._assert_sent_only_to(holder, other_profile, f"probe {self.uid}")

    def test_daily_report_goes_to_the_holder_only(self):
        holder = self._make_alert_user("holder", ALERT_RECIPIENT_ROLE_PROFILE)
        other_profile = self._make_alert_user("vadmin", "Verenigingen Administrator")

        AlertManager().generate_daily_report()

        self._assert_sent_only_to(holder, other_profile, "Daily Monitoring Report")

    def test_nobody_with_the_profile_queues_nothing_and_logs(self):
        self._make_alert_user("vadmin", "Verenigingen Administrator")  # real row for a wrong fix to find
        since = now()
        self.expectErrorLog(NO_RECIPIENT_TITLE)

        manager = AlertManager()
        with self.assertErrorLog(NO_RECIPIENT_TITLE):
            manager.send_alert("TEST_ALERT", "LOW", f"probe {self.uid}")
        with self.assertErrorLog(NO_RECIPIENT_TITLE):
            manager.generate_daily_report()

        self.assertEqual(self._sent_to(), [])
        self.assertEqual(len(self._no_recipient_logs(since)), 2)
