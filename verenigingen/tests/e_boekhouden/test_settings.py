"""
Tests for the E-Boekhouden Settings controller + module-level helpers.

verenigingen/e_boekhouden/doctype/e_boekhouden_settings/e_boekhouden_settings.py

test_eboekhouden_doctype_coverage.py already covers _parse_ranges, _parse_keywords,
_parse_balance_sheet_group_mappings, _parse_pl_group_mappings, get_classification_rules
and validate_api_connection(no token). This file covers the rest:

  - _parse_group_type_mappings (child table)
  - HTTP boundary methods (test_connection / _get_session_token / get_api_data /
    validate_api_connection success) -- HTTP is stubbed, never live.
  - module-level whitelisted wrappers (test_connection, get_grootboekrekeningen)
  - _suggest_account_type_for_group (pure)
  - parse_groups_and_suggest_type_mappings (reads settings text fields)
  - might_be_group_cost_center, generate_cost_center_id (pure)

Run with:
    bench --site test_site_5 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_settings
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.e_boekhouden.doctype.e_boekhouden_settings import e_boekhouden_settings as eb_settings
from verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings import (
    _suggest_account_type_for_group,
    generate_cost_center_id,
    might_be_group_cost_center,
    parse_groups_and_suggest_type_mappings,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _ok_get(payload):
    """Build a stub requests.get/post response with 200 + json payload."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.text = str(payload)
    return resp


# ---------------------------------------------------------------------------
# Pure helpers (no DB, no settings)
# ---------------------------------------------------------------------------
class TestSuggestAccountTypeForGroup(unittest.TestCase):
    """_suggest_account_type_for_group: keyword/code based type suggestion."""

    def test_pl_income_keyword(self):
        s = _suggest_account_type_for_group("055", "Opbrengsten dienstverlening", is_balance_sheet=False)
        self.assertEqual(s["root_type"], "Income")
        self.assertEqual(s["account_type"], "Income Account")
        self.assertEqual(s["confidence"], "High")

    def test_pl_expense_keyword(self):
        s = _suggest_account_type_for_group("056", "Personeelskosten", is_balance_sheet=False)
        self.assertEqual(s["root_type"], "Expense")
        self.assertEqual(s["account_type"], "Expense Account")

    def test_pl_default_is_expense_low_confidence(self):
        s = _suggest_account_type_for_group("099", "Iets onbekends", is_balance_sheet=False)
        self.assertEqual(s["root_type"], "Expense")
        self.assertEqual(s["confidence"], "Low")

    def test_bal_fixed_asset(self):
        s = _suggest_account_type_for_group("001", "Vaste activa")
        self.assertEqual(s["root_type"], "Asset")
        self.assertEqual(s["account_type"], "Fixed Asset")

    def test_bal_bank(self):
        s = _suggest_account_type_for_group("002", "Liquide middelen bank")
        self.assertEqual(s["account_type"], "Bank")

    def test_bal_cash_when_kas_only(self):
        s = _suggest_account_type_for_group("002", "Kas")
        self.assertEqual(s["account_type"], "Cash")

    def test_bal_receivable(self):
        s = _suggest_account_type_for_group("004", "Vorderingen debiteuren")
        self.assertEqual(s["account_type"], "Receivable")

    def test_bal_payable(self):
        s = _suggest_account_type_for_group("006", "Schulden crediteuren")
        self.assertEqual(s["root_type"], "Liability")
        self.assertEqual(s["account_type"], "Payable")

    def test_bal_general_liability(self):
        s = _suggest_account_type_for_group("007", "Voorziening groot onderhoud")
        self.assertEqual(s["root_type"], "Liability")
        self.assertEqual(s["account_type"], "Current Liability")

    def test_bal_equity(self):
        s = _suggest_account_type_for_group("005", "Eigen vermogen")
        self.assertEqual(s["root_type"], "Equity")
        self.assertEqual(s["account_type"], "Equity")

    def test_bal_code_fallback_asset(self):
        s = _suggest_account_type_for_group("100", "Onbekend balanspost")
        self.assertEqual(s["root_type"], "Asset")
        self.assertEqual(s["confidence"], "Low")

    def test_bal_code_fallback_liability(self):
        s = _suggest_account_type_for_group("300", "Onbekend")
        self.assertEqual(s["root_type"], "Liability")

    def test_bal_unknown_code_left_empty(self):
        s = _suggest_account_type_for_group("900", "Mysterie")
        self.assertEqual(s["root_type"], "")
        self.assertIn("manually", s["notes"])

    def test_empty_code_does_not_crash(self):
        s = _suggest_account_type_for_group("", "Mysterie")
        self.assertEqual(s["group_code"], "")


