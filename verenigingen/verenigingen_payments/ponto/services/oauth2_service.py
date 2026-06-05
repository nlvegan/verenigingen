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
from verenigingen.verenigingen_payments.ponto.utils.secure_cert_manager import SecureCertManager


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
    # NOTE: Refresh token is NOT cached - always read from database.
    # Redis cache gets cleared too easily (bench restart, cache clear, etc.)
    # and losing the refresh token requires full re-authorization.
    STATE_CACHE_KEY = "ponto_oauth2_state"
    CODE_VERIFIER_CACHE_KEY = "ponto_oauth2_code_verifier"
    ACCESS_TOKEN_CACHE_KEY = "ponto_ibanity_access_token"
    TOKEN_EXPIRY_CACHE_KEY = "ponto_ibanity_token_expiry"

    # Cache TTL settings (seconds)
    STATE_CACHE_TTL = 600  # 10 minutes - OAuth2 state/code_verifier expiry

    # Access token storage failure tracking
    ACCESS_TOKEN_STORAGE_FAILURES_KEY = "ponto_access_token_storage_failures"
    ACCESS_TOKEN_STORAGE_FAILURE_THRESHOLD = 3  # Log ERROR after this many consecutive failures

    # Token expiry buffer (seconds before expiry to trigger refresh)
    TOKEN_EXPIRY_BUFFER = 300  # 5 minutes - allows for clock skew

    # Distributed lock for token refresh (prevents race conditions)
    TOKEN_REFRESH_LOCK_NAME = "ponto_token_refresh"
    TOKEN_REFRESH_LOCK_TIMEOUT = 30  # Lock timeout in seconds

    def __init__(self):
        """Initialize OAuth2 service."""
        self._settings = None
        self._cert_files = None
        self._cert_manager: Optional[SecureCertManager] = None

    def __del__(self):
        """Clean up certificate files on object destruction."""
        if self._cert_manager:
            self._cert_manager._cleanup()
            self._cert_manager = None

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

        Uses SecureCertManager for secure certificate file handling.

        Returns:
            Tuple of (cert_path, key_path) or None
        """
        if self._cert_files:
            return self._cert_files

        settings = self._get_settings()

        if not settings.use_ibanity_mtls:
            return None

        # Use SecureCertManager for certificate handling
        self._cert_manager = SecureCertManager()
        if not self._cert_manager.setup_from_settings():
            self._cert_manager = None
            return None

        self._cert_files = self._cert_manager.get_cert_files()
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

        CRITICAL: Tokens must be persisted to database FIRST before updating cache.
        Ibanity invalidates refresh tokens immediately upon use, so if we lose the new
        token, the user must re-authorize.

        Order of operations (each independently committed):
        1. Store refresh token to DB + commit (critical - must not fail)
        2. Store access token to DB + commit (important - survives cache clears)
        3. Update access_token_expiry (for UI visibility)
        4. Update cache (convenience, can be regenerated from DB)

        Args:
            token_data: Token response from OAuth2 endpoint

        Raises:
            PontoAuthenticationError: If refresh token cannot be persisted to database
        """
        from frappe.utils.password import set_encrypted_password

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 1800)

        expiry_time = datetime.now() + timedelta(seconds=expires_in)

        # Step 1: CRITICAL - Store refresh token to database FIRST
        # Ibanity invalidates refresh tokens immediately upon use, so we MUST persist
        # the new one before doing anything else. If this fails, propagate the error.
        if refresh_token:
            try:
                set_encrypted_password(
                    "Ponto Settings",
                    "Ponto Settings",  # For Singles, name == doctype
                    refresh_token,
                    fieldname="ibanity_refresh_token",
                )
                # Commit immediately - do NOT let this be rolled back by outer transaction
                # Per Ibanity docs: "Make sure that the refresh token is renewed outside
                # of the main database transaction"
                frappe.db.commit()
                frappe.logger().info("Ponto refresh token persisted to database")
            except Exception as e:
                frappe.logger().error(f"CRITICAL: Failed to persist Ponto refresh token: {e}")
                # This is critical - without the refresh token, user must re-authorize
                raise PontoAuthenticationError(
                    "Failed to save authentication token. Please try again.",
                    details={"error": str(e), "action": "retry_or_reauthorize"},
                ) from e

        # Step 2: Store access token to database (important - survives cache clears)
        if access_token:
            cache = frappe.cache()
            try:
                set_encrypted_password(
                    "Ponto Settings",
                    "Ponto Settings",
                    access_token,
                    fieldname="ibanity_access_token",
                )
                frappe.db.commit()
                frappe.logger().info("Ponto access token persisted to database")
                # Reset failure counter on success
                cache.delete_value(self.ACCESS_TOKEN_STORAGE_FAILURES_KEY)
            except Exception as e:
                # Track consecutive failures
                failure_count = cache.get_value(self.ACCESS_TOKEN_STORAGE_FAILURES_KEY) or 0
                if isinstance(failure_count, bytes):
                    failure_count = int(failure_count.decode("utf-8"))
                failure_count = int(failure_count) + 1
                cache.set_value(self.ACCESS_TOKEN_STORAGE_FAILURES_KEY, failure_count, expires_in_sec=3600)

                if failure_count >= self.ACCESS_TOKEN_STORAGE_FAILURE_THRESHOLD:
                    frappe.logger().error(
                        f"DEGRADED: Ponto access token storage failed {failure_count} consecutive times. "
                        f"System will rely on cache only. Error: {e}"
                    )
                    # Send notification to system managers on first threshold breach
                    if failure_count == self.ACCESS_TOKEN_STORAGE_FAILURE_THRESHOLD:
                        try:
                            frappe.publish_realtime(
                                "msgprint",
                                {
                                    "message": (
                                        "Ponto Integration Alert: Token storage is degraded. "
                                        "Access tokens cannot be persisted to database. "
                                        "Please check Ponto Settings and database connectivity."
                                    ),
                                    "indicator": "orange",
                                    "title": "Ponto Token Storage Degraded",
                                },
                                user="Administrator",
                            )
                            # Also create an Error Log for visibility
                            frappe.log_error(
                                title="Ponto Token Storage Degraded",
                                message=(
                                    f"Access token storage has failed {failure_count} consecutive times.\n"
                                    f"The system is operating in degraded mode (cache only).\n"
                                    f"Last error: {e}\n\n"
                                    "Action required: Check database connectivity and Ponto Settings."
                                ),
                            )
                        except Exception:
                            pass  # Don't fail token flow due to notification errors
                else:
                    frappe.logger().warning(
                        f"Could not persist access token to database (attempt {failure_count}): {e}"
                    )

        # Step 3: Update access_token_expiry in settings (for UI visibility)
        try:
            # Use direct DB update to avoid "Document has been modified" errors
            frappe.db.set_value(
                "Ponto Settings",
                "Ponto Settings",
                "access_token_expiry",
                expiry_time,
                update_modified=False,
            )
        except Exception as e:
            # Non-critical - just for UI visibility
            frappe.logger().warning(f"Could not update access_token_expiry: {e}")

        # Step 4: Update access token cache (convenience, can be regenerated from DB if lost)
        # NOTE: Refresh token is NOT cached - see class docstring for rationale
        cache = frappe.cache()
        cache.set_value(self.ACCESS_TOKEN_CACHE_KEY, access_token, expires_in_sec=expires_in)
        cache.set_value(self.TOKEN_EXPIRY_CACHE_KEY, expiry_time.isoformat(), expires_in_sec=expires_in)

        frappe.logger().debug(f"Ponto tokens stored, access token expires at {expiry_time.isoformat()}")

    def _get_valid_cached_token(self, now: "datetime") -> Optional[str]:
        """Return the cached access token only if it is still valid (with buffer).

        Used by the in-lock double-check in get_access_token(): another process may
        have refreshed the token while we waited for the lock, but a stale (expired)
        cached token must NOT be returned — otherwise an expired token short-circuits
        the refresh.
        """
        cache = frappe.cache()
        cached_token = cache.get_value(self.ACCESS_TOKEN_CACHE_KEY)
        cached_expiry = cache.get_value(self.TOKEN_EXPIRY_CACHE_KEY)
        if isinstance(cached_token, bytes):
            cached_token = cached_token.decode("utf-8")
        if isinstance(cached_expiry, bytes):
            cached_expiry = cached_expiry.decode("utf-8")
        if cached_token and cached_expiry:
            try:
                expiry_time = datetime.fromisoformat(cached_expiry)
                if now < expiry_time - timedelta(seconds=self.TOKEN_EXPIRY_BUFFER):
                    return cached_token
            except (ValueError, TypeError):
                pass
        return None

    def get_access_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary.

        Order of lookup:
        1. Cache (fastest)
        2. Database access token field (survives cache clears)
        3. Refresh using refresh token (last resort, uses up refresh token)

        Returns:
            str: Valid access token

        Raises:
            PontoAuthenticationError: If no valid token available
        """
        cache = frappe.cache()
        now = datetime.now()

        # Step 1: Check cached access token
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
                # Return if still valid (with buffer for clock skew)
                if now < expiry_time - timedelta(seconds=self.TOKEN_EXPIRY_BUFFER):
                    return cached_token
            except (ValueError, TypeError):
                pass

        # Step 2: Check database-stored access token (survives cache clears)
        # Load settings once and reuse for both access token and refresh token lookups
        settings = None
        try:
            settings = frappe.get_single("Ponto Settings")
            db_access_token = settings.get_password("ibanity_access_token")
            db_expiry = settings.access_token_expiry

            if db_access_token:
                # Make expiry check defensive - if expiry is invalid/missing, still try the token
                token_valid = False
                if db_expiry:
                    try:
                        if isinstance(db_expiry, str):
                            db_expiry = datetime.fromisoformat(db_expiry)
                        token_valid = now < db_expiry - timedelta(seconds=self.TOKEN_EXPIRY_BUFFER)
                    except (ValueError, TypeError, AttributeError):
                        # If expiry is corrupt, let API validation be the final arbiter
                        frappe.logger().debug("DB token expiry invalid, attempting use anyway")
                        token_valid = True

                if token_valid:
                    frappe.logger().debug("Using access token from database (cache miss)")
                    # Re-populate cache from DB
                    if db_expiry and isinstance(db_expiry, datetime):
                        expires_in = int((db_expiry - now).total_seconds())
                        if expires_in > 0:
                            cache.set_value(
                                self.ACCESS_TOKEN_CACHE_KEY, db_access_token, expires_in_sec=expires_in
                            )
                            cache.set_value(
                                self.TOKEN_EXPIRY_CACHE_KEY, db_expiry.isoformat(), expires_in_sec=expires_in
                            )
                    return db_access_token
        except Exception as e:
            frappe.logger().debug(f"Could not get access token from database: {e}")

        # Step 3: Refresh using refresh token (last resort)
        # ALWAYS read refresh token from database - never cache it.
        # Redis cache gets cleared too easily and losing the refresh token
        # requires full re-authorization with Ibanity.
        refresh_token = None
        try:
            # Reuse settings if already loaded, otherwise fetch
            if settings is None:
                settings = frappe.get_single("Ponto Settings")
            refresh_token = settings.get_password("ibanity_refresh_token")
            if refresh_token:
                frappe.logger().debug("Retrieved refresh token from database")
        except Exception as e:
            frappe.logger().debug(f"Could not get refresh token from database: {e}")

        if refresh_token:
            # Use distributed lock to prevent race conditions
            # If two processes try to refresh simultaneously, only one should proceed
            from frappe.utils.file_lock import LockTimeoutError
            from frappe.utils.synchronization import filelock

            try:
                with filelock(self.TOKEN_REFRESH_LOCK_NAME, timeout=self.TOKEN_REFRESH_LOCK_TIMEOUT):
                    # Double-check cache inside lock - another process may have refreshed.
                    # Must validate EXPIRY, not just existence: we only reached Step 3
                    # because the cached token was already determined expired, so a bare
                    # existence check would return that same stale token and skip the
                    # refresh entirely.
                    fresh_token = self._get_valid_cached_token(now)
                    if fresh_token:
                        frappe.logger().debug("Token refreshed by another process, using cached token")
                        return fresh_token

                    # Proceed with refresh
                    return self._refresh_access_token(refresh_token)
            except LockTimeoutError:
                # Lock held by another process - check if they refreshed (valid token only)
                fresh_token = self._get_valid_cached_token(now)
                if fresh_token:
                    frappe.logger().debug("Token refreshed by another process, using cached token")
                    return fresh_token
                raise PontoAuthenticationError(
                    "Token refresh in progress by another process. Please retry.",
                    details={"action": "retry_after_seconds", "retry_after": 2},
                )

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
        except Exception as e:
            # Log unexpected errors but don't expose them as authorization failures
            frappe.logger().warning(f"Unexpected error checking Ponto authorization: {e}")
            return False


def get_oauth2_service() -> PontoOAuth2Service:
    """
    Factory function for OAuth2 service.

    Returns:
        PontoOAuth2Service instance
    """
    return PontoOAuth2Service()
