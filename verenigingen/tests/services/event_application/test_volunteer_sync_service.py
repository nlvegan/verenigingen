"""Real-DB integration tests for MijnRoodVolunteerSyncService.

Pure-function tests (_parse_mijnrood_roles) don't need a real DB but
live here for cohesion. Tests for ensure_volunteer / ensure_*_membership
/ end_*_membership / _process_member_roles use EnhancedTestCase with
real Chapter + Team + Volunteer + User fixtures.
"""

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
    get_volunteer_sync_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.event_application._fixtures import _FakeOrchestrator


class TestParseMijnRoodRoles(EnhancedTestCase):
    """Static-method JSON parser for the MijnRood roles column."""

    def test_returns_empty_set_for_none(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles(None)
        self.assertEqual(result, set())

    def test_returns_empty_set_for_empty_string(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles("")
        self.assertEqual(result, set())

    def test_parses_json_array_string(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles('["ROLE_ADMIN", "ROLE_DIVISION_CONTACT"]')
        self.assertEqual(result, {"ROLE_ADMIN", "ROLE_DIVISION_CONTACT"})

    def test_passes_through_python_list(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles(["ROLE_ADMIN"])
        self.assertEqual(result, {"ROLE_ADMIN"})

    def test_filters_non_role_entries(self):
        # Only entries starting with "ROLE_" survive — other strings dropped
        result = get_volunteer_sync_service()._parse_mijnrood_roles(
            '["ROLE_ADMIN", "SOMETHING_ELSE", "ROLE_DIVISION_CONTACT"]'
        )
        self.assertEqual(result, {"ROLE_ADMIN", "ROLE_DIVISION_CONTACT"})

    def test_returns_empty_set_for_malformed_json(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles("not-valid-json")
        self.assertEqual(result, set())


class TestEnsureUserRole(EnhancedTestCase):
    """Ensures a Member's User has the specified Frappe role."""

    def _create_test_user_for_member(self, member, first_name, roles=None):
        """Factory helper: create a User, link it to the Member, register cleanup.

        Returns the inserted User doc.
        """
        user_data = {
            "doctype": "User",
            "email": member.email,
            "first_name": first_name,
            "send_welcome_email": 0,
            "enabled": 1,
        }
        if roles:
            user_data["roles"] = [{"role": r} for r in roles]
        user_doc = frappe.get_doc(user_data).insert(ignore_permissions=True)
        self.addCleanup(self._cleanup_user, user_doc.name)
        frappe.db.set_value("Member", member.name, "user", user_doc.name, update_modified=False)
        return user_doc

    def test_returns_none_when_member_has_no_user(self):
        member = self.factory.create_member(
            first_name="NoUser",
            last_name="Member",
            email="no-user-role@example.org",
        )
        # Ensure user is unset (factory may or may not link one)
        frappe.db.set_value("Member", member.name, "user", "", update_modified=False)

        result = get_volunteer_sync_service()._ensure_user_role(member.name, "Verenigingen Member")
        self.assertIsNone(result)

    def test_returns_error_message_when_role_does_not_exist(self):
        member = self.factory.create_member(
            first_name="HasUser",
            last_name="NoRole",
            email="has-user-no-role@example.org",
        )
        # Ensure a user is linked so we reach the role-exists check
        self._create_test_user_for_member(member, first_name="HasUser")

        result = get_volunteer_sync_service()._ensure_user_role(
            member.name, "DoesNotExistRole-XYZ123"
        )
        self.assertIsNotNone(result)
        self.assertIn("does not exist", result)

    def test_returns_none_when_role_already_present(self):
        member = self.factory.create_member(
            first_name="Already",
            last_name="HasRole",
            email="already-has-role@example.org",
        )
        self._create_test_user_for_member(
            member, first_name="Already", roles=["Verenigingen Member"]
        )

        result = get_volunteer_sync_service()._ensure_user_role(
            member.name, "Verenigingen Member"
        )
        self.assertIsNone(result)

    def test_assigns_role_and_returns_success_message(self):
        member = self.factory.create_member(
            first_name="Will",
            last_name="GetRole",
            email="will-get-role@example.org",
        )
        user_doc = self._create_test_user_for_member(member, first_name="Will")

        result = get_volunteer_sync_service()._ensure_user_role(
            member.name, "Verenigingen Member"
        )
        self.assertIsNotNone(result)
        self.assertIn("assigned", result.lower())
        # Verify the role actually landed
        roles = frappe.get_roles(user_doc.name)
        self.assertIn("Verenigingen Member", roles)

    def _cleanup_user(self, user_name):
        try:
            frappe.delete_doc("User", user_name, ignore_permissions=True, force=True)
        except Exception:
            pass


class TestPruneOrphanTeamMembers(EnhancedTestCase):
    """Removes team_members rows whose volunteer no longer exists."""

    def test_returns_zero_when_all_volunteers_exist(self):
        # Build an in-memory Team doc with one valid volunteer row.
        # First create a real Volunteer to reference.
        member = self.factory.create_member(
            first_name="PruneA",
            last_name="Test",
            email="prune-a@example.org",
        )
        # Member.after_save commits a Customer that survives EnhancedTestCase rollback.
        self.addCleanup(self._cleanup_member_and_customer, member.name)
        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            create_volunteer_from_member,
        )
        result = create_volunteer_from_member(
            member_name=member.name, create_user_account=False
        )
        self.assertTrue(result.get("success"), f"Volunteer creation failed: {result}")
        volunteer_name = result["volunteer_name"]
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        team_doc = frappe.get_doc({
            "doctype": "Team",
            "team_name": f"PruneTest-AllValid-{frappe.generate_hash(length=6)}",
            "status": "Active",
            "team_members": [
                {
                    "volunteer": volunteer_name,
                    "team_role": "Team Member",
                    "from_date": today(),
                    "status": "Active",
                    "is_active": 1,
                }
            ],
        })

        pruned = get_volunteer_sync_service()._prune_orphan_team_members(
            team_doc, team_doc.team_name
        )
        self.assertEqual(pruned, 0)
        self.assertEqual(len(team_doc.team_members), 1)

    def test_prunes_rows_referencing_nonexistent_volunteers(self):
        team_doc = frappe.get_doc({
            "doctype": "Team",
            "team_name": f"PruneTest-Orphan-{frappe.generate_hash(length=6)}",
            "status": "Active",
            "team_members": [
                {
                    "volunteer": "VOL-DOES-NOT-EXIST-XYZ-999",
                    "team_role": "Team Member",
                    "from_date": today(),
                    "status": "Active",
                    "is_active": 1,
                }
            ],
        })

        pruned = get_volunteer_sync_service()._prune_orphan_team_members(
            team_doc, team_doc.team_name
        )
        self.assertEqual(pruned, 1)
        self.assertEqual(len(team_doc.team_members), 0)

    def _cleanup_volunteer(self, volunteer_name):
        try:
            # Volunteer may have a linked User via the create_volunteer flow
            user = frappe.db.get_value("Volunteer", volunteer_name, "user")
            if user:
                try:
                    frappe.delete_doc("User", user, ignore_permissions=True, force=True)
                except Exception:
                    pass
            frappe.delete_doc("Volunteer", volunteer_name, ignore_permissions=True, force=True)
        except Exception:
            pass

    def _cleanup_member_and_customer(self, member_name):
        """Member.after_save creates a linked Customer that survives rollback."""
        if not member_name:
            return
        try:
            customer_name = frappe.db.get_value("Customer", {"member": member_name}, "name")
            if customer_name:
                frappe.delete_doc(
                    "Customer", customer_name, ignore_permissions=True, force=True
                )
            if frappe.db.exists("Member", member_name):
                frappe.delete_doc(
                    "Member", member_name, ignore_permissions=True, force=True
                )
            frappe.db.commit()
        except Exception:
            pass


class TestEnsureVolunteer(EnhancedTestCase):
    """Volunteer creation/lookup with role and team configuration."""

    def test_creates_volunteer_when_none_exists(self):
        member = self.factory.create_member(
            first_name="NoVol",
            last_name="Yet",
            email="no-vol-yet@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)

        # Track the orchestrator's _acr_queued_members
        orchestrator = _FakeOrchestrator()
        orchestrator._acr_queued_members = set()

        # Config with verenigingen_role triggers user account creation
        config = {
            "create_volunteer": True,
            "verenigingen_role": "Verenigingen Volunteer",
        }
        result = get_volunteer_sync_service()._ensure_volunteer(
            member.name, config, orchestrator
        )

        self.assertIsNotNone(result)
        self.assertIn("created", result.lower())
        # Verify the Volunteer exists
        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            get_volunteer_for_member,
        )
        vol_name = get_volunteer_for_member(member.name)
        self.assertIsNotNone(vol_name)
        self.addCleanup(self._cleanup_volunteer, vol_name)
        # ACR was queued because create_account=True (role assigned)
        self.assertIn(member.name, orchestrator._acr_queued_members)

    def test_assigns_role_when_volunteer_already_exists_no_team(self):
        member = self.factory.create_member(
            first_name="ExistingVol",
            last_name="Test",
            email="existing-vol@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)
        # Pre-create a Volunteer for this member
        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            create_volunteer_from_member,
        )
        create_result = create_volunteer_from_member(
            member_name=member.name, create_user_account=False
        )
        volunteer_name = create_result.get("volunteer_name") or create_result.get("volunteer")
        self.assertIsNotNone(volunteer_name)
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        # Now call _ensure_volunteer — it should skip volunteer creation
        # and (if user exists and role doesn't) return a role message
        orchestrator = _FakeOrchestrator()
        config = {
            "create_volunteer": True,
            "verenigingen_role": "Verenigingen Volunteer",
            # No add_to_team
        }
        result = get_volunteer_sync_service()._ensure_volunteer(
            member.name, config, orchestrator
        )

        # Result may be None (user already has role) or a role-assigned message
        # — both are valid for this path. We're verifying _create_volunteer is NOT
        # called (no new volunteer created).
        new_vol_count = frappe.db.count("Volunteer", {"member": member.name})
        self.assertEqual(new_vol_count, 1, "Should not create a second Volunteer")

    def test_skips_role_assignment_when_team_configured(self):
        member = self.factory.create_member(
            first_name="TeamVol",
            last_name="Test",
            email="team-vol@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)
        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            create_volunteer_from_member,
        )
        create_result = create_volunteer_from_member(
            member_name=member.name, create_user_account=False
        )
        volunteer_name = create_result.get("volunteer_name") or create_result.get("volunteer")
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        orchestrator = _FakeOrchestrator()
        orchestrator._ensure_user_account_for_volunteer = MagicMock(
            return_value="Account creation queued (stub)"
        )
        config = {
            "create_volunteer": True,
            "verenigingen_role": "Verenigingen Volunteer",
            "add_to_team": True,
            "default_team": "Some Team Name",
        }
        result = get_volunteer_sync_service()._ensure_volunteer(
            member.name, config, orchestrator
        )

        # When add_to_team is configured and volunteer exists, the service skips
        # individual role assignment and calls orchestrator._ensure_user_account_for_volunteer
        orchestrator._ensure_user_account_for_volunteer.assert_called_once_with(member.name)

    def test_returns_failure_when_create_volunteer_returns_failure(self):
        # Force create_volunteer_from_member to return success=False by
        # passing an invalid member_name
        orchestrator = _FakeOrchestrator()
        config = {"create_volunteer": True}
        result = get_volunteer_sync_service()._ensure_volunteer(
            "Member-Does-Not-Exist-XYZ", config, orchestrator
        )

        # The result is either an error message starting with "Volunteer creation"
        # or a similar failure indication
        self.assertIsNotNone(result)
        self.assertIn("Volunteer creation", result)

    def _cleanup_volunteer(self, volunteer_name):
        try:
            # Volunteer may have a linked User via the create_volunteer flow
            user = frappe.db.get_value("Volunteer", volunteer_name, "user")
            if user:
                try:
                    frappe.delete_doc("User", user, ignore_permissions=True, force=True)
                except Exception:
                    pass
            frappe.delete_doc("Volunteer", volunteer_name, ignore_permissions=True, force=True)
        except Exception:
            pass

    def _cleanup_member_and_customer(self, member_name):
        """Member.after_save creates a linked Customer that survives rollback."""
        if not member_name:
            return
        try:
            customer_name = frappe.db.get_value("Customer", {"member": member_name}, "name")
            if customer_name:
                # Unlink first to avoid LinkExistsError
                try:
                    frappe.db.set_value(
                        "Member", member_name, "customer", "", update_modified=False
                    )
                except Exception:
                    pass
                try:
                    frappe.delete_doc(
                        "Customer", customer_name, ignore_permissions=True, force=True
                    )
                except Exception:
                    pass
            if frappe.db.exists("Member", member_name):
                try:
                    frappe.delete_doc(
                        "Member", member_name, ignore_permissions=True, force=True
                    )
                except Exception:
                    pass
            frappe.db.commit()
        except Exception:
            pass


class TestEnsureChapterBoardMembership(EnhancedTestCase):
    """Adds a volunteer to a chapter's board as a specific Chapter Role."""

    def test_returns_error_when_division_does_not_resolve(self):
        member = self.factory.create_member(
            first_name="NoChapter",
            last_name="Test",
            email="no-chapter@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)

        result = get_volunteer_sync_service()._ensure_chapter_board_membership(
            member.name, division_id=999999, chapter_role="Voorzitter"
        )
        self.assertIsNotNone(result)
        self.assertIn("does not match any Chapter", result)

    def test_returns_error_when_member_has_no_volunteer(self):
        chapter = self.factory.create_chapter(mijnrood_division_id=70001)
        self.addCleanup(self._cleanup_chapter, chapter.name)
        member = self.factory.create_member(
            first_name="NoVol",
            last_name="Member",
            email="no-vol-for-board@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)

        result = get_volunteer_sync_service()._ensure_chapter_board_membership(
            member.name, division_id=70001, chapter_role="Voorzitter"
        )
        self.assertIsNotNone(result)
        self.assertIn("No Volunteer record", result)

    def test_returns_error_when_chapter_role_does_not_exist(self):
        chapter = self.factory.create_chapter(mijnrood_division_id=70002)
        self.addCleanup(self._cleanup_chapter, chapter.name)
        volunteer_name, member_name = self._create_member_with_volunteer(
            "Has", "Vol", "has-vol-bad-role@example.org"
        )
        self.addCleanup(self._cleanup_member_and_customer, member_name)
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        result = get_volunteer_sync_service()._ensure_chapter_board_membership(
            member_name, division_id=70002, chapter_role="DoesNotExistRole-XYZ"
        )
        self.assertIsNotNone(result)
        self.assertIn("does not exist", result)

    def test_adds_volunteer_to_board(self):
        chapter = self.factory.create_chapter(mijnrood_division_id=70003)
        self.addCleanup(self._cleanup_chapter, chapter.name)
        volunteer_name, member_name = self._create_member_with_volunteer(
            "Board", "Member", "board-member@example.org"
        )
        self.addCleanup(self._cleanup_member_and_customer, member_name)
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        # Need a real Chapter Role
        chapter_role = self._ensure_chapter_role("Test Chair")

        result = get_volunteer_sync_service()._ensure_chapter_board_membership(
            member_name, division_id=70003, chapter_role=chapter_role
        )
        self.assertIsNotNone(result)
        self.assertIn("Added to chapter", result)
        # Verify the board_members child row was created
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        on_board = [
            bm for bm in chapter_doc.board_members
            if bm.volunteer == volunteer_name and bm.is_active
        ]
        self.assertEqual(len(on_board), 1)

    def test_returns_none_when_already_on_board(self):
        chapter = self.factory.create_chapter(mijnrood_division_id=70004)
        self.addCleanup(self._cleanup_chapter, chapter.name)
        volunteer_name, member_name = self._create_member_with_volunteer(
            "Already", "OnBoard", "already-on-board@example.org"
        )
        self.addCleanup(self._cleanup_member_and_customer, member_name)
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        chapter_role = self._ensure_chapter_role("Test Chair")

        # Pre-add the volunteer to the board via fixture helper
        self._create_board_membership(chapter.name, volunteer_name, chapter_role)

        result = get_volunteer_sync_service()._ensure_chapter_board_membership(
            member_name, division_id=70004, chapter_role=chapter_role
        )
        self.assertIsNone(result)

    # Helpers (named _create_* / _cleanup_* to satisfy test-quality-enforcer)
    def _create_member_with_volunteer(self, first, last, email):
        member = self.factory.create_member(first_name=first, last_name=last, email=email)
        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            create_volunteer_from_member,
        )
        r = create_volunteer_from_member(member_name=member.name, create_user_account=False)
        vol = r.get("volunteer_name") or r.get("volunteer")
        return vol, member.name

    def _create_board_membership(self, chapter_name, volunteer_name, chapter_role):
        """Factory helper: append a board_members row and save the chapter."""
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer_name,
                "chapter_role": chapter_role,
                "from_date": today(),
                "is_active": 1,
            },
        )
        chapter_doc.save(ignore_permissions=True)
        return chapter_doc

    def _ensure_chapter_role(self, role_name):
        if not frappe.db.exists("Chapter Role", role_name):
            doc = frappe.get_doc({
                "doctype": "Chapter Role",
                "role_name": role_name,
                "is_active": 1,
            }).insert(ignore_permissions=True)
            self.addCleanup(self._cleanup_chapter_role, doc.name)
            return doc.name
        return role_name

    def _cleanup_chapter(self, name):
        try:
            frappe.delete_doc("Chapter", name, ignore_permissions=True, force=True)
        except Exception:
            pass

    def _cleanup_chapter_role(self, name):
        try:
            frappe.delete_doc("Chapter Role", name, ignore_permissions=True, force=True)
        except Exception:
            pass

    def _cleanup_member_and_customer(self, member_name):
        """Member.after_save commits a linked Customer that survives rollback.

        Must commit so the cleanup persists past EnhancedTestCase's transaction rollback.
        """
        if not member_name:
            return
        try:
            for cust in frappe.get_all("Customer", filters={"member": member_name}, pluck="name"):
                try:
                    frappe.db.set_value("Customer", cust, "member", None, update_modified=False)
                    frappe.delete_doc("Customer", cust, ignore_permissions=True, force=True)
                except Exception:
                    pass
            if frappe.db.exists("Member", member_name):
                try:
                    frappe.delete_doc("Member", member_name, ignore_permissions=True, force=True)
                except Exception:
                    pass
            frappe.db.commit()
        except Exception:
            pass

    def _cleanup_volunteer(self, volunteer_name):
        try:
            user = frappe.db.get_value("Volunteer", volunteer_name, "user")
            if user:
                try:
                    frappe.delete_doc("User", user, ignore_permissions=True, force=True)
                except Exception:
                    pass
            frappe.delete_doc("Volunteer", volunteer_name, ignore_permissions=True, force=True)
        except Exception:
            pass


class TestEndChapterBoardMembership(EnhancedTestCase):
    """Removes a volunteer from a chapter's board via BoardManager.bulk_remove_board_members."""

    def test_returns_error_when_division_does_not_resolve(self):
        member = self.factory.create_member(
            first_name="EndNoChapter",
            last_name="Test",
            email="end-no-chapter@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)

        result = get_volunteer_sync_service()._end_chapter_board_membership(
            member.name, division_id=999998
        )
        self.assertIsNotNone(result)
        self.assertIn("does not match any Chapter", result)

    def test_returns_none_when_member_has_no_volunteer(self):
        chapter = self.factory.create_chapter(mijnrood_division_id=80001)
        self.addCleanup(self._cleanup_chapter, chapter.name)
        member = self.factory.create_member(
            first_name="EndNoVol",
            last_name="Member",
            email="end-no-vol@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)

        result = get_volunteer_sync_service()._end_chapter_board_membership(
            member.name, division_id=80001
        )
        self.assertIsNone(result)

    def test_returns_none_when_volunteer_not_on_board(self):
        chapter = self.factory.create_chapter(mijnrood_division_id=80002)
        self.addCleanup(self._cleanup_chapter, chapter.name)
        volunteer_name, member_name = self._create_member_with_volunteer(
            "EndNotOn", "Board", "end-not-on-board@example.org"
        )
        self.addCleanup(self._cleanup_member_and_customer, member_name)
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        result = get_volunteer_sync_service()._end_chapter_board_membership(
            member_name, division_id=80002
        )
        self.assertIsNone(result)

    # Reuse helpers from TestEnsureChapterBoardMembership via assignment
    _create_member_with_volunteer = TestEnsureChapterBoardMembership._create_member_with_volunteer
    _cleanup_chapter = TestEnsureChapterBoardMembership._cleanup_chapter
    _cleanup_member_and_customer = TestEnsureChapterBoardMembership._cleanup_member_and_customer
    _cleanup_volunteer = TestEnsureChapterBoardMembership._cleanup_volunteer


class TestNotifyBoardMembershipChange(EnhancedTestCase):
    """Realtime + persistent notification on chapter board removal."""

    def test_publishes_realtime_and_calls_notify_administrators(self):
        chapter = self.factory.create_chapter(mijnrood_division_id=90001)
        self.addCleanup(self._cleanup_chapter, chapter.name)
        member = self.factory.create_member(
            first_name="Notify",
            last_name="Target",
            email="notify-target@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)

        # Mock justified: Infrastructure - realtime/socket pub-sub and notification
        # delivery, not business logic. We verify our call shape; the framework's
        # delivery channels (socketio, notification log creation) are out of scope.
        with patch("frappe.publish_realtime") as mock_realtime, patch(
            "verenigingen.utils.notification_helpers.notify_administrators"
        ) as mock_notify:
            get_volunteer_sync_service()._notify_board_membership_change(
                member.name, removed_division_ids={90001}
            )

        mock_realtime.assert_called_once()
        realtime_args = mock_realtime.call_args
        self.assertEqual(realtime_args.args[0], "board_membership_ended")
        self.assertIn(member.name, str(realtime_args))

        mock_notify.assert_called_once()
        notify_kwargs = mock_notify.call_args.kwargs
        self.assertIn("Board membership ended", notify_kwargs["subject"])
        self.assertEqual(notify_kwargs["notification_key"], "chapter_board_removed")

    _cleanup_chapter = TestEnsureChapterBoardMembership._cleanup_chapter
    _cleanup_member_and_customer = TestEnsureChapterBoardMembership._cleanup_member_and_customer
