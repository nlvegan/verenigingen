"""
Every place that records or SENDS the client IP must use the trusted-proxy aware
``get_client_ip()`` (issues #1768, #1769).

Frappe sets ``frappe.local.request_ip`` from the LEFTMOST X-Forwarded-For entry,
which the client chooses, and ``REMOTE_ADDR`` behind nginx is the proxy itself
(127.0.0.1). So a site reading either one records a forged address or a useless one.

Requests here are REAL werkzeug requests; ``request_ip`` is derived by Frappe's own
``HTTPRequest.set_request_ip`` exactly as in production. Topology: a trusted proxy
(127.0.0.1, in the default trusted range) appends the real client to whatever XFF the
client sent. Outbound HTTP is stubbed at ``requests.get`` only (a boundary), and the
value sent is asserted.

Probe shortcuts: Pay.nl's consent IP is asserted on the payload builder's output
(``_build_mandate_payload``), which is the dict ``create_mandate_for_member`` posts;
the full create flow needs live Pay.nl settings. Bank settings are a SimpleNamespace
returned by a patched ``frappe.get_single`` (no Bank Integration Settings row exists on a
test site). Site config here: test_site_7 has developer_mode=1; the assertions do not
depend on it.
"""

import ast
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.auth import HTTPRequest
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.utils.base import VereningingenTestCase

PROXY = "127.0.0.1"
REAL_CLIENT = "203.0.113.77"
SPOOF = "198.51.100.9"


