"""
Coverage sweep for eboekhouden_rest_iterator.py

Target: verenigingen/e_boekhouden/utils/eboekhouden_rest_iterator.py

The iterator's value is the PARSING / ITERATION logic layered on top of the HTTP
transport (response unwrapping, amount-field preservation rules, pagination stop
conditions, consecutive-not-found cutoff, ID-range probing). We exercise that logic
deterministically by stubbing the EXTERNAL HTTP boundary only:

  * ``_request_with_retry`` -- the single seam to the eBoekhouden REST API. This is
    the external-service boundary (the same boundary test_http_client_mixin already
    stubs at the ``requests`` level), NOT Frappe business logic. We feed it canned
    ``requests.Response``-like objects so the iterator's own branching runs for real.

This mirrors the sibling ``test_http_client_mixin.py`` pattern: subclass the client,
inject a fake settings object, and drive responses through the transport seam.

OUT OF SCOPE (genuinely API-required / thin wrappers):
  * The whitelisted endpoints estimate_mutation_range / fetch_mutations_batch /
    fix_crediteuren_accounts -- they only instantiate the iterator (needs a live
    token) and forward to the methods covered here, or mutate live Accounts.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_rest_iterator_coverage
"""

import unittest
from unittest.mock import MagicMock

from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator


class FakeResponse:
    """Minimal stand-in for requests.Response carrying status + JSON body."""

    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _make_settings():
    settings = MagicMock()
    settings.api_url = "https://api.e-boekhouden.nl"
    settings.get_password.return_value = "test_api_token"
    settings.source_application = "Test"
    return settings


def _iterator(transport):
    """Build an iterator whose HTTP transport is replaced by ``transport``.

    ``transport`` is a callable(method, url, **kwargs) -> FakeResponse.
    """
    it = EBoekhoudenRESTIterator(settings=_make_settings())
    it._request_with_retry = transport  # stub external HTTP boundary only
    return it


class TestFetchMutationById(unittest.TestCase):
    def test_unwraps_first_item_from_wrapped_response(self):
        captured = {}

        def transport(method, url, params=None, **kw):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse(200, {"items": [{"id": 42, "amount": 10}]})

        it = _iterator(transport)
        result = it.fetch_mutation_by_id(42)

        self.assertEqual(result, {"id": 42, "amount": 10})
        # Correct endpoint + id filter were used.
        self.assertTrue(captured["url"].endswith("/v1/mutation"))
        self.assertEqual(captured["params"], {"id": 42})

    def test_empty_items_returns_none(self):
        it = _iterator(lambda *a, **k: FakeResponse(200, {"items": []}))
        self.assertIsNone(it.fetch_mutation_by_id(7))

    def test_non_dict_payload_returns_none(self):
        it = _iterator(lambda *a, **k: FakeResponse(200, [{"id": 1}]))
        self.assertIsNone(it.fetch_mutation_by_id(1))

    def test_404_returns_none_without_raising(self):
        it = _iterator(lambda *a, **k: FakeResponse(404, None))
        self.assertIsNone(it.fetch_mutation_by_id(999))

    def test_transport_exception_is_swallowed_to_none(self):
        def boom(*a, **k):
            raise RuntimeError("network down")

        it = _iterator(boom)
        # The method catches and logs, returning None (resilient bulk iteration).
        self.assertIsNone(it.fetch_mutation_by_id(5))


class TestFetchMutationDetail(unittest.TestCase):
    def test_returns_json_on_200(self):
        captured = {}

        def transport(method, url, **kw):
            captured["url"] = url
            return FakeResponse(200, {"id": 3, "type": 5})

        it = _iterator(transport)
        self.assertEqual(it.fetch_mutation_detail(3), {"id": 3, "type": 5})
        # Detail uses the /v1/mutation/<id> path.
        self.assertTrue(captured["url"].endswith("/v1/mutation/3"))

    def test_non_200_returns_none(self):
        it = _iterator(lambda *a, **k: FakeResponse(500, None))
        self.assertIsNone(it.fetch_mutation_detail(3))

    def test_exception_returns_none(self):
        def boom(*a, **k):
            raise ValueError("bad")

        self.assertIsNone(_iterator(boom).fetch_mutation_detail(3))


