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
