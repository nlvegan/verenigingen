"""Real-DB integration tests for MijnRoodVolunteerSyncService.

Pure-function tests (_parse_mijnrood_roles) don't need a real DB but
live here for cohesion. Tests for ensure_volunteer / ensure_*_membership
/ end_*_membership / _process_member_roles use EnhancedTestCase with
real Chapter + Team + Volunteer + User fixtures.
"""

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import now_datetime, today

from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    MijnRoodRelatedRecordsOrchestrator,
    get_related_records_orchestrator,
)
from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
    get_volunteer_sync_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


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

    def setUp(self):
        super().setUp()
        # The ACR dedup set now lives on the shared related_records
        # orchestrator singleton — reset it so dedup state never leaks
        # between tests.
        get_related_records_orchestrator().reset_acr_dedup()

    def test_creates_volunteer_when_none_exists(self):
        member = self.factory.create_member(
            first_name="NoVol",
            last_name="Yet",
            email="no-vol-yet@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)

        # Config with verenigingen_role triggers user account creation
        config = {
            "create_volunteer": True,
            "verenigingen_role": "Verenigingen Volunteer",
        }
        result = get_volunteer_sync_service()._ensure_volunteer(
            member.name, config
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
        # The success message must name the actual Volunteer, not "None":
        # create_volunteer_from_member returns the name under "volunteer_name".
        self.assertIn(vol_name, result)
        self.assertNotIn("None", result)
        # ACR was queued because create_account=True (role assigned)
        self.assertTrue(get_related_records_orchestrator().is_acr_queued(member.name))

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
        config = {
            "create_volunteer": True,
            "verenigingen_role": "Verenigingen Volunteer",
            # No add_to_team
        }
        result = get_volunteer_sync_service()._ensure_volunteer(
            member.name, config
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

        config = {
            "create_volunteer": True,
            "verenigingen_role": "Verenigingen Volunteer",
            "add_to_team": True,
            "default_team": "Some Team Name",
        }
        # Mock justified: Infrastructure - ACR queueing covered by its own suite
        with patch.object(
            MijnRoodRelatedRecordsOrchestrator,
            "_ensure_user_account_for_volunteer",
            return_value="Account creation queued (stub)",
        ) as mock_acr:
            get_volunteer_sync_service()._ensure_volunteer(member.name, config)

        # When add_to_team is configured and volunteer exists, the service skips
        # individual role assignment and calls
        # related_records._ensure_user_account_for_volunteer
        mock_acr.assert_called_once_with(member.name)

    def test_returns_failure_when_create_volunteer_returns_failure(self):
        # Force create_volunteer_from_member to return success=False by
        # passing an invalid member_name
        config = {"create_volunteer": True}
        result = get_volunteer_sync_service()._ensure_volunteer(
            "Member-Does-Not-Exist-XYZ", config
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


class TestEnsureTeamMembership(EnhancedTestCase):
    """Adds a member's volunteer to a team."""

    def test_returns_error_when_member_has_no_volunteer(self):
        team_name = self._create_team("EnsureTeam-NoVol")
        self.addCleanup(self._cleanup_team, team_name)
        member = self.factory.create_member(
            first_name="NoVolTeam",
            last_name="Test",
            email="no-vol-team@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)

        result = get_volunteer_sync_service()._ensure_team_membership(
            member.name, team_name
        )
        self.assertIsNotNone(result)
        self.assertIn("No Volunteer record", result)

    def test_returns_error_when_team_does_not_exist(self):
        volunteer_name, member_name = self._create_member_with_volunteer(
            "TeamGone", "Test", "team-gone@example.org"
        )
        self.addCleanup(self._cleanup_member_and_customer, member_name)
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        result = get_volunteer_sync_service()._ensure_team_membership(
            member_name, "Team-Does-Not-Exist-XYZ-999"
        )
        self.assertIsNotNone(result)
        self.assertIn("does not exist", result)

    def test_returns_error_when_team_is_not_active(self):
        team_name = self._create_team("EnsureTeam-Inactive", status="Inactive")
        self.addCleanup(self._cleanup_team, team_name)
        volunteer_name, member_name = self._create_member_with_volunteer(
            "TeamInactive", "Test", "team-inactive@example.org"
        )
        self.addCleanup(self._cleanup_member_and_customer, member_name)
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        result = get_volunteer_sync_service()._ensure_team_membership(
            member_name, team_name
        )
        self.assertIsNotNone(result)
        self.assertIn("not active", result)

    def test_adds_volunteer_to_team(self):
        team_name = self._create_team("EnsureTeam-Add")
        self.addCleanup(self._cleanup_team, team_name)
        volunteer_name, member_name = self._create_member_with_volunteer(
            "AddedTo", "Team", "added-to-team@example.org"
        )
        self.addCleanup(self._cleanup_member_and_customer, member_name)
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        result = get_volunteer_sync_service()._ensure_team_membership(
            member_name, team_name
        )
        self.assertIsNotNone(result)
        self.assertIn("Added to team", result)
        # Verify the Team Member row exists
        on_team = frappe.db.exists(
            "Team Member",
            {"parent": team_name, "volunteer": volunteer_name, "status": "Active"},
        )
        self.assertTrue(on_team)

    def test_returns_none_when_already_on_team(self):
        team_name = self._create_team("EnsureTeam-Already")
        self.addCleanup(self._cleanup_team, team_name)
        volunteer_name, member_name = self._create_member_with_volunteer(
            "AlreadyOn", "Team", "already-on-team@example.org"
        )
        self.addCleanup(self._cleanup_member_and_customer, member_name)
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        # Pre-add the volunteer
        self._create_team_membership(team_name, volunteer_name)

        result = get_volunteer_sync_service()._ensure_team_membership(
            member_name, team_name
        )
        self.assertIsNone(result)

    # Factory helpers (named _create_* to satisfy test-quality-enforcer)
    def _create_team(self, name_prefix, status="Active"):
        team_name = f"{name_prefix}-{frappe.generate_hash(length=6)}"
        frappe.get_doc({
            "doctype": "Team",
            "team_name": team_name,
            "status": status,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        return team_name

    def _create_team_membership(self, team_name, volunteer_name):
        team_doc = frappe.get_doc("Team", team_name)
        team_doc.append("team_members", {
            "volunteer": volunteer_name,
            "team_role": "Team Member",
            "from_date": today(),
            "status": "Active",
            "is_active": 1,
        })
        team_doc.save(ignore_permissions=True)
        frappe.db.commit()

    def _create_member_with_volunteer(self, first, last, email):
        member = self.factory.create_member(first_name=first, last_name=last, email=email)
        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            create_volunteer_from_member,
        )
        r = create_volunteer_from_member(member_name=member.name, create_user_account=False)
        vol = r.get("volunteer_name") or r.get("volunteer")
        return vol, member.name

    def _cleanup_team(self, team_name):
        try:
            if frappe.db.exists("Team", team_name):
                frappe.delete_doc("Team", team_name, ignore_permissions=True, force=True)
                frappe.db.commit()
        except Exception:
            pass

    def _cleanup_member_and_customer(self, member_name):
        for cust in frappe.get_all("Customer", filters={"member": member_name}, pluck="name"):
            try:
                frappe.db.set_value("Customer", cust, "member", None, update_modified=False)
                frappe.delete_doc("Customer", cust, ignore_permissions=True, force=True)
            except Exception:
                pass
        try:
            if frappe.db.exists("Member", member_name):
                frappe.delete_doc("Member", member_name, ignore_permissions=True, force=True)
        except Exception:
            pass
        frappe.db.commit()

    def _cleanup_volunteer(self, volunteer_name):
        try:
            user = frappe.db.get_value("Volunteer", volunteer_name, "user")
            if user:
                try:
                    frappe.delete_doc("User", user, ignore_permissions=True, force=True)
                except Exception:
                    pass
            if frappe.db.exists("Volunteer", volunteer_name):
                frappe.delete_doc("Volunteer", volunteer_name, ignore_permissions=True, force=True)
        except Exception:
            pass
        frappe.db.commit()


class TestEndTeamMembership(EnhancedTestCase):
    """Ends an active team membership when role is revoked."""

    def test_returns_none_when_member_has_no_volunteer(self):
        team_name = self._create_team("EndTeam-NoVol")
        self.addCleanup(self._cleanup_team, team_name)
        member = self.factory.create_member(
            first_name="EndNoVol",
            last_name="Test",
            email="end-team-no-vol@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)

        result = get_volunteer_sync_service()._end_team_membership(
            member.name, team_name
        )
        self.assertIsNone(result)

    def test_returns_none_when_not_on_team(self):
        team_name = self._create_team("EndTeam-NotOn")
        self.addCleanup(self._cleanup_team, team_name)
        volunteer_name, member_name = self._create_member_with_volunteer(
            "EndNotOn", "Team", "end-not-on-team@example.org"
        )
        self.addCleanup(self._cleanup_member_and_customer, member_name)
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        result = get_volunteer_sync_service()._end_team_membership(
            member_name, team_name
        )
        self.assertIsNone(result)

    def test_ends_active_team_membership(self):
        team_name = self._create_team("EndTeam-Active")
        self.addCleanup(self._cleanup_team, team_name)
        volunteer_name, member_name = self._create_member_with_volunteer(
            "EndActive", "Team", "end-active-team@example.org"
        )
        self.addCleanup(self._cleanup_member_and_customer, member_name)
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        # Pre-add the volunteer as active
        self._create_team_membership(team_name, volunteer_name)

        # production_validation(): EnhancedTestCase.setUp sets frappe.flags.in_import,
        # which makes Document._validate_selects() return early. Production runs with
        # the flag off, so an out-of-options status value throws there and not here.
        with self.production_validation():
            result = get_volunteer_sync_service()._end_team_membership(
                member_name, team_name
            )
        self.assertIsNotNone(result)
        self.assertIn("Removed from team", result)

        # Verify the row was ended with a value the Select field actually allows
        team_doc = frappe.get_doc("Team", team_name)
        ended_rows = [
            row for row in team_doc.team_members
            if row.volunteer == volunteer_name and row.status == "Completed"
        ]
        self.assertEqual(len(ended_rows), 1)
        self.assertEqual(ended_rows[0].is_active, 0)
        self.assertEqual(str(ended_rows[0].to_date), today())

    # Reuse helpers from TestEnsureTeamMembership
    _create_team = TestEnsureTeamMembership._create_team
    _create_team_membership = TestEnsureTeamMembership._create_team_membership
    _create_member_with_volunteer = TestEnsureTeamMembership._create_member_with_volunteer
    _cleanup_team = TestEnsureTeamMembership._cleanup_team
    _cleanup_member_and_customer = TestEnsureTeamMembership._cleanup_member_and_customer
    _cleanup_volunteer = TestEnsureTeamMembership._cleanup_volunteer


class TestApplyRoleActions(EnhancedTestCase):
    """Dispatcher that fans out to ensure-methods based on config."""

    def setUp(self):
        super().setUp()
        # Mock justified: Routing - testing dispatcher logic, downstream
        # methods (_ensure_volunteer, _ensure_chapter_board_membership,
        # _ensure_team_membership) are covered by their own tests in
        # TestEnsureVolunteer / TestEnsureChapterBoardMembership /
        # TestEnsureTeamMembership.
        from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
            MijnRoodVolunteerSyncService,
        )
        self.service = MijnRoodVolunteerSyncService()
        self.service._ensure_volunteer = MagicMock(return_value="Volunteer V1 created")
        self.service._ensure_chapter_board_membership = MagicMock(return_value="Added to board")
        self.service._ensure_team_membership = MagicMock(return_value="Added to team")

    def test_create_volunteer_triggers_ensure_volunteer(self):
        config = {"create_volunteer": True, "verenigingen_role": "Verenigingen Volunteer"}
        msgs = self.service._apply_role_actions("MEM-001", config)
        self.service._ensure_volunteer.assert_called_once_with(
            "MEM-001", config, event=None
        )
        self.assertIn("Volunteer V1 created", msgs)

    def test_add_to_chapter_board_calls_ensure_board_per_division(self):
        config = {
            "add_to_chapter_board": True,
            "chapter_role": "Voorzitter",
        }
        msgs = self.service._apply_role_actions(
            "MEM-002", config, division_ids=[10, 20]
        )
        # Called once per division_id
        self.assertEqual(self.service._ensure_chapter_board_membership.call_count, 2)
        self.assertEqual(len([m for m in msgs if "Added to board" in m]), 2)

    def test_add_to_chapter_board_without_chapter_role_warns(self):
        config = {"add_to_chapter_board": True}  # missing chapter_role
        msgs = self.service._apply_role_actions(
            "MEM-003", config, division_ids=[10]
        )
        self.service._ensure_chapter_board_membership.assert_not_called()
        self.assertTrue(any("no chapter_role configured" in m for m in msgs))

    def test_add_to_team_calls_ensure_team(self):
        config = {"add_to_team": True, "default_team": "TestTeam"}
        msgs = self.service._apply_role_actions("MEM-004", config)
        self.service._ensure_team_membership.assert_called_once_with(
            "MEM-004", "TestTeam", event=None
        )
        self.assertIn("Added to team", msgs)


class TestHandleAdminRoleChange(EnhancedTestCase):
    """Detects ROLE_ADMIN transitions and applies actions or end-actions."""

    def setUp(self):
        super().setUp()
        # Mock justified: Routing - dispatcher logic, downstream methods
        # tested elsewhere.
        from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
            MijnRoodVolunteerSyncService,
        )
        self.service = MijnRoodVolunteerSyncService()
        self.service._apply_role_actions = MagicMock(return_value=["role action applied"])
        self.service._end_team_membership = MagicMock(return_value="Removed from team")

    def test_role_admin_added_calls_apply_role_actions(self):
        role_config = {"ROLE_ADMIN": {"create_volunteer": True}}
        msgs = self.service._handle_admin_role_change(
            "MEM-A1", current_roles={"ROLE_ADMIN"}, old_roles=set(), role_config=role_config
        )
        self.service._apply_role_actions.assert_called_once()
        self.assertEqual(msgs, ["role action applied"])

    def test_role_admin_removed_with_team_config_ends_team(self):
        role_config = {"ROLE_ADMIN": {"add_to_team": True, "default_team": "AdminTeam"}}
        msgs = self.service._handle_admin_role_change(
            "MEM-A2", current_roles=set(), old_roles={"ROLE_ADMIN"}, role_config=role_config
        )
        self.service._end_team_membership.assert_called_once_with(
            "MEM-A2", "AdminTeam", event=None
        )
        self.assertTrue(any("Removed from team" in m for m in msgs))
        self.assertTrue(any("ROLE_ADMIN removed" in m for m in msgs))

    def test_role_admin_unchanged_returns_empty(self):
        # Admin role present in both old and current — no transition
        role_config = {"ROLE_ADMIN": {"create_volunteer": True}}
        msgs = self.service._handle_admin_role_change(
            "MEM-A3",
            current_roles={"ROLE_ADMIN"},
            old_roles={"ROLE_ADMIN"},
            role_config=role_config,
        )
        self.service._apply_role_actions.assert_not_called()
        self.service._end_team_membership.assert_not_called()
        self.assertEqual(msgs, [])


class TestHandleDivisionContactChange(EnhancedTestCase):
    """Detects ROLE_DIVISION_CONTACT additions/removals."""

    def setUp(self):
        super().setUp()
        # Mock justified: Routing - dispatcher logic, downstream methods
        # tested elsewhere.
        from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
            MijnRoodVolunteerSyncService,
        )
        self.service = MijnRoodVolunteerSyncService()
        self.service._apply_role_actions = MagicMock(return_value=["role action applied"])
        self.service._end_chapter_board_membership = MagicMock(return_value="Removed from board")
        self.service._notify_board_membership_change = MagicMock(return_value=None)

    def test_new_divisions_call_apply_role_actions(self):
        role_config = {"ROLE_DIVISION_CONTACT": {"add_to_chapter_board": True}}
        msgs = self.service._handle_division_contact_change(
            "MEM-D1",
            new_division_ids=[42],
            old_division_ids=None,
            role_config=role_config,
        )
        self.service._apply_role_actions.assert_called_once()
        self.assertEqual(msgs, ["role action applied"])

    def test_removed_divisions_call_end_board_and_notify(self):
        role_config = {"ROLE_DIVISION_CONTACT": {"add_to_chapter_board": True}}
        msgs = self.service._handle_division_contact_change(
            "MEM-D2",
            new_division_ids=[10],
            old_division_ids=[10, 20, 30],
            role_config=role_config,
        )
        # _end_chapter_board_membership called once per removed division (20, 30)
        self.assertEqual(self.service._end_chapter_board_membership.call_count, 2)
        # Notify called once with the set of removed divisions
        self.service._notify_board_membership_change.assert_called_once()
        notify_args = self.service._notify_board_membership_change.call_args
        self.assertEqual(notify_args.args[0], "MEM-D2")
        self.assertEqual(notify_args.args[1], {20, 30})


class TestProcessMemberRoles(EnhancedTestCase):
    """Entry point that parses roles + dispatches to handlers."""

    def setUp(self):
        super().setUp()
        # Mock justified: Routing entry point - handlers tested elsewhere.
        from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
            MijnRoodVolunteerSyncService,
        )
        self.service = MijnRoodVolunteerSyncService()
        self.service._handle_admin_role_change = MagicMock(return_value=["admin handled"])
        self.service._handle_division_contact_change = MagicMock(return_value=["division handled"])

    def test_returns_empty_when_role_config_is_empty(self):
        # get_role_mapping() returns {} when no mapping is configured
        with patch(
            "verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service.get_role_mapping",
            return_value={},
        ):
            msgs = self.service._process_member_roles("MEM-P1", mijnrood_data={"roles": '["ROLE_ADMIN"]'})
        self.assertEqual(msgs, [])
        self.service._handle_admin_role_change.assert_not_called()

    def test_dispatches_to_both_handlers(self):
        # get_role_mapping() returns a non-empty dict
        with patch(
            "verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service.get_role_mapping",
            return_value={"ROLE_ADMIN": {"create_volunteer": True}},
        ):
            msgs = self.service._process_member_roles(
                "MEM-P2",
                mijnrood_data={"roles": '["ROLE_ADMIN"]', "managed_division_ids": [10]},
                old_data={"roles": "[]", "managed_division_ids": []},
            )

        self.service._handle_admin_role_change.assert_called_once()
        admin_call = self.service._handle_admin_role_change.call_args
        # current_roles, old_roles — verify parse_mijnrood_roles output flowed through
        self.assertEqual(admin_call.args[1], {"ROLE_ADMIN"})
        self.assertEqual(admin_call.args[2], set())

        self.service._handle_division_contact_change.assert_called_once()
        self.assertIn("admin handled", msgs)
        self.assertIn("division handled", msgs)


class TestRoleRevocationClosesAccess(EnhancedTestCase):
    """ROLE_ADMIN revocation must actually revoke the team-derived role profile.

    These are access-control tests, not bookkeeping tests: asserting that the Team
    Member row changed is not enough, because the whole point of ending the row is
    that ``on_team_members_change`` recalculates the user's role profile. Every
    assertion here therefore ends on the User's effective role profile.

    Calls that must mirror production run inside ``production_validation()``:
    ``EnhancedTestCase.setUp`` sets ``frappe.flags.in_import``, and
    ``Document._validate_selects()`` (base_document.py) returns early on that flag —
    so an out-of-options Select value is silently accepted here while it throws in
    production.
    """

    # Team profile deliberately outranks the member/volunteer baseline
    # (PRIORITY_STAFF 75 > PRIORITY_VOLUNTEER 30 > PRIORITY_MEMBER 10).
    TEAM_PROFILE = "Verenigingen Staff"
    BASE_PROFILE = "Verenigingen Member"

    def _create_staff_team(self, label):
        """An association-wide team whose membership grants TEAM_PROFILE."""
        team_name = f"{label}-{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": team_name,
                "status": "Active",
                "is_association_wide": 1,
                "default_role_profile": self.TEAM_PROFILE,
            }
        ).insert(ignore_permissions=True)
        frappe.db.commit()
        self.addCleanup(self._cleanup_team, team_name)
        return team_name

    def _create_admin_on_team(self, label, team_name):
        """Member + User + Volunteer, active on ``team_name``, profile synced.

        Returns (member_name, user_name, volunteer_name).
        """
        member = self.factory.create_member(
            first_name=label,
            last_name="Revoke",
            email=f"{label.lower()}-revoke-{frappe.generate_hash(length=6)}@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)

        user_doc = frappe.get_doc(
            {
                "doctype": "User",
                "email": member.email,
                "first_name": label,
                "send_welcome_email": 0,
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        self.addCleanup(self._cleanup_user, user_doc.name)
        frappe.db.set_value("Member", member.name, "user", user_doc.name, update_modified=False)

        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            create_volunteer_from_member,
        )

        result = create_volunteer_from_member(member_name=member.name, create_user_account=False)
        volunteer_name = result.get("volunteer_name") or result.get("volunteer")
        self.addCleanup(self._cleanup_volunteer, volunteer_name)

        team_doc = frappe.get_doc("Team", team_name)
        team_doc.append(
            "team_members",
            {
                "volunteer": volunteer_name,
                "team_role": "Team Member",
                "from_date": today(),
                "status": "Active",
                "is_active": 1,
            },
        )
        team_doc.save(ignore_permissions=True)
        frappe.db.commit()

        # Baseline: the team membership must actually have granted the profile,
        # otherwise the revocation assertion below would pass vacuously.
        from verenigingen.services.member.account.user_role_profile_calculator import (
            sync_user_role_profile,
        )

        sync_user_role_profile(user_doc.name)
        self.assertEqual(
            self._effective_profile(user_doc.name),
            self.TEAM_PROFILE,
            "fixture is not exercising the escalation path",
        )
        return member.name, user_doc.name, volunteer_name

    def _effective_profile(self, user_name):
        from verenigingen.services.member.account.user_role_profile_calculator import (
            get_user_role_profiles,
        )

        profiles = get_user_role_profiles(user_name)
        if profiles:
            return profiles[0]
        return frappe.db.get_value("User", user_name, "role_profile_name")

    def _team_member_row(self, team_name, volunteer_name):
        team_doc = frappe.get_doc("Team", team_name)
        rows = [r for r in team_doc.team_members if r.volunteer == volunteer_name]
        self.assertEqual(len(rows), 1)
        return rows[0]

    # ── the bug ────────────────────────────────────────────────────────

    def test_revocation_revokes_team_derived_role_profile(self):
        team_name = self._create_staff_team("RevokeTeam")
        member_name, user_name, volunteer_name = self._create_admin_on_team("Revoked", team_name)

        with self.production_validation():
            msg = get_volunteer_sync_service()._end_team_membership(member_name, team_name)

        self.assertIsNotNone(msg)
        self.assertIn("Removed from team", msg)

        row = self._team_member_row(team_name, volunteer_name)
        self.assertEqual(row.status, "Completed")
        self.assertEqual(row.is_active, 0)
        self.assertEqual(str(row.to_date), today())

        # The point of the fix: on_team_members_change must have re-run and
        # dropped the team-derived profile.
        self.assertEqual(self._effective_profile(user_name), self.BASE_PROFILE)

    def test_admin_role_change_revokes_profile_end_to_end(self):
        """The transition handler — not just the helper — must close the access."""
        team_name = self._create_staff_team("RevokeHandler")
        member_name, user_name, _volunteer_name = self._create_admin_on_team("Handler", team_name)
        role_config = {"ROLE_ADMIN": {"add_to_team": True, "default_team": team_name}}

        with self.production_validation():
            msgs = get_volunteer_sync_service()._handle_admin_role_change(
                member_name,
                current_roles=set(),
                old_roles={"ROLE_ADMIN"},
                role_config=role_config,
            )

        self.assertTrue(any("Removed from team" in m for m in msgs), msgs)
        self.assertTrue(any("ROLE_ADMIN removed" in m for m in msgs), msgs)
        self.assertEqual(self._effective_profile(user_name), self.BASE_PROFILE)

    # ── failure must not be reported as success ────────────────────────

    def test_failed_removal_raises_instead_of_reporting_success(self):
        """A revocation that cannot be persisted must not return a success message.

        Failure is injected by breaking a real link on the Team (the state left
        behind when a Chapter is force-deleted out from under a team), so
        ``_validate_links()`` rejects the save. No business logic is mocked.
        """
        team_name = self._create_staff_team("RevokeFails")
        member_name, user_name, volunteer_name = self._create_admin_on_team("Fails", team_name)
        frappe.db.set_value(
            "Team", team_name, "chapter", "Chapter-Deleted-XYZ-999", update_modified=False
        )
        frappe.db.commit()
        self.expectErrorLog("MijnRood Sync - Team Removal Failed")

        role_config = {"ROLE_ADMIN": {"add_to_team": True, "default_team": team_name}}
        with self.production_validation():
            with self.assertRaises(frappe.ValidationError):
                get_volunteer_sync_service()._handle_admin_role_change(
                    member_name,
                    current_roles=set(),
                    old_roles={"ROLE_ADMIN"},
                    role_config=role_config,
                )

        # And the access really is still open — which is exactly why the caller
        # must not be told "ROLE_ADMIN removed".
        self.assertEqual(
            frappe.db.get_value(
                "Team Member", {"parent": team_name, "volunteer": volunteer_name}, "status"
            ),
            "Active",
        )
        self.assertEqual(self._effective_profile(user_name), self.TEAM_PROFILE)

    def test_apply_event_records_failure_instead_of_marking_applied(self):
        """The effective layer: apply_event() is where the raise becomes visible.

        Every frame between _end_team_membership and apply_event passes messages
        through and returns success=True unconditionally, so this is the boundary
        that has to observe the failure — and it must leave the event un-Applied
        so an operator re-runs it.
        """
        from verenigingen.mijnrood_sync.services.event_application.dispatcher import (
            get_event_application_service,
        )

        team_name = self._create_staff_team("RevokeEvent")
        member_name, user_name, volunteer_name = self._create_admin_on_team("Event", team_name)
        frappe.db.set_value(
            "Team", team_name, "chapter", "Chapter-Deleted-XYZ-999", update_modified=False
        )
        frappe.db.commit()
        self.expectErrorLog(
            "MijnRood Sync - Team Removal Failed", "MijnRood Event Application Failed"
        )
        self._setup_role_mapping(
            mijnrood_role="ROLE_ADMIN", label="Admin", add_to_team=1, default_team=team_name
        )
        event = self._create_role_removal_event(member_name)

        with self.production_validation():
            result = get_event_application_service().apply_event(event.name)

        self.assertFalse(result.get("success"), result)
        event.reload()
        self.assertNotEqual(event.status, "Applied")
        self.assertTrue(event.error_message)

        # Access unchanged — which is what "not Applied" has to mean here.
        self.assertEqual(
            frappe.db.get_value(
                "Team Member", {"parent": team_name, "volunteer": volunteer_name}, "status"
            ),
            "Active",
        )
        self.assertEqual(self._effective_profile(user_name), self.TEAM_PROFILE)

    # ── fixture + cleanup helpers ──────────────────────────────────────

    def _create_role_removal_event(self, member_name):
        """An Approved 'Changed' event whose only delta is ROLE_ADMIN going away."""
        event = frappe.get_doc(
            {
                "doctype": "MijnRood Sync Event",
                "event_type": "Changed",
                "status": "Pending",
                "mijnrood_table": "admin_member",
                "mijnrood_row_id": 990001,
                "detected_at": now_datetime(),
                "linked_member": member_name,
                "old_data": json.dumps({"roles": '["ROLE_ADMIN"]'}),
                "new_data": json.dumps({"roles": "[]"}),
                "changed_fields": json.dumps(
                    [{"field": "roles", "old": '["ROLE_ADMIN"]', "new": "[]"}]
                ),
            }
        ).insert(ignore_permissions=True)
        self.addCleanup(self._cleanup_event, event.name)
        event.approve()
        frappe.db.commit()
        return event

    def _setup_role_mapping(self, **fields):
        """Point MijnRood Sync Settings at this test's team, then restore.

        MijnRood Sync Settings is a Single: its writes are committed and survive
        the harness rollback, so the prior rows are snapshotted and restored.
        """
        settings = frappe.get_single("MijnRood Sync Settings")
        snapshot = [r.as_dict() for r in (settings.role_mapping or [])]
        self.addCleanup(self._restore_role_mapping, snapshot)
        settings.set("role_mapping", [])
        settings.append("role_mapping", fields)
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache.delete_value("mijnrood_role_mapping")

    def _restore_role_mapping(self, snapshot):
        settings = frappe.get_single("MijnRood Sync Settings")
        settings.set("role_mapping", [])
        for row in snapshot:
            settings.append("role_mapping", row)
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache.delete_value("mijnrood_role_mapping")

    def _cleanup_event(self, event_name):
        try:
            if frappe.db.exists("MijnRood Sync Event", event_name):
                frappe.delete_doc("MijnRood Sync Event", event_name, ignore_permissions=True, force=True)
        except Exception:
            pass
        frappe.db.commit()

    def _cleanup_user(self, user_name):
        for emp in frappe.get_all("Employee", filters={"user_id": user_name}, pluck="name"):
            try:
                frappe.db.set_value("Employee", emp, "user_id", None, update_modified=False)
                frappe.delete_doc("Employee", emp, ignore_permissions=True, force=True)
            except Exception:
                pass
        try:
            frappe.delete_doc("User", user_name, ignore_permissions=True, force=True)
        except Exception:
            pass
        frappe.db.commit()

    _cleanup_team = TestEnsureTeamMembership._cleanup_team
    _cleanup_member_and_customer = TestEnsureTeamMembership._cleanup_member_and_customer
    _cleanup_volunteer = TestEnsureTeamMembership._cleanup_volunteer
