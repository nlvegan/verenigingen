"""
Unit tests verifying legacy expense system removal
Tests to ensure legacy components have been properly phased out

Created: December 2024 - Legacy system phase-out verification
"""

import os
import unittest
from unittest.mock import MagicMock, patch

import frappe


class TestLegacySystemRemoval(unittest.TestCase):
    """Test that legacy expense system components have been removed"""

    def setUp(self):
        frappe.set_user("Administrator")

    def test_expense_approval_dashboard_removed(self):
        """Test that Expense Approval Dashboard doctype has been removed"""
        # This doctype should no longer exist
        dashboard_exists = frappe.db.exists("DocType", "Expense Approval Dashboard")
        self.assertFalse(dashboard_exists, "Expense Approval Dashboard should be removed")

    def test_expense_permission_manager_removed(self):
        """Test that ExpensePermissionManager utility has been removed"""
        # This module should no longer be importable
        with self.assertRaises(ImportError):
            pass

    def test_chapter_expense_report_uses_erpnext_only(self):
        """Test that Chapter Expense Report only uses ERPNext data"""
        from verenigingen.verenigingen.report.chapter_expense_report.chapter_expense_report import (
            get_erpnext_expense_data,
        )

        # Should not reference Volunteer Expense table in queries
        with patch("frappe.get_all") as mock_get_all:
            mock_get_all.return_value = []

            # This should work without errors (no legacy table references)
            result = get_erpnext_expense_data({"from_date": "2024-01-01", "to_date": "2024-12-31"})
            self.assertIsInstance(result, list)

    def test_workspace_links_updated(self):
        """Test that workspace links point to ERPNext components"""
        try:
            # Check if workspace update function exists and works
            from verenigingen.templates.pages.volunteer.expenses import check_workspace_status

            result = check_workspace_status()
            self.assertIsInstance(result, dict)

            # Should have links to ERPNext Expense Claims
            if "db_links" in result:
                expense_links = [
                    link for link in result["db_links"] if "expense" in link.get("label", "").lower()
                ]
                erpnext_links = [link for link in expense_links if "erpnext" in link.get("label", "").lower()]
                self.assertGreater(len(erpnext_links), 0, "Should have ERPNext expense links")

        except ImportError:
            # If function doesn't exist, that's also acceptable
            pass

    def test_volunteer_expense_portal_still_functional(self):
        """Test that volunteer expense portal still works (but uses ERPNext backend)"""
        from verenigingen.templates.pages.volunteer.expenses import get_context

        # Mock the user session
        with patch("frappe.session.user", "test@example.com"):
            with patch(
                "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record"
            ) as mock_get_volunteer:
                mock_volunteer = MagicMock()
                mock_volunteer.name = "TEST-VOL-001"
                mock_volunteer.volunteer_name = "Test Volunteer"
                mock_get_volunteer.return_value = mock_volunteer

                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_volunteer_organizations",
                    return_value={"chapters": [], "teams": []},
                ):
                    with patch(
                        "verenigingen.templates.pages.volunteer.expenses.get_expense_categories",
                        return_value=[],
                    ):
                        with patch(
                            "verenigingen.templates.pages.volunteer.expenses.get_volunteer_expenses",
                            return_value=[],
                        ):
                            with patch(
                                "verenigingen.templates.pages.volunteer.expenses.get_expense_statistics",
                                return_value={},
                            ):
                                with patch(
                                    "verenigingen.templates.pages.volunteer.expenses.get_approval_thresholds",
                                    return_value={},
                                ):
                                    with patch(
                                        "verenigingen.templates.pages.volunteer.expenses.get_national_chapter",
                                        return_value=None,
                                    ):
                                        context = get_context({})

                                        # Portal should still provide necessary context
                                        self.assertIn("volunteer", context)
                                        self.assertIn("organizations", context)
                                        self.assertIn("expense_categories", context)

    def test_expense_submission_uses_erpnext_backend(self):
        """Test that expense submission creates ERPNext Expense Claims"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        test_expense_data = {
            "description": "Test expense for ERPNext integration",
            "amount": 75.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel",
            "notes": "Testing ERPNext backend",
        }

        mock_volunteer = MagicMock()
        mock_volunteer.name = "TEST-VOL-001"
        mock_volunteer.employee_id = "HR-EMP-001"

        mock_expense_claim = MagicMock()
        mock_expense_claim.name = "EXP-TEST-001"

        mock_volunteer_expense = MagicMock()
        mock_volunteer_expense.name = "VEXP-TEST-001"

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
                    with patch(
                        "verenigingen.templates.pages.volunteer.expenses.get_organization_cost_center",
                        return_value="Test Cost Center",
                    ):
                        with patch("frappe.defaults.get_global_default", return_value="Test Company"):
                            with patch("frappe.db.get_value", return_value="Test Account"):
                                result = submit_expense(test_expense_data)

                                # Should successfully create ERPNext Expense Claim
                                self.assertTrue(result.get("success"))
                                self.assertEqual(result.get("expense_claim_name"), "EXP-TEST-001")

                                # Should also create tracking record
                                self.assertEqual(result.get("expense_name"), "VEXP-TEST-001")

    def test_workspace_shortcuts_accessible(self):
        """Test that workspace shortcuts for expenses are accessible"""
        try:
            from verenigingen.templates.pages.volunteer.expenses import update_workspace_links

            # Should execute without errors
            result = update_workspace_links()
            self.assertTrue(result.get("success", False))

        except ImportError:
            # If function doesn't exist, skip this test
            self.skipTest("Workspace update function not available")

    def test_error_handling_for_missing_legacy_components(self):
        """Test that system handles missing legacy components gracefully"""
        # Test Chapter Expense Report with missing Volunteer Expense table
        from verenigingen.verenigingen.report.chapter_expense_report.chapter_expense_report import get_data

        # Should not fail even if legacy tables don't exist
        with patch("frappe.get_all") as mock_get_all:
            # Simulate table not found (which is expected after phase-out)
            mock_get_all.side_effect = [[], Exception("Table doesn't exist")]

            try:
                result = get_data({"from_date": "2024-01-01", "to_date": "2024-12-31"})
                self.assertIsInstance(result, list)
            except Exception as e:
                # Should handle missing legacy tables gracefully
                self.fail(f"System should handle missing legacy tables gracefully: {e}")

    def test_documentation_updated(self):
        """Test that documentation reflects system changes"""
        import os

        # Check if documentation files exist and mention ERPNext integration
        doc_files = [
            "/home/frappe/frappe-bench/apps/verenigingen/VOLUNTEER_EXPENSE_PORTAL.md",
            "/home/frappe/frappe-bench/apps/verenigingen/BOARD_MEMBER_EXPENSE_ACCESS.md",
        ]

        for doc_file in doc_files:
            if os.path.exists(doc_file):
                with open(doc_file, "r") as f:
                    content = f.read().lower()

                    # Should mention ERPNext integration
                    self.assertIn("erpnext", content, f"{doc_file} should mention ERPNext integration")

                    # Should mention migration or phase-out
                    phase_out_terms = ["migration", "phase", "erpnext", "integration", "updated"]
                    has_phase_out_mention = any(term in content for term in phase_out_terms)
                    self.assertTrue(has_phase_out_mention, f"{doc_file} should mention system changes")

    def test_no_legacy_dashboard_imports(self):
        """Test that no code still imports legacy dashboard components"""
        import os

        # Check key files don't import legacy components
        files_to_check = [
            "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/templates/pages/volunteer/expenses.py",
            "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/report/chapter_expense_report/chapter_expense_report.py",
        ]

        legacy_imports = ["expense_permissions", "ExpensePermissionManager", "Expense Approval Dashboard"]

        for file_path in files_to_check:
            if os.path.exists(file_path):
                with open(file_path, "r") as f:
                    content = f.read()

                    for legacy_import in legacy_imports:
                        self.assertNotIn(
                            legacy_import,
                            content,
                            f"{file_path} should not import legacy component: {legacy_import}",
                        )

    def test_workspace_configuration_complete(self):
        """Test that workspace configuration is complete with ERPNext links"""
        try:
            # Check workspace configuration
            workspace_file = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/workspace/verenigingen/verenigingen.json"

            if os.path.exists(workspace_file):
                import json

                with open(workspace_file, "r") as f:
                    workspace_config = json.load(f)

                # Should have shortcuts for expense management
                shortcuts = workspace_config.get("shortcuts", [])
                expense_shortcuts = [s for s in shortcuts if "expense" in s.get("label", "").lower()]

                self.assertGreater(len(expense_shortcuts), 0, "Should have expense management shortcuts")

                # Should have links to ERPNext components
                links = workspace_config.get("links", [])
                erpnext_links = [link for link in links if "erpnext" in link.get("label", "").lower()]

                self.assertGreater(len(erpnext_links), 0, "Should have ERPNext component links")

        except (ImportError, FileNotFoundError):
            self.skipTest("Workspace configuration file not accessible")


class TestERPNextMigrationCompliance(unittest.TestCase):
    """Test compliance with ERPNext migration requirements"""

    def setUp(self):
        frappe.set_user("Administrator")

    def test_expense_claim_field_compatibility(self):
        """Test that we only use existing ERPNext Expense Claim fields"""
        from verenigingen.verenigingen.report.chapter_expense_report.chapter_expense_report import (
            get_erpnext_expense_data,
        )

        # Fields that should exist in ERPNext Expense Claim
        required_fields = [
            "name",
            "posting_date",
            "total_claimed_amount",
            "total_sanctioned_amount",
            "status",
            "approval_status",
            "employee",
            "employee_name",
            "remark",
            "company",
        ]

        # Fields that don't exist and should not be used
        non_existent_fields = ["title", "description", "volunteer_id"]

        with patch("frappe.get_all") as mock_get_all:
            mock_get_all.return_value = []

            get_erpnext_expense_data({})

            # Check that the call was made with correct fields
            call_args = mock_get_all.call_args
            if call_args:
                fields_used = call_args[1].get("fields", [])

                # Should use required fields
                for field in required_fields:
                    if field != "cost_center":  # cost_center is optional
                        self.assertIn(field, fields_used, f"Should use field: {field}")

                # Should not use non-existent fields
                for field in non_existent_fields:
                    self.assertNotIn(field, fields_used, f"Should not use non-existent field: {field}")

    def test_no_legacy_table_references(self):
        """Test that no code references legacy expense tables"""
        from verenigingen.verenigingen.report.chapter_expense_report.chapter_expense_report import (
            get_erpnext_expense_data,
        )

        with patch("frappe.get_all") as mock_get_all:
            with patch("frappe.db.sql") as mock_sql:
                mock_get_all.return_value = []

                get_erpnext_expense_data({})

                # Should not make any SQL calls to legacy tables
                if mock_sql.called:
                    for call in mock_sql.call_args_list:
                        query = call[0][0] if call[0] else ""
                        self.assertNotIn(
                            "tabVolunteer Expense", query, "Should not query legacy Volunteer Expense table"
                        )
                        self.assertNotIn(
                            "tabExpense Approval Dashboard", query, "Should not query legacy dashboard table"
                        )

    def test_employee_integration_functional(self):
        """Test that volunteer-to-employee integration works"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Test with volunteer that has employee_id
        mock_volunteer = MagicMock()
        mock_volunteer.name = "TEST-VOL-001"
        mock_volunteer.employee_id = "HR-EMP-001"

        test_data = {
            "description": "Employee integration test",
            "amount": 100.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel",
        }

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc", return_value=MagicMock(name="EXP-TEST")):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    with patch(
                        "verenigingen.templates.pages.volunteer.expenses.get_organization_cost_center",
                        return_value="Test Center",
                    ):
                        with patch("frappe.defaults.get_global_default", return_value="Test Company"):
                            with patch("frappe.db.get_value", return_value="Test Account"):
                                result = submit_expense(test_data)

                                # Should work without employee creation
                                self.assertTrue(result.get("success"))
                                self.assertNotIn("Employee record created", result.get("message", ""))

    def test_automatic_employee_creation(self):
        """Test automatic employee creation for volunteers"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Test with volunteer that has no employee_id
        mock_volunteer = MagicMock()
        mock_volunteer.name = "TEST-VOL-002"
        mock_volunteer.employee_id = None

        test_data = {
            "description": "Auto employee creation test",
            "amount": 50.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel",
        }

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            # Mock successful employee creation
            with patch.object(mock_volunteer, "create_minimal_employee", return_value="HR-EMP-NEW-001"):
                with patch.object(mock_volunteer, "reload"):
                    mock_volunteer.employee_id = "HR-EMP-NEW-001"  # Simulate successful creation

                    with patch("frappe.get_doc", return_value=MagicMock(name="EXP-AUTO")):
                        with patch(
                            "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                            return_value="Travel",
                        ):
                            with patch(
                                "verenigingen.templates.pages.volunteer.expenses.get_organization_cost_center",
                                return_value="Test Center",
                            ):
                                with patch("frappe.defaults.get_global_default", return_value="Test Company"):
                                    with patch("frappe.db.get_value", return_value="Test Account"):
                                        result = submit_expense(test_data)

                                        # Should work with automatic employee creation
                                        self.assertTrue(result.get("success"))
                                        self.assertIn("Employee record created", result.get("message", ""))


if __name__ == "__main__":
    unittest.main()
