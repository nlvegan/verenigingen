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
    def test_status_safe_guest_gets_graceful_not_authenticated(self):
        # The endpoint is @public_api so a guest reaches the body, where the
        # access-control logic returns a graceful NOT_AUTHENTICATED response
        # (no raise) and -- critically -- NO member data.
        with self.set_user("Guest"):
            result = get_suspension_status_safe()
        self.assertFalse(result["success"], msg=result)
        self.assertEqual(result["error"]["code"], "NOT_AUTHENTICATED")
        # No suspension status leaked to an unauthenticated caller.
        self.assertNotIn("is_suspended", result.get("data", {}))
        self.assertNotIn("member_status", result.get("data", {}))

    def test_status_safe_guest_with_explicit_member_name_no_leak(self):
        # Adversarial: a guest passing an explicit member_name skips the
        # member_name=None resolution and lands on the ownership check. The
        # session user "Guest" never equals a member's linked user, and Guest
        # holds no admin role, so the response must be PERMISSION_DENIED with
        # NO suspension status of the queried member leaked.
        with self.set_user("Guest"):
            result = get_suspension_status_safe(self.member.name)
        self.assertFalse(result["success"], msg=result)
        self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")
        denied_data = result.get("data", {})
        self.assertNotIn("is_suspended", denied_data)
        self.assertNotIn("member_status", denied_data)
        self.assertNotIn("access_type", denied_data)
        # Belt-and-suspenders: the queried member's status must not appear
        # anywhere in the serialized response (message or any top-level key).
        self.assertNotIn("Suspended", str(result))

    def test_status_safe_admin_access_other_member(self):
        # Administrator (default test user) gets admin access to any member.
        result = get_suspension_status_safe(self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"]["access_type"], "admin_access")
        self.assertEqual(result["data"]["member_status"], "Active")

    def test_status_safe_own_record(self):
        # An ORDINARY member ("Verenigingen Member", LOW tier) linked to the member
        # reads its OWN record through the lowered @public_api gate -- no MEDIUM
        # role-profile grant needed; ownership is enforced in-band.
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

        with self.set_user(user_email):
            result = get_suspension_status_safe(self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"]["access_type"], "own_record")
        # Own status is returned (this is the member's OWN record).
        self.assertEqual(result["data"]["member_status"], "Active")

    def test_status_safe_other_member_denied_for_non_admin(self):
        # An ORDINARY member querying a DIFFERENT member's status is denied with
        # NO status data leaked -- the core data-leak guarantee of the lowered gate.
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

        with self.set_user(user_email):
            result = get_suspension_status_safe(other_member.name)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")
        # NO LEAK: the denied response must not carry the queried member's status.
        denied_data = result.get("data", {})
        self.assertNotIn("is_suspended", denied_data)
        self.assertNotIn("member_status", denied_data)
        self.assertNotIn("access_type", denied_data)

    def test_status_safe_no_member_record_for_user(self):
        # An authenticated ORDINARY member with no linked Member record gets
        # NO_MEMBER_RECORD (no MEDIUM grant needed under the lowered gate).
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
