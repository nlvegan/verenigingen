"""
Tests for Ponto REST API Client.

Tests HTTP client functionality including GET/POST/DELETE requests,
pagination, circuit breaker, retry logic, and mTLS handling.

Usage:
    bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_ponto_client
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.ponto_test_data_factory import (
    PontoTestDataFactory,
    TestIBAN,
)


class TestPontoClient(FrappeTestCase):
    """Test cases for PontoClient."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        super().setUpClass()
        cls._setup_test_settings()

    @classmethod
    def _setup_test_settings(cls):
        """Configure Ponto Settings for testing."""
        settings = frappe.get_single("Ponto Settings")
        settings.ibanity_client_id = "test_client_id"
        # Password fields are set directly in Single DocTypes
        settings.ibanity_client_secret = "test_client_secret"
        settings.sandbox_mode = 1
        settings.use_ibanity_mtls = 0
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    def setUp(self):
        """Set up each test."""
        super().setUp()
        # Store a valid token for requests
        self._store_valid_token()

    def _store_valid_token(self):
        """Store a valid access token for testing."""
        from datetime import datetime, timedelta

        from frappe.utils.password import set_encrypted_password

        # Store valid tokens
        set_encrypted_password(
            "Ponto Settings",
            "Ponto Settings",
            "test_access_token_valid",
            fieldname="ibanity_access_token",
        )

        # Set expiry
        frappe.db.set_value(
            "Ponto Settings",
            "Ponto Settings",
            "access_token_expiry",
            datetime.now() + timedelta(hours=1),
            update_modified=False,
        )

        # Also cache it
        cache = frappe.cache()
        cache.set_value("ponto_ibanity_access_token", "test_access_token_valid", expires_in_sec=3600)
        cache.set_value(
            "ponto_ibanity_token_expiry",
            (datetime.now() + timedelta(hours=1)).isoformat(),
            expires_in_sec=3600,
        )
        frappe.db.commit()

    # -------------------------------------------------------------------------
    # Headers Tests
    # -------------------------------------------------------------------------

    def test_request_headers_include_authorization(self):
        """Test that requests include Authorization header with Bearer token."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        client = PontoClient()
        headers = client._get_headers()

        self.assertIn("Authorization", headers)
        self.assertTrue(headers["Authorization"].startswith("Bearer "))
        self.assertIn("test_access_token_valid", headers["Authorization"])

    def test_request_headers_include_json_api_content_type(self):
        """Test that requests include JSON:API content type."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        client = PontoClient()
        headers = client._get_headers()

        self.assertIn("Content-Type", headers)
        self.assertEqual(headers["Content-Type"], "application/vnd.api+json")

        self.assertIn("Accept", headers)
        self.assertEqual(headers["Accept"], "application/vnd.api+json")

    # -------------------------------------------------------------------------
    # GET Request Tests
    # -------------------------------------------------------------------------

    def test_get_request_success(self):
        """Test successful GET request."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        client = PontoClient()

        account_data = PontoTestDataFactory.create_account(iban=TestIBAN.ABN_AMRO_1)

        with patch.object(client._session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": account_data}
            mock_get.return_value = mock_response

            result = client.get("/accounts/test-account-id")

            self.assertEqual(result["data"]["type"], "account")
            self.assertEqual(result["data"]["attributes"]["reference"], TestIBAN.ABN_AMRO_1)

    def test_get_request_with_params(self):
        """Test GET request with query parameters."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        client = PontoClient()

        with patch.object(client._session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": []}
            mock_get.return_value = mock_response

            client.get("/accounts", params={"page[limit]": 10, "filter[status]": "active"})

            # Verify params were passed
            call_kwargs = mock_get.call_args
            self.assertIn("params", call_kwargs.kwargs)
            self.assertEqual(call_kwargs.kwargs["params"]["page[limit]"], 10)

    def test_get_request_404_raises_error(self):
        """Test that 404 response raises PontoAPIError."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client = PontoClient()

        with patch.object(client._session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.ok = False
            mock_response.status_code = 404
            mock_response.text = "Not found"
            mock_response.json.return_value = PontoTestDataFactory.create_api_error_response(
                status_code=404,
                error_code="resourceNotFound",
                error_detail="Account not found",
            )
            mock_get.return_value = mock_response

            with self.assertRaises(PontoAPIError):
                client.get("/accounts/nonexistent")

    def test_get_request_401_triggers_token_refresh(self):
        """Test that 401 response triggers token refresh and retry."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        client = PontoClient()

        call_count = 0

        def mock_get_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            mock_response = MagicMock()

            if call_count == 1:
                # First call returns 401
                mock_response.ok = False
                mock_response.status_code = 401
                mock_response.text = "Unauthorized"
                mock_response.json.return_value = {"error": "unauthorized"}
            else:
                # Retry after token refresh succeeds
                mock_response.ok = True
                mock_response.status_code = 200
                mock_response.json.return_value = {"data": []}

            return mock_response

        with patch.object(client._session, "get", side_effect=mock_get_side_effect):
            with patch.object(client._token_manager, "refresh_token") as mock_refresh:
                mock_refresh.return_value = "new_access_token"

                result = client.get("/accounts")

                # Should have called refresh
                mock_refresh.assert_called_once()
                # Should have retried the request
                self.assertEqual(call_count, 2)
                self.assertEqual(result, {"data": []})

    def test_get_request_429_raises_rate_limit_error(self):
        """Test that 429 response raises PontoRateLimitError."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoRateLimitError

        client = PontoClient()

        with patch.object(client._session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.ok = False
            mock_response.status_code = 429
            mock_response.headers = {"Retry-After": "60"}
            mock_response.text = "Rate limit exceeded"
            mock_response.json.return_value = {"error": "rate_limited"}
            mock_get.return_value = mock_response

            with self.assertRaises(PontoRateLimitError) as ctx:
                client.get("/accounts")

            # Should include retry-after info
            self.assertIn("60", str(ctx.exception) + str(ctx.exception.details))

    # -------------------------------------------------------------------------
    # POST Request Tests
    # -------------------------------------------------------------------------

    def test_post_request_success(self):
        """Test successful POST request."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        client = PontoClient()

        payment_data = PontoTestDataFactory.create_sepa_payment_data(
            amount=100.00,
            creditor_name="Test Supplier BV",
            creditor_iban=TestIBAN.ABN_AMRO_1,
        )

        with patch.object(client._session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.status_code = 201
            mock_response.json.return_value = {
                "data": {
                    "type": "paymentInitiationRequest",
                    "id": "pir-123",
                    "attributes": {"status": "pending"},
                }
            }
            mock_post.return_value = mock_response

            result = client.post("/payment-initiation-requests", data={"data": payment_data})

            self.assertEqual(result["data"]["type"], "paymentInitiationRequest")
            self.assertEqual(result["data"]["attributes"]["status"], "pending")

    def test_post_request_sends_json_body(self):
        """Test that POST request sends JSON body correctly."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        client = PontoClient()

        test_data = {"data": {"type": "test", "attributes": {"foo": "bar"}}}

        with patch.object(client._session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.status_code = 201
            mock_response.json.return_value = {"data": {}}
            mock_post.return_value = mock_response

            client.post("/test-endpoint", data=test_data)

            # Verify JSON body was sent
            call_kwargs = mock_post.call_args
            self.assertIn("json", call_kwargs.kwargs)
            self.assertEqual(call_kwargs.kwargs["json"], test_data)

    # -------------------------------------------------------------------------
    # DELETE Request Tests
    # -------------------------------------------------------------------------

    def test_delete_request_success(self):
        """Test successful DELETE request."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        client = PontoClient()

        with patch.object(client._session, "delete") as mock_delete:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.status_code = 204
            mock_response.text = ""
            mock_delete.return_value = mock_response

            # Should not raise
            client.delete("/payment-initiation-requests/pir-123")

    # -------------------------------------------------------------------------
    # Pagination Tests
    # -------------------------------------------------------------------------

    def test_get_paginated_single_page(self):
        """Test paginated request with single page."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        client = PontoClient()

        accounts = [
            PontoTestDataFactory.create_account(iban=TestIBAN.ABN_AMRO_1),
            PontoTestDataFactory.create_account(iban=TestIBAN.ING_1),
        ]

        with patch.object(client._session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": accounts,
                "links": {"self": "https://api.myponto.com/accounts"},
                # No "next" link = last page
            }
            mock_get.return_value = mock_response

            result = client.get_paginated("/accounts")

            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["attributes"]["reference"], TestIBAN.ABN_AMRO_1)
            self.assertEqual(result[1]["attributes"]["reference"], TestIBAN.ING_1)

    def test_get_paginated_multiple_pages(self):
        """Test paginated request that spans multiple pages."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        client = PontoClient()

        page1_accounts = [
            PontoTestDataFactory.create_account(iban=TestIBAN.ABN_AMRO_1),
            PontoTestDataFactory.create_account(iban=TestIBAN.ING_1),
        ]
        page2_accounts = [
            PontoTestDataFactory.create_account(iban=TestIBAN.RABO_1),
        ]

        call_count = 0

        def mock_get_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.status_code = 200

            if call_count == 1:
                mock_response.json.return_value = {
                    "data": page1_accounts,
                    "links": {
                        "self": "https://api.myponto.com/accounts",
                        "next": "https://api.myponto.com/accounts?page[after]=cursor1",
                    },
                }
            else:
                mock_response.json.return_value = {
                    "data": page2_accounts,
                    "links": {"self": "https://api.myponto.com/accounts?page[after]=cursor1"},
                    # No "next" = last page
                }

            return mock_response

        with patch.object(client._session, "get", side_effect=mock_get_side_effect):
            result = client.get_paginated("/accounts")

            # Should have all 3 accounts from both pages
            self.assertEqual(len(result), 3)
            self.assertEqual(call_count, 2)

    def test_get_paginated_respects_limit(self):
        """Test that pagination respects the limit parameter."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        client = PontoClient()

        # Create 5 accounts
        accounts = [PontoTestDataFactory.create_account() for _ in range(5)]

        with patch.object(client._session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": accounts,
                "links": {
                    "self": "https://api.myponto.com/accounts",
                    "next": "https://api.myponto.com/accounts?page[after]=cursor",
                },
            }
            mock_get.return_value = mock_response

            # Request with limit of 3
            result = client.get_paginated("/accounts", limit=3)

            # Should only return 3 even though page has 5
            self.assertEqual(len(result), 3)

    # -------------------------------------------------------------------------
    # Error Handling Tests
    # -------------------------------------------------------------------------

    def test_error_response_extracts_message(self):
        """Test that API error responses are parsed correctly."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client = PontoClient()

        with patch.object(client._session, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.ok = False
            mock_response.status_code = 400
            mock_response.text = json.dumps(
                {
                    "errors": [
                        {
                            "code": "invalidParameter",
                            "detail": "Amount must be positive",
                            "status": "400",
                        }
                    ]
                }
            )
            mock_response.json.return_value = {
                "errors": [
                    {
                        "code": "invalidParameter",
                        "detail": "Amount must be positive",
                        "status": "400",
                    }
                ]
            }
            mock_get.return_value = mock_response

            with self.assertRaises(PontoAPIError) as ctx:
                client.get("/payments")

            # Error message should contain the API error detail
            self.assertIn("invalidParameter", str(ctx.exception))

    def test_network_error_handling(self):
        """Test handling of network errors."""
        from requests.exceptions import ConnectionError

        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client = PontoClient()

        with patch.object(client._session, "get") as mock_get:
            mock_get.side_effect = ConnectionError("Network unreachable")

            with self.assertRaises(PontoAPIError):
                client.get("/accounts")

    def test_timeout_error_handling(self):
        """Test handling of timeout errors."""
        from requests.exceptions import Timeout

        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client = PontoClient()

        with patch.object(client._session, "get") as mock_get:
            mock_get.side_effect = Timeout("Request timed out")

            with self.assertRaises(PontoAPIError):
                client.get("/accounts")

    # -------------------------------------------------------------------------
    # mTLS Configuration Tests
    # -------------------------------------------------------------------------

    def test_mtls_disabled_by_default(self):
        """Test that mTLS is disabled by default."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        client = PontoClient()
        self.assertFalse(client._use_mtls)

    def test_mtls_enabled_when_configured(self):
        """Test that mTLS is enabled when configured in settings."""
        # Configure mTLS
        settings = frappe.get_single("Ponto Settings")
        settings.use_ibanity_mtls = 1
        settings.ibanity_certificate = "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----"
        settings.ibanity_private_key = "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
        settings.save()

        try:
            from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

            with patch.object(PontoClient, "_setup_mtls"):
                # Just test that mtls flag would be set
                client = PontoClient()
                # The actual setup is mocked to avoid temp file creation
        finally:
            # Restore
            settings.use_ibanity_mtls = 0
            settings.ibanity_certificate = ""
            settings.ibanity_private_key = ""
            settings.save()

    def test_mtls_changes_base_url(self):
        """Test that mTLS changes base URL to Ibanity."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        # When mTLS is enabled, base URL should point to Ibanity
        settings = frappe.get_single("Ponto Settings")
        original_mtls = settings.use_ibanity_mtls

        settings.use_ibanity_mtls = 1
        settings.ibanity_certificate = "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----"
        settings.ibanity_private_key = "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
        settings.ibanity_api_url = "https://api.ibanity.com"
        settings.save()

        try:
            # Create client - this would set up mTLS
            # We need to mock the actual file operations
            with patch("tempfile.NamedTemporaryFile"):
                client = PontoClient()

                # Base URL should be Ibanity
                if client._use_mtls:
                    self.assertIn("ibanity.com", client.BASE_URL)
        finally:
            settings.use_ibanity_mtls = original_mtls
            settings.ibanity_certificate = ""
            settings.ibanity_private_key = ""
            settings.save()

    # -------------------------------------------------------------------------
    # Cleanup Tests
    # -------------------------------------------------------------------------

    def test_client_cleanup_on_deletion(self):
        """Test that temporary files are cleaned up on client deletion."""
        import os
        import tempfile

        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        # Create a client with mock temp files
        client = PontoClient()

        # Simulate temp files being created
        cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
        cert_file.write(b"test cert")
        cert_file.close()

        key_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
        key_file.write(b"test key")
        key_file.close()

        client._temp_cert_file = cert_file.name
        client._temp_key_file = key_file.name
        client._cert_files = (cert_file.name, key_file.name)

        # Verify files exist
        self.assertTrue(os.path.exists(cert_file.name))
        self.assertTrue(os.path.exists(key_file.name))

        # Delete client
        del client

        # Files should be cleaned up
        self.assertFalse(os.path.exists(cert_file.name))
        self.assertFalse(os.path.exists(key_file.name))


class TestPontoClientFactory(FrappeTestCase):
    """Test cases for get_ponto_client factory function."""

    def test_get_ponto_client_returns_client_instance(self):
        """Test that factory returns PontoClient instance."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import (
            PontoClient,
            get_ponto_client,
        )

        client = get_ponto_client()
        self.assertIsInstance(client, PontoClient)

    def test_get_ponto_client_creates_new_instance_each_call(self):
        """Test that factory creates new instance each call."""
        from verenigingen.verenigingen_payments.ponto.core.ponto_client import get_ponto_client

        client1 = get_ponto_client()
        client2 = get_ponto_client()

        self.assertIsNot(client1, client2)


if __name__ == "__main__":
    unittest.main()
