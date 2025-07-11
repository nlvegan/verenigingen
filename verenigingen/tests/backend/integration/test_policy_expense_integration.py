"""
Unit tests for policy-covered expense functionality
Tests the national policy-based expense system with ERPNext integration

Created: December 2024 - Policy-based expenses implementation
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.templates.pages.volunteer.expenses import is_policy_covered_expense, submit_expense


class TestPolicyExpenseIntegration(unittest.TestCase):
    """Test policy-covered expense functionality"""

    def setUp(self):
        """Set up for each test"""
        frappe.set_user("Administrator")
        self.policy_expense_data = {
            "description": "Policy-covered travel expense",
            "amount": 85.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel",  # Policy-covered category
            "notes": "Business trip for organization activities",
        }

        self.non_policy_expense_data = {
            "description": "Non-policy office equipment",
            "amount": 200.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Equipment",  # Non-policy category
            "notes": "Office equipment purchase",
        }

    def tearDown(self):
        """Clean up after each test"""
        frappe.db.rollback()

    def test_is_policy_covered_expense_with_flag(self):
        """Test policy coverage detection using category flag"""
        # Mock expense category with policy_covered flag
        mock_category = MagicMock()
        mock_category.policy_covered = True

        with patch("frappe.get_doc", return_value=mock_category):
            result = is_policy_covered_expense("Travel")
            self.assertTrue(result)

    def test_is_policy_covered_expense_without_flag(self):
        """Test policy coverage detection for categories without flag"""
        # Mock expense category without policy_covered flag
        mock_category = MagicMock()
        mock_category.policy_covered = False
        mock_category.category_name = "Travel"

        with patch("frappe.get_doc", return_value=mock_category):
            result = is_policy_covered_expense("Travel")
            self.assertTrue(result)  # Should still be covered due to fallback logic

    def test_is_policy_covered_expense_fallback_logic(self):
        """Test fallback logic for policy coverage"""
        # Test with category names that should be policy-covered
        policy_covered_names = ["Travel", "Materials", "Office Supplies", "Events"]

        for category_name in policy_covered_names:
            mock_category = MagicMock()
            mock_category.policy_covered = False  # No explicit flag
            mock_category.category_name = category_name

            with patch("frappe.get_doc", return_value=mock_category):
                result = is_policy_covered_expense(category_name)
                self.assertTrue(result, f"{category_name} should be policy-covered")

    def test_is_policy_covered_expense_not_covered(self):
        """Test non-policy-covered expenses"""
        # Mock non-policy category
        mock_category = MagicMock()
        mock_category.policy_covered = False
        mock_category.category_name = "Expensive Equipment"

        with patch("frappe.get_doc", return_value=mock_category):
            result = is_policy_covered_expense("Expensive Equipment")
            self.assertFalse(result)

    def test_is_policy_covered_expense_error_handling(self):
        """Test error handling in policy coverage check"""
        # Mock exception during category lookup
        with patch("frappe.get_doc", side_effect=Exception("Category not found")):
            result = is_policy_covered_expense("NonExistent")
            self.assertFalse(result)  # Should default to False on error

    def test_policy_expense_submission_allowed_for_any_volunteer(self):
        """Test that any volunteer can submit policy-covered national expenses"""
        # Mock regular volunteer (not national board member)
        mock_volunteer = MagicMock()
        mock_volunteer.name = "REG-VOL-001"
        mock_volunteer.volunteer_name = "Regular Volunteer"
        mock_volunteer.employee_id = "HR-EMP-001"

        # Mock policy-covered category
        with patch(
            "verenigingen.templates.pages.volunteer.expenses.is_policy_covered_expense", return_value=True
        ):
            with patch(
                "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
                return_value=mock_volunteer,
            ):
                with patch("frappe.get_doc", return_value=MagicMock(name="EXP-POLICY-001")):
                    with patch(
                        "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                        return_value="Travel",
                    ):
                        with patch(
                            "verenigingen.templates.pages.volunteer.expenses.get_organization_cost_center",
                            return_value="National Cost Center",
                        ):
                            with patch("frappe.get_single") as mock_get_single:
                                # Mock settings with national chapter
                                mock_settings = MagicMock()
                                mock_settings.national_board_chapter = "National Board"
                                mock_get_single.return_value = mock_settings

                                # Mock no board membership (regular volunteer)
                                with patch("frappe.db.exists", return_value=False):
                                    with patch(
                                        "verenigingen.templates.pages.volunteer.expenses.is_policy_covered_expense",
                                        return_value=True,
                                    ):
                                        with patch(
                                            "frappe.defaults.get_global_default", return_value="Test Company"
                                        ):
                                            with patch("frappe.db.get_value", return_value="Test Account"):
                                                result = submit_expense(self.policy_expense_data)

                                                # Should succeed for policy-covered expense
                                                self.assertTrue(
                                                    result.get("success"),
                                                    f"Policy-covered expense should be allowed: {result.get('message')}",
                                                )

    def test_non_policy_expense_requires_board_membership(self):
        """Test that non-policy national expenses require board membership"""
        # Mock regular volunteer (not national board member)
        mock_volunteer = MagicMock()
        mock_volunteer.name = "REG-VOL-002"
        mock_volunteer.volunteer_name = "Regular Volunteer"
        mock_volunteer.employee_id = "HR-EMP-002"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_single") as mock_get_single:
                # Mock settings with national chapter
                mock_settings = MagicMock()
                mock_settings.national_board_chapter = "National Board"
                mock_get_single.return_value = mock_settings

                # Mock no board membership (regular volunteer)
                with patch("frappe.db.exists", return_value=False):
                    with patch(
                        "verenigingen.templates.pages.volunteer.expenses.is_policy_covered_expense",
                        return_value=False,
                    ):
                        result = submit_expense(self.non_policy_expense_data)

                        # Should fail for non-policy expense without board membership
                        self.assertFalse(result.get("success"))
                        self.assertIn("board membership required", result.get("message", "").lower())

    def test_policy_expense_with_board_member(self):
        """Test that board members can submit any national expense"""
        # Mock board member volunteer
        mock_volunteer = MagicMock()
        mock_volunteer.name = "BOARD-VOL-001"
        mock_volunteer.volunteer_name = "Board Member"
        mock_volunteer.employee_id = "HR-EMP-003"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc", return_value=MagicMock(name="EXP-BOARD-001")):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Equipment",
                ):
                    with patch(
                        "verenigingen.templates.pages.volunteer.expenses.get_organization_cost_center",
                        return_value="National Cost Center",
                    ):
                        with patch("frappe.get_single") as mock_get_single:
                            # Mock settings with national chapter
                            mock_settings = MagicMock()
                            mock_settings.national_board_chapter = "National Board"
                            mock_get_single.return_value = mock_settings

                            # Mock board membership
                            with patch("frappe.db.exists", return_value=True):
                                with patch(
                                    "verenigingen.templates.pages.volunteer.expenses.is_policy_covered_expense",
                                    return_value=False,
                                ):
                                    with patch(
                                        "frappe.defaults.get_global_default", return_value="Test Company"
                                    ):
                                        with patch("frappe.db.get_value", return_value="Test Account"):
                                            result = submit_expense(self.non_policy_expense_data)

                                            # Should succeed for board member even with non-policy expense
                                            self.assertTrue(result.get("success"))

    def test_policy_expense_categories_setup(self):
        """Test that policy expense categories are properly configured"""
        # Mock expense categories with policy_covered field
        mock_categories = [
            {"name": "Travel", "category_name": "Travel", "policy_covered": True},
            {"name": "Materials", "category_name": "Campaign Materials", "policy_covered": True},
            {"name": "Events", "category_name": "Event Supplies", "policy_covered": True},
            {"name": "Equipment", "category_name": "Office Equipment", "policy_covered": False},
        ]

        with patch("frappe.get_all", return_value=mock_categories):
            # Test getting policy-covered categories
            policy_categories = frappe.get_all(
                "Expense Category",
                filters={"policy_covered": 1},
                fields=["name", "category_name", "policy_covered"],
            )

            # Should find policy-covered categories
            self.assertGreater(len(policy_categories), 0)

            # All returned categories should be policy-covered
            for category in policy_categories:
                self.assertTrue(category.get("policy_covered"))

    def test_policy_expense_with_attachment(self):
        """Test policy expense submission with receipt attachment"""
        policy_data_with_attachment = self.policy_expense_data.copy()
        policy_data_with_attachment["receipt_attachment"] = "/files/receipt_001.pdf"

        mock_volunteer = MagicMock()
        mock_volunteer.name = "VOL-ATTACH-001"
        mock_volunteer.employee_id = "HR-EMP-004"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc") as mock_get_doc:
                mock_expense_claim = MagicMock()
                mock_expense_claim.name = "EXP-ATTACH-001"
                mock_get_doc.return_value = mock_expense_claim

                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    with patch(
                        "verenigingen.templates.pages.volunteer.expenses.get_organization_cost_center",
                        return_value="National Cost Center",
                    ):
                        with patch(
                            "verenigingen.templates.pages.volunteer.expenses.is_policy_covered_expense",
                            return_value=True,
                        ):
                            with patch("frappe.defaults.get_global_default", return_value="Test Company"):
                                with patch("frappe.db.get_value", return_value="Test Account"):
                                    result = submit_expense(policy_data_with_attachment)

                                    # Should succeed with attachment
                                    self.assertTrue(result.get("success"))

                                    # Verify attachment was added
                                    mock_expense_claim.append.assert_called()

    def test_policy_expense_amount_limits(self):
        """Test policy expenses with different amount limits"""
        amounts_to_test = [25.00, 100.00, 250.00, 500.00, 750.00]

        for amount in amounts_to_test:
            with self.subTest(amount=amount):
                test_data = self.policy_expense_data.copy()
                test_data["amount"] = amount

                mock_volunteer = MagicMock()
                mock_volunteer.name = f"VOL-AMT-{int(amount)}"
                mock_volunteer.employee_id = f"HR-EMP-{int(amount)}"

                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
                    return_value=mock_volunteer,
                ):
                    with patch("frappe.get_doc", return_value=MagicMock(name=f"EXP-AMT-{int(amount)}")):
                        with patch(
                            "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                            return_value="Travel",
                        ):
                            with patch(
                                "verenigingen.templates.pages.volunteer.expenses.get_organization_cost_center",
                                return_value="National Cost Center",
                            ):
                                with patch(
                                    "verenigingen.templates.pages.volunteer.expenses.is_policy_covered_expense",
                                    return_value=True,
                                ):
                                    with patch(
                                        "frappe.defaults.get_global_default", return_value="Test Company"
                                    ):
                                        with patch("frappe.db.get_value", return_value="Test Account"):
                                            result = submit_expense(test_data)

                                            # Policy expenses should work regardless of amount
                                            self.assertTrue(
                                                result.get("success"),
                                                f"Policy expense with amount €{amount} should succeed",
                                            )

    def test_policy_expense_logging(self):
        """Test that policy expense approvals are properly logged"""
        mock_volunteer = MagicMock()
        mock_volunteer.name = "VOL-LOG-001"
        mock_volunteer.employee_id = "HR-EMP-LOG"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc", return_value=MagicMock(name="EXP-LOG-001")):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    with patch(
                        "verenigingen.templates.pages.volunteer.expenses.get_organization_cost_center",
                        return_value="National Cost Center",
                    ):
                        with patch(
                            "verenigingen.templates.pages.volunteer.expenses.is_policy_covered_expense",
                            return_value=True,
                        ):
                            with patch("frappe.logger") as mock_logger:
                                with patch("frappe.defaults.get_global_default", return_value="Test Company"):
                                    with patch("frappe.db.get_value", return_value="Test Account"):
                                        result = submit_expense(self.policy_expense_data)

                                        # Should succeed and log the policy allowance
                                        self.assertTrue(result.get("success"))

                                        # Verify logging was called
                                        mock_logger.return_value.info.assert_called()

    def test_national_chapter_configuration_missing(self):
        """Test behavior when national chapter is not configured"""
        mock_volunteer = MagicMock()
        mock_volunteer.name = "VOL-NO-NATIONAL"
        mock_volunteer.employee_id = "HR-EMP-NO-NAT"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_single") as mock_get_single:
                # Mock settings without national chapter
                mock_settings = MagicMock()
                mock_settings.national_board_chapter = None
                mock_get_single.return_value = mock_settings

                result = submit_expense(self.policy_expense_data)

                # Should fail when national chapter not configured
                self.assertFalse(result.get("success"))
                self.assertIn("national chapter not configured", result.get("message", "").lower())


class TestPolicyExpenseReporting(unittest.TestCase):
    """Test policy expense reporting and analytics"""

    def setUp(self):
        frappe.set_user("Administrator")

    def test_policy_expense_tracking_in_report(self):
        """Test that policy expenses are properly tracked in reports"""
        from verenigingen.verenigingen.report.chapter_expense_report.chapter_expense_report import (
            build_expense_row,
        )

        # Test building report row for policy expense
        with patch("frappe.db.count", return_value=1):
            row = build_expense_row(
                name="EXP-POLICY-001",
                volunteer_name="Policy Test User",
                description="Policy-covered travel",
                amount=150.00,
                expense_date="2024-12-14",
                category_name="Travel",
                organization_type="National",
                organization_name="National",
                status="Approved",
                is_erpnext=True,
                expense_claim_id="EXP-POLICY-001",
            )

            # Should create proper report row
            self.assertEqual(row["name"], "EXP-POLICY-001")
            self.assertEqual(row["organization_type"], "National")
            self.assertEqual(row["category_name"], "Travel")
            self.assertEqual(row["approval_level"], "Financial")

    def test_policy_expense_statistics(self):
        """Test statistics calculation for policy expenses"""
        # Mock expense data with policy and non-policy expenses
        test_expenses = [
            {"amount": 100, "status": "Approved", "category_name": "Travel", "organization_type": "National"},
            {
                "amount": 75,
                "status": "Approved",
                "category_name": "Materials",
                "organization_type": "National",
            },
            {
                "amount": 500,
                "status": "Approved",
                "category_name": "Equipment",
                "organization_type": "National",
            },
            {"amount": 50, "status": "Approved", "category_name": "Travel", "organization_type": "Chapter"},
        ]

        # Policy expenses would be Travel and Materials (national)
        policy_expenses = [
            exp
            for exp in test_expenses
            if exp["organization_type"] == "National" and exp["category_name"] in ["Travel", "Materials"]
        ]

        total_policy_amount = sum(exp["amount"] for exp in policy_expenses)

        # Should properly identify and sum policy expenses
        self.assertEqual(len(policy_expenses), 2)
        self.assertEqual(total_policy_amount, 175)


if __name__ == "__main__":
    unittest.main()
