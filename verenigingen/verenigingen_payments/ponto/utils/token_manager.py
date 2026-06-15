# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto OAuth2 Token Manager

Handles OAuth2 client credentials flow for Ponto API authentication.
Tokens are cached with automatic refresh before expiry.

Usage:
    from verenigingen.verenigingen_payments.ponto.utils.token_manager import (
        PontoTokenManager,
    )

    # Using credentials from settings (recommended)
    token_manager = PontoTokenManager()
    token = token_manager.get_valid_token()

    # Using explicit credentials (for testing)
    token_manager = PontoTokenManager(
        client_id="your-client-id",
        client_secret="your-client-secret"
    )
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple

import frappe
import requests
from frappe import _

from verenigingen.verenigingen_payments.ponto.exceptions import (
    PontoAuthenticationError,
    PontoTokenExpiredError,
)
from verenigingen.verenigingen_payments.ponto.utils.secure_cert_manager import SecureCertManager


class PontoTokenManager:
    """
    OAuth2 token manager for Ponto API.

    Handles token acquisition, caching, and automatic refresh.
    Tokens have a 30-minute lifespan; refresh occurs 60 seconds before expiry.

    Supports both:
    - api.myponto.com (OAuth2 only, no mTLS)
    - api.ibanity.com (mTLS required, uses client certificates for OAuth2)

    Attributes:
        TOKEN_CACHE_KEY: Redis cache key for storing access token
        TOKEN_EXPIRY_BUFFER: Seconds before expiry to trigger refresh
        MYPONTO_TOKEN_URL: Ponto OAuth2 token endpoint (no mTLS)
        IBANITY_TOKEN_URL: Ibanity OAuth2 token endpoint (mTLS required)
    """

    TOKEN_CACHE_KEY = "ponto_access_token"
    EXPIRY_CACHE_KEY = "ponto_token_expiry"
    TOKEN_EXPIRY_BUFFER = 60  # Refresh 60 seconds before expiry
    MYPONTO_TOKEN_URL = "https://api.myponto.com/oauth2/token"
    IBANITY_TOKEN_URL = "https://api.ibanity.com/ponto-connect/oauth2/token"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        """
        Initialize token manager.

        Args:
            client_id: OAuth2 client ID (uses settings if not provided)
            client_secret: OAuth2 client secret (uses settings if not provided)
        """
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = requests.Session()
        self._use_mtls = False
        self._cert_files = None
        self._cert_manager: Optional[SecureCertManager] = None

        # Check if mTLS is configured
        self._setup_mtls()

    def __del__(self):
        """Clean up certificate files on object destruction."""
        if self._cert_manager:
            self._cert_manager._cleanup()
            self._cert_manager = None

    def _setup_mtls(self):
        """
        Set up mTLS certificate authentication if enabled.

        Uses SecureCertManager for secure certificate file handling.
        """
        try:
            settings = frappe.get_single("Ponto Settings")
            if not settings.use_ibanity_mtls:
                return

            # Use SecureCertManager for certificate handling
            self._cert_manager = SecureCertManager()
            if not self._cert_manager.setup_from_settings():
                self._cert_manager = None
                return

            self._use_mtls = True
            self._cert_files = self._cert_manager.get_cert_files()
            frappe.logger().debug("Ponto TokenManager mTLS configured")

        except Exception as e:
            frappe.logger().error(f"Failed to setup mTLS for token manager: {e}")
            self._use_mtls = False
            if self._cert_manager:
                self._cert_manager._cleanup()
                self._cert_manager = None

    def _get_credentials(self) -> Tuple[str, str]:
        """
        Get OAuth2 credentials from settings or instance.

        When mTLS is enabled, uses Ibanity-specific credentials.
        Otherwise uses MyPonto credentials based on sandbox mode.

        Returns:
            Tuple of (client_id, client_secret)

        Raises:
            PontoAuthenticationError: If credentials not configured
        """
        client_id = self._client_id
        client_secret = self._client_secret

        if not client_id or not client_secret:
            # Load from Ponto Settings
            try:
                settings = frappe.get_single("Ponto Settings")

                if self._use_mtls:
                    # Use Ibanity-specific credentials
                    client_id = client_id or settings.ibanity_client_id
                    client_secret = client_secret or settings.get_password("ibanity_client_secret")
                    frappe.logger().debug("Using Ibanity OAuth2 credentials")
                else:
                    # Use MyPonto credentials based on environment
                    client_id = client_id or settings.get_active_client_id()
                    client_secret = client_secret or settings.get_active_client_secret()
                    frappe.logger().debug("Using MyPonto OAuth2 credentials")
            except Exception as e:
                frappe.logger().error(f"Failed to load Ponto credentials: {e}")
                raise PontoAuthenticationError(
                    "Failed to load Ponto credentials from settings",
                    details={"error": str(e)},
                )

        if not client_id:
            raise PontoAuthenticationError(
                "Ponto Client ID not configured",
                details={"missing": "client_id"},
            )

        if not client_secret:
            raise PontoAuthenticationError(
                "Ponto Client Secret not configured",
                details={"missing": "client_secret"},
            )

        return client_id, client_secret

    def get_valid_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary.

        This is the main entry point for obtaining tokens.
        Handles caching and automatic refresh transparently.

        For Ibanity mTLS (authorization_code flow), delegates to OAuth2Service.
        For MyPonto (client_credentials flow), uses direct token fetch.

        Returns:
            str: Valid access token

        Raises:
            PontoAuthenticationError: If token fetch fails
        """
        # For Ibanity mTLS, use the OAuth2 service (authorization_code flow)
        if self._use_mtls:
            from verenigingen.verenigingen_payments.ponto.services.oauth2_service import get_oauth2_service

            oauth2_service = get_oauth2_service()
            return oauth2_service.get_access_token()

        # For MyPonto (client_credentials flow), check cache first
        cache = frappe.cache()
        cached_token = cache.get_value(self.TOKEN_CACHE_KEY)
        cached_expiry = cache.get_value(self.EXPIRY_CACHE_KEY)

        if cached_token and cached_expiry:
            # Check if token is still valid (with buffer)
            try:
                expiry_time = datetime.fromisoformat(cached_expiry)
                if datetime.now() < expiry_time - timedelta(seconds=self.TOKEN_EXPIRY_BUFFER):
                    frappe.logger().debug("Using cached Ponto access token")
                    return cached_token
            except (ValueError, TypeError):
                # Invalid expiry format, fetch new token
                pass

        # Fetch new token using client_credentials (MyPonto only)
        frappe.logger().debug("Fetching new Ponto access token")
        return self._fetch_new_token()

    def _fetch_new_token(self) -> str:
        """
        Fetch new access token from Ponto/Ibanity OAuth2 endpoint.

        Uses client credentials grant type.
        When mTLS is enabled, uses Ibanity API with client certificates.

        Returns:
            str: New access token

        Raises:
            PontoAuthenticationError: If token fetch fails
        """
        client_id, client_secret = self._get_credentials()

        # Choose endpoint based on mTLS configuration
        if self._use_mtls:
            token_url = self.IBANITY_TOKEN_URL
            frappe.logger().debug(f"Fetching token from Ibanity mTLS endpoint: {token_url}")
        else:
            token_url = self.MYPONTO_TOKEN_URL
            frappe.logger().debug(f"Fetching token from MyPonto endpoint: {token_url}")

        try:
            # Build request kwargs
            request_kwargs = {
                "data": {"grant_type": "client_credentials"},
                "auth": (client_id, client_secret),
                "headers": {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                "timeout": 30,
            }

            # Add client certificate for mTLS
            if self._use_mtls and self._cert_files:
                request_kwargs["cert"] = self._cert_files

            response = self._session.post(token_url, **request_kwargs)

            if response.status_code == 401:
                raise PontoAuthenticationError(
                    "Invalid Ponto credentials",
                    details={"status_code": 401},
                )

            if response.status_code == 400:
                error_data = response.json() if response.text else {}
                raise PontoAuthenticationError(
                    f"OAuth2 token request failed: {error_data.get('error_description', 'Bad request')}",
                    details=error_data,
                )

            response.raise_for_status()
            token_data = response.json()

        except requests.RequestException as e:
            frappe.logger().error(f"Ponto token request failed: {e}")
            raise PontoAuthenticationError(
                "Failed to connect to Ponto OAuth2 endpoint",
                details={"error": str(e)},
            )

        access_token = token_data.get("access_token")
        if not access_token:
            raise PontoAuthenticationError(
                "No access token in Ponto response",
                details={"response": token_data},
            )

        # Calculate expiry (default 30 minutes = 1800 seconds)
        expires_in = token_data.get("expires_in", 1800)
        expiry_time = datetime.now() + timedelta(seconds=expires_in)

        # Cache token and expiry
        cache = frappe.cache()
        cache.set_value(self.TOKEN_CACHE_KEY, access_token, expires_in_sec=expires_in)
        cache.set_value(
            self.EXPIRY_CACHE_KEY,
            expiry_time.isoformat(),
            expires_in_sec=expires_in,
        )

        # Persist expiry time for visibility. Use db.set_value(update_modified=False)
        # instead of settings.save(): save() fires Ponto Settings.on_update ->
        # clear_token_cache(), which would delete the token we JUST cached above,
        # defeating the cache so every API call re-hits the OAuth2 endpoint. The
        # direct DB write skips document hooks (same approach as
        # oauth2_service._store_tokens).
        # SECURITY JUSTIFICATION: Token refresh is a system operation triggered by OAuth2 flow.
        # No user context available during background token refresh. Only updating the
        # non-sensitive access_token_expiry timestamp field.
        try:
            frappe.db.set_value(
                "Ponto Settings", "Ponto Settings", "access_token_expiry", expiry_time, update_modified=False
            )
        except Exception as e:
            # Non-critical, just log
            frappe.logger().warning(f"Could not update Ponto Settings token expiry: {e}")

        frappe.logger().info(f"Ponto access token acquired, expires at {expiry_time.isoformat()}")

        return access_token

    def invalidate_token(self):
        """
        Invalidate the cached token.

        Call this when receiving 401 errors to force token refresh.
        """
        cache = frappe.cache()
        cache.delete_value(self.TOKEN_CACHE_KEY)
        cache.delete_value(self.EXPIRY_CACHE_KEY)
        frappe.logger().debug("Invalidated Ponto access token cache")

    def refresh_token(self) -> str:
        """
        Force token refresh.

        Returns:
            str: New access token

        Raises:
            PontoAuthenticationError: If refresh fails
        """
        self.invalidate_token()
        return self._fetch_new_token()

    @classmethod
    def clear_cache(cls):
        """
        Clear token cache (class method for external use).

        Called when Ponto Settings credentials are updated.
        """
        cache = frappe.cache()
        cache.delete_value(cls.TOKEN_CACHE_KEY)
        cache.delete_value(cls.EXPIRY_CACHE_KEY)
        frappe.logger().debug("Cleared Ponto token cache")


def get_token_manager() -> PontoTokenManager:
    """
    Factory function to get PontoTokenManager instance.

    Returns:
        PontoTokenManager: Token manager instance using settings credentials
    """
    return PontoTokenManager()
