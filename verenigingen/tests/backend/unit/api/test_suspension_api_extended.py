"""
Extended real-DB integration coverage for verenigingen/api/suspension_api.py.

Complements tests/backend/workflows/test_suspension_api.py (which covers the core
suspend/unsuspend/preview/bulk happy paths) by exercising the remaining endpoints
and branches: get_suspension_list pagination/filtering, get_suspension_status_safe
(own-record / admin / guest / no-member / other-member-denied), can_suspend_member
without a member_name and its fallback path, _can_suspend_member_fallback directly,
and test_bank_details_debug.

NO business-logic mocking: members are real fixtures, suspension state is produced
by the real suspend_member endpoint, and expected values are derived from the data
each test creates. The @*_api decorators serialize OperationResult into plain dicts
for in-process calls, so assertions target the dict shape the caller receives.
"""

import frappe

from verenigingen.api.suspension_api import (
    _can_suspend_member_fallback,
    can_suspend_member,
    get_suspension_list,
    get_suspension_status_safe,
    suspend_member,
    test_bank_details_debug,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSuspensionAPIExtended(EnhancedTestCase):
    """Coverage for the previously-untested suspension API surface."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="SuspExt",
            last_name="Member",
            status="Active",
        )

    def _make_user(self, email, *, role_profile=None):
        """Create (idempotently) a real non-admin User.

        ``role_profile`` assigns a Role Profile (User.role_profile_name) so the user
        clears the API security framework's role-profile auth ladder. "Verenigingen
        Volunteer" grants MEDIUM (the self-service tier) -- ordinary members hold the
        "Verenigingen Member" profile which only grants LOW, so MEDIUM endpoints like
        get_suspension_status_safe require the volunteer/self-service profile.
        """
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Susp",
                    "last_name": "User",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()
        if role_profile:
            frappe.db.set_value("User", email, "role_profile_name", role_profile)
        frappe.db.commit()
        # Bust the authorization engine's role-profile cache so the new assignment is seen.
        frappe.cache().delete_keys("user_role_profiles")
        return email

    def _grant_medium_profile(self, email):
        """get_suspension_status_safe is @standard_api(MEMBER_DATA) = MEDIUM, so the
        caller must hold the "Verenigingen Volunteer" role profile to clear the auth
        ladder and reach the endpoint's own/other/no-member branches at all."""
        frappe.db.set_value("User", email, "role_profile_name", "Verenigingen Volunteer")
        frappe.db.commit()
        frappe.cache().delete_keys("user_role_profiles")

    # ------------------------------------------------------------------
    # get_suspension_list
    # ------------------------------------------------------------------
    def test_get_suspension_list_includes_suspended_member(self):
        # Suspend a real member, then confirm it surfaces in the list.
        suspend_result = suspend_member(
            self.member.name,
            "List coverage suspension",
            suspend_user=False,
            suspend_teams=False,
        )
        self.assertTrue(suspend_result.get("success"), msg=suspend_result)

        result = get_suspension_list()
        self.assertTrue(result["success"], msg=result)
        data = result["data"]
        names = [m["name"] for m in data["data"]]
        self.assertIn(self.member.name, names)
        # Total count must be at least the number of returned rows.
        self.assertGreaterEqual(data["total"], len(data["data"]))
        # Each row carries the enrichment field.
        for row in data["data"]:
            self.assertIn("active_team_count", row)

    def test_get_suspension_list_excludes_active_member(self):
        # An Active member must NOT appear in the suspended list.
        result = get_suspension_list()
        self.assertTrue(result["success"], msg=result)
        names = [m["name"] for m in result["data"]["data"]]
        self.assertNotIn(self.member.name, names)

    def test_get_suspension_list_pagination_clamps_limit(self):
        # limit above 1000 is clamped; negative offset is normalized to 0.
        result = get_suspension_list(limit=5000, offset=-10)
        self.assertTrue(result["success"], msg=result)
        data = result["data"]
        self.assertEqual(data["limit"], 1000)
        self.assertEqual(data["offset"], 0)

    def test_get_suspension_list_chapter_filter(self):
        # Filtering by a chapter no suspended member belongs to yields nothing.
        result = get_suspension_list(chapter="Chapter-That-Does-Not-Exist-ZZZ")
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"]["total"], 0)
        self.assertEqual(result["data"]["data"], [])

    # ------------------------------------------------------------------
    # get_suspension_status_safe
    # ------------------------------------------------------------------
    def test_status_safe_guest_blocked_by_security_ladder(self):
        # FLAG (prod): get_suspension_status_safe has an internal NOT_AUTHENTICATED
        # branch for guests, but @standard_api(MEMBER_DATA) requires MEDIUM and
        # rejects an unauthenticated caller BEFORE the body runs -> that graceful
        # branch is unreachable (dead). This characterizes the actual behavior: the
        # security ladder raises rather than returning NOT_AUTHENTICATED.
        from verenigingen.utils.error_handling import PermissionError as VPermissionError

        with self.set_user("Guest"):
            with self.assertRaises(VPermissionError):
                get_suspension_status_safe()

    def test_status_safe_admin_access_other_member(self):
        # Administrator (default test user) gets admin access to any member.
        result = get_suspension_status_safe(self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"]["access_type"], "admin_access")
        self.assertEqual(result["data"]["member_status"], "Active")

    def test_status_safe_own_record(self):
        # A non-admin user linked to the member reads its own record.
        user_email = f"safe.own.{self.member.name}@example.com".lower()
        if not frappe.db.exists("User", user_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": user_email,
                    "first_name": "Safe",
                    "last_name": "Own",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()
        frappe.db.set_value("Member", self.member.name, "user", user_email)
        frappe.db.commit()
        self._grant_medium_profile(user_email)

        with self.set_user(user_email):
            result = get_suspension_status_safe(self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"]["access_type"], "own_record")

    def test_status_safe_other_member_denied_for_non_admin(self):
        # A non-admin user querying a DIFFERENT member's status is denied.
        other_member = self.create_test_member(
            first_name="SuspExt", last_name="Other", status="Active"
        )
        user_email = f"safe.nonadmin.{self.member.name}@example.com".lower()
        if not frappe.db.exists("User", user_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": user_email,
                    "first_name": "Safe",
                    "last_name": "NonAdmin",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()
        frappe.db.set_value("Member", self.member.name, "user", user_email)
        frappe.db.commit()
        self._grant_medium_profile(user_email)

        with self.set_user(user_email):
            result = get_suspension_status_safe(other_member.name)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")

    def test_status_safe_no_member_record_for_user(self):
        # An authenticated user with no linked Member record gets NO_MEMBER_RECORD.
        user_email = "safe.nomember@example.com"
        if not frappe.db.exists("User", user_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": user_email,
                    "first_name": "Safe",
                    "last_name": "NoMember",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()
        self._grant_medium_profile(user_email)

        with self.set_user(user_email):
            result = get_suspension_status_safe()
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "NO_MEMBER_RECORD")

    # ------------------------------------------------------------------
    # can_suspend_member (no member_name + with member_name)
    # ------------------------------------------------------------------
    def test_can_suspend_member_no_member_name_admin(self):
        # Administrator holds an admin role -> general permission is True.
        result = can_suspend_member()
        self.assertTrue(result["success"], msg=result)
        self.assertTrue(result["data"]["can_suspend"])

    def test_can_suspend_member_no_member_name_regular_user(self):
        user_email = "cansuspend.regular@example.com"
        if not frappe.db.exists("User", user_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": user_email,
                    "first_name": "Can",
                    "last_name": "Regular",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()

        with self.set_user(user_email):
            result = can_suspend_member()
        self.assertTrue(result["success"], msg=result)
        self.assertFalse(result["data"]["can_suspend"])

    def test_can_suspend_member_with_member_name_admin(self):
        result = can_suspend_member(self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertTrue(result["data"]["can_suspend"])
        self.assertEqual(result["data"]["member_name"], self.member.name)

    # ------------------------------------------------------------------
    # _can_suspend_member_fallback (direct unit coverage)
    # ------------------------------------------------------------------
    def test_fallback_admin_true(self):
        # Administrator has System Manager -> fallback returns True.
        self.assertTrue(_can_suspend_member_fallback(self.member.name))

    def test_fallback_no_requesting_member_false(self):
        # A non-admin user with no linked Member record cannot suspend.
        user_email = "fallback.nomember@example.com"
        if not frappe.db.exists("User", user_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": user_email,
                    "first_name": "Fallback",
                    "last_name": "NoMember",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()

        with self.set_user(user_email):
            self.assertFalse(_can_suspend_member_fallback(self.member.name))

    def test_fallback_nonexistent_member_false(self):
        # Non-admin requesting fallback on a nonexistent member returns False.
        user_email = "fallback.regular@example.com"
        if not frappe.db.exists("User", user_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": user_email,
                    "first_name": "Fallback",
                    "last_name": "Regular",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()

        with self.set_user(user_email):
            self.assertFalse(_can_suspend_member_fallback("MEMBER-DOES-NOT-EXIST-ZZZ"))

    # ------------------------------------------------------------------
    # test_bank_details_debug
    # ------------------------------------------------------------------
    def test_bank_details_debug_returns_session_info(self):
        result = test_bank_details_debug()
        self.assertTrue(result["success"], msg=result)
        data = result["data"]
        self.assertEqual(data["status"], "working_from_api_file")
        self.assertEqual(data["user"], frappe.session.user)
        self.assertIn("form_data", data)