class TestFetchMutationsByType(unittest.TestCase):
    def test_paginates_then_stops_on_short_page(self):
        # Page 1 returns a full page (limit) of summaries -> continue.
        # Page 2 returns fewer than limit -> stop after it.
        pages = [
            FakeResponse(200, {"items": [{"id": 1}, {"id": 2}]}),
            FakeResponse(200, {"items": [{"id": 3}]}),
        ]
        details = {
            1: {"id": 1, "type": 5},
            2: {"id": 2, "type": 5},
            3: {"id": 3, "type": 5},
        }
        calls = {"n": 0}

        def transport(method, url, params=None, **kw):
            i = calls["n"]
            calls["n"] += 1
            return pages[i]

        it = _iterator(transport)
        it.fetch_mutation_detail = lambda mid: details.get(mid)

        result = it.fetch_mutations_by_type(mutation_type=5, limit=2)

        # All three details collected across both pages.
        self.assertEqual([m["id"] for m in result], [1, 2, 3])

    def test_amount_preserved_for_non_invoice_types(self):
        # Type 3 (payment): when detail lacks amount, the summary amount is copied in.
        page = FakeResponse(200, {"items": [{"id": 10, "amount": 99.5, "type": 3}]})
        # One full-ish page then an empty page to terminate pagination.
        responses = [page, FakeResponse(200, {"items": []})]
        seq = {"n": 0}

        def transport(method, url, params=None, **kw):
            r = responses[min(seq["n"], len(responses) - 1)]
            seq["n"] += 1
            return r

        it = _iterator(transport)
        it.fetch_mutation_detail = lambda mid: {"id": 10, "type": 3}  # no amount

        result = it.fetch_mutations_by_type(mutation_type=3, limit=500)
        self.assertEqual(len(result), 1)
        # Amount must be backfilled from the summary for type 3.
        self.assertEqual(result[0]["amount"], 99.5)

    def test_amount_NOT_copied_for_invoice_types_1_and_2(self):
        # Types 1 (PINV) and 2 (SINV) must NOT inherit the summary net amount,
        # because credit-note detection runs on line items, not the net total.
        responses = [
            FakeResponse(200, {"items": [{"id": 20, "amount": 250.0, "type": 2}]}),
            FakeResponse(200, {"items": []}),
        ]
        seq = {"n": 0}

        def transport(method, url, params=None, **kw):
            r = responses[min(seq["n"], len(responses) - 1)]
            seq["n"] += 1
            return r

        it = _iterator(transport)
        it.fetch_mutation_detail = lambda mid: {"id": 20, "type": 2}  # no amount

        result = it.fetch_mutations_by_type(mutation_type=2, limit=500)
        self.assertEqual(len(result), 1)
        # The summary amount must stay OUT of the type-2 detail.
        self.assertNotIn("amount", result[0])

    def test_unexpected_format_breaks_with_empty_result(self):
        # A non-wrapped (list) response is unexpected -> log + break, empty result.
        it = _iterator(lambda *a, **k: FakeResponse(200, [{"id": 1}]))
        self.assertEqual(it.fetch_mutations_by_type(mutation_type=5), [])

    def test_non_200_breaks_with_empty_result(self):
        it = _iterator(lambda *a, **k: FakeResponse(503, None))
        self.assertEqual(it.fetch_mutations_by_type(mutation_type=5), [])

    def test_progress_callback_invoked(self):
        responses = [
            FakeResponse(200, {"items": [{"id": 1, "type": 3}]}),
            FakeResponse(200, {"items": []}),
        ]
        seq = {"n": 0}

        def transport(method, url, params=None, **kw):
            r = responses[min(seq["n"], len(responses) - 1)]
            seq["n"] += 1
            return r

        it = _iterator(transport)
        it.fetch_mutation_detail = lambda mid: {"id": 1, "type": 3}
        seen = []
        it.fetch_mutations_by_type(mutation_type=3, limit=500, progress_callback=seen.append)
        self.assertTrue(seen)
        self.assertEqual(seen[0]["mutation_type"], 3)
        self.assertEqual(seen[0]["total_fetched"], 1)


