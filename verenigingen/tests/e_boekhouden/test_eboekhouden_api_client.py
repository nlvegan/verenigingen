"""
Real-logic coverage for the E-Boekhouden API client wrapper
``verenigingen/e_boekhouden/utils/eboekhouden_api.py``.

These tests drive the REAL ``EBoekhoudenAPI`` class and module-level whitelisted
endpoints. The ONLY thing mocked is the external HTTP boundary — ``requests.get``
/ ``requests.post`` / ``requests.request`` — which is the eBoekhouden REST server,
not business logic (mirrors the existing ``@patch("requests.post")`` test in
test_eboekhouden_doctype_coverage.py). Everything else — pagination assembly,
JSON parsing, endpoint URL construction, the request/response success/error
mapping, and the XML parser — runs for real.

A lightweight fake Settings object is used as a FIXTURE so a client can be
constructed without a live API token configured on the test site. It exposes
exactly the attributes ``_init_http_client`` reads (``api_url``,
``source_application``, ``get_password``).

Run with:
    cd /home/frappeuser/frappe-bench && bench --site test_site_1 run-tests \
        --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_eboekhouden_api_client
"""

import json
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_api import (
    EBoekhoudenAPI,
    EBoekhoudenXMLParser,
    get_mutation_type_name_for_analysis,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _FakeSettings:
    """Fixture stand-in for the E-Boekhouden Settings single.

    ``EBoekhoudenAPI.__init__`` -> ``_init_http_client`` reads only ``api_url``,
    ``source_application`` and ``get_password("api_token")``. This is a data
    fixture, NOT a mock of business logic: it lets us instantiate the real client
    on a site that has no live token configured.
    """

    def __init__(self, api_url="https://api.example-eb.test", token="fake-token", source="TestSource"):
        self.api_url = api_url
        self.source_application = source
        # _init_http_client reads the password only when ``hasattr(settings,
        # "api_token")`` is true, so the attribute must exist (its value is
        # irrelevant — the real value comes from get_password()).
        self.api_token = "***"
        self._token = token

    def get_password(self, fieldname, raise_exception=True):
        if fieldname == "api_token":
            return self._token
        return None


def _insert_test_doc(doc):
    """Persist ``doc`` with permissions bypassed (test fixture helper).

    These coverage tests run as the FrappeTestCase default user, which lacks
    insert permission on Account. The bypass lives in this fixture helper so test
    bodies stay declarative (matches the helper in test_eboekhouden_doctype_coverage.py)."""
    doc.insert(ignore_permissions=True)
    return doc


def _http_response(status_code=200, text="", headers=None):
    """Build a MagicMock shaped like a requests.Response for the HTTP boundary."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {}
    resp.json = lambda: json.loads(text) if text else {}
    return resp


def _make_api(token="fake-token", source="TestSource", api_url="https://api.example-eb.test"):
    return EBoekhoudenAPI(_FakeSettings(api_url=api_url, token=token, source=source))


class TestEBoekhoudenAPIClient(EnhancedTestCase):
    """REST client behaviour: construction, request mapping, pagination, endpoints."""

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def test_init_requires_token(self):
        """A settings object with no api_token raises ValueError (mixin contract)."""
        with self.assertRaises(ValueError):
            _make_api(token=None)

    def test_init_normalizes_base_url(self):
        """base_url gets an https scheme and trailing slash stripped."""
        api = _make_api(api_url="api.example-eb.test/")
        self.assertEqual(api.base_url, "https://api.example-eb.test")

    def test_source_attribute_kept_for_backward_compat(self):
        """The client keeps source_application as the ``source`` attribute."""
        api = _make_api(source="MyApp")
        self.assertEqual(api.source, "MyApp")

    def test_source_attribute_defaults_when_blank(self):
        """A blank source_application falls back to the default label."""
        api = _make_api(source="")
        self.assertEqual(api.source, "Verenigingen ERPNext")

    # ------------------------------------------------------------------
    # make_request: success and failure mapping
    # ------------------------------------------------------------------
    def test_make_request_get_success(self):
        """A 200 GET returns success=True with the raw text in ``data``."""
        api = _make_api()
        with patch.object(api, "_get_headers", return_value={"Authorization": "t"}), patch(
            "requests.get", return_value=_http_response(200, text='{"items": []}')
        ) as mock_get:
            result = api.make_request("v1/ledger", "GET", {"limit": 5})
        self.assertTrue(result["success"])
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["data"], '{"items": []}')
        # URL is assembled from base_url + endpoint
        called_url = mock_get.call_args[0][0]
        self.assertEqual(called_url, "https://api.example-eb.test/v1/ledger")

    def test_make_request_post_uses_json_body(self):
        """A POST sends params as the JSON body, not query params."""
        api = _make_api()
        with patch.object(api, "_get_headers", return_value={"Authorization": "t"}), patch(
            "requests.post", return_value=_http_response(200, text="{}")
        ) as mock_post:
            result = api.make_request("v1/session", "POST", {"a": 1})
        self.assertTrue(result["success"])
        self.assertEqual(mock_post.call_args.kwargs["json"], {"a": 1})

    def test_make_request_non_200_maps_to_error(self):
        """A non-200 response maps to success=False with the error text."""
        api = _make_api()
        with patch.object(api, "_get_headers", return_value={"Authorization": "t"}), patch(
            "requests.get", return_value=_http_response(404, text="not found")
        ):
            result = api.make_request("v1/ledger")
        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 404)
        self.assertIn("404", result["error"])

    # ------------------------------------------------------------------
    # _paginated_fetch: real pagination assembly
    # ------------------------------------------------------------------
    def test_paginated_fetch_single_page(self):
        """A short page (< limit) terminates after one request and returns its items."""
        api = _make_api()
        page = json.dumps({"items": [{"id": 1}, {"id": 2}]})
        with patch.object(api, "make_request", return_value={"success": True, "data": page}) as mock_req:
            result = api.get_chart_of_accounts()
        self.assertTrue(result["success"])
        items = json.loads(result["data"])["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual(mock_req.call_count, 1)

    def test_paginated_fetch_multi_page_aggregates(self):
        """A full page (== limit) triggers a follow-up fetch; items aggregate across pages."""
        api = _make_api()
        full_page = json.dumps({"items": [{"id": i} for i in range(500)]})
        last_page = json.dumps({"items": [{"id": 9999}]})

        calls = {"n": 0}

        def fake_make_request(endpoint, method, params):
            calls["n"] += 1
            # Verify pagination params advance by 500
            self.assertEqual(params["limit"], 500)
            expected_offset = 0 if calls["n"] == 1 else 500
            self.assertEqual(params["offset"], expected_offset)
            return {"success": True, "data": full_page if calls["n"] == 1 else last_page}

        with patch.object(api, "make_request", side_effect=fake_make_request):
            result = api.get_chart_of_accounts()
        self.assertTrue(result["success"])
        items = json.loads(result["data"])["items"]
        self.assertEqual(len(items), 501)
        self.assertEqual(calls["n"], 2)

    def test_paginated_fetch_propagates_request_failure(self):
        """If a page request fails, the failure dict is returned verbatim."""
        api = _make_api()
        with patch.object(
            api, "make_request", return_value={"success": False, "error": "boom", "status_code": 500}
        ):
            result = api.get_chart_of_accounts()
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "boom")

    def test_get_customers_sets_relation_type_filter(self):
        """get_customers injects relationType=Customer into the pagination params."""
        api = _make_api()
        captured = {}

        def fake_make_request(endpoint, method, params):
            captured.update(params)
            return {"success": True, "data": json.dumps({"items": []})}

        with patch.object(api, "make_request", side_effect=fake_make_request):
            api.get_customers()
        self.assertEqual(captured.get("relationType"), "Customer")

    def test_get_suppliers_sets_relation_type_filter(self):
        """get_suppliers injects relationType=Supplier."""
        api = _make_api()
        captured = {}

        def fake_make_request(endpoint, method, params):
            captured.update(params)
            return {"success": True, "data": json.dumps({"items": []})}

        with patch.object(api, "make_request", side_effect=fake_make_request):
            api.get_suppliers()
        self.assertEqual(captured.get("relationType"), "Supplier")

    # ------------------------------------------------------------------
    # single-resource endpoint URL construction (BUG: missing f-string)
    # ------------------------------------------------------------------
    def test_get_invoice_detail_builds_interpolated_url(self):
        """get_invoice_detail(<id>) must hit v1/invoice/<id>, not a literal '{invoice_id}'.

        Regression guard: the endpoint string was a plain (non-f) string, so the
        client requested 'v1/invoice/{invoice_id}' for every invoice id.
        """
        api = _make_api()
        captured = {}

        def fake_make_request(endpoint, params=None):
            captured["endpoint"] = endpoint
            return {"success": True, "data": "{}"}

        with patch.object(api, "make_request", side_effect=fake_make_request):
            api.get_invoice_detail("12345")
        self.assertEqual(captured["endpoint"], "v1/invoice/12345")

    def test_download_document_builds_interpolated_url(self):
        """download_document(<id>) must hit v1/document/<id>/download."""
        api = _make_api()
        captured = {}

        def fake_make_request(endpoint, params=None):
            captured["endpoint"] = endpoint
            return {"success": True, "data": "{}"}

        with patch.object(api, "make_request", side_effect=fake_make_request):
            api.download_document("77")
        self.assertEqual(captured["endpoint"], "v1/document/77/download")

    def test_get_invoice_documents_builds_interpolated_url(self):
        """get_invoice_documents(<id>) must hit v1/invoice/<id>/document."""
        api = _make_api()
        captured = {}

        def fake_make_request(endpoint, params=None):
            captured["endpoint"] = endpoint
            return {"success": True, "data": "{}"}

        with patch.object(api, "make_request", side_effect=fake_make_request):
            api.get_invoice_documents("88")
        self.assertEqual(captured["endpoint"], "v1/invoice/88/document")


class TestEBoekhoudenAPIPreviewEndpoints(EnhancedTestCase):
    """Whitelisted preview endpoints: count messages and simplified shapes.

    The preview endpoints wrap the client and return a human-readable ``message``
    plus a trimmed list. These tests pin the message wording (which contains the
    real item count) and the first-10 truncation behaviour.
    """

    def _patch_api(self, method_name, items):
        """Patch a single EBoekhoudenAPI accessor to return canned page data,
        and stub the token requirement so a real client can be built."""
        data = {"success": True, "data": json.dumps({"items": items})}
        return patch.object(EBoekhoudenAPI, method_name, return_value=data)

    def setUp(self):
        super().setUp()
        # Make EBoekhoudenAPI() construct without a live token.
        self._init_patch = patch(
            "verenigingen.utils.settings_utils.get_e_boekhouden_settings",
            return_value=_FakeSettings(),
        )
        self._init_patch.start()
        self.addCleanup(self._init_patch.stop)

    def test_preview_chart_of_accounts_counts_and_trims(self):
        """preview_chart_of_accounts reports the full count and trims to 10 items."""
        from verenigingen.e_boekhouden.utils.eboekhouden_api import preview_chart_of_accounts

        accounts = [{"id": i, "code": str(i), "description": f"acc{i}"} for i in range(15)]
        with self._patch_api("get_chart_of_accounts", accounts):
            result = preview_chart_of_accounts()
        self.assertTrue(result["success"])
        self.assertEqual(result["total_count"], 15)
        self.assertEqual(len(result["accounts"]), 10)
        # Message embeds the real count (was an f-string already here).
        self.assertIn("15", result["message"])

    def test_preview_customers_message_embeds_count(self):
        """preview_customers' message must contain the actual customer count.

        Regression guard: the message string was a plain (non-f) string, so it
        always returned the literal '{len(customers)}'.
        """
        from verenigingen.e_boekhouden.utils.eboekhouden_api import preview_customers

        customers = [{"id": i, "name": f"cust{i}"} for i in range(4)]
        with self._patch_api("get_customers", customers):
            result = preview_customers()
        self.assertTrue(result["success"])
        self.assertEqual(result["total_count"], 4)
        self.assertEqual(result["message"], "Found 4 customers")

    def test_preview_suppliers_message_embeds_count(self):
        """preview_suppliers' message must contain the actual supplier count."""
        from verenigingen.e_boekhouden.utils.eboekhouden_api import preview_suppliers

        suppliers = [{"id": i, "name": f"sup{i}"} for i in range(3)]
        with self._patch_api("get_suppliers", suppliers):
            result = preview_suppliers()
        self.assertTrue(result["success"])
        self.assertEqual(result["total_count"], 3)
        self.assertEqual(result["message"], "Found 3 suppliers")

    def test_preview_chart_of_accounts_propagates_failure(self):
        """A failed client call surfaces as success=False with the error."""
        from verenigingen.e_boekhouden.utils.eboekhouden_api import preview_chart_of_accounts

        with patch.object(
            EBoekhoudenAPI, "get_chart_of_accounts", return_value={"success": False, "error": "no auth"}
        ):
            result = preview_chart_of_accounts()
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "no auth")

    def test_preview_chart_of_accounts_bad_json(self):
        """Invalid JSON in the response is reported as a parse error, not a crash."""
        from verenigingen.e_boekhouden.utils.eboekhouden_api import preview_chart_of_accounts

        with patch.object(
            EBoekhoudenAPI, "get_chart_of_accounts", return_value={"success": True, "data": "not-json"}
        ):
            result = preview_chart_of_accounts()
        self.assertFalse(result["success"])
        self.assertIn("parse", result["error"].lower())