class TestMightBeGroupCostCenter(unittest.TestCase):
    """might_be_group_cost_center: has a longer-code sibling under same 2-char prefix."""

    def test_has_children_is_group(self):
        groups = [{"code": "05"}, {"code": "0501"}, {"code": "0502"}]
        self.assertTrue(might_be_group_cost_center("05", "Parent", groups))

    def test_no_children_not_group(self):
        groups = [{"code": "05"}, {"code": "06"}]
        self.assertFalse(might_be_group_cost_center("05", "Leaf", groups))

    def test_self_excluded(self):
        groups = [{"code": "05"}]
        self.assertFalse(might_be_group_cost_center("05", "Solo", groups))


class TestGenerateCostCenterId(unittest.TestCase):
    """generate_cost_center_id: appends ' - <company>' unless already present."""

    def test_appends_company_suffix(self):
        self.assertEqual(generate_cost_center_id("Marketing", "ACME"), "Marketing - ACME")

    def test_does_not_double_append(self):
        self.assertEqual(generate_cost_center_id("Marketing - ACME", "ACME"), "Marketing - ACME")

    def test_strips_whitespace(self):
        self.assertEqual(generate_cost_center_id("  Sales  ", "ACME"), "Sales - ACME")


# ---------------------------------------------------------------------------
# Shared setup for tests that need a usable singleton
# ---------------------------------------------------------------------------
class _SettingsTestBase(EnhancedTestCase):
    """Sets up the E-Boekhouden Settings singleton with a stored api_token,
    api_url and default_company so the HTTP-stubbed code paths (which require a
    decryptable password) and the whitelisted wrappers (which save the doc, so
    need mandatory fields populated) can run.

    All field writes go through frappe.db.set_single_value / set_encrypted_password
    to avoid full-doc saves (which trip TimestampMismatchError when a concurrent
    session also touches this singleton, and MandatoryError when fields are unset).
    """

    SINGLE = "E-Boekhouden Settings"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from frappe.utils.password import set_encrypted_password

        cls._orig_url = frappe.db.get_single_value(cls.SINGLE, "api_url")
        cls._orig_company = frappe.db.get_single_value(cls.SINGLE, "default_company")
        cls._eur_company = (
            frappe.db.get_value("Company", {"default_currency": "EUR"}, "name") or "_Test Company 2"
        )

        frappe.db.set_single_value(cls.SINGLE, "api_url", "https://api.example.com")
        frappe.db.set_single_value(cls.SINGLE, "default_company", cls._eur_company)
        set_encrypted_password(cls.SINGLE, cls.SINGLE, "DUMMY-TOKEN", "api_token")
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        frappe.db.set_single_value(cls.SINGLE, "api_url", cls._orig_url)
        frappe.db.set_single_value(cls.SINGLE, "default_company", cls._orig_company)
        frappe.db.sql(
            "DELETE FROM `__Auth` WHERE doctype=%s AND name=%s AND fieldname='api_token'",
            (cls.SINGLE, cls.SINGLE),
        )
        frappe.db.commit()
        super().tearDownClass()


