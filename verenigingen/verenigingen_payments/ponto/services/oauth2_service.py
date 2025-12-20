# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Connect OAuth2 Authorization Service

Handles the OAuth2 authorization_code flow with PKCE for Ponto Connect API.

The Ponto API requires user authorization (not just client credentials).
This service manages:
1. Authorization URL generation with PKCE
2. Authorization code exchange for tokens
3. Token refresh

Usage:
    from verenigingen.verenigingen_payments.ponto.services.oauth2_service import (
        PontoOAuth2Service,
        get_oauth2_service,
    )

    service = get_oauth2_service()

    # Step 1: Get authorization URL for user to visit
    auth_url = service.get_authorization_url()

    # Step 2: After user authorizes, exchange code for tokens
    tokens = service.exchange_authorization_code(code)

    # Step 3: Get valid access token (auto-refreshes if needed)
    token = service.get_access_token()
"""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from urllib.parse import urlencode

import frappe
from frappe.utils import get_url

from verenigingen.verenigingen_payments.ponto.exceptions import PontoAuthenticationError


class PontoOAuth2Service:
    """
    OAuth2 authorization service for Ponto Connect.

    Implements the authorization_code flow with PKCE required by Ponto API.
    Tokens are stored in Ponto Settings for persistence.
    """

    # MyPonto OAuth2 authorization endpoints (user-facing)
    SANDBOX_AUTHORIZATION_URL = "https://sandbox-authorization.myponto.com/oauth2/auth"
    LIVE_AUTHORIZATION_URL = "https://authorization.myponto.com/oauth2/auth"

    # Ibanity OAuth2 token endpoint (API endpoint, requires mTLS)
    TOKEN_URL = "https://api.ibanity.com/ponto-connect/oauth2/token"

    # OAuth2 scopes for Ponto Connect
    # ai = account information, pi = payment initiation, name = org info
    DEFAULT_SCOPES = "ai pi name offline_access"

    # Cache keys
    STATE_CACHE_KEY = "ponto_oauth2_state"
    CODE_VERIFIER_CACHE_KEY = "ponto_oauth2_code_verifier"
    ACCESS_TOKEN_CACHE_KEY = "ponto_ibanity_access_token"
    REFRESH_TOKEN_CACHE_KEY = "ponto_ibanity_refresh_token"
    TOKEN_EXPIRY_CACHE_KEY = "ponto_ibanity_token_expiry"

    # Cache TTL settings (seconds)
    STATE_CACHE_TTL = 600  # 10 minutes - OAuth2 state/code_verifier expiry
    REFRESH_TOKEN_CACHE_TTL = 86400 * 30  # 30 days - Refresh token cache

    def __init__(self):
        """Initialize OAuth2 service."""
        self._settings = None
        self._cert_files = None

    def __del__(self):
        """Clean up temporary certificate files on object destruction."""
        self._cleanup_temp_files()

    def _cleanup_temp_files(self):
        """
        Securely remove temporary certificate and key files.

        Uses secure deletion (overwrite before delete) for key files
        to prevent recovery of sensitive cryptographic material.
        """
        import os

        if not self._cert_files:
            return

        for filepath in self._cert_files:
            if filepath:
                try:
                    if os.path.exists(filepath):
                        # Secure delete: overwrite with random data before unlinking
                        try:
                            file_size = os.path.getsize(filepath)
                            for _ in range(3):  # Multiple overwrite passes
                                with open(filepath, "wb") as f:
                                    f.write(os.urandom(file_size))
                                    f.flush()
                                    os.fsync(f.fileno())
                        except Exception:
                            pass  # Fall through to unlink
                        os.unlink(filepath)
                except Exception:
                    pass

        self._cert_files = None

    def _generate_pkce_pair(self) -> Tuple[str, str]:
        """
        Generate PKCE code_verifier and code_challenge pair.

        Returns:
            Tuple of (code_verifier, code_challenge)
        """
        # Generate a random code_verifier (43-128 characters)
        code_verifier = secrets.token_urlsafe(64)

        # Create code_challenge using S256 method
        # SHA256 hash, then base64url encode (without padding)
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

        return code_verifier, code_challenge

    def _get_authorization_base_url(self) -> str:
        """
        Get the authorization URL based on sandbox mode.

        Returns:
            str: Sandbox or live authorization URL
        """
        settings = self._get_settings()
        if settings.sandbox_mode:
            return self.SANDBOX_AUTHORIZATION_URL
        return self.LIVE_AUTHORIZATION_URL

    def _get_settings(self):
        """Get Ponto Settings singleton."""
        if not self._settings:
            self._settings = frappe.get_single("Ponto Settings")
        return self._settings

    def _get_credentials(self) -> Tuple[str, str]:
        """
        Get Ibanity OAuth2 credentials.

        Returns:
            Tuple of (client_id, client_secret)
        """
        settings = self._get_settings()
        client_id = settings.ibanity_client_id
        client_secret = settings.get_password("ibanity_client_secret")

        if not client_id or not client_secret:
            raise PontoAuthenticationError(
                "Ibanity OAuth2 credentials not configured",
                details={"missing": "ibanity_client_id or ibanity_client_secret"},
            )

        return client_id, client_secret

    def _get_redirect_uri(self) -> str:
        """
        Get the OAuth2 callback URL.

        Returns:
            str: Full callback URL
        """
        base_url = get_url()
        return f"{base_url}/api/method/verenigingen.verenigingen_payments.ponto.api.oauth2_callback.handle_callback"

    def get_authorization_url(self, scopes: str = None) -> str:
        """
        Generate OAuth2 authorization URL with PKCE for user to visit.

        The user will be redirected to MyPonto to authorize the application.
        After authorization, they are redirected back to our callback URL.

        Args:
            scopes: OAuth2 scopes (default: ai pi name offline_access)

        Returns:
            str: Authorization URL to redirect user to
        """
        client_id, _ = self._get_credentials()

        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)

        # Generate PKCE code_verifier and code_challenge
        code_verifier, code_challenge = self._generate_pkce_pair()

        # Store state and code_verifier in cache for verification/exchange
        cache = frappe.cache()
        cache.set_value(self.STATE_CACHE_KEY, state, expires_in_sec=self.STATE_CACHE_TTL)
        cache.set_value(self.CODE_VERIFIER_CACHE_KEY, code_verifier, expires_in_sec=self.STATE_CACHE_TTL)

        params = {
            "client_id": client_id,
            "redirect_uri": self._get_redirect_uri(),
            "response_type": "code",
            "scope": scopes or self.DEFAULT_SCOPES,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        base_url = self._get_authorization_base_url()
        auth_url = f"{base_url}?{urlencode(params)}"

        frappe.logger().debug(
            f"Generated Ponto OAuth2 authorization URL (sandbox={self._get_settings().sandbox_mode}) "
            f"with state: {state[:10]}..."
        )

        return auth_url

    def verify_state(self, state: str) -> bool:
        """
        Verify the OAuth2 state parameter for CSRF protection.

        Args:
            state: State parameter from callback

        Returns:
            bool: True if state is valid
        """
        cache = frappe.cache()
        stored_state = cache.get_value(self.STATE_CACHE_KEY)

        # Handle bytes from Redis
        if isinstance(stored_state, bytes):
            stored_state = stored_state.decode("utf-8")

        if not stored_state or stored_state != state:
            frappe.logger().warning(
                f"OAuth2 state mismatch: expected {stored_state[:10] if stored_state else 'None'}..., got {state[:10] if state else 'None'}..."
            )
            return False

        # Clear state after verification
        cache.delete_value(self.STATE_CACHE_KEY)
        return True

    def _get_cert_files(self) -> Optional[Tuple[str, str]]:
        """
        Get mTLS certificate files for API requests.

        Returns:
            Tuple of (cert_path, key_path) or None
        """
        import os
        import tempfile

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        if self._cert_files:
            return self._cert_files

        settings = self._get_settings()

        if not settings.use_ibanity_mtls:
            return None

        if not settings.ibanity_certificate or not settings.ibanity_private_key:
            return None

        # Write certificate to temp file
        cert_file = tempfile.NamedTemporaryFile(
            mode="wb", suffix=".pem", delete=False, prefix="ponto_oauth_cert_"
        )
        cert_file.write(settings.ibanity_certificate.encode("utf-8"))
        cert_file.close()

        # Decrypt and write private key
        key_pem = settings.ibanity_private_key
        passphrase = settings.get_password("ibanity_key_passphrase")

        key_bytes = key_pem.encode("utf-8")
        if b"ENCRYPTED" in key_bytes and passphrase:
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
            mode="wb", suffix=".pem", delete=False, prefix="ponto_oauth_key_"
        )
        key_file.write(decrypted_key)
        key_file.close()

        self._cert_files = (cert_file.name, key_file.name)
        return self._cert_files

    def exchange_authorization_code(self, code: str) -> Dict[str, str]:
        """
        Exchange authorization code for access and refresh tokens.

        Uses PKCE code_verifier stored during authorization URL generation.

        Args:
            code: Authorization code from callback

        Returns:
            Dict with access_token, refresh_token, expires_in

        Raises:
            PontoAuthenticationError: If exchange fails
        """
        import requests

        client_id, client_secret = self._get_credentials()

        # Get the code_verifier from cache (stored during authorization URL generation)
        cache = frappe.cache()
        code_verifier = cache.get_value(self.CODE_VERIFIER_CACHE_KEY)

        if not code_verifier:
            raise PontoAuthenticationError(
                "PKCE code_verifier not found. Authorization session may have expired.",
                details={"action": "retry_authorization"},
            )

        # Handle bytes from Redis
        if isinstance(code_verifier, bytes):
            code_verifier = code_verifier.decode("utf-8")

        # Clear the code_verifier from cache (one-time use)
        cache.delete_value(self.CODE_VERIFIER_CACHE_KEY)

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._get_redirect_uri(),
            "code_verifier": code_verifier,
        }

        try:
            request_kwargs = {
                "data": data,
                "headers": {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                "auth": (client_id, client_secret),  # HTTP Basic Auth
                "timeout": 30,
            }

            # Add mTLS certificates
            cert_files = self._get_cert_files()
            if cert_files:
                request_kwargs["cert"] = cert_files

            response = requests.post(self.TOKEN_URL, **request_kwargs)

            if not response.ok:
                error_data = response.json() if response.text else {}
                frappe.logger().error(f"OAuth2 token exchange failed: {response.status_code} - {error_data}")
                raise PontoAuthenticationError(
                    f"Failed to exchange authorization code: {error_data.get('error_description', response.text[:100])}",
                    details=error_data,
                )

            token_data = response.json()

        except requests.RequestException as e:
            frappe.logger().error(f"OAuth2 token exchange request failed: {e}")
            raise PontoAuthenticationError(
                "Failed to connect to Ibanity OAuth2 endpoint",
                details={"error": str(e)},
            )

        # Store tokens
        self._store_tokens(token_data)

        frappe.logger().info("Successfully exchanged authorization code for tokens")

        return {
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "expires_in": token_data.get("expires_in"),
            "token_type": token_data.get("token_type"),
            "scope": token_data.get("scope"),
        }

    def _store_tokens(self, token_data: Dict):
        """
        Store tokens in cache and database.

        Access token is stored in cache (short-lived).
        Refresh token is stored in both cache and database (survives cache clears).

        Args:
            token_data: Token response from OAuth2 endpoint
        """
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 1800)

        expiry_time = datetime.now() + timedelta(seconds=expires_in)

        cache = frappe.cache()
        cache.set_value(self.ACCESS_TOKEN_CACHE_KEY, access_token, expires_in_sec=expires_in)
        cache.set_value(self.TOKEN_EXPIRY_CACHE_KEY, expiry_time.isoformat(), expires_in_sec=expires_in)

        if refresh_token:
            # Refresh tokens have longer expiry (typically 28 days)
            cache.set_value(
                self.REFRESH_TOKEN_CACHE_KEY, refresh_token, expires_in_sec=self.REFRESH_TOKEN_CACHE_TTL
            )

        # Update settings - store refresh token in database for persistence
        try:
            settings = frappe.get_single("Ponto Settings")
            settings.access_token_expiry = expiry_time
            # SECURITY JUSTIFICATION: OAuth2 token storage is a system operation triggered by
            # OAuth2 callback flow (user just completed authorization). No persistent user session
            # during callback. Audit trail via access_token_expiry timestamp. Only updating
            # token-related fields as part of authorized OAuth2 flow.
            settings.save(ignore_permissions=True)

            # Password fields require special handling for Single DocTypes
            if refresh_token:
                from frappe.utils.password import set_encrypted_password

                set_encrypted_password(
                    "Ponto Settings",
                    "Ponto Settings",  # For Singles, name == doctype
                    refresh_token,
                    fieldname="ibanity_refresh_token",
                )
                frappe.db.commit()  # Ensure password is persisted immediately
            frappe.logger().debug("Stored refresh token in database for persistence")
        except Exception as e:
            frappe.logger().warning(f"Could not update Ponto Settings: {e}")

    def get_access_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary.

        Checks cache first, then falls back to database-stored refresh token.

        Returns:
            str: Valid access token

        Raises:
            PontoAuthenticationError: If no valid token available
        """
        cache = frappe.cache()

        # Check cached access token
        cached_token = cache.get_value(self.ACCESS_TOKEN_CACHE_KEY)
        cached_expiry = cache.get_value(self.TOKEN_EXPIRY_CACHE_KEY)

        # Handle bytes from Redis
        if isinstance(cached_token, bytes):
            cached_token = cached_token.decode("utf-8")
        if isinstance(cached_expiry, bytes):
            cached_expiry = cached_expiry.decode("utf-8")

        if cached_token and cached_expiry:
            try:
                expiry_time = datetime.fromisoformat(cached_expiry)
                # Refresh 60 seconds before expiry
                if datetime.now() < expiry_time - timedelta(seconds=60):
                    return cached_token
            except (ValueError, TypeError):
                pass

        # Try to refresh from cache first
        refresh_token = cache.get_value(self.REFRESH_TOKEN_CACHE_KEY)
        if isinstance(refresh_token, bytes):
            refresh_token = refresh_token.decode("utf-8")

        # Fall back to database-stored refresh token if cache is empty
        if not refresh_token:
            try:
                settings = frappe.get_single("Ponto Settings")
                refresh_token = settings.get_password("ibanity_refresh_token")
                if refresh_token:
                    frappe.logger().debug("Retrieved refresh token from database (cache was empty)")
            except Exception as e:
                frappe.logger().debug(f"Could not get refresh token from database: {e}")

        if refresh_token:
            try:
                return self._refresh_access_token(refresh_token)
            except Exception as e:
                frappe.logger().warning(f"Token refresh failed: {e}")

        raise PontoAuthenticationError(
            "No valid Ponto access token. Please authorize the application first.",
            details={"action": "authorize"},
        )

    def _refresh_access_token(self, refresh_token: str) -> str:
        """
        Refresh the access token using refresh token.

        Args:
            refresh_token: Refresh token

        Returns:
            str: New access token

        Raises:
            PontoAuthenticationError: If refresh fails
        """
        import requests

        client_id, client_secret = self._get_credentials()

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        try:
            request_kwargs = {
                "data": data,
                "headers": {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                "auth": (client_id, client_secret),  # HTTP Basic Auth
                "timeout": 30,
            }

            cert_files = self._get_cert_files()
            if cert_files:
                request_kwargs["cert"] = cert_files

            response = requests.post(self.TOKEN_URL, **request_kwargs)

            if not response.ok:
                error_data = response.json() if response.text else {}
                raise PontoAuthenticationError(
                    f"Token refresh failed: {error_data.get('error_description', 'Unknown error')}",
                    details=error_data,
                )

            token_data = response.json()

        except requests.RequestException as e:
            raise PontoAuthenticationError(
                "Failed to refresh token",
                details={"error": str(e)},
            )

        self._store_tokens(token_data)

        frappe.logger().debug("Successfully refreshed Ponto access token")

        return token_data.get("access_token")

    def revoke_tokens(self):
        """Clear all stored tokens (cache and database)."""
        cache = frappe.cache()
        cache.delete_value(self.ACCESS_TOKEN_CACHE_KEY)
        cache.delete_value(self.REFRESH_TOKEN_CACHE_KEY)
        cache.delete_value(self.TOKEN_EXPIRY_CACHE_KEY)

        # Also clear database-stored refresh token
        try:
            settings = frappe.get_single("Ponto Settings")
            settings.access_token_expiry = None
            # SECURITY JUSTIFICATION: Token revocation is a security operation initiated by admin
            # or system. Clearing tokens doesn't expose sensitive data - it removes access.
            # Operation logged via revoke_tokens() logger call.
            settings.save(ignore_permissions=True)

            # Delete password from __Auth table
            frappe.db.delete(
                "__Auth",
                {"doctype": "Ponto Settings", "name": "Ponto Settings", "fieldname": "ibanity_refresh_token"},
            )
        except Exception as e:
            frappe.logger().warning(f"Could not clear database tokens: {e}")

        frappe.logger().info("Revoked Ponto OAuth2 tokens")

    def is_authorized(self) -> bool:
        """
        Check if the application has valid authorization.

        Returns:
            bool: True if we have valid tokens
        """
        try:
            self.get_access_token()
            return True
        except PontoAuthenticationError:
            return False


def get_oauth2_service() -> PontoOAuth2Service:
    """
    Factory function for OAuth2 service.

    Returns:
        PontoOAuth2Service instance
    """
    return PontoOAuth2Service()