class _RequestCase(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._orig_request = getattr(frappe.local, "request", None)
        self._orig_request_ip = getattr(frappe.local, "request_ip", None)
        self.addCleanup(self._restore)

    def _restore(self):
        frappe.local.request = self._orig_request  # Mock justified: execution-context state, restoring the request the harness had
        frappe.local.request_ip = self._orig_request_ip  # Mock justified: execution-context state

    def _install(self, remote_addr=PROXY, xff=None):
        headers = {"X-Forwarded-For": xff} if xff is not None else {}
        environ = EnvironBuilder(method="POST", path="/x", headers=headers, data=b"{}").get_environ()
        environ["REMOTE_ADDR"] = remote_addr
        frappe.local.request = Request(environ)  # Mock justified: real werkzeug request bound as the execution context
        HTTPRequest.__new__(HTTPRequest).set_request_ip()

    def _install_behind_proxy_with_spoof(self):
        # client sent "SPOOF"; the trusted proxy appended the real address
        self._install(PROXY, f"{SPOOF}, {REAL_CLIENT}")

    def _no_request(self):
        frappe.local.request = None  # Mock justified: models a background job (no request)
        frappe.local.request_ip = None  # Mock justified: same


class TestPayNlConsentIp(_RequestCase):
    def _payload(self):
        from verenigingen.verenigingen_payments.ing_checkout.services.mandate_service import MandateService

        svc = MandateService()
        svc._settings = SimpleNamespace(service_id="SL-TEST")
        mandate = SimpleNamespace(
            name="SM-1", iban="NL91ABNA0417164300", account_holder_name="A", bic=None
        )
        member = SimpleNamespace(full_name="A B", email="a@example.org")
        return svc._build_mandate_payload(mandate, member, "flexible", 10.0)

    def test_spoofed_leftmost_xff_is_not_sent_as_consent_ip(self):
        self._install_behind_proxy_with_spoof()
        self.assertEqual(self._payload()["customer"]["ipAddress"], REAL_CLIENT)

    def test_direct_client_ip_is_recorded_when_there_is_no_proxy(self):
        # not a trusted proxy: a forged XFF must lose to the connecting address
        self._install(REAL_CLIENT, SPOOF)
        self.assertEqual(self._payload()["customer"]["ipAddress"], REAL_CLIENT)

    def test_placeholder_for_background_callers_without_a_request(self):
        self._no_request()
        self.assertEqual(self._payload()["customer"]["ipAddress"], "0.0.0.0")


class TestBankPsuIp(_RequestCase):
    def _sent_headers(self):
        from verenigingen.verenigingen_payments.utils.bank_integration import BankAPIClient

        settings = frappe._dict(
            api_endpoint="https://bank.invalid", account_id="X", access_token="t"
        )
        response = MagicMock(status_code=500)
        with (
            # Mock justified: External Service - the bank HTTP API (requests.get) is the boundary under observation;
            # the two frappe patches only stand in for a Bank Integration Settings row that test sites lack.
            patch("frappe.get_single", return_value=settings),  # Mock justified: no settings row on test sites
            patch("frappe.db.exists", return_value=True),  # Mock justified: same
            patch("requests.get", return_value=response) as get,  # Mock justified: External Service - bank API
        ):
            BankAPIClient().fetch_statements("2026-01-02")
        return get.call_args.kwargs["headers"]

    def test_spoofed_leftmost_xff_is_not_sent_as_psu_ip(self):
        self._install_behind_proxy_with_spoof()
        self.assertEqual(self._sent_headers()["PSU-IP-Address"], REAL_CLIENT)

    def test_direct_client_ip_is_sent_when_there_is_no_proxy(self):
        self._install(REAL_CLIENT, SPOOF)
        self.assertEqual(self._sent_headers()["PSU-IP-Address"], REAL_CLIENT)

    def test_unattended_call_sends_no_psu_ip_rather_than_a_fabricated_one(self):
        # PSD2: PSU-IP-Address is only for a PSU-initiated call. A scheduled job has no
        # PSU, and the bank must not be told 127.0.0.1.
        self._no_request()
        self.assertNotIn("PSU-IP-Address", self._sent_headers())


class TestAuditRecordsIp(_RequestCase):
    def test_sepa_operation_audit_log_records_trusted_ip(self):
        from verenigingen.verenigingen_payments.doctype.sepa_operation_audit_log.sepa_operation_audit_log import (
            SEPAOperationAuditLog,
        )

        self._install_behind_proxy_with_spoof()
        doc = frappe.new_doc("SEPA Operation Audit Log")
        SEPAOperationAuditLog.before_insert(doc)
        self.assertEqual(doc.ip_address, REAL_CLIENT)

    def test_sepa_operation_audit_log_outside_a_request_is_unknown(self):
        from verenigingen.verenigingen_payments.doctype.sepa_operation_audit_log.sepa_operation_audit_log import (
            SEPAOperationAuditLog,
        )

        self._no_request()
        doc = frappe.new_doc("SEPA Operation Audit Log")
        SEPAOperationAuditLog.before_insert(doc)
        self.assertEqual(doc.ip_address, "unknown")

    def test_security_audit_logger_event_ip(self):
        from verenigingen.utils.security.audit_logging import get_audit_logger

        logger = get_audit_logger()
        self._install_behind_proxy_with_spoof()
        stored = []
        with (
            patch.object(logger, "_store_audit_event", side_effect=stored.append),
            patch.object(logger, "_log_to_file"),
        ):
            logger.log_event("test_event", check_alerts=False)
        self.assertEqual(stored[0]["ip_address"], REAL_CLIENT)

    def test_service_security_context_ip(self):
        from verenigingen.services.infrastructure.base_service import APIService

        class _Svc(APIService):
            pass

        self._install_behind_proxy_with_spoof()
        self.assertEqual(_Svc("t").get_security_context()["ip_address"], REAL_CLIENT)

    def test_mollie_audit_trail_context_ip(self):
        from verenigingen.verenigingen_payments.core.compliance.audit_trail import ImmutableAuditTrail

        self._install(REAL_CLIENT, SPOOF)  # direct client; REMOTE_ADDR is right here
        trail = ImmutableAuditTrail.__new__(ImmutableAuditTrail)
        self.assertEqual(trail._get_system_context()["ip_address"], REAL_CLIENT)
        self._install_behind_proxy_with_spoof()  # behind nginx REMOTE_ADDR is the proxy
        self.assertEqual(trail._get_system_context()["ip_address"], REAL_CLIENT)

    def test_membership_application_rate_limit_is_per_client_not_per_proxy(self):
        from verenigingen.api.membership_application import check_rate_limit

        endpoint = f"ipsrc-{frappe.generate_hash(length=6)}"
        self._install_behind_proxy_with_spoof()
        keys = [f"rate_limit:{endpoint}:{ip}" for ip in (REAL_CLIENT, PROXY, SPOOF)]
        self.addCleanup(lambda: [frappe.cache().delete(k) for k in keys])
        self.assertTrue(check_rate_limit(endpoint))
        self.assertEqual(
            [bool(frappe.cache().get(k)) for k in keys],
            [True, False, False],
            "the bucket must belong to the real client, not the proxy or the forged value",
        )


class TestNoSpoofableIpSourcesRemain(VereningingenTestCase):
    """Census: raw IP sources are read only by client_ip.py (and listed exceptions)."""

    TOKENS = {"request_ip", "REMOTE_ADDR", "X-Forwarded-For", "HTTP_X_FORWARDED_FOR", "X-Real-IP"}
    # path suffix -> reason it may read a raw source
    ALLOWED = {
        "utils/security/client_ip.py": "the canonical resolver itself",
        "verenigingen_payments/mollie/utils/security.py": (
            "validate_webhook_origin takes a bare header dict and has no production caller"
            " (only tests); tracked separately"
        ),
    }

    @staticmethod
    def _app_root():
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _hits(self, source, tokens=None):
        tokens = tokens or self.TOKENS
        out = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in tokens:
                out.append((node.lineno, node.value))
            elif isinstance(node, ast.Attribute) and node.attr in tokens:
                out.append((node.lineno, node.attr))
        return out

    def test_control_the_scan_sees_each_raw_source_shape(self):
        src = (
            "a = frappe.local.request_ip\n"
            "b = getattr(frappe.local, 'request_ip', None)\n"
            "c = environ.get('REMOTE_ADDR')\n"
            "d = frappe.get_request_header('X-Forwarded-For')\n"
        )
        self.assertEqual(len(self._hits(src)), 4)
        self.assertEqual(self._hits("x = 'docstring mentioning REMOTE_ADDR here'"), [])

    def test_only_the_resolver_reads_raw_ip_sources(self):
        root = self._app_root()
        found = {}
        for base in (root, os.path.join(os.path.dirname(root), "scripts")):
            for dirpath, dirnames, files in os.walk(base):
                dirnames[:] = [d for d in dirnames if d not in ("tests", "node_modules", "__pycache__")]
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(dirpath, name)
                    with open(path, encoding="utf-8") as fh:
                        hits = self._hits(fh.read())
                    rel = os.path.relpath(path, os.path.dirname(root))
                    if hits and not any(rel.endswith(a) for a in self.ALLOWED):
                        found[rel] = hits
        self.assertEqual(found, {}, "read client_ip.get_client_ip() instead")
