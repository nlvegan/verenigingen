"""
#1439 (payment_processing cluster): the scalar parameters of the three overdue-payment endpoints
are annotated, so Frappe's dispatch-time validation refuses a non-scalar payload with a 417 instead
of letting it reach the endpoint body.

Every case goes through the real WSGI app (``run_wsgi_cases``): annotations are only checked at
dispatch, a direct Python call proves nothing. The JSON body carries the values a browser's
``frappe.call`` delivers (Check fields as 0/1 or "0"/"1", Select/Text as strings).

Controls send the real callers' values and must reach the endpoint body (200 or the endpoint's own
400), so a wrong annotation that rejects a legitimate caller (e.g. ``int`` for a string id) fails here.

Usage:
    bench --site test_site_12 run-tests --app verenigingen \
        --module verenigingen.tests.api.test_payment_processing_param_types_1439
"""

import json

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.wsgi_http_session import (
    CommittedLoginUsersMixin,
    api_path,
    run_wsgi_cases,
)

BASE = "verenigingen.api.payment_processing."
SEND = api_path(BASE + "send_overdue_payment_reminders")
EXPORT = api_path(BASE + "export_overdue_payments")
BULK = api_path(BASE + "execute_bulk_payment_action")
# A chapter nobody belongs to: the overdue report returns no rows, so no reminder is ever built.
NO_ROWS = json.dumps({"chapter": "NO-SUCH-CHAPTER-1439"})
MAIL_STUBS = ("frappe.sendmail",)  # Mock justified: External Service - outbound SMTP

NON_SCALAR = {"not": "a scalar"}
# Frappe widens an annotation with the TYPE OF THE DEFAULT (``int`` + default "x" accepts str too), so a
# wrong ``int`` annotation on a defaulted str param is only visible to a value that is an int.
A_NUMBER = 5


class TestPaymentProcessingParamTypes1439(CommittedLoginUsersMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.finance = self._create_login_users(finance="Verenigingen Administrator")["finance"]

    def _call(self, endpoint, **args):
        case = {
            "name": "c",
            "endpoint": endpoint,
            "login": {"usr": self.finance, "pwd": self.password},
            "csrf": "valid",
            "json": args,
        }
        return run_wsgi_cases(case, patches=MAIL_STUBS)["c"]

    def _assert_refused_by_annotation(self, endpoint, param, **args):
        out = self._call(endpoint, **args)
        self.assertEqual(out["status"], 417, (param, out["body"][:300]))
        self.assertIn(f"Argument '{param}'", out["body"], param)

    def _assert_reached_body(self, endpoint, **args):
        out = self._call(endpoint, **args)
        self.assertNotEqual(out["status"], 417, out["body"][:300])
        self.assertIn(out["status"], (200, 400), out["body"][:300])
        return out

    # --- send_overdue_payment_reminders -------------------------------------------------
    def test_send_refuses_a_non_scalar_for_every_scalar_param(self):
        for param in ("reminder_type", "include_payment_link", "custom_message", "send_to_chapters"):
            with self.subTest(param=param):
                self._assert_refused_by_annotation(
                    SEND, param, filters=NO_ROWS, **{param: NON_SCALAR}
                )

    def test_send_refuses_a_number_where_a_string_is_expected(self):
        for param in ("reminder_type", "custom_message"):
            with self.subTest(param=param):
                self._assert_refused_by_annotation(SEND, param, filters=NO_ROWS, **{param: A_NUMBER})

    def test_send_accepts_the_values_the_report_dialog_sends(self):
        """Control: Check fields arrive as 0/1 or "0"/"1", "true"/"false"; "" was always read as false (cbool)."""
        for flag in (0, 1, "0", "1", "true", "false", "", True, False):
            with self.subTest(flag=flag):
                out = self._assert_reached_body(
                    SEND,
                    reminder_type="Urgent Notice",  # not the default: the default's type would widen a wrong annotation
                    include_payment_link=flag,
                    custom_message="Hello",
                    send_to_chapters=flag,
                    filters=NO_ROWS,
                )
                self.assertEqual(out["status"], 200, out["body"][:300])

    # --- export_overdue_payments --------------------------------------------------------
    def test_export_refuses_a_non_scalar_format(self):
        self._assert_refused_by_annotation(EXPORT, "format", filters=NO_ROWS, format=NON_SCALAR)

    def test_export_refuses_a_number_format(self):
        self._assert_refused_by_annotation(EXPORT, "format", filters=NO_ROWS, format=A_NUMBER)

    def test_export_accepts_a_string_format(self):
        """Control: an unsupported but well-typed format reaches the body's own 400."""
        out = self._assert_reached_body(EXPORT, filters=NO_ROWS, format="PDF")
        self.assertIn("Invalid export format", out["body"])

    # --- execute_bulk_payment_action ----------------------------------------------------
    def test_bulk_refuses_a_non_scalar_for_each_scalar_param(self):
        for param in ("action", "apply_to"):
            with self.subTest(param=param):
                args = {"action": "Bogus Action", "apply_to": "All Visible Records", "filters": NO_ROWS}
                args[param] = NON_SCALAR
                self._assert_refused_by_annotation(BULK, param, **args)

    def test_bulk_refuses_a_number_for_each_string_param(self):
        for param in ("action", "apply_to"):
            with self.subTest(param=param):
                args = {"action": "Bogus Action", "apply_to": "All Visible Records", "filters": NO_ROWS}
                args[param] = A_NUMBER
                self._assert_refused_by_annotation(BULK, param, **args)

    def test_bulk_accepts_string_action_and_apply_to(self):
        """Control: the dialog's strings reach the body (an unknown action is its own 400)."""
        out = self._assert_reached_body(
            BULK, action="Bogus Action", apply_to="Urgent Only (>30 days)", filters=NO_ROWS
        )
        self.assertIn("Invalid action", out["body"])
