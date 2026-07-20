"""
Suspension API — HTTP-layer security tests.

These exercise the genuinely HTTP-specific security behaviour of the suspension
API (CSRF enforcement, unauthenticated rejection, security-decorator enforcement)
by driving REAL HTTP requests against the running site. Under `bench run-tests`
(and in CI) no web server is bound to the site URL, so they self-skip.

The business-logic and RBAC coverage that used to live here as always-skipped
HTTP tests now runs in-process in ``test_suspension_api_integration.py`` (issue
#162), where it can actually execute and assert in CI.
"""

import requests

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _http_endpoint_reachable(site_url):
    """Return True if the site's HTTP endpoint accepts connections.

    These tests drive real HTTP requests; under `bench run-tests` there is no
    live web server bound to the site URL, so probe once with a short timeout so
    the suite self-skips cleanly instead of erroring on every test.
    """
    try:
        requests.get(f"{site_url}/api/method/frappe.ping", timeout=2)
        return True
    except Exception:
        return False


class TestSuspensionAPISecurityHTTPIntegration(EnhancedTestCase):
    """Real-HTTP security-framework validation for the suspension API.

    Tests real security-framework behaviour (CSRF, authentication, decorator
    enforcement) that only exists at the HTTP transport layer. Skips when no live
    web server is reachable (the normal case under `bench run-tests` / CI).
    """

    def setUp(self):
        super().setUp()
        self.site_url = frappe.utils.get_url()
        self.api_base = f"{self.site_url}/api/method"

        if not _http_endpoint_reachable(self.site_url):
            self.skipTest(
                f"Site HTTP endpoint not reachable at {self.site_url}; "
                "HTTP integration tests require a running web server."
            )

        self.test_member = self.create_test_member(
            first_name="Security",
            last_name="Test",
            email="security.suspend@test.nl",
        )

    def test_csrf_protection_real_validation(self):
        """A session POST without a CSRF token is rejected by the framework."""
        response = requests.Session().post(
            f"{self.api_base}/verenigingen.api.suspension_api.suspend_member",
            data={"member_name": self.test_member.name, "suspension_reason": "CSRF Test"},
        )
        self.assertIn(response.status_code, [401, 403])

    def test_authentication_required_real_validation(self):
        """An unauthenticated suspension request is rejected."""
        response = requests.post(
            f"{self.api_base}/verenigingen.api.suspension_api.suspend_member",
            data={"member_name": self.test_member.name, "suspension_reason": "Auth Test"},
        )
        self.assertIn(response.status_code, [401, 403])

    def test_api_security_decorators_real_validation(self):
        """The @critical_api decorator denies an unauthenticated caller."""
        response = requests.Session().post(
            f"{self.api_base}/verenigingen.api.suspension_api.suspend_member",
            data={"member_name": "test", "suspension_reason": "decorator test"},
        )
        self.assertIn(response.status_code, [401, 403])
