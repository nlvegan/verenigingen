"""The critical authentication alert fires on a FAILED-LOGIN RATE, not on the scheduler's own session (#2285).

``alert_if_auth_issues`` used to mail only when ``get_auth_health_status`` reported
``health_status == "error"``, and that is only ever set when ``validate_current_session()`` finds the
CURRENT (scheduler) session invalid, which cannot happen under a scheduler tick. Maintainer ruling
(2026-11-10): count login failures across ALL users in Frappe's Activity Log over a recent window against a
hardcoded threshold; recipients stay as #2254 made them.

What Frappe writes on a failed login was measured on test_site_8 by a real POST to /api/method/login:
``operation='Login', status='Failed', subject='Invalid login credentials'`` (also 'Incorrect password',
'User disabled or missing'), ``user`` = the typed name even when no such User exists, and ``creation`` on the
SITE clock (Asia/Kolkata there) while the database's ``NOW()`` is UTC. The window is therefore cut from
``now_datetime()``, never from SQL ``NOW()``. (``test_the_window_edge`` catches a ``NOW()`` cutoff ONLY on a
site whose zone differs from the database's, like test_site_8; CI is UTC/UTC, so there it cannot tell the two
apart.) The ``operation == "Login"`` filter is equivalent today: ``LoginManager.fail`` is the only writer of
``status='Failed'`` Activity Log rows, so no test can pin it with a real non-Login row. Rows here come from Frappe's own writer
(``add_authentication_log``); window-edge rows are then moved with ``db.set_value`` on ``creation``
(probe shortcut: no real login can be made at a past instant).

Mock justification: only the EmailService factory (the outgoing-mail boundary) is stubbed.

Run:
    bench --site test_site_8 run-tests --app verenigingen --module verenigingen.tests.test_auth_failed_login_rate_alert_2285
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import frappe
from frappe.core.doctype.activity_log.activity_log import add_authentication_log
from frappe.utils import now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.notification_state import own_notification_keys
from verenigingen.utils import auth_monitoring
from verenigingen.utils.auth_monitoring import (
    FAILED_LOGIN_ALERT_THRESHOLD,
    FAILED_LOGIN_WINDOW_HOURS,
    alert_if_auth_issues,
    count_recent_failed_logins,
)
from verenigingen.utils.constants import Roles

CONFIG = "Verenigingen Email Configuration"
KEY = "auth_monitoring_alert"
PROFILE = "Verenigingen System Administrator"
MODULE = "verenigingen.utils.auth_monitoring"


class TestAuthFailedLoginRateAlert2285(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        own_notification_keys(self, KEY)
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", "")
        # Rows a previous run (or the site's history) left in the window would move every boundary below.
        frappe.db.delete("Activity Log", {"operation": "Login", "status": "Failed"})
        self.holder = self._make_profile_holder()
        self.mail = MagicMock(name="EmailService")
        self.mail.send_simple_email.return_value = MagicMock(success=True, error_message=None)
        patcher = patch(f"{MODULE}.get_email_service", return_value=self.mail)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_profile_holder(self):
        if not frappe.db.exists("Role Profile", PROFILE):
            doc = frappe.get_doc({"doctype": "Role Profile", "role_profile": PROFILE})
            doc.append("roles", {"role": Roles.SYSTEM_MANAGER})
            doc.insert(ignore_permissions=True)
            self.addCleanup(frappe.delete_doc, "Role Profile", PROFILE, force=True, ignore_permissions=True)
        email = f"holder-2285-{frappe.generate_hash(length=5)}@example.org"
        user = self.create_test_user(email, roles=[Roles.SYSTEM_MANAGER])
        user.append("role_profiles", {"role_profile": PROFILE})
        user.save()
        return email

    def _failures(self, count, subject="Invalid login credentials", age=timedelta(minutes=5), distinct=True):
        """``count`` real Failed Login rows aged ``age``, by default one per DISTINCT typed username."""
        names = []
        for i in range(count):
            who = f"nobody-2285-{frappe.generate_hash(length=6)}" if distinct else "same-user-2285"
            add_authentication_log(subject, who, operation="Login", status="Failed")
            names.append(frappe.get_all("Activity Log", filters={"user": who}, order_by="creation desc", limit=1, pluck="name")[0])
        stamp = now_datetime() - age
        for name in names:
            frappe.db.set_value("Activity Log", name, "creation", stamp, update_modified=False)
        return names

    def _alert_mails(self):
        return self.mail.send_simple_email.call_args_list

    def test_below_the_threshold_nobody_is_mailed(self):
        self._failures(FAILED_LOGIN_ALERT_THRESHOLD - 1)
        alert_if_auth_issues()
        self.assertEqual(self._alert_mails(), [])

    def test_at_the_threshold_across_distinct_users_the_profile_holders_are_mailed(self):
        # one failure per user: a per-user rule would see 1 each and stay silent
        self._failures(FAILED_LOGIN_ALERT_THRESHOLD)
        alert_if_auth_issues()
        self.assertEqual(len(self._alert_mails()), 1)
        kwargs = self._alert_mails()[0].kwargs
        self.assertEqual(kwargs["notification_key"], KEY)
        self.assertIn(self.holder, kwargs["recipients"])
        self.assertIn(str(FAILED_LOGIN_ALERT_THRESHOLD), kwargs["message"])
        self.assertNotIn("Administrator", kwargs["recipients"])

    def test_the_alert_does_not_consult_the_scheduler_session_health_check(self):
        """The old trigger: a broken CURRENT session. It must neither fire nor suppress the alert now."""
        broken = {"success": True, "health_status": "error", "warnings": ["w"], "invalid_sessions": 3,
                  "recent_errors": {"error_count": 9}}
        with patch(f"{MODULE}.get_auth_health_status", return_value=broken) as health:
            alert_if_auth_issues()
        self.assertEqual(self._alert_mails(), [], "an invalid current session alone is not a failed-login rate")
        health.assert_not_called()
        self._failures(FAILED_LOGIN_ALERT_THRESHOLD)
        with patch(f"{MODULE}.get_auth_health_status", side_effect=RuntimeError("health check down")):
            alert_if_auth_issues()
        self.assertEqual(len(self._alert_mails()), 1, "a failing health snapshot must not hide a login flood")

    def test_only_failed_login_rows_count(self):
        self._failures(FAILED_LOGIN_ALERT_THRESHOLD - 1)
        for _ in range(FAILED_LOGIN_ALERT_THRESHOLD * 2):
            add_authentication_log("Logged In", f"ok-2285-{frappe.generate_hash(length=6)}", status="Success")
        add_authentication_log("Logged Out", "ok-2285-out", operation="Logout", status="Success")
        self.assertEqual(count_recent_failed_logins(), FAILED_LOGIN_ALERT_THRESHOLD - 1)
        alert_if_auth_issues()
        self.assertEqual(self._alert_mails(), [])

    def test_the_window_edge(self):
        """Just inside counts, just outside does not. Sized so only the inside rows can reach the threshold."""
        edge = timedelta(hours=FAILED_LOGIN_WINDOW_HOURS)
        self._failures(FAILED_LOGIN_ALERT_THRESHOLD - 1, age=edge - timedelta(minutes=1))
        self._failures(5, age=edge + timedelta(minutes=1))
        self.assertEqual(count_recent_failed_logins(), FAILED_LOGIN_ALERT_THRESHOLD - 1)
        alert_if_auth_issues()
        self.assertEqual(self._alert_mails(), [], "rows older than the window must not tip a below-threshold count")
        self._failures(1, age=edge - timedelta(minutes=1))
        self.assertEqual(count_recent_failed_logins(), FAILED_LOGIN_ALERT_THRESHOLD)
        alert_if_auth_issues()
        self.assertEqual(len(self._alert_mails()), 1)

    def test_every_failure_subject_frappe_writes_counts(self):
        subjects = ("Invalid login credentials", "Incorrect password", "User disabled or missing")
        for subject in subjects:
            self._failures(1, subject=subject)
        self.assertEqual(count_recent_failed_logins(), len(subjects))

    def test_with_no_recipient_the_alert_leaves_an_error_log_row(self):
        """#2277 item 1: no recipient used to mean a silent skip."""
        self._failures(FAILED_LOGIN_ALERT_THRESHOLD)
        with patch.object(auth_monitoring, "get_auth_alert_recipients", return_value=[]):
            before = frappe.db.count("Error Log", {"method": ["like", "%auth_monitoring%"]})
            alert_if_auth_issues()
        self.assertEqual(self._alert_mails(), [])
        self.assertEqual(frappe.db.count("Error Log", {"method": ["like", "%auth_monitoring%"]}), before + 1)

    def test_a_refused_send_is_not_reported_as_sent(self):
        """#2277 item 3: a skipped/failed send result must be recorded, not logged as 'sent'."""
        self.mail.send_simple_email.return_value = MagicMock(success=False, error_message="key disabled")
        self._failures(FAILED_LOGIN_ALERT_THRESHOLD)
        before = frappe.db.count("Error Log", {"method": ["like", "%auth_monitoring%"]})
        alert_if_auth_issues()
        self.assertEqual(frappe.db.count("Error Log", {"method": ["like", "%auth_monitoring%"]}), before + 1)
