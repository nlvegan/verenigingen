"""
Unit and Integration Tests for Cost Center Parsing

Tests the parse_groups_and_suggest_cost_centers function including:
- Tab vs space handling
- Balance sheet vs P&L filtering
- Cost center suggestion logic
"""

import frappe
import unittest
from verenigingen.e_boekhouden.doctype.e_boekhouden_settings import e_boekhouden_settings as eb_settings
from verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings import (
    clean_cost_center_name,
    create_cost_centers_from_mappings,
    create_single_cost_center,
    parse_groups_and_suggest_cost_centers,
    preview_cost_center_creation,
    should_suggest_cost_center,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCostCenterParsing(unittest.TestCase):
    """Test suite for cost center parsing functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.test_company = frappe.get_value("Company", {"company_name": "Test Company"}, "name")
        if not self.test_company:
            # Create test company if it doesn't exist
            company = frappe.get_doc(
                {
                    "doctype": "Company",
                    "company_name": "Test Company",
                    "abbr": "TC",
                    "default_currency": "EUR",
                    "country": "Netherlands",
                }
            )
            company.insert(ignore_permissions=True)
            self.test_company = company.name

    def test_parsing_with_spaces(self):
        """Test that parsing works correctly with space-separated values"""
        input_text = """007 Personeelskosten
008 Promotiekosten
009 Algemene kosten"""

        result = parse_groups_and_suggest_cost_centers(input_text, self.test_company)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["suggestions"]), 3)

        # Verify first entry
        self.assertEqual(result["suggestions"][0]["group_code"], "007")
        self.assertEqual(result["suggestions"][0]["group_name"], "Personeelskosten")

    def test_parsing_with_tabs(self):
        """Test that parsing works correctly with tab-separated values"""
        input_text = "007\tPersoneelskosten\n008\tPromotiekosten\n009\tAlgemene kosten"

        result = parse_groups_and_suggest_cost_centers(input_text, self.test_company)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["suggestions"]), 3)

        # Verify parsing correctly handles tabs
        self.assertEqual(result["suggestions"][0]["group_code"], "007")
        self.assertEqual(result["suggestions"][0]["group_name"], "Personeelskosten")

    def test_parsing_with_multiple_spaces(self):
        """Test that parsing works with multiple spaces between code and name"""
        input_text = """007    Personeelskosten
008     Promotiekosten"""

        result = parse_groups_and_suggest_cost_centers(input_text, self.test_company)

        self.assertTrue(result["success"])
        self.assertEqual(result["suggestions"][0]["group_code"], "007")
        self.assertEqual(result["suggestions"][0]["group_name"], "Personeelskosten")

    def test_parsing_multi_word_names(self):
        """Test that parsing correctly handles multi-word group names"""
        input_text = "033\tInterne evenementen"

        result = parse_groups_and_suggest_cost_centers(input_text, self.test_company)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["suggestions"]), 1)

        # Should NOT split the name on internal spaces
        self.assertEqual(result["suggestions"][0]["group_code"], "033")
        self.assertEqual(result["suggestions"][0]["group_name"], "Interne evenementen")

    def test_empty_input(self):
        """Test that empty input is handled gracefully"""
        result = parse_groups_and_suggest_cost_centers("", self.test_company)

        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_expense_group_suggestion(self):
        """Test that expense groups are suggested for cost center creation"""
        # Expense codes start with "5" (personnel) or "6" (other expenses)
        should_create, reason = should_suggest_cost_center("507", "Personeelskosten")

        self.assertTrue(should_create)
        self.assertIn("Expense", reason)

    def test_balance_sheet_not_suggested(self):
        """Test that balance sheet accounts are NOT suggested for cost centers"""
        # Balance sheet codes start with "1" (assets) or "2" (liabilities)
        should_create, reason = should_suggest_cost_center("101", "Materiële vaste activa")

        self.assertFalse(should_create)
        self.assertIn("Balance sheet", reason)

    def test_income_group_suggestion(self):
        """Test that income groups can be suggested for cost centers"""
        should_create, reason = should_suggest_cost_center("055", "Opbrengsten dienstverlening")

        # Income groups with specific keywords should be suggested
        self.assertTrue(should_create)

    def test_cost_center_name_cleaning(self):
        """Test that cost center names are properly cleaned"""
        cleaned = clean_cost_center_name("Personeelskosten rekeningen")

        self.assertEqual(cleaned, "Personeelskosten")

        cleaned2 = clean_cost_center_name("grootboek kosten")
        self.assertEqual(cleaned2, "Kosten")

    def test_operational_keywords_detection(self):
        """Test that operational keywords trigger cost center suggestions"""
        should_create, reason = should_suggest_cost_center("025", "Project Marketing")

        self.assertTrue(should_create)
        self.assertIn("departmental", reason.lower())

    def tearDown(self):
        """Clean up test data"""
        # Note: We don't delete the test company as it might be used by other tests
        pass


class TestCostCenterIntegration(unittest.TestCase):
    """Integration tests for cost center functionality with settings"""

    def setUp(self):
        """Set up test settings"""
        self.settings = frappe.get_single("E-Boekhouden Settings")

        # Backup original values
        self.original_pl_mappings = self.settings.get("pl_group_mappings")

    def test_settings_pl_mapping_parsing(self):
        """Test that settings correctly parse P&L mappings"""
        # Parser splits on space, not tab
        test_mappings = "007 Personeelskosten\n008 Promotiekosten"

        self.settings.pl_group_mappings = test_mappings

        # Parse using settings method
        parsed = self.settings._parse_pl_group_mappings()

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed["007"], "Personeelskosten")
        self.assertEqual(parsed["008"], "Promotiekosten")

    def test_balance_sheet_separate_from_pl(self):
        """Test that balance sheet and P&L mappings are kept separate"""
        # Parser splits on space, not tab
        self.settings.balance_sheet_group_mappings = "001 Vaste activa"
        self.settings.pl_group_mappings = "055 Opbrengsten"

        bal_parsed = self.settings._parse_balance_sheet_group_mappings()
        pl_parsed = self.settings._parse_pl_group_mappings()

        self.assertEqual(len(bal_parsed), 1)
        self.assertEqual(len(pl_parsed), 1)
        self.assertIn("001", bal_parsed)
        self.assertIn("055", pl_parsed)

    def tearDown(self):
        """Restore original settings"""
        if self.original_pl_mappings:
            self.settings.pl_group_mappings = self.original_pl_mappings
            self.settings.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Pure-logic branch coverage for should_suggest_cost_center
# (asserts the EXACT branch each input falls into via the reason string).
# ---------------------------------------------------------------------------
class TestShouldSuggestCostCenterBranches(unittest.TestCase):
    """should_suggest_cost_center: assert each decision branch + reason."""

    def test_expense_code_with_expense_keyword(self):
        # Code 5/6 + expense keyword -> expense-tracking branch
        ok, reason = should_suggest_cost_center("507", "Personeelskosten")
        self.assertTrue(ok)
        self.assertEqual(reason, "Expense group - good for cost tracking")

    def test_expense_code_without_keyword_falls_through(self):
        # Code 5 but name has no expense/cost/operational keyword -> not suitable.
        # "Afschrijvingen" is not in any keyword list, so it must NOT be suggested.
        ok, reason = should_suggest_cost_center("580", "Afschrijvingen")
        self.assertFalse(ok)
        self.assertEqual(reason, "Not suitable for cost center tracking")

    def test_revenue_code_with_revenue_keyword(self):
        # Code 3 + revenue keyword -> revenue branch (reached before operational).
        ok, reason = should_suggest_cost_center("300", "Omzet verkopen")
        self.assertTrue(ok)
        self.assertEqual(reason, "Revenue group - useful for departmental income tracking")

    def test_operational_keyword_branch(self):
        ok, reason = should_suggest_cost_center("025", "Project Marketing")
        self.assertTrue(ok)
        self.assertEqual(reason, "Contains departmental/operational keywords")

    def test_cost_keyword_branch_on_non_expense_code(self):
        # Code 4 (not 5/6, not 3) but name contains "kosten" -> cost-related branch.
        ok, reason = should_suggest_cost_center("400", "Inkoopkosten")
        self.assertTrue(ok)
        self.assertEqual(reason, "Cost-related group")

    def test_balance_sheet_asset_explicitly_rejected(self):
        ok, reason = should_suggest_cost_center("101", "Materiele vaste activa")
        self.assertFalse(ok)
        self.assertEqual(reason, "Balance sheet item - cost center not needed")

    def test_balance_sheet_liability_bank_rejected(self):
        ok, reason = should_suggest_cost_center("210", "Bankschulden")
        self.assertFalse(ok)
        self.assertEqual(reason, "Balance sheet item - cost center not needed")

    def test_balance_sheet_code_without_balance_keyword_not_rejected_explicitly(self):
        # Code 1 but name lacks a balance keyword (activa/passiva/...) -> generic
        # "not suitable", NOT the balance-sheet-specific message.
        ok, reason = should_suggest_cost_center("150", "Inventaris")
        self.assertFalse(ok)
        self.assertEqual(reason, "Not suitable for cost center tracking")

    def test_case_insensitive_keyword_match(self):
        ok, _ = should_suggest_cost_center("600", "ALGEMENE KOSTEN")
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# Additional clean_cost_center_name edge cases.
# ---------------------------------------------------------------------------
class TestCleanCostCenterNameEdges(unittest.TestCase):
    def test_all_removed_words_yield_empty(self):
        self.assertEqual(clean_cost_center_name("rekeningen grootboek accounts"), "")

    def test_html_entity_decoded(self):
        # &amp; -> & and first letter capitalized
        self.assertEqual(clean_cost_center_name("bestuur &amp; beleid"), "Bestuur & beleid")

    def test_collapses_multiple_internal_spaces(self):
        self.assertEqual(clean_cost_center_name("Marketing    en   Sales"), "Marketing en Sales")

    def test_single_char_uppercased(self):
        self.assertEqual(clean_cost_center_name("a"), "A")

    def test_removal_is_word_boundary_only(self):
        # "rekeningen" as a whole word is removed; a substring inside another word
        # ("grootboekje") must NOT be touched.
        self.assertEqual(clean_cost_center_name("grootboekje kosten"), "Grootboekje kosten")


# ---------------------------------------------------------------------------
# parse_groups_and_suggest_cost_centers: structure + is_group grouping.
# ---------------------------------------------------------------------------
class TestParseGroupsSuggestStructure(unittest.TestCase):
    def setUp(self):
        self.company = frappe.db.get_value("Company", {}, "name")

    def test_is_group_flag_when_child_present(self):
        # "05" has children "0501"/"0502" sharing the 2-char prefix -> is_group True;
        # the children themselves have no longer-code descendants -> is_group False.
        text = "05 Personeelskosten\n0501 Salarissen\n0502 Sociale lasten"
        result = parse_groups_and_suggest_cost_centers(text, self.company)
        self.assertTrue(result["success"])
        by_code = {s["group_code"]: s for s in result["suggestions"]}
        self.assertTrue(by_code["05"]["is_group"])
        self.assertFalse(by_code["0501"]["is_group"])

    def test_suggested_count_matches_create_flags(self):
        text = "507 Personeelskosten\n101 Vaste activa"
        result = parse_groups_and_suggest_cost_centers(text, self.company)
        self.assertEqual(result["total_groups"], 2)
        # 507 (expense+keyword) suggested; 101 (balance sheet asset) not.
        self.assertEqual(result["suggested_count"], 1)
        by_code = {s["group_code"]: s for s in result["suggestions"]}
        self.assertTrue(by_code["507"]["create_cost_center"])
        self.assertEqual(by_code["507"]["cost_center_name"], "Personeelskosten")
        self.assertFalse(by_code["101"]["create_cost_center"])
        self.assertEqual(by_code["101"]["cost_center_name"], "")

    def test_whitespace_only_line_skipped(self):
        result = parse_groups_and_suggest_cost_centers("507 Personeelskosten\n   \n", self.company)
        self.assertEqual(result["total_groups"], 1)

    def test_lines_without_name_are_dropped(self):
        # A bare code with no name is not a valid group (regex split yields 1 part).
        result = parse_groups_and_suggest_cost_centers("507 Personeelskosten\n999", self.company)
        self.assertEqual(result["total_groups"], 1)


# ---------------------------------------------------------------------------
# DB-touching whitelisted functions: preview + real creation.
# Uses a company DERIVED from an existing Account so a chart of accounts is
# guaranteed (an arbitrary Company may have none).
# ---------------------------------------------------------------------------
class _CostCenterDBBase(EnhancedTestCase):
    SINGLE = "E-Boekhouden Settings"
    CHILD_DT = "E-Boekhouden Cost Center Mapping"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Derive a company that is guaranteed to have a cost-center tree.
        cc = frappe.db.get_value("Cost Center", {"is_group": 1}, ["name", "company"], as_dict=True)
        cls.company = cc.company if cc else frappe.db.get_value("Company", {}, "name")
        cls._orig_company = frappe.db.get_single_value(cls.SINGLE, "default_company")
        frappe.db.set_single_value(cls.SINGLE, "default_company", cls.company)
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        frappe.db.set_single_value(cls.SINGLE, "default_company", cls._orig_company)
        frappe.db.commit()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self._orig_children = frappe.get_all(
            self.CHILD_DT,
            filters={"parent": self.SINGLE, "parenttype": self.SINGLE},
            fields=["group_code", "group_name", "create_cost_center", "cost_center_name", "is_group"],
            order_by="idx",
        )
        self._clear_children()

    def tearDown(self):
        self._clear_children()
        for idx, row in enumerate(self._orig_children, start=1):
            child = frappe.new_doc(self.CHILD_DT)
            child.parent = self.SINGLE
            child.parenttype = self.SINGLE
            child.parentfield = "cost_center_mappings"
            child.idx = idx
            child.group_code = row.group_code
            child.group_name = row.group_name
            child.create_cost_center = row.create_cost_center
            child.cost_center_name = row.cost_center_name
            child.is_group = row.is_group
            child.db_insert()
        frappe.db.commit()
        super().tearDown()

    def _clear_children(self):
        frappe.db.delete(self.CHILD_DT, {"parent": self.SINGLE, "parenttype": self.SINGLE})

    def _add_mapping(self, idx, **fields):
        child = frappe.new_doc(self.CHILD_DT)
        child.parent = self.SINGLE
        child.parenttype = self.SINGLE
        child.parentfield = "cost_center_mappings"
        child.idx = idx
        child.update(fields)
        child.db_insert()
        return child


class TestPreviewCostCenterCreation(_CostCenterDBBase):
    def test_no_mappings_returns_error(self):
        result = preview_cost_center_creation()
        self.assertFalse(result["success"])
        self.assertIn("No cost center mappings", result["error"])

    def test_preview_lists_new_and_existing(self):
        # One brand-new cost center + one that already exists (the company group CC).
        existing_cc = frappe.db.get_value(
            "Cost Center", {"company": self.company, "is_group": 1}, "cost_center_name"
        )
        unique = f"EBTEST-CC-{frappe.generate_hash()[:6]}"
        self._add_mapping(
            1, group_code="507", group_name="Personeelskosten", create_cost_center=1, cost_center_name=unique
        )
        self._add_mapping(
            2, group_code="508", group_name="Bestaand", create_cost_center=1, cost_center_name=existing_cc
        )
        # A row with create flag off must be excluded entirely.
        self._add_mapping(
            3, group_code="509", group_name="Skip", create_cost_center=0, cost_center_name="NotUsed"
        )

        result = preview_cost_center_creation()
        self.assertTrue(result["success"])
        self.assertEqual(result["total_to_process"], 2)
        self.assertEqual(result["would_create"], 1)
        self.assertEqual(result["would_skip"], 1)
        by_name = {r["cost_center_name"]: r for r in result["preview_results"]}
        self.assertFalse(by_name[unique]["already_exists"])
        self.assertEqual(by_name[unique]["action"], "Create new")
        self.assertTrue(by_name[existing_cc]["already_exists"])
        self.assertEqual(by_name[existing_cc]["action"], "Skip (already exists)")
        # generate_cost_center_id appends the company suffix.
        self.assertEqual(by_name[unique]["cost_center_id"], f"{unique} - {self.company}")


class TestCreateCostCentersFromMappings(_CostCenterDBBase):
    def test_no_mappings_configured_for_creation(self):
        # Mapping present but create flag off -> "configured for creation" error.
        self._add_mapping(1, group_code="507", group_name="X", create_cost_center=0, cost_center_name="X")
        result = create_cost_centers_from_mappings()
        self.assertFalse(result["success"])
        self.assertIn("configured for creation", result["error"])

    def test_creates_new_cost_center_and_is_idempotent(self):
        unique = f"EBTEST-CC-{frappe.generate_hash()[:6]}"
        self._add_mapping(
            1,
            group_code="507",
            group_name="Personeelskosten",
            create_cost_center=1,
            cost_center_name=unique,
            is_group=0,
        )
        try:
            result = create_cost_centers_from_mappings()
            self.assertTrue(result["success"])
            self.assertEqual(result["created_count"], 1)
            self.assertEqual(result["failed_count"], 0)
            created = result["created_cost_centers"][0]
            self.assertEqual(created["cost_center_name"], unique)
            self.assertTrue(frappe.db.exists("Cost Center", created["cost_center_id"]))

            # Second run must SKIP (already exists), not fail or duplicate.
            result2 = create_cost_centers_from_mappings()
            self.assertTrue(result2["success"])
            self.assertEqual(result2["created_count"], 0)
            self.assertEqual(result2["skipped_count"], 1)
            self.assertIn("already exists", result2["skipped_cost_centers"][0]["reason"])
        finally:
            frappe.db.delete("Cost Center", {"cost_center_name": unique, "company": self.company})
            frappe.db.commit()

    def test_create_single_cost_center_skips_existing(self):
        existing_cc = frappe.db.get_value(
            "Cost Center", {"company": self.company, "is_group": 1}, "cost_center_name"
        )
        mapping = frappe._dict(
            cost_center_name=existing_cc,
            is_group=1,
            parent_cost_center=None,
            group_code="500",
            group_name="Dup",
            suggestion_reason=None,
        )
        result = create_single_cost_center(mapping, self.company)
        self.assertFalse(result["success"])
        self.assertTrue(result["skipped"])
        self.assertIn("already exists", result["reason"])


# ---------------------------------------------------------------------------
# Thin hierarchy-service wrappers: assert pass-through with dry_run (no mutation).
# ---------------------------------------------------------------------------
class TestHierarchyWrappers(unittest.TestCase):
    def test_reclassify_wrapper_returns_dict_dry_run(self):
        result = eb_settings.reclassify_accounts_by_group_mappings(dry_run=True)
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)

    def test_reorganize_wrapper_returns_dict_dry_run(self):
        result = eb_settings.reorganize_account_hierarchy(dry_run=True)
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
