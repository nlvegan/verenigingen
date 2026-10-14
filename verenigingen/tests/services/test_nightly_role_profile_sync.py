"""Nightly role-profile sync (#1676): registration and behaviour through the real sync."""

from unittest import mock

import frappe

from verenigingen.services.member.account import user_role_profile_calculator as calc
from verenigingen.services.member.account.user_role_profile_calculator import (
    PROFILE_MEMBER,
    PROFILE_VOLUNTEER,
    nightly_role_profile_sync,
    sync_role_profiles_for_users,
    sync_user_role_profile,
)
from verenigingen.tests.utils.base import VereningingenTestCase

JOB = "verenigingen.services.member.account.user_role_profile_calculator.nightly_role_profile_sync"
ADMIN_PROFILE = "Verenigingen Administrator"


class TestNightlyRoleProfileSync(VereningingenTestCase):
    def _nightly_member_user(self, roles=("Verenigingen Member",)):
        email = f"nightly.{frappe.generate_hash(length=8)}@test.invalid"
        member = self.create_test_member(
            first_name="Nightly",
            last_name=f"M{frappe.generate_hash(length=5)}",
            email=email,
            status="Active",
        )
        user = self.create_test_user(email, roles=list(roles))
        self.track_doc("User", user.name)
        frappe.db.set_value("Member", member.name, "user", user.name)
        return user.name

    def _attach(self, user, profile):
        """Attach a profile through a real User save (same as production's store)."""
        doc = frappe.get_doc("User", user)
        doc.set("role_profiles", [{"role_profile": profile}])
        doc.save()
        frappe.clear_cache(user=user)
        self.assertIn(profile, calc.get_user_role_profiles(user), "fixture failed to attach")

    def _drift_to_volunteer(self, user):
        """Real flow: an Active volunteer is synced to Volunteer (recorded as sync-granted),
        then stops being active, so the held profile is stale and withdrawable."""
        member = frappe.db.get_value("Member", {"user": user}, "name")
        volunteer = self.create_test_volunteer(member=member, status="Active").name
        sync_user_role_profile(user, dry_run=False)
        self.assertIn(PROFILE_VOLUNTEER, calc.get_user_role_profiles(user), "fixture: not granted")
        # Direct status write stands in for the volunteer being deactivated (not the real flow).
        frappe.db.set_value("Volunteer", volunteer, "status", "Inactive")

    def test_job_is_registered_as_a_daily_long_scheduler_event(self):
        events = frappe.get_hooks("scheduler_events")
        self.assertIn(JOB, events.get("daily_long", []))
        self.assertTrue(callable(frappe.get_attr(JOB)))

    def test_job_corrects_a_drifted_user(self):
        user = self._nightly_member_user()
        self._drift_to_volunteer(user)

        results = nightly_role_profile_sync()

        self.assertGreaterEqual(results["changed"], 1, results)
        held = calc.get_user_role_profiles(user)
        self.assertIn(PROFILE_MEMBER, held)
        self.assertNotIn(PROFILE_VOLUNTEER, held)

    def test_job_leaves_a_correct_user_unchanged(self):
        user = self._nightly_member_user()
        sync_user_role_profile(user, dry_run=False)
        before = calc.get_user_role_profiles(user)
        modified = frappe.db.get_value("User", user, "modified")

        nightly_role_profile_sync()

        self.assertEqual(calc.get_user_role_profiles(user), before)
        self.assertEqual(frappe.db.get_value("User", user, "modified"), modified)

    def test_job_preserves_a_manual_admin_profile_on_a_nightly_member_user(self):
        user = self._nightly_member_user(roles=("System Manager",))
        self._attach(user, ADMIN_PROFILE)
        roles_before = set(frappe.get_roles(user))

        nightly_role_profile_sync()
        nightly_role_profile_sync()  # the bootstrap record is written on run 1; run 2 uses it

        frappe.clear_cache(user=user)
        self.assertIn(ADMIN_PROFILE, calc.get_user_role_profiles(user))
        self.assertTrue(roles_before <= set(frappe.get_roles(user)), "admin roles were stripped")

    def test_job_skips_a_disabled_user_and_a_non_member(self):
        disabled = self._nightly_member_user()
        self._drift_to_volunteer(disabled)
        frappe.db.set_value("User", disabled, "enabled", 0)
        email = f"nightly.nm.{frappe.generate_hash(length=6)}@test.invalid"
        non_member = self.create_test_user(email, roles=["Verenigingen Member"]).name
        self.track_doc("User", non_member)

        users = calc.get_nightly_sync_users()
        nightly_role_profile_sync()

        self.assertNotIn(disabled, users)
        self.assertNotIn(non_member, users)
        self.assertIn(PROFILE_VOLUNTEER, calc.get_user_role_profiles(disabled))

    def test_one_failing_user_does_not_stop_the_run(self):
        bad, good = self._nightly_member_user(), self._nightly_member_user()
        self._drift_to_volunteer(good)
        real = calc.sync_user_role_profile

        def flaky(user, **kwargs):
            if user == bad:
                raise RuntimeError("boom")
            return real(user, **kwargs)

        # Mock justified: injects a failure into ONE user; the other user takes the real sync.
        with mock.patch.object(calc, "sync_user_role_profile", side_effect=flaky):
            results = sync_role_profiles_for_users([bad, good])

        self.assertEqual(results["errors"], 1, results)
        self.assertEqual(results["errors_list"][0]["user"], bad)
        self.assertEqual(results["changed"], 1, results)
        self.assertNotIn(PROFILE_VOLUNTEER, calc.get_user_role_profiles(good))

    def test_failures_are_logged_and_a_summary_is_printed(self):
        bad = self._nightly_member_user()
        with mock.patch.object(calc, "get_nightly_sync_users", return_value=[bad]), mock.patch.object(
            calc, "sync_user_role_profile", side_effect=RuntimeError("boom")
        ), mock.patch.object(calc.frappe, "log_error") as log_error, mock.patch("builtins.print") as out:
            # Mock justified: failure injection; asserts the reporting channels only.
            nightly_role_profile_sync()

        self.assertEqual(log_error.call_args.kwargs["title"], "Nightly Role Profile Sync Failed")
        self.assertIn(bad, log_error.call_args.kwargs["message"])
        self.assertIn("errors=1", out.call_args.args[0])
