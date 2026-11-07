"""#2000: monitoring email goes to role-profile holders, never to a literal address.

Technical alerts reach the Verenigingen System Administrator profile; business/finance
alerts and the daily report reach the Verenigingen Administrator profile, each group with
its own notification key (so its own cooldown).

Fixture shortcut, stated: users are given the profile through
``grant_matching_role_profiles`` (the real ``role_profiles`` child-table write);
pre-existing holders on the site are disabled with ``db.set_value`` only so the
expected recipient set is exactly the fixture's. Teardown rolls that back.
"""

import frappe
from frappe.utils import now

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles
from verenigingen.utils.alert_manager import (
    BUSINESS_ALERT_TYPES,
    BUSINESS_GROUP,
    NO_RECIPIENTS_LOG_TITLE,
    TECHNICAL_GROUP,
    UNSENT_LOG_CACHE_PREFIX,
    UNSENT_LOG_TITLE,
    AlertManager,
    alert_group_for,
)

# Literals on purpose: deriving them from ALERT_GROUPS would let a swap in production code pass.
SYSADMIN = "Verenigingen System Administrator"
VADMIN = "Verenigingen Administrator"
TECH_KEY = "system_alert"
BIZ_KEY = "business_monitoring_alert"
TECH_TYPE = "HIGH_ERROR_RATE"
BIZ_TYPE = "SEPA_COMPLIANCE"


def _snapshot_rows():
    """Plain copy of the Email Notification Type child rows (#2029)."""
    fields = [
        f.fieldname for f in frappe.get_meta("Email Notification Type").fields if f.fieldtype != "Section Break"
    ]
    config = frappe.get_single("Verenigingen Email Configuration")
    return [{f: r.get(f) for f in fields} for r in config.notification_types]


