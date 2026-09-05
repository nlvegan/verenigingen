"""
Coverage sweep for MollieBaseClient (mollie_base_client.py)

Targets paths NOT covered by core/test_response_parsing.py:
- request() success + HTTP error-status -> exception mapping
- _handle_api_error error-detail extraction
- _validate_request_data (amount / currency / IBAN validation)
- _validate_response (settlement hard-fail, payment soft-warning)
- _request_paginated (multi-page cursor following, _embedded / data / single)
- _filter_by_date (string + datetime dates, naive/aware, invalid skip)
- _validate_financial_fields (strict raise vs non-strict warn)
- caching helpers (get_cached hit/miss/force_refresh, invalidate, clear, metrics)

The ONLY mock boundary is the HTTP transport: self.client.http_client.request.
Everything inside MollieBaseClient runs for real.
"""

import unittest
from datetime import datetime
from typing import Any, Dict, Optional
from unittest.mock import patch

import frappe
import requests
from frappe.test_runner import make_test_records

from verenigingen.verenigingen_payments.core.models.base import BaseModel
from verenigingen.verenigingen_payments.core.mollie_base_client import (
    MollieAPIError,
    MollieBaseClient,
    ResponseValidationError,
)


class _SweepModel(BaseModel):
    """Trivial model for parse paths."""

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        self.id: Optional[str] = None
        super().__init__(data)