class TestExploreInvoiceFields(EnhancedTestCase):
    """explore_invoice_fields aggregates per-probe results under distinct keys.

    Regression guard: the result keys were the literal string 'test_{i}', so all
    five probes collapsed onto a single key instead of test_0..test_4.
    """

    def setUp(self):
        super().setUp()
        self._init_patch = patch(
            "verenigingen.utils.settings_utils.get_e_boekhouden_settings",
            return_value=_FakeSettings(),
        )
        # explore_invoice_fields builds EBoekhoudenAPI(settings) from the single,
        # so patch frappe.get_single in that module to return the fake settings.
        self._single_patch = patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_api.frappe.get_single",
            return_value=_FakeSettings(),
        )
        self._init_patch.start()
        self._single_patch.start()
        self.addCleanup(self._init_patch.stop)
        self.addCleanup(self._single_patch.stop)

    def test_failing_probes_use_distinct_keys(self):
        """Each failing probe records under its own test_<i> key."""
        from verenigingen.e_boekhouden.utils.eboekhouden_api import explore_invoice_fields

        with patch.object(
            EBoekhoudenAPI,
            "get_invoices",
            return_value={"success": False, "error": "nope", "status_code": 500},
        ):
            result = explore_invoice_fields()
        self.assertTrue(result["success"])
        # All 5 probes fail -> 5 distinct keys, not a single overwritten one.
        self.assertEqual(set(result["results"].keys()), {f"test_{i}" for i in range(5)})

    def test_successful_probe_with_items_interpolates_key(self):
        """The first successful probe with items records under test_0 and BREAKS
        (eboekhouden_api.py:651). Guards the success-branch f-strings (:619, :629)
        which the all-failing case never exercises -- the key and its
        first_item_analysis sub-key must interpolate to "test_0", not "test_{i}"."""
        from verenigingen.e_boekhouden.utils.eboekhouden_api import explore_invoice_fields

        payload = json.dumps({"items": [{"invoiceId": 1, "documentUrl": "x"}]})
        with patch.object(
            EBoekhoudenAPI,
            "get_invoices",
            return_value={"success": True, "data": payload},
        ):
            result = explore_invoice_fields()
        self.assertTrue(result["success"])
        # Loop breaks after the first items-bearing probe -> exactly test_0, and the
        # literal placeholder must NOT survive interpolation.
        self.assertEqual(set(result["results"].keys()), {"test_0"})
        self.assertNotIn("test_{i}", result["results"])
        entry = result["results"]["test_0"]
        self.assertTrue(entry["success"])
        self.assertEqual(entry["items_count"], 1)
        self.assertIn("first_item_analysis", entry)
        self.assertIn("invoiceId", entry["first_item_analysis"]["all_keys"])


