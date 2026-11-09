"""
Suspension API: HTTP-layer security tests (#2370)
=================================================

These exercise the security behaviour that only exists at the HTTP transport layer (CSRF
enforcement, guest refusal, security-tier enforcement) by driving ``suspend_member`` through the
real WSGI app (``verenigingen.tests.support.wsgi_http_session``).

They used to send ``requests`` to the site URL and self-skipped when no web server answered, which
is always the case under ``bench run-tests`` and in CI. The business-logic and RBAC coverage lives
in-process in ``test_suspension_api_integration.py`` (issue #162).

Two premises of the old tests were false, and nothing ever checked them because they never ran:

* ``test_csrf_protection_real_validation`` posted with a bare ``requests.Session()``, i.e. as a
  guest, and expected 401/403. That is the guest refusal, not CSRF. A real CSRF failure is HTTP
  400 ``CSRFTokenError``, and only for a logged-in session that has loaded a page (#2367).
* ``test_api_security_decorators_real_validation`` also posted as a guest, which Frappe refuses at
  whitelist dispatch ("not whitelisted" for guests), so ``@critical_api`` never ran. The decorator
  is now exercised by a logged-in user whose profile tops out below CRITICAL.
"""

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.wsgi_http_session import (
    CommittedLoginUsersMixin,
    api_path,
    operation_result,
    run_wsgi_cases,
)

SUSPEND_MEMBER = api_path("verenigingen.api.suspension_api.suspend_member")
# Unknown on purpose: an admin who gets past every layer is answered DOES_NOT_EXIST and nothing
# is suspended, so the control never changes data.
PAYLOAD = {"member_name": "HTTP-SUSPENSION-NO-SUCH-MEMBER", "suspension_reason": "HTTP security test"}


class TestSuspensionAPISecurityHTTPIntegration(CommittedLoginUsersMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # A CRITICAL profile, and one that tops out below CRITICAL (the framework tier must refuse it).
        users = self._create_login_users(
            admin="Verenigingen Administrator", member="Verenigingen Member"
        )
        self.admin_user, self.member_user = users["admin"], users["member"]

    def _suspend_case(self, name, user=None, csrf="valid"):
        return {
            "name": name,
            "endpoint": SUSPEND_MEMBER,
            "login": {"usr": user, "pwd": self.password} if user else None,
            "csrf": csrf if user else False,
            "json": PAYLOAD,
        }

    def test_csrf_protection_real_validation(self):
        """A logged-in POST with a missing or wrong CSRF token is refused; the same user with the token is not."""
        out = run_wsgi_cases(
            self._suspend_case("missing", self.admin_user, csrf="missing"),
            self._suspend_case("wrong", self.admin_user, csrf="wrong"),
            self._suspend_case("valid", self.admin_user, csrf="valid"),
        )

        for name in ("missing", "wrong"):
            self.assertEqual(out[name]["status"], 400, out[name]["body"][:300])
            self.assertIn("CSRFTokenError", out[name]["body"], name)
        # Control: with a valid token the endpoint body runs, so the refusals are about the token.
        self.assertEqual(out["valid"]["status"], 200, out["valid"]["body"][:300])
        self.assertEqual(operation_result(out["valid"])["error"]["code"], "DOES_NOT_EXIST")

    def test_authentication_required_real_validation(self):
        """An unauthenticated suspension request is refused at dispatch (403 PermissionError)."""
        out = run_wsgi_cases(self._suspend_case("guest"))["guest"]

        self.assertEqual(out["status"], 403, out["body"][:300])
        self.assertIn("PermissionError", out["body"])
        self.assertNotIn("DOES_NOT_EXIST", out["body"])

    def test_api_security_decorators_real_validation(self):
        """@critical_api refuses a logged-in caller whose role profile is below CRITICAL."""
        out = run_wsgi_cases(
            self._suspend_case("member", self.member_user),
            self._suspend_case("admin", self.admin_user),
        )

        self.assertEqual(out["member"]["status"], 403, out["member"]["body"][:300])
        # The framework's generic refusal, raised before the endpoint body ran.
        self.assertIn("Access denied", out["member"]["body"])
        self.assertNotIn("DOES_NOT_EXIST", out["member"]["body"])
        # Control: a CRITICAL profile gets through to the body.
        self.assertEqual(operation_result(out["admin"])["error"]["code"], "DOES_NOT_EXIST")
