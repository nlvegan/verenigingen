# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for automatic cost center creation on Chapter insert.

Tests real database operations with EnhancedTestCase — no mocks.
Covers:
- Chapter.after_insert triggers cost center auto-creation
- Cost center gets correct company, parent, and naming
- Chapter.cost_center field is populated after insert
- Idempotency: second call with existing CC is a no-op
- update_chapter_cost_center_name: recreation when CC is missing
"""

from unittest.mock import patch

import frappe

from verenigingen.services.chapter.chapter_finance_service import ChapterFinanceService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.cost_center_test_helpers import (
    create_group_cost_center,
    create_isolated_test_company,
    delete_all_cost_centers,
)


class TestChapterCostCenterAutoCreation(EnhancedTestCase):
    """Integration tests: chapter after_insert triggers cost center creation."""

    def setUp(self):
        super().setUp()
        settings = frappe.get_single("Verenigingen Settings")
        self.company = settings.company or frappe.db.get_single_value(
            "Global Defaults", "default_company"
        )
        if not self.company:
            self.skipTest("No company configured")
        self.company_abbr = frappe.db.get_value("Company", self.company, "abbr")

    def test_chapter_insert_creates_cost_center(self):
        """Creating a chapter should auto-create a linked cost center."""
        chapter = self.create_chapter()
        chapter.reload()

        self.assertIsNotNone(chapter.cost_center, "Chapter should have a cost center after insert")
        self.assertTrue(
            frappe.db.exists("Cost Center", chapter.cost_center),
            f"Cost center {chapter.cost_center} should exist in the database",
        )

    def test_cost_center_has_correct_company(self):
        """Auto-created cost center should belong to the validated company."""
        chapter = self.create_chapter()
        chapter.reload()

        cc = frappe.get_doc("Cost Center", chapter.cost_center)
        # The company should be a real company (from Global Defaults or single-company fallback)
        self.assertTrue(
            frappe.db.exists("Company", cc.company),
            f"Cost center company {cc.company} should exist",
        )

    def test_cost_center_has_parent(self):
        """Auto-created cost center should have a parent (group) cost center."""
        chapter = self.create_chapter()
        chapter.reload()

        cc = frappe.get_doc("Cost Center", chapter.cost_center)
        self.assertIsNotNone(cc.parent_cost_center, "Cost center should have a parent")

        # Parent should be a group node
        parent_is_group = frappe.db.get_value("Cost Center", cc.parent_cost_center, "is_group")
        self.assertTrue(parent_is_group, "Parent cost center should be a group node")

    def test_cost_center_is_not_group(self):
        """Auto-created chapter cost center should be a leaf node, not a group."""
        chapter = self.create_chapter()
        chapter.reload()

        cc = frappe.get_doc("Cost Center", chapter.cost_center)
        self.assertEqual(cc.is_group, 0, "Chapter cost center should not be a group")

    def test_cost_center_naming_convention(self):
        """Cost center name should follow '{chapter_name} - Chapter' pattern."""
        chapter = self.create_chapter()
        chapter.reload()

        cc = frappe.get_doc("Cost Center", chapter.cost_center)
        expected_name_part = f"{chapter.name} - Chapter"
        self.assertIn(
            expected_name_part,
            cc.cost_center_name or cc.name,
            f"Cost center name should contain '{expected_name_part}'",
        )

    def test_idempotent_when_cost_center_already_exists(self):
        """Calling create_chapter_cost_center again should be a no-op."""
        chapter = self.create_chapter()
        chapter.reload()

        original_cc = chapter.cost_center
        self.assertIsNotNone(original_cc)

        # Call again — should not create a second CC
        svc = ChapterFinanceService()
        svc.create_chapter_cost_center(chapter)
        chapter.reload()

        self.assertEqual(chapter.cost_center, original_cc, "Cost center should not change")

    def test_second_chapter_gets_own_cost_center(self):
        """Each chapter should get its own unique cost center."""
        chapter1 = self.create_chapter()
        chapter1.reload()

        chapter2 = self.create_chapter()
        chapter2.reload()

        self.assertIsNotNone(chapter1.cost_center)
        self.assertIsNotNone(chapter2.cost_center)
        self.assertNotEqual(
            chapter1.cost_center,
            chapter2.cost_center,
            "Each chapter should have a unique cost center",
        )


class TestGetValidatedCompanyIntegration(EnhancedTestCase):
    """Integration tests: get_validated_company with real Global Defaults."""

    def test_returns_a_valid_company(self):
        """Should return a company that actually exists in the database."""
        svc = ChapterFinanceService()
        chapter = self.create_chapter()

        company = svc.get_validated_company(chapter)

        if company:
            self.assertTrue(
                frappe.db.exists("Company", company),
                f"Returned company {company} should exist",
            )
        # If None, it means no default and multiple/no companies — acceptable

    def test_does_not_query_disabled_field_on_company(self):
        """Should not crash — Company DocType has no 'disabled' field in ERPNext v15+."""
        svc = ChapterFinanceService()
        chapter = self.create_chapter()

        # This should NOT raise OperationalError about unknown column
        try:
            company = svc.get_validated_company(chapter)
        except Exception as e:
            if "disabled" in str(e).lower():
                self.fail(f"get_validated_company references non-existent 'disabled' field: {e}")
            raise


class TestGetAppropriateParentCostCenterIntegration(EnhancedTestCase):
    """Integration tests: parent cost center resolution with real data."""

    def setUp(self):
        super().setUp()
        self.company = frappe.db.get_single_value("Global Defaults", "default_company")
        if not self.company:
            companies = frappe.get_all("Company", pluck="name", limit=1)
            self.company = companies[0] if companies else None
        if not self.company:
            self.skipTest("No company available")

    def test_returns_a_group_cost_center(self):
        """Should return a group cost center as parent."""
        svc = ChapterFinanceService()
        chapter = self.create_chapter()

        parent = svc.get_appropriate_parent_cost_center(chapter, self.company)

        if parent:
            is_group = frappe.db.get_value("Cost Center", parent, "is_group")
            self.assertTrue(is_group, f"Parent {parent} should be a group")

    def test_does_not_query_is_disabled_field(self):
        """Should use 'disabled' not 'is_disabled' on Cost Center."""
        svc = ChapterFinanceService()
        chapter = self.create_chapter()

        # This should NOT raise OperationalError about unknown column 'is_disabled'
        try:
            parent = svc.get_appropriate_parent_cost_center(chapter, self.company)
        except Exception as e:
            if "is_disabled" in str(e).lower():
                self.fail(
                    f"get_appropriate_parent_cost_center uses wrong field 'is_disabled': {e}"
                )
            raise

    def test_returns_none_for_nonexistent_company(self):
        """Nonexistent company should return None (no cost centers to find)."""
        svc = ChapterFinanceService()
        chapter = self.create_chapter()

        parent = svc.get_appropriate_parent_cost_center(chapter, "NONEXISTENT-COMPANY-XYZ")

        self.assertIsNone(parent)


class TestUpdateChapterCostCenterNameIntegration(EnhancedTestCase):
    """Integration tests: cost center name update and recreation."""

    def test_recreates_cost_center_when_reference_is_stale(self):
        """Should recreate cost center when referenced CC was deleted."""
        chapter = self.create_chapter()
        chapter.reload()
        original_cc = chapter.cost_center
        self.assertIsNotNone(original_cc)

        # Simulate a deleted cost center by clearing the reference
        chapter.db_set("cost_center", "DELETED-CC-THAT-DOESNT-EXIST", update_modified=False)
        chapter.cost_center = None  # Simulate no CC assigned

        svc = ChapterFinanceService()
        svc.update_chapter_cost_center_name(chapter)
        chapter.reload()

        # Should have recreated a cost center
        self.assertIsNotNone(
            chapter.cost_center, "Should have recreated a cost center"
        )
        self.assertTrue(
            frappe.db.exists("Cost Center", chapter.cost_center),
            "Recreated cost center should exist",
        )


class _FakeChapterDoc:
    """Minimal stand-in for a Chapter document.

    create_chapter_cost_center() only ever reads `.name` and `.cost_center`
    and calls `.db_set()` on its argument -- it does not resolve the company
    from chapter_doc.company (get_validated_company() reads Verenigingen
    Settings / Global Defaults instead), so a real Chapter row is unnecessary
    here and actively unwanted: self.create_chapter() ties its auto-created
    Cost Center to the shared default company via the real after_insert hook,
    and this test needs a company with a controlled (often zero) Cost Center
    count instead.
    """

    def __init__(self, name):
        self.name = name
        self.cost_center = None

    def db_set(self, field, value, update_modified=False):
        setattr(self, field, value)


class TestChapterCostCenterZeroCostCenterFallback(EnhancedTestCase):
    """#1441: get_appropriate_parent_cost_center() returns None for a company
    with literally zero Cost Centers. create_chapter_cost_center() used to
    then insert a non-root Cost Center with parent_cost_center completely
    unset -- ERPNext's blank-parent exception in
    CostCenter.validate_mandatory() only exempts cost_center_name == company,
    so this raised frappe.MandatoryError, swallowed by the function's own
    `except Exception` and only visible as a logged
    "[CHAPTER-CC-CREATE-ERR]" warning. The fix falls back to
    ensure_root_cost_center(company), which (post-#1359) can create that root
    even when the company starts with zero Cost Centers.

    Each test builds its own throwaway company (never the shared settings
    company) and uses _FakeChapterDoc rather than a real Chapter, so this
    class touches nothing any other class in the shard depends on.
    """

    def test_falls_back_to_root_cost_center_when_company_has_none(self):
        company = create_isolated_test_company(self, "TEST Chapter CC Fallback", "CF")
        delete_all_cost_centers(company)
        self.assertEqual(frappe.db.count("Cost Center", {"company": company}), 0)

        chapter = _FakeChapterDoc(f"Test Chapter Fallback Root {company}")

        svc = ChapterFinanceService()
        with patch.object(svc, "get_validated_company", return_value=company):
            svc.create_chapter_cost_center(chapter)

        self.assertIsNotNone(
            chapter.cost_center,
            "Cost center should have been created despite zero pre-existing Cost Centers",
        )
        cc = frappe.get_doc("Cost Center", chapter.cost_center)
        self.assertEqual(cc.company, company)

        root_name = frappe.db.get_value(
            "Cost Center",
            {"company": company, "is_group": 1, "parent_cost_center": ["in", ["", None]]},
            "name",
        )
        self.assertTrue(root_name, "ensure_root_cost_center() should have created a root")
        self.assertEqual(
            cc.parent_cost_center, root_name, "New cost center's parent should be the company root"
        )
        self.assertEqual(frappe.db.get_value("Cost Center", root_name, "cost_center_name"), company)

    def test_does_not_override_an_existing_group_cost_center(self):
        """Opposite-harm control: when a real (non-root) group Cost Center IS
        discoverable, the zero-Cost-Center fallback must not run at all -- it
        must not replace a legitimate parent with the company root."""
        company = create_isolated_test_company(self, "TEST Chapter CC Fallback", "CF")
        root_name = frappe.db.get_value(
            "Cost Center",
            {"company": company, "is_group": 1, "parent_cost_center": ["in", ["", None]]},
            "name",
        )
        self.assertTrue(root_name, "Company.on_update() should have created a default root")

        department_name = create_group_cost_center(company, "Department X", root_name)

        # Disable the root so get_appropriate_parent_cost_center()'s first
        # (root-by-name) check misses it and falls through to its own
        # any-active-group-cost-center fallback, which must find `department`
        # -- exercising the "a real group Cost Center exists" branch without
        # needing to delete the root (a group node with a live child cannot be
        # deleted, and this scenario is realistic: an admin can disable a Cost
        # Center without deleting it).
        frappe.db.set_value("Cost Center", root_name, "disabled", 1)

        chapter = _FakeChapterDoc(f"Test Chapter Fallback Group {company}")

        svc = ChapterFinanceService()
        with patch.object(svc, "get_validated_company", return_value=company):
            svc.create_chapter_cost_center(chapter)

        self.assertIsNotNone(chapter.cost_center)
        cc = frappe.get_doc("Cost Center", chapter.cost_center)
        self.assertEqual(
            cc.parent_cost_center,
            department_name,
            "Existing group Cost Center must be used as parent, not the company root",
        )
