"""The critical authentication alert reaches the holders of the Verenigingen System Administrator profile (#2254).

``alert_if_auth_issues`` used to filter ``User.role_profile_name == "System Manager"``, a profile that
does not exist, so the alert reached nobody. Maintainer ruling (2026-11-08): it goes to ENABLED holders of
the Verenigingen System Administrator ROLE PROFILE, never the Administrator user, keeping the key
``auth_monitoring_alert`` so recipients stay configurable in Verenigingen Email Configuration.

Real Users, assigned the profile through ``User.role_profiles`` (the save path every writer in the app
uses), real Verenigingen Email Configuration row seeded from the registry. Controls, each with a real row:
a System-Manager-ROLE-only user, a Verenigingen-Administrator-ROLE-only user, a disabled holder, a holder
of another profile and the Administrator user holding the profile.

Mock justification: the EmailService factory (the
outgoing-mail boundary, as in test_staff_recipients_2095) are stubbed. The recipient list is what the
alert handed that boundary. Probe shortcut: ``test_a_legacy_only_holder_is_found`` writes the deprecated
``role_profile_name`` column directly, because ``User.validate`` always mirrors it into the child table.

Run:
    bench --site test_site_3 run-tests --app verenigingen --module verenigingen.tests.test_auth_alert_recipients_2254
"""

import importlib
from unittest.mock import MagicMock, patch

import frappe
from frappe.core.doctype.activity_log.activity_log import add_authentication_log

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.notification_state import (
    own_notification_keys,
    restore_notification_rows,
    snapshot_notification_rows,
)
from verenigingen.utils.constants import Roles

CONFIG = "Verenigingen Email Configuration"
KEY = "auth_monitoring_alert"
PROFILE = "Verenigingen System Administrator"
OTHER_PROFILE = "Verenigingen Administrator"
MODULE = "verenigingen.utils.auth_monitoring"


class _Mail:
    def __init__(self):
        self.service = MagicMock(name="EmailService")
        self.service.send_simple_email.return_value = MagicMock(success=True, error_message=None)

    @property
    def recipients(self):
        out = []
        for call in self.service.send_simple_email.call_args_list:
            out.extend(call.kwargs.get("recipients") or [])
        return out

    @property
    def keys(self):
        return [c.kwargs.get("notification_key") for c in self.service.send_simple_email.call_args_list]