# ---------------------------------------------------------------------------
# Settings controller methods (singleton; HTTP stubbed where needed)
# ---------------------------------------------------------------------------
class TestSettingsController(_SettingsTestBase):
    """Exercises the singleton controller. We save+restore mutated text fields."""

    def _get_settings(self):
        return frappe.get_single("E-Boekhouden Settings")

    # ---- _parse_group_type_mappings (child table) ----
    def test_parse_group_type_mappings_empty(self):
        settings = self._get_settings()
        # New in-memory list keeps the singleton untouched
        original = settings.group_type_mappings
        try:
            settings.group_type_mappings = []
            self.assertEqual(settings._parse_group_type_mappings(), {})
        finally:
            settings.group_type_mappings = original

    def test_parse_group_type_mappings_builds_dict(self):
        settings = self._get_settings()
        original = settings.group_type_mappings
        try:
            settings.set("group_type_mappings", [])
            settings.append(
                "group_type_mappings",
                {
                    "group_code": "001",
                    "group_name": "Vaste activa",
                    "account_type": "Fixed Asset",
                    "root_type": "Asset",
                    "confidence": "High",
                    "notes": "n",
                },
            )
            # Row missing root_type must be skipped
            settings.append(
                "group_type_mappings",
                {"group_code": "002", "group_name": "x", "account_type": "Bank", "root_type": ""},
            )
            parsed = settings._parse_group_type_mappings()
            self.assertIn("001", parsed)
            self.assertNotIn("002", parsed)
            self.assertEqual(parsed["001"]["account_type"], "Fixed Asset")
            self.assertEqual(parsed["001"]["root_type"], "Asset")
        finally:
            settings.set("group_type_mappings", original)

    # ---- _get_session_token (HTTP stubbed) ----
    @patch("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.requests.post")
    def test_get_session_token_success(self, mock_post):
        mock_post.return_value = _ok_get({"token": "SESS-TOKEN-123"})
        settings = self._get_settings()
        original_url = settings.api_url
        try:
            settings.api_url = "https://api.example.com"
            token = settings._get_session_token()
            self.assertEqual(token, "SESS-TOKEN-123")
        finally:
            settings.api_url = original_url

    @patch("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.requests.post")
    def test_get_session_token_failure_returns_none(self, mock_post):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "unauthorized"
        mock_post.return_value = resp
        settings = self._get_settings()
        original_url = settings.api_url
        try:
            settings.api_url = "https://api.example.com"
            self.assertIsNone(settings._get_session_token())
        finally:
            settings.api_url = original_url

    # ---- validate_api_connection success path ----
    @patch("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.requests.post")
    def test_validate_api_connection_success(self, mock_post):
        mock_post.return_value = _ok_get({"token": "T"})
        settings = self._get_settings()
        original_url = settings.api_url
        try:
            settings.api_url = "https://api.example.com"
            result = settings.validate_api_connection()
            self.assertTrue(result["success"])
        finally:
            settings.api_url = original_url

    # ---- test_connection success (session + ledger both stubbed) ----
    @patch("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.requests.get")
    @patch("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.requests.post")
    def test_test_connection_success(self, mock_post, mock_get):
        mock_post.return_value = _ok_get({"token": "T"})
        mock_get.return_value = _ok_get({"items": [{"id": 1}]})
        settings = self._get_settings()
        original_url = settings.api_url
        original_status = settings.connection_status
        try:
            settings.api_url = "https://api.example.com"
            result = settings.test_connection()
            self.assertTrue(result)
            self.assertIn("Successful", settings.connection_status)
        finally:
            settings.api_url = original_url
            settings.connection_status = original_status

    @patch("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.requests.post")
    def test_test_connection_no_session_token_fails(self, mock_post):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "boom"
        mock_post.return_value = resp
        settings = self._get_settings()
        original_url = settings.api_url
        original_status = settings.connection_status
        try:
            settings.api_url = "https://api.example.com"
            result = settings.test_connection()
            self.assertFalse(result)
            self.assertIn("session token", settings.connection_status)
        finally:
            settings.api_url = original_url
            settings.connection_status = original_status

    @patch("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.requests.get")
    @patch("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.requests.post")
    def test_test_connection_http_error_on_ledger(self, mock_post, mock_get):
        mock_post.return_value = _ok_get({"token": "T"})
        bad = MagicMock()
        bad.status_code = 403
        bad.text = "forbidden"
        mock_get.return_value = bad
        settings = self._get_settings()
        original_url = settings.api_url
        original_status = settings.connection_status
        try:
            settings.api_url = "https://api.example.com"
            result = settings.test_connection()
            self.assertFalse(result)
            self.assertIn("403", settings.connection_status)
        finally:
            settings.api_url = original_url
            settings.connection_status = original_status

    # ---- get_api_data (HTTP stubbed) ----
    @patch("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.requests.get")
    @patch("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.requests.post")
    def test_get_api_data_get_success(self, mock_post, mock_get):
        mock_post.return_value = _ok_get({"token": "T"})
        ledger = MagicMock()
        ledger.status_code = 200
        ledger.text = '{"items": []}'
        mock_get.return_value = ledger
        settings = self._get_settings()
        original_url = settings.api_url
        try:
            settings.api_url = "https://api.example.com"
            result = settings.get_api_data("v1/ledger")
            self.assertTrue(result["success"])
            self.assertEqual(result["data"], '{"items": []}')
        finally:
            settings.api_url = original_url

    @patch("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.requests.post")
    def test_get_api_data_no_session_token(self, mock_post):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "no"
        mock_post.return_value = resp
        settings = self._get_settings()
        original_url = settings.api_url
        try:
            settings.api_url = "https://api.example.com"
            result = settings.get_api_data("v1/ledger")
            self.assertFalse(result["success"])
            self.assertIn("session token", result["error"])
        finally:
            settings.api_url = original_url


