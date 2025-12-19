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

import os
import tempfile
from datetime import datetime, timedelta
from typing import Optional, Tuple

import frappe
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from frappe import _

from verenigingen.verenigingen_payments.ponto.exceptions import (
    PontoAuthenticationError,
    PontoTokenExpiredError,
)


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
        self._temp_files = []

        # Check if mTLS is configured
        self._setup_mtls()

    def __del__(self):
        """Clean up temporary certificate files."""
        self._cleanup_temp_files()

    def _cleanup_temp_files(self):
        """Remove temporary certificate and key files."""
        for filepath in self._temp_files:
            try:
                if filepath and os.path.exists(filepath):
                    os.unlink(filepath)
            except Exception:
                pass

    def _setup_mtls(self):
        """
        Set up mTLS certificate authentication if enabled.

        Reads certificate and private key from Ponto Settings,
        decrypts the private key if needed, and creates temp files
        for use with requests library.
        """
        try:
            settings = frappe.get_single("Ponto Settings")
            if not settings.use_ibanity_mtls:
                return

            if not settings.ibanity_certificate or not settings.ibanity_private_key:
                frappe.logger().warning("mTLS enabled but certificate/key not configured")
                return

            self._use_mtls = True

            # Write certificate to temp file
            cert_file = tempfile.NamedTemporaryFile(
                mode="wb", suffix=".pem", delete=False, prefix="ponto_token_cert_"
            )
            cert_file.write(settings.ibanity_certificate.encode("utf-8"))
            cert_file.close()
            self._temp_files.append(cert_file.name)

            # Decrypt and write private key to temp file
            key_pem = settings.ibanity_private_key
            passphrase = settings.get_password("ibanity_key_passphrase")

            key_bytes = key_pem.encode("utf-8")
            if b"ENCRYPTED" in key_bytes and passphrase:
                # Decrypt the key
                password = passphrase.encode("utf-8")
                private_key = load_pem_private_key(key_bytes, password=password)
                decrypted_key = private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            else:
                decrypted_key = key_bytes

            key_file = tempfile.NamedTemporaryFile(
                mode="wb", suffix=".pem", delete=False, prefix="ponto_token_key_"
            )
            key_file.write(decrypted_key)
            key_file.close()
            self._temp_files.append(key_file.name)

            self._cert_files = (cert_file.name, key_file.name)
            frappe.logger().info("Ponto TokenManager mTLS configured")

        except Exception as e:
            frappe.logger().error(f"Failed to setup mTLS for token manager: {e}")
            self._use_mtls = False

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
        frappe.logger().info("Fetching new Ponto access token")
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
            frappe.logger().info(f"Fetching token from Ibanity mTLS endpoint: {token_url}")
        else:
            token_url = self.MYPONTO_TOKEN_URL
            frappe.logger().info(f"Fetching token from MyPonto endpoint: {token_url}")

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

        # Update settings with expiry time for visibility
        try:
            settings = frappe.get_single("Ponto Settings")
            settings.access_token_expiry = expiry_time
            settings.save(ignore_permissions=True)
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
        frappe.logger().info("Invalidated Ponto access token cache")

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
        frappe.logger().info("Cleared Ponto token cache")


def get_token_manager() -> PontoTokenManager:
    """
    Factory function to get PontoTokenManager instance.

    Returns:
        PontoTokenManager: Token manager instance using settings credentials
    """
    return PontoTokenManager()
