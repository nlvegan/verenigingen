"""#2252: the subscription webhook's Error Log rows.

frappe.log_error is (title, message). These call sites passed (message, title), so the
dynamic text landed in the title (`method`, 140 chars) and the label in the body, and the
authentication-failure row also carried every request header (Authorization, Cookie).

The Error Log doctype is MyISAM: rows written here are not rolled back, so each test
deletes the rows it caused.

Mock justified: `authenticate_mollie_webhook` and the parse helper are the SEAMS that put
the code into the failure branch under test (a signature check against live Mollie
credentials is not what is being tested); the Error Log write itself is real and is read
back from the database.
"""

from unittest.mock import patch

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import payment_gateways as pg

SECRET_AUTH = "Bearer sentinel-secret-token-2252"
SECRET_COOKIE = "sid=sentinel-cookie-2252"


class TestSubscriptionWebhookErrorLogShape(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._old_request = getattr(frappe.local, "request", None)
        builder = EnvironBuilder(
            method="POST",
            data='{"id": "sub_x"',
            headers={
                "Authorization": SECRET_AUTH,
                "Cookie": SECRET_COOKIE,
                "X-Mollie-Signature": "bogus",
            },
        )
        frappe.local.request = Request(builder.get_environ())
        self._before = set(frappe.get_all("Error Log", pluck="name", limit_page_length=0))
        self.addCleanup(self._restore)

    def _restore(self):
        frappe.local.request = self._old_request
        for name in self._new_rows():
            frappe.delete_doc("Error Log", name, force=True, ignore_permissions=True)

    def _new_rows(self):
        now = set(frappe.get_all("Error Log", pluck="name", limit_page_length=0))
        return list(now - self._before)

    def _rows(self):
        return frappe.get_all("Error Log", filters={"name": ["in", self._new_rows()]}, fields=["method", "error"])

    def _assert_shape(self, rows, label, diagnostic):
        match = [r for r in rows if r.method == label]
        self.assertEqual(len(match), 1, f"no row titled {label!r}; got titles {[r.method for r in rows]}")
        self.assertIn(diagnostic, match[0].error)
        return match[0]

    def test_authentication_failure_row_has_label_title_and_no_secret_headers(self):
        sentinel = "auth-sentinel-2252"
        with patch(
            "verenigingen.utils.webhook_security.authenticate_mollie_webhook",
            side_effect=Exception(sentinel),
        ):
            parsed, error = pg._authenticate_and_parse_subscription_payload()
        self.assertIsNone(parsed)
        self.assertIsNotNone(error)

        rows = self._rows()
        row = self._assert_shape(rows, "Webhook Security Alert", sentinel)
        for r in rows:
            self.assertNotIn(SECRET_AUTH, r.error)
            self.assertNotIn(SECRET_COOKIE, r.error)
            self.assertNotIn("sentinel-secret", r.error)
        self.assertNotIn(sentinel, row.method)

    def test_json_parse_failure_row_has_label_title(self):
        with patch(
            "verenigingen.utils.webhook_security.authenticate_mollie_webhook",
            return_value='{"id": "sub_x"',
        ):
            parsed, error = pg._authenticate_and_parse_subscription_payload()
        self.assertIsNone(parsed)
        self._assert_shape(self._rows(), "Mollie Subscription Webhook JSON Error", "JSON parsing failed")

    def test_form_parse_failure_row_has_label_title(self):
        auth = patch(
            "verenigingen.utils.webhook_security.authenticate_mollie_webhook",
            return_value="a=b",
        )
        # Mock justified: stdlib urllib.parse.unquote_plus is the only way to make a
        # well-formed "k=v" body fail form parsing; the Error Log write stays real.
        unquote = patch("urllib.parse.unquote_plus", side_effect=ValueError("form-sentinel-2252"))
        with auth, unquote:
            parsed, error = pg._authenticate_and_parse_subscription_payload()
        self.assertIsNone(parsed)
        self._assert_shape(self._rows(), "Mollie Subscription Webhook Parsing Error", "form-sentinel-2252")

    def test_handler_catch_all_row_has_label_title(self):
        with patch.object(pg, "_authenticate_and_parse_subscription_payload", side_effect=RuntimeError("boom-2252")):
            pg.mollie_subscription_webhook()
        self._assert_shape(self._rows(), "Mollie Subscription Webhook", "boom-2252")

    def test_payment_processing_row_has_label_title(self):
        """The real payment step fails on a bare gateway stand-in (no Mollie call is made)."""
        parsed = {"subscription_id": "sub_2252", "payment_id": "tr_2252"}
        auth = patch.object(pg, "_authenticate_and_parse_subscription_payload", return_value=(parsed, None))
        # Mock justified: member/customer lookup is a DB read of fixtures this test does not build.
        find = patch.object(pg, "_find_member_for_subscription", return_value=("M-2252", "C", "cst_2252"))
        # Mock justified: PaymentGatewayFactory would build a live Mollie client.
        gateway = patch.object(pg.PaymentGatewayFactory, "get_gateway", return_value=object())
        status = patch.object(pg, "_update_subscription_status")
        with auth, find, gateway, status:
            result = pg.mollie_subscription_webhook()
        self.assertIn("payment_error", result)
        self._assert_shape(
            self._rows(),
            "Mollie Subscription Payment Processing",
            "for member M-2252: " + result["payment_error"],
        )

    def test_unknown_subscription_row_has_label_title(self):
        member, _, _ = pg._find_member_for_subscription("sub_unknown_2252")
        self.assertIsNone(member)
        self._assert_shape(self._rows(), "Mollie Subscription Webhook", "sub_unknown_2252")

    def test_subscription_status_failure_row_has_label_title(self):
        class Gateway:
            def get_subscription_status(self, customer_id, subscription_id):
                return {"status": "error", "message": "status-sentinel-2252"}

        result = {"actions": []}
        pg._update_subscription_status(Gateway(), "cst_2252", "sub_2252", "M-2252", result)
        self.assertEqual(result["subscription_error"], "status-sentinel-2252")
        self._assert_shape(self._rows(), "Mollie Subscription Webhook", "status-sentinel-2252")
