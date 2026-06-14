"""
Unit coverage for the Mollie Subscription Recreation admin tool — no Mollie key,
no network. Runs in CI.

verenigingen/templates/pages/mollie_subscription_recreation.py is real operational
code (a CSV-driven tool that cancels and recreates broken Mollie subscriptions with
corrected next-invoice dates). The bulk of its logic is pure and side-effect-free
and is tested here directly:

- parse_amount_string        : tolerant amount parsing across Mollie's formats
- sanitize_csv_field         : CSV-injection guard (formula-prefix escaping)
- sanitize_description       : None/blank -> default; trims
- generate_unique_description: suffix / timestamp uniqueness
- retry_api_call             : exponential-backoff retry wrapper
- has_admin_access           : role gate
- get_context                : permission throw + context assembly

The whitelisted endpoints (parse_and_validate_csv / recreate_subscriptions /
export_subscriptions_from_customers) reach Mollie through MollieDebugService. Their
pure early-exit paths (CSV size limits, missing columns, malformed dates, empty
payloads, base64 limits) are tested without any Mollie call; the validation-with-
Mollie path is exercised with the SERVICE BOUNDARY ONLY mocked (debug_subscription /
debug_mandate / debug_customer) — every line of the endpoint's own parsing,
branching and result-assembly logic runs for real.

Mocking note: MollieDebugService is the thin wrapper over the Mollie HTTP SDK; it is
the external boundary, not app business logic, so patching it is the same boundary the
test-quality policy permits for Mollie. Hence the *_unit.py name.
"""

import base64
import json
from unittest.mock import patch

import frappe

from verenigingen.templates.pages import mollie_subscription_recreation as msr
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

_SERVICE = "verenigingen.templates.pages.mollie_subscription_recreation.MollieDebugService"


