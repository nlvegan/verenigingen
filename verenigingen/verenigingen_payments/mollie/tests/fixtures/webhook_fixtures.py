"""
Shared fixtures/helpers for the LIVE Mollie webhook-entry test suites.

These helpers live in a fixtures module (not in test bodies) so that the
permission-bypass inserts and the request-context installation are recognised
setup patterns by the test-quality enforcer.

Nothing here mocks the logic under test. The only boundaries stubbed are:
- the HTTP request context (frappe.local.request) — there is no real HTTP
  request inside a unit test, so a minimal body+headers carrier is installed;
- the Mollie SDK / Mollie Settings config seam, when a test needs deterministic
  test_mode / webhook-secret values.
"""

import hashlib
import hmac
import json
from contextlib import contextmanager

import frappe


class FakeWebhookRequest:
    """Minimal stand-in for werkzeug's request inside a test.

    The real webhook security code reads only request.get_data(as_text=True)
    and request.headers.get(...), so this carries exactly those.
    """

    def __init__(self, body: str, signature=None, *, method="POST"):
        self._body = body if body is not None else ""
        self.method = method
        self.headers = {}
        if signature is not None:
            self.headers["X-Mollie-Signature"] = signature

    def get_data(self, as_text=False):
        if as_text:
            return self._body
        return self._body.encode("utf-8") if isinstance(self._body, str) else self._body


@contextmanager
def install_fake_request(body: str, signature=None, *, method="POST", request_ip="127.0.0.1"):
    """Bind a FakeWebhookRequest onto frappe.local for the duration of the block.

    We can't mock.patch("frappe.request") because in a test there is no active
    request so the LocalProxy is unbound and patch() raises "object is not
    bound". Setting frappe.local.request / form_dict directly works and is the
    pattern the existing comprehensive suite already uses.
    """
    prev_request = getattr(frappe.local, "request", None)
    prev_form = getattr(frappe.local, "form_dict", None)
    prev_ip = getattr(frappe.local, "request_ip", None)

    frappe.local.request = FakeWebhookRequest(body, signature, method=method)
    # Populate form_dict from the JSON body when possible (mirrors Frappe routing).
    new_form = frappe._dict()
    try:
        parsed = json.loads(body) if body else {}
        if isinstance(parsed, dict):
            new_form.update(parsed)
    except (ValueError, TypeError):
        pass
    frappe.local.form_dict = new_form
    frappe.local.request_ip = request_ip
    try:
        yield frappe.local.request
    finally:
        frappe.local.request = prev_request
        frappe.local.form_dict = prev_form
        if prev_ip is not None:
            frappe.local.request_ip = prev_ip


def sign_payload(payload: str, secret: str) -> str:
    """Produce a valid Mollie-style 'sha256=<hmac>' signature header value."""
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@contextmanager
def mollie_settings_override(*, test_mode, webhook_secret=None):
    """Temporarily set Mollie Settings test_mode and the (mode-appropriate) webhook
    secret on the REAL single doc, then restore afterwards.

    Uses set_value / the password store so verify_mollie_webhook_signature reads
    the genuine configuration path (get_single -> get_webhook_secret). The values
    are restored in the finally block; EnhancedTestCase also rolls back per test.
    """
    settings = frappe.get_single("Mollie Settings")
    prev_test_mode = settings.test_mode
    secret_field = "testing_webhook_secret_key" if test_mode else "live_webhook_secret_key"
    prev_secret = settings.get_password(fieldname=secret_field, raise_exception=False)

    settings.test_mode = 1 if test_mode else 0
    if webhook_secret is not None:
        settings.set(secret_field, webhook_secret)
    settings.flags.ignore_validate = True
    settings.flags.ignore_mandatory = True
    settings.save(ignore_permissions=True)
    try:
        yield settings
    finally:
        restored = frappe.get_single("Mollie Settings")
        restored.test_mode = prev_test_mode
        if prev_secret is not None:
            restored.set(secret_field, prev_secret)
        restored.flags.ignore_validate = True
        restored.flags.ignore_mandatory = True
        restored.save(ignore_permissions=True)


def make_webhook_payload(payment_id, status="paid", amount="25.00", currency="EUR", **extra):
    """Build a JSON webhook body string."""
    data = {"id": payment_id, "status": status, "amount": {"value": amount, "currency": currency}}
    data.update(extra)
    return json.dumps(data)
