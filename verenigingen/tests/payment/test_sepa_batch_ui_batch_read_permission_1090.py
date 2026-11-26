"""
#1090: the batch-keyed SEPA batch UI endpoints must enforce Direct Debit Batch READ.

get_batch_analytics / preview_sepa_xml (and their _secure twins) loaded
`frappe.get_doc("Direct Debit Batch", batch_name)` with no permission check, so a
caller who cleared the security-tier decorator but holds no read on the DocType read
every member's name, amount, IBAN presence and the XML preview.

Scope: batch pairs only. The invoice-keyed pairs are NOT covered here (see the PR body:
a Sales Invoice read check would lock National Board Member out of the batch form).

Every call goes through frappe.handler.execute_cmd (the real dispatch: whitelist check,
method resolution, decorator stack), as a user holding the real
"Verenigingen Chapter Board Member" role profile: it clears the HIGH tier but its roles have
no Direct Debit Batch DocPerm. Controls: a Staff-role reader still gets data, and an
unknown batch name is refused IDENTICALLY to a forbidden one on every channel compared.

Run:
  cd ~/frappe-bench && PYTHONPATH=<worktree> bench --site test_site_13 run-tests \
    --app verenigingen --module verenigingen.tests.payment.test_sepa_batch_ui_batch_read_permission_1090
"""

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.security.test_authorization_coverage import AuthorizationTestBase

API = "verenigingen.verenigingen_payments.api"
ENDPOINTS = (
    f"{API}.sepa_batch_ui.get_batch_analytics",
    f"{API}.sepa_batch_ui.preview_sepa_xml",
    f"{API}.sepa_batch_ui_secure.get_batch_analytics_secure",
    f"{API}.sepa_batch_ui_secure.preview_sepa_xml_secure",
)


class TestSepaBatchUiBatchReadPermission1090(AuthorizationTestBase):
    def setUp(self):
        super().setUp()
        # handle_api_error (get_batch_analytics) logs every refusal by design; both the
        # forbidden and the unknown name produce the same row, which is compared below.
        self.expectErrorLog("You do not have permission to access this batch")
        self.batch = SEPATestDataFactory(seed=109001, use_faker=True).create_test_direct_debit_batch(
            invoice_count=2
        )
        # Real role profiles. Chapter Board Member clears the HIGH tier but its roles carry
        # no Direct Debit Batch DocPerm; Staff clears HIGH and does carry one.
        self.outsider = self._make_user_with_role_profile(
            "Verenigingen Chapter Board Member", "ddb1090out"
        ).name
        self.reader = self._make_user_with_role_profile("Verenigingen Staff", "ddb1090rd").name
        with self.as_user(self.outsider):
            self.assertFalse(frappe.has_permission("Direct Debit Batch", "read"))
        with self.as_user(self.reader):
            self.assertTrue(frappe.has_permission("Direct Debit Batch", "read"))
        self.unknown = f"DDB-1090-NOPE-{frappe.generate_hash()[:8]}"

    def _dispatch(self, user, cmd, batch_name):
        """Run `cmd` through frappe.handler.execute_cmd; return every observable channel."""
        errors_before = frappe.db.count("Error Log")
        env = EnvironBuilder(
            path=f"/api/method/{cmd}",
            query_string={"batch_name": batch_name},
            method="GET",
            environ_overrides={"REMOTE_ADDR": "10.90.0.1"},
        ).get_environ()
        original_request = getattr(frappe.local, "request", None)
        with self.as_user(user):
            frappe.local.request = Request(env)  # Mock justified: request-context setup for in-process dispatch; the endpoint under test is real
            frappe.local.message_log = []  # Mock justified: request-context setup for in-process dispatch; the endpoint under test is real
            frappe.local.response = frappe._dict()  # Mock justified: request-context setup for in-process dispatch; the endpoint under test is real
            frappe.local.form_dict = frappe._dict(cmd=cmd, batch_name=batch_name)  # Mock justified: request-context setup for in-process dispatch; the endpoint under test is real
            exc = value = None
            try:
                value = frappe.handler.execute_cmd(cmd)
            except Exception as e:  # noqa: BLE001 - the exception IS the observation
                exc = e
            channels = {
                "exc_type": type(exc).__name__ if exc else None,
                "http_status": getattr(exc, "http_status_code", None) if exc else None,
                "message": str(exc) if exc else None,
                "message_log": [m.get("message") if isinstance(m, dict) else m for m in _queued_messages_1090()],
                "error_log_delta": frappe.db.count("Error Log") - errors_before,
                "shape": _response_shape_1090(value),
                "value": value,
            }
            frappe.local.message_log = []  # Mock justified: request-context setup for in-process dispatch; the endpoint under test is real
        frappe.local.request = original_request  # Mock justified: request-context setup for in-process dispatch; the endpoint under test is real
        return channels

    def test_outsider_is_refused_on_every_endpoint(self):
        for cmd in ENDPOINTS:
            with self.subTest(cmd=cmd):
                got = self._dispatch(self.outsider, cmd, self.batch.name)
                self.assertNotIn("Required:", got["message"] or "", "refused by the tier gate, not the check")
                self.assertNotIn("summary", str(got["value"]), "batch analytics leaked")
                self.assertNotIn("transactions", str(got["value"]), "XML preview leaked")
                self.assertNotIn("header", str(got["value"]), "XML preview leaked")
                refused = got["exc_type"] == "PermissionError" or (
                    isinstance(got["value"], dict)
                    and (got["value"].get("error") or {}).get("code") == "PERMISSION_DENIED"
                )
                self.assertTrue(refused, f"expected a permission refusal, got {got}")

    def test_reader_control_still_gets_data(self):
        for cmd in ENDPOINTS:
            with self.subTest(cmd=cmd):
                got = self._dispatch(self.reader, cmd, self.batch.name)
                self.assertIsNone(got["exc_type"], got)
                value = got["value"]
                self.assertTrue("summary" in value or "header" in value, value)

    def test_unknown_and_forbidden_are_indistinguishable(self):
        for cmd in ENDPOINTS:
            with self.subTest(cmd=cmd):
                forbidden = self._dispatch(self.outsider, cmd, self.batch.name)
                unknown = self._dispatch(self.outsider, cmd, self.unknown)
                # The refusal text must not echo the name (it differs by construction).
                for channel in ("exc_type", "http_status", "message", "message_log", "shape"):
                    self.assertEqual(forbidden[channel], unknown[channel], f"{channel} differs")
                self.assertEqual(forbidden["error_log_delta"], unknown["error_log_delta"])
                self.assertNotIn(self.batch.name, str(forbidden["value"]) + str(forbidden["message"]))
                self.assertNotIn(self.unknown, str(unknown["value"]) + str(unknown["message"]))

    def test_unknown_name_for_an_outsider_is_a_permission_refusal_not_not_found(self):
        for cmd in ENDPOINTS:
            with self.subTest(cmd=cmd):
                got = self._dispatch(self.outsider, cmd, self.unknown)
                self.assertNotIn("not found", (got["message"] or "").lower())
                self.assertNotIn("not found", str(got["value"]).lower())


def _queued_messages_1090():
    return list(getattr(frappe.local, "message_log", []) or [])


def _response_shape_1090(value):
    if isinstance(value, dict):
        return ("dict", tuple(sorted(value)))
    return (type(value).__name__,)
