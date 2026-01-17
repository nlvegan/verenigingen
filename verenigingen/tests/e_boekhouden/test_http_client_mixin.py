"""
Tests for EBoekhoudenHTTPClientMixin

Tests for the HTTP client mixin including:
- Token caching and expiry tracking
- Automatic token refresh on 401/403 responses
- Retry mechanism with exponential backoff
- Consistent error handling
"""

import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from requests.exceptions import ConnectionError, RequestException, Timeout


class TestHTTPClientMixinTokenManagement(unittest.TestCase):
    """Tests for token management functionality"""

    def setUp(self):
        """Set up test fixtures with mocked settings"""
        self.mock_settings = MagicMock()
        self.mock_settings.api_url = "https://api.e-boekhouden.nl"
        self.mock_settings.get_password.return_value = "test_api_token"
        self.mock_settings.source_application = "Test App"

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_token_is_expired_when_none(self, mock_frappe):
        """Test that missing token is considered expired"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        client = TestClient(self.mock_settings)
        client._session_token = None
        client._token_obtained_at = None

        self.assertTrue(client._token_is_expired())

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_token_is_expired_when_old(self, mock_frappe):
        """Test that token is expired after TTL"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        client = TestClient(self.mock_settings)
        client._session_token = "test_token"
        # Token obtained 60 minutes ago (exceeds 55 min TTL)
        client._token_obtained_at = datetime.now() - timedelta(minutes=60)

        self.assertTrue(client._token_is_expired())

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_token_is_valid_when_recent(self, mock_frappe):
        """Test that recent token is considered valid"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        client = TestClient(self.mock_settings)
        client._session_token = "test_token"
        # Token obtained 30 minutes ago (within 55 min TTL)
        client._token_obtained_at = datetime.now() - timedelta(minutes=30)

        self.assertFalse(client._token_is_expired())

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_invalidate_token(self, mock_frappe):
        """Test token invalidation"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        client = TestClient(self.mock_settings)
        client._session_token = "test_token"
        client._token_obtained_at = datetime.now()

        client.invalidate_token()

        self.assertIsNone(client._session_token)
        self.assertIsNone(client._token_obtained_at)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_get_session_token_caches_token(self, mock_frappe, mock_requests):
        """Test that session token is cached"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        # Mock successful session response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "new_session_token"}
        mock_requests.post.return_value = mock_response

        client = TestClient(self.mock_settings)

        # First call should get new token
        token1 = client._get_session_token()
        self.assertEqual(token1, "new_session_token")
        self.assertEqual(mock_requests.post.call_count, 1)

        # Second call should use cached token
        token2 = client._get_session_token()
        self.assertEqual(token2, "new_session_token")
        # Should not make another request
        self.assertEqual(mock_requests.post.call_count, 1)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_get_session_token_refreshes_on_expiry(self, mock_frappe, mock_requests):
        """Test that expired token is refreshed"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        # Mock successful session responses
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "refreshed_token"}
        mock_requests.post.return_value = mock_response

        client = TestClient(self.mock_settings)

        # Set expired token
        client._session_token = "old_token"
        client._token_obtained_at = datetime.now() - timedelta(minutes=60)

        # Should get new token since old one expired
        token = client._get_session_token()
        self.assertEqual(token, "refreshed_token")
        self.assertEqual(mock_requests.post.call_count, 1)


