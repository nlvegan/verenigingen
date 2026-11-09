"""notify_administrators: the key's own recipients beat the category (#2043, maintainer ruling 2026-11-04).

Real flows and real rows: the two ``termination_overdue`` call sites in ``termination_utils`` and the
``chapter_board_removed`` call site in ``volunteer_sync_service`` are driven for real, against a real
Email Notification Type row, and the Notification Log rows they leave are read back. Nothing in the
resolver is mocked.

Probe shortcuts (stated, not hidden): the Quit member that makes the compliance audit alert is set with
``frappe.db.set_value`` (the same shortcut test_termination_utils uses for that finding); the overdue
request is backdated with ``set_value``.

The category's recipients are made distinguishable from the key's: the Admin category falls back to the
enabled holders of ``fallback_admin_role`` (System Manager), so the category user holds that role.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
    MijnRoodVolunteerSyncService,
)
from verenigingen.services.termination import termination_utils as tu
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.notification_state import own_notification_keys
from verenigingen.utils.notification_helpers import resolve_admin_recipients

CONFIG = "Verenigingen Email Configuration"
OVERDUE_KEY = "termination_overdue"
CHAPTER_KEY = "chapter_board_removed"


def _set_key_row(key, policy, **fields):
    """Reshape the key's (seeded by ``own_notification_keys``) row; the helper restores it afterwards."""
    config = frappe.get_single(CONFIG)
    row = next(r for r in config.notification_types if r.notification_key == key)
    row.recipient_policy = policy
    for field, value in fields.items():
        row.set(field, value)
    config.save()


def _drop_key_row(key):
    config = frappe.get_single(CONFIG)
    config.set("notification_types", [r for r in config.notification_types if r.notification_key != key])
    config.save()


