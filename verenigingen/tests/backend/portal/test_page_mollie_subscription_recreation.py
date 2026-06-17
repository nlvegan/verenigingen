# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for the Mollie subscription recreation page controller
(``verenigingen/templates/pages/mollie_subscription_recreation.py``).

This is an administrative tool that lets privileged staff re-create broken
Mollie subscriptions from a CSV upload. The controller is permission-gated
(``has_admin_access`` / ``require_login``), parses & validates CSV against the
live Mollie API, and orchestrates a cancel-then-recreate flow.

Everything runs against real users/roles created via the factory. The ONLY
external boundary stubbed is the Mollie API: the controller builds a real
``MollieDebugService`` (which would construct a real ``MollieClient``), so we
patch the class at its import seam
(``...mollie_subscription_recreation.MollieDebugService``) with a fake whose
methods return the dict shapes the controller consumes. No business logic of
the page itself is mocked.

The fake is designed so the cancel/poll/retry paths resolve with zero real
sleeps: ``poll_subscription_cancellation`` returns immediately when
``debug_subscription`` reports an "...not found" error, and the retry helper
only sleeps when a call raises.
"""

import base64
import json
from unittest.mock import patch

import frappe

from verenigingen.templates.pages import mollie_subscription_recreation as msr
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

PATCH_TARGET = "verenigingen.templates.pages.mollie_subscription_recreation.MollieDebugService"


class FakeMollieDebugService:
    """Stub for the Mollie API boundary.

    Behaviour is driven by class-level attributes set per test, so the
    controller's own logic (validation, branching, orchestration) runs for
    real while every network call is short-circuited.
    """

    # Defaults — each test overrides what it needs.
    debug_subscription_return = {"error": "not found"}
    debug_mandate_return = {"mandate_data": {"status": "valid"}}
    debug_customer_return = {"mandates": [], "subscriptions": []}
    admin_cancel_return = {}
    create_subscription_return = {"subscription_id": "sub_new"}

    def __init__(self, *args, **kwargs):
        pass

    def debug_subscription(self, subscription_id, customer_id=None):
        return type(self).debug_subscription_return

    def debug_mandate(self, mandate_id, customer_id=None):
        return type(self).debug_mandate_return

    def debug_customer(self, customer_id):
        return type(self).debug_customer_return

    def admin_cancel_subscription(self, customer_id, subscription_id, reason="x"):
        return type(self).admin_cancel_return

    def create_subscription(self, **kwargs):
        return type(self).create_subscription_return


def make_fake(**overrides):
    """Build a one-off FakeMollieDebugService subclass with given returns."""
    return type("_FakeMollie", (FakeMollieDebugService,), overrides)


class TestPageMollieSubscriptionRecreation(EnhancedTestCase):
    ADMIN_ROLE = "Verenigingen Administrator"
    NONADMIN_ROLE = "Verenigingen Volunteer"

    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()
        self._original_form_dict = frappe.local.form_dict
        frappe.local.form_dict = frappe._dict()

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        if hasattr(self, "_original_user"):
            frappe.set_user(self._original_user)
        super().tearDown()

    # ------------------------------------------------------------------
    # get_context - permission gate
    # ------------------------------------------------------------------

    def test_get_context_denied_for_non_admin_role(self):
        """A non-privileged role (Volunteer) is rejected with PermissionError."""
        with self.as_role(self.NONADMIN_ROLE):
            context = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                msr.get_context(context)

    def test_get_context_denied_for_guest(self):
        """require_login() blocks Guest before any admin check."""
        with self.as_user("Guest"):
            context = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                msr.get_context(context)

    def test_get_context_allowed_for_admin(self):
        """An admin role gets a fully-populated context (title, csrf, Mollie fields)."""
        with self.as_role(self.ADMIN_ROLE):
            context = frappe._dict()
            result = msr.get_context(context)
            self.assertEqual(result.title, "Mollie Subscription Recreation")
            self.assertTrue(result.csrf_token)
            self.assertEqual(result.no_cache, 1)
            # populate_mollie_context populates settings-derived fields.
            self.assertIn("mollie_configured", result)

    # ------------------------------------------------------------------
    # has_admin_access
    # ------------------------------------------------------------------

    def test_has_admin_access_true_under_admin_role(self):
        with self.as_role(self.ADMIN_ROLE):
            self.assertTrue(msr.has_admin_access())

    def test_has_admin_access_false_under_nonadmin_role(self):
        with self.as_role(self.NONADMIN_ROLE):
            self.assertFalse(msr.has_admin_access())

    # ------------------------------------------------------------------
    # parse_amount_string
    # ------------------------------------------------------------------

    def test_parse_amount_string_variants(self):
        self.assertEqual(msr.parse_amount_string("25.00 EUR"), 25.0)
        self.assertEqual(msr.parse_amount_string("25.00"), 25.0)
        self.assertEqual(msr.parse_amount_string(25.0), 25.0)
        self.assertEqual(msr.parse_amount_string(None), 0.0)
        self.assertEqual(msr.parse_amount_string("garbage"), 0.0)

    # ------------------------------------------------------------------
    # sanitize_csv_field
    # ------------------------------------------------------------------

    def test_sanitize_csv_field(self):
        self.assertEqual(msr.sanitize_csv_field("=cmd"), "'=cmd")
        self.assertEqual(msr.sanitize_csv_field("benign"), "benign")
        # Empty/falsy is returned unchanged.
        self.assertEqual(msr.sanitize_csv_field(""), "")

    # ------------------------------------------------------------------
    # sanitize_description
    # ------------------------------------------------------------------

    def test_sanitize_description(self):
        self.assertEqual(msr.sanitize_description(None), "Membership dues")
        self.assertEqual(msr.sanitize_description("  "), "Membership dues")
        self.assertEqual(msr.sanitize_description("x"), "x")

    # ------------------------------------------------------------------
    # generate_unique_description
    # ------------------------------------------------------------------

    def test_generate_unique_description(self):
        self.assertEqual(msr.generate_unique_description("base", "suffix"), "base (suffix)")
        with_default = msr.generate_unique_description("base", "")
        self.assertIn("updated", with_default)
        self.assertTrue(with_default.startswith("base ("))

    # ------------------------------------------------------------------
    # retry_api_call
    # ------------------------------------------------------------------

    def test_retry_api_call_succeeds_first_try(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            return "ok"

        self.assertEqual(msr.retry_api_call(fn, max_attempts=2), "ok")
        self.assertEqual(calls["n"], 1)

    def test_retry_api_call_retries_then_reraises(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise RuntimeError("boom")

        # The one inter-attempt sleep is backoff_factor**0 == 1.0s regardless of
        # the factor, so patch time.sleep to keep the test instant.
        with patch.object(msr.time, "sleep") as slept:
            with self.assertRaises(RuntimeError):
                msr.retry_api_call(fn, max_attempts=2, backoff_factor=2.0)
        self.assertEqual(calls["n"], 2)
        # One sleep between the two attempts.
        self.assertEqual(slept.call_count, 1)

    # ------------------------------------------------------------------
    # parse_and_validate_csv - non-Mollie validation branches
    # ------------------------------------------------------------------

    def test_csv_missing_required_columns(self):
        with self.as_role(self.ADMIN_ROLE):
            result = msr.parse_and_validate_csv("foo,bar\n1,2\n")
        self.assertEqual(result["status"], "error")
        self.assertIn("Required columns", result["error"])

    def test_csv_no_valid_rows(self):
        with self.as_role(self.ADMIN_ROLE):
            # Header present but row has empty required fields.
            result = msr.parse_and_validate_csv("customer_id,subscription_id\n,\n")
        self.assertEqual(result["status"], "error")
        self.assertIn("No valid rows", result["error"])

    def test_csv_invalid_global_date_format(self):
        csv_content = "customer_id,subscription_id\ncst_x,sub_x\n"
        with self.as_role(self.ADMIN_ROLE):
            result = msr.parse_and_validate_csv(csv_content, planned_next_invoice_date="31-12-2026")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid date format", result["error"])

    # ------------------------------------------------------------------
    # parse_and_validate_csv - Mollie-touching branches
    # ------------------------------------------------------------------

    def test_csv_happy_path_valid_row(self):
        fake = make_fake(
            debug_subscription_return={
                "subscription_data": {
                    "amount": "25.00 EUR",
                    "next_payment_date": "2020-01-01",
                    "status": "active",
                    "interval": "1 month",
                    "description": "Dues",
                    "mandate_id": "mdt_x",
                }
            },
            debug_mandate_return={"mandate_data": {"status": "valid"}},
        )
        csv_content = "customer_id,subscription_id\ncst_x,sub_x\n"
        with self.as_role(self.ADMIN_ROLE):
            with patch(PATCH_TARGET, fake):
                result = msr.parse_and_validate_csv(csv_content, skip_date_validation=True)
        self.assertEqual(result["status"], "success")
        row = result["results"][0]
        self.assertIn(row["status"], ("valid", "warning"))
        self.assertEqual(row["current_amount"], 25.0)
        self.assertTrue(row["mandate_valid"])

    def test_csv_cancelled_subscription_is_error(self):
        fake = make_fake(
            debug_subscription_return={
                "subscription_data": {
                    "amount": "25.00 EUR",
                    "next_payment_date": "2020-01-01",
                    "status": "cancelled",
                    "interval": "1 month",
                    "description": "Dues",
                    "mandate_id": "mdt_x",
                }
            },
        )
        csv_content = "customer_id,subscription_id\ncst_x,sub_x\n"
        with self.as_role(self.ADMIN_ROLE):
            with patch(PATCH_TARGET, fake):
                result = msr.parse_and_validate_csv(csv_content, skip_date_validation=True)
        row = result["results"][0]
        self.assertEqual(row["status"], "error")

    def test_csv_subscription_lookup_error_is_error(self):
        fake = make_fake(debug_subscription_return={"error": "not found"})
        csv_content = "customer_id,subscription_id\ncst_x,sub_x\n"
        with self.as_role(self.ADMIN_ROLE):
            with patch(PATCH_TARGET, fake):
                result = msr.parse_and_validate_csv(csv_content, skip_date_validation=True)
        row = result["results"][0]
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["error"], "not found")

    # ------------------------------------------------------------------
    # recreate_subscriptions
    # ------------------------------------------------------------------

    @staticmethod
    def _encode(payload):
        return base64.b64encode(json.dumps(payload).encode()).decode()

    def test_recreate_empty_payload_is_error(self):
        with self.as_role(self.ADMIN_ROLE):
            result = msr.recreate_subscriptions("")
        self.assertEqual(result["status"], "error")
        self.assertIn("required", result["error"].lower())

    def test_recreate_non_base64_is_decode_error(self):
        with self.as_role(self.ADMIN_ROLE):
            # "!!!!" is not valid base64 of valid utf-8 JSON.
            result = msr.recreate_subscriptions("!!!notbase64@@@")
        self.assertEqual(result["status"], "error")
        self.assertIn("decode", result["error"].lower())

    def test_recreate_missing_interval_is_error(self):
        payload = self._encode(
            [
                {
                    "customer_id": "cst_x",
                    "subscription_id": "sub_x",
                    "planned_amount": 25.0,
                    "planned_next_invoice_date": "2026-01-01",
                    # no current_interval
                }
            ]
        )
        with self.as_role(self.ADMIN_ROLE):
            result = msr.recreate_subscriptions(payload)
        self.assertEqual(result["status"], "completed")
        row = result["results"][0]
        self.assertEqual(row["status"], "error")
        self.assertIn("interval", row["error"].lower())

    def test_recreate_no_valid_mandate_is_error(self):
        # mandate_valid False + no mandate_id; debug_customer returns no mandates.
        fake = make_fake(debug_customer_return={"mandates": []})
        payload = self._encode(
            [
                {
                    "customer_id": "cst_x",
                    "subscription_id": "sub_x",
                    "planned_amount": 25.0,
                    "planned_next_invoice_date": "2026-01-01",
                    "current_interval": "1 month",
                    "mandate_valid": False,
                }
            ]
        )
        with self.as_role(self.ADMIN_ROLE):
            with patch(PATCH_TARGET, fake):
                result = msr.recreate_subscriptions(payload)
        row = result["results"][0]
        self.assertEqual(row["status"], "error")
        self.assertIn("mandate", row["error"].lower())

    def test_recreate_full_success_path_no_sleeps(self):
        """A complete cancel→poll→create path succeeds with zero real sleeps.

        admin_cancel returns no error; debug_subscription reports the old sub as
        "not found" so poll confirms cancellation on attempt 0 (no sleep);
        create_subscription returns a new id.
        """
        fake = make_fake(
            admin_cancel_return={},
            debug_subscription_return={"error": "not found"},
            create_subscription_return={"subscription_id": "sub_new"},
        )
        payload = self._encode(
            [
                {
                    "customer_id": "cst_x",
                    "subscription_id": "sub_old",
                    "planned_amount": 25.0,
                    "planned_next_invoice_date": "2026-01-01",
                    "current_interval": "1 month",
                    "current_mandate_id": "mdt_x",
                    "mandate_valid": True,
                    "current_description": "Dues",
                    "planned_description": "Dues",
                }
            ]
        )
        with self.as_role(self.ADMIN_ROLE):
            with patch.object(msr.time, "sleep") as slept:
                with patch(PATCH_TARGET, fake):
                    result = msr.recreate_subscriptions(payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"]["success"], 1)
        row = result["results"][0]
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["new_subscription_id"], "sub_new")
        # Guard against accidental real sleeps in the orchestration path.
        self.assertEqual(slept.call_count, 0)

    # ------------------------------------------------------------------
    # export_subscriptions_from_customers
    # ------------------------------------------------------------------

    def test_export_denied_for_non_admin(self):
        with self.as_role(self.NONADMIN_ROLE):
            with self.assertRaises(frappe.PermissionError):
                msr.export_subscriptions_from_customers("customer_id\ncst_x\n")

    def test_export_missing_customer_id_column(self):
        with self.as_role(self.ADMIN_ROLE):
            result = msr.export_subscriptions_from_customers("foo\nbar\n")
        self.assertEqual(result["status"], "error")
        self.assertIn("customer_id", result["error"])

    def test_export_happy_path(self):
        fake = make_fake(
            debug_customer_return={
                "subscriptions": [
                    {
                        "id": "sub_a",
                        "status": "active",
                        "amount": "25.00 EUR",
                        "interval": "1 month",
                        "description": "Dues",
                        "next_payment_date": "2026-01-01",
                        "mandate_id": "mdt",
                    }
                ]
            }
        )
        with self.as_role(self.ADMIN_ROLE):
            with patch(PATCH_TARGET, fake):
                result = msr.export_subscriptions_from_customers("customer_id\ncst_x\n")
        self.assertIn(result["status"], ("success", "partial"))
        self.assertIn("sub_a", result["csv_content"])
        self.assertEqual(result["subscription_count"], 1)
