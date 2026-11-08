"""
The weekly termination report and the manual dues-schedule summary reach staff the key-first way
(#2240, #2169): never Administrator, a Verenigingen Administrator by role profile OR by role alone, and
only those. Before, each built its own list from ``User.role_profile_name``.

Real flows and real rows: real Users (one through a real role-profile assignment, one holding the role
directly), real Has Role rows, the real Verenigingen Email Configuration. The only stub is the outgoing
EmailService factory (the mail boundary), whose recorded ``recipients`` are asserted.

Probe shortcut, said plainly: Administrator's ``role_profile_name`` is written with ``db.set_value``
(profile assignment would rewrite its roles); it stands in for "Administrator holds the profile" on a
real site, which #2240 left unestablished. Administrator's roles are real Has Role rows.

Run:
    bench --site test_site_6 run-tests --app verenigingen --module verenigingen.tests.test_staff_summary_recipients_2240
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.services.billing import dues_schedule_auto_creator as dsac
from verenigingen.services.termination import termination_utils as tu
from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_sepa_literal_recipients import (
    _put_key_row,
    _restore_rows,
    _snapshot_rows,
)
from verenigingen.utils.constants import Roles

CONFIG = "Verenigingen Email Configuration"
SOURCE = "verenigingen.services.communication.email_service.get_email_service"
WEEKLY_KEY = "termination_weekly_report"
DUES_KEY = "dues_schedule_manual_creation"
KEYS = (WEEKLY_KEY, DUES_KEY, "termination_overdue")


class _Mail:
    def __init__(self):
        self.service = MagicMock(name="EmailService")
        self.service.send_simple_email.return_value = MagicMock(success=True, error_message=None)
        self.service.send_templated_email.return_value = MagicMock(success=True, error_message=None)

    @property
    def recipients(self):
        out = []
        for name in ("send_simple_email", "send_templated_email", "send_email"):
            for call in getattr(self.service, name).call_args_list:
                out.extend(call.kwargs.get("recipients") or [])
        return out

    @property
    def keys(self):
        return [
            call.kwargs.get("notification_key")
            for name in ("send_simple_email", "send_templated_email")
            for call in getattr(self.service, name).call_args_list
        ]


class _Base(EnhancedTestCase):
    seed_rows = False  # True: the keys' rows are seeded from the registry, as on a migrated site

    def setUp(self):
        super().setUp()
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        config = frappe.get_single(CONFIG)
        config.set("notification_types", [r for r in config.notification_types if r.notification_key not in KEYS])
        config.save()
        if self.seed_rows:
            ensure_notification_registry_rows()
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", "")
        for field in ("stuck_schedule_notification_emails",):
            self._set_single("Verenigingen Settings", field, "")
        self._set_single("Verenigingen Payments Settings", "financial_admin_emails", "")

        suffix = frappe.generate_hash(length=5)
        self._administrator_holds_the_role_and_the_profile()
        self.profile_holder = self._user(f"profile-2240-{suffix}@example.org", role_profile=Roles.VERENIGINGEN_ADMIN)
        self.role_holder = self._user(f"role-2240-{suffix}@example.org", roles=[Roles.VERENIGINGEN_ADMIN])
        self.gone = self._user(f"gone-2240-{suffix}@example.org", roles=[Roles.VERENIGINGEN_ADMIN], enabled=0)
        # Control: System Manager alone was never part of either audience.
        self.sm_only = self._user(f"smonly-2240-{suffix}@example.org", roles=[Roles.SYSTEM_MANAGER])

    def _set_single(self, doctype, field, value):
        old = frappe.db.get_single_value(doctype, field)
        self.addCleanup(frappe.db.set_single_value, doctype, field, old)
        frappe.db.set_single_value(doctype, field, value)

    def _user(self, email, roles=None, role_profile=None, enabled=1):
        if role_profile:
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Rcp",
                    "send_welcome_email": 0,
                    "enabled": enabled,
                    "role_profile_name": role_profile,
                }
            ).insert()
            self.assertIn(Roles.VERENIGINGEN_ADMIN, frappe.get_roles(user.name), "the profile must grant the role")
            self.track_doc("User", user.name)
            return email
        self.create_test_user(email, roles=roles, enabled=enabled)
        return email

    def _administrator_holds_the_role_and_the_profile(self):
        old_email, old_profile = frappe.db.get_value("User", "Administrator", ["email", "role_profile_name"])
        self.addCleanup(
            frappe.db.set_value,
            "User",
            "Administrator",
            {"email": old_email, "role_profile_name": old_profile},
            update_modified=False,
        )
        self.admin_email = "administrator-2240@example.org"
        frappe.db.set_value(
            "User",
            "Administrator",
            {"email": self.admin_email, "role_profile_name": Roles.VERENIGINGEN_ADMIN},
            update_modified=False,
        )
        admin = frappe.get_doc("User", "Administrator")
        held = {r.role for r in admin.roles}
        added = [r for r in (Roles.VERENIGINGEN_ADMIN, Roles.SYSTEM_MANAGER) if r not in held]
        for role in added:
            admin.append("roles", {"role": role})
        admin.save()
        self.addCleanup(frappe.db.delete, "Has Role", {"parent": "Administrator", "role": ["in", added]})

    def assert_audience(self, mail):
        recipients = mail.recipients
        self.assertTrue(recipients, "the mail must still be sent to the staff that resolve")
        self.assertIn(self.profile_holder, recipients, "a holder through the role profile is reached")
        self.assertIn(self.role_holder, recipients, "a holder of the role WITHOUT the profile is reached (#2169)")
        self.assertNotIn(self.admin_email, recipients, "Administrator is never a recipient")
        self.assertNotIn("Administrator", recipients)
        self.assertNotIn(self.gone, recipients, "a disabled holder is not reached")
        self.assertNotIn(self.sm_only, recipients, "the audience stays Verenigingen Administrator (#2095)")
        self.assertTrue(all("@" in r for r in recipients), recipients)

    def mail(self):
        mail = _Mail()
        self._stack = patch(SOURCE, return_value=mail.service)
        self._stack.start()
        self.addCleanup(self._stack.stop)
        return mail


class _WeeklyReport:
    def test_weekly_termination_report_audience(self):
        member = self.create_test_member(first_name="Wk", last_name=f"T{frappe.generate_hash(length=6)}")
        frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member.name,
                "termination_type": "Voluntary",
                "status": "Pending",
                "request_date": today(),
                "termination_date": today(),
                "termination_reason": "recipients 2240",
            }
        ).insert()
        mail = self.mail()
        tu.generate_weekly_termination_report()
        self.assert_audience(mail)
        self.assertEqual(set(mail.keys), {WEEKLY_KEY}, "its own key: it must not borrow termination_overdue's row")


class _DuesSummary:
    RESULT = {"total_members": 3, "created_count": 2, "error_count": 1}

    def test_manual_dues_summary_audience(self):
        mail = self.mail()
        with patch("verenigingen.verenigingen_payments.services.mollie_configuration_service.get_mollie_config"):
            dsac._send_summary_email(dict(self.RESULT))
        self.assert_audience(mail)
        self.assertEqual(set(mail.keys), {DUES_KEY})

    def test_manual_dues_summary_falls_back_to_the_settings_list_when_nobody_resolves(self):
        """Kept from before: when no staff resolve, the settings list is used.

        Seam stubbed: the resolver answering nobody (a site where nobody holds the role cannot be built
        without deleting every real holder's Has Role rows).
        """
        self._set_single("Verenigingen Settings", "stuck_schedule_notification_emails", "ops-2240@example.org")
        mail = self.mail()
        with patch.object(dsac, "resolve_admin_recipients", return_value=[]), patch(
            "verenigingen.verenigingen_payments.services.mollie_configuration_service.get_mollie_config"
        ):
            dsac._send_summary_email(dict(self.RESULT))
        self.assertEqual(mail.recipients, ["ops-2240@example.org"])


class TestNoRowForTheKeys(_Base, _WeeklyReport, _DuesSummary):
    """No row for the keys: each sender's own default roles apply."""


class TestSeededRowAudiences(_Base, _WeeklyReport, _DuesSummary):
    """The row a migrated site really has, seeded from the registry; the resolver uses it first."""

    seed_rows = True

    def test_seeded_rows_name_the_old_audience(self):
        from verenigingen.notification_registry import NOTIFICATION_KEYS

        for key in (WEEKLY_KEY, DUES_KEY):
            self.assertEqual(NOTIFICATION_KEYS[key]["recipient_policy"], "Role-Based", key)
            self.assertEqual(NOTIFICATION_KEYS[key]["recipient_roles"], Roles.VERENIGINGEN_ADMIN, key)


class TestManualDuesSummaryRowPatch(EnhancedTestCase):
    PATCH = "verenigingen.patches.v2_2.route_manual_dues_summary_to_administrators_2169"

    def setUp(self):
        super().setUp()
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)

    def _row_for_key_2240(self, key):
        frappe.clear_document_cache(CONFIG, CONFIG)
        return next(r for r in frappe.get_single(CONFIG).notification_types if r.notification_key == key)

    def _run(self):
        import importlib

        importlib.import_module(self.PATCH).execute()

    def test_the_seeded_document_field_row_moves_to_the_old_audience(self):
        _put_key_row(DUES_KEY, "Document-Field")
        self._run()
        row = self._row_for_key_2240(DUES_KEY)
        self.assertEqual((row.recipient_policy, row.recipient_roles), ("Role-Based", Roles.VERENIGINGEN_ADMIN))

    def test_an_edited_row_is_left_alone(self):
        _put_key_row(DUES_KEY, "Fixed", fixed_recipients="board-2169@example.org")
        _put_key_row("dues_schedule_creation_failed", "Document-Field")  # control: another key never moves
        self._run()
        self.assertEqual(self._row_for_key_2240(DUES_KEY).recipient_policy, "Fixed")
        self.assertEqual(self._row_for_key_2240("dues_schedule_creation_failed").recipient_policy, "Document-Field")
        _put_key_row(DUES_KEY, "Document-Field", recipient_field="member")  # an admin's own field choice
        self._run()
        self.assertEqual(self._row_for_key_2240(DUES_KEY).recipient_policy, "Document-Field")

    def test_the_patch_is_idempotent_and_registered(self):
        from pathlib import Path

        _put_key_row(DUES_KEY, "Document-Field")
        self._run()
        self._run()
        self.assertEqual(self._row_for_key_2240(DUES_KEY).recipient_roles, Roles.VERENIGINGEN_ADMIN)
        listing = (Path(frappe.get_app_path("verenigingen")) / "patches.txt").read_text()
        self.assertIn(self.PATCH, listing)

    def test_the_patch_agrees_with_the_registry(self):
        from verenigingen.notification_registry import NOTIFICATION_KEYS

        entry = NOTIFICATION_KEYS[DUES_KEY]
        self.assertEqual((entry["recipient_policy"], entry["recipient_roles"]), ("Role-Based", Roles.VERENIGINGEN_ADMIN))


class TestDeadCopiesAreGone(EnhancedTestCase):
    def test_no_role_name_is_handed_to_get_roles(self):
        """`frappe.get_roles` takes a USER; the copies passing a role name were dead code and are deleted."""
        from pathlib import Path

        source = Path(dsac.__file__).read_text()
        self.assertNotIn("get_roles(Roles.", source)
        self.assertFalse(hasattr(dsac, "send_summary_email"), "no reader: the unscheduled public copy is deleted")