class TestFetchAllMutationsByRange(unittest.TestCase):
    def test_collects_details_over_range(self):
        # For each id, list-endpoint returns a matching summary, detail returns full.
        it = _iterator(lambda *a, **k: FakeResponse(200, {"items": []}))
        store = {1: {"id": 1, "amount": 5}, 2: {"id": 2, "amount": 6}, 3: {"id": 3, "amount": 7}}
        it.fetch_mutation_by_id = lambda mid: store.get(mid)
        it.fetch_mutation_detail = lambda mid: store.get(mid)

        result = it.fetch_all_mutations_by_range(1, 3)
        self.assertEqual(sorted(m["id"] for m in result), [1, 2, 3])

    def test_amount_backfilled_from_summary_when_detail_missing_it(self):
        it = _iterator(lambda *a, **k: FakeResponse(200, {"items": []}))
        # Summary carries amount; detail (same id) lacks it -> backfill.
        it.fetch_mutation_by_id = lambda mid: {"id": mid, "amount": 42.0}
        it.fetch_mutation_detail = lambda mid: {"id": mid}  # no amount

        result = it.fetch_all_mutations_by_range(1, 1)
        self.assertEqual(result[0]["amount"], 42.0)

    def test_consecutive_not_found_stops_early(self):
        # Everything is "not found"; the range is large but the loop must abort
        # after max_consecutive_not_found (100) probes, not walk the whole span.
        calls = {"n": 0}

        def fetch_by_id(mid):
            calls["n"] += 1
            return None

        it = _iterator(lambda *a, **k: FakeResponse(200, {"items": []}))
        it.fetch_mutation_by_id = fetch_by_id
        it.fetch_mutation_detail = lambda mid: None

        result = it.fetch_all_mutations_by_range(1, 100000)
        self.assertEqual(result, [])
        # Must have stopped at the 100-consecutive-miss cutoff, far short of 100k.
        self.assertLessEqual(calls["n"], 101)


class TestEstimateIdRange(unittest.TestCase):
    def test_no_mutations_found_reports_failure_defaults(self):
        it = _iterator(lambda *a, **k: FakeResponse(404, None))
        it.fetch_mutation_detail = lambda mid: None
        out = it.estimate_id_range()
        self.assertFalse(out["success"])
        self.assertEqual(out["lowest_id"], 1)
        self.assertEqual(out["highest_id"], 10000)
        self.assertTrue(out["estimated"])

    def test_finds_bounds_from_present_ids(self):
        # Only ids 100..130 exist (in 10-steps). estimate must bracket them.
        present = set(range(100, 131))

        it = _iterator(lambda *a, **k: FakeResponse(404, None))
        it.fetch_mutation_detail = lambda mid: {"id": mid} if mid in present else None

        out = it.estimate_id_range()
        self.assertTrue(out["success"])
        # Lowest found should be 100 (a probe point); highest extends via the
        # forward search to the last present id reachable in 10-steps.
        self.assertEqual(out["lowest_id"], 100)
        self.assertGreaterEqual(out["highest_id"], 100)
        self.assertLessEqual(out["highest_id"], 140)

    def test_mutation_zero_detected_as_lowest(self):
        # Opening balances live at id 0; estimate explicitly probes 0 first.
        it = _iterator(lambda *a, **k: FakeResponse(404, None))
        it.fetch_mutation_detail = lambda mid: {"id": mid} if mid == 0 else None
        out = it.estimate_id_range()
        self.assertTrue(out["success"])
        self.assertEqual(out["lowest_id"], 0)


if __name__ == "__main__":
    unittest.main()
