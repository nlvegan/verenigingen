"""
Unit tests for Ponto OAuth2 Token Manager (Tier-1).

Covers the MyPonto client_credentials token flow: cache hit / miss / expiry-buffer
refresh, the OAuth2 token endpoint error branches (401 / 400 / missing token /
connection failure), token invalidation, forced refresh, and the class-level
cache clear.

HTTP-boundary stubbing: ONLY the external token endpoint is mocked
(requests.Session.post). The Frappe cache is real, and PontoTokenManager's own
caching/expiry logic runs unmocked. This file is named *_unit.py per the
test-quality-enforcer rule for HTTP-boundary-stubbing tests.

Usage:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_ponto_token_manager_unit
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.ponto_test_data_factory import PontoTestDataFactory
from verenigingen.tests.fixtures.singleton_backup import SingletonBackup
from verenigingen.verenigingen_payments.ponto.exceptions import PontoAuthenticationError
from verenigingen.verenigingen_payments.ponto.utils.token_manager import (
    PontoTokenManager,
    get_token_manager,
)


def _mock_token_response(status_code=200, json_data=None, text="{}"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data if json_data is not None else {}
    resp.raise_for_status = MagicMock()
    return resp


class TestPontoTokenManagerUnit(FrappeTestCase):
    """Token caching / refresh logic with the HTTP endpoint stubbed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Token manager __init__ reads Ponto Settings (use_ibanity_mtls). Back up
        # and force the non-mTLS MyPonto path so client_credentials flow is used.
        cls._singleton_backup = SingletonBackup("Ponto Settings")
        cls._singleton_backup.backup()
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_mode = 1
        settings.use_ibanity_mtls = 0
        settings.sandbox_client_id = "test_sandbox_client"
        settings.sandbox_client_secret = "test_sandbox_secret"
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls._singleton_backup.restore()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        # CI shards multiple test processes onto ONE site sharing ONE redis
        # cache. A sibling shard's frappe.clear_cache() FLUSHES the entire shared
        # redis db, wiping the token this test just cached (regardless of key
        # uniqueness) -- so the second get_valid_token() call sees an empty cache
        # and re-hits the (mocked) OAuth2 endpoint, breaking
        # ``mock_post.assert_called_once()``. Isolate the cache to a per-process
        # in-memory dict for the duration of each test so the token persists
        # across the two calls and is immune to a sibling's FLUSH. The token
        # manager still calls frappe.cache().get_value/set_value/delete_value and
        # branches on presence + the cached expiry timestamp, so the real
        # cache/refresh LOGIC is still exercised. Patch frappe.cache (resolved
        # fresh on every call) before any cache access below.
        from verenigingen.tests.fixtures.fake_cache import isolate_cache_keys

        self._cache_ctx = isolate_cache_keys(
            PontoTokenManager.TOKEN_CACHE_KEY, PontoTokenManager.EXPIRY_CACHE_KEY
        )
        self._cache_ctx.__enter__()
        self.addCleanup(self._cache_ctx.__exit__, None, None, None)
        PontoTokenManager.clear_cache()
        # Explicit credentials => _get_credentials never hits settings/DB.
        self.tm = PontoTokenManager(client_id="explicit_client", client_secret="explicit_secret")

    def tearDown(self):
        PontoTokenManager.clear_cache()
        super().tearDown()

    # -------------------------------------------------------------------------
    # Construction
    # -------------------------------------------------------------------------

    def test_factory_returns_instance(self):
        tm = get_token_manager()
        self.assertIsInstance(tm, PontoTokenManager)

    def test_non_mtls_mode_after_setup(self):
        self.assertFalse(self.tm._use_mtls)

    # -------------------------------------------------------------------------
    # Token fetch (cache miss)
    # -------------------------------------------------------------------------

    def test_fetch_new_token_on_cache_miss(self):
        token_data = PontoTestDataFactory.create_token_response(
            access_token="fresh_token_abc", expires_in=1800
        )
        with patch.object(self.tm._session, "post") as mock_post:
            mock_post.return_value = _mock_token_response(json_data=token_data)
            token = self.tm.get_valid_token()

        self.assertEqual(token, "fresh_token_abc")
        mock_post.assert_called_once()
        # Verify the OAuth2 token endpoint + client_credentials grant were used.
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], PontoTokenManager.MYPONTO_TOKEN_URL)
        self.assertEqual(kwargs["data"]["grant_type"], "client_credentials")
        self.assertEqual(kwargs["auth"], ("explicit_client", "explicit_secret"))

    def test_fetched_token_persists_expiry_to_settings(self):
        """A successful fetch records access_token_expiry on the settings doc.

        The expiry is persisted via db.set_value(update_modified=False), which
        skips Ponto Settings.on_update -> clear_token_cache(), so it no longer
        evicts the token cached in the same call (see the cache-survival test).
        """
        before = datetime.now()
        token_data = PontoTestDataFactory.create_token_response(access_token="to_be_cached", expires_in=1800)
        with patch.object(self.tm._session, "post") as mock_post:
            mock_post.return_value = _mock_token_response(json_data=token_data)
            token = self.tm.get_valid_token()

        self.assertEqual(token, "to_be_cached")
        expiry = frappe.db.get_value("Ponto Settings", "Ponto Settings", "access_token_expiry")
        self.assertIsNotNone(expiry)
        # Expiry should be roughly 30 minutes out.
        if isinstance(expiry, str):
            expiry = datetime.fromisoformat(expiry)
        self.assertGreater(expiry, before + timedelta(seconds=1700))

    def test_cache_survives_fetch_no_second_http(self):
        # Regression: persisting the expiry must NOT evict the just-cached token.
        # A first call fetches+caches; a second call must serve from cache without
        # a second OAuth2 HTTP request. (Pre-fix, settings.save() fired
        # on_update -> clear_token_cache(), so the second call re-hit the endpoint.)
        token_data = PontoTestDataFactory.create_token_response(
            access_token="cached_across_calls", expires_in=1800
        )
        with patch.object(self.tm._session, "post") as mock_post:
            mock_post.return_value = _mock_token_response(json_data=token_data)
            first = self.tm.get_valid_token()
            second = self.tm.get_valid_token()
            mock_post.assert_called_once()  # only the first call hit the endpoint
        self.assertEqual(first, "cached_across_calls")
        self.assertEqual(second, "cached_across_calls")
        self.assertEqual(frappe.cache().get_value(PontoTokenManager.TOKEN_CACHE_KEY), "cached_across_calls")

    # -------------------------------------------------------------------------
    # Cache hit
    # -------------------------------------------------------------------------

    def test_valid_cached_token_returned_without_http(self):
        cache = frappe.cache()
        cache.set_value(PontoTokenManager.TOKEN_CACHE_KEY, "cached_valid_token")
        cache.set_value(
            PontoTokenManager.EXPIRY_CACHE_KEY,
            (datetime.now() + timedelta(minutes=20)).isoformat(),
        )
        with patch.object(self.tm._session, "post") as mock_post:
            token = self.tm.get_valid_token()
            mock_post.assert_not_called()
        self.assertEqual(token, "cached_valid_token")

    def test_expired_cache_triggers_refresh(self):
        """A token inside the expiry buffer must be refreshed via HTTP."""
        cache = frappe.cache()
        cache.set_value(PontoTokenManager.TOKEN_CACHE_KEY, "stale_token")
        # Expires in 30s — within the 60s buffer => must refresh.
        cache.set_value(
            PontoTokenManager.EXPIRY_CACHE_KEY,
            (datetime.now() + timedelta(seconds=30)).isoformat(),
        )
        token_data = PontoTestDataFactory.create_token_response(
            access_token="refreshed_after_buffer", expires_in=1800
        )
        with patch.object(self.tm._session, "post") as mock_post:
            mock_post.return_value = _mock_token_response(json_data=token_data)
            token = self.tm.get_valid_token()
            mock_post.assert_called_once()
        self.assertEqual(token, "refreshed_after_buffer")

    def test_corrupt_cached_expiry_triggers_refresh(self):
        """A non-ISO expiry string must fall through to a fresh fetch."""
        cache = frappe.cache()
        cache.set_value(PontoTokenManager.TOKEN_CACHE_KEY, "token_with_bad_expiry")
        cache.set_value(PontoTokenManager.EXPIRY_CACHE_KEY, "not-a-datetime")
        token_data = PontoTestDataFactory.create_token_response(
            access_token="recovered_token", expires_in=1800
        )
        with patch.object(self.tm._session, "post") as mock_post:
            mock_post.return_value = _mock_token_response(json_data=token_data)
            token = self.tm.get_valid_token()
            mock_post.assert_called_once()
        self.assertEqual(token, "recovered_token")

    # -------------------------------------------------------------------------
    # Error branches
    # -------------------------------------------------------------------------

    def test_401_raises_authentication_error(self):
        with patch.object(self.tm._session, "post") as mock_post:
            mock_post.return_value = _mock_token_response(status_code=401)
            with self.assertRaises(PontoAuthenticationError) as ctx:
                self.tm.get_valid_token()
        self.assertIn("Invalid Ponto credentials", str(ctx.exception))

    def test_400_raises_with_error_description(self):
        with patch.object(self.tm._session, "post") as mock_post:
            mock_post.return_value = _mock_token_response(
                status_code=400,
                text='{"error":"invalid_request"}',
                json_data={"error_description": "bad scope"},
            )
            with self.assertRaises(PontoAuthenticationError) as ctx:
                self.tm.get_valid_token()
        self.assertIn("bad scope", str(ctx.exception))

    def test_connection_error_raises_authentication_error(self):
        import requests

        with patch.object(self.tm._session, "post") as mock_post:
            mock_post.side_effect = requests.ConnectionError("network down")
            with self.assertRaises(PontoAuthenticationError) as ctx:
                self.tm.get_valid_token()
        self.assertIn("Failed to connect", str(ctx.exception))

    def test_missing_access_token_in_response_raises(self):
        with patch.object(self.tm._session, "post") as mock_post:
            # Valid HTTP 200 but no access_token field.
            mock_post.return_value = _mock_token_response(
                json_data={"token_type": "Bearer", "expires_in": 1800}
            )
            with self.assertRaises(PontoAuthenticationError) as ctx:
                self.tm.get_valid_token()
        self.assertIn("No access token", str(ctx.exception))

    # -------------------------------------------------------------------------
    # Credential resolution
    # -------------------------------------------------------------------------

    def test_explicit_credentials_used_directly(self):
        """Explicit credentials are returned without touching settings."""
        cid, secret = self.tm._get_credentials()
        self.assertEqual((cid, secret), ("explicit_client", "explicit_secret"))

    def test_missing_credentials_from_settings_raises(self):
        """With no explicit creds and a blank settings client id, auth fails."""
        tm = PontoTokenManager()  # no explicit creds -> falls back to settings
        original = frappe.db.get_value("Ponto Settings", "Ponto Settings", "sandbox_client_id")
        frappe.db.set_value(
            "Ponto Settings",
            "Ponto Settings",
            "sandbox_client_id",
            "",
            update_modified=False,
        )
        try:
            with self.assertRaises(PontoAuthenticationError):
                tm._get_credentials()
        finally:
            frappe.db.set_value(
                "Ponto Settings",
                "Ponto Settings",
                "sandbox_client_id",
                original,
                update_modified=False,
            )

    # -------------------------------------------------------------------------
    # Invalidate / refresh / clear
    # -------------------------------------------------------------------------

    def test_invalidate_token_clears_cache(self):
        cache = frappe.cache()
        cache.set_value(PontoTokenManager.TOKEN_CACHE_KEY, "x")
        cache.set_value(PontoTokenManager.EXPIRY_CACHE_KEY, "y")
        self.tm.invalidate_token()
        self.assertIsNone(cache.get_value(PontoTokenManager.TOKEN_CACHE_KEY))
        self.assertIsNone(cache.get_value(PontoTokenManager.EXPIRY_CACHE_KEY))

    def test_refresh_token_invalidates_then_fetches(self):
        cache = frappe.cache()
        cache.set_value(PontoTokenManager.TOKEN_CACHE_KEY, "old_token")
        cache.set_value(
            PontoTokenManager.EXPIRY_CACHE_KEY,
            (datetime.now() + timedelta(minutes=20)).isoformat(),
        )
        token_data = PontoTestDataFactory.create_token_response(
            access_token="forced_refresh_token", expires_in=1800
        )
        with patch.object(self.tm._session, "post") as mock_post:
            mock_post.return_value = _mock_token_response(json_data=token_data)
            # Even though cache has a valid token, refresh_token() forces a fetch.
            token = self.tm.refresh_token()
            mock_post.assert_called_once()
        self.assertEqual(token, "forced_refresh_token")

    def test_clear_cache_classmethod(self):
        cache = frappe.cache()
        cache.set_value(PontoTokenManager.TOKEN_CACHE_KEY, "x")
        cache.set_value(PontoTokenManager.EXPIRY_CACHE_KEY, "y")
        PontoTokenManager.clear_cache()
        self.assertIsNone(cache.get_value(PontoTokenManager.TOKEN_CACHE_KEY))
        self.assertIsNone(cache.get_value(PontoTokenManager.EXPIRY_CACHE_KEY))
