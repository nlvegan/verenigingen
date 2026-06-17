# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for the Mollie bulk payment creation page controller
(``verenigingen/templates/pages/mollie_bulk_payment_creation.py``).

This is an administrative tool for creating one-time payments / subscriptions
in bulk against existing Mollie mandates. The behaviours under test:

* ``get_context`` / ``has_admin_access`` - the role gate guarding the page.
* ``sanitize_csv_field`` - CSV formula-injection escaping (pure helper).
* ``validate_csv_members`` - CSV parsing + per-row validation, including the
  member-lookup and mandate-validity branches.
* ``create_bulk_payments`` - the subscription-creation endpoint, including the
  guard branches and the happy path with a duplicate check.
* ``get_webhook_url`` - URL construction with the env= parameter.

Everything runs against real ORM documents created via the factory. The ONLY
external boundary stubbed is the Mollie API: the controller builds a real
``MollieDebugService`` (which constructs a real MollieClient) and calls
``MollieSettings.get_mollie_client()``. Both are patched at the import seam so
the controller's own business logic is exercised unmodified.
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.templates.pages import mollie_bulk_payment_creation as page
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles


def _future_date(days=30):
    return (datetime.now() + timedelta(days=days)).date().strftime("%Y-%m-%d")


class FakeMollieService:
    """Stand-in for MollieDebugService exposing only what the controller calls.

    Behaviour is configured via class-level attributes set by each test before
    the controller is invoked, so a single fake serves every branch.
    """

    debug_customer_return = {"mandates": []}
    debug_mandate_return = {"mandate_data": {"status": "valid"}}
    create_subscription_return = {"status": "success", "subscription_id": "sub_default"}

    def __init__(self, *args, **kwargs):
        pass

    def debug_customer(self, customer_id):
        return type(self).debug_customer_return

    def debug_mandate(self, mandate_id, customer_id=None):
        return type(self).debug_mandate_return

    def create_subscription(self, **kwargs):
        type(self).last_create_subscription_kwargs = kwargs
        return type(self).create_subscription_return


class FakeSubscriptionList(list):
    """A list-like that also exposes .list() returning itself (Mollie SDK seam)."""

    def list(self):
        return self


class FakeMollieClient:
    """Minimal Mollie client: client.customers.get(id).subscriptions.list()."""

    def __init__(self, subscriptions=None):
        self._subscriptions = FakeSubscriptionList(subscriptions or [])

    @property
    def customers(self):
        return self

    def get(self, customer_id):
        return SimpleNamespace(subscriptions=self._subscriptions)


