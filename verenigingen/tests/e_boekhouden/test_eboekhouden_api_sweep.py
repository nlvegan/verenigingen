"""
Supplementary real-logic coverage for
``verenigingen/e_boekhouden/utils/eboekhouden_api.py``.

This module complements ``test_eboekhouden_api_client.py`` by filling the gaps it
leaves: the ``_paginated_fetch`` safety-limit guard, the thin pagination wrappers
``get_cost_centers`` / ``get_invoices`` / ``get_mutations`` (endpoint routing,
safety-limit contract, and their exception handling), and the
``check_api_relation_data`` diagnostic (data-quality maths + failure/error arms).

Only the HTTP boundary is mocked (``EBoekhoudenAPI.make_request`` -- the eBoekhouden
REST server) or, where the wrapper-to-_paginated_fetch contract is the thing under
test, ``_paginated_fetch`` is captured. The logic being asserted always runs for
real. The fixtures ``_FakeSettings`` / ``_make_api`` mirror the sibling test file.

Run with:
    cd /home/frappeuser/frappe-bench && bench --site veg11.veganisme.org run-tests \\
        --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_eboekhouden_api_sweep
"""

import json
from unittest.mock import patch

from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI
from verenigingen.tests.e_boekhouden.test_eboekhouden_api_client import _FakeSettings, _make_api
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaginatedFetchSafetyLimit(EnhancedTestCase):
    """The pagination loop must stop at safety_limit even if pages never shrink."""

    def test_safety_limit_breaks_unbounded_pagination(self):
        """When every page is full (== limit), the loop stops once offset exceeds
        safety_limit and logs a safety-limit error rather than looping forever."""
        api = _make_api()
        full_page = json.dumps({"items": [{"id": i} for i in range(500)]})

        calls = {"n": 0}

        def always_full(endpoint, method, params):
            calls["n"] += 1
            # Each page is full (500 == limit), so len(items) < limit never trips.
            return {"success": True, "data": full_page}

        with patch.object(api, "make_request", side_effect=always_full), patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_api.frappe.log_error"
        ) as mock_log:
            # safety_limit=500: page1 offset->500 (not >500), page2 offset->1000 (>500) breaks.
            result = api._paginated_fetch("v1/test", safety_limit=500)

        self.assertTrue(result["success"])
        items = json.loads(result["data"])["items"]
        # Exactly two full pages were consumed before the guard fired.
        self.assertEqual(len(items), 1000)
        self.assertEqual(calls["n"], 2)
        mock_log.assert_called_once()
        self.assertIn("Safety limit reached", mock_log.call_args[0][0])

    def test_offset_advances_by_limit_each_page(self):
        """The loop feeds offset=0 then offset=500 (limit-sized strides)."""
        api = _make_api()
        full_page = json.dumps({"items": [{"id": i} for i in range(500)]})
        short_page = json.dumps({"items": [{"id": 9999}]})
        seen_offsets = []

        def fake(endpoint, method, params):
            seen_offsets.append(params["offset"])
            self.assertEqual(params["limit"], 500)
            return {"success": True, "data": full_page if len(seen_offsets) == 1 else short_page}

        with patch.object(api, "make_request", side_effect=fake):
            api._paginated_fetch("v1/test")

        self.assertEqual(seen_offsets, [0, 500])


class TestPaginationWrappers(EnhancedTestCase):
    """get_cost_centers / get_invoices / get_mutations: endpoint, safety-limit, errors."""

    # -- endpoint routing (real _paginated_fetch, mocked HTTP boundary) ----------
    def _capture_endpoint(self, accessor_name, *args):
        api = _make_api()
        captured = {}

        def fake(endpoint, method, params):
            captured["endpoint"] = endpoint
            return {"success": True, "data": json.dumps({"items": []})}

        with patch.object(api, "make_request", side_effect=fake):
            getattr(api, accessor_name)(*args)
        return captured["endpoint"]

    def test_get_cost_centers_hits_costcenter_endpoint(self):
        self.assertEqual(self._capture_endpoint("get_cost_centers"), "v1/costcenter")

    def test_get_invoices_hits_invoice_endpoint(self):
        self.assertEqual(self._capture_endpoint("get_invoices"), "v1/invoice")

    def test_get_mutations_hits_mutation_endpoint(self):
        self.assertEqual(self._capture_endpoint("get_mutations"), "v1/mutation")

    # -- safety-limit contract (capture the _paginated_fetch call) ---------------
    def _capture_safety_limit(self, accessor_name, *args):
        api = _make_api()
        captured = {}

        def fake(endpoint, params=None, safety_limit=10000):
            captured["endpoint"] = endpoint
            captured["safety_limit"] = safety_limit
            return {"success": True, "data": json.dumps({"items": []})}

        with patch.object(api, "_paginated_fetch", side_effect=fake):
            getattr(api, accessor_name)(*args)
        return captured

    def test_get_invoices_uses_large_safety_limit(self):
        """Invoices can be voluminous -> the wrapper raises the guard to 50000."""
        self.assertEqual(self._capture_safety_limit("get_invoices")["safety_limit"], 50000)

    def test_get_mutations_uses_large_safety_limit(self):
        """Mutations likewise use the 50000 guard."""
        self.assertEqual(self._capture_safety_limit("get_mutations")["safety_limit"], 50000)

    def test_get_cost_centers_uses_default_safety_limit(self):
        """Cost centers are few -> the default 10000 guard is left in place."""
        self.assertEqual(self._capture_safety_limit("get_cost_centers")["safety_limit"], 10000)

    # -- exception handling (the except arm of each wrapper) ---------------------
    def _assert_wrapper_swallows_exception(self, accessor_name, *args):
        api = _make_api()
        with patch.object(api, "make_request", side_effect=RuntimeError("network down")), patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_api.frappe.log_error"
        ) as mock_log:
            result = getattr(api, accessor_name)(*args)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "network down")
        mock_log.assert_called_once()
        return result

    def test_get_cost_centers_handles_exception(self):
        self._assert_wrapper_swallows_exception("get_cost_centers")

    def test_get_invoices_handles_exception(self):
        self._assert_wrapper_swallows_exception("get_invoices")

    def test_get_mutations_handles_exception(self):
        self._assert_wrapper_swallows_exception("get_mutations")

    def test_get_chart_of_accounts_handles_exception(self):
        self._assert_wrapper_swallows_exception("get_chart_of_accounts")

    def test_get_relations_handles_exception(self):
        self._assert_wrapper_swallows_exception("get_relations")


