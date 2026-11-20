"""Role-based staff alert recipients never include the Administrator user (#1960, ruling 2026-11-01).

Real rows: Administrator genuinely holds System Manager and Verenigingen Administrator (asserted in
setUp, so the control cannot rot), and a second, real, enabled staff user holds the same role. The
resolvers are called for real and the Notification Log rows left by ``notify_administrators`` are read back.

Probe shortcut (stated): the shared-email case points Administrator's email at the staff user's address with
``frappe.db.set_value``; User.email is not unique, so a real site can be in that state.
"""

import frappe

from verenigingen.services.communication.email_configuration_service import (
    EmailConfigurationService,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.notification_state import own_notification_keys
from verenigingen.utils.notification_helpers import (
    get_notification_recipients,
    notify_administrators,
    resolve_admin_recipients,
)

CONFIG = "Verenigingen Email Configuration"
KEY = "termination_overdue"
ROLE = "Verenigingen Administrator"


def _set_key_row(**fields):
    config = frappe.get_single(CONFIG)
    row = next(r for r in config.notification_types if r.notification_key == KEY)
    for field, value in fields.items():
        row.set(field, value)
    config.save()


class TestNoAdministratorRecipients(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        own_notification_keys(self, KEY)
        original = frappe.db.get_single_value(CONFIG, "admin_notification_emails")
        self.addCleanup(frappe.db.set_single_value, CONFIG, "admin_notification_emails", original)
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", "")
        held = set(frappe.get_all("Has Role", {"parent": "Administrator"}, pluck="role"))
        self.assertTrue({ROLE, "System Manager"} <= held, "control: Administrator must hold the roles")
        self.admin_email = frappe.db.get_value("User", "Administrator", "email")
        self.staff = f"staff-1960-{frappe.generate_hash(length=6)}@example.org"
        self.create_test_user(self.staff, roles=[ROLE])
        self.service = EmailConfigurationService()
        _set_key_row(recipient_policy="Role-Based", recipient_roles=ROLE)

    def _logged_for(self, subject):
        return set(frappe.get_all("Notification Log", {"subject": subject}, pluck="for_user"))

    def _assert_staff_not_admin(self, recipients):
        self.assertIn(self.staff, recipients)
        self.assertNotIn(self.admin_email, recipients)

    def test_key_role_based_recipients(self):
        self._assert_staff_not_admin(self.service.get_recipients_for_notification(KEY))

    def test_fallback_recipients(self):
        frappe.db.set_single_value(CONFIG, "fallback_admin_role", ROLE)
        self._assert_staff_not_admin(self.service._get_fallback_recipients())

    def test_unknown_key_falls_back_without_administrator(self):
        frappe.db.set_single_value(CONFIG, "fallback_admin_role", ROLE)
        self._assert_staff_not_admin(self.service.get_recipients_for_notification("no_such_key_1960"))

    def test_category_recipients(self):
        frappe.db.set_single_value(CONFIG, "fallback_admin_role", ROLE)
        self._assert_staff_not_admin(self.service.get_category_recipients("Admin"))

    def test_legacy_get_notification_recipients(self):
        self._assert_staff_not_admin(get_notification_recipients("no_such_setting_1960", [ROLE]))

    def test_notify_administrators_without_exclude_users_skips_administrator(self):
        subject = f"1960 alert {frappe.generate_hash(length=6)}"
        notify_administrators(subject=subject, message="x", notification_key=KEY)
        self.assertIn(self.staff, self._logged_for(subject))
        self.assertNotIn("Administrator", self._logged_for(subject))

    def test_shared_email_staff_user_still_receives_it(self):
        """Administrator's email is the staff user's: the staff user is reached, Administrator is not."""
        frappe.db.set_value("User", "Administrator", "email", self.staff, update_modified=False)
        self.assertEqual(self.service.get_recipients_for_notification(KEY).count(self.staff), 1)
        subject = f"1960 shared {frappe.generate_hash(length=6)}"
        # exclude_users=["Administrator"] is what the Ponto alert and 15 siblings pass.
        notify_administrators(
            subject=subject, message="x", notification_key=KEY, exclude_users=["Administrator"]
        )
        self.assertIn(self.staff, self._logged_for(subject))
        self.assertNotIn("Administrator", self._logged_for(subject))

    def test_shared_email_resolver_keeps_the_staff_address(self):
        frappe.db.set_value("User", "Administrator", "email", self.staff, update_modified=False)
        recipients = resolve_admin_recipients(notification_key=KEY, exclude_users=["Administrator"])
        self.assertIn(self.staff, recipients)

    def test_control_administrator_only_email_is_still_excluded(self):
        """An excluded Administrator with its own email is dropped from a Fixed list by exclude_users."""
        _set_key_row(recipient_policy="Fixed", fixed_recipients=f"{self.admin_email}, {self.staff}")
        self.assertEqual(
            resolve_admin_recipients(notification_key=KEY, exclude_users=["Administrator"]), [self.staff]
        )

    def test_administrator_only_holder_resolves_to_nobody(self):
        role = f"Only Admin 1960 {frappe.generate_hash(length=4)}"
        frappe.get_doc({"doctype": "Role", "role_name": role}).insert()
        admin = frappe.get_doc("User", "Administrator")
        admin.append("roles", {"role": role})
        admin.save()
        _set_key_row(recipient_roles=role)
        self.assertEqual(self.service.get_recipients_for_notification(KEY), [])
        # The key reaches nobody, so notify_administrators falls back to the admin roles' other holders.
        fallback = resolve_admin_recipients(notification_key=KEY)
        self.assertNotIn(self.admin_email, fallback)
        self.assertIn(self.staff, fallback)