class TestAuthAlertRecipients2254(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        own_notification_keys(self, KEY)
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", "")
        self._ensure_profile(PROFILE, [Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN])
        self._ensure_profile(OTHER_PROFILE, [Roles.VERENIGINGEN_ADMIN])

        suffix = frappe.generate_hash(length=5)
        self.holder = self._make_holder(f"holder-2254-{suffix}@example.org", [Roles.SYSTEM_MANAGER], profiles=[PROFILE])
        self.second = self._make_holder(
            f"second-2254-{suffix}@example.org", [Roles.SYSTEM_MANAGER], profiles=[OTHER_PROFILE, PROFILE]
        )
        self.gone = self._make_holder(f"gone-2254-{suffix}@example.org", [Roles.SYSTEM_MANAGER], profiles=[PROFILE], enabled=0)
        self.other_profile = self._make_holder(f"other-2254-{suffix}@example.org", [Roles.SYSTEM_MANAGER], profiles=[OTHER_PROFILE])
        self.sm_only = self._make_holder(f"smonly-2254-{suffix}@example.org", [Roles.SYSTEM_MANAGER])
        self.va_only = self._make_holder(f"vaonly-2254-{suffix}@example.org", [Roles.VERENIGINGEN_ADMIN])

    def _ensure_profile(self, name, roles):
        if frappe.db.exists("Role Profile", name):
            return
        doc = frappe.get_doc({"doctype": "Role Profile", "role_profile": name})
        for role in roles:
            doc.append("roles", {"role": role})
        doc.insert(ignore_permissions=True)
        self.addCleanup(frappe.delete_doc, "Role Profile", name, force=True, ignore_permissions=True)

    def _make_holder(self, email, roles, profiles=(), enabled=1):
        user = self.create_test_user(email, roles=roles, enabled=enabled)
        for profile in profiles:
            user.append("role_profiles", {"role_profile": profile})
        if profiles:
            user.save()
        return email

    def _admin_holds_profile(self):
        """The Administrator user holds the profile and has an email: the control for 'never Administrator'.

        Probe shortcut: ``User.populate_role_profile_roles`` empties ``role_profiles`` for STANDARD_USERS,
        so no save can give Administrator a profile. The row is written directly (as a raw import or
        a hand-edited database would), which is the only way the state exists.
        """
        old_email = frappe.db.get_value("User", "Administrator", "email")
        self.addCleanup(self._restore_administrator, old_email)
        self.admin_email = f"administrator-2254-{frappe.generate_hash(length=5)}@example.org"
        frappe.db.set_value("User", "Administrator", "email", self.admin_email, update_modified=False)
        frappe.get_doc(
            {
                "doctype": "User Role Profile",
                "parent": "Administrator",
                "parenttype": "User",
                "parentfield": "role_profiles",
                "role_profile": PROFILE,
            }
        ).db_insert()
        self.assertTrue(frappe.db.exists("User Role Profile", {"parent": "Administrator", "role_profile": PROFILE}))

    @staticmethod
    def _restore_administrator(email):
        frappe.db.delete("User Role Profile", {"parent": "Administrator"})
        frappe.db.set_value("User", "Administrator", "email", email, update_modified=False)

    def _fire_auth_alert(self):
        """Real failed-login rows at the threshold (#2285: the alert keys on a failed-login rate now)."""
        mail = _Mail()
        module = importlib.import_module(MODULE)
        frappe.db.delete("Activity Log", {"operation": "Login", "status": "Failed"})
        for _ in range(module.FAILED_LOGIN_ALERT_THRESHOLD):
            add_authentication_log("Invalid login credentials", f"nobody-2254-{frappe.generate_hash(length=6)}", status="Failed")
        with patch(f"{MODULE}.get_email_service", return_value=mail.service):
            module.alert_if_auth_issues()
        return mail

    def test_profile_holders_are_reached_everyone_else_is_not(self):
        self._admin_holds_profile()
        mail = self._fire_auth_alert()
        recipients = mail.recipients
        self.assertEqual(mail.keys, [KEY], "one critical alert, on its registered key")
        self.assertIn(self.holder, recipients)
        self.assertIn(self.second, recipients, "a holder whose profile is NOT the first one (child table only)")
        for who, why in (
            ("gone", "disabled holder"),
            ("other_profile", "holder of another profile"),
            ("sm_only", "System Manager ROLE alone"),
            ("va_only", "Verenigingen Administrator ROLE alone"),
        ):
            self.assertNotIn(getattr(self, who), recipients, f"{why} must not be reached: {recipients}")
        self.assertNotIn(self.admin_email, recipients, "the Administrator user is never a recipient")
        self.assertNotIn("Administrator", recipients)

    def test_a_legacy_only_holder_is_found(self):
        """Holder recorded ONLY in the deprecated role_profile_name column (no child row)."""
        legacy = self._make_holder(f"legacy-2254-{frappe.generate_hash(length=5)}@example.org", [Roles.SYSTEM_MANAGER])
        frappe.db.set_value("User", legacy, "role_profile_name", PROFILE, update_modified=False)
        self.assertFalse(frappe.db.exists("User Role Profile", {"parent": legacy}))
        recipients = self._fire_auth_alert().recipients
        self.assertIn(legacy, recipients)
        self.assertNotIn(self.sm_only, recipients)

    def test_a_configured_row_beats_the_profile(self):
        """Recipients stay configurable: a Fixed row in Email Configuration wins over the profile default."""
        frappe.db.set_value(
            "Email Notification Type",
            {"parent": CONFIG, "notification_key": KEY},
            {"recipient_policy": "Fixed", "fixed_recipients": "ops-2254@example.org"},
        )
        frappe.clear_document_cache(CONFIG, CONFIG)
        recipients = self._fire_auth_alert().recipients
        self.assertEqual(recipients, ["ops-2254@example.org"])

    def test_with_no_profile_holder_the_admin_roles_still_get_it_but_never_administrator(self):
        frappe.db.delete("User Role Profile", {"role_profile": PROFILE, "parenttype": "User"})
        frappe.db.set_value("User", {"role_profile_name": PROFILE}, "role_profile_name", None, update_modified=False)
        self._admin_holds_roles_and_email()
        recipients = self._fire_auth_alert().recipients
        self.assertTrue(recipients, "the alert must not vanish when no one holds the profile")
        self.assertIn(self.sm_only, recipients)
        self.assertNotIn(self.admin_email, recipients)
        self.assertNotIn(self.gone, recipients)

    def _admin_holds_roles_and_email(self):
        old_email = frappe.db.get_value("User", "Administrator", "email")
        self.addCleanup(frappe.db.set_value, "User", "Administrator", "email", old_email, update_modified=False)
        self.admin_email = f"administrator-2254-{frappe.generate_hash(length=5)}@example.org"
        frappe.db.set_value("User", "Administrator", "email", self.admin_email, update_modified=False)


class TestAuthAlertPatch2254(EnhancedTestCase):
    """The patch moves only a stock row. Probe shortcut: existing-site rows are written directly and
    ``execute`` is called without the patch runner."""

    PATCH = "verenigingen.patches.v2_2.route_auth_alert_to_system_admin_profile_2254"

    def setUp(self):
        super().setUp()
        rows = snapshot_notification_rows()
        self.addCleanup(restore_notification_rows, rows)

    def _put_auth_row(self, policy, roles):
        config = frappe.get_single(CONFIG)
        config.set("notification_types", [r for r in config.notification_types if r.notification_key != KEY])
        config.append(
            "notification_types",
            {
                "notification_key": KEY,
                "label": KEY,
                "category": "System",
                "recipient_policy": policy,
                "recipient_roles": roles,
                "enabled": 1,
            },
        )
        config.save()

    def _auth_row_state(self):
        row = frappe.db.get_value(
            "Email Notification Type",
            {"parent": CONFIG, "notification_key": KEY},
            ["recipient_policy", "recipient_roles"],
        )
        return row[0], row[1] or ""

    def test_a_stock_row_becomes_custom(self):
        for roles in ("System Manager, Verenigingen Administrator", "Verenigingen Administrator, System Manager"):
            self._put_auth_row("Role-Based", roles)
            importlib.import_module(self.PATCH).execute()
            self.assertEqual(self._auth_row_state(), ("Custom", ""), roles)

    def test_an_admins_own_row_is_left_alone(self):
        # Fixed and Document-Field rows that still carry the stock roles string pin the policy condition.
        for policy, roles in (
            ("Role-Based", "Verenigingen Treasurer"),
            ("Role-Based", "System Manager"),
            ("Fixed", "System Manager, Verenigingen Administrator"),
            ("Document-Field", "System Manager, Verenigingen Administrator"),
        ):
            self._put_auth_row(policy, roles)
            importlib.import_module(self.PATCH).execute()
            self.assertEqual(self._auth_row_state(), (policy, roles))

    def test_the_patch_is_registered_and_the_registry_seeds_custom(self):
        from pathlib import Path

        import verenigingen
        from verenigingen.notification_registry import NOTIFICATION_KEYS

        listed = (Path(verenigingen.__file__).parent / "patches.txt").read_text().splitlines()
        self.assertIn(self.PATCH, listed)
        self.assertEqual(NOTIFICATION_KEYS[KEY]["recipient_policy"], "Custom")
