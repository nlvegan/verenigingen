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
ACR_AUTO_SYNC = "verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change"
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

    def test_team_permissions_event_propagates_a_lock_error(self):
        """Entry point: handle_permissions_updates wrapped _update_team_permissions in
        ``except Exception`` + log_error, so the helper's re-raise never reached the job."""
        from verenigingen.events.subscribers.team_subscribers import handle_permissions_updates

        team, _volunteer, row = self._team_with_volunteer()
        team.append("team_members", row)
        team.save()
        event = {"team": team.name, "changed_fields": ["default_role_profile"]}
        with self._lock_in_sync():
            with self.assertRaises(frappe.QueryDeadlockError):
                handle_permissions_updates("team_settings_changed", event)

    def test_team_permissions_event_still_logs_an_ordinary_error(self):
        """Control: only a lock error escapes; anything else keeps the logged contract."""
        from verenigingen.events.subscribers import team_subscribers

        title = "Team Permissions Update Error"
        self.expectErrorLog(title)
        event = {"team": "any-team", "changed_fields": ["default_role_profile"]}
        with self.assertErrorLog(title):
            with patch.object(
                team_subscribers, "_update_team_permissions", side_effect=frappe.ValidationError("boom")
            ):
                team_subscribers.handle_permissions_updates("team_settings_changed", event)

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
        """Entry point: handle_permissions_updates wrapped _update_chapter_permissions in
        ``except Exception`` + log_error, so the helper's re-raise never reached the job."""
        from verenigingen.events.subscribers.chapter_subscribers import handle_permissions_updates

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
        event = {"chapter": chapter.name, "changed_fields": ["default_board_role_profile"]}
        with self._lock_in_sync():
            with self.assertRaises(frappe.QueryDeadlockError):
                handle_permissions_updates("chapter_settings_changed", event)

    def test_chapter_permissions_event_still_logs_an_ordinary_error(self):
        """Control: only a lock error escapes; anything else keeps the logged contract."""
        from verenigingen.events.subscribers import chapter_subscribers

        title = "Chapter Permissions Update Error"
        self.expectErrorLog(title)
        event = {"chapter": "any-chapter", "changed_fields": ["default_board_role_profile"]}
        with self.assertErrorLog(title):
            with patch.object(
                chapter_subscribers, "_update_chapter_permissions", side_effect=frappe.ValidationError("boom")
            ):
                chapter_subscribers.handle_permissions_updates("chapter_settings_changed", event)

    def test_account_creation_phase_3_propagates_a_lock_error(self):
        from verenigingen.services.member.account.account_creation_manager import AccountCreationManager

        manager = object.__new__(AccountCreationManager)
        manager.created_user = self._user()[1].name
        with self._lock_in_sync():
            with self.assertRaises(frappe.QueryDeadlockError):
                manager._sync_role_profile()

    def test_account_creation_phase_3_still_swallows_an_ordinary_error(self):
        """Control: the Phase 3 non-fatal contract is intact for anything but a lock error.

        Patched at the name the ACR imports (the deprecated ``utils`` re-export), at
        ``auto_sync_on_role_change`` itself: a fault injected any deeper is swallowed by
        auto_sync before it reaches ``_sync_role_profile``'s handler, which would leave
        this control unable to fail under ``except Exception: raise`` there.
        """
        from verenigingen.services.member.account.account_creation_manager import AccountCreationManager

        manager = object.__new__(AccountCreationManager)
        manager.created_user = self._user()[1].name
        with patch(ACR_AUTO_SYNC, side_effect=RuntimeError("x")) as injected:
            manager._sync_role_profile()  # must not raise
        injected.assert_called_once_with(manager.created_user)

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

    # ------------------------------------------------ F1a / F1c entry points (review round 2)

    def _apply_team_action(self, team_name, member_name):
        from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
            get_volunteer_sync_service,
        )

        config = {"add_to_team": True, "default_team": team_name}
        return get_volunteer_sync_service()._apply_role_actions(member_name, config)

    def _team_for_mijnrood_add(self):
        """An Active Team and a user-bearing volunteer NOT yet on it (the sync adds them)."""
        member, _user = self._user()
        self.create_test_volunteer(member=member.name)
        suffix = frappe.generate_hash(length=6)
        if not frappe.db.exists("Team Role", "Team Member"):
            self.track_doc(
                "Team Role",
                frappe.get_doc(
                    {
                        "doctype": "Team Role",
                        "role_name": "Team Member",
                        "permissions_level": "Basic",
                        "is_team_leader": 0,
                        "is_unique": 0,
                        "is_active": 1,
                    }
                )
                .insert()
                .name,
            )
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"LockErr Add {suffix}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
                "description": "#1888",
            }
        ).insert()
        self.track_doc("Team", team.name)
        return member, team

    def test_mijnrood_team_addition_propagates_a_lock_error(self):
        """_apply_role_actions -> _ensure_team_membership: its ``except Exception`` returned
        'Team addition failed: 1213' and wrote log_error on the discarded transaction."""
        member, team = self._team_for_mijnrood_add()
        with patch(USER_VALIDATE, side_effect=frappe.QueryDeadlockError("1213")):
            with self.assertRaises(frappe.QueryDeadlockError):
                self._apply_team_action(team.name, member.name)

    def test_mijnrood_team_addition_still_reports_an_ordinary_error(self):
        """Control: a non-lock failure keeps the returned-message contract (and a real
        team, so the wrong fix of re-raising everything has something to find)."""
        self.expectErrorLog("MijnRood Sync - Team Addition Failed")
        member, team = self._team_for_mijnrood_add()
        with patch("frappe.model.document.Document.save", side_effect=frappe.ValidationError("boom")):
            messages = self._apply_team_action(team.name, member.name)
        self.assertTrue(any("Team addition failed" in m for m in messages), messages)

    def test_bulk_recalculate_role_profiles_propagates_a_lock_error(self):
        """Whitelisted API: its ``except Exception`` returned {'success': False, 'error': '1213'}."""
        _member, user = self._user()
        with self._lock_in_sync():
            with self.assertRaises(frappe.QueryDeadlockError):
                calc.bulk_recalculate_role_profiles(filters={"name": user.name}, dry_run=False)

    def test_bulk_recalculate_role_profiles_still_returns_an_ordinary_error(self):
        """Control: anything but a lock error keeps the {'success': False} contract."""
        self.expectErrorLog("Role Profile Bulk Sync Error")
        with patch.object(calc, "sync_role_profiles_for_users", side_effect=frappe.ValidationError("boom")):
            result = calc.bulk_recalculate_role_profiles(filters={"name": "x@test.invalid"})
        self.assertFalse(result["success"])
        self.assertIn("boom", result["error"])

    def test_employee_stub_insert_lock_error_reaches_the_sync_caller(self):
        """_ensure_employee_for_profile swallowed a 1213 from Employee.insert (logging
        'Employee Stub Failed') and the sync went on to user.save() on a fresh transaction.
        Injected on Employee.insert only, so the sync's own User.save is untouched."""
        member, user = self._user()
        self.create_test_volunteer(member=member.name)
        real_insert = frappe.model.document.Document.insert

        def insert(doc, *args, **kwargs):
            if doc.doctype == "Employee":
                raise frappe.QueryDeadlockError("1213")
            return real_insert(doc, *args, **kwargs)

        with patch("frappe.model.document.Document.insert", insert):
            with self.assertRaises(frappe.QueryDeadlockError):
                calc.sync_user_role_profile(user.name)

    def test_employee_stub_ordinary_error_is_logged_and_the_sync_completes(self):
        """Control for the handler above: only a lock error escapes _ensure_employee_for_profile.
        Any other failure writes the 'Employee Stub Failed' Error Log row and the sync goes on."""
        title = "Role Profile Sync: Employee Stub Failed"
        self.expectErrorLog(title)
        member, user = self._user()
        self.create_test_volunteer(member=member.name)
        real_insert = frappe.model.document.Document.insert
        seen = []

        def insert(doc, *args, **kwargs):
            if doc.doctype == "Employee":
                seen.append(doc.user_id)
                raise frappe.ValidationError("boom")
            return real_insert(doc, *args, **kwargs)

        with self.assertErrorLog(title):
            with patch("frappe.model.document.Document.insert", insert):
                result = calc.sync_user_role_profile(user.name)
        self.assertEqual(seen, [user.name], "the Employee stub path was never reached")
        self.assertTrue(result["success"], result)

    # ------------------------------------------------ F1 (review round 3): chapter wrapper

    def _chapter_with_board_member(self):
        member, user = self._user()
        volunteer = self.create_test_volunteer(member=member.name)
        chapter = self.create_test_chapter(
            chapter_name=f"LockErr Bulk {frappe.generate_hash(length=6)}",
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
        return chapter, user

    def test_bulk_apply_chapter_board_role_profiles_propagates_a_lock_error(self):
        """Whitelisted wrapper: its ``except Exception`` returned
        {'success': False, 'error': '1213'}. Injected at calculate_user_role_profile, the
        depth the review probe used, through the real chapter and board member."""
        from verenigingen.verenigingen.doctype.chapter.chapter import bulk_apply_chapter_board_role_profiles

        chapter, _user = self._chapter_with_board_member()
        with patch(CALCULATE, side_effect=frappe.QueryDeadlockError("1213")):
            with self.assertRaises(frappe.QueryDeadlockError):
                bulk_apply_chapter_board_role_profiles(chapter.name)

    def test_bulk_apply_chapter_board_role_profiles_still_returns_an_ordinary_error(self):
        """Control: anything but a lock error keeps the {'success': False} answer."""
        from verenigingen.services.chapter import chapter_role_profile_manager as crpm
        from verenigingen.verenigingen.doctype.chapter.chapter import bulk_apply_chapter_board_role_profiles

        title = "Bulk Chapter Board Role Profile Assignment Error"
        self.expectErrorLog(title)
        chapter, _user = self._chapter_with_board_member()
        with self.assertErrorLog(title):
            with patch.object(
                crpm, "bulk_assign_chapter_board_role_profiles", side_effect=frappe.ValidationError("boom")
            ):
                result = bulk_apply_chapter_board_role_profiles(chapter.name)
        self.assertFalse(result["success"])
        self.assertIn("boom", result["error"])
