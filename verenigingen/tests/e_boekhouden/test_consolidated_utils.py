"""
Tests for E-Boekhouden Consolidated Utilities

Tests the consolidated utility modules:
- ledger_utils: Canonical ledger resolution with auto-create
- bank_account_utils: Bank account resolution from ledger IDs
- date_utils: Fiscal year creation with race condition handling
- party_utils: Party account resolution with Vraagposten avoidance
- cost_center_utils: Cost center resolution with Magazine exclusion

Also tests:
- ensure_account_type_is_correct: Account type validation with auto_fix safety

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_consolidated_utils
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe


class MockFiscalYearResult:
    """Mock result that supports both dict and attribute access like frappe.db.sql results."""

    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __getattr__(self, key):
        if key.startswith("_"):
            raise AttributeError(key)
        return self._data.get(key)

    def get(self, key, default=None):
        return self._data.get(key, default)


class TestLedgerUtils(unittest.TestCase):
    """Tests for ledger_utils.py - canonical ledger resolution"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_info = []

    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.frappe")
    def test_get_ledger_mapping_returns_existing_mapping(self, mock_frappe):
        """Test that existing mapping is returned with both code and account"""
        from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import (
            get_ledger_mapping,
        )

        mock_frappe.db.get_value.return_value = {
            "ledger_code": "42902",
            "erpnext_account": "42902 - Revenue - NVV",
        }

        code, account = get_ledger_mapping("13201916", "NVV", self.debug_info)

        self.assertEqual(code, "42902")
        self.assertEqual(account, "42902 - Revenue - NVV")
        self.assertTrue(any("mapping found" in msg.lower() for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.frappe")
    def test_get_ledger_mapping_returns_none_for_empty_ledger_id(self, mock_frappe):
        """Test that None is returned for empty/None ledger_id"""
        from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import (
            get_ledger_mapping,
        )

        code, account = get_ledger_mapping(None, "NVV", self.debug_info)
        self.assertIsNone(code)
        self.assertIsNone(account)

        code, account = get_ledger_mapping("", "NVV", self.debug_info)
        self.assertIsNone(code)
        self.assertIsNone(account)

        mock_frappe.db.get_value.assert_not_called()

    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils._find_erpnext_account_by_code")
    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.frappe")
    def test_get_ledger_mapping_auto_links_account(self, mock_frappe, mock_find_account):
        """Test that auto-linking works when account not in mapping but code exists"""
        from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import (
            get_ledger_mapping,
        )

        # Mapping has code but no account
        mock_frappe.db.get_value.side_effect = [
            {"ledger_code": "42902", "erpnext_account": None},  # First call for mapping
            "LEDGER-001",  # Second call for docname in _update_mapping
        ]
        mock_find_account.return_value = "42902 - Revenue - NVV"

        code, account = get_ledger_mapping("13201916", "NVV", self.debug_info)

        self.assertEqual(code, "42902")
        self.assertEqual(account, "42902 - Revenue - NVV")

    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.frappe")
    def test_get_ledger_mapping_no_mapping_found(self, mock_frappe):
        """Test that None is returned when no mapping exists and auto_create=False"""
        from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import (
            get_ledger_mapping,
        )

        mock_frappe.db.get_value.return_value = None

        code, account = get_ledger_mapping("13201916", "NVV", self.debug_info, auto_create=False)

        self.assertIsNone(code)
        self.assertIsNone(account)
        self.assertTrue(any("no mapping found" in msg.lower() for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.frappe")
    def test_resolve_ledger_code_returns_code_or_fallback(self, mock_frappe):
        """Test resolve_ledger_code returns code or falls back to ledger_id"""
        from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import (
            resolve_ledger_code,
        )

        # Case 1: Mapping found
        mock_frappe.db.get_value.return_value = {"ledger_code": "42902", "erpnext_account": None}
        result = resolve_ledger_code("13201916", "NVV")
        self.assertEqual(result, "42902")

        # Case 2: No mapping - falls back to ledger_id
        mock_frappe.db.get_value.return_value = None
        result = resolve_ledger_code("13201916", "NVV")
        self.assertEqual(result, "13201916")

    def test_resolve_ledger_code_handles_none_input(self):
        """Test resolve_ledger_code returns None for None input"""
        from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import (
            resolve_ledger_code,
        )

        result = resolve_ledger_code(None, "NVV")
        self.assertIsNone(result)

    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.frappe")
    def test_get_ledger_mapping_denies_auto_create_without_permission(self, mock_frappe):
        """Test that auto_create is denied when user lacks permission"""
        from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import (
            get_ledger_mapping,
        )

        mock_frappe.db.get_value.return_value = None  # No existing mapping
        mock_frappe.has_permission.return_value = False  # User lacks permission
        mock_frappe.session.user = "test@example.com"

        code, account = get_ledger_mapping("13201916", "NVV", self.debug_info, auto_create=True)

        self.assertIsNone(code)
        self.assertIsNone(account)
        self.assertTrue(any("lacks permission" in msg.lower() for msg in self.debug_info))
        mock_frappe.has_permission.assert_called_once_with("E-Boekhouden Ledger Mapping", "create")


class TestBankAccountUtils(unittest.TestCase):
    """Tests for bank_account_utils.py - bank account resolution"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_info = []

    def test_resolve_bank_account_raises_on_empty_ledger_id(self):
        """Test that ValidationError is raised for empty ledger_id"""
        from verenigingen.e_boekhouden.utils.consolidated.bank_account_utils import (
            resolve_bank_account_for_ledger,
        )

        with self.assertRaises(frappe.ValidationError):
            resolve_bank_account_for_ledger(None, "NVV", debug_info=self.debug_info)

        with self.assertRaises(frappe.ValidationError):
            resolve_bank_account_for_ledger("", "NVV", debug_info=self.debug_info)

    @patch("verenigingen.e_boekhouden.utils.consolidated.bank_account_utils.get_ledger_mapping")
    @patch("verenigingen.e_boekhouden.utils.consolidated.bank_account_utils.frappe")
    def test_resolve_bank_account_returns_bank_type_account(self, mock_frappe, mock_get_mapping):
        """Test that Bank type accounts are returned"""
        from verenigingen.e_boekhouden.utils.consolidated.bank_account_utils import (
            resolve_bank_account_for_ledger,
        )

        mock_get_mapping.return_value = ("1100", "1100 - Bank ASN - NVV")
        mock_frappe.db.get_value.return_value = "Bank"

        result = resolve_bank_account_for_ledger("12345", "NVV", debug_info=self.debug_info)

        self.assertEqual(result, "1100 - Bank ASN - NVV")
        self.assertTrue(any("bank account" in msg.lower() for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.consolidated.bank_account_utils.get_ledger_mapping")
    @patch("verenigingen.e_boekhouden.utils.consolidated.bank_account_utils.frappe")
    def test_resolve_bank_account_returns_cash_type_account(self, mock_frappe, mock_get_mapping):
        """Test that Cash type accounts are also accepted"""
        from verenigingen.e_boekhouden.utils.consolidated.bank_account_utils import (
            resolve_bank_account_for_ledger,
        )

        mock_get_mapping.return_value = ("1000", "1000 - Cash - NVV")
        mock_frappe.db.get_value.return_value = "Cash"

        result = resolve_bank_account_for_ledger("12345", "NVV", debug_info=self.debug_info)

        self.assertEqual(result, "1000 - Cash - NVV")

    @patch("verenigingen.e_boekhouden.utils.consolidated.bank_account_utils._get_account_from_pattern")
    @patch("verenigingen.e_boekhouden.utils.consolidated.bank_account_utils._get_account_from_payment_config")
    @patch("verenigingen.e_boekhouden.utils.consolidated.bank_account_utils.get_ledger_mapping")
    @patch("verenigingen.e_boekhouden.utils.consolidated.bank_account_utils.frappe")
    def test_resolve_bank_account_rejects_non_bank_account(
        self, mock_frappe, mock_get_mapping, mock_payment_config, mock_pattern
    ):
        """Test that non-Bank/Cash accounts are rejected and fallbacks are tried"""
        from verenigingen.e_boekhouden.utils.consolidated.bank_account_utils import (
            resolve_bank_account_for_ledger,
        )

        mock_get_mapping.return_value = ("4000", "4000 - Revenue - NVV")
        mock_frappe.db.get_value.return_value = "Income Account"
        mock_payment_config.return_value = None
        mock_pattern.return_value = None

        result = resolve_bank_account_for_ledger("12345", "NVV", debug_info=self.debug_info)

        self.assertIsNone(result)
        self.assertTrue(any("income account" in msg.lower() for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.consolidated.bank_account_utils.get_ledger_mapping")
    def test_resolve_bank_account_or_raise_throws_on_not_found(self, mock_get_mapping):
        """Test that resolve_bank_account_or_raise raises when no account found"""
        from verenigingen.e_boekhouden.utils.consolidated.bank_account_utils import (
            resolve_bank_account_or_raise,
        )

        mock_get_mapping.return_value = (None, None)

        with self.assertRaises(frappe.ValidationError) as ctx:
            resolve_bank_account_or_raise("12345", "NVV", debug_info=self.debug_info)

        self.assertIn("No Bank/Cash account found", str(ctx.exception))
        self.assertIn("12345", str(ctx.exception))

    @patch("verenigingen.e_boekhouden.utils.consolidated.bank_account_utils.frappe")
    def test_pattern_matching_finds_asn_bank(self, mock_frappe):
        """Test that pattern matching finds ASN bank from description"""
        from verenigingen.e_boekhouden.utils.consolidated.bank_account_utils import (
            _get_account_from_pattern,
        )

        mock_frappe.get_all.return_value = [{"name": "1100 - ASN Bank - NVV"}]

        result = _get_account_from_pattern(
            "Betaling ASN rekening", "NVV", "Pay", self.debug_info
        )

        self.assertEqual(result, "1100 - ASN Bank - NVV")

    @patch("verenigingen.e_boekhouden.utils.consolidated.bank_account_utils.frappe")
    def test_pattern_matching_finds_ing_bank(self, mock_frappe):
        """Test that pattern matching finds ING bank from description"""
        from verenigingen.e_boekhouden.utils.consolidated.bank_account_utils import (
            _get_account_from_pattern,
        )

        mock_frappe.get_all.return_value = [{"name": "1101 - ING Business - NVV"}]

        result = _get_account_from_pattern(
            "Overboeking ING Bank", "NVV", "Receive", self.debug_info
        )

        self.assertEqual(result, "1101 - ING Business - NVV")

    def test_pattern_matching_returns_none_for_empty_description(self):
        """Test that pattern matching handles empty description"""
        from verenigingen.e_boekhouden.utils.consolidated.bank_account_utils import (
            _get_account_from_pattern,
        )

        result = _get_account_from_pattern(None, "NVV", "Pay", self.debug_info)
        self.assertIsNone(result)

        result = _get_account_from_pattern("", "NVV", "Pay", self.debug_info)
        self.assertIsNone(result)


class TestDateUtils(unittest.TestCase):
    """Tests for date_utils.py - fiscal year management with race condition handling"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_info = []

    @patch("verenigingen.e_boekhouden.utils.consolidated.date_utils.frappe")
    def test_ensure_fiscal_year_returns_existing(self, mock_frappe):
        """Test that existing fiscal year is returned"""
        from verenigingen.e_boekhouden.utils.consolidated.date_utils import (
            ensure_fiscal_year_exists,
        )

        mock_frappe.db.sql.return_value = [
            MockFiscalYearResult({"name": "2024", "year_start_date": "2024-01-01", "year_end_date": "2024-12-31"})
        ]

        result = ensure_fiscal_year_exists("2024-06-15", "NVV", self.debug_info)

        self.assertEqual(result, "2024")
        self.assertTrue(any("exists" in msg.lower() for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.consolidated.date_utils.frappe")
    def test_ensure_fiscal_year_creates_new(self, mock_frappe):
        """Test that new fiscal year is created when missing"""
        from verenigingen.e_boekhouden.utils.consolidated.date_utils import (
            ensure_fiscal_year_exists,
        )

        mock_frappe.db.sql.return_value = []  # No existing fiscal year
        mock_frappe.db.get_value.return_value = None  # Name doesn't exist
        mock_doc = MagicMock()
        mock_frappe.get_doc.return_value = mock_doc

        result = ensure_fiscal_year_exists("2025-03-15", "NVV", self.debug_info)

        self.assertEqual(result, "2025")
        mock_doc.insert.assert_called_once_with(ignore_permissions=True)
        self.assertTrue(any("creating" in msg.lower() for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.consolidated.date_utils.frappe")
    def test_ensure_fiscal_year_handles_concurrent_creation(self, mock_frappe):
        """Test that concurrent fiscal year creation is handled gracefully"""
        from verenigingen.e_boekhouden.utils.consolidated.date_utils import (
            ensure_fiscal_year_exists,
        )

        mock_frappe.db.sql.return_value = []  # No existing fiscal year
        mock_frappe.db.get_value.return_value = None  # Name doesn't exist initially
        mock_doc = MagicMock()
        mock_doc.insert.side_effect = frappe.DuplicateEntryError("Duplicate entry")
        mock_frappe.get_doc.return_value = mock_doc
        mock_frappe.DuplicateEntryError = frappe.DuplicateEntryError

        # Should not raise, should return the year name
        result = ensure_fiscal_year_exists("2025-03-15", "NVV", self.debug_info)

        self.assertEqual(result, "2025")
        self.assertTrue(
            any("concurrent" in msg.lower() for msg in self.debug_info),
            f"Expected concurrent creation message in debug_info, got: {self.debug_info}",
        )

    @patch("verenigingen.e_boekhouden.utils.consolidated.date_utils.frappe")
    def test_ensure_fiscal_year_reuses_existing_by_name(self, mock_frappe):
        """Test that fiscal year found by name (but not date range) is reused"""
        from verenigingen.e_boekhouden.utils.consolidated.date_utils import (
            ensure_fiscal_year_exists,
        )

        mock_frappe.db.sql.return_value = []  # No fiscal year covering this date
        mock_frappe.db.get_value.return_value = MockFiscalYearResult({
            "name": "2025",
            "year_start_date": "2025-01-01",
            "year_end_date": "2025-12-31",
        })

        result = ensure_fiscal_year_exists("2025-03-15", "NVV", self.debug_info)

        self.assertEqual(result, "2025")
        self.assertTrue(any("already exists" in msg.lower() for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.consolidated.date_utils.frappe")
    def test_ensure_fiscal_year_handles_string_date(self, mock_frappe):
        """Test that string dates are properly converted"""
        from verenigingen.e_boekhouden.utils.consolidated.date_utils import (
            ensure_fiscal_year_exists,
        )

        mock_frappe.db.sql.return_value = [
            MockFiscalYearResult({"name": "2024", "year_start_date": "2024-01-01", "year_end_date": "2024-12-31"})
        ]

        # String date should work
        result = ensure_fiscal_year_exists("2024-06-15", "NVV", self.debug_info)
        self.assertEqual(result, "2024")

    @patch("verenigingen.e_boekhouden.utils.consolidated.date_utils.frappe")
    def test_ensure_fiscal_year_handles_date_object(self, mock_frappe):
        """Test that date objects are properly handled"""
        from datetime import date

        from verenigingen.e_boekhouden.utils.consolidated.date_utils import (
            ensure_fiscal_year_exists,
        )

        mock_frappe.db.sql.return_value = [
            MockFiscalYearResult({"name": "2024", "year_start_date": "2024-01-01", "year_end_date": "2024-12-31"})
        ]

        # Date object should work
        result = ensure_fiscal_year_exists(date(2024, 6, 15), "NVV", self.debug_info)
        self.assertEqual(result, "2024")

    @patch("verenigingen.e_boekhouden.utils.consolidated.date_utils.frappe")
    def test_ensure_fiscal_year_denies_creation_without_permission(self, mock_frappe):
        """Test that fiscal year creation is denied when user lacks permission"""
        from verenigingen.e_boekhouden.utils.consolidated.date_utils import (
            ensure_fiscal_year_exists,
        )

        mock_frappe.db.sql.return_value = []  # No existing fiscal year
        mock_frappe.db.get_value.return_value = None  # Name doesn't exist
        mock_frappe.has_permission.return_value = False  # User lacks permission
        mock_frappe.session.user = "test@example.com"
        mock_frappe.PermissionError = frappe.PermissionError

        with self.assertRaises(frappe.PermissionError) as ctx:
            ensure_fiscal_year_exists("2025-03-15", "NVV", self.debug_info)

        self.assertIn("lacks permission", str(ctx.exception))
        mock_frappe.has_permission.assert_called_once_with("Fiscal Year", "create")


class TestLedgerUtilsAutoCreate(unittest.TestCase):
    """Tests for ledger auto-creation via API"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_info = []

    # Mock justified: External HTTP API - e-boekhouden REST API, not business logic
    @patch("requests.get")
    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.frappe")
    def test_fetch_and_create_mapping_from_api(self, mock_frappe, mock_requests):
        """Test that ledger mapping is created from API response"""
        from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import (
            _fetch_and_create_single_mapping,
        )

        # Mock session token acquisition
        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator"
        ) as MockIterator:
            mock_iterator = MagicMock()
            mock_iterator._get_session_token.return_value = "test-token"
            mock_iterator.base_url = "https://api.e-boekhouden.nl"
            MockIterator.return_value = mock_iterator

            # Mock API response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"code": "42902", "description": "Revenue Account"}
            mock_requests.return_value = mock_response

            # No existing mapping
            mock_frappe.db.get_value.return_value = None

            # Mock doc creation
            mock_doc = MagicMock()
            mock_frappe.new_doc.return_value = mock_doc

            with patch(
                "verenigingen.e_boekhouden.utils.consolidated.ledger_utils._find_erpnext_account_by_code"
            ) as mock_find:
                mock_find.return_value = "42902 - Revenue - NVV"

                code, account = _fetch_and_create_single_mapping("13201916", "NVV", self.debug_info)

            self.assertEqual(code, "42902")
            self.assertEqual(account, "42902 - Revenue - NVV")
            mock_doc.insert.assert_called_once_with(ignore_permissions=True)

    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.frappe")
    def test_fetch_and_create_handles_concurrent_creation(self, mock_frappe):
        """Test that concurrent creation via DuplicateEntryError is handled"""
        from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import (
            _fetch_and_create_single_mapping,
        )

        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator"
        ) as MockIterator:
            mock_iterator = MagicMock()
            mock_iterator._get_session_token.return_value = "test-token"
            mock_iterator.base_url = "https://api.e-boekhouden.nl"
            MockIterator.return_value = mock_iterator

            # Mock justified: External HTTP API - e-boekhouden REST API, not business logic
            with patch("requests.get") as mock_requests:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"code": "42902", "description": "Revenue"}
                mock_requests.return_value = mock_response

                # First call returns None, second call (after insert) returns existing
                mock_frappe.db.get_value.side_effect = [
                    None,  # Check before insert
                    {"ledger_code": "42902", "erpnext_account": "42902 - Revenue - NVV"},  # After concurrent insert
                ]

                mock_doc = MagicMock()
                mock_doc.insert.side_effect = frappe.DuplicateEntryError("Duplicate")
                mock_frappe.new_doc.return_value = mock_doc
                mock_frappe.DuplicateEntryError = frappe.DuplicateEntryError

                with patch(
                    "verenigingen.e_boekhouden.utils.consolidated.ledger_utils._find_erpnext_account_by_code"
                ):
                    code, account = _fetch_and_create_single_mapping("13201916", "NVV", self.debug_info)

                # Should return the existing mapping after handling duplicate
                self.assertTrue(
                    any("concurrent" in msg.lower() for msg in self.debug_info),
                    f"Expected concurrent message in debug_info: {self.debug_info}",
                )

    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.time")
    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.frappe")
    def test_fetch_and_create_retries_on_transient_failure(self, mock_frappe, mock_time):
        """Test that API calls are retried with exponential backoff on transient failures"""
        from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import (
            _fetch_and_create_single_mapping,
        )

        # Mock justified: External Service - E-Boekhouden API
        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator"
        ) as MockIterator:
            mock_iterator = MagicMock()
            mock_iterator._get_session_token.return_value = "test-token"
            mock_iterator.base_url = "https://api.e-boekhouden.nl"
            MockIterator.return_value = mock_iterator

            # Mock justified: External Service - E-Boekhouden API
            with patch("requests.get") as mock_requests:
                # First two calls return 503, third succeeds
                mock_error_response = MagicMock()
                mock_error_response.status_code = 503

                mock_success_response = MagicMock()
                mock_success_response.status_code = 200
                mock_success_response.json.return_value = {"code": "42902", "description": "Revenue"}

                mock_requests.side_effect = [
                    mock_error_response,
                    mock_error_response,
                    mock_success_response,
                ]

                mock_frappe.db.get_value.return_value = None
                mock_doc = MagicMock()
                mock_frappe.new_doc.return_value = mock_doc

                with patch(
                    "verenigingen.e_boekhouden.utils.consolidated.ledger_utils._find_erpnext_account_by_code"
                ) as mock_find:
                    mock_find.return_value = "42902 - Revenue - NVV"
                    code, account = _fetch_and_create_single_mapping("13201916", "NVV", self.debug_info)

                # Should succeed after retries
                self.assertEqual(code, "42902")
                self.assertEqual(account, "42902 - Revenue - NVV")

                # Verify retries occurred
                self.assertEqual(mock_requests.call_count, 3)
                self.assertTrue(
                    any("retrying" in msg.lower() for msg in self.debug_info),
                    f"Expected retry message in debug_info: {self.debug_info}",
                )

    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.time")
    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.frappe")
    def test_fetch_and_create_fails_after_max_retries(self, mock_frappe, mock_time):
        """Test that API calls fail gracefully after max retries exhausted"""
        from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import (
            API_MAX_RETRIES,
            _fetch_and_create_single_mapping,
        )

        # Mock justified: External Service - E-Boekhouden API
        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator"
        ) as MockIterator:
            mock_iterator = MagicMock()
            mock_iterator._get_session_token.return_value = "test-token"
            mock_iterator.base_url = "https://api.e-boekhouden.nl"
            MockIterator.return_value = mock_iterator

            # Mock justified: External Service - E-Boekhouden API
            with patch("requests.get") as mock_requests:
                # All calls return 503
                mock_error_response = MagicMock()
                mock_error_response.status_code = 503
                mock_requests.return_value = mock_error_response

                code, account = _fetch_and_create_single_mapping("13201916", "NVV", self.debug_info)

                # Should fail after max retries
                self.assertIsNone(code)
                self.assertIsNone(account)

                # Verify all retries were attempted
                self.assertEqual(mock_requests.call_count, API_MAX_RETRIES)
                self.assertTrue(
                    any("failed after" in msg.lower() for msg in self.debug_info),
                    f"Expected failure message in debug_info: {self.debug_info}",
                )


class TestPartyUtils(unittest.TestCase):
    """Tests for party_utils.py - canonical party account resolution"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_info = []

    @patch("verenigingen.e_boekhouden.utils.consolidated.party_utils.frappe")
    def test_get_party_account_priority_1_party_specific(self, mock_frappe):
        """Test that party-specific account from Party Account table is returned first"""
        from verenigingen.e_boekhouden.utils.consolidated.party_utils import (
            get_party_account,
        )

        # Party-specific account exists
        mock_frappe.db.sql.return_value = [("1300 - Debiteuren Specifiek - NVV",)]

        result = get_party_account("CUST-001", "Customer", "NVV", self.debug_info)

        self.assertEqual(result, "1300 - Debiteuren Specifiek - NVV")
        self.assertTrue(any("party-specific" in msg.lower() for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.consolidated.party_utils._get_party_specific_account")
    @patch("verenigingen.e_boekhouden.utils.consolidated.party_utils.frappe")
    def test_get_party_account_priority_2_company_default(self, mock_frappe, mock_party_specific):
        """Test that company default is used when no party-specific account exists"""
        from verenigingen.e_boekhouden.utils.consolidated.party_utils import (
            get_party_account,
        )

        mock_party_specific.return_value = None
        mock_frappe.db.get_value.return_value = "1300 - Debiteuren - NVV"

        result = get_party_account("CUST-001", "Customer", "NVV", self.debug_info)

        self.assertEqual(result, "1300 - Debiteuren - NVV")
        self.assertTrue(any("company default" in msg.lower() for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.consolidated.party_utils._get_safe_account")
    @patch("verenigingen.e_boekhouden.utils.consolidated.party_utils._get_generic_account")
    @patch("verenigingen.e_boekhouden.utils.consolidated.party_utils._get_company_default_account")
    @patch("verenigingen.e_boekhouden.utils.consolidated.party_utils._get_party_specific_account")
    def test_get_party_account_priority_3_generic(
        self, mock_party, mock_company, mock_generic, mock_safe
    ):
        """Test that generic account (Default/General/Algemeen) is used as fallback"""
        from verenigingen.e_boekhouden.utils.consolidated.party_utils import (
            get_party_account,
        )

        mock_party.return_value = None
        mock_company.return_value = None
        mock_generic.return_value = "1300 - Algemeen Debiteuren - NVV"

        result = get_party_account("CUST-001", "Customer", "NVV", self.debug_info)

        self.assertEqual(result, "1300 - Algemeen Debiteuren - NVV")
        self.assertTrue(any("generic" in msg.lower() for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.consolidated.party_utils.frappe")
    def test_get_party_account_avoids_vraagposten(self, mock_frappe):
        """Test that Vraagposten accounts are avoided in fallback"""
        from verenigingen.e_boekhouden.utils.consolidated.party_utils import (
            _get_safe_account,
        )

        mock_frappe.db.sql.return_value = [{"name": "1300 - Safe Account - NVV"}]

        result = _get_safe_account("Receivable", "NVV")

        # Verify SQL excludes Vraagposten
        call_args = mock_frappe.db.sql.call_args[0][0]
        self.assertIn("NOT LIKE", call_args)
        self.assertIn("Vraagposten", call_args)

    @patch("verenigingen.e_boekhouden.utils.consolidated.party_utils.frappe")
    def test_get_party_account_supplier_type(self, mock_frappe):
        """Test that Supplier party type correctly uses Payable accounts"""
        from verenigingen.e_boekhouden.utils.consolidated.party_utils import (
            _get_company_default_account,
        )

        mock_frappe.db.get_value.return_value = "2000 - Crediteuren - NVV"

        result = _get_company_default_account("Supplier", "NVV")

        mock_frappe.db.get_value.assert_called_once_with("Company", "NVV", "default_payable_account")
        self.assertEqual(result, "2000 - Crediteuren - NVV")

    @patch("verenigingen.e_boekhouden.utils.consolidated.party_utils.frappe")
    def test_get_party_account_customer_type(self, mock_frappe):
        """Test that Customer party type correctly uses Receivable accounts"""
        from verenigingen.e_boekhouden.utils.consolidated.party_utils import (
            _get_company_default_account,
        )

        mock_frappe.db.get_value.return_value = "1300 - Debiteuren - NVV"

        result = _get_company_default_account("Customer", "NVV")

        mock_frappe.db.get_value.assert_called_once_with("Company", "NVV", "default_receivable_account")
        self.assertEqual(result, "1300 - Debiteuren - NVV")


class TestCostCenterUtils(unittest.TestCase):
    """Tests for cost_center_utils.py - canonical cost center resolution"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_info = []

    @patch("verenigingen.e_boekhouden.utils.consolidated.cost_center_utils.frappe")
    def test_get_default_cost_center_priority_1_company_default(self, mock_frappe):
        """Test that company's default cost center is returned first"""
        from verenigingen.e_boekhouden.utils.consolidated.cost_center_utils import (
            get_default_cost_center,
        )

        mock_company_doc = MagicMock()
        mock_company_doc.cost_center = "Main - NVV"
        mock_frappe.get_doc.return_value = mock_company_doc

        result = get_default_cost_center("NVV", self.debug_info)

        self.assertEqual(result, "Main - NVV")
        self.assertTrue(any("company default" in msg.lower() for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.consolidated.cost_center_utils._get_company_default_cost_center")
    @patch("verenigingen.e_boekhouden.utils.consolidated.cost_center_utils.frappe")
    def test_get_default_cost_center_priority_2_main(self, mock_frappe, mock_company_default):
        """Test that 'Main' cost center is used when no company default"""
        from verenigingen.e_boekhouden.utils.consolidated.cost_center_utils import (
            get_default_cost_center,
        )

        mock_company_default.return_value = None
        mock_frappe.db.get_value.return_value = "Main - NVV"

        result = get_default_cost_center("NVV", self.debug_info)

        self.assertEqual(result, "Main - NVV")
        self.assertTrue(any("main" in msg.lower() for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.consolidated.cost_center_utils._get_company_default_cost_center")
    @patch("verenigingen.e_boekhouden.utils.consolidated.cost_center_utils.frappe")
    def test_get_default_cost_center_excludes_magazine(self, mock_frappe, mock_company_default):
        """Test that Magazine cost centers are excluded from selection"""
        from verenigingen.e_boekhouden.utils.consolidated.cost_center_utils import (
            get_default_cost_center,
        )

        mock_company_default.return_value = None
        mock_frappe.db.get_value.side_effect = [None, None, None]  # No Main, no company-named, no fallback
        mock_frappe.get_all.return_value = [
            {"name": "Magazine - NVV", "cost_center_name": "Magazine"},
            {"name": "General - NVV", "cost_center_name": "General"},
        ]

        result = get_default_cost_center("NVV", self.debug_info)

        # Should skip Magazine and return General
        self.assertEqual(result, "General - NVV")

    @patch("verenigingen.e_boekhouden.utils.consolidated.cost_center_utils.frappe")
    def test_get_general_cost_center_finds_general(self, mock_frappe):
        """Test that general cost center names are found"""
        from verenigingen.e_boekhouden.utils.consolidated.cost_center_utils import (
            get_general_cost_center,
        )

        mock_frappe.db.get_value.return_value = "General Fund - NVV"

        result = get_general_cost_center("NVV", self.debug_info)

        self.assertEqual(result, "General Fund - NVV")

    @patch("verenigingen.e_boekhouden.utils.consolidated.cost_center_utils.frappe")
    def test_get_chapter_cost_center_finds_by_reference(self, mock_frappe):
        """Test that chapter cost center is found by reference"""
        from verenigingen.e_boekhouden.utils.consolidated.cost_center_utils import (
            get_chapter_cost_center,
        )

        mock_frappe.db.get_value.return_value = "Amsterdam Chapter - NVV"

        result = get_chapter_cost_center("NVV", "Amsterdam", self.debug_info)

        self.assertEqual(result, "Amsterdam Chapter - NVV")
        # Verify LIKE query was used
        call_args = mock_frappe.db.get_value.call_args
        self.assertIn("like", str(call_args).lower())


class TestEnsureAccountTypeIsCorrect(unittest.TestCase):
    """Tests for ensure_account_type_is_correct with auto_fix parameter"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_info = []

    @patch("verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.frappe")
    def test_auto_fix_false_does_not_modify(self, mock_frappe):
        """Test that auto_fix=False (default) does not modify account type"""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
            ensure_account_type_is_correct,
        )

        mock_frappe.db.exists.return_value = True
        mock_frappe.db.get_value.return_value = "Bank"  # Wrong type

        result = ensure_account_type_is_correct(
            "1100 - Bank - NVV", "Receivable", self.debug_info, auto_fix=False
        )

        self.assertFalse(result)
        mock_frappe.db.set_value.assert_not_called()
        self.assertTrue(any("auto_fix=False" in msg for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.frappe")
    def test_auto_fix_true_modifies_and_logs(self, mock_frappe):
        """Test that auto_fix=True modifies account type and creates audit log (but does NOT commit)"""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
            ensure_account_type_is_correct,
        )

        mock_frappe.db.exists.return_value = True
        mock_frappe.db.get_value.return_value = "Bank"  # Wrong type
        mock_frappe.session.user = "test@example.com"
        mock_frappe._.side_effect = lambda x: x  # Pass through translation

        result = ensure_account_type_is_correct(
            "1100 - Bank - NVV", "Receivable", self.debug_info, auto_fix=True
        )

        self.assertTrue(result)
        mock_frappe.db.set_value.assert_called_once_with(
            "Account", "1100 - Bank - NVV", "account_type", "Receivable"
        )
        # Verify commit is NOT called - callers control transaction boundaries
        mock_frappe.db.commit.assert_not_called()
        mock_frappe.log_error.assert_called_once()  # Audit log created

    @patch("verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.frappe")
    def test_correct_type_returns_true_no_modification(self, mock_frappe):
        """Test that correct account type returns True without modification"""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
            ensure_account_type_is_correct,
        )

        mock_frappe.db.exists.return_value = True
        mock_frappe.db.get_value.return_value = "Receivable"  # Already correct

        result = ensure_account_type_is_correct(
            "1300 - Debiteuren - NVV", "Receivable", self.debug_info, auto_fix=True
        )

        self.assertTrue(result)
        mock_frappe.db.set_value.assert_not_called()
        self.assertTrue(any("already has correct type" in msg for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.frappe")
    def test_nonexistent_account_returns_false(self, mock_frappe):
        """Test that nonexistent account returns False"""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
            ensure_account_type_is_correct,
        )

        mock_frappe.db.exists.return_value = False

        result = ensure_account_type_is_correct(
            "9999 - Missing - NVV", "Receivable", self.debug_info
        )

        self.assertFalse(result)
        self.assertTrue(any("does not exist" in msg for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.frappe")
    def test_default_auto_fix_is_false(self, mock_frappe):
        """Test that auto_fix defaults to False for safety"""
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
            ensure_account_type_is_correct,
        )

        mock_frappe.db.exists.return_value = True
        mock_frappe.db.get_value.return_value = "Bank"  # Wrong type

        # Call without auto_fix parameter (should default to False)
        result = ensure_account_type_is_correct(
            "1100 - Bank - NVV", "Receivable", self.debug_info
        )

        self.assertFalse(result)
        mock_frappe.db.set_value.assert_not_called()  # Should NOT modify


class TestPaymentEntryHandlerErrorPath(unittest.TestCase):
    """Tests for PaymentEntryHandler._determine_bank_account error path logging"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_log = []

    @patch("verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler.nowdate")
    @patch("verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler.frappe")
    @patch("verenigingen.e_boekhouden.utils.consolidated.bank_account_utils.resolve_bank_account_for_ledger")
    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.get_ledger_mapping")
    def test_error_path_logs_debug_info_and_includes_in_exception(
        self, mock_get_mapping, mock_resolve, mock_frappe, mock_nowdate
    ):
        """Test that debug info from get_ledger_mapping is logged and included in exception"""
        from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
            PaymentEntryHandler,
        )

        # Set up frappe mock
        mock_frappe.ValidationError = frappe.ValidationError
        mock_frappe.logger.return_value = MagicMock()
        mock_nowdate.return_value = "2024-01-01"

        # resolve_bank_account_for_ledger returns None (no bank account found)
        mock_resolve.return_value = None

        # get_ledger_mapping returns code but populates debug_info
        def mapping_side_effect(ledger_id, company=None, debug_info=None, auto_create=False):
            if debug_info is not None:
                debug_info.append(f"No mapping found for ledger_id {ledger_id}")
                debug_info.append("Tried account_number lookup: not found")
                debug_info.append("Tried eboekhouden_grootboek_nummer: not found")
            return ("12345", None)

        mock_get_mapping.side_effect = mapping_side_effect

        # Create handler
        handler = PaymentEntryHandler(company="NVV", cost_center="Main - NVV")

        # Call _determine_bank_account - should raise ValidationError
        with self.assertRaises(frappe.ValidationError) as ctx:
            handler._determine_bank_account(ledger_id=99999, payment_type="Receive")

        # Verify debug messages were logged
        logged_messages = [msg for msg in handler.debug_log if "mapping" in msg.lower()]
        self.assertTrue(len(logged_messages) >= 1, "Debug messages should be logged")

        # Verify exception includes debug snippet
        error_message = str(ctx.exception)
        self.assertIn("Debug info:", error_message)
        self.assertIn("not found", error_message.lower())

    @patch("verenigingen.e_boekhouden.utils.consolidated.bank_account_utils.resolve_bank_account_for_ledger")
    @patch("verenigingen.e_boekhouden.utils.consolidated.ledger_utils.get_ledger_mapping")
    def test_error_path_without_debug_info_still_raises(self, mock_get_mapping, mock_resolve):
        """Test that error is raised even when get_ledger_mapping returns no debug info"""
        from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
            PaymentEntryHandler,
        )

        mock_resolve.return_value = None
        mock_get_mapping.return_value = (None, None)  # No code, no account, no debug

        handler = PaymentEntryHandler(company="NVV", cost_center="Main - NVV")

        with self.assertRaises(frappe.ValidationError) as ctx:
            handler._determine_bank_account(ledger_id=99999, payment_type="Receive")

        # Should still raise with basic message (no Debug info section)
        error_message = str(ctx.exception)
        self.assertIn("No Bank/Cash account found", error_message)


if __name__ == "__main__":
    unittest.main()
