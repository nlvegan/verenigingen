"""Real-DB integration tests for MijnRoodVolunteerSyncService.

Pure-function tests (_parse_mijnrood_roles) don't need a real DB but
live here for cohesion. Tests for ensure_volunteer / ensure_*_membership
/ end_*_membership / _process_member_roles use EnhancedTestCase with
real Chapter + Team + Volunteer + User fixtures.
"""

import json

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