# ---------------------------------------------------------------------------
# Module-level whitelisted wrappers
# ---------------------------------------------------------------------------
class TestModuleLevelWrappers(_SettingsTestBase):
    """test_connection() and get_grootboekrekeningen() whitelisted endpoints.

    The module test_connection() wrapper internally saves the singleton, so the
    mandatory api_token/default_company set up by _SettingsTestBase are required.
    """

    @patch("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.requests.post")
    def test_module_test_connection_returns_structured_result(self, mock_post):
        # The wrapper saves the singleton internally; with no session token it
        # records a failure and returns {"success": False}. We assert the wrapper
        # returns the documented {"success": ...} shape without raising.
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "boom"
        mock_post.return_value = resp
        result = eb_settings.test_connection()
        self.assertIn("success", result)
        self.assertFalse(result["success"])

    @patch("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.requests.post")
    def test_module_get_grootboekrekeningen_failure_propagates(self, mock_post):
        # Session token fetch returns 401 -> get_api_data returns failure -> wrapper returns it
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "no"
        mock_post.return_value = resp
        result = eb_settings.get_grootboekrekeningen()
        self.assertFalse(result["success"])


# ---------------------------------------------------------------------------
# parse_groups_and_suggest_type_mappings (reads settings text fields)
# ---------------------------------------------------------------------------
class TestParseGroupsAndSuggestTypeMappings(_SettingsTestBase):
    """parse_groups_and_suggest_type_mappings reads the two mapping text fields
    and the group_type_mappings child table off a freshly-fetched singleton.

    We mutate those via frappe.db.set_single_value and direct child-table writes
    so no full singleton save is needed (avoids Mandatory/Timestamp issues).
    """

    CHILD_DT = "E-Boekhouden Group Type Mapping"

    def setUp(self):
        super().setUp()
        self._orig_bal = frappe.db.get_single_value(self.SINGLE, "balance_sheet_group_mappings")
        self._orig_pl = frappe.db.get_single_value(self.SINGLE, "pl_group_mappings")
        # Snapshot existing child rows so we can restore them
        self._orig_children = frappe.get_all(
            self.CHILD_DT,
            filters={"parent": self.SINGLE, "parenttype": self.SINGLE},
            fields=["group_code", "group_name", "root_type", "account_type"],
        )
        self._clear_children()

    def tearDown(self):
        frappe.db.set_single_value(self.SINGLE, "balance_sheet_group_mappings", self._orig_bal)
        frappe.db.set_single_value(self.SINGLE, "pl_group_mappings", self._orig_pl)
        self._clear_children()
        for idx, row in enumerate(self._orig_children, start=1):
            self._append_child(row.group_code, row.group_name, row.get("root_type"), idx)
        frappe.db.commit()
        super().tearDown()

    def _clear_children(self):
        frappe.db.delete(self.CHILD_DT, {"parent": self.SINGLE, "parenttype": self.SINGLE})

    def _append_child(self, group_code, group_name, root_type, idx):
        if not group_code:
            return
        child = frappe.new_doc(self.CHILD_DT)
        child.parent = self.SINGLE
        child.parenttype = self.SINGLE
        child.parentfield = "group_type_mappings"
        child.idx = idx
        child.group_code = group_code
        child.group_name = group_name or ""
        child.root_type = root_type or "Asset"
        child.db_insert()

    def _set_text(self, bal, pl):
        frappe.db.set_single_value(self.SINGLE, "balance_sheet_group_mappings", bal)
        frappe.db.set_single_value(self.SINGLE, "pl_group_mappings", pl)
        frappe.db.commit()

    def test_no_mappings_returns_error(self):
        self._set_text("", "")
        result = parse_groups_and_suggest_type_mappings()
        self.assertFalse(result["success"])

    def test_parses_balance_and_pl(self):
        self._set_text("001 Vaste activa\n004 Vorderingen", "055 Opbrengsten\n056 Personeelskosten")
        result = parse_groups_and_suggest_type_mappings()
        self.assertTrue(result["success"])
        self.assertEqual(result["total_groups"], 4)
        codes = {s["group_code"] for s in result["suggestions"]}
        self.assertEqual(codes, {"001", "004", "055", "056"})

    def test_duplicate_in_source_text_detected(self):
        self._set_text("001 Vaste activa\n001 Duplicate", "")
        result = parse_groups_and_suggest_type_mappings()
        self.assertTrue(result["success"])
        self.assertEqual(len(result["duplicates"]), 1)
        self.assertEqual(result["duplicates"][0]["code"], "001")

    def test_merge_mode_skips_existing(self):
        self._set_text("001 Vaste activa\n002 Liquide middelen", "")
        self._append_child("001", "Vaste activa", "Asset", 1)
        frappe.db.commit()
        result = parse_groups_and_suggest_type_mappings(merge_mode=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["skipped_existing"], 1)
        codes = {s["group_code"] for s in result["suggestions"]}
        self.assertEqual(codes, {"002"})


if __name__ == "__main__":
    unittest.main()
