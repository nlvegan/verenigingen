"""
Coverage sweep for eboekhouden_rest_client.py

Target: verenigingen/e_boekhouden/utils/eboekhouden_rest_client.py

Testable surface = the PARSING / PAGINATION / CACHING logic layered on top of the
HTTP transport. We stub only the external HTTP boundary (``_request_with_retry`` --
the single seam to the eBoekhouden REST API, exactly the boundary
test_http_client_mixin stubs at the ``requests`` level) and let the client's own
branching run for real:

  * get_mutations          -- wrapped/list payload handling, has_more, date filters
  * get_all_mutations      -- multi-page accumulation + early-error propagation
  * get_ledgers/get_relations + _fetch_and_cache_paginated -- pagination + cache
  * invalidate_*_cache     -- cache lifecycle (pure, no HTTP)

OUT OF SCOPE: count_all_mutations (whitelisted wrapper that instantiates a live
client) and get_mutation_detail's error-log path (thin transport wrapper).

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_rest_client_coverage
"""

import unittest
from unittest.mock import MagicMock

from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import EBoekhoudenRESTClient


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def _make_settings():
    settings = MagicMock()
    settings.api_url = "https://api.e-boekhouden.nl"
    settings.get_password.return_value = "test_api_token"
    settings.source_application = "Test"
    return settings


def _client(transport):
    c = EBoekhoudenRESTClient(settings=_make_settings())
    c._request_with_retry = transport  # stub external HTTP boundary only
    return c


class TestGetMutations(unittest.TestCase):
    def test_wrapped_items_payload(self):
        captured = {}

        def transport(method, url, params=None, **kw):
            captured["params"] = params
            return FakeResponse(200, {"items": [{"id": 1}, {"id": 2}], "count": 2})

        result = _client(transport).get_mutations(limit=2, offset=0)
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["mutations"]), 2)
        # Full page (len == limit) => has_more True.
        self.assertTrue(result["has_more"])

    def test_bare_list_payload(self):
        result = _client(lambda *a, **k: FakeResponse(200, [{"id": 1}])).get_mutations(limit=5)
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        # Partial page => no more pages.
        self.assertFalse(result["has_more"])

    def test_date_filters_passed_through(self):
        captured = {}

        def transport(method, url, params=None, **kw):
            captured["params"] = params
            return FakeResponse(200, {"items": []})

        _client(transport).get_mutations(date_from="2023-01-01", date_to="2023-12-31")
        self.assertEqual(captured["params"]["from"], "2023-01-01")
        self.assertEqual(captured["params"]["to"], "2023-12-31")

    def test_limit_capped_at_api_max(self):
        captured = {}

        def transport(method, url, params=None, **kw):
            captured["params"] = params
            return FakeResponse(200, {"items": []})

        _client(transport).get_mutations(limit=999999)
        self.assertEqual(captured["params"]["limit"], 2000)

    def test_non_200_returns_error(self):
        result = _client(lambda *a, **k: FakeResponse(404, None, text="nope")).get_mutations()
        self.assertFalse(result["success"])
        self.assertIn("404", result["error"])

    def test_transport_exception_returns_error_dict(self):
        def boom(*a, **k):
            raise RuntimeError("dead socket")

        result = _client(boom).get_mutations()
        self.assertFalse(result["success"])
        self.assertIn("dead socket", result["error"])


class TestGetAllMutations(unittest.TestCase):
    def test_accumulates_across_pages(self):
        # Page 1 full (2000 ids -> has_more), page 2 partial -> stop.
        page1 = {"items": [{"id": i} for i in range(2000)]}
        page2 = {"items": [{"id": 9999}]}
        seq = {"n": 0}

        def transport(method, url, params=None, **kw):
            n = seq["n"]
            seq["n"] += 1
            return FakeResponse(200, page1 if n == 0 else page2)

        result = _client(transport).get_all_mutations()
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 2001)

    def test_propagates_page_error(self):
        # If a page fails, get_all_mutations must surface that error verbatim.
        result = _client(lambda *a, **k: FakeResponse(500, None, text="boom")).get_all_mutations()
        self.assertFalse(result["success"])
        self.assertIn("500", result["error"])


class TestPaginatedCache(unittest.TestCase):
    def test_get_ledgers_paginates_and_caches(self):
        # First full page (2000) then a short page terminates pagination.
        page1 = [{"id": i} for i in range(2000)]
        page2 = [{"id": 5000}]
        seq = {"n": 0}

        def transport(method, url, params=None, **kw):
            n = seq["n"]
            seq["n"] += 1
            return FakeResponse(200, page1 if n == 0 else page2)

        client = _client(transport)
        result = client.get_ledgers()
        self.assertTrue(result["success"])
        self.assertEqual(len(result["ledgers"]), 2001)
        self.assertEqual(result["count"], 2001)

        # Second call must serve from cache: transport NOT invoked again.
        seq["n"] = 99  # if transport ran it would IndexError-ish; here it returns page2
        before = seq["n"]
        cached = client.get_ledgers()
        self.assertTrue(cached["success"])
        self.assertEqual(len(cached["ledgers"]), 2001)
        # Transport counter unchanged => cache hit.
        self.assertEqual(seq["n"], before)

    def test_get_relations_non_200_returns_error(self):
        result = _client(lambda *a, **k: FakeResponse(503, None)).get_relations()
        self.assertFalse(result["success"])
        self.assertIn("503", result["error"])

    def test_invalidate_ledger_cache_forces_refetch(self):
        calls = {"n": 0}

        def transport(method, url, params=None, **kw):
            calls["n"] += 1
            return FakeResponse(200, [])  # empty page terminates immediately

        client = _client(transport)
        client.get_ledgers()
        first_calls = calls["n"]
        # Cached: no new fetch.
        client.get_ledgers()
        self.assertEqual(calls["n"], first_calls)
        # After invalidation a fresh fetch must occur.
        client.invalidate_ledger_cache()
        client.get_ledgers()
        self.assertGreater(calls["n"], first_calls)

    def test_invalidate_all_caches_clears_both(self):
        client = _client(lambda *a, **k: FakeResponse(200, []))
        client._ledger_cache = [{"id": 1}]
        client._relation_cache = [{"id": 2}]
        client.invalidate_all_caches()
        self.assertIsNone(client._ledger_cache)
        self.assertIsNone(client._relation_cache)

    def test_invalidate_relation_cache_only(self):
        client = _client(lambda *a, **k: FakeResponse(200, []))
        client._ledger_cache = [{"id": 1}]
        client._relation_cache = [{"id": 2}]
        client.invalidate_relation_cache()
        self.assertEqual(client._ledger_cache, [{"id": 1}])
        self.assertIsNone(client._relation_cache)


if __name__ == "__main__":
    unittest.main()
