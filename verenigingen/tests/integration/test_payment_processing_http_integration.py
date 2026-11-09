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

Why a subprocess: ``frappe.app.application`` calls ``frappe.destroy()`` per request, which would
pull the running test's ``frappe.local`` (and its DB transaction) out from under it. The request
runs in a child process with its own ``frappe.local``; it inherits this process's PYTHONPATH, so
it exercises whichever verenigingen is importable. The user and its password are committed
first because the child is a separate DB connection (and the commit is removed again in
``tearDown``).

Only outbound mail is stubbed (``frappe.sendmail``, inside the child), so no reminder can leave
the site; everything else is real. The security cases do not depend on the site's overdue data.

Usage:
    bench --site test_site_5 run-tests --app verenigingen \
        --module verenigingen.tests.integration.test_payment_processing_http_integration
"""

import json
import os
import subprocess
import sys
import textwrap

import frappe
from frappe.utils import get_bench_path
from frappe.utils.password import update_password

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.harness_logger import get_harness_logger

ENDPOINT = "/api/method/verenigingen.api.payment_processing.send_overdue_payment_reminders"

# Runs in the child. Each case is {"name", "login": None | {"usr", "pwd"}, "csrf": False | "valid" | "wrong"
# | "missing", "json": dict}. False never loads the desk, so the session has no token yet.
_CHILD = textwrap.dedent(
    r"""
    import json, re, sys, time
    from unittest.mock import patch

    import frappe

    site, endpoint, cases = {site!r}, {endpoint!r}, json.loads({cases!r})
    frappe.init(site=site)
    frappe.connect()
    frappe.destroy()

    import frappe.app
    from werkzeug.test import Client

    out = {{}}
    # Mock justified: External Service - outbound SMTP, not business logic
    with patch("frappe.sendmail"):
        for case in cases:
            client = Client(frappe.app.application)  # keeps the session cookie
            headers = {{"X-Frappe-Site-Name": site}}
            if case["login"]:
                login = client.post("/api/method/login", data=case["login"], headers=headers)
                assert login.status_code == 200, login.get_data(as_text=True)
                if case["csrf"]:
                    # Loading the desk page is where a browser's session gets its token
                    # (frappe.csrf_token = "..."); Frappe only enforces CSRF once one exists.
                    desk = client.get("/desk", headers=headers)
                    token = re.search(r'frappe\.csrf_token = "([^"]+)"', desk.get_data(as_text=True)).group(1)
                    if case["csrf"] == "valid":
                        headers["X-Frappe-CSRF-Token"] = token
                    elif case["csrf"] == "wrong":
                        headers["X-Frappe-CSRF-Token"] = "not-" + token
            started = time.time()
            response = client.post(endpoint, json=case["json"], headers=headers)
            out[case["name"]] = {{
                "status": response.status_code,
                "body": response.get_data(as_text=True),
                "ms": (time.time() - started) * 1000,
            }}
    print("RESULT" + json.dumps(out))
    """
)


class TestPaymentProcessingHTTPIntegration(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.password = f"Probe-{frappe.generate_hash()[:12]}!"
        self.addCleanup(self._cleanup_committed_users)
        self._create_login_users()

    def _create_login_users(self):
        # @critical_api grants CRITICAL only through a vetted Role Profile (a bare role is not
        # enough); the Administrator profile also carries the roles the endpoint's own check wants.
        self.finance_user = self._make_committed_login_user("finance", "Verenigingen Administrator")
        # Each refusal layer needs a caller that clears the OTHER layer, or a mutant disabling
        # one layer stays green behind the other. Framework layer: has the roles the endpoint
        # wants but a profile that tops out below CRITICAL.
        self.low_profile_user = self._make_committed_login_user(
            "lowprofile", "Verenigingen Member", extra_roles=["Accounts Manager"]
        )
        # Endpoint layer: a CRITICAL profile (clears the framework) without any financial role.
        self.board_user = self._make_committed_login_user("board", "Verenigingen National Board Member")
        # Load-bearing: the request runs on another DB connection, which sees none of these
        # rows until they are committed. Removed again by _cleanup_committed_users.
        frappe.db.commit()

    def _make_committed_login_user(self, label, role_profile, extra_roles=()):
        email = f"http-int-{label}-{frappe.generate_hash()[:8]}@test.invalid"
        user = frappe.get_doc(
            {"doctype": "User", "email": email, "first_name": "HTTP", "send_welcome_email": 0}
        )
        user.append("role_profiles", {"role_profile": role_profile})
        user.insert(ignore_permissions=True)
        for role in extra_roles:  # direct roles, added after the profile sync would strip them
            frappe.get_doc(
                {
                    "doctype": "Has Role",
                    "parent": email,
                    "parenttype": "User",
                    "parentfield": "roles",
                    "role": role,
                }
            ).insert(ignore_permissions=True)
        update_password(email, self.password)
        return email

    def _cleanup_committed_users(self):
        frappe.db.rollback()
        created = ("finance_user", "low_profile_user", "board_user")
        failures = []
        for email in filter(None, (getattr(self, name, None) for name in created)):
            try:
                frappe.delete_doc("User", email, force=True, ignore_permissions=True)
                # The logins in the child process leave rows delete_doc does not remove.
                frappe.db.delete("Activity Log", {"user": email})
                frappe.db.delete("Sessions", {"user": email})  # doctype-ok: core table tabSessions, no DocType record
            except Exception as exc:
                get_harness_logger("http-integration").warning(f"cleanup of {email} failed: {exc!r}")
                failures.append(exc)
                frappe.db.rollback()
        frappe.db.commit()
        if failures:
            raise failures[0]

    def _login(self, user):
        return {"usr": user, "pwd": self.password}

    def _run_wsgi_cases(self, *cases):
        """Run the cases through the WSGI app in a child process; return {name: response}."""
        script = _CHILD.format(site=frappe.local.site, endpoint=ENDPOINT, cases=json.dumps(list(cases)))
        result = subprocess.run(
            [sys.executable, "-W", "ignore", "-c", script],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        line = next(x for x in result.stdout.splitlines() if x.startswith("RESULT"))
        return json.loads(line[len("RESULT") :])

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
        message = json.loads(out["body"])["message"]
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
        for name in ("missing_csrf", "wrong_csrf"):
            self.assertIn("CSRFTokenError", out[name]["body"], out[name]["body"][:300])
            self.assertNotEqual(out[name]["status"], 200, name)
        # Control: the same finance user with a token is let through, so the refusals above are
        # about the missing token / role, not about this user or the payload.
        self.assertEqual(out["control_authorised"]["status"], 200, out["control_authorised"]["body"][:300])

    def test_performance_monitoring_through_http(self):
        """An authorised request through @performance_monitor completes in reasonable time."""
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