class TestCheckApiRelationData(EnhancedTestCase):
    """check_api_relation_data analyses customer-name data quality."""

    def setUp(self):
        super().setUp()
        # The diagnostic builds EBoekhoudenAPI(frappe.get_single(...)). Patch the
        # single lookup so a real client is constructed without a live token.
        self._single_patch = patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_api.frappe.get_single",
            return_value=_FakeSettings(),
        )
        self._single_patch.start()
        self.addCleanup(self._single_patch.stop)

    def test_data_quality_percentage_and_shape(self):
        """meaningful_names counts rows with any name field; percentage is /total."""
        from verenigingen.e_boekhouden.utils.eboekhouden_api import check_api_relation_data

        customers = [
            {"name": "Alice"},
            {"companyName": "ACME BV"},
            {"contactName": "Bob"},
            {"name": "", "companyName": "", "contactName": ""},  # blank -> not meaningful
        ]
        canned = {"success": True, "data": json.dumps({"items": customers})}
        with patch.object(EBoekhoudenAPI, "get_customers", return_value=canned):
            result = check_api_relation_data()

        rest = result["rest_api"]
        self.assertEqual(rest["status"], "success")
        self.assertEqual(rest["total_count"], 4)
        self.assertEqual(rest["meaningful_names"], 3)
        self.assertEqual(rest["meaningful_percentage"], 75.0)
        # Only the first 3 relations are echoed back for comparison.
        self.assertEqual(len(rest["relations"]), 3)
        self.assertTrue(result["summary"]["rest_api_working"])
        self.assertEqual(
            result["summary"]["recommendation"], "REST API working with good data quality"
        )

    def test_failed_customer_call_reports_failed_status(self):
        """A failed client call surfaces as status='failed' with the error + a
        connection-failed recommendation."""
        from verenigingen.e_boekhouden.utils.eboekhouden_api import check_api_relation_data

        with patch.object(
            EBoekhoudenAPI, "get_customers", return_value={"success": False, "error": "bad token"}
        ):
            result = check_api_relation_data()

        self.assertEqual(result["rest_api"]["status"], "failed")
        self.assertEqual(result["rest_api"]["error"], "bad token")
        self.assertFalse(result["summary"]["rest_api_working"])
        self.assertEqual(
            result["summary"]["recommendation"],
            "REST API connection failed - check credentials",
        )

    def test_exception_reports_error_status(self):
        """An unexpected exception is captured as status='error' (not raised)."""
        from verenigingen.e_boekhouden.utils.eboekhouden_api import check_api_relation_data

        with patch.object(
            EBoekhoudenAPI, "get_customers", side_effect=RuntimeError("kaboom")
        ):
            result = check_api_relation_data()

        self.assertEqual(result["rest_api"]["status"], "error")
        self.assertEqual(result["rest_api"]["error"], "kaboom")
        self.assertFalse(result["summary"]["rest_api_working"])

    def test_zero_customers_avoids_division_by_zero(self):
        """An empty customer list yields meaningful_percentage 0 (no ZeroDivision)."""
        from verenigingen.e_boekhouden.utils.eboekhouden_api import check_api_relation_data

        canned = {"success": True, "data": json.dumps({"items": []})}
        with patch.object(EBoekhoudenAPI, "get_customers", return_value=canned):
            result = check_api_relation_data()

        self.assertEqual(result["rest_api"]["status"], "success")
        self.assertEqual(result["rest_api"]["total_count"], 0)
        self.assertEqual(result["rest_api"]["meaningful_percentage"], 0)