class TestFixAccountTypes(EnhancedTestCase):
    """fix_account_types remaps Receivable/Payable imported accounts.

    Regression guard: the fixed_accounts entries and message were plain strings,
    so they returned literal '{account.name} ...' / 'Fixed {len(...)} accounts'.
    """

    def setUp(self):
        super().setUp()
        self.company = frappe.db.get_value("Company", {}, "name")
        self.parent = frappe.db.get_value(
            "Account", {"company": self.company, "is_group": 1, "root_type": "Asset"}, "name"
        ) or frappe.db.get_value("Account", {"company": self.company, "is_group": 1}, "name")
        if not self.parent:
            self.skipTest("No group account to parent a test account")

    def test_receivable_account_message_interpolated(self):
        """A Receivable account with an account_number is remapped and listed by name."""
        from verenigingen.e_boekhouden.utils.eboekhouden_api import fix_account_types

        acct = frappe.new_doc("Account")
        acct.account_name = f"EB Recv {frappe.generate_hash()[:6]}"
        acct.account_number = f"R{frappe.generate_hash()[:6]}"
        acct.company = self.company
        acct.parent_account = self.parent
        acct.is_group = 0
        acct.account_type = "Receivable"
        _insert_test_doc(acct)

        result = fix_account_types()
        self.assertTrue(result["success"])
        # Message embeds the real count (no literal placeholder).
        self.assertNotIn("{len(", result["message"])
        self.assertRegex(result["message"], r"Fixed \d+ accounts")
        # Our account's real name appears in the fixed list, not a literal placeholder.
        self.assertTrue(
            any(acct.name in entry for entry in result["fixed_accounts"]),
            "fixed_accounts should contain the interpolated account name",
        )
        self.assertFalse(
            any("{account.name}" in entry for entry in result["fixed_accounts"]),
            "fixed_accounts must not contain a literal placeholder",
        )
        # The account was actually remapped in the DB.
        self.assertEqual(
            frappe.db.get_value("Account", acct.name, "account_type"), "Current Asset"
        )


