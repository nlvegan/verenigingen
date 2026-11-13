"""#1888: sync_user_role_profile / auto_sync_on_role_change must not swallow 1213/1205.

After a 1213 MariaDB has already rolled the whole transaction back, so a handler that logs
"Role Profile Sync Failed" and returns lets the surrounding save carry on in a fresh implicit
transaction while the role-profile write is lost (the user lacks the role until the nightly sync).
Every other exception keeps the event-driven contract: logged, returned as ``success=False``.

The lock errors are injected, not provoked (a real deadlock needs a second connection racing the
same rows): raising the exact class Frappe raises for 1213/1205 exercises the routing under test.
"""

from unittest.mock import patch

import frappe

from verenigingen.services.member.account import user_role_profile_calculator as calc
from verenigingen.tests.utils.base import VereningingenTestCase

CALCULATE = "verenigingen.services.member.account.user_role_profile_calculator.calculate_user_role_profile"
USER_VALIDATE = "frappe.core.doctype.user.user.User.validate"
SYNC_FAILURE_TITLE = "Role Profile Sync Failed"
LOCK_ERRORS = (frappe.QueryDeadlockError, frappe.QueryTimeoutError)


class TestRoleProfileSyncLockErrors1888(VereningingenTestCase):
    def _user(self):
        member = self.create_test_member(
            first_name="LockErr",
            last_name="Sync",
            email=f"lockerr.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        user = self.create_test_user(member.email)
        self.track_doc("User", user.name)
        member.db_set("user", user.name, update_modified=False)
        return member, user

    # ------------------------------------------------------------ the two functions

    def test_sync_user_role_profile_reraises_lock_errors(self):
        _member, user = self._user()
        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__):
                with patch(CALCULATE, side_effect=error("lock")):
                    with self.assertRaises(error):
                        calc.sync_user_role_profile(user.name)

    def test_auto_sync_on_role_change_reraises_lock_errors(self):
        _member, user = self._user()
        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__):
                with patch(CALCULATE, side_effect=error("lock")):
                    with self.assertRaises(error):
                        calc.auto_sync_on_role_change(user.name)

    def test_lock_error_at_depth_in_user_validate_reaches_the_caller(self):
        """Injected where the real write happens, not on the swallowing entry point."""
        _member, user = self._user()
        with patch(USER_VALIDATE, side_effect=frappe.QueryDeadlockError("1213")):
            with self.assertRaises(frappe.QueryDeadlockError):
                calc.auto_sync_on_role_change(user.name)

    # ------------------------------------------------------------ controls

    def test_ordinary_error_is_still_logged_and_returned_by_sync(self):
        self.expectErrorLog(SYNC_FAILURE_TITLE)
        _member, user = self._user()
        with self.assertErrorLog(SYNC_FAILURE_TITLE):
            with patch(CALCULATE, side_effect=frappe.ValidationError("boom")):
                result = calc.sync_user_role_profile(user.name)
        self.assertFalse(result["success"])
        self.assertIn("boom", result["error"])

    def test_ordinary_error_is_still_swallowed_by_auto_sync(self):
        self.expectErrorLog(SYNC_FAILURE_TITLE)
        _member, user = self._user()
        with self.assertErrorLog(SYNC_FAILURE_TITLE):
            with patch(CALCULATE, side_effect=frappe.ValidationError("boom")):
                result = calc.auto_sync_on_role_change(user.name)
        self.assertFalse(result["success"])

    def test_auto_sync_still_swallows_an_ordinary_error_raised_by_sync_itself(self):
        """auto_sync's own handler: a non-DB exception from the inner call stays fire-and-forget."""
        with patch.object(calc, "sync_user_role_profile", side_effect=RuntimeError("x")):
            self.assertIsNone(calc.auto_sync_on_role_change("nobody@test.invalid"))

    # ------------------------------------------------------------ one caller, end to end

    def _team_with_volunteer(self):
        """A saved Team plus a pending (unsaved) active member row for a user-bearing volunteer."""
        member, _user = self._user()
        volunteer = self.create_test_volunteer(member=member.name)
        suffix = frappe.generate_hash(length=6)
        role = frappe.get_doc(
            {
                "doctype": "Team Role",
                "role_name": f"LockErr Member {suffix}",
                "permissions_level": "Basic",
                "is_team_leader": 0,
                "is_unique": 0,
                "is_active": 1,
            }
        ).insert()
        self.track_doc("Team Role", role.name)
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"LockErr Team {suffix}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
                "description": "#1888",
            }
        ).insert()
        self.track_doc("Team", team.name)
        row = {
            "volunteer": volunteer.name,
            "team_role": role.name,
            "from_date": frappe.utils.today(),
            "is_active": 1,
            "status": "Active",
        }
        return team, volunteer, row

    def test_team_save_aborts_when_the_member_role_sync_deadlocks(self):
        """Team.on_update -> on_team_members_change wrapped the sync in ``except Exception``.

        One level up from the sync, so fixing only the sync would still have logged the
        deadlock and let the Team save commit.
        """
        team, _volunteer, row = self._team_with_volunteer()
        team.append("team_members", row)
        with patch(USER_VALIDATE, side_effect=frappe.QueryDeadlockError("1213")):
            with self.assertRaises(frappe.QueryDeadlockError):
                team.save()

    def test_team_save_aborts_when_the_lost_member_sync_deadlocks(self):
        """The second handler in on_team_members_change (members who LOST active status)."""
        team, _volunteer, row = self._team_with_volunteer()
        team.append("team_members", row)
        team.save()
        team = frappe.get_doc("Team", team.name)
        team.team_members[0].status = "Inactive"
        team.team_members[0].is_active = 0
        with self._lock_in_sync():
            with self.assertRaises(frappe.QueryDeadlockError):
                team.save()

    # ------------------------------------------------ callers that wrapped the sync (#1888)
    # The sync itself is real; the lock error is injected on the call it makes into
    # sync_user_role_profile, so each caller's own handler is what is under test.

    def _lock_in_sync(self, error=frappe.QueryDeadlockError):
        return patch.object(calc, "sync_user_role_profile", side_effect=error("lock"))

    def test_update_team_permissions_propagates_a_lock_error(self):
        from verenigingen.events.subscribers.team_subscribers import _update_team_permissions

        team, _volunteer, row = self._team_with_volunteer()
        team.append("team_members", row)
        team.save()
        with self._lock_in_sync():
            with self.assertRaises(frappe.QueryDeadlockError):
                _update_team_permissions(team.name)

    def test_board_role_assignment_event_propagates_a_lock_error(self):
        from verenigingen.events.subscribers.chapter_subscribers import handle_board_role_assignments

        member, _user = self._user()
        volunteer = self.create_test_volunteer(member=member.name)
        chapter = self.create_test_chapter(
            chapter_name=f"LockErr Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        event = {"chapter": chapter.name, "volunteer": volunteer.name, "action": "added"}
        with self._lock_in_sync():
            with self.assertRaises(frappe.QueryDeadlockError):
                handle_board_role_assignments("chapter_board_changed", event)

    def test_chapter_permissions_event_propagates_a_lock_error(self):
        from verenigingen.events.subscribers.chapter_subscribers import _update_chapter_permissions

        member, _user = self._user()
        volunteer = self.create_test_volunteer(member=member.name)
        chapter = self.create_test_chapter(
            chapter_name=f"LockErr Perm {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        role = self.create_test_chapter_role()
        chapter = frappe.get_doc("Chapter", chapter.name)
        with patch(USER_VALIDATE):  # seat without provisioning anything
            chapter.append(
                "board_members",
                {
                    "volunteer": volunteer.name,
                    "chapter_role": role.name if hasattr(role, "name") else role,
                    "from_date": frappe.utils.today(),
                    "is_active": 1,
                },
            )
            chapter.save()
        with self._lock_in_sync():
            with self.assertRaises(frappe.QueryDeadlockError):
                _update_chapter_permissions(chapter.name)

    def test_account_creation_phase_3_propagates_a_lock_error(self):
        from verenigingen.services.member.account.account_creation_manager import AccountCreationManager

        manager = object.__new__(AccountCreationManager)
        manager.created_user = self._user()[1].name
        with self._lock_in_sync():
            with self.assertRaises(frappe.QueryDeadlockError):
                manager._sync_role_profile()

    def test_account_creation_phase_3_still_swallows_an_ordinary_error(self):
        """Control: the Phase 3 non-fatal contract is intact for anything but a lock error."""
        from verenigingen.services.member.account.account_creation_manager import AccountCreationManager

        manager = object.__new__(AccountCreationManager)
        manager.created_user = self._user()[1].name
        with patch.object(calc, "sync_user_role_profile", side_effect=RuntimeError("x")):
            manager._sync_role_profile()

    def test_bulk_board_sync_propagates_a_lock_error_instead_of_listing_it_as_failed(self):
        from verenigingen.services.chapter import chapter_role_profile_manager as crpm

        fn = crpm.bulk_assign_chapter_board_role_profiles
        while hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        _member, user = self._user()
        with patch.object(crpm, "require_profile_admin"), patch.object(
            frappe.db, "exists", return_value=True
        ), patch.object(frappe.db, "sql", return_value=[{"user": user.name}]), self._lock_in_sync():
            with self.assertRaises(frappe.QueryDeadlockError):
                fn("any-chapter")
