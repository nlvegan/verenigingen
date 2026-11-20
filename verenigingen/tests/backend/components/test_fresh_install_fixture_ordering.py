# Fresh-install ordering (#1956, #1957).
#
# `frappe.installer.install_app` runs `after_install` BEFORE `sync_fixtures` and `after_sync`
# after it, and a fresh site has no Company. CI sites are fresh installs, so both showed up as
# failed `execute_after_install` steps on every shard.
#
# Every test works inside one transaction that is rolled back; the setup code commits, so
# `frappe.db.commit` is replaced by a no-op for the duration (Mock justified: the commit is
# the only thing that would make these deliberate deletions permanent).

import contextlib
import io
import json
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen import setup as setup_mod
from verenigingen.setup import webhook_user_setup as webhook_mod
from verenigingen.tests.utils.paths import APP_ROOT

MEMBER_PROFILE = "Verenigingen Member"
DEFAULT_TYPES = ["Lid", "Huisgenootlid", "Aspirant", "Erelid", "Donateur"]


class _RolledBackCase(FrappeTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(frappe.db, "commit")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(frappe.db.rollback)
        self.addCleanup(frappe.clear_cache)


class TestMembershipTypesWaitForTheFixtures(_RolledBackCase):
    """#1956: the types need the `Verenigingen Member` Role Profile, which only a fixture ships."""

    def setUp(self):
        super().setUp()
        # The state a fresh site is in when after_install runs: no default type, and the
        # fixture-shipped Role Profile not imported yet.
        frappe.db.delete("Membership Type", {"name": ["in", DEFAULT_TYPES]})
        frappe.db.delete("Role Profile", {"name": MEMBER_PROFILE})
        frappe.clear_cache()
        self.assertFalse(frappe.db.exists("Role Profile", MEMBER_PROFILE))

    def _in_install(self):
        # Mock justified: frappe.flags.in_install is the execution context install_app sets.
        old = frappe.flags.in_install
        frappe.flags.in_install = "verenigingen"
        self.addCleanup(setattr, frappe.flags, "in_install", old)

    def _import_the_role_profile_fixture(self):
        with open(APP_ROOT / "verenigingen" / "fixtures" / "role_profile.json", encoding="utf-8") as f:
            row = next(r for r in json.load(f) if r["name"] == MEMBER_PROFILE)
        frappe.get_doc(row).insert()

    def _reference_data(self):
        with contextlib.redirect_stdout(io.StringIO()):
            setup_mod.create_all_reference_data()

    def test_reference_data_does_not_fail_while_fixtures_are_pending(self):
        self._in_install()
        self._reference_data()  # RED before: RuntimeError "Could not find Role Profile"
        self.assertEqual(frappe.db.count("Membership Type", {"name": ["in", DEFAULT_TYPES]}), 0)

    def test_during_an_install_with_the_profile_present_the_types_are_created_at_once(self):
        self._in_install()
        self._import_the_role_profile_fixture()
        self._reference_data()
        found = frappe.get_all("Membership Type", filters={"name": ["in", DEFAULT_TYPES]}, pluck="name")
        self.assertCountEqual(found, DEFAULT_TYPES)

    def test_outside_an_install_a_missing_profile_is_still_a_failure(self):
        # Control: the deferral must not turn every missing profile into a silent skip.
        with self.assertRaises(RuntimeError) as ctx:
            self._reference_data()
        self.assertIn(MEMBER_PROFILE, str(ctx.exception))

    def test_after_sync_hook_creates_the_types_once_the_profile_exists(self):
        self._in_install()
        self._reference_data()
        self._import_the_role_profile_fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            setup_mod.ensure_default_membership_types()
        found = frappe.get_all("Membership Type", filters={"name": ["in", DEFAULT_TYPES]}, pluck="name")
        self.assertCountEqual(found, DEFAULT_TYPES)
        for name in DEFAULT_TYPES:
            self.assertEqual(frappe.db.get_value("Membership Type", name, "role_profile"), MEMBER_PROFILE)

    def test_after_sync_hook_does_not_raise_when_the_profile_is_still_missing(self):
        # A raise would abort install-app (the installer does not guard after_sync); it logs.
        before = frappe.db.count("Error Log")
        with contextlib.redirect_stdout(io.StringIO()):
            setup_mod.ensure_default_membership_types()
        self.assertEqual(frappe.db.count("Membership Type", {"name": ["in", DEFAULT_TYPES]}), 0)
        self.assertGreater(frappe.db.count("Error Log"), before)

    def test_the_hook_is_registered(self):
        hooks = frappe.get_hooks("after_sync", app_name="verenigingen")
        self.assertIn("verenigingen.setup.ensure_default_membership_types", hooks)


WEBHOOK_PROFILE = "Verenigingen Webhook User"


class TestWebhookUserWaitsForTheFixtures(_RolledBackCase):
    """#2357: the webhook user's Role Profile is also fixture-only, so the after_install step
    failed on every fresh install (and left initial setup unmarked). after_sync converges it."""

    def setUp(self):
        super().setUp()
        # The state a fresh site is in when after_install runs: the fixture-shipped Role Profile is
        # not imported yet.
        frappe.db.delete("Role Profile", {"name": WEBHOOK_PROFILE})
        frappe.clear_cache()
        self.assertFalse(frappe.db.exists("Role Profile", WEBHOOK_PROFILE))
        self.addCleanup(setattr, frappe.flags, "in_install", frappe.flags.in_install)

    def _import_the_webhook_profile_fixture(self):
        with open(APP_ROOT / "verenigingen" / "fixtures" / "role_profile.json", encoding="utf-8") as f:
            row = next(r for r in json.load(f) if r["name"] == WEBHOOK_PROFILE)
        frappe.get_doc(row).insert()

    def _install_step(self):
        with contextlib.redirect_stdout(io.StringIO()):
            setup_mod._install_webhook_user()

    def test_install_step_does_not_fail_while_fixtures_are_pending(self):
        frappe.flags.in_install = "verenigingen"
        before = frappe.db.count("Error Log")
        self._install_step()  # RED before: RuntimeError "Role Profile Verenigingen Webhook User not found"
        self.assertEqual(frappe.db.count("Error Log"), before)

    def test_install_step_leaves_no_half_configured_user_behind(self):
        # A user created now would have no roles; the deferral must not create it at all.
        frappe.flags.in_install = "verenigingen"
        from verenigingen.setup.webhook_user_setup import generate_webhook_user_email

        email = generate_webhook_user_email()
        # The site may already carry the user (a fresh install does not): start from none.
        frappe.db.delete("Has Role", {"parent": email})
        frappe.db.delete("User", {"name": email})
        self.assertFalse(frappe.db.exists("User", email))
        self._install_step()
        self.assertFalse(frappe.db.exists("User", email))

    def test_during_an_install_with_the_profile_present_the_user_is_configured_at_once(self):
        # Control: the deferral keys on the profile being absent, not on in_install alone.
        frappe.flags.in_install = "verenigingen"
        self._import_the_webhook_profile_fixture()
        # Start from a site with no webhook user (the site may already carry one).
        from verenigingen.setup.webhook_user_setup import generate_webhook_user_email

        frappe.db.set_single_value("Verenigingen Payments Settings", "webhook_user", None)
        email = generate_webhook_user_email()
        frappe.db.delete("Has Role", {"parent": email})
        frappe.db.delete("User", {"name": email})
        self._install_step()
        self.assertEqual(frappe.db.get_single_value("Verenigingen Payments Settings", "webhook_user"), email)
        self.assertTrue( frappe.db.get_value("User", email, "enabled"))
        self.assertIn(WEBHOOK_PROFILE, frappe.get_roles(email))

    def test_outside_an_install_a_missing_profile_is_still_a_failure(self):
        # Control: the deferral must not turn every missing profile into a silent skip.
        frappe.flags.in_install = False
        with self.assertRaises(RuntimeError) as ctx:
            self._install_step()
        self.assertIn(WEBHOOK_PROFILE, str(ctx.exception))

    def test_after_install_then_after_sync_configures_the_webhook_user(self):
        # The whole fresh-install sequence: after_install step (profile absent), fixtures sync
        # (profile appears), after_sync hook. The user must end up enabled, with the role, and
        # named in Verenigingen Payments Settings.
        frappe.flags.in_install = "verenigingen"
        self._install_step()
        self._import_the_webhook_profile_fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            result = webhook_mod.ensure_webhook_user()
        self.assertTrue(result.get("success"), result)
        email = frappe.db.get_single_value("Verenigingen Payments Settings", "webhook_user")
        self.assertEqual(email, result["webhook_user_email"])
        self.assertEqual(frappe.db.get_value("User", email, "enabled"), 1)
        self.assertIn(WEBHOOK_PROFILE, frappe.get_roles(email))

    def test_the_hook_is_registered(self):
        hooks = frappe.get_hooks("after_sync", app_name="verenigingen")
        self.assertIn("verenigingen.setup.webhook_user_setup.ensure_webhook_user", hooks)