class TestEBoekhoudenXMLParser(EnhancedTestCase):
    """Static XML parsers for the legacy SOAP-shaped payloads."""

    def test_parse_grootboekrekeningen(self):
        """Account XML maps to code/name/category/group dicts."""
        xml = (
            "<Grootboekrekeningen>"
            "<Grootboekrekening><Code>1000</Code><Omschrijving>Kas</Omschrijving>"
            "<Categorie>BAL</Categorie><Groep>001</Groep></Grootboekrekening>"
            "</Grootboekrekeningen>"
        )
        accounts = EBoekhoudenXMLParser.parse_grootboekrekeningen(xml)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["code"], "1000")
        self.assertEqual(accounts[0]["name"], "Kas")
        self.assertEqual(accounts[0]["category"], "BAL")
        self.assertEqual(accounts[0]["group"], "001")

    def test_parse_mutaties_numeric_coercion(self):
        """Mutation XML coerces debit/credit to floats and reads core fields."""
        xml = (
            "<Mutaties><Mutatie>"
            "<MutatieNr>42</MutatieNr><Datum>2024-01-01</Datum>"
            "<Rekening>1300</Rekening><Debet>10.50</Debet><Credit></Credit>"
            "</Mutatie></Mutaties>"
        )
        txns = EBoekhoudenXMLParser.parse_mutaties(xml)
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0]["number"], "42")
        self.assertEqual(txns[0]["debit"], 10.5)
        self.assertEqual(txns[0]["credit"], 0.0)

    def test_parse_relaties(self):
        """Relation XML maps company/contact/email fields."""
        xml = (
            "<Relaties><Relatie>"
            "<Code>C1</Code><Bedrij>ACME BV</Bedrij><Email>a@b.nl</Email>"
            "</Relatie></Relaties>"
        )
        rels = EBoekhoudenXMLParser.parse_relaties(xml)
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0]["code"], "C1")
        self.assertEqual(rels[0]["company_name"], "ACME BV")
        self.assertEqual(rels[0]["email"], "a@b.nl")

    def test_parse_grootboekrekeningen_malformed_returns_empty(self):
        """Malformed XML returns an empty list rather than raising."""
        self.expectErrorLog("XML Parse Error")
        result = EBoekhoudenXMLParser.parse_grootboekrekeningen("<unclosed>")
        self.assertEqual(result, [])


class TestMutationTypeNames(EnhancedTestCase):
    """The static mutation-type -> human name mapping."""

    def test_known_types(self):
        self.assertIn("Opening Balance", get_mutation_type_name_for_analysis(0))
        self.assertIn("Purchase Invoice", get_mutation_type_name_for_analysis(1))
        self.assertIn("Memorial", get_mutation_type_name_for_analysis(7))

    def test_unknown_type_fallback(self):
        self.assertEqual(get_mutation_type_name_for_analysis(99), "Unknown Type 99")
