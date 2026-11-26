"""
Payment Processing API: HTTP stack integration tests (#2364)
============================================================

These drive ``send_overdue_payment_reminders`` through the real WSGI app
(``werkzeug.test.Client(frappe.app.application)``): the whitelist dispatch, the session
cookie from a real ``POST /api/method/login``, Frappe's native CSRF check, the
``@critical_api`` security framework and the endpoint's own role check all run.

They used to send ``requests`` to ``frappe.utils.get_url()`` and skipped whenever no live web
server answered. A CI runner never has one, so all four tests always skipped and nothing here
was ever checked.

The WSGI child process, the committed login users and their cleanup live in
``verenigingen.tests.support.wsgi_http_session`` (shared with the suspension API tests, #2371).

Only outbound mail is stubbed (``frappe.sendmail``, inside the child), so no reminder can leave
the site; everything else is real. The security cases do not depend on the site's overdue data.

Usage:
    bench --site test_site_5 run-tests --app verenigingen \
        --module verenigingen.tests.integration.test_payment_processing_http_integration
"""

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.wsgi_http_session import (
    CommittedLoginUsersMixin,
    api_path,
    operation_result,
    run_wsgi_cases,
)

ENDPOINT = api_path("verenigingen.api.payment_processing.send_overdue_payment_reminders")
# Mock justified: External Service - outbound SMTP, not business logic
OUTBOUND_MAIL_STUBS = ("frappe.sendmail",)


class TestPaymentProcessingHTTPIntegration(CommittedLoginUsersMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # @critical_api grants CRITICAL only through a vetted Role Profile (a bare role is not
        # enough); the Administrator profile also carries the roles the endpoint's own check wants.
        # Each refusal layer needs a caller that clears the OTHER layer, or a mutant disabling
        # one layer stays green behind the other. Framework layer ("low_profile"): has the roles the
        # endpoint wants but a profile that tops out below CRITICAL. Endpoint layer ("board"): a
        # CRITICAL profile (clears the framework) without any financial role.
        users = self._create_login_users(
            finance="Verenigingen Administrator",
            low_profile=("Verenigingen Member", ["Accounts Manager"]),
            board="Verenigingen National Board Member",
            # Clears the framework (CRITICAL profile) and Sales Invoice/Member read, so ONLY the
            # endpoint's role check refuses it. The has_permission layer cannot be pinned
            # independently by role (every role passing the role check also reads Sales Invoice;
            # Member read is held by every CRITICAL profile): only a User Permission fixture could.
            role_check_only=("Verenigingen National Board Member", ["Accounts User"]),
        )
        self.finance_user = users["finance"]
        self.low_profile_user = users["low_profile"]
        self.board_user = users["board"]
        self.role_check_only_user = users["role_check_only"]

    def _login(self, user):
        return {"usr": user, "pwd": self.password}

    def _run_wsgi_cases(self, *cases):
        """Run the cases against the reminder endpoint, outbound mail stubbed in the child."""
        return run_wsgi_cases(*({"endpoint": ENDPOINT, **case} for case in cases), patches=OUTBOUND_MAIL_STUBS)

    def test_send_payment_reminders_http_integration(self):
        """An authorised finance user, with a CSRF token, runs the real reminder workflow."""
        out = self._run_wsgi_cases(
            {
                "name": "run",
                "login": self._login(self.finance_user),
                "csrf": "valid",
                "json": {
                    "reminder_type": "HTTP Integration Test",
                    "include_payment_link": True,
                    "custom_message": "This is a real HTTP integration test",
                },
            }
        )["run"]

        self.assertEqual(out["status"], 200, out["body"][:300])
        message = operation_result(out)
        self.assertIsInstance(message, dict, out["body"][:300])
        self.assertIn("count", message, out["body"][:300])

    def test_api_security_through_http(self):
        """Unauthenticated, under-privileged and CSRF-less callers are all refused."""
        out = self._run_wsgi_cases(
            {"name": "guest", "login": None, "csrf": False, "json": {"reminder_type": "Security Test"}},
            {
                "name": "low_profile",
                "login": self._login(self.low_profile_user),
                "csrf": "valid",
                "json": {"reminder_type": "Security Test"},
            },
            {
                "name": "no_financial_role",
                "login": self._login(self.board_user),
                "csrf": "valid",
                "json": {"reminder_type": "Security Test"},
            },
            {
                "name": "role_check_only",
                "login": self._login(self.role_check_only_user),
                "csrf": "valid",
                "json": {"reminder_type": "Security Test"},
            },
            {
                "name": "missing_csrf",
                "login": self._login(self.finance_user),
                "csrf": "missing",
                "json": {"reminder_type": "No CSRF Test"},
            },
            {
                "name": "wrong_csrf",
                "login": self._login(self.finance_user),
                "csrf": "wrong",
                "json": {"reminder_type": "Wrong CSRF Test"},
            },
            {
                "name": "control_authorised",
                "login": self._login(self.finance_user),
                "csrf": "valid",
                "json": {"reminder_type": "Security Test"},
            },
        )

        self.assertIn(out["guest"]["status"], [401, 403], out["guest"]["body"][:300])
        self.assertIn(out["low_profile"]["status"], [401, 403], out["low_profile"]["body"][:300])
        # Which layer refused is told by the message: the framework's generic "Access denied"
        # versus the endpoint's own explicit permission message.
        self.assertIn("Access denied", out["low_profile"]["body"])
        self.assertNotIn("Access denied", out["no_financial_role"]["body"])
        self.assertEqual(out["no_financial_role"]["status"], 403, out["no_financial_role"]["body"][:300])
        self.assertIn("permission", out["no_financial_role"]["body"].lower())
        self.assertEqual(out["role_check_only"]["status"], 403, out["role_check_only"]["body"][:300])
        self.assertIn("Required roles", out["role_check_only"]["body"])
        for name in ("missing_csrf", "wrong_csrf"):
            self.assertIn("CSRFTokenError", out[name]["body"], out[name]["body"][:300])
            self.assertNotEqual(out[name]["status"], 200, name)
        # Control: the same finance user with a token is let through, so the refusals above are
        # about the missing token / role, not about this user or the payload.
        self.assertEqual(out["control_authorised"]["status"], 200, out["control_authorised"]["body"][:300])

    def test_performance_monitoring_through_http(self):
        """An authorised request completes within 30s. Only guards against a hang: it does not check that @performance_monitor ran."""
        out = self._run_wsgi_cases(
            {
                "name": "run",
                "login": self._login(self.finance_user),
                "csrf": "valid",
                "json": {"reminder_type": "Performance Test"},
            }
        )["run"]

        self.assertEqual(out["status"], 200, out["body"][:300])
        self.assertLess(out["ms"], 30000, "Request should complete within 30 seconds")
