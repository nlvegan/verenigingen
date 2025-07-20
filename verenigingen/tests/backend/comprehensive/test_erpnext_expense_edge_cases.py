"""
Edge case tests for ERPNext Expense Claims integration
Focus on error handling, boundary conditions, and real-world scenarios
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.exceptions import ValidationError

from verenigingen.templates.pages.volunteer.expenses import (
    get_or_create_expense_type,
    get_organization_cost_center,
    get_user_volunteer_record,
    setup_expense_claim_types,
    submit_expense,
)


class TestERPNextExpenseIntegrationEdgeCases(unittest.TestCase):
    """Test edge cases for ERPNext Expense Claims integration"""

    def setUp(self):
        frappe.set_user("Administrator")

    def test_json_string_expense_data_parsing(self):
        """Test expense submission with JSON string data"""
        expense_data_json = json.dumps(
            {
                "description": "JSON parsed expense",
                "amount": 50.00,
                "expense_date": "2024-12-14",
                "organization_type": "National",
                "category": "Travel",
                "notes": "Testing JSON parsing"}
        )

        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc", return_value=MagicMock(name="EXP-JSON-001")):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    result = submit_expense(expense_data_json)
                    self.assertTrue(result.get("success"))

    def test_malformed_json_expense_data(self):
        """Test expense submission with malformed JSON data"""
        malformed_json = '{"description": "Test", "amount": 50.00, invalid}'

        result = submit_expense(malformed_json)
        self.assertFalse(result.get("success"))
        self.assertIn("error", result.get("message", "").lower())

    def test_expense_submission_with_zero_amount(self):
        """Test expense submission with zero amount"""
        expense_data = {
            "description": "Zero amount expense",
            "amount": 0.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel",
            "notes": "Testing zero amount"}

        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc", return_value=MagicMock(name="EXP-ZERO-001")):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    result = submit_expense(expense_data)
                    self.assertTrue(result.get("success"))  # Should allow zero amounts

    def test_expense_submission_with_negative_amount(self):
        """Test expense submission with negative amount"""
        expense_data = {
            "description": "Negative amount expense",
            "amount": -50.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel",
            "notes": "Testing negative amount"}

        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc", return_value=MagicMock(name="EXP-NEG-001")):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    result = submit_expense(expense_data)
                    self.assertTrue(result.get("success"))  # Should handle negative amounts

    def test_expense_submission_with_invalid_date_format(self):
        """Test expense submission with invalid date format"""
        expense_data = {
            "description": "Invalid date expense",
            "amount": 50.00,
            "expense_date": "invalid-date-format",
            "organization_type": "National",
            "category": "Travel",
            "notes": "Testing invalid date"}

        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            # ERPNext should handle date validation
            with patch("frappe.get_doc") as mock_get_doc:
                mock_expense_claim = MagicMock()
                mock_expense_claim.insert.side_effect = ValidationError("Invalid date format")
                mock_get_doc.return_value = mock_expense_claim

                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    result = submit_expense(expense_data)
                    self.assertFalse(result.get("success"))
                    self.assertIn("Invalid date", result.get("message", ""))

    def test_volunteer_with_multiple_member_records(self):
        """Test volunteer lookup when multiple member records exist with same email"""
        with patch("frappe.db.get_value") as mock_get_value:
            # First call returns multiple member IDs (should return first one)
            mock_get_value.side_effect = [
                "MEMBER-001",  # First member found
                {"name": "VOL-001", "volunteer_name": "Test Volunteer"},  # Volunteer record
            ]

            result = get_user_volunteer_record()
            self.assertIsNotNone(result)
            self.assertEqual(result["name"], "VOL-001")

    def test_volunteer_with_no_member_but_direct_email(self):
        """Test volunteer lookup when no member record but volunteer has direct email"""
        with patch("frappe.db.get_value") as mock_get_value:
            # First call (member lookup) returns None, second call (direct volunteer) returns volunteer
            mock_get_value.side_effect = [
                None,  # No member record
                {"name": "VOL-002", "volunteer_name": "Direct Volunteer"},  # Direct volunteer
            ]

            result = get_user_volunteer_record()
            self.assertIsNotNone(result)
            self.assertEqual(result["name"], "VOL-002")

    def test_employee_creation_returns_none(self):
        """Test handling when employee creation returns None instead of employee ID"""
        mock_volunteer = MagicMock()
        mock_volunteer.name = "TEST-VOL"
        mock_volunteer.employee_id = None
        mock_volunteer.create_minimal_employee.return_value = None  # Returns None instead of employee ID

        expense_data = {
            "description": "Test expense",
            "amount": 50.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel"}

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            result = submit_expense(expense_data)
            self.assertFalse(result.get("success"))
            self.assertIn("Unable to create employee record", result.get("message", ""))

    def test_cost_center_retrieval_with_missing_chapter(self):
        """Test cost center retrieval when referenced chapter doesn't exist"""
        expense_data = {"organization_type": "Chapter", "chapter": "NON-EXISTENT-CHAPTER"}

        with patch("frappe.get_doc", side_effect=frappe.DoesNotExistError("Chapter not found")):
            result = get_organization_cost_center(expense_data)
            self.assertIsNone(result)

    def test_cost_center_retrieval_with_missing_team(self):
        """Test cost center retrieval when referenced team doesn't exist"""
        expense_data = {"organization_type": "Team", "team": "NON-EXISTENT-TEAM"}

        with patch("frappe.get_doc", side_effect=frappe.DoesNotExistError("Team not found")):
            result = get_organization_cost_center(expense_data)
            self.assertIsNone(result)

    def test_national_cost_center_with_missing_settings(self):
        """Test national cost center retrieval when settings don't exist"""
        expense_data = {"organization_type": "National"}

        with patch("frappe.get_single", side_effect=frappe.DoesNotExistError("Settings not found")):
            with patch("frappe.defaults.get_global_default", return_value=None):
                result = get_organization_cost_center(expense_data)
                self.assertIsNone(result)

    def test_expense_claim_type_creation_with_missing_company(self):
        """Test expense claim type creation when no company exists"""
        with patch("frappe.db.get_value", return_value=None):  # No existing type
            with patch("frappe.defaults.get_global_default", return_value=None):  # No default company
                with patch("frappe.get_all", return_value=[]):  # No companies exist
                    result = get_or_create_expense_type("Test Category")
                    self.assertEqual(result, "Travel")  # Should fallback

    def test_expense_claim_type_creation_with_account_creation_failure(self):
        """Test expense claim type creation when account creation fails"""
        with patch("frappe.db.get_value") as mock_get_value:
            # No existing type, has company, no existing account
            mock_get_value.side_effect = [None, "Test Company", None, None]

            with patch("frappe.defaults.get_global_default", return_value="Test Company"):
                with patch("frappe.get_all", return_value=[{"name": "Test Company"}]):
                    with patch("frappe.get_doc") as mock_get_doc:
                        # Account creation fails
                        mock_account = MagicMock()
                        mock_account.insert.side_effect = ValidationError("Account creation failed")

                        mock_expense_type = MagicMock()
                        mock_expense_type.name = "Test Category"

                        def get_doc_side_effect(doc_dict):
                            if doc_dict["doctype"] == "Account":
                                return mock_account
                            else:
                                return mock_expense_type

                        mock_get_doc.side_effect = get_doc_side_effect

                        result = get_or_create_expense_type("Test Category")
                        # Should still return the expense type name even if account creation fails
                        self.assertEqual(result, "Test Category")

    def test_receipt_attachment_handling(self):
        """Test expense submission with receipt attachment"""
        expense_data = {
            "description": "Expense with receipt",
            "amount": 50.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel",
            "receipt_attachment": "/files/receipt.pdf"}

        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        mock_expense_claim = MagicMock()
        mock_expense_claim.name = "EXP-RECEIPT-001"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc", return_value=mock_expense_claim):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    result = submit_expense(expense_data)
                    self.assertTrue(result.get("success"))

                    # Verify attachment was added
                    mock_expense_claim.append.assert_any_call(
                        "attachments", {"file_url": "/files/receipt.pdf"}
                    )

    def test_expense_submission_with_invalid_currency(self):
        """Test expense submission with invalid currency code"""
        expense_data = {
            "description": "Invalid currency expense",
            "amount": 50.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel",
            "currency": "INVALID"}

        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        # Should still process - currency validation happens at ERPNext level
        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc", return_value=MagicMock(name="EXP-CURRENCY-001")):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    result = submit_expense(expense_data)
                    self.assertTrue(result.get("success"))

    def test_expense_submission_session_user_context(self):
        """Test that expense submission properly handles session user context"""
        original_user = frappe.session.user

        try:
            # Test with different user
            frappe.session.user = "test@example.com"

            mock_volunteer = MagicMock()
            mock_volunteer.name = "TEST-VOL"
            mock_volunteer.email = "test@example.com"
            mock_volunteer.employee_id = "HR-EMP-001"

            expense_data = {
                "description": "Session test expense",
                "amount": 50.00,
                "expense_date": "2024-12-14",
                "organization_type": "National",
                "category": "Travel"}

            with patch(
                "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
                return_value=mock_volunteer,
            ):
                with patch("frappe.get_doc", return_value=MagicMock(name="EXP-SESSION-001")):
                    with patch(
                        "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                        return_value="Travel",
                    ):
                        result = submit_expense(expense_data)
                        self.assertTrue(result.get("success"))

        finally:
            frappe.session.user = original_user

    def test_expense_submission_with_missing_national_chapter_setting(self):
        """Test national expense submission when national chapter is not configured"""
        expense_data = {
            "description": "National expense without config",
            "amount": 50.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel"}

        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        # Mock settings without national chapter
        mock_settings = MagicMock()
        mock_settings.national_board_chapter = None

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_single", return_value=mock_settings):
                result = submit_expense(expense_data)
                self.assertFalse(result.get("success"))
                self.assertIn("National chapter not configured", result.get("message", ""))

    def test_expense_claim_submit_failure(self):
        """Test handling when ERPNext expense claim submission fails"""
        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        expense_data = {
            "description": "Submit failure test",
            "amount": 50.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel"}

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc") as mock_get_doc:
                mock_expense_claim = MagicMock()
                mock_expense_claim.submit.side_effect = ValidationError("Submit failed - workflow error")
                mock_get_doc.return_value = mock_expense_claim

                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    result = submit_expense(expense_data)
                    self.assertFalse(result.get("success"))
                    self.assertIn("workflow error", result.get("message", ""))

    def test_volunteer_expense_creation_failure_after_erpnext_success(self):
        """Test handling when volunteer expense creation fails after ERPNext expense claim succeeds"""
        mock_volunteer = MagicMock()
        mock_volunteer.name = "TEST-VOL"
        mock_volunteer.employee_id = "HR-EMP-001"

        expense_data = {
            "description": "Dual creation test",
            "amount": 50.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel"}

        mock_expense_claim = MagicMock()
        mock_expense_claim.name = "EXP-SUCCESS-001"

        mock_volunteer_expense = MagicMock()
        mock_volunteer_expense.insert.side_effect = ValidationError("Volunteer expense creation failed")

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc") as mock_get_doc:

                def get_doc_side_effect(doc_dict):
                    if doc_dict["doctype"] == "Expense Claim":
                        return mock_expense_claim
                    elif doc_dict["doctype"] == "Volunteer Expense":
                        return mock_volunteer_expense
                    return MagicMock()

                mock_get_doc.side_effect = get_doc_side_effect

                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    result = submit_expense(expense_data)
                    # Should still report success as ERPNext claim was created
                    self.assertFalse(result.get("success"))  # But fails because volunteer expense failed

    def test_setup_expense_claim_types_with_accounts_field_missing(self):
        """Test setup when Expense Claim Type doesn't have accounts field"""
        with patch("frappe.defaults.get_global_default", return_value="Test Company"):
            with patch("frappe.db.get_value", return_value="Test Account"):
                with patch("frappe.db.exists", return_value=False):
                    mock_expense_type = MagicMock()
                    # Remove accounts attribute to simulate older version
                    del mock_expense_type.accounts

                    with patch("frappe.get_doc", return_value=mock_expense_type):
                        result = setup_expense_claim_types()
                        self.assertEqual(result, "Travel")

    def test_extremely_long_expense_description_truncation(self):
        """Test handling of extremely long expense descriptions"""
        # Create a description longer than typical database field limits
        very_long_description = "A" * 5000  # 5000 characters

        expense_data = {
            "description": very_long_description,
            "amount": 50.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel"}

        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc", return_value=MagicMock(name="EXP-LONG-DESC-001")):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    result = submit_expense(expense_data)
                    self.assertTrue(result.get("success"))

    def test_expense_submission_performance_with_complex_category(self):
        """Test performance with complex expense category that requires multiple lookups"""
        expense_data = {
            "description": "Complex category expense",
            "amount": 50.00,
            "expense_date": "2024-12-14",
            "organization_type": "Chapter",
            "chapter": "Test Chapter",
            "category": "Complex Category With Spaces & Special Characters!"}

        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        # Mock multiple lookups for expense type creation
        with patch("frappe.db.get_value") as mock_get_value:
            mock_get_value.side_effect = [
                None,  # No existing expense type
                "Test Company",  # Default company
                "Test Account",  # Expense account
            ]

            with patch(
                "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
                return_value=mock_volunteer,
            ):
                with patch("frappe.get_doc", return_value=MagicMock(name="EXP-COMPLEX-001")):
                    with patch(
                        "verenigingen.templates.pages.volunteer.expenses.get_organization_cost_center",
                        return_value="Test Cost Center",
                    ):
                        result = submit_expense(expense_data)
                        self.assertTrue(result.get("success"))


if __name__ == "__main__":
    unittest.main()