class TestPageMollieBulkPaymentCreation(EnhancedTestCase):
    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()
        self._original_form_dict = frappe.local.form_dict
        frappe.local.form_dict = frappe._dict()
        # Reset fake service config to defaults for each test.
        FakeMollieService.debug_customer_return = {"mandates": []}
        FakeMollieService.debug_mandate_return = {"mandate_data": {"status": "valid"}}
        FakeMollieService.create_subscription_return = {
            "status": "success",
            "subscription_id": "sub_default",
        }

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        if hasattr(self, "_original_user"):
            frappe.set_user(self._original_user)
        super().tearDown()

    def _patch_service(self):
        return patch.object(page, "MollieDebugService", FakeMollieService)

    def _make_member_with_customer(self, customer_id, status="Active", mandate_id=None):
        member = self.create_test_member(
            first_name="Bulk",
            last_name="Payer",
            email=f"bulk.{frappe.generate_hash()[:8]}@example.com",
            birth_date="1990-01-01",
        )
        values = {"mollie_customer_id": customer_id, "status": status}
        if mandate_id is not None:
            values["mollie_mandate_id"] = mandate_id
        frappe.db.set_value("Member", member.name, values)
        member.reload()
        return member

    # ------------------------------------------------------------------
    # get_context - role gate
    # ------------------------------------------------------------------

    def test_get_context_denies_non_privileged_user(self):
        """A logged-in non-privileged user (Volunteer) is denied with PermissionError."""
        with self.as_role(Roles.VOLUNTEER):
            context = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                page.get_context(context)

    def test_get_context_allows_admin_and_populates_mollie(self):
        """A Verenigingen Administrator gets a titled context with Mollie fields populated."""
        with self.as_role(Roles.VERENIGINGEN_ADMIN):
            context = frappe._dict()
            page.get_context(context)
            self.assertEqual(context.title, "Mollie Bulk Payment Creation")
            self.assertEqual(context.no_cache, 1)
            # populate_mollie_context always sets these keys.
            self.assertIn("mollie_configured", context)
            self.assertIn("test_mode", context)

    # ------------------------------------------------------------------
    # has_admin_access
    # ------------------------------------------------------------------

    def test_has_admin_access_true_for_admin_role(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN):
            self.assertTrue(page.has_admin_access())

    def test_has_admin_access_false_for_volunteer_role(self):
        with self.as_role(Roles.VOLUNTEER):
            self.assertFalse(page.has_admin_access())

    # ------------------------------------------------------------------
    # sanitize_csv_field
    # ------------------------------------------------------------------

    def test_sanitize_csv_field_escapes_formula_chars(self):
        for char in ("=", "+", "-", "@"):
            value = f"{char}cmd|'/c calc'"
            sanitized = page.sanitize_csv_field(value)
            self.assertTrue(sanitized.startswith("'" + char), f"failed for {char!r}")

    def test_sanitize_csv_field_passes_benign_values(self):
        self.assertEqual(page.sanitize_csv_field("cst_normal123"), "cst_normal123")

    def test_sanitize_csv_field_empty_and_none_unchanged(self):
        self.assertEqual(page.sanitize_csv_field(""), "")
        self.assertIsNone(page.sanitize_csv_field(None))

    # ------------------------------------------------------------------
    # validate_csv_members - pure validation guards (no Mollie needed)
    # ------------------------------------------------------------------

    def test_validate_invalid_interval_is_error(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.validate_csv_members("customer_id\ncst_x\n", payment_interval="13 months")
        self.assertEqual(result["status"], "error")
        self.assertIn("interval", result["error"].lower())

    def test_validate_payment_times_below_minimum_is_error(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.validate_csv_members("customer_id\ncst_x\n", payment_times=0)
        self.assertEqual(result["status"], "error")
        self.assertIn("at least 1", result["error"])

    def test_validate_payment_times_above_maximum_is_error(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.validate_csv_members("customer_id\ncst_x\n", payment_times=101)
        self.assertEqual(result["status"], "error")
        self.assertIn("exceed 100", result["error"])

    def test_validate_missing_customer_id_column_is_error(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.validate_csv_members("wrong_col\nval\n")
        self.assertEqual(result["status"], "error")
        self.assertIn("customer_id", result["error"])

    def test_validate_global_charge_date_in_past_is_error(self):
        past = (datetime.now() - timedelta(days=5)).date().strftime("%Y-%m-%d")
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.validate_csv_members("customer_id\ncst_x\n", global_charge_date=past)
        self.assertEqual(result["status"], "error")
        self.assertIn("future", result["error"])

    def test_validate_global_charge_date_malformed_is_error(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.validate_csv_members("customer_id\ncst_x\n", global_charge_date="31-12-2099")
        self.assertEqual(result["status"], "error")
        self.assertIn("date format", result["error"].lower())

    # ------------------------------------------------------------------
    # validate_csv_members - row-level branches (member lookup + mandate)
    # ------------------------------------------------------------------

    def test_validate_member_not_found_row_is_error(self):
        """A customer_id with no matching Member yields a 'Member not found' row error."""
        unknown_id = f"cst_unknown_{frappe.generate_hash()[:8]}"
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.validate_csv_members(
                f"customer_id\n{unknown_id}\n",
                global_amount="10.00",
                global_charge_date=_future_date(),
            )
        self.assertEqual(result["status"], "success")
        row = result["results"][0]
        self.assertEqual(row["status"], "error")
        self.assertTrue(any("not found" in issue.lower() for issue in row["issues"]))

    def test_validate_non_active_member_with_valid_mandate_is_warning(self):
        """A non-Active member with a stored, valid mandate is flagged warning, mandate valid."""
        customer_id = f"cst_warn_{frappe.generate_hash()[:8]}"
        member = self._make_member_with_customer(
            customer_id, status="Suspended", mandate_id="mdt_stored_valid"
        )
        FakeMollieService.debug_mandate_return = {"mandate_data": {"status": "valid"}}
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.validate_csv_members(
                f"customer_id\n{customer_id}\n",
                global_amount="15.00",
                global_charge_date=_future_date(),
            )
        row = result["results"][0]
        self.assertEqual(row["member_id"], member.name)
        self.assertTrue(row["mandate_valid"])
        self.assertEqual(row["status"], "warning")
        self.assertTrue(any("status is Suspended" in i for i in row["issues"]))

    def test_validate_stored_mandate_not_valid_is_error(self):
        """A stored mandate that Mollie reports as non-valid produces a row error."""
        customer_id = f"cst_badmandate_{frappe.generate_hash()[:8]}"
        self._make_member_with_customer(customer_id, status="Active", mandate_id="mdt_revoked")
        FakeMollieService.debug_mandate_return = {"mandate_data": {"status": "invalid"}}
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.validate_csv_members(
                f"customer_id\n{customer_id}\n",
                global_amount="15.00",
                global_charge_date=_future_date(),
            )
        row = result["results"][0]
        self.assertFalse(row["mandate_valid"])
        self.assertEqual(row["status"], "error")
        self.assertTrue(any("Mandate status is invalid" in i for i in row["issues"]))

    # ------------------------------------------------------------------
    # create_bulk_payments - guard branches
    # ------------------------------------------------------------------

    def test_create_bulk_payments_empty_payload_is_error(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.create_bulk_payments("")
        self.assertEqual(result["status"], "error")
        self.assertIn("required", result["error"].lower())

    def test_create_bulk_payments_invalid_json_is_error(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.create_bulk_payments("{not valid json")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid JSON", result["error"])

    def test_create_bulk_payments_missing_mandate_row_is_error(self):
        payload = json.dumps(
            [
                {
                    "customer_id": "cst_x",
                    "amount": 10.0,
                    "charge_date": _future_date(),
                    # mandate_id intentionally absent
                }
            ]
        )
        with (
            self.as_role(Roles.VERENIGINGEN_ADMIN),
            self._patch_service(),
            patch(
                "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.MollieSettings.get_mollie_client",
                return_value=FakeMollieClient(),
            ),
        ):
            result = page.create_bulk_payments(payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"]["errors"], 1)
        self.assertEqual(result["results"][0]["error"], "No valid mandate ID")

    def test_create_bulk_payments_non_positive_amount_is_error(self):
        payload = json.dumps(
            [
                {
                    "customer_id": "cst_x",
                    "amount": 0,
                    "charge_date": _future_date(),
                    "mandate_id": "mdt_1",
                }
            ]
        )
        with (
            self.as_role(Roles.VERENIGINGEN_ADMIN),
            self._patch_service(),
            patch(
                "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.MollieSettings.get_mollie_client",
                return_value=FakeMollieClient(),
            ),
        ):
            result = page.create_bulk_payments(payload)
        self.assertEqual(result["results"][0]["status"], "error")
        self.assertEqual(result["results"][0]["error"], "Invalid amount")

    def test_create_bulk_payments_missing_charge_date_is_error(self):
        payload = json.dumps(
            [
                {
                    "customer_id": "cst_x",
                    "amount": 10.0,
                    "mandate_id": "mdt_1",
                    # charge_date absent
                }
            ]
        )
        with (
            self.as_role(Roles.VERENIGINGEN_ADMIN),
            self._patch_service(),
            patch(
                "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.MollieSettings.get_mollie_client",
                return_value=FakeMollieClient(),
            ),
        ):
            result = page.create_bulk_payments(payload)
        self.assertEqual(result["results"][0]["status"], "error")
        self.assertIn("Charge date is required", result["results"][0]["error"])

    # ------------------------------------------------------------------
    # create_bulk_payments - happy path
    # ------------------------------------------------------------------

    def test_create_bulk_payments_success_no_duplicate(self):
        """A fully-valid row with no duplicate subscription succeeds and returns the sub id."""
        charge_date = _future_date()
        payload = json.dumps(
            [
                {
                    "customer_id": "cst_happy",
                    "member_name": "Happy Member",
                    "amount": 12.5,
                    "charge_date": charge_date,
                    "description": "Membership payment",
                    "mandate_id": "mdt_valid",
                    "interval": "1 month",
                    "times": 1,
                }
            ]
        )
        FakeMollieService.create_subscription_return = {
            "status": "success",
            "subscription_id": "sub_x",
        }
        with (
            self.as_role(Roles.VERENIGINGEN_ADMIN),
            self._patch_service(),
            patch(
                "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.MollieSettings.get_mollie_client",
                return_value=FakeMollieClient(subscriptions=[]),
            ),
        ):
            result = page.create_bulk_payments(payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"]["success"], 1)
        self.assertEqual(result["summary"]["total_amount"], 12.5)
        self.assertEqual(result["results"][0]["status"], "success")
        self.assertEqual(result["results"][0]["payment_id"], "sub_x")

    def test_create_bulk_payments_skips_duplicate_subscription(self):
        """An existing active subscription with same date/amount is skipped, not re-created."""
        charge_date = _future_date()
        existing = SimpleNamespace(
            id="sub_existing",
            status="active",
            startDate=charge_date,
            amount={"value": "12.50", "currency": "EUR"},
        )
        payload = json.dumps(
            [
                {
                    "customer_id": "cst_dup",
                    "member_name": "Dup Member",
                    "amount": 12.5,
                    "charge_date": charge_date,
                    "description": "Membership payment",
                    "mandate_id": "mdt_valid",
                    "interval": "1 month",
                    "times": 1,
                }
            ]
        )
        with (
            self.as_role(Roles.VERENIGINGEN_ADMIN),
            self._patch_service(),
            patch(
                "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings.MollieSettings.get_mollie_client",
                return_value=FakeMollieClient(subscriptions=[existing]),
            ),
        ):
            result = page.create_bulk_payments(payload)
        self.assertEqual(result["summary"]["skipped"], 1)
        self.assertEqual(result["summary"]["success"], 0)
        self.assertEqual(result["results"][0]["status"], "skipped")
        self.assertEqual(result["results"][0]["payment_id"], "sub_existing")

    # ------------------------------------------------------------------
    # get_webhook_url
    # ------------------------------------------------------------------

    def test_get_webhook_url_contains_api_method_and_env(self):
        url = page.get_webhook_url()
        self.assertIn("/api/method/", url)
        self.assertIn("env=", url)
        self.assertTrue(url.split("env=")[-1] in ("test", "live"))
