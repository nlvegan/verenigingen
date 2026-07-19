# -*- coding: utf-8 -*-
"""
In-process integration tests for the suspension API.

These exercise `verenigingen.api.suspension_api` end-to-end against real
documents (members, users, teams) by calling the whitelisted functions directly
under an authenticated user context (`self.as_user`). This is the in-process
counterpart to the old real-HTTP suspension suite: CI runs no web server, so the
HTTP variant could never authenticate and was absorbed by the known-failures
baseline (issue #162). Calling in-process still runs the full `@critical_api`
security wrapper (authorization, audit, input validation), so the auth/RBAC
surface is genuinely covered here.

Return contract: every endpoint is wrapped by `api_security_framework`, whose
success path returns `OperationResult.to_dict(scrub_sensitive=True)` — a plain
dict `{"success": bool, "data": {...}}` on success or
`{"success": False, "error": {"code", "message"}}` on a handled failure. A
security-level authorization failure (wrong Role Profile tier) instead *raises*
`frappe.PermissionError` before the function body runs.
"""

import frappe

from verenigingen.api import suspension_api
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

ADMIN_ROLES = ["System Manager", "Verenigingen Administrator"]


class TestSuspensionAPIIntegration(EnhancedTestCase):
    """Suspension API business logic + RBAC, exercised in-process."""

    def setUp(self):
        super().setUp()

        self.test_chapter = self.ensure_test_chapter(
            chapter_name="Amsterdam",
            attributes={"email": "amsterdam@veganisme.nl"},
        )

        # Admin user authorized for CRITICAL suspension endpoints. The security
        # framework authorizes on Role Profiles, not bare roles, so grant the
        # matching profile (see issue #162).
        self.admin_user = self.create_test_user_with_roles(
            email="suspend.admin@test.verenigingen.invalid",
            roles=ADMIN_ROLES,
            first_name="Suspend",
            last_name="Admin",
        )
        grant_matching_role_profiles(self.admin_user.email, ADMIN_ROLES)

        self.test_member = self.create_test_member(
            first_name="Jan",
            last_name="Suspension",
            email="jan.suspension@test.nl",
            chapter="Amsterdam",
            status="Active",
        )

        # A member with a linked user account, for the user-suspension test.
        self.member_with_user = self.create_test_member(
            first_name="Piet",
            last_name="UserSuspend",
            email="piet.usersuspend@test.nl",
            chapter="Amsterdam",
            status="Active",
        )
        self.linked_user = self.create_test_user_with_roles(
            email=self.member_with_user.email,
            roles=["Verenigingen Member"],
            first_name="Piet",
            last_name="UserSuspend",
        )
        self.member_with_user.user = self.linked_user.name
        self.member_with_user.save()

    # --- helpers -----------------------------------------------------------

    def _suspend(self, member_name, reason="Integration test", **kw):
        with self.as_user(self.admin_user.email):
            return suspension_api.suspend_member(
                member_name=member_name, suspension_reason=reason, **kw
            )

    # --- business-logic tests ---------------------------------------------

    def test_suspend_member(self):
        """suspend_member updates real member status to Suspended."""
        result = self._suspend(
            self.test_member.name, suspend_user=False, suspend_teams=False
        )

        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"]["member_name"], self.test_member.name)

        self.test_member.reload()
        self.assertEqual(self.test_member.status, "Suspended")

    def test_unsuspend_member(self):
        """unsuspend_member restores a suspended member to its prior status."""
        suspend = self._suspend(
            self.test_member.name, suspend_user=False, suspend_teams=False
        )
        self.assertTrue(suspend["success"], msg=suspend)
        self.test_member.reload()
        self.assertEqual(self.test_member.status, "Suspended")

        with self.as_user(self.admin_user.email):
            result = suspension_api.unsuspend_member(
                member_name=self.test_member.name,
                unsuspension_reason="Integration test restoration",
            )

        self.assertTrue(result["success"], msg=result)
        self.test_member.reload()
        self.assertEqual(self.test_member.status, "Active")

    def test_suspension_status_queries(self):
        """get_suspension_status reflects the real suspended state."""
        self.assertTrue(
            self._suspend(
                self.member_with_user.name, suspend_user=False, suspend_teams=False
            )["success"]
        )

        with self.as_user(self.admin_user.email):
            result = suspension_api.get_suspension_status(
                member_name=self.member_with_user.name
            )

        self.assertTrue(result["success"], msg=result)
        data = result["data"]
        self.assertTrue(data["is_suspended"])
        self.assertIn("member_status", data)
        self.assertIn("active_teams", data)

    def test_bulk_suspension(self):
        """bulk_suspend_members suspends every member in the batch."""
        bulk_members = [
            self.create_test_member(
                first_name=f"Bulk{i}",
                last_name="Suspension",
                email=f"bulk{i}.suspension@test.nl",
                chapter="Amsterdam",
                status="Active",
            ).name
            for i in range(3)
        ]

        with self.as_user(self.admin_user.email):
            result = suspension_api.bulk_suspend_members(
                member_list=bulk_members,
                suspension_reason="Bulk integration test",
                suspend_user=False,
                suspend_teams=False,
            )

        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"]["successful"], 3)
        for name in bulk_members:
            self.assertEqual(frappe.db.get_value("Member", name, "status"), "Suspended")

    def test_suspension_preview(self):
        """get_suspension_preview returns a real impact analysis."""
        with self.as_user(self.admin_user.email):
            result = suspension_api.get_suspension_preview(
                member_name=self.member_with_user.name
            )

        self.assertTrue(result["success"], msg=result)
        data = result["data"]
        self.assertIn("member_status", data)
        self.assertIn("has_user_account", data)
        self.assertIn("active_teams", data)

    def test_user_suspension_integration(self):
        """suspend_user=True disables the linked user; unsuspend re-enables it."""
        self.assertEqual(
            frappe.db.get_value("User", self.linked_user.name, "enabled"), 1
        )

        result = self._suspend(
            self.member_with_user.name, suspend_user=True, suspend_teams=False
        )
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(
            frappe.db.get_value("User", self.linked_user.name, "enabled"), 0
        )

        with self.as_user(self.admin_user.email):
            restore = suspension_api.unsuspend_member(
                member_name=self.member_with_user.name,
                unsuspension_reason="Restore user",
            )
        self.assertTrue(restore["success"], msg=restore)
        self.assertEqual(
            frappe.db.get_value("User", self.linked_user.name, "enabled"), 1
        )

    # --- RBAC + validation tests ------------------------------------------

    def test_suspension_permissions_rbac(self):
        """A low-tier user is denied the CRITICAL endpoint; admin is allowed."""
        low_user = self.create_test_user_with_roles(
            email="limited.suspend@test.verenigingen.invalid",
            roles=["Verenigingen Member"],
            first_name="Limited",
            last_name="Member",
        )
        grant_matching_role_profiles(low_user.email, ["Verenigingen Member"])

        # Security-level denial raises before the function body runs.
        with self.as_user(low_user.email), self.assertRaises(frappe.PermissionError):
            suspension_api.suspend_member(
                member_name=self.test_member.name,
                suspension_reason="Should be denied",
            )

        # Member is untouched by the denied attempt.
        self.test_member.reload()
        self.assertEqual(self.test_member.status, "Active")

        # Admin passes the security wrapper and the business permission check.
        with self.as_user(self.admin_user.email):
            allowed = suspension_api.can_suspend_member(
                member_name=self.test_member.name
            )
        self.assertTrue(allowed["success"], msg=allowed)

    def test_suspension_error_handling(self):
        """Handled validation failures return structured error dicts, not crashes."""
        self.expectErrorLog("Suspension API Validation Error")

        missing = self._suspend("NON_EXISTENT_MEMBER", reason="no such member")
        self.assertFalse(missing["success"])
        self.assertEqual(missing["error"]["code"], "DOES_NOT_EXIST")

        empty_reason = self._suspend(self.test_member.name, reason="")
        self.assertFalse(empty_reason["success"])
        self.assertEqual(empty_reason["error"]["code"], "INVALID_INPUT")
