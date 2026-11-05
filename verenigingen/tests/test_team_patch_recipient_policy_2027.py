"""#2027: add_team_chapter_notification_types wrote an invalid recipient_policy ("Role") and a list.

Measured on test_site_3: with analytics_alert / payment_plan_request absent from the Single, the
patch's ``config.save()`` RAISES ``Row #N: Recipient Policy cannot be "Role"``, so a site that
reaches this patch with a populated configuration (migrate_email_settings_to_configuration
returns early then) fails ``bench migrate`` outright. Nothing wrong can be stored; there are no
wrong rows to repair.

Probe shortcut: the "old site" state is built by dropping the two rows from the Single directly
and calling the patch's ``execute()``; a real ``bench migrate`` was not run.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v15_0.add_team_chapter_notification_types import execute
from verenigingen.services.communication.email_configuration_service import (
    get_email_configuration_service,
)
from verenigingen.tests.test_notification_registry_seed_1959 import _rows

DOCTYPE = "Verenigingen Email Configuration"
KEYS = ("analytics_alert", "payment_plan_request")
STAFF_ROLE = "Verenigingen Staff"


class TestTeamPatchRecipientPolicy(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.baseline = {k: dict(r.as_dict()) for k, r in _rows().items()}
        self.addCleanup(self._cleanup_restore_snapshot)
        config = frappe.get_single(DOCTYPE)
        config.notification_types = [r for r in config.notification_types if r.notification_key not in KEYS]
        config.save()
        self.assertFalse(set(KEYS) & set(_rows()), "control: the two rows are really missing")

    def _cleanup_restore_snapshot(self):
        # Not singleton_backup: it skips child tables (#2029).
        config = frappe.get_single(DOCTYPE)
        config.notification_types = []
        for row in self.baseline.values():
            row = {k: v for k, v in row.items() if k not in ("name", "creation", "modified", "idx")}
            config.append("notification_types", row)
        config.save()
        # The patch under test commits its own save, so the restore must be committed too or the
        # class-level rollback would bring the patch's rows back (measured: 88 -> 89 rows on the site).
        frappe.db.commit()

    def _staff_user(self):
        email = "staff-2027@example.com"
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {"doctype": "User", "email": email, "first_name": "Staff2027", "send_welcome_email": 0}
            )
            user.append("roles", {"role": STAFF_ROLE})
            user.insert()
            self.addCleanup(frappe.delete_doc, "User", email, force=True)
        return email

    def test_patch_writes_valid_role_based_rows(self):
        execute()

        rows = _rows()
        for key in KEYS:
            self.assertEqual(rows[key].recipient_policy, "Role-Based", key)
            self.assertEqual(rows[key].recipient_roles, STAFF_ROLE, f"{key}: a comma string, not a list")

    def test_role_based_branch_is_taken_not_the_system_manager_fallback(self):
        staff = self._staff_user()
        execute()
        frappe.cache.delete_value("email_configuration:singleton")

        service = get_email_configuration_service()
        for key in KEYS:
            recipients = service.get_recipients_for_notification(key)
            self.assertIn(staff, recipients, f"{key}: Verenigingen Staff must be notified")

    def test_patch_does_not_touch_existing_rows(self):
        execute()
        config = frappe.get_single(DOCTYPE)
        row = next(r for r in config.notification_types if r.notification_key == "payment_plan_request")
        row.recipient_roles = "Accounts Manager"
        config.save()

        execute()

        self.assertEqual(_rows()["payment_plan_request"].recipient_roles, "Accounts Manager")