class TestKeyRecipientsBeatCategory(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        own_notification_keys(self, OVERDUE_KEY, CHAPTER_KEY)
        original = frappe.db.get_single_value(CONFIG, "admin_notification_emails")
        self.addCleanup(frappe.db.set_single_value, CONFIG, "admin_notification_emails", original)
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", "")
        suffix = frappe.generate_hash(length=6)
        self.key_user = f"key-2043-{suffix}@example.org"
        self.cat_user = f"cat-2043-{suffix}@example.org"
        self.create_test_user(self.key_user, roles=["Verenigingen Administrator"])
        # System Manager: what the Admin and Chapter categories fall back to.
        self.create_test_user(self.cat_user, roles=["System Manager"])

    def _reached(self, subject_like):
        return set(
            frappe.get_all(
                "Notification Log",
                {"subject": ["like", subject_like], "for_user": ["in", [self.key_user, self.cat_user]]},
                pluck="for_user",
            )
        )

    def _make_overdue_request(self):
        member = self.create_test_member(first_name="Key2043", last_name=f"M{self.uid}")
        request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member.name,
                "termination_type": "Voluntary",
                "status": "Pending",
                "request_date": today(),
                "termination_date": today(),
                "termination_reason": "test reason",
            }
        ).insert()
        frappe.db.set_value("Membership Termination Request", request.name, "request_date", add_days(today(), -10))
        return member

    # ---- real flows -----------------------------------------------------------------------------
    def test_overdue_termination_alert_reaches_the_keys_recipient_not_the_category(self):
        _set_key_row(OVERDUE_KEY, "Fixed", fixed_recipients=self.key_user)
        self._make_overdue_request()
        tu.process_overdue_termination_requests()
        self.assertEqual(self._reached("Overdue Termination Requests%"), {self.key_user})

    def test_compliance_alert_reaches_the_keys_recipient_not_the_category(self):
        self.expectErrorLog("Quit Member Without Executed Termination")
        _set_key_row(OVERDUE_KEY, "Fixed", fixed_recipients=self.key_user)
        member = self.create_test_member(first_name="Key2043", last_name=f"Q{self.uid}")
        frappe.db.set_value("Member", member.name, "status", "Quit")  # probe shortcut
        tu.audit_termination_compliance()
        self.assertEqual(self._reached("Termination Compliance Issues Detected"), {self.key_user})

    def test_chapter_board_removal_alert_reaches_the_keys_recipient_not_the_category(self):
        """Driven through the service's own notifier; the chapter names are plain strings there."""
        _set_key_row(CHAPTER_KEY, "Fixed", fixed_recipients=self.key_user)
        who = f"Board2043 {frappe.generate_hash(length=6)}"
        MijnRoodVolunteerSyncService()._notify_board_membership_change(who, vacated_chapters=["Chapter X"])
        self.assertEqual(self._reached(f"%{who}%"), {self.key_user})

    def test_control_without_a_key_row_the_same_flow_reaches_the_category(self):
        """The category is the fallback: with the key's row reshaped to nobody, the System Manager is reached."""
        # The System Manager fallback includes Administrator; create_system_notification drops it (#1958).
        _set_key_row(OVERDUE_KEY, "Role-Based", recipient_roles=None)
        self._make_overdue_request()
        tu.process_overdue_termination_requests()
        self.assertIn(self.cat_user, self._reached("Overdue Termination Requests%"))
        self.assertNotIn(self.key_user, self._reached("Overdue Termination Requests%"))

    # ---- the fallback ---------------------------------------------------------------------------
    def test_a_key_with_no_row_falls_back_to_the_category_recipients(self):
        """No row: the category's configured admin emails, NOT the service's System Manager fallback."""
        _drop_key_row(OVERDUE_KEY)
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", self.cat_user)
        self.assertEqual(resolve_admin_recipients(notification_key=OVERDUE_KEY, category="Admin"), [self.cat_user])

    def test_a_row_that_resolves_to_nobody_falls_back_to_the_category_recipients(self):
        _set_key_row(OVERDUE_KEY, "Role-Based", recipient_roles=None)
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", self.cat_user)
        self.assertEqual(resolve_admin_recipients(notification_key=OVERDUE_KEY, category="Admin"), [self.cat_user])

    def test_a_key_alone_with_no_row_is_unchanged_and_still_gets_the_service_fallback(self):
        """Control: only a key WITH a category treats a missing row as 'no recipients of its own'."""
        _drop_key_row(OVERDUE_KEY)
        # default_roles names the key_user's role, so reaching the legacy tier would show up as key_user.
        recipients = resolve_admin_recipients(
            notification_key=OVERDUE_KEY, default_roles=["Verenigingen Administrator"]
        )
        self.assertIn(self.cat_user, recipients)  # a System Manager holder: the service fallback
        self.assertNotIn(self.key_user, recipients)

    def test_administrator_stays_excluded_from_the_keys_recipients(self):
        admin_email = "administrator-2043@example.org"
        frappe.db.set_value("User", "Administrator", "email", admin_email, update_modified=False)
        _set_key_row(OVERDUE_KEY, "Fixed", fixed_recipients=f"{admin_email}, {self.key_user}")
        self.assertEqual(
            resolve_admin_recipients(
                notification_key=OVERDUE_KEY, category="Admin", exclude_users=["Administrator"]
            ),
            [self.key_user],
        )

    def test_a_key_row_holding_only_excluded_users_falls_through_to_the_category(self):
        """Maintainer decision on #2043: all-excluded counts as 'resolves to nobody'."""
        admin_email = "administrator-2043@example.org"
        frappe.db.set_value("User", "Administrator", "email", admin_email, update_modified=False)
        _set_key_row(OVERDUE_KEY, "Fixed", fixed_recipients=admin_email)
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", self.cat_user)
        self.assertEqual(
            resolve_admin_recipients(
                notification_key=OVERDUE_KEY, category="Admin", exclude_users=["Administrator"]
            ),
            [self.cat_user],
        )

    def test_key_only_exclusion_is_still_applied_to_the_final_list(self):
        """Control: key-only keeps final-list exclusion, so an Administrator-only key gives nobody."""
        admin_email = "administrator-2043@example.org"
        frappe.db.set_value("User", "Administrator", "email", admin_email, update_modified=False)
        _set_key_row(OVERDUE_KEY, "Fixed", fixed_recipients=admin_email)
        self.assertEqual(
            resolve_admin_recipients(notification_key=OVERDUE_KEY, exclude_users=["Administrator"]), []
        )

    # ---- a key row that names nobody deliverable (reviewer F1/F3) ---------------------------------
    def test_a_key_row_naming_a_disabled_user_falls_through_to_the_category(self):
        disabled = f"disabled-2043-{frappe.generate_hash(length=6)}@example.org"
        self.create_test_user(disabled, roles=["Verenigingen Administrator"])
        frappe.db.set_value("User", disabled, "enabled", 0)
        _set_key_row(OVERDUE_KEY, "Fixed", fixed_recipients=disabled)
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", self.cat_user)
        self.assertEqual(resolve_admin_recipients(notification_key=OVERDUE_KEY, category="Admin"), [self.cat_user])

    def test_a_key_row_naming_an_email_that_is_not_a_user_falls_through_to_the_category(self):
        _set_key_row(OVERDUE_KEY, "Fixed", fixed_recipients="not-a-user-2043@example.org")
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", self.cat_user)
        self.assertEqual(resolve_admin_recipients(notification_key=OVERDUE_KEY, category="Admin"), [self.cat_user])

    def test_only_the_deliverable_recipients_of_the_keys_row_are_kept(self):
        _set_key_row(OVERDUE_KEY, "Fixed", fixed_recipients=f"not-a-user-2043@example.org, {self.key_user}")
        self.assertEqual(resolve_admin_recipients(notification_key=OVERDUE_KEY, category="Admin"), [self.key_user])

    def test_an_administrator_only_key_row_reaches_the_category_through_termination_utils(self):
        """Real call site, exclude_users=None: Administrator never counts as reached, so the System
        Manager category user gets the alert and a Notification Log row proves it."""
        admin_email = "administrator-2043@example.org"
        frappe.db.set_value("User", "Administrator", "email", admin_email, update_modified=False)
        _set_key_row(OVERDUE_KEY, "Fixed", fixed_recipients=admin_email)
        self._make_overdue_request()
        tu.process_overdue_termination_requests()
        self.assertIn(self.cat_user, self._reached("Overdue Termination Requests%"))

    def test_a_key_alone_naming_nobody_deliverable_is_unchanged(self):
        """Control: the deliverable filter is for category+key only; a key alone returns its row as is."""
        _set_key_row(OVERDUE_KEY, "Fixed", fixed_recipients="not-a-user-2043@example.org")
        self.assertEqual(resolve_admin_recipients(notification_key=OVERDUE_KEY), ["not-a-user-2043@example.org"])

    def test_a_category_alone_with_only_excluded_emails_keeps_final_list_exclusion(self):
        """Mirror control: a category-only call does not fall through per tier."""
        admin_email = "administrator-2043@example.org"
        frappe.db.set_value("User", "Administrator", "email", admin_email, update_modified=False)
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", admin_email)
        self.assertEqual(resolve_admin_recipients(category="Admin", exclude_users=["Administrator"]), [])