class TestRecreationPureHelpers(EnhancedTestCase):
    """The pure, deterministic helper functions — no Frappe state, no Mollie."""

    # --- parse_amount_string -------------------------------------------------

    def test_parse_amount_eur_suffix(self):
        self.assertEqual(msr.parse_amount_string("25.00 EUR"), 25.0)

    def test_parse_amount_plain_string(self):
        self.assertEqual(msr.parse_amount_string("25.00"), 25.0)

    def test_parse_amount_float(self):
        self.assertEqual(msr.parse_amount_string(25.0), 25.0)

    def test_parse_amount_none_is_zero(self):
        self.assertEqual(msr.parse_amount_string(None), 0.0)

    def test_parse_amount_garbage_is_zero(self):
        self.assertEqual(msr.parse_amount_string("not-a-number"), 0.0)

    def test_parse_amount_empty_string_is_zero(self):
        self.assertEqual(msr.parse_amount_string(""), 0.0)

    # --- sanitize_csv_field --------------------------------------------------

    def test_sanitize_csv_escapes_formula_prefixes(self):
        for dangerous in ("=cmd", "+1", "-2", "@SUM", "\tx", "\rx"):
            escaped = msr.sanitize_csv_field(dangerous)
            self.assertTrue(escaped.startswith("'"), f"{dangerous!r} not escaped")

    def test_sanitize_csv_leaves_safe_value(self):
        self.assertEqual(msr.sanitize_csv_field("Monthly dues"), "Monthly dues")

    def test_sanitize_csv_empty_passthrough(self):
        self.assertEqual(msr.sanitize_csv_field(""), "")

    # --- sanitize_description ------------------------------------------------

    def test_sanitize_description_default_on_none(self):
        self.assertEqual(msr.sanitize_description(None), "Membership dues")

    def test_sanitize_description_default_on_blank(self):
        self.assertEqual(msr.sanitize_description("   "), "Membership dues")

    def test_sanitize_description_trims(self):
        self.assertEqual(msr.sanitize_description("  Annual fee  "), "Annual fee")

    # --- generate_unique_description -----------------------------------------

    def test_generate_unique_description_with_custom_suffix(self):
        self.assertEqual(msr.generate_unique_description("Dues", "renewal"), "Dues (renewal)")

    def test_generate_unique_description_defaults_to_timestamp(self):
        result = msr.generate_unique_description("Dues")
        self.assertTrue(result.startswith("Dues (updated "))
        self.assertTrue(result.endswith(")"))

    # --- retry_api_call ------------------------------------------------------

    def test_retry_api_call_returns_first_success(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            return "ok"

        self.assertEqual(msr.retry_api_call(fn, max_attempts=3), "ok")
        self.assertEqual(calls["n"], 1)

    def test_retry_api_call_retries_then_succeeds(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("transient")
            return "recovered"

        # backoff_factor 0 -> no real sleep delay (2**attempt * 0 == 0).
        self.assertEqual(msr.retry_api_call(fn, max_attempts=3, backoff_factor=0.0), "recovered")
        self.assertEqual(calls["n"], 3)

    def test_retry_api_call_raises_after_exhausting_attempts(self):
        def fn():
            raise ValueError("always fails")

        with self.assertRaises(ValueError):
            msr.retry_api_call(fn, max_attempts=2, backoff_factor=0.0)


class TestRecreationAccessAndContext(EnhancedTestCase):
    """Role gate + get_context, run as real users."""

    def setUp(self):
        super().setUp()
        # Real privileged (non-superuser) account: the tool is open to
        # Verenigingen Staff. Test the real role boundary, not the Administrator
        # superuser.
        self.privileged_user = self.create_test_user(
            f"msr-priv-{frappe.generate_hash(length=6)}@test.com", roles=["Verenigingen Staff"]
        )

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_has_admin_access_true_for_privileged_role(self):
        with self.set_user(self.privileged_user.name):
            self.assertTrue(msr.has_admin_access())

    def test_has_admin_access_false_for_guest(self):
        frappe.set_user("Guest")
        self.assertFalse(msr.has_admin_access())

    def test_get_context_throws_for_guest(self):
        frappe.set_user("Guest")
        context = frappe._dict()
        with self.assertRaises(frappe.PermissionError):
            msr.get_context(context)

    def test_get_context_populates_for_privileged_role(self):
        with self.set_user(self.privileged_user.name):
            context = frappe._dict()
            msr.get_context(context)
        self.assertEqual(context.no_cache, 1)
        self.assertTrue(context.show_sidebar)
        self.assertIn("Mollie", context.title)
        self.assertTrue(hasattr(context, "csrf_token"))
        # populate_mollie_context sets these.
        self.assertIn("mollie_configured", context)


class TestRecreationCSVValidationEarlyExits(EnhancedTestCase):
    """parse_and_validate_csv pure-Python guards (no Mollie call reached)."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_rejects_oversize_csv(self):
        huge = "x" * (msr.MAX_CSV_SIZE + 1)
        result = msr.parse_and_validate_csv(huge)
        self.assertEqual(result["status"], "error")
        self.assertIn("too large", result["error"])

    def test_rejects_missing_required_columns(self):
        result = msr.parse_and_validate_csv("foo,bar\n1,2\n")
        self.assertEqual(result["status"], "error")
        self.assertIn("Required columns", result["error"])

    def test_rejects_when_no_valid_rows(self):
        # Header present but rows lack both ids.
        result = msr.parse_and_validate_csv("customer_id,subscription_id\n,\n")
        self.assertEqual(result["status"], "error")
        self.assertIn("No valid rows", result["error"])

    def test_rejects_bad_global_date_format(self):
        csv = "customer_id,subscription_id\ncst_x,sub_y\n"
        result = msr.parse_and_validate_csv(csv, planned_next_invoice_date="01-01-2026")
        self.assertEqual(result["status"], "error")
        self.assertIn("date format", result["error"].lower())


class TestRecreationCSVValidationWithService(EnhancedTestCase):
    """The full parse_and_validate_csv path with only the Mollie SDK boundary mocked."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_valid_active_subscription_with_valid_mandate(self):
        csv = "customer_id,subscription_id\ncst_abc,sub_abc\n"
        with patch(_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.debug_subscription.return_value = {
                "subscription_data": {
                    "amount": "25.00 EUR",
                    "next_payment_date": "2026-02-01",
                    "status": "active",
                    "interval": "1 month",
                    "description": "Monthly dues",
                    "mandate_id": "mdt_abc",
                }
            }
            svc.debug_mandate.return_value = {"mandate_data": {"status": "valid"}}
            result = msr.parse_and_validate_csv(csv, skip_date_validation=True)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_rows"], 1)
        row = result["results"][0]
        self.assertEqual(row["status"], "valid")
        self.assertEqual(row["current_amount"], 25.0)
        self.assertTrue(row["mandate_valid"])

    def test_blocks_non_active_subscription(self):
        csv = "customer_id,subscription_id\ncst_abc,sub_abc\n"
        with patch(_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.debug_subscription.return_value = {
                "subscription_data": {
                    "amount": "25.00",
                    "status": "canceled",
                    "interval": "1 month",
                    "description": "Monthly",
                    "mandate_id": None,
                }
            }
            result = msr.parse_and_validate_csv(csv, skip_date_validation=True)

        row = result["results"][0]
        # A non-active subscription is blocked: status flips to "error" and the
        # current status is reported. (The endpoint computes an internal `errors`
        # list but only surfaces `warnings` + `status` in the row, so we assert on
        # what is actually returned.)
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["current_status"], "canceled")

    def test_warns_on_invalid_mandate(self):
        csv = "customer_id,subscription_id\ncst_abc,sub_abc\n"
        with patch(_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.debug_subscription.return_value = {
                "subscription_data": {
                    "amount": "25.00",
                    "status": "active",
                    "interval": "1 month",
                    "description": "Monthly",
                    "mandate_id": "mdt_bad",
                }
            }
            svc.debug_mandate.return_value = {"mandate_data": {"status": "invalid"}}
            result = msr.parse_and_validate_csv(csv, skip_date_validation=True)

        row = result["results"][0]
        self.assertEqual(row["status"], "warning")
        self.assertFalse(row["mandate_valid"])

    def test_csv_description_override_marks_changed(self):
        csv = "customer_id,subscription_id,description\ncst_abc,sub_abc,Brand new desc\n"
        with patch(_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.debug_subscription.return_value = {
                "subscription_data": {
                    "amount": "25.00",
                    "status": "active",
                    "interval": "1 month",
                    "description": "Old desc",
                    "mandate_id": "mdt_abc",
                }
            }
            svc.debug_mandate.return_value = {"mandate_data": {"status": "valid"}}
            result = msr.parse_and_validate_csv(csv, skip_date_validation=True)

        row = result["results"][0]
        self.assertTrue(row["description_changed"])
        self.assertEqual(row["planned_description"], "Brand new desc")

    def test_propagates_subscription_fetch_error(self):
        csv = "customer_id,subscription_id\ncst_abc,sub_missing\n"
        with patch(_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.debug_subscription.return_value = {"error": "Subscription not found"}
            result = msr.parse_and_validate_csv(csv, skip_date_validation=True)

        row = result["results"][0]
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["error"], "Subscription not found")


class TestRecreateSubscriptionsEarlyExits(EnhancedTestCase):
    """recreate_subscriptions payload-guard paths (base64 decode / size)."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_requires_payload(self):
        result = msr.recreate_subscriptions("")
        self.assertEqual(result["status"], "error")
        self.assertIn("required", result["error"].lower())

    def test_rejects_oversize_encoded_payload(self):
        # Larger than max_encoded_size (MAX_SUBSCRIPTIONS_PAYLOAD_SIZE * 1.4).
        oversize = "A" * (int(msr.MAX_SUBSCRIPTIONS_PAYLOAD_SIZE * 1.4) + 1)
        result = msr.recreate_subscriptions(oversize)
        self.assertEqual(result["status"], "error")
        self.assertIn("too large", result["error"].lower())

    def test_rejects_undecodable_base64(self):
        # Valid-length but not valid base64 of utf-8.
        result = msr.recreate_subscriptions("!!!!notbase64!!!!")
        self.assertEqual(result["status"], "error")
        self.assertIn("decode", result["error"].lower())

    def test_missing_interval_reports_per_row_error(self):
        payload = [
            {
                "customer_id": "cst_abc",
                "subscription_id": "sub_abc",
                "planned_amount": 25.0,
                "planned_next_invoice_date": "2026-02-01",
                # current_interval intentionally omitted
                "current_mandate_id": "mdt_abc",
                "mandate_valid": True,
            }
        ]
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        # No Mollie call should be reached: the missing-interval guard fires first,
        # but patch the service anyway so an accidental call can't hit the network.
        with patch(_SERVICE):
            result = msr.recreate_subscriptions(encoded)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"]["errors"], 1)
        self.assertIn("interval", result["results"][0]["error"].lower())


class TestExportSubscriptionsEarlyExits(EnhancedTestCase):
    """export_subscriptions_from_customers guard + assembly paths."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_rejects_missing_customer_id_column(self):
        result = msr.export_subscriptions_from_customers("foo\n1\n")
        self.assertEqual(result["status"], "error")
        self.assertIn("customer_id", result["error"])

    def test_warns_when_no_active_subscriptions(self):
        csv = "customer_id\ncst_abc\n"
        with patch(_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.debug_customer.return_value = {"subscriptions": []}
            result = msr.export_subscriptions_from_customers(csv)
        self.assertEqual(result["status"], "warning")
        self.assertIn("No active subscriptions", result["error"])

    def test_exports_active_subscription_rows(self):
        csv = "customer_id\ncst_abc\n"
        with patch(_SERVICE) as MockSvc:
            svc = MockSvc.return_value
            svc.debug_customer.return_value = {
                "subscriptions": [
                    {
                        "id": "sub_abc",
                        "status": "active",
                        "amount": "25.00 EUR",
                        "interval": "1 month",
                        "description": "Monthly dues",
                        "next_payment_date": "2026-02-01",
                        "mandate_id": "mdt_abc",
                    }
                ]
            }
            result = msr.export_subscriptions_from_customers(csv)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_count"], 1)
        self.assertIn("sub_abc", result["csv_content"])
        self.assertIn("25.00", result["csv_content"])
