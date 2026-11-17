"""The security framework's response headers reach the wire as HTTP headers, not the JSON body (#2732).

``api_security_framework`` used to write X-Frame-Options, nosniff, Referrer-Policy, the
X-RateLimit-* pair and (HIGH/CRITICAL) X-CSRF-Token into ``frappe.local.response["headers"]``.
Frappe serialises every key of ``frappe.local.response`` into the JSON body; only
``frappe.local.response_headers`` (a werkzeug ``Headers`` built per request in ``frappe.init`` and
applied at ``frappe/app.py`` ``response.headers.update(...)``) reaches the wire. So the "security
headers" were never headers, and the CSRF token sat in the body.

The probe runs in a SUBPROCESS through the real WSGI app (``frappe.app.application`` destroys
``frappe.local`` per request). Shortcuts, stated: (1) the HIGH-security endpoint is a probe
function injected into ``sys.modules`` (no shipped HIGH endpoint is both cheap and free of side
effects) and decorated with the real ``@high_security_api``; (2) a probe user with the
Verenigingen System Administrator role profile (HIGH is profile-only, never a bare role) is
committed, logs in through the real ``/api/method/login`` for a cookie session, and is removed
again. The guest case is the shipped ``validate_postal_code`` endpoint, untouched.
"""

import json
import os
import subprocess
import sys

import frappe
from frappe.utils import get_bench_path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

_PROBE = r"""
import json, sys, types, uuid
import frappe

SITE = sys.argv[1]
EMAIL = "headers-2732-probe@example.com"
PWD = "Pr0be-" + uuid.uuid4().hex
frappe.init(site=SITE)
frappe.connect()
user_created = False
out = {}
try:
    frappe.set_user("Administrator")
    if frappe.db.exists("User", EMAIL):
        frappe.delete_doc("User", EMAIL, force=True, ignore_permissions=True)
    u = frappe.new_doc("User")
    u.email, u.first_name, u.send_welcome_email = EMAIL, "Headers2732", 0
    u.role_profile_name = "Verenigingen System Administrator"
    u.new_password = PWD
    u.insert(ignore_permissions=True)
    user_created = True
    frappe.db.commit()
    frappe.destroy()

    # a real-decorator HIGH endpoint, callable through /api/method
    from verenigingen.utils.security.api_security_framework import high_security_api
    from verenigingen.utils.security.types import OperationType
    mod = types.ModuleType("verenigingen.probe_2732_api")
    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.MEMBER_DATA)
    def high_probe():
        return {"probe_payload": "high-ok"}
    mod.high_probe = high_probe
    sys.modules["verenigingen.probe_2732_api"] = mod

    import frappe.app
    from werkzeug.test import Client
    H = {"X-Frappe-Site-Name": SITE}
    GUEST = "/api/method/verenigingen.api.membership_application.validate_postal_code?postal_code=1011AB"
    PLAIN = "/api/method/ping"

    def shape(r):
        try:
            body = json.loads(r.get_data(as_text=True))
        except ValueError:
            body = {}
        return {"status": r.status_code, "headers": {k: v for k, v in r.headers}, "body": body}

    guest = Client(frappe.app.application, use_cookies=False)
    out["guest_first"] = shape(guest.get(GUEST, headers=H))
    out["plain_after_guest"] = shape(guest.get(PLAIN, headers=H))

    member = Client(frappe.app.application, use_cookies=True)
    login = member.post("/api/method/login", data={"usr": EMAIL, "pwd": PWD}, headers=H)
    out["login_status"] = login.status_code
    out["high"] = shape(member.get("/api/method/verenigingen.probe_2732_api.high_probe", headers=H))
    out["plain_after_high"] = shape(member.get(PLAIN, headers=H))
    print("RESULT" + json.dumps(out))
finally:
    frappe.init(site=SITE)
    frappe.connect()
    if user_created:
        try:
            frappe.delete_doc("User", EMAIL, force=True, ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.db.rollback()
            print("CLEANUP_FAILED User " + str(e))
    print("LEFTOVER" + json.dumps([EMAIL] if frappe.db.exists("User", EMAIL) else []))
    frappe.destroy()
"""

