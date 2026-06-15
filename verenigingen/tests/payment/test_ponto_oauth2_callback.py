"""
Tests for the Ponto Connect OAuth2 callback endpoint.

Integration tests for api/oauth2_callback.handle_callback: query-parameter
parsing, the error / access_denied branch, missing-code and missing-state
guards, CSRF state verification, and the success path (code exchange) — all by
constructing a realistic werkzeug request on frappe.local.request and asserting
the redirect response and side effects.

The ONLY thing stubbed is the external token-exchange HTTP call
(requests.post inside oauth2_service.exchange_authorization_code). State
verification, PKCE handling and token storage run for real against the cache /
settings singleton.

Usage:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_ponto_oauth2_callback
"""

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.fixtures.ponto_test_data_factory import PontoTestDataFactory
from verenigingen.tests.fixtures.singleton_backup import SingletonBackup
from verenigingen.verenigingen_payments.ponto.api import oauth2_callback


def _make_request(query: dict):
    """Build a real werkzeug Request with the given query params."""
    builder = EnvironBuilder(
        path="/api/method/...handle_callback", method="GET", query_string=query
    )
    return Request(builder.get_environ())


class TestPontoOAuth2Callback(FrappeTestCase):
    """handle_callback redirect + side-effect behaviour."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._singleton_backup = SingletonBackup("Ponto Settings")
        cls._singleton_backup.backup()
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_mode = 1
        settings.use_ibanity_mtls = 0
        settings.sandbox_client_id = "test_sandbox_client"
        settings.sandbox_client_secret = "test_sandbox_secret"
        settings.ibanity_client_id = "test_ibanity_client"
        settings.ibanity_client_secret = "test_ibanity_secret"
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls._singleton_backup.restore()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self._prev_request = getattr(frappe.local, "request", None)
        # Fresh response container for each test.
        frappe.local.response = frappe._dict()
        cache = frappe.cache()
        cache.delete_value("ponto_oauth2_state")
        cache.delete_value("ponto_oauth2_code_verifier")

    def tearDown(self):
        frappe.local.request = self._prev_request
        cache = frappe.cache()
        cache.delete_value("ponto_oauth2_state")
        cache.delete_value("ponto_oauth2_code_verifier")
        super().tearDown()

    def _set_request(self, query):
        frappe.local.request = _make_request(query)

    def _assert_redirects_to_settings(self):
        self.assertEqual(frappe.local.response.get("type"), "redirect")
        self.assertIn("/app/ponto-settings", frappe.local.response.get("location", ""))

    # -------------------------------------------------------------------------
    # Error branch (provider returned ?error=...)
    # -------------------------------------------------------------------------

    def test_access_denied_redirects(self):
        """access_denied is the user-cancelled case: redirect, no Error Log."""
        self._set_request({"error": "access_denied", "error_description": "User said no"})
        with patch("frappe.log_error") as mock_log:
            oauth2_callback.handle_callback()
            # access_denied is benign — must NOT create an Error Log.
            mock_log.assert_not_called()
        self._assert_redirects_to_settings()

    def test_generic_error_logs_and_redirects(self):
        """A non-access_denied error is logged and still redirects."""
        self._set_request({"error": "server_error", "error_description": "boom"})
        with patch("frappe.log_error") as mock_log:
            oauth2_callback.handle_callback()
            mock_log.assert_called_once()
        self._assert_redirects_to_settings()

    # -------------------------------------------------------------------------
    # Missing required parameters
    # -------------------------------------------------------------------------

    def test_missing_code_redirects(self):
        self._set_request({"state": "somestate"})
        oauth2_callback.handle_callback()
        self._assert_redirects_to_settings()

    def test_missing_state_redirects(self):
        self._set_request({"code": "somecode"})
        oauth2_callback.handle_callback()
        self._assert_redirects_to_settings()

    def test_empty_query_redirects(self):
        self._set_request({})
        oauth2_callback.handle_callback()
        self._assert_redirects_to_settings()

    # -------------------------------------------------------------------------
    # CSRF state verification
    # -------------------------------------------------------------------------

    def test_invalid_state_redirects_without_exchange(self):
        """A state that does not match the cached one must not exchange the code."""
        # No state cached => verify_state returns False.
        self._set_request({"code": "abc", "state": "wrong_state"})
        # Patch the token exchange boundary to ensure it is NEVER reached.
        with patch("requests.post") as mock_post:
            oauth2_callback.handle_callback()
            mock_post.assert_not_called()
        self._assert_redirects_to_settings()

    # -------------------------------------------------------------------------
    # Success path (valid state + code exchange)
    # -------------------------------------------------------------------------

    def test_successful_callback_exchanges_code(self):
        """Valid state + code => token exchange runs and redirects."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        # Generate a real authorization URL to seed state + PKCE verifier in cache.
        service = get_oauth2_service()
        auth_url = service.get_authorization_url()
        state = parse_qs(urlparse(auth_url).query)["state"][0]

        self._set_request({"code": "valid_auth_code", "state": state})

        token_data = PontoTestDataFactory.create_token_response(
            access_token="cb_access", refresh_token="cb_refresh", expires_in=1800
        )
        # Stub ONLY the HTTP token endpoint.
        with patch("requests.post") as mock_post:
            resp = MagicMock()
            resp.ok = True
            resp.json.return_value = token_data
            mock_post.return_value = resp
            oauth2_callback.handle_callback()
            mock_post.assert_called_once()

        self._assert_redirects_to_settings()
        # State is one-time use: it must have been consumed from the cache.
        self.assertIsNone(frappe.cache().get_value("ponto_oauth2_state"))

    def test_exchange_failure_redirects(self):
        """If the token exchange raises, the callback still redirects (no 500)."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        service = get_oauth2_service()
        auth_url = service.get_authorization_url()
        state = parse_qs(urlparse(auth_url).query)["state"][0]

        self._set_request({"code": "bad_code", "state": state})

        with patch("requests.post") as mock_post:
            resp = MagicMock()
            resp.ok = False
            resp.status_code = 400
            resp.text = '{"error":"invalid_grant"}'
            resp.json.return_value = {"error_description": "Authorization code expired"}
            mock_post.return_value = resp
            with patch("frappe.log_error"):
                oauth2_callback.handle_callback()

        self._assert_redirects_to_settings()