class TestMollieBaseClientSweep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        # frappe.db.exists(dt, dt) is unconditionally truthy for a Single
        # (#889); check whether it has actually been saved instead.
        if not frappe.db.get_singles_dict("Mollie Settings"):
            make_test_records("Mollie Settings")

    def setUp(self):
        frappe.set_user("Administrator")
        self.client = MollieBaseClient(use_backend_api=False)

    def tearDown(self):
        frappe.db.rollback()

    def _patch_transport(self, return_value=None, side_effect=None):
        """Patch the HTTP transport boundary only."""
        m = patch.object(self.client.http_client, "request")
        mock = m.start()
        self.addCleanup(m.stop)
        if side_effect is not None:
            mock.side_effect = side_effect
        else:
            mock.return_value = return_value
        return mock

    # ====================
    # request() success
    # ====================

    def test_request_success_returns_response_body(self):
        body = {"resource": "payment", "id": "tr_123"}
        mock = self._patch_transport(return_value=(body, 200))

        result = self.client.request("GET", "payments/tr_123")

        self.assertEqual(result, body)
        mock.assert_called_once()
        # GET helper passes through to request()
        self.assertEqual(mock.call_args.kwargs["method"], "GET")

    def test_get_post_patch_delete_dispatch(self):
        mock = self._patch_transport(return_value=({"ok": True}, 200))

        self.client.get("things")
        self.client.post("things", {"a": 1})
        self.client.patch("things/1", {"b": 2})
        self.client.delete("things/1")

        methods = [c.kwargs["method"] for c in mock.call_args_list]
        self.assertEqual(methods, ["GET", "POST", "PATCH", "DELETE"])

    # ====================
    # request() HTTP error -> exception mapping (via _handle_api_error)
    # ====================

    def test_request_401_raises_authentication_error(self):
        self._patch_transport(return_value=({"detail": "bad key"}, 401))
        with self.assertRaises(frappe.AuthenticationError):
            self.client.request("GET", "balances")

    def test_request_403_raises_permission_error(self):
        self._patch_transport(return_value=({"detail": "nope"}, 403))
        with self.assertRaises(frappe.PermissionError):
            self.client.request("GET", "balances")

    def test_request_404_raises_does_not_exist(self):
        self._patch_transport(return_value=({"detail": "gone"}, 404))
        with self.assertRaises(frappe.DoesNotExistError):
            self.client.request("GET", "settlements/stl_x")

    def test_request_422_raises_validation_error_with_message(self):
        self._patch_transport(return_value=({"detail": "amount invalid"}, 422))
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.client.request("GET", "payments")
        self.assertIn("amount invalid", str(ctx.exception))

    def test_request_429_raises_rate_limit(self):
        self._patch_transport(return_value=({"detail": "slow down"}, 429))
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.client.request("GET", "payments")
        self.assertIn("Rate limit exceeded", str(ctx.exception))

    def test_request_500_raises_with_message(self):
        self._patch_transport(return_value=({"detail": "boom"}, 503))
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.client.request("GET", "payments")
        self.assertIn("boom", str(ctx.exception))

    def test_request_generic_4xx_raises_mollie_api_error(self):
        body = {
            "detail": "I'm a teapot",
            "type": "teapot_error",
            "field": "kettle",
            "_links": {"documentation": {"href": "https://docs/x"}},
        }
        self._patch_transport(return_value=(body, 418))
        with self.assertRaises(MollieAPIError) as ctx:
            self.client.request("GET", "payments")
        err = ctx.exception
        self.assertEqual(err.status_code, 418)
        self.assertEqual(err.error_code, "teapot_error")
        self.assertEqual(err.details["field"], "kettle")
        self.assertEqual(err.details["documentation"], "https://docs/x")
        self.assertIn("teapot", str(err))

    def test_request_connection_error_propagates(self):
        self._patch_transport(side_effect=requests.ConnectionError("network down"))
        with self.assertRaises(requests.ConnectionError):
            self.client.request("GET", "payments")

    # ====================
    # _handle_api_error message precedence
    # ====================

    def test_handle_api_error_title_when_no_detail(self):
        with self.assertRaises(MollieAPIError) as ctx:
            self.client._handle_api_error({"title": "Bad Request"}, 418)
        self.assertIn("Bad Request", str(ctx.exception))

    def test_handle_api_error_message_when_no_detail_or_title(self):
        with self.assertRaises(MollieAPIError) as ctx:
            self.client._handle_api_error({"message": "msg-only"}, 418)
        self.assertIn("msg-only", str(ctx.exception))

    def test_handle_api_error_none_response_unknown_error(self):
        with self.assertRaises(MollieAPIError) as ctx:
            self.client._handle_api_error(None, 418)
        self.assertIn("Unknown API error", str(ctx.exception))

    # ====================
    # _validate_request_data
    # ====================

    def test_validate_request_data_invalid_amount_value(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.client._validate_request_data(
                "payments", {"amount": {"value": "not-a-number", "currency": "EUR"}}
            )
        self.assertIn("Invalid amount", str(ctx.exception))

    def test_validate_request_data_invalid_currency(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.client._validate_request_data("payments", {"amount": {"value": "10.00", "currency": "ZZZ"}})
        self.assertIn("Invalid currency", str(ctx.exception))

    def test_validate_request_data_invalid_iban(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.client._validate_request_data("payments", {"iban": "INVALID-IBAN"})
        self.assertIn("Invalid IBAN", str(ctx.exception))

    def test_validate_request_data_valid_passes(self):
        # Should not raise
        self.client._validate_request_data("payments", {"amount": {"value": "10.00", "currency": "EUR"}})

    # ====================
    # _validate_response resource validation
    # ====================

    def test_validate_response_settlement_invalid_raises(self):
        # Settlement missing id + below-minimum amount -> validator invalid -> hard fail
        bad_settlement = {"resource": "settlement", "amount": {"value": "-5.00", "currency": "EUR"}}
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.client._validate_response(bad_settlement, 200)
        self.assertIn("Settlement validation failed", str(ctx.exception))

    def test_validate_response_payment_warning_does_not_raise(self):
        # Payment validation warnings -> msgprint, not raise
        bad_payment = {"resource": "payment", "id": "tr_bad"}
        with patch("frappe.msgprint") as mock_msg:
            self.client._validate_response(bad_payment, 200)
            # warnings should have been surfaced via msgprint (validator found issues)
            self.assertTrue(mock_msg.called)

    # ====================
    # _request_paginated
    # ====================

    def test_paginated_follows_next_cursor_across_pages(self):
        page1 = (
            {
                "_embedded": {"payments": [{"id": "tr_1"}, {"id": "tr_2"}]},
                "_links": {"next": {"href": "https://api.mollie.com/v2/payments?from=tr_3&limit=250"}},
            },
            200,
        )
        page2 = (
            {
                "_embedded": {"payments": [{"id": "tr_3"}]},
                "_links": {"next": None},
            },
            200,
        )
        mock = self._patch_transport(side_effect=[page1, page2])

        result = self.client.request("GET", "payments", paginated=True)

        self.assertEqual([i["id"] for i in result], ["tr_1", "tr_2", "tr_3"])
        self.assertEqual(mock.call_count, 2)
        # Second call should carry the extracted cursor
        self.assertEqual(mock.call_args_list[1].kwargs["params"]["from"], "tr_3")

    def test_paginated_data_key_collection(self):
        page = ({"data": [{"id": "a"}, {"id": "b"}], "_links": {}}, 200)
        self._patch_transport(side_effect=[page])
        result = self.client.request("GET", "things", paginated=True)
        self.assertEqual(len(result), 2)

    def test_paginated_single_item_response_stops(self):
        page = ({"resource": "payment", "id": "tr_solo"}, 200)
        self._patch_transport(side_effect=[page])
        result = self.client.request("GET", "payments/tr_solo", paginated=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "tr_solo")

    def test_paginated_error_status_raises(self):
        self._patch_transport(side_effect=[({"detail": "nope"}, 404)])
        with self.assertRaises(frappe.DoesNotExistError):
            self.client.request("GET", "payments", paginated=True)

    # ====================
    # _filter_by_date
    # ====================

    def test_filter_by_date_no_bounds_returns_original(self):
        items = [{"created_at": "2025-01-15T10:00:00Z"}]
        self.assertIs(self.client._filter_by_date(items), items)

    def test_filter_by_date_string_dates_inclusive_bounds(self):
        items = [
            {"created_at": "2025-01-10T10:00:00Z"},  # before from -> excluded
            {"created_at": "2025-01-15T23:00:00Z"},  # boundary from -> included
            {"created_at": "2025-01-20T10:00:00Z"},  # boundary until -> included
            {"created_at": "2025-01-31T00:00:00Z"},  # after until -> excluded
        ]
        result = self.client._filter_by_date(
            items,
            from_date=datetime(2025, 1, 15),
            until_date=datetime(2025, 1, 20),
        )
        dates = [i["created_at"] for i in result]
        self.assertIn("2025-01-15T23:00:00Z", dates)
        self.assertIn("2025-01-20T10:00:00Z", dates)
        self.assertNotIn("2025-01-10T10:00:00Z", dates)
        self.assertNotIn("2025-01-31T00:00:00Z", dates)

    def test_filter_by_date_object_attribute(self):
        class _Item:
            def __init__(self, dt):
                self.created_at = dt

        items = [_Item(datetime(2025, 6, 1)), _Item(datetime(2025, 7, 1))]
        result = self.client._filter_by_date(items, from_date=datetime(2025, 6, 15))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].created_at, datetime(2025, 7, 1))

    def test_filter_by_date_invalid_string_skipped(self):
        items = [
            {"created_at": "not-a-date"},
            {"created_at": "2025-06-01T00:00:00Z"},
        ]
        result = self.client._filter_by_date(items, from_date=datetime(2025, 1, 1))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["created_at"], "2025-06-01T00:00:00Z")

    def test_filter_by_date_missing_field_skipped(self):
        items = [{"other": "x"}, {"created_at": "2025-06-01T00:00:00Z"}]
        result = self.client._filter_by_date(items, from_date=datetime(2025, 1, 1))
        self.assertEqual(len(result), 1)

    # ====================
    # _validate_financial_fields
    # ====================

    # Regression guard for a fixed bug: the callsites at
    # mollie_base_client.py:1080,1088,1094,1105,1116 raise
    # `ResponseValidationError(msg, original_response=response)`, but the
    # ResponseValidationError class used to be a bare `pass` subclass of
    # frappe.ValidationError that accepted NO keyword args -- so in strict mode
    # (the DEFAULT) any malformed financial field raised
    # TypeError("ResponseValidationError() takes no keyword arguments") instead
    # of the intended ResponseValidationError. Fixed by giving the class an
    # __init__(message, original_response=None) like ResponseParsingError.
    def test_financial_fields_strict_raises_on_non_dict(self):
        self.client.strict_financial_validation = True
        with self.assertRaises(ResponseValidationError):
            self.client._validate_financial_fields({"amount": "10.00"}, _SweepModel)

    def test_financial_fields_strict_raises_on_missing_currency(self):
        self.client.strict_financial_validation = True
        with self.assertRaises(ResponseValidationError):
            self.client._validate_financial_fields({"amount": {"value": "10.00"}}, _SweepModel)

    def test_financial_fields_strict_raises_on_bad_currency_format(self):
        self.client.strict_financial_validation = True
        with self.assertRaises(ResponseValidationError):
            self.client._validate_financial_fields(
                {"amount": {"value": "10.00", "currency": "EURO"}}, _SweepModel
            )

    def test_financial_fields_strict_raises_on_non_string_value(self):
        self.client.strict_financial_validation = True
        with self.assertRaises(ResponseValidationError):
            self.client._validate_financial_fields(
                {"amount": {"value": 10.0, "currency": "EUR"}}, _SweepModel
            )

    def test_financial_fields_validation_error_carries_original_response(self):
        # The fix must preserve the original_response kwarg the callsites pass.
        self.client.strict_financial_validation = True
        bad = {"amount": "10.00"}
        with self.assertRaises(ResponseValidationError) as ctx:
            self.client._validate_financial_fields(bad, _SweepModel)
        self.assertEqual(ctx.exception.original_response, bad)

    def test_financial_fields_non_strict_warns_only(self):
        self.client.strict_financial_validation = False
        # Should NOT raise even with malformed data
        self.client._validate_financial_fields({"amount": "10.00"}, _SweepModel)

    def test_financial_fields_valid_amount_passes(self):
        self.client.strict_financial_validation = True
        # Should not raise
        self.client._validate_financial_fields({"amount": {"value": "10.00", "currency": "EUR"}}, _SweepModel)

    def test_financial_fields_none_amount_skipped(self):
        self.client.strict_financial_validation = True
        # None amount is valid (optional) -> no raise
        self.client._validate_financial_fields({"amount": None}, _SweepModel)

    # ====================
    # Caching helpers
    # ====================

    def test_get_cached_miss_then_hit(self):
        body = ({"resource": "balance", "id": "bal_1"}, 200)
        mock = self._patch_transport(side_effect=[body])

        first = self.client.get_cached("balances/bal_1")
        second = self.client.get_cached("balances/bal_1")

        self.assertEqual(first, second)
        # transport called once -> second served from cache
        self.assertEqual(mock.call_count, 1)

    def test_get_cached_force_refresh_bypasses_cache(self):
        mock = self._patch_transport(side_effect=[({"id": "v1"}, 200), ({"id": "v2"}, 200)])
        self.client.get_cached("balances/bal_1")
        refreshed = self.client.get_cached("balances/bal_1", force_refresh=True)
        self.assertEqual(refreshed["id"], "v2")
        self.assertEqual(mock.call_count, 2)

    def test_invalidate_cache_forces_refetch(self):
        mock = self._patch_transport(side_effect=[({"id": "v1"}, 200), ({"id": "v2"}, 200)])
        self.client.get_cached("balances/bal_1")
        invalidated = self.client.invalidate_cache("balances/bal_1")
        self.assertGreaterEqual(invalidated, 1)
        after = self.client.get_cached("balances/bal_1")
        self.assertEqual(after["id"], "v2")
        self.assertEqual(mock.call_count, 2)

    def test_clear_cache_then_refetch(self):
        mock = self._patch_transport(side_effect=[({"id": "v1"}, 200), ({"id": "v2"}, 200)])
        self.client.get_cached("balances/bal_1")
        self.client.clear_cache()
        after = self.client.get_cached("balances/bal_1")
        self.assertEqual(after["id"], "v2")
        self.assertEqual(mock.call_count, 2)

    def test_get_metrics_includes_cache_section(self):
        # Patch the transport's get_metrics (its own internals are out of scope
        # for this file); assert MollieBaseClient.get_metrics merges cache stats in.
        with patch.object(self.client.http_client, "get_metrics", return_value={"total_requests": 0}):
            metrics = self.client.get_metrics()
        self.assertIn("cache", metrics)
        self.assertIn("total_requests", metrics)

    def test_get_cached_disabled_bypasses_cache(self):
        no_cache = MollieBaseClient(use_backend_api=False, enable_cache=False)
        m = patch.object(no_cache.http_client, "request")
        mock = m.start()
        self.addCleanup(m.stop)
        mock.side_effect = [({"id": "a"}, 200), ({"id": "b"}, 200)]
        self.assertEqual(no_cache.get_cached("x")["id"], "a")
        self.assertEqual(no_cache.get_cached("x")["id"], "b")
        self.assertEqual(no_cache.invalidate_cache("x"), 0)
        self.assertEqual(no_cache.cleanup_expired_cache(), 0)


if __name__ == "__main__":
    unittest.main()