_SECURITY_HEADERS = ("X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy")
_RATE_HEADERS = ("X-RateLimit-Limit", "X-RateLimit-Window")


def _lowercase_keys_2732(mapping):
    return {k.lower(): v for k, v in mapping.items()}


class TestSecurityResponseHeaders2732(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            result = subprocess.run(
                [sys.executable, "-c", _PROBE, frappe.local.site],
                cwd=os.path.join(get_bench_path(), "sites"),
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired as e:
            raise AssertionError(f"the WSGI probe did not finish in 300s; stdout: {e.stdout}") from e
        if result.returncode != 0:
            raise AssertionError(result.stdout + "\n" + result.stderr)
        lines = result.stdout.splitlines()
        cls.out = json.loads(next(x for x in lines if x.startswith("RESULT"))[len("RESULT") :])
        cls.leftover = next(x for x in lines if x.startswith("LEFTOVER"))[len("LEFTOVER") :]

    def test_probe_cleaned_up_after_itself(self):
        self.assertEqual(self.leftover, "[]")

    def test_control_the_probe_logged_in_and_reached_the_decorated_endpoints(self):
        self.assertEqual(self.out["login_status"], 200)
        self.assertEqual(self.out["guest_first"]["status"], 200, self.out["guest_first"])
        self.assertEqual(self.out["high"]["status"], 200, self.out["high"])

    def test_guest_endpoint_sends_security_and_rate_limit_headers_on_the_wire(self):
        wire = _lowercase_keys_2732(self.out["guest_first"]["headers"])
        self.assertEqual(wire.get("x-frame-options"), "DENY")
        self.assertEqual(wire.get("x-content-type-options"), "nosniff")
        self.assertEqual(wire.get("referrer-policy"), "strict-origin-when-cross-origin")
        self.assertIn("x-ratelimit-limit", wire)
        self.assertIn("x-ratelimit-window", wire)

    def test_guest_endpoint_body_has_no_headers_key(self):
        self.assertNotIn("headers", self.out["guest_first"]["body"])

    def test_control_guest_endpoint_body_still_carries_its_payload(self):
        body = self.out["guest_first"]["body"]
        self.assertIn("message", body)
        self.assertIsInstance(body["message"], dict)
        self.assertIn("valid", json.dumps(body["message"]).lower())

    def test_high_security_endpoint_sends_headers_and_csrf_token_on_the_wire(self):
        wire = _lowercase_keys_2732(self.out["high"]["headers"])
        self.assertEqual(wire.get("x-frame-options"), "DENY")
        self.assertEqual(wire.get("x-content-type-options"), "nosniff")
        token = wire.get("x-csrf-token")
        self.assertTrue(token and len(token) >= 16, wire)

    def test_high_security_endpoint_body_has_no_headers_key_and_no_csrf_token(self):
        body = self.out["high"]["body"]
        self.assertNotIn("headers", body)
        self.assertNotIn("x-csrf-token", json.dumps(body).lower())

    def test_control_high_security_endpoint_body_still_carries_its_payload(self):
        self.assertEqual(self.out["high"]["body"].get("message"), {"probe_payload": "high-ok"})

    def test_a_header_set_by_one_request_does_not_leak_into_the_next_in_process(self):
        # Same process, same werkzeug app, the very next request: an undecorated endpoint.
        for key in ("plain_after_guest", "plain_after_high"):
            wire = _lowercase_keys_2732(self.out[key]["headers"])
            self.assertEqual(self.out[key]["status"], 200, self.out[key])
            for name in ("x-ratelimit-limit", "x-ratelimit-window", "x-csrf-token"):
                self.assertNotIn(name, wire, f"{name} leaked into {key}")
            self.assertNotEqual(wire.get("x-frame-options"), "DENY", f"X-Frame-Options leaked into {key}")
