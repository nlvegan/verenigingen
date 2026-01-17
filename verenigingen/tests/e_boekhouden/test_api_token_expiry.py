"""
Tests for E-Boekhouden REST Client Token Expiry Handling

This module tests the token expiry tracking functionality added to
EBoekhoudenRESTClient to ensure tokens are properly refreshed before
they expire during long-running migrations.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import frappe


class TestTokenExpiryTracking(unittest.TestCase):
    """Test cases for token expiry tracking in EBoekhoudenRESTClient."""

    def setUp(self):
        """Set up test fixtures."""
        # We need to mock the settings since we may not have real credentials
        self.mock_settings = MagicMock()
        self.mock_settings.api_url = "https://api.e-boekhouden.nl"
        self.mock_settings.source_application = "Test"
        self.mock_settings.get_password.return_value = "test-api-token"

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_fresh_client_has_no_token(self, mock_requests):
        """A newly created client should have no cached token."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        client = EBoekhoudenRESTClient(settings=self.mock_settings)

        self.assertIsNone(client._session_token)
        self.assertIsNone(client._token_obtained_at)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_token_is_expired_returns_true_when_no_token(self, mock_requests):
        """_token_is_expired should return True when no token exists."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        client = EBoekhoudenRESTClient(settings=self.mock_settings)

        self.assertTrue(client._token_is_expired())

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_token_is_expired_returns_true_when_token_but_no_timestamp(self, mock_requests):
        """_token_is_expired should return True when token exists but no timestamp."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        client._session_token = "some-token"
        client._token_obtained_at = None

        self.assertTrue(client._token_is_expired())

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_token_is_expired_returns_false_when_token_is_fresh(self, mock_requests):
        """_token_is_expired should return False when token was just obtained."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        client._session_token = "valid-token"
        client._token_obtained_at = datetime.now()  # Just obtained

        self.assertFalse(client._token_is_expired())

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_token_is_expired_returns_true_after_ttl_exceeded(self, mock_requests):
        """_token_is_expired should return True when TTL has been exceeded."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        client._session_token = "old-token"
        # Set token obtained time to 56 minutes ago (past 55 min TTL)
        client._token_obtained_at = datetime.now() - timedelta(minutes=56)

        self.assertTrue(client._token_is_expired())

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_token_is_not_expired_just_before_ttl(self, mock_requests):
        """_token_is_expired should return False just before TTL."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        client._session_token = "valid-token"
        # Set token obtained time to 54 minutes ago (just before 55 min TTL)
        client._token_obtained_at = datetime.now() - timedelta(minutes=54)

        self.assertFalse(client._token_is_expired())

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_get_session_token_acquires_new_token_when_none_exists(self, mock_requests):
        """_get_session_token should acquire new token when none is cached."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock successful token response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "new-session-token"}
        mock_requests.post.return_value = mock_response

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        token = client._get_session_token()

        self.assertEqual(token, "new-session-token")
        self.assertEqual(client._session_token, "new-session-token")
        self.assertIsNotNone(client._token_obtained_at)
        mock_requests.post.assert_called_once()

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_get_session_token_returns_cached_token_when_valid(self, mock_requests):
        """_get_session_token should return cached token without API call."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        client._session_token = "cached-token"
        client._token_obtained_at = datetime.now()  # Fresh token

        token = client._get_session_token()

        self.assertEqual(token, "cached-token")
        # Should NOT make any API calls
        mock_requests.post.assert_not_called()

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_get_session_token_refreshes_expired_token(self, mock_requests):
        """_get_session_token should refresh token when expired."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock successful token response for refresh
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "refreshed-token"}
        mock_requests.post.return_value = mock_response

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        client._session_token = "old-expired-token"
        client._token_obtained_at = datetime.now() - timedelta(minutes=60)  # Expired

        token = client._get_session_token()

        self.assertEqual(token, "refreshed-token")
        self.assertEqual(client._session_token, "refreshed-token")
        # Should have made API call to refresh
        mock_requests.post.assert_called_once()

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_invalidate_token_clears_token_and_timestamp(self, mock_requests):
        """invalidate_token should clear both token and timestamp."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        client._session_token = "some-token"
        client._token_obtained_at = datetime.now()

        client.invalidate_token()

        self.assertIsNone(client._session_token)
        self.assertIsNone(client._token_obtained_at)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_invalidate_token_forces_refresh_on_next_call(self, mock_requests):
        """After invalidate_token, next _get_session_token should make API call."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock successful token response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "new-token-after-invalidate"}
        mock_requests.post.return_value = mock_response

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        client._session_token = "old-token"
        client._token_obtained_at = datetime.now()  # Still valid

        # Invalidate the token
        client.invalidate_token()

        # Next call should fetch new token
        token = client._get_session_token()

        self.assertEqual(token, "new-token-after-invalidate")
        mock_requests.post.assert_called_once()

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_token_ttl_class_constant_exists(self, mock_requests):
        """TOKEN_TTL_MINUTES class constant should exist and be reasonable."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        self.assertTrue(hasattr(EBoekhoudenRESTClient, "TOKEN_TTL_MINUTES"))
        self.assertEqual(EBoekhoudenRESTClient.TOKEN_TTL_MINUTES, 55)
        # Should be less than actual expiry (60 min) to provide safety margin
        self.assertLess(EBoekhoudenRESTClient.TOKEN_TTL_MINUTES, 60)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_get_session_token_handles_api_failure(self, mock_requests):
        """_get_session_token should return None on API failure."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock failed token response
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_requests.post.return_value = mock_response

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        token = client._get_session_token()

        self.assertIsNone(token)
        self.assertIsNone(client._session_token)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_get_session_token_handles_network_exception(self, mock_requests):
        """_get_session_token should handle network exceptions gracefully."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock network exception
        mock_requests.post.side_effect = Exception("Network error")

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        token = client._get_session_token()

        self.assertIsNone(token)


class TestTokenExpiryIntegrationWithAPIOperations(unittest.TestCase):
    """Integration tests for token expiry during API operations."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_settings = MagicMock()
        self.mock_settings.api_url = "https://api.e-boekhouden.nl"
        self.mock_settings.source_application = "Test"
        self.mock_settings.get_password.return_value = "test-api-token"

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_get_headers_triggers_token_acquisition(self, mock_requests):
        """_get_headers should trigger token acquisition if none exists."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock successful token response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "header-token"}
        mock_requests.post.return_value = mock_response

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        headers = client._get_headers()

        self.assertIn("Authorization", headers)
        self.assertEqual(headers["Authorization"], "header-token")
        mock_requests.post.assert_called_once()

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_get_mutations_refreshes_expired_token(self, mock_requests):
        """get_mutations should refresh token if expired before API call."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Set up mock responses
        token_response = Mock()
        token_response.status_code = 200
        token_response.json.return_value = {"token": "fresh-token"}

        mutations_response = Mock()
        mutations_response.status_code = 200
        mutations_response.json.return_value = {"items": []}

        # First call (POST) returns token, subsequent GET returns mutations
        mock_requests.post.return_value = token_response
        mock_requests.get.return_value = mutations_response

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        # Set expired token
        client._session_token = "expired-token"
        client._token_obtained_at = datetime.now() - timedelta(minutes=60)

        result = client.get_mutations()

        # Should have refreshed token
        mock_requests.post.assert_called_once()
        # And made the API call with fresh token
        mock_requests.get.assert_called_once()
        self.assertTrue(result["success"])


