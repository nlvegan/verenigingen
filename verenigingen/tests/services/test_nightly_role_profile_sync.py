"""Nightly role-profile sync (#1676): registration and behaviour through the real sync."""

from unittest import mock

import frappe

from verenigingen.services.member.account import user_role_profile_calculator as calc
from verenigingen.services.member.account.user_role_profile_calculator import (
    PROFILE_MEMBER,
    PROFILE_TEAM_LEADER,
    PROFILE_VOLUNTEER,
    nightly_role_profile_sync,
    sync_role_profiles_for_users,
    sync_user_role_profile,
)
from verenigingen.tests.utils.base import VereningingenTestCase

JOB = "verenigingen.services.member.account.user_role_profile_calculator.nightly_role_profile_sync"
ADMIN_PROFILE = "Verenigingen Administrator"
DIRECT_ROLE = "Newsletter Manager"


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

    def _error_log_rows(self, user):
        self.expectErrorLog("Role Profile Sync Failed")
        rows = frappe.get_all(
            "Error Log", filters={"error": ["like", f"%{user}%"]}, pluck="name"
        )
        # tabError Log is MyISAM: the harness rollback cannot remove these.
        self.addCleanup(lambda: [frappe.delete_doc("Error Log", r, force=True) for r in
                                 frappe.get_all("Error Log", filters={"error": ["like", f"%{user}%"]}, pluck="name")])
        return rows

    def _raise_for(self, bad, exc):
        real = calc.calculate_user_role_profile_set

        def flaky(user):
            if user == bad:
                raise exc
            return real(user)

        # Mock justified: failure injection INSIDE the real sync (the calculator call it makes).
        return mock.patch.object(calc, "calculate_user_role_profile_set", side_effect=flaky)

    def test_one_failing_user_does_not_stop_the_run_and_logs_one_error_row(self):
        bad, good = self._nightly_member_user(), self._nightly_member_user()
        self._drift_to_volunteer(good)
        self._error_log_rows(bad)

        with self._raise_for(bad, RuntimeError("boom")):
            results = sync_role_profiles_for_users([bad, good], nightly=True)

        self.assertEqual(results["errors"], 1, results)
        self.assertEqual(results["errors_list"][0]["user"], bad)
        self.assertEqual(results["changed"], 1, results)
        self.assertNotIn(PROFILE_VOLUNTEER, calc.get_user_role_profiles(good))
        rows = frappe.get_all(
            "Error Log", filters={"error": ["like", f"%{bad}%"]}, fields=["method"]
        )
        self.assertEqual([r.method for r in rows], ["Role Profile Sync Failed"])

    def test_a_deadlock_stops_the_nightly_run_but_not_the_event_path(self):
        bad, after = self._nightly_member_user(), self._nightly_member_user()
        self._drift_to_volunteer(after)
        self._error_log_rows(bad)
        with self._raise_for(bad, frappe.QueryDeadlockError()):
            with self.assertRaises(frappe.QueryDeadlockError):
                sync_role_profiles_for_users([bad, after], nightly=True)
            self.assertIn(PROFILE_VOLUNTEER, calc.get_user_role_profiles(after), "run must have stopped")
            # Event-driven callers keep swallowing (unchanged contract).
            self.assertFalse(sync_user_role_profile(bad)["success"])

    def test_a_failure_after_the_save_rolls_the_users_writes_back(self):
        user = self._nightly_member_user()
        self._drift_to_volunteer(user)
        self._error_log_rows(user)
        record_before = calc.read_sync_granted_profiles(user)
        self.assertEqual(record_before, [PROFILE_VOLUNTEER], "fixture: record names Volunteer")

        # Mock justified: fails AFTER user_doc.save() inside the real sync.
        with mock.patch.object(calc, "_restore_direct_roles", side_effect=RuntimeError("late")):
            results = sync_role_profiles_for_users([user], nightly=True)

        self.assertEqual(results["errors"], 1, results)
        self.assertIn(PROFILE_VOLUNTEER, calc.get_user_role_profiles(user))
        self.assertNotIn(PROFILE_MEMBER, calc.get_user_role_profiles(user), "saved change survived")
        self.assertEqual(calc.read_sync_granted_profiles(user), record_before, "record write survived")

    def test_summary_line_counts_errors(self):
        bad = self._nightly_member_user()
        self._error_log_rows(bad)
        with mock.patch.object(calc, "get_nightly_sync_users", return_value=[bad]), self._raise_for(
            bad, RuntimeError("boom")
        ), mock.patch("builtins.print") as out:
            nightly_role_profile_sync()
        self.assertIn("errors=1", out.call_args.args[0])

    def test_administrator_and_guest_are_never_listed(self):
        member = self.create_test_member(
            first_name="Adm", last_name=f"A{frappe.generate_hash(length=5)}",
            email=f"adm.{frappe.generate_hash(length=6)}@test.invalid", status="Active",
        )
        frappe.db.set_value("Member", member.name, "user", "Administrator")
        self.assertTrue(frappe.db.get_value("User", "Administrator", "enabled"), "control: enabled")
        self.assertNotIn("Administrator", calc.get_nightly_sync_users())

    # ---- maintainer rulings (#1676): direct roles kept, no strip without a record

    def _grant_direct_role(self, user, role):
        # A User save would reset roles to the profiles' roles, so write the row directly,
        # the way a direct grant is stored.
        doc = frappe.get_doc("User", user)
        row = frappe.new_doc("Has Role", parent_doc=doc, parentfield="roles")
        row.role = role
        row.db_insert()
        frappe.clear_cache(user=user)

    def test_a_direct_role_survives_a_profile_change(self):
        user = self._nightly_member_user()
        self._drift_to_volunteer(user)
        self._grant_direct_role(user, DIRECT_ROLE)
        self.assertIn(DIRECT_ROLE, frappe.get_roles(user), "fixture")

        nightly_role_profile_sync()

        frappe.clear_cache(user=user)
        self.assertNotIn(PROFILE_VOLUNTEER, calc.get_user_role_profiles(user))
        self.assertIn(DIRECT_ROLE, frappe.get_roles(user))
        idx = frappe.db.get_value("Has Role", {"parent": user, "role": DIRECT_ROLE}, "idx")
        self.assertGreater(idx, 0, "restored row kept no position")
        # Control for "keep everything": roles only the old profile supplied ARE withdrawn.
        gone = {r.role for r in frappe.get_doc("Role Profile", PROFILE_VOLUNTEER).roles} - {
            r.role for r in frappe.get_doc("Role Profile", PROFILE_MEMBER).roles
        }
        self.assertTrue(gone - {DIRECT_ROLE}, "fixture: Volunteer adds nothing over Member")
        for role in gone - {DIRECT_ROLE}:
            self.assertNotIn(role, frappe.get_roles(user))

    def test_a_direct_role_survives_a_module_profile_only_change(self):
        user = self._nightly_member_user()
        sync_user_role_profile(user)
        self._grant_direct_role(user, DIRECT_ROLE)
        frappe.db.set_value("User", user, "module_profile", None)
        result = sync_user_role_profile(user, dry_run=True, nightly=True)
        self.assertTrue(result["module_changed"] and not result["role_changed"], f"fixture: {result}")

        nightly_role_profile_sync()

        frappe.clear_cache(user=user)
        self.assertTrue(frappe.db.get_value("User", user, "module_profile"), "module not applied")
        self.assertIn(DIRECT_ROLE, frappe.get_roles(user))

    def test_event_path_still_replaces_direct_roles(self):
        """Control: only the nightly path preserves (#1293 tracks the event path)."""
        user = self._nightly_member_user()
        self._drift_to_volunteer(user)
        self._grant_direct_role(user, DIRECT_ROLE)
        sync_user_role_profile(user)
        frappe.clear_cache(user=user)
        self.assertNotIn(DIRECT_ROLE, frappe.get_roles(user))

    def _assert_hand_assigned_survives_two_nights(self, profile):
        user = self._nightly_member_user()
        self._attach(user, profile)
        frappe.db.set_value("User", user, calc.SYNC_GRANTED_FIELD, None)
        self.assertIsNone(calc.read_sync_granted_profiles(user), "fixture: no record")

        nightly_role_profile_sync()
        self.assertIn(profile, calc.get_user_role_profiles(user), "stripped on night 1")
        self.assertIn(PROFILE_MEMBER, calc.get_user_role_profiles(user), "derived profile not added")
        record = calc.read_sync_granted_profiles(user)
        self.assertIsNotNone(record, "record not written")
        self.assertNotIn(profile, record)

        nightly_role_profile_sync()
        self.assertIn(profile, calc.get_user_role_profiles(user), "stripped on night 2")

    def test_hand_assigned_team_leader_survives_first_and_second_night(self):
        self._assert_hand_assigned_survives_two_nights(PROFILE_TEAM_LEADER)

    def test_hand_assigned_national_treasurer_survives_first_and_second_night(self):
        self._assert_hand_assigned_survives_two_nights(calc.NATIONAL_TREASURER_PROFILE)

    def test_event_path_bootstrap_still_strips_without_a_record(self):
        """Control: the strip these tests forbid for the nightly job is the event path's."""
        user = self._nightly_member_user()
        self._attach(user, PROFILE_TEAM_LEADER)
        frappe.db.set_value("User", user, calc.SYNC_GRANTED_FIELD, None)
        sync_user_role_profile(user)
        self.assertNotIn(PROFILE_TEAM_LEADER, calc.get_user_role_profiles(user))

    # ---- S1: a record-less user the job adds nothing to must stay record-less

    def _legacy_volunteer_holder(self):
        """Holds Volunteer with no record, as pre-record data does, and has an Active volunteer."""
        user = self._nightly_member_user()
        member = frappe.db.get_value("Member", {"user": user}, "name")
        volunteer = self.create_test_volunteer(member=member, status="Active").name
        self._attach(user, PROFILE_VOLUNTEER)
        frappe.db.set_value("User", user, calc.SYNC_GRANTED_FIELD, None)
        self.assertIsNone(calc.read_sync_granted_profiles(user), "fixture: no record")
        return user, volunteer

    def test_nothing_to_add_leaves_the_user_recordless_so_event_bootstrap_still_withdraws(self):
        user, volunteer = self._legacy_volunteer_holder()

        nightly_role_profile_sync()

        self.assertIsNone(calc.read_sync_granted_profiles(user), "nightly wrote a record")
        self.assertIn(PROFILE_VOLUNTEER, calc.get_user_role_profiles(user))
        # Direct status write stands in for the volunteer being deactivated.
        frappe.db.set_value("Volunteer", volunteer, "status", "Inactive")
        sync_user_role_profile(user)  # event path
        held = calc.get_user_role_profiles(user)
        self.assertNotIn(PROFILE_VOLUNTEER, held, "event bootstrap no longer withdraws")
        self.assertIn(PROFILE_MEMBER, held)

    def test_adding_a_profile_writes_the_record_and_ends_the_event_bootstrap(self):
        """Documented residual (maintainer, #1676): the record the job writes is final."""
        user = self._nightly_member_user()
        self._attach(user, PROFILE_VOLUNTEER)  # stale: no Volunteer record; Member is missing
        frappe.db.set_value("User", user, calc.SYNC_GRANTED_FIELD, None)

        nightly_role_profile_sync()

        held = calc.get_user_role_profiles(user)
        self.assertIn(PROFILE_MEMBER, held)
        self.assertEqual(calc.read_sync_granted_profiles(user), [PROFILE_MEMBER])
        sync_user_role_profile(user)  # event path: bootstrap no longer runs
        self.assertIn(PROFILE_VOLUNTEER, calc.get_user_role_profiles(user))