def _restore_rows(rows):
    config = frappe.get_single("Verenigingen Email Configuration")
    config.set("notification_types", rows)
    config.save()


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
        # The once-a-day Error Log guard lives in the (non-rolled-back) cache.
        for title in (NO_RECIPIENTS_LOG_TITLE, UNSENT_LOG_TITLE):
            for scope in (SYSADMIN, VADMIN, TECHNICAL_GROUP, BUSINESS_GROUP):
                frappe.cache().delete_value(f"{UNSENT_LOG_CACHE_PREFIX}:{title}:{scope}")
        # Own the rows by hand (kept; singleton_backup has restored child tables since #2091, see #2159).
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        self._set_alert_rows(TECH_KEY, 1)
        self._set_alert_rows(BIZ_KEY, 1)
        # Only the fixture users hold the profiles; the site may carry others.
        for profile in (SYSADMIN, VADMIN):
            for holder in frappe.get_all(
                "User Role Profile",
                filters={"role_profile": profile, "parenttype": "User"},
                pluck="parent",
            ):
                frappe.db.set_value("User", holder, "enabled", 0)

    def _set_alert_rows(self, key, enabled, cooldown_minutes=0):
        """EmailService skips a key whose Email Configuration row is missing or off, so own that state
        (sites differ: only those seeded by #1959 have it). Rolled back at teardown.
        enabled=None removes the row."""
        config = frappe.get_single("Verenigingen Email Configuration")
        config.set(
            "notification_types",
            [r for r in config.notification_types if r.notification_key != key],
        )
        if enabled is not None:
            config.append(
                "notification_types",
                {
                    "notification_key": key,
                    "label": key,
                    "category": "System",
                    "recipient_policy": "Role-Based",
                    "recipient_roles": "System Manager",
                    "cooldown_minutes": cooldown_minutes,
                    "enabled": enabled,
                },
            )
        config.save()

    def _make_alert_user(self, label, profiles=(), enabled=1):
        """A user holding exactly ``profiles``, in order. Frappe mirrors only the FIRST into
        User.role_profile_name, so single-profile holders carry an unrelated profile first and a
        lookup on the legacy field cannot find them."""
        email = f"alert-{label}-{self.uid}@test.invalid"
        user = self.create_test_user(email, roles=["System Manager"], enabled=enabled)
        if profiles:
            grant_matching_role_profiles(email, ["Verenigingen Member", *profiles])
            # a disabled holder: the save above re-enables nothing, so set it last
            frappe.db.set_value("User", email, "enabled", enabled)
        return user.email

    def _four_users(self):
        return {
            "tech": self._make_alert_user("tech", [SYSADMIN]),
            "biz": self._make_alert_user("biz", [VADMIN]),
            "both": self._make_alert_user("both", [SYSADMIN, VADMIN]),
            "plain": self._make_alert_user("plain"),
        }

    def _sent_to(self):
        recipients = []
        for mail in self.captured_emails:
            recipients.extend(mail["recipients"] or [])
        return recipients

    def _alert_error_logs(self, since, title, needle):
        return frappe.get_all(
            "Error Log",
            filters={"creation": [">=", since], "method": title, "error": ["like", f"%{needle}%"]},
            pluck="name",
        )

    # --- who is a recipient -------------------------------------------------------------

    def test_profile_holder_receives_and_others_do_not(self):
        users = self._four_users()

        recipients = AlertManager().get_alert_recipients(SYSADMIN)

        self.assertEqual(sorted(recipients), sorted([users["tech"], users["both"]]))
        self.assertNotIn(users["biz"], recipients)
        self.assertNotIn(users["plain"], recipients)

    def test_disabled_holder_does_not_receive(self):
        enabled_holder = self._make_alert_user("on", [SYSADMIN])
        disabled_holder = self._make_alert_user("off", [SYSADMIN], enabled=0)

        recipients = AlertManager().get_alert_recipients(SYSADMIN)

        self.assertIn(enabled_holder, recipients)
        self.assertNotIn(disabled_holder, recipients)

    def test_holder_without_an_email_is_not_a_recipient(self):
        with_email = self._make_alert_user("mail", [SYSADMIN])
        no_email = self._make_alert_user("nomail", [SYSADMIN])
        # Shortcut: User.email is mandatory on insert, so blank it directly.
        frappe.db.set_value("User", no_email, "email", "")

        recipients = AlertManager().get_alert_recipients(SYSADMIN)

        self.assertIn(with_email, recipients)
        self.assertNotIn("", recipients)
        self.assertEqual(sorted(recipients), [with_email])

    # --- routing ------------------------------------------------------------------------

    def test_alert_type_to_group_mapping_is_pinned(self):
        for alert_type in ("HIGH_ERROR_RATE", "PERFORMANCE_DEGRADATION", "HIGH_JOB_QUEUE", "CRITICAL_ERRORS"):
            self.assertEqual(alert_group_for(alert_type), TECHNICAL_GROUP, alert_type)
        business = (
            "SEPA_COMPLIANCE",
            "HIGH_MEMBER_CHURN",
            "STUCK_DUES_SCHEDULES",
            "DATA_QUALITY_ISSUE",
            "ORPHANED_PAYMENTS",
        )
        for alert_type in business:
            self.assertEqual(alert_group_for(alert_type), BUSINESS_GROUP, alert_type)
        self.assertEqual(set(business), set(BUSINESS_ALERT_TYPES))
        # an alert type nobody mapped is technical
        self.assertEqual(alert_group_for(f"BRAND_NEW_{self.uid}"), TECHNICAL_GROUP)
        self.assertEqual(alert_group_for("TEST_ALERT"), TECHNICAL_GROUP)

    def test_technical_alert_reaches_only_system_administrator_holders(self):
        users = self._four_users()

        AlertManager().send_alert(TECH_TYPE, "LOW", f"probe {self.uid}")

        self.assertEqual(sorted(self._sent_to()), sorted([users["tech"], users["both"]]))

    def test_business_alert_reaches_only_administrator_holders(self):
        users = self._four_users()

        AlertManager().send_alert(BIZ_TYPE, "LOW", f"probe {self.uid}")

        self.assertEqual(sorted(self._sent_to()), sorted([users["biz"], users["both"]]))

    def test_daily_report_reaches_only_administrator_holders(self):
        users = self._four_users()

        AlertManager().generate_daily_report()

        self.assertIn("Daily Monitoring Report", [m["subject"] for m in self.captured_emails])
        self.assertEqual(sorted(self._sent_to()), sorted([users["biz"], users["both"]]))

    def test_a_holder_of_both_profiles_gets_each_kind_once(self):
        users = self._four_users()
        manager = AlertManager()

        manager.send_alert(TECH_TYPE, "LOW", f"tech {self.uid}")
        manager.send_alert(BIZ_TYPE, "LOW", f"biz {self.uid}")

        for mail in self.captured_emails:
            self.assertEqual((mail["recipients"] or []).count(users["both"]), 1, mail["subject"])
        self.assertEqual(self._sent_to().count(users["both"]), 2)

    # --- per-group cooldown (#2003) -------------------------------------------------------

    def test_each_group_has_its_own_cooldown(self):
        both = self._make_alert_user("both", [SYSADMIN, VADMIN])
        self._set_alert_rows(TECH_KEY, 1, cooldown_minutes=60)
        self._set_alert_rows(BIZ_KEY, 1, cooldown_minutes=60)
        manager = AlertManager()

        manager.send_alert(BIZ_TYPE, "LOW", f"low business {self.uid}")
        manager.send_alert(TECH_TYPE, "CRITICAL", f"critical technical {self.uid}")

        subjects = [m["subject"] for m in self.captured_emails]
        self.assertTrue(any("low business" in s for s in subjects), subjects)
        self.assertTrue(any("critical technical" in s for s in subjects), subjects)
        # control: the cooldown is really on, a second business alert is held back
        manager.send_alert(BIZ_TYPE, "LOW", f"low business again {self.uid}")
        self.assertFalse(any("low business again" in m["subject"] for m in self.captured_emails))
        self.assertEqual(self._sent_to().count(both), 2)

    # --- HIGH and CRITICAL bypass the cooldown, LOW and MEDIUM do not (#2003 ruling) ---------

    def _cooldown_fixture(self):
        """One technical recipient, a 60-minute cooldown, and an empty cooldown cache."""
        tech = self._make_alert_user("tech", [SYSADMIN])
        self._set_alert_rows(TECH_KEY, 1, cooldown_minutes=60)
        # delete_keys: get_keys + delete_value is a no-op on this cache wrapper.
        frappe.cache().delete_keys("email_cooldown:*")
        self.addCleanup(frappe.cache().delete_keys, "email_cooldown:*")
        return tech

    def _mailed(self, needle):
        return [m["subject"] for m in self.captured_emails if needle in m["subject"]]

    def test_critical_after_low_in_the_window_is_still_mailed(self):
        self._cooldown_fixture()
        manager = AlertManager()

        manager.send_alert(TECH_TYPE, "LOW", f"low {self.uid}")
        manager.send_alert(TECH_TYPE, "CRITICAL", f"critical {self.uid}")

        self.assertEqual(len(self._mailed(f"low {self.uid}")), 1)
        self.assertEqual(len(self._mailed(f"critical {self.uid}")), 1)

    def test_high_behaves_like_critical(self):
        self._cooldown_fixture()
        manager = AlertManager()

        manager.send_alert(TECH_TYPE, "LOW", f"low {self.uid}")
        manager.send_alert(TECH_TYPE, "HIGH", f"high {self.uid}")

        self.assertEqual(len(self._mailed(f"high {self.uid}")), 1)

    def test_critical_after_critical_is_mailed_both_times(self):
        self._cooldown_fixture()
        manager = AlertManager()

        manager.send_alert(TECH_TYPE, "CRITICAL", f"crit one {self.uid}")
        manager.send_alert(TECH_TYPE, "CRITICAL", f"crit two {self.uid}")

        self.assertEqual(len(self._mailed(f"crit one {self.uid}")), 1)
        self.assertEqual(len(self._mailed(f"crit two {self.uid}")), 1)

    def test_low_and_medium_stay_rate_limited(self):
        self._cooldown_fixture()
        manager = AlertManager()

        manager.send_alert(TECH_TYPE, "LOW", f"low one {self.uid}")
        manager.send_alert(TECH_TYPE, "LOW", f"low two {self.uid}")
        manager.send_alert(TECH_TYPE, "MEDIUM", f"medium {self.uid}")

        self.assertEqual(len(self._mailed(f"low one {self.uid}")), 1)
        self.assertEqual(self._mailed(f"low two {self.uid}"), [])
        self.assertEqual(self._mailed(f"medium {self.uid}"), [])

    def test_a_bypassing_send_does_not_start_the_window_for_lower_alerts(self):
        # Choice (coordinator, after review): LOW/MEDIUM are rate-limited among themselves, so a
        # bypassing HIGH/CRITICAL mail must not use up their slot and silently lose them.
        self._cooldown_fixture()
        manager = AlertManager()

        manager.send_alert(TECH_TYPE, "CRITICAL", f"critical {self.uid}")
        manager.send_alert(TECH_TYPE, "MEDIUM", f"medium after {self.uid}")
        manager.send_alert(TECH_TYPE, "LOW", f"low after {self.uid}")

        self.assertEqual(len(self._mailed(f"critical {self.uid}")), 1)
        self.assertEqual(len(self._mailed(f"medium after {self.uid}")), 1)
        # control: the slot the MEDIUM took does rate-limit the LOW behind it
        self.assertEqual(self._mailed(f"low after {self.uid}"), [])

    def test_business_group_bypass_high_after_low_is_mailed(self):
        self._cooldown_fixture()
        self._make_alert_user("biz", [VADMIN])
        self._set_alert_rows(BIZ_KEY, 1, cooldown_minutes=60)
        manager = AlertManager()

        manager.send_alert(BIZ_TYPE, "LOW", f"biz low {self.uid}")
        manager.send_alert(BIZ_TYPE, "LOW", f"biz low again {self.uid}")
        manager.send_alert(BIZ_TYPE, "HIGH", f"biz high {self.uid}")

        self.assertEqual(len(self._mailed(f"biz low {self.uid}")), 1)
        self.assertEqual(self._mailed(f"biz low again {self.uid}"), [])
        self.assertEqual(len(self._mailed(f"biz high {self.uid}")), 1)

    def test_daily_report_is_rate_limited_and_not_lost_after_a_bypassing_alert(self):
        self._cooldown_fixture()
        self._make_alert_user("biz", [VADMIN])
        self._set_alert_rows(BIZ_KEY, 1, cooldown_minutes=60)
        manager = AlertManager()

        # a bypassing HIGH does not use up the report's slot ...
        manager.send_alert(BIZ_TYPE, "HIGH", f"biz high {self.uid}")
        manager.generate_daily_report()
        self.assertEqual(len(self._mailed("Daily Monitoring Report")), 1)
        # ... but the report itself is not a bypass: a second one in the window is held back
        manager.generate_daily_report()
        self.assertEqual(len(self._mailed("Daily Monitoring Report")), 1)
        # and it holds back a LOW on the same key
        manager.send_alert(BIZ_TYPE, "LOW", f"biz low {self.uid}")
        self.assertEqual(self._mailed(f"biz low {self.uid}"), [])

    def test_a_user_opt_out_still_applies_to_a_critical_alert(self):
        # Shortcut: User.unsubscribed is set with db.set_value, and respect_user_preferences is
        # switched on the same way (restored in cleanup); the opt-out filter itself is the real one.
        opted_out = self._make_alert_user("out", [SYSADMIN])
        staying = self._make_alert_user("in", [SYSADMIN])
        self._set_alert_rows(TECH_KEY, 1, cooldown_minutes=60)
        frappe.cache().delete_keys("email_cooldown:*")
        self.addCleanup(frappe.cache().delete_keys, "email_cooldown:*")
        previous = frappe.db.get_single_value("Verenigingen Email Configuration", "respect_user_preferences")
        frappe.db.set_single_value("Verenigingen Email Configuration", "respect_user_preferences", 1)
        self.addCleanup(
            frappe.db.set_single_value, "Verenigingen Email Configuration", "respect_user_preferences", previous
        )
        frappe.db.set_value("User", opted_out, "unsubscribed", 1)

        AlertManager().send_alert(TECH_TYPE, "CRITICAL", f"critical optout {self.uid}")

        recipients = self._sent_to()
        self.assertIn(staying, recipients)  # control: the filter removes one, not everyone
        self.assertNotIn(opted_out, recipients)

    def test_critical_does_not_bypass_a_disabled_key(self):
        self._cooldown_fixture()
        self._set_alert_rows(TECH_KEY, 0, cooldown_minutes=60)
        self.expectErrorLog(UNSENT_LOG_TITLE)

        AlertManager().send_alert(TECH_TYPE, "CRITICAL", f"critical off {self.uid}")

        self.assertEqual(self._mailed(f"critical off {self.uid}"), [])

    # --- nobody / not queued: visible, once a day, per group ------------------------------

    def test_a_group_with_nobody_logs_without_blocking_the_other(self):
        users = {"tech": self._make_alert_user("tech", [SYSADMIN])}  # nobody holds VADMIN
        since = now()
        self.expectErrorLog(NO_RECIPIENTS_LOG_TITLE)
        manager = AlertManager()

        manager.send_alert(TECH_TYPE, "LOW", f"tech {self.uid}")
        with self.assertErrorLog(NO_RECIPIENTS_LOG_TITLE):
            manager.send_alert(BIZ_TYPE, "LOW", f"biz {self.uid}")

        self.assertEqual(self._sent_to(), [users["tech"]])
        self.assertEqual(len(self._alert_error_logs(since, NO_RECIPIENTS_LOG_TITLE, VADMIN)), 1)
        self.assertEqual(len(self._alert_error_logs(since, NO_RECIPIENTS_LOG_TITLE, SYSADMIN)), 0)

    def test_nobody_in_either_group_queues_nothing_and_logs_once_per_group(self):
        self._make_alert_user("plain")  # a user with neither profile
        since = now()
        self.expectErrorLog(NO_RECIPIENTS_LOG_TITLE)
        manager = AlertManager()

        with self.assertErrorLog(NO_RECIPIENTS_LOG_TITLE):
            manager.send_alert(TECH_TYPE, "LOW", f"probe {self.uid}")
        manager.send_alert(TECH_TYPE, "LOW", f"probe again {self.uid}")
        with self.assertErrorLog(NO_RECIPIENTS_LOG_TITLE):
            manager.generate_daily_report()
        manager.send_alert(BIZ_TYPE, "LOW", f"probe biz {self.uid}")

        self.assertEqual(self._sent_to(), [])
        self.assertEqual(len(self._alert_error_logs(since, NO_RECIPIENTS_LOG_TITLE, SYSADMIN)), 1)
        self.assertEqual(len(self._alert_error_logs(since, NO_RECIPIENTS_LOG_TITLE, VADMIN)), 1)

    def test_a_disabled_or_absent_key_stops_only_its_own_group(self):
        users = self._four_users()
        self.expectErrorLog(UNSENT_LOG_TITLE)
        for enabled in (0, None):  # off, and no row at all
            self._set_alert_rows(BIZ_KEY, enabled)
            for scope in (TECHNICAL_GROUP, BUSINESS_GROUP):
                frappe.cache().delete_value(f"{UNSENT_LOG_CACHE_PREFIX}:{UNSENT_LOG_TITLE}:{scope}")
            self.captured_emails.clear()
            since = now()

            manager = AlertManager()
            manager.send_alert(BIZ_TYPE, "LOW", f"biz {self.uid}")
            manager.send_alert(BIZ_TYPE, "LOW", f"biz again {self.uid}")
            manager.send_alert(TECH_TYPE, "LOW", f"tech {self.uid}")

            self.assertEqual(
                sorted(self._sent_to()), sorted([users["tech"], users["both"]]), f"enabled={enabled}"
            )
            rows = self._alert_error_logs(since, UNSENT_LOG_TITLE, "business group")
            self.assertEqual(len(rows), 1, f"enabled={enabled}")
            self.assertEqual(len(self._alert_error_logs(since, UNSENT_LOG_TITLE, "technical group")), 0)

    def test_daily_report_follows_the_business_key_not_the_technical_one(self):
        self._four_users()
        self._set_alert_rows(BIZ_KEY, 0)  # business off, technical still on
        self.expectErrorLog(UNSENT_LOG_TITLE)
        since = now()

        AlertManager().generate_daily_report()

        self.assertEqual(self._sent_to(), [])
        self.assertEqual(len(self._alert_error_logs(since, UNSENT_LOG_TITLE, "business group")), 1)