class TestRetryMechanism(unittest.TestCase):
    """Test cases for retry mechanism in EBoekhoudenRESTClient."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_settings = MagicMock()
        self.mock_settings.api_url = "https://api.e-boekhouden.nl"
        self.mock_settings.source_application = "Test"
        self.mock_settings.get_password.return_value = "test-api-token"

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_retry_constants_exist(self, mock_requests):
        """Retry configuration constants should exist."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        self.assertTrue(hasattr(EBoekhoudenRESTClient, "MAX_RETRIES"))
        self.assertTrue(hasattr(EBoekhoudenRESTClient, "RETRY_BACKOFF_FACTOR"))
        self.assertTrue(hasattr(EBoekhoudenRESTClient, "RETRY_STATUS_CODES"))
        self.assertTrue(hasattr(EBoekhoudenRESTClient, "AUTH_REFRESH_STATUS_CODES"))

        self.assertEqual(EBoekhoudenRESTClient.MAX_RETRIES, 3)
        self.assertEqual(EBoekhoudenRESTClient.RETRY_BACKOFF_FACTOR, 1.0)
        self.assertIn(429, EBoekhoudenRESTClient.RETRY_STATUS_CODES)
        self.assertIn(500, EBoekhoudenRESTClient.RETRY_STATUS_CODES)
        self.assertIn(401, EBoekhoudenRESTClient.AUTH_REFRESH_STATUS_CODES)
        self.assertIn(403, EBoekhoudenRESTClient.AUTH_REFRESH_STATUS_CODES)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.time.sleep")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_retry_on_500_error(self, mock_requests, mock_sleep):
        """Should retry on 500 server error with exponential backoff."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock token response
        token_response = Mock()
        token_response.status_code = 200
        token_response.json.return_value = {"token": "test-token"}
        mock_requests.post.return_value = token_response

        # First 2 calls return 500, third succeeds
        error_response = Mock()
        error_response.status_code = 500
        error_response.text = "Internal Server Error"
        error_response.headers.get.return_value = None  # No Retry-After header

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {"items": []}

        mock_requests.get.side_effect = [error_response, error_response, success_response]

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        response = client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        self.assertEqual(response.status_code, 200)
        # Should have called get 3 times (2 retries + 1 success)
        self.assertEqual(mock_requests.get.call_count, 3)
        # Should have slept twice for backoff
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.time.sleep")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_retry_on_429_rate_limit(self, mock_requests, mock_sleep):
        """Should retry on 429 rate limit error."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock token response
        token_response = Mock()
        token_response.status_code = 200
        token_response.json.return_value = {"token": "test-token"}
        mock_requests.post.return_value = token_response

        # First call returns 429, second succeeds
        rate_limit_response = Mock()
        rate_limit_response.status_code = 429
        rate_limit_response.text = "Too Many Requests"
        rate_limit_response.headers.get.return_value = None  # No Retry-After header

        success_response = Mock()
        success_response.status_code = 200

        mock_requests.get.side_effect = [rate_limit_response, success_response]

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        response = client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_requests.get.call_count, 2)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.time.sleep")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_max_retries_exhausted(self, mock_requests, mock_sleep):
        """Should return error response after max retries exhausted."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock token response
        token_response = Mock()
        token_response.status_code = 200
        token_response.json.return_value = {"token": "test-token"}
        mock_requests.post.return_value = token_response

        # All calls return 500
        error_response = Mock()
        error_response.status_code = 500
        error_response.text = "Internal Server Error"
        error_response.headers.get.return_value = None  # No Retry-After header
        mock_requests.get.return_value = error_response

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        response = client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        # Should return the error response after max retries
        self.assertEqual(response.status_code, 500)
        # Should have called get MAX_RETRIES + 1 times
        self.assertEqual(mock_requests.get.call_count, client.MAX_RETRIES + 1)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_401_triggers_token_refresh(self, mock_requests):
        """Should refresh token on 401 and retry once."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock token responses
        token_response = Mock()
        token_response.status_code = 200
        token_response.json.return_value = {"token": "new-token"}
        mock_requests.post.return_value = token_response

        # First call returns 401, after token refresh second succeeds
        auth_error_response = Mock()
        auth_error_response.status_code = 401
        auth_error_response.text = "Unauthorized"

        success_response = Mock()
        success_response.status_code = 200

        mock_requests.get.side_effect = [auth_error_response, success_response]

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        # Set an existing token that will be invalidated
        client._session_token = "old-token"
        client._token_obtained_at = datetime.now()

        response = client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        self.assertEqual(response.status_code, 200)
        # Should have called get twice (401 + retry)
        self.assertEqual(mock_requests.get.call_count, 2)
        # Should have called post once (refresh only - initial token was manually set)
        self.assertEqual(mock_requests.post.call_count, 1)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_401_only_refreshes_once(self, mock_requests):
        """Should only refresh token once on 401, not retry indefinitely."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock token responses
        token_response = Mock()
        token_response.status_code = 200
        token_response.json.return_value = {"token": "new-token"}
        mock_requests.post.return_value = token_response

        # Both calls return 401 (token refresh doesn't help)
        auth_error_response = Mock()
        auth_error_response.status_code = 401
        auth_error_response.text = "Unauthorized"
        mock_requests.get.return_value = auth_error_response

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        client._session_token = "old-token"
        client._token_obtained_at = datetime.now()

        response = client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        # Should return 401 after one retry
        self.assertEqual(response.status_code, 401)
        # Should have called get only twice (original + 1 retry after refresh)
        self.assertEqual(mock_requests.get.call_count, 2)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.time.sleep")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_timeout_triggers_retry(self, mock_requests, mock_sleep):
        """Should retry on connection timeout."""
        from requests.exceptions import Timeout

        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock token response
        token_response = Mock()
        token_response.status_code = 200
        token_response.json.return_value = {"token": "test-token"}
        mock_requests.post.return_value = token_response

        # First call times out, second succeeds
        success_response = Mock()
        success_response.status_code = 200
        mock_requests.get.side_effect = [Timeout("Connection timed out"), success_response]

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        response = client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_requests.get.call_count, 2)
        # Should have slept once for backoff
        self.assertEqual(mock_sleep.call_count, 1)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.time.sleep")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_connection_error_triggers_retry(self, mock_requests, mock_sleep):
        """Should retry on connection error."""
        from requests.exceptions import ConnectionError

        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock token response
        token_response = Mock()
        token_response.status_code = 200
        token_response.json.return_value = {"token": "test-token"}
        mock_requests.post.return_value = token_response

        # First call has connection error, second succeeds
        success_response = Mock()
        success_response.status_code = 200
        mock_requests.get.side_effect = [
            ConnectionError("Connection refused"),
            success_response,
        ]

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        response = client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_requests.get.call_count, 2)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.time.sleep")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_exponential_backoff_delays(self, mock_requests, mock_sleep):
        """Should use exponential backoff delays."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock token response
        token_response = Mock()
        token_response.status_code = 200
        token_response.json.return_value = {"token": "test-token"}
        mock_requests.post.return_value = token_response

        # All calls return 500 except last
        error_response = Mock()
        error_response.status_code = 500
        error_response.headers.get.return_value = None  # No Retry-After header

        success_response = Mock()
        success_response.status_code = 200

        mock_requests.get.side_effect = [
            error_response,
            error_response,
            error_response,
            success_response,
        ]

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        # Check exponential backoff: 1*2^0=1, 1*2^1=2, 1*2^2=4
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        self.assertEqual(sleep_calls, [1.0, 2.0, 4.0])

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    def test_non_retryable_error_not_retried(self, mock_requests):
        """Should not retry on non-retryable status codes like 404."""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import (
            EBoekhoudenRESTClient,
        )

        # Mock token response
        token_response = Mock()
        token_response.status_code = 200
        token_response.json.return_value = {"token": "test-token"}
        mock_requests.post.return_value = token_response

        # Return 404 (not in retry list)
        not_found_response = Mock()
        not_found_response.status_code = 404
        not_found_response.text = "Not Found"
        mock_requests.get.return_value = not_found_response

        client = EBoekhoudenRESTClient(settings=self.mock_settings)
        response = client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        # Should return immediately without retry
        self.assertEqual(response.status_code, 404)
        self.assertEqual(mock_requests.get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