class TestHTTPClientMixinRetryMechanism(unittest.TestCase):
    """Tests for retry mechanism with exponential backoff"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_settings = MagicMock()
        self.mock_settings.api_url = "https://api.e-boekhouden.nl"
        self.mock_settings.get_password.return_value = "test_api_token"
        self.mock_settings.source_application = "Test App"

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.time.sleep")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_retry_on_429_rate_limit(self, mock_frappe, mock_requests, mock_sleep):
        """Test retry on 429 rate limit response"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        # Mock session token
        mock_session_response = MagicMock()
        mock_session_response.status_code = 200
        mock_session_response.json.return_value = {"token": "test_token"}
        mock_requests.post.return_value = mock_session_response

        # First call returns 429, then success
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"data": "success"}

        mock_requests.get.side_effect = [rate_limit_response, success_response]

        client = TestClient(self.mock_settings)
        response = client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        # Verify retry happened
        self.assertEqual(mock_requests.get.call_count, 2)
        self.assertEqual(response.status_code, 200)

        # Verify sleep was called for backoff
        mock_sleep.assert_called()

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.time.sleep")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_retry_on_5xx_server_error(self, mock_frappe, mock_requests, mock_sleep):
        """Test retry on 5xx server error responses"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        # Mock session token
        mock_session_response = MagicMock()
        mock_session_response.status_code = 200
        mock_session_response.json.return_value = {"token": "test_token"}
        mock_requests.post.return_value = mock_session_response

        # First two calls return 503, then success
        server_error = MagicMock()
        server_error.status_code = 503

        success_response = MagicMock()
        success_response.status_code = 200

        mock_requests.get.side_effect = [server_error, server_error, success_response]

        client = TestClient(self.mock_settings)
        response = client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        # Verify retries happened
        self.assertEqual(mock_requests.get.call_count, 3)
        self.assertEqual(response.status_code, 200)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.time.sleep")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_token_refresh_on_401(self, mock_frappe, mock_requests, mock_sleep):
        """Test automatic token refresh on 401 response"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        # Mock session token responses
        mock_session_response = MagicMock()
        mock_session_response.status_code = 200
        mock_session_response.json.return_value = {"token": "new_token"}
        mock_requests.post.return_value = mock_session_response

        # First call returns 401, then success after token refresh
        unauthorized_response = MagicMock()
        unauthorized_response.status_code = 401

        success_response = MagicMock()
        success_response.status_code = 200

        mock_requests.get.side_effect = [unauthorized_response, success_response]

        client = TestClient(self.mock_settings)
        # Set an existing token to be invalidated
        client._session_token = "old_token"
        client._token_obtained_at = datetime.now()

        response = client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        # Verify token was refreshed
        self.assertEqual(response.status_code, 200)
        # Should have called post once for session (only refresh, since existing token was valid)
        # The initial request uses the existing token, only after 401 does it refresh
        self.assertEqual(mock_requests.post.call_count, 1)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.time.sleep")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_timeout_retry(self, mock_frappe, mock_requests, mock_sleep):
        """Test retry on timeout exception"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        # Mock session token
        mock_session_response = MagicMock()
        mock_session_response.status_code = 200
        mock_session_response.json.return_value = {"token": "test_token"}
        mock_requests.post.return_value = mock_session_response

        # First call times out, then success
        success_response = MagicMock()
        success_response.status_code = 200

        mock_requests.get.side_effect = [Timeout("Connection timed out"), success_response]

        client = TestClient(self.mock_settings)
        response = client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        # Verify retry happened
        self.assertEqual(mock_requests.get.call_count, 2)
        self.assertEqual(response.status_code, 200)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.time.sleep")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_connection_error_retry(self, mock_frappe, mock_requests, mock_sleep):
        """Test retry on connection error"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        # Mock session token
        mock_session_response = MagicMock()
        mock_session_response.status_code = 200
        mock_session_response.json.return_value = {"token": "test_token"}
        mock_requests.post.return_value = mock_session_response

        # First call fails, then success
        success_response = MagicMock()
        success_response.status_code = 200

        mock_requests.get.side_effect = [ConnectionError("Connection failed"), success_response]

        client = TestClient(self.mock_settings)
        response = client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        # Verify retry happened
        self.assertEqual(mock_requests.get.call_count, 2)
        self.assertEqual(response.status_code, 200)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.time.sleep")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_max_retries_exceeded(self, mock_frappe, mock_requests, mock_sleep):
        """Test that exception is raised after max retries"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        # Mock session token
        mock_session_response = MagicMock()
        mock_session_response.status_code = 200
        mock_session_response.json.return_value = {"token": "test_token"}
        mock_requests.post.return_value = mock_session_response

        # All calls timeout
        mock_requests.get.side_effect = Timeout("Connection timed out")

        client = TestClient(self.mock_settings)

        with self.assertRaises(Timeout):
            client._request_with_retry("GET", "https://api.e-boekhouden.nl/v1/test")

        # Verify all retries were attempted (MAX_RETRIES + 1 attempts)
        self.assertEqual(mock_requests.get.call_count, 4)  # 3 retries + 1 initial


class TestHTTPClientMixinSimpleRequest(unittest.TestCase):
    """Tests for _make_simple_request() convenience method"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_settings = MagicMock()
        self.mock_settings.api_url = "https://api.e-boekhouden.nl"
        self.mock_settings.get_password.return_value = "test_api_token"
        self.mock_settings.source_application = "Test App"

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_simple_request_success(self, mock_frappe, mock_requests):
        """Test successful simple request returns tuple"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        # Mock session token
        mock_session_response = MagicMock()
        mock_session_response.status_code = 200
        mock_session_response.json.return_value = {"token": "test_token"}
        mock_requests.post.return_value = mock_session_response

        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"data": "success"}'
        mock_requests.get.return_value = mock_response

        client = TestClient(self.mock_settings)
        success, data, status_code = client._make_simple_request(
            "GET", "https://api.e-boekhouden.nl/v1/test"
        )

        self.assertTrue(success)
        self.assertEqual(data, '{"data": "success"}')
        self.assertEqual(status_code, 200)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_simple_request_failure(self, mock_frappe, mock_requests):
        """Test failed simple request returns error tuple"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        # Mock session token
        mock_session_response = MagicMock()
        mock_session_response.status_code = 200
        mock_session_response.json.return_value = {"token": "test_token"}
        mock_requests.post.return_value = mock_session_response

        # Mock error response
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not found"
        mock_requests.get.return_value = mock_response

        client = TestClient(self.mock_settings)
        success, data, status_code = client._make_simple_request(
            "GET", "https://api.e-boekhouden.nl/v1/test"
        )

        self.assertFalse(success)
        self.assertIn("404", data)
        self.assertEqual(status_code, 404)

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.requests")
    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_simple_request_timeout(self, mock_frappe, mock_requests):
        """Test timeout in simple request returns error tuple"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        # Mock session token
        mock_session_response = MagicMock()
        mock_session_response.status_code = 200
        mock_session_response.json.return_value = {"token": "test_token"}
        mock_requests.post.return_value = mock_session_response

        # All requests timeout
        mock_requests.get.side_effect = Timeout("Connection timed out")

        client = TestClient(self.mock_settings)
        success, data, status_code = client._make_simple_request(
            "GET", "https://api.e-boekhouden.nl/v1/test"
        )

        self.assertFalse(success)
        self.assertIn("timeout", data.lower())
        self.assertEqual(status_code, 0)


class TestHTTPClientMixinInitialization(unittest.TestCase):
    """Tests for client initialization"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_settings = MagicMock()
        self.mock_settings.api_url = "https://api.e-boekhouden.nl"
        self.mock_settings.get_password.return_value = "test_api_token"
        self.mock_settings.source_application = "Test App"

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_raises_on_missing_api_token(self, mock_frappe):
        """Test that ValueError is raised when API token is missing"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings
        self.mock_settings.get_password.return_value = None

        with self.assertRaises(ValueError) as context:
            TestClient(self.mock_settings)

        self.assertIn("API token", str(context.exception))

    @patch("verenigingen.e_boekhouden.utils.http_client_mixin.frappe")
    def test_url_normalization(self, mock_frappe):
        """Test that URL is normalized properly"""
        from verenigingen.e_boekhouden.utils.http_client_mixin import (
            EBoekhoudenHTTPClientMixin,
        )

        class TestClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings):
                self._init_http_client(settings)

        mock_frappe.get_single.return_value = self.mock_settings

        # Test trailing slash removal
        self.mock_settings.api_url = "https://api.e-boekhouden.nl/"
        client = TestClient(self.mock_settings)
        self.assertEqual(client.base_url, "https://api.e-boekhouden.nl")

        # Test https prefix addition
        self.mock_settings.api_url = "api.e-boekhouden.nl"
        client = TestClient(self.mock_settings)
        self.assertEqual(client.base_url, "https://api.e-boekhouden.nl")


if __name__ == "__main__":
    unittest.main()
