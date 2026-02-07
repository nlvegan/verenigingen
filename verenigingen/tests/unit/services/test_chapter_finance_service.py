# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Unit tests for ChapterFinanceService.

Tests branching logic using mocks — no database required.
Covers:
- create_chapter_cost_center: skip, link-existing, create-new, error handling
- get_validated_company: default company, fallback, multi-company, no-company
- get_appropriate_parent_cost_center: root CC, fallback CC, no CC
- update_chapter_cost_center_name: update, recreation on missing CC, no-op
"""

import unittest
from unittest.mock import MagicMock, patch

from verenigingen.services.chapter.chapter_finance_service import ChapterFinanceService


def _make_chapter(**overrides):
    """Create a minimal mock chapter document."""
    chapter = MagicMock()
    chapter.name = "Test-Chapter-001"
    chapter.cost_center = None
    for k, v in overrides.items():
        setattr(chapter, k, v)
    return chapter


def _make_secure_result(success=True, errors=None):
    """Create a mock SecureOperationResult."""
    result = MagicMock()
    result.success = success
    result.errors = errors or []
    return result


class TestGetValidatedCompany(unittest.TestCase):
    """Test ChapterFinanceService.get_validated_company() selection logic."""

    def setUp(self):
        self.svc = ChapterFinanceService()
        self.chapter = _make_chapter()

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_returns_default_company_when_exists(self, mock_frappe):
        """Default company from Global Defaults should be returned when it exists."""
        mock_frappe.db.get_single_value.return_value = "Ned Ver Vegan"
        mock_frappe.db.exists.return_value = True

        result = self.svc.get_validated_company(self.chapter)

        self.assertEqual(result, "Ned Ver Vegan")

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_returns_none_when_default_company_doesnt_exist(self, mock_frappe):
        """When default company doesn't exist in DB, should fall back."""
        mock_frappe.db.get_single_value.return_value = "Ghost Company"
        mock_frappe.db.exists.return_value = False
        # Fallback returns multiple companies → ambiguous
        mock_frappe.get_all.return_value = ["CompanyA", "CompanyB"]

        result = self.svc.get_validated_company(self.chapter)

        self.assertIsNone(result)

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_fallback_to_single_company(self, mock_frappe):
        """When no default company, falls back to single active company."""
        mock_frappe.db.get_single_value.return_value = None
        mock_frappe.get_all.return_value = ["Only Company"]

        result = self.svc.get_validated_company(self.chapter)

        self.assertEqual(result, "Only Company")

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_returns_none_when_multiple_companies(self, mock_frappe):
        """Multiple companies without default → None (ambiguous)."""
        mock_frappe.db.get_single_value.return_value = None
        mock_frappe.get_all.return_value = ["Company A", "Company B"]

        result = self.svc.get_validated_company(self.chapter)

        self.assertIsNone(result)

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_returns_none_when_no_companies(self, mock_frappe):
        """No companies at all → None."""
        mock_frappe.db.get_single_value.return_value = None
        mock_frappe.get_all.return_value = []

        result = self.svc.get_validated_company(self.chapter)

        self.assertIsNone(result)


class TestGetAppropriateParentCostCenter(unittest.TestCase):
    """Test ChapterFinanceService.get_appropriate_parent_cost_center()."""

    def setUp(self):
        self.svc = ChapterFinanceService()
        self.chapter = _make_chapter()

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_returns_root_cost_center(self, mock_frappe):
        """Should prefer root cost center matching company name."""
        mock_frappe.get_all.return_value = [MagicMock(name="Ned Ver Vegan - NVV")]
        # Patch the .name attribute properly (MagicMock has its own .name)
        mock_frappe.get_all.return_value[0].name = "Ned Ver Vegan - NVV"

        result = self.svc.get_appropriate_parent_cost_center(self.chapter, "Ned Ver Vegan")

        self.assertEqual(result, "Ned Ver Vegan - NVV")
        # Should have been called with disabled=0, NOT is_disabled=0
        call_kwargs = mock_frappe.get_all.call_args_list[0]
        filters = call_kwargs[1].get("filters") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1]["filters"]
        self.assertIn("disabled", filters)
        self.assertNotIn("is_disabled", filters)

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_fallback_when_no_root_cc(self, mock_frappe):
        """Should fall back to any group CC when root doesn't match company name."""
        fallback_cc = MagicMock()
        fallback_cc.name = "Some Group - NVV"
        # First call: root lookup (empty), second call: fallback
        mock_frappe.get_all.side_effect = [[], [fallback_cc]]

        result = self.svc.get_appropriate_parent_cost_center(self.chapter, "Ned Ver Vegan")

        self.assertEqual(result, "Some Group - NVV")

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_returns_none_when_no_group_cc(self, mock_frappe):
        """No group cost centers at all → None."""
        mock_frappe.get_all.side_effect = [[], []]

        result = self.svc.get_appropriate_parent_cost_center(self.chapter, "Ned Ver Vegan")

        self.assertIsNone(result)


