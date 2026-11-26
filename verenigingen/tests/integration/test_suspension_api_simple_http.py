"""
Suspension API: simple HTTP-stack integration tests (#2370)
===========================================================

These drive the suspension endpoints through the real WSGI app (see
``verenigingen.tests.support.wsgi_http_session``): the whitelist dispatch, a real login, and the
``@critical_api`` / ``@utility_api`` / ``@public_api`` security tiers all run.

They used to send ``requests`` to ``frappe.utils.get_url()`` and skipped whenever no live web
server answered, so they never ran in CI. Their assertions were also vacuous: each only printed a
tick when the status was one of 200/401/403, so a refusal and a success were both "success" and
nothing could fail. Each test now pins the specific outcome per caller, and an authorised control
shows the endpoint body really ran.

No Member is created: an unknown member name is enough to tell "the body ran" from "refused", and it
keeps the committed footprint to the login users, which are removed again afterwards.
"""

import json

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.wsgi_http_session import (
    CommittedLoginUsersMixin,
    api_path,
    operation_result,
    run_wsgi_cases,
)

SUSPENSION_API = "verenigingen.api.suspension_api."
UNKNOWN_MEMBER = "HTTP-SUSPENSION-NO-SUCH-MEMBER"


class TestSuspensionAPISimpleHTTP(CommittedLoginUsersMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # @critical_api grants CRITICAL only through a vetted Role Profile, so the admin and the
        # board user both clear the framework; only the endpoint's own check tells them apart.
        # The member profile tops out below CRITICAL and has no admin role.
        users = self._create_login_users(
            admin="Verenigingen Administrator",
            board="Verenigingen National Board Member",
            member="Verenigingen Member",
        )
        self.admin_user, self.board_user, self.member_user = users["admin"], users["board"], users["member"]

    def _suspension_case(self, name, endpoint, payload, user=None):
        return {
            "name": name,
            "endpoint": api_path(SUSPENSION_API + endpoint),
            "login": {"usr": user, "pwd": self.password} if user else None,
            "csrf": "valid" if user else False,
            "json": payload,
        }

    def test_suspension_api_security_validation_http(self):
        """suspend_member refuses a guest at dispatch, a low profile at the framework, a non-admin at the endpoint."""
        # The endpoint logs both its refusal and its unknown-member answer; they are the behaviour here.
        self.expectErrorLog("Suspension API Permission Error", "Suspension API Validation Error")
        payload = {"member_name": UNKNOWN_MEMBER, "suspension_reason": "HTTP Security Test"}
        out = run_wsgi_cases(
            self._suspension_case("guest", "suspend_member", payload),
            self._suspension_case("member", "suspend_member", payload, self.member_user),
            self._suspension_case("board", "suspend_member", payload, self.board_user),
            self._suspension_case("admin", "suspend_member", payload, self.admin_user),
        )

        self.assertEqual(out["guest"]["status"], 403, out["guest"]["body"][:300])
        self.assertIn("PermissionError", out["guest"]["body"])
        # A profile below CRITICAL is refused by the framework tier before the body runs.
        self.assertEqual(out["member"]["status"], 403, out["member"]["body"][:300])
        self.assertIn("Access denied", out["member"]["body"])
        # The board user clears the framework tier, so this refusal is the endpoint's own check.
        self.assertEqual(out["board"]["status"], 200, out["board"]["body"][:300])
        board = operation_result(out["board"])
        self.assertFalse(board["success"], board)
        self.assertEqual(board["error"]["code"], "PERMISSION_DENIED")
        # Control: the admin gets past both layers and the body runs (unknown member, so nothing is
        # suspended), which is what makes the two refusals above about the caller.
        admin = operation_result(out["admin"])
        self.assertEqual(admin["error"]["code"], "DOES_NOT_EXIST", admin)

    def test_suspension_status_api_http_access(self):
        """get_suspension_status_safe serves a guest only a login prompt, never another member's status."""
        out = run_wsgi_cases(
            self._suspension_case("guest_self", "get_suspension_status_safe", {}),
            self._suspension_case("guest_other", "get_suspension_status_safe", {"member_name": UNKNOWN_MEMBER}),
            self._suspension_case(
                "member_other", "get_suspension_status_safe", {"member_name": UNKNOWN_MEMBER}, self.member_user
            ),
            self._suspension_case(
                "admin_other", "get_suspension_status_safe", {"member_name": UNKNOWN_MEMBER}, self.admin_user
            ),
        )

        for name in out:
            self.assertEqual(out[name]["status"], 200, out[name]["body"][:300])
        self.assertEqual(operation_result(out["guest_self"])["error"]["code"], "NOT_AUTHENTICATED")
        for name in ("guest_other", "member_other"):
            result = operation_result(out[name])
            self.assertFalse(result["success"], result)
            self.assertEqual(result["error"]["code"], "PERMISSION_DENIED", result)
            self.assertNotIn("is_suspended", json.dumps(result), name)
        # Control: an admin may look at any member, so the denials above are about the caller.
        admin = operation_result(out["admin_other"])
        self.assertTrue(admin["success"], admin)
        self.assertEqual(admin["data"]["access_type"], "admin_access")

    def test_can_suspend_member_api_http(self):
        """can_suspend_member needs a login and answers per role: an admin may suspend, a member may not."""
        out = run_wsgi_cases(
            self._suspension_case("guest", "can_suspend_member", {}),
            self._suspension_case("member", "can_suspend_member", {}, self.member_user),
            self._suspension_case("admin", "can_suspend_member", {}, self.admin_user),
        )

        self.assertEqual(out["guest"]["status"], 403, out["guest"]["body"][:300])
        member = operation_result(out["member"])
        self.assertTrue(member["success"], member)
        self.assertIs(member["data"]["can_suspend"], False)
        self.assertIs(operation_result(out["admin"])["data"]["can_suspend"], True)
