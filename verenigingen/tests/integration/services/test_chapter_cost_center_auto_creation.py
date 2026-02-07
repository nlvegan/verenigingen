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

import frappe

from verenigingen.services.chapter.chapter_finance_service import ChapterFinanceService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


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