class TestCreateChapterCostCenter(unittest.TestCase):
    """Test ChapterFinanceService.create_chapter_cost_center() branching."""

    def setUp(self):
        self.svc = ChapterFinanceService()

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_skips_when_cost_center_already_exists(self, mock_frappe):
        """Should skip creation when chapter already has a valid cost center."""
        chapter = _make_chapter(cost_center="Existing-CC")
        mock_frappe.db.exists.return_value = True

        self.svc.create_chapter_cost_center(chapter)

        # Should not try to create anything
        mock_frappe.new_doc.assert_not_called()

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_returns_early_when_no_valid_company(self, mock_frappe):
        """Should bail out when no company can be resolved."""
        chapter = _make_chapter()
        mock_frappe.db.exists.return_value = False
        mock_frappe.db.get_single_value.return_value = None
        mock_frappe.get_all.return_value = []  # No companies

        self.svc.create_chapter_cost_center(chapter)

        mock_frappe.new_doc.assert_not_called()

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_links_existing_cost_center_by_name(self, mock_frappe):
        """Should link existing CC if one matches the naming pattern."""
        chapter = _make_chapter()

        def exists_side_effect(*args, **kwargs):
            # frappe.db.exists("Company", name) for company validation
            if len(args) >= 2 and args[0] == "Company":
                return True
            # frappe.db.exists("Cost Center", {dict}) for CC name lookup
            if len(args) >= 2 and isinstance(args[1], dict) and "cost_center_name" in args[1]:
                return "Existing-CC-Name"
            return False

        mock_frappe.db.exists.side_effect = exists_side_effect
        mock_frappe.db.get_single_value.return_value = "Test Company"

        self.svc.create_chapter_cost_center(chapter)

        chapter.db_set.assert_called_once_with("cost_center", "Existing-CC-Name", update_modified=False)
        mock_frappe.new_doc.assert_not_called()

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_creates_new_cost_center_on_success(self, mock_frappe):
        """Should create a new cost center and link it when secure_op succeeds."""
        chapter = _make_chapter()
        mock_frappe.db.exists.return_value = False

        mock_cc_doc = MagicMock()
        mock_cc_doc.name = "Test-Chapter-001 - Chapter - TC"
        mock_frappe.new_doc.return_value = mock_cc_doc

        with patch.object(self.svc, "get_validated_company", return_value="TestCo"), \
             patch.object(self.svc, "get_appropriate_parent_cost_center", return_value="Root - TC"), \
             patch(
                 "verenigingen.utils.secure_operations.secure_document_operation",
                 return_value=_make_secure_result(success=True),
             ):
            self.svc.create_chapter_cost_center(chapter)

        chapter.db_set.assert_called_once_with(
            "cost_center", mock_cc_doc.name, update_modified=False
        )

    def test_does_not_raise_on_error(self):
        """Errors during creation should be swallowed (non-fatal)."""
        chapter = _make_chapter()

        with patch.object(self.svc, "get_validated_company", side_effect=RuntimeError("boom")):
            # Should not raise
            self.svc.create_chapter_cost_center(chapter)


class TestUpdateChapterCostCenterName(unittest.TestCase):
    """Test ChapterFinanceService.update_chapter_cost_center_name()."""

    def setUp(self):
        self.svc = ChapterFinanceService()

    def test_creates_cost_center_when_none_assigned(self):
        """Should call create_chapter_cost_center when no CC is assigned."""
        chapter = _make_chapter(cost_center=None)

        with patch.object(self.svc, "create_chapter_cost_center") as mock_create:
            self.svc.update_chapter_cost_center_name(chapter)

        mock_create.assert_called_once_with(chapter)

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_updates_cost_center_name_when_changed(self, mock_frappe):
        """Should update CC name to match chapter name."""
        chapter = _make_chapter(cost_center="Old-CC", name="New-Chapter-Name")

        mock_cc_doc = MagicMock()
        mock_cc_doc.cost_center_name = "Old-Chapter-Name - Chapter"
        mock_frappe.get_doc.return_value = mock_cc_doc

        with patch(
            "verenigingen.utils.secure_operations.secure_document_operation",
            return_value=_make_secure_result(success=True),
        ):
            self.svc.update_chapter_cost_center_name(chapter)

        self.assertEqual(mock_cc_doc.cost_center_name, "New-Chapter-Name - Chapter")

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_no_op_when_name_unchanged(self, mock_frappe):
        """Should skip save when CC name already matches."""
        chapter = _make_chapter(cost_center="Some-CC", name="MyChapter")

        mock_cc_doc = MagicMock()
        mock_cc_doc.cost_center_name = "MyChapter - Chapter"
        mock_frappe.get_doc.return_value = mock_cc_doc

        with patch(
            "verenigingen.utils.secure_operations.secure_document_operation",
        ) as mock_sdo:
            self.svc.update_chapter_cost_center_name(chapter)

        mock_sdo.assert_not_called()

    @patch("verenigingen.services.chapter.chapter_finance_service.frappe")
    def test_recreates_on_does_not_exist_error(self, mock_frappe):
        """Should clear invalid CC reference and recreate when CC is missing."""
        chapter = _make_chapter(cost_center="Deleted-CC")
        mock_frappe.get_doc.side_effect = mock_frappe.DoesNotExistError
        mock_frappe.DoesNotExistError = type("DoesNotExistError", (Exception,), {})
        mock_frappe.get_doc.side_effect = mock_frappe.DoesNotExistError()

        with patch.object(self.svc, "create_chapter_cost_center") as mock_create:
            self.svc.update_chapter_cost_center_name(chapter)

        chapter.db_set.assert_called_once_with("cost_center", None, update_modified=False)
        mock_create.assert_called_once_with(chapter)

    def test_does_not_raise_on_error(self):
        """Errors during update should be swallowed (non-fatal)."""
        chapter = _make_chapter(cost_center="Some-CC")

        with patch(
            "verenigingen.services.chapter.chapter_finance_service.frappe"
        ) as mock_frappe:
            mock_frappe.get_doc.side_effect = RuntimeError("unexpected")
            mock_frappe.DoesNotExistError = type("DoesNotExistError", (Exception,), {})

            # Should not raise
            self.svc.update_chapter_cost_center_name(chapter)
