"""
Tests for Ponto OAuth2 Service.

Tests the OAuth2 authorization flow with PKCE, token storage,
refresh logic, and mTLS certificate handling.

Usage:
    bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_ponto_oauth2_service
"""

import base64
import hashlib
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.ponto_test_data_factory import (
    PontoTestDataFactory,
    TestIBAN,
)


class TestPontoOAuth2Service(FrappeTestCase):
    """Test cases for PontoOAuth2Service."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        # Ensure Ponto Settings exists with test credentials
        cls._setup_test_settings()

    @classmethod
    def _setup_test_settings(cls):
        """Configure Ponto Settings for testing."""
        settings = frappe.get_single("Ponto Settings")
        settings.ibanity_client_id = "test_client_id_12345"
        # Password fields are set directly in Single DocTypes
        settings.ibanity_client_secret = "test_client_secret_67890"
        settings.sandbox_mode = 1
        settings.use_ibanity_mtls = 0
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    def setUp(self):
        """Set up each test."""
        super().setUp()
        # Clear cache before each test
        cache = frappe.cache()
        cache.delete_value("ponto_oauth2_state")
        cache.delete_value("ponto_oauth2_code_verifier")
        cache.delete_value("ponto_ibanity_access_token")
        cache.delete_value("ponto_ibanity_token_expiry")

    def tearDown(self):
        """Clean up after each test."""
        super().tearDown()
        # Clear cache after each test
        cache = frappe.cache()
        cache.delete_value("ponto_oauth2_state")
        cache.delete_value("ponto_oauth2_code_verifier")
        cache.delete_value("ponto_ibanity_access_token")
        cache.delete_value("ponto_ibanity_token_expiry")

    # -------------------------------------------------------------------------
    # PKCE Generation Tests
    # -------------------------------------------------------------------------

    def test_pkce_pair_generation(self):
        """Test PKCE code_verifier and code_challenge generation."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            PontoOAuth2Service,
        )

        service = PontoOAuth2Service()
        code_verifier, code_challenge = service._generate_pkce_pair()

        # Verify code_verifier format (43-128 URL-safe characters)
        self.assertIsInstance(code_verifier, str)
        self.assertGreaterEqual(len(code_verifier), 43)
        self.assertLessEqual(len(code_verifier), 128)

        # Verify code_challenge is S256 transformation of code_verifier
        expected_digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        expected_challenge = base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
        self.assertEqual(code_challenge, expected_challenge)

    def test_pkce_pair_uniqueness(self):
        """Test that each PKCE pair is unique."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            PontoOAuth2Service,
        )

        service = PontoOAuth2Service()

        pairs = [service._generate_pkce_pair() for _ in range(5)]
        verifiers = [p[0] for p in pairs]
        challenges = [p[1] for p in pairs]

        # All verifiers should be unique
        self.assertEqual(len(set(verifiers)), 5)
        # All challenges should be unique
        self.assertEqual(len(set(challenges)), 5)

    # -------------------------------------------------------------------------
    # Authorization URL Tests
    # -------------------------------------------------------------------------

    def test_authorization_url_generation(self):
        """Test authorization URL has correct PKCE parameters."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        service = get_oauth2_service()
        auth_url = service.get_authorization_url()

        # Parse URL and validate components
        parsed = urlparse(auth_url)
        params = parse_qs(parsed.query)

        # Should use sandbox URL
        self.assertIn("sandbox-authorization.myponto.com", parsed.netloc)

        # Required OAuth2 parameters
        self.assertIn("client_id", params)
        self.assertEqual(params["client_id"][0], "test_client_id_12345")

        self.assertIn("response_type", params)
        self.assertEqual(params["response_type"][0], "code")

        self.assertIn("redirect_uri", params)

        # PKCE parameters
        self.assertIn("code_challenge", params)
        self.assertIn("code_challenge_method", params)
        self.assertEqual(params["code_challenge_method"][0], "S256")

        # CSRF state parameter
        self.assertIn("state", params)

        # Scopes
        self.assertIn("scope", params)
        self.assertIn("offline_access", params["scope"][0])

    def test_authorization_url_stores_pkce_verifier(self):
        """Test that code_verifier is cached for later exchange."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        service = get_oauth2_service()
        auth_url = service.get_authorization_url()

        # Parse code_challenge from URL
        parsed = urlparse(auth_url)
        params = parse_qs(parsed.query)
        code_challenge = params["code_challenge"][0]

        # Verify code_verifier is cached
        cache = frappe.cache()
        cached_verifier = cache.get_value("ponto_oauth2_code_verifier")

        self.assertIsNotNone(cached_verifier)

        # Handle bytes from Redis
        if isinstance(cached_verifier, bytes):
            cached_verifier = cached_verifier.decode("utf-8")

        # Verify the cached verifier produces the URL's challenge
        expected_digest = hashlib.sha256(cached_verifier.encode("ascii")).digest()
        expected_challenge = base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
        self.assertEqual(code_challenge, expected_challenge)

    def test_authorization_url_stores_state(self):
        """Test that state parameter is cached for CSRF verification."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        service = get_oauth2_service()
        auth_url = service.get_authorization_url()

        # Parse state from URL
        parsed = urlparse(auth_url)
        params = parse_qs(parsed.query)
        url_state = params["state"][0]

        # Verify state is cached
        cache = frappe.cache()
        cached_state = cache.get_value("ponto_oauth2_state")

        self.assertIsNotNone(cached_state)

        # Handle bytes from Redis
        if isinstance(cached_state, bytes):
            cached_state = cached_state.decode("utf-8")

        self.assertEqual(url_state, cached_state)

    def test_live_authorization_url_when_not_sandbox(self):
        """Test that live URL is used when sandbox mode is disabled."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        # Temporarily disable sandbox mode
        settings = frappe.get_single("Ponto Settings")
        original_sandbox = settings.sandbox_mode
        settings.sandbox_mode = 0
        settings.save()

        try:
            service = get_oauth2_service()
            # Force reload settings
            service._settings = None
            auth_url = service.get_authorization_url()

            parsed = urlparse(auth_url)
            self.assertEqual(parsed.netloc, "authorization.myponto.com")
        finally:
            # Restore sandbox mode
            settings.sandbox_mode = original_sandbox
            settings.save()

    # -------------------------------------------------------------------------
    # State Verification Tests
    # -------------------------------------------------------------------------

    def test_state_verification_valid(self):
        """Test that valid state passes verification."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        service = get_oauth2_service()
        auth_url = service.get_authorization_url()

        # Extract state from URL
        parsed = urlparse(auth_url)
        params = parse_qs(parsed.query)
        state = params["state"][0]

        # Verify state
        self.assertTrue(service.verify_state(state))

    def test_state_verification_clears_cache(self):
        """Test that state is cleared from cache after verification."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        service = get_oauth2_service()
        auth_url = service.get_authorization_url()

        # Extract state from URL
        parsed = urlparse(auth_url)
        params = parse_qs(parsed.query)
        state = params["state"][0]

        # First verification should succeed
        self.assertTrue(service.verify_state(state))

        # Second verification should fail (state cleared)
        self.assertFalse(service.verify_state(state))

    def test_state_verification_invalid(self):
        """Test that invalid state fails verification."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        service = get_oauth2_service()
        service.get_authorization_url()

        # Try to verify with wrong state
        self.assertFalse(service.verify_state("invalid_state_12345"))

    def test_state_verification_expired(self):
        """Test that expired state fails verification."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        service = get_oauth2_service()
        auth_url = service.get_authorization_url()

        # Extract state
        parsed = urlparse(auth_url)
        params = parse_qs(parsed.query)
        state = params["state"][0]

        # Clear cache to simulate expiry
        frappe.cache().delete_value("ponto_oauth2_state")

        # Should fail
        self.assertFalse(service.verify_state(state))

    # -------------------------------------------------------------------------
    # Token Storage Tests
    # -------------------------------------------------------------------------

    def test_token_storage_to_cache(self):
        """Test that tokens are stored in cache."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            PontoOAuth2Service,
        )

        service = PontoOAuth2Service()

        token_data = PontoTestDataFactory.create_token_response(
            access_token="test_access_token_abc",
            refresh_token="test_refresh_token_xyz",
            expires_in=1800,
        )

        service._store_tokens(token_data)

        # Verify cache storage
        cache = frappe.cache()
        cached_token = cache.get_value("ponto_ibanity_access_token")

        if isinstance(cached_token, bytes):
            cached_token = cached_token.decode("utf-8")

        self.assertEqual(cached_token, "test_access_token_abc")

    def test_token_storage_to_database(self):
        """Test that tokens are persisted to database."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            PontoOAuth2Service,
        )

        service = PontoOAuth2Service()

        token_data = PontoTestDataFactory.create_token_response(
            access_token="db_access_token_123",
            refresh_token="db_refresh_token_456",
            expires_in=1800,
        )

        service._store_tokens(token_data)

        # Verify database storage
        settings = frappe.get_single("Ponto Settings")
        db_access = settings.get_password("ibanity_access_token")
        db_refresh = settings.get_password("ibanity_refresh_token")

        self.assertEqual(db_access, "db_access_token_123")
        self.assertEqual(db_refresh, "db_refresh_token_456")

    def test_token_expiry_stored(self):
        """Test that token expiry time is stored correctly."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            PontoOAuth2Service,
        )

        service = PontoOAuth2Service()
        before_store = datetime.now()

        token_data = PontoTestDataFactory.create_token_response(expires_in=1800)
        service._store_tokens(token_data)

        after_store = datetime.now()

        # Check cache expiry
        cache = frappe.cache()
        cached_expiry = cache.get_value("ponto_ibanity_token_expiry")

        if isinstance(cached_expiry, bytes):
            cached_expiry = cached_expiry.decode("utf-8")

        expiry_time = datetime.fromisoformat(cached_expiry)

        # Expiry should be ~30 minutes from now
        expected_min = before_store + timedelta(seconds=1795)
        expected_max = after_store + timedelta(seconds=1805)

        self.assertGreater(expiry_time, expected_min)
        self.assertLess(expiry_time, expected_max)

    # -------------------------------------------------------------------------
    # Access Token Retrieval Tests
    # -------------------------------------------------------------------------

    def test_get_access_token_from_cache(self):
        """Test that valid cached token is returned."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            PontoOAuth2Service,
        )

        service = PontoOAuth2Service()

        # Store a valid token
        token_data = PontoTestDataFactory.create_token_response(
            access_token="cached_token_123",
            expires_in=1800,
        )
        service._store_tokens(token_data)

        # Should return cached token
        token = service.get_access_token()
        self.assertEqual(token, "cached_token_123")

    def test_get_access_token_from_database_on_cache_miss(self):
        """Test that database token is used when cache is empty."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            PontoOAuth2Service,
        )

        service = PontoOAuth2Service()

        # Store token (goes to both cache and DB)
        token_data = PontoTestDataFactory.create_token_response(
            access_token="db_fallback_token",
            expires_in=1800,
        )
        service._store_tokens(token_data)

        # Clear only the cache
        cache = frappe.cache()
        cache.delete_value("ponto_ibanity_access_token")
        cache.delete_value("ponto_ibanity_token_expiry")

        # Should retrieve from database
        token = service.get_access_token()
        self.assertEqual(token, "db_fallback_token")

    def test_get_access_token_triggers_refresh_when_expired(self):
        """Test that expired token triggers refresh."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            PontoOAuth2Service,
        )

        service = PontoOAuth2Service()

        # Store expired token
        cache = frappe.cache()
        cache.set_value("ponto_ibanity_access_token", "expired_token")
        cache.set_value(
            "ponto_ibanity_token_expiry",
            (datetime.now() - timedelta(hours=1)).isoformat(),
        )

        # Store refresh token in DB
        from frappe.utils.password import set_encrypted_password

        set_encrypted_password(
            "Ponto Settings",
            "Ponto Settings",
            "valid_refresh_token",
            fieldname="ibanity_refresh_token",
        )
        frappe.db.commit()

        # Mock justified: External API - Ibanity OAuth2 token endpoint (not business logic)
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.json.return_value = PontoTestDataFactory.create_token_response(
                access_token="refreshed_token_new",
                refresh_token="new_refresh_token",
                expires_in=1800,
            )
            mock_post.return_value = mock_response

            # Should trigger refresh and return new token
            token = service.get_access_token()
            self.assertEqual(token, "refreshed_token_new")

            # Verify refresh endpoint was called
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            self.assertIn("refresh_token", call_kwargs.kwargs.get("data", {}))

    def test_get_access_token_respects_expiry_buffer(self):
        """Test that token refresh triggers 5 minutes before expiry."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            PontoOAuth2Service,
        )

        service = PontoOAuth2Service()

        # Store token that expires in 4 minutes (within 5-minute buffer)
        cache = frappe.cache()
        cache.set_value("ponto_ibanity_access_token", "almost_expired_token")
        cache.set_value(
            "ponto_ibanity_token_expiry",
            (datetime.now() + timedelta(minutes=4)).isoformat(),
        )

        # Store refresh token
        from frappe.utils.password import set_encrypted_password

        set_encrypted_password(
            "Ponto Settings",
            "Ponto Settings",
            "refresh_for_buffer_test",
            fieldname="ibanity_refresh_token",
        )
        frappe.db.commit()

        # Mock justified: External API - Ibanity OAuth2 token refresh endpoint (not business logic)
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.json.return_value = PontoTestDataFactory.create_token_response(
                access_token="proactively_refreshed_token",
            )
            mock_post.return_value = mock_response

            token = service.get_access_token()

            # Should have refreshed proactively
            self.assertEqual(token, "proactively_refreshed_token")
            mock_post.assert_called_once()

    # -------------------------------------------------------------------------
    # Authorization Code Exchange Tests
    # -------------------------------------------------------------------------

    def test_exchange_authorization_code_success(self):
        """Test successful authorization code exchange."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        service = get_oauth2_service()

        # Generate auth URL to set up PKCE verifier
        service.get_authorization_url()

        # Mock justified: External API - Ibanity OAuth2 token exchange endpoint (not business logic)
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.json.return_value = PontoTestDataFactory.create_token_response(
                access_token="exchanged_access_token",
                refresh_token="exchanged_refresh_token",
                expires_in=1800,
            )
            mock_post.return_value = mock_response

            result = service.exchange_authorization_code("test_auth_code_123")

            self.assertEqual(result["access_token"], "exchanged_access_token")
            self.assertEqual(result["refresh_token"], "exchanged_refresh_token")
            self.assertEqual(result["expires_in"], 1800)

    def test_exchange_authorization_code_clears_verifier(self):
        """Test that code_verifier is cleared after exchange."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        service = get_oauth2_service()
        service.get_authorization_url()

        # Verify verifier is set
        cache = frappe.cache()
        self.assertIsNotNone(cache.get_value("ponto_oauth2_code_verifier"))

        # Mock justified: External API - Ibanity OAuth2 token exchange endpoint (not business logic)
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.json.return_value = PontoTestDataFactory.create_token_response()
            mock_post.return_value = mock_response

            service.exchange_authorization_code("test_code")

        # Verifier should be cleared (one-time use)
        self.assertIsNone(cache.get_value("ponto_oauth2_code_verifier"))

    def test_exchange_authorization_code_without_verifier_fails(self):
        """Test that exchange fails if PKCE verifier is missing."""
        from verenigingen.verenigingen_payments.ponto.exceptions import (
            PontoAuthenticationError,
        )
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        service = get_oauth2_service()

        # Don't generate auth URL (no verifier stored)

        with self.assertRaises(PontoAuthenticationError) as ctx:
            service.exchange_authorization_code("orphan_code")

        self.assertIn("code_verifier not found", str(ctx.exception))

    def test_exchange_authorization_code_api_error(self):
        """Test handling of API errors during exchange."""
        from verenigingen.verenigingen_payments.ponto.exceptions import (
            PontoAuthenticationError,
        )
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            get_oauth2_service,
        )

        service = get_oauth2_service()
        service.get_authorization_url()

        # Mock justified: External API - Ibanity OAuth2 token endpoint error handling (not business logic)
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.ok = False
            mock_response.status_code = 400
            mock_response.text = "Invalid grant"
            mock_response.json.return_value = {
                "error": "invalid_grant",
                "error_description": "Authorization code expired",
            }
            mock_post.return_value = mock_response

            with self.assertRaises(PontoAuthenticationError) as ctx:
                service.exchange_authorization_code("expired_code")

            self.assertIn("Authorization code expired", str(ctx.exception))

    # -------------------------------------------------------------------------
    # Credentials Tests
    # -------------------------------------------------------------------------

    def test_missing_credentials_raises_error(self):
        """Test that missing credentials raise proper error."""
        from verenigingen.verenigingen_payments.ponto.exceptions import (
            PontoAuthenticationError,
        )
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            PontoOAuth2Service,
        )

        # Clear credentials
        settings = frappe.get_single("Ponto Settings")
        original_client_id = settings.ibanity_client_id
        settings.ibanity_client_id = ""
        settings.save()

        try:
            service = PontoOAuth2Service()
            service._settings = None  # Force reload

            with self.assertRaises(PontoAuthenticationError) as ctx:
                service._get_credentials()

            self.assertIn("not configured", str(ctx.exception))
        finally:
            # Restore
            settings.ibanity_client_id = original_client_id
            settings.save()

    # -------------------------------------------------------------------------
    # Token Revocation Tests
    # -------------------------------------------------------------------------

    def test_revoke_tokens_clears_cache(self):
        """Test that revoke_tokens clears cache."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            PontoOAuth2Service,
        )

        service = PontoOAuth2Service()

        # Store tokens
        token_data = PontoTestDataFactory.create_token_response()
        service._store_tokens(token_data)

        # Verify they exist
        cache = frappe.cache()
        self.assertIsNotNone(cache.get_value("ponto_ibanity_access_token"))

        # Revoke
        service.revoke_tokens()

        # Should be cleared
        self.assertIsNone(cache.get_value("ponto_ibanity_access_token"))
        self.assertIsNone(cache.get_value("ponto_ibanity_token_expiry"))

    def test_is_authorized_returns_true_with_valid_token(self):
        """Test is_authorized returns True when token is valid."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            PontoOAuth2Service,
        )

        service = PontoOAuth2Service()

        # Store valid token
        token_data = PontoTestDataFactory.create_token_response(expires_in=1800)
        service._store_tokens(token_data)

        self.assertTrue(service.is_authorized())

    def test_is_authorized_returns_false_without_token(self):
        """Test is_authorized returns False when no token exists."""
        from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
            PontoOAuth2Service,
        )

        service = PontoOAuth2Service()

        # Clear all tokens
        service.revoke_tokens()

        self.assertFalse(service.is_authorized())


if __name__ == "__main__":
    unittest.main()
