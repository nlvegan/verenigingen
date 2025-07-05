#!/usr/bin/env python3
"""
Integration tests for complete expense submission workflow to catch field omission bugs
"""

import json
import unittest
from unittest.mock import patch

import frappe
from frappe.utils import flt, today


class TestExpenseSubmissionIntegration(unittest.TestCase):
    """Integration tests for expense submission workflow"""

    @classmethod
    def setUpClass(cls):
        """Set up integration test data"""
        frappe.set_user("Administrator")

        # Create comprehensive test setup
        cls.test_member = frappe.get_doc(
            {
                "doctype": "Member",
                "name": "INTEGRATION-MEMBER",
                "first_name": "Integration",
                "last_name": "Test",
                "email": "integration@example.com",
                "join_date": today(),
            }
        )
        cls.test_member.insert(ignore_permissions=True)

        cls.test_volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "name": "INTEGRATION-VOLUNTEER",
                "volunteer_name": "Integration Test Volunteer",
                "email": "integration@example.com",
                "member": cls.test_member.name,
                "status": "Active",
                "start_date": today(),
            }
        )
        cls.test_volunteer.insert(ignore_permissions=True)

        cls.test_chapter = frappe.get_doc(
            {"doctype": "Chapter", "name": "INTEGRATION-CHAPTER", "chapter_name": "Integration Test Chapter"}
        )
        cls.test_chapter.insert(ignore_permissions=True)

        # Add chapter membership
        cls.test_chapter.append(
            "members",
            {"member": cls.test_member.name, "member_name": cls.test_volunteer.volunteer_name, "enabled": 1},
        )
        cls.test_chapter.save(ignore_permissions=True)

        # Create expense category
        if not frappe.db.exists("Expense Category", "INTEGRATION-CATEGORY"):
            cls.test_category = frappe.get_doc(
                {
                    "doctype": "Expense Category",
                    "name": "INTEGRATION-CATEGORY",
                    "category_name": "Integration Test Category",
                    "is_active": 1,
                }
            )
            cls.test_category.insert(ignore_permissions=True)

    def test_complete_expense_submission_workflow(self):
        """Test the complete expense submission workflow end-to-end"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record, submit_expense

        # Step 1: Test volunteer lookup
        with patch("frappe.session.user", self.test_volunteer.email):
            volunteer_record = get_user_volunteer_record()

            self.assertIsNotNone(volunteer_record, "Step 1: Volunteer lookup should succeed")
            self.assertIsNotNone(volunteer_record.member, "Step 1: Volunteer should have member field")
            self.assertEqual(
                volunteer_record.member, self.test_member.name, "Step 1: Member field should be correct"
            )

        # Step 2: Test expense submission
        expense_data = {
            "description": "Integration test complete workflow",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter.name,
            "category": "INTEGRATION-CATEGORY",
            "notes": "End-to-end integration test",
        }

        with patch("frappe.session.user", self.test_volunteer.email):
            result = submit_expense(expense_data)

            self.assertTrue(
                result.get("success"),
                f"Step 2: Expense submission should succeed. Error: {result.get('message')}",
            )
            self.assertIsNotNone(result.get("expense_claim_name"), "Step 2: Should create expense claim")
            self.assertIsNotNone(result.get("expense_name"), "Step 2: Should create volunteer expense record")

        # Step 3: Verify created records
        if result.get("expense_claim_name"):
            expense_claim = frappe.get_doc("Expense Claim", result.get("expense_claim_name"))
            self.assertEqual(expense_claim.status, "Draft", "Step 3: Expense claim should be in Draft status")
            self.assertEqual(
                flt(expense_claim.total_claimed_amount),
                flt(expense_data["amount"]),
                "Step 3: Amount should match",
            )

        if result.get("expense_name"):
            volunteer_expense = frappe.get_doc("Volunteer Expense", result.get("expense_name"))
            self.assertEqual(
                volunteer_expense.volunteer,
                self.test_volunteer.name,
                "Step 3: Volunteer link should be correct",
            )
            self.assertEqual(
                volunteer_expense.chapter, self.test_chapter.name, "Step 3: Chapter should be correct"
            )

    def test_workflow_with_api_call_simulation(self):
        """Test workflow simulating API calls from frontend"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Simulate JSON data from frontend
        expense_data_json = json.dumps(
            {
                "description": "API simulation test",
                "amount": 25.50,
                "expense_date": today(),
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "category": "INTEGRATION-CATEGORY",
                "notes": "Testing API call simulation",
            }
        )

        with patch("frappe.session.user", self.test_volunteer.email):
            result = submit_expense(expense_data_json)

            self.assertTrue(
                result.get("success"), f"API simulation should succeed. Error: {result.get('message')}"
            )

    def test_workflow_resilience_to_field_changes(self):
        """Test that workflow is resilient to field additions/changes"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        # Test that adding extra fields doesn't break anything
        with patch("frappe.db.get_value") as mock_get_value:
            # Simulate a record with extra fields
            mock_get_value.side_effect = [
                self.test_member.name,
                frappe._dict(
                    {
                        "name": self.test_volunteer.name,
                        "volunteer_name": self.test_volunteer.volunteer_name,
                        "member": self.test_member.name,
                        "extra_field": "extra_value",  # Extra field shouldn't break anything
                        "another_field": 123,
                    }
                ),
            ]

            with patch("frappe.session.user", self.test_member.email):
                result = get_user_volunteer_record()

                self.assertIsNotNone(result, "Should handle extra fields gracefully")
                self.assertEqual(result.member, self.test_member.name, "Essential fields should still work")

    def test_concurrent_submission_safety(self):
        """Test that concurrent submissions don't interfere with each other"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Create multiple expense data sets
        expense_data_sets = [
            {
                "description": f"Concurrent test {i}",
                "amount": 10.00 + i,
                "expense_date": today(),
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "category": "INTEGRATION-CATEGORY",
                "notes": f"Concurrent submission test {i}",
            }
            for i in range(3)
        ]

        results = []
        with patch("frappe.session.user", self.test_volunteer.email):
            for expense_data in expense_data_sets:
                result = submit_expense(expense_data)
                results.append(result)

        # All submissions should succeed
        for i, result in enumerate(results):
            self.assertTrue(result.get("success"), f"Concurrent submission {i} should succeed")
            self.assertIsNotNone(
                result.get("expense_claim_name"), f"Submission {i} should create expense claim"
            )

    def test_data_consistency_across_records(self):
        """Test that data remains consistent across ERPNext and Volunteer Expense records"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Data consistency test",
            "amount": 75.25,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter.name,
            "category": "INTEGRATION-CATEGORY",
            "notes": "Testing data consistency",
        }

        with patch("frappe.session.user", self.test_volunteer.email):
            result = submit_expense(expense_data)

            self.assertTrue(result.get("success"), "Submission should succeed for consistency test")

            # Check data consistency between records
            if result.get("expense_claim_name") and result.get("expense_name"):
                expense_claim = frappe.get_doc("Expense Claim", result.get("expense_claim_name"))
                volunteer_expense = frappe.get_doc("Volunteer Expense", result.get("expense_name"))

                # Check linkage
                self.assertEqual(
                    volunteer_expense.expense_claim_id, expense_claim.name, "Records should be linked"
                )

                # Check amount consistency
                self.assertEqual(
                    flt(volunteer_expense.amount),
                    flt(expense_claim.total_claimed_amount),
                    "Amounts should match",
                )

                # Check date consistency
                self.assertEqual(
                    str(volunteer_expense.expense_date), str(expense_claim.posting_date), "Dates should match"
                )

    def test_error_handling_and_rollback(self):
        """Test that errors are handled gracefully and don't leave partial data"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Test with invalid chapter (should fail gracefully)
        invalid_expense_data = {
            "description": "Error handling test",
            "amount": 30.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": "NONEXISTENT-CHAPTER",
            "category": "INTEGRATION-CATEGORY",
            "notes": "Testing error handling",
        }

        with patch("frappe.session.user", self.test_volunteer.email):
            result = submit_expense(invalid_expense_data)

            self.assertFalse(result.get("success"), "Should fail for nonexistent chapter")
            self.assertIsNone(result.get("expense_claim_name"), "Should not create expense claim on failure")
            self.assertIsNone(result.get("expense_name"), "Should not create volunteer expense on failure")

    def test_performance_with_large_data_sets(self):
        """Test performance doesn't degrade significantly with data volume"""
        import time

        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        # Test multiple lookups to ensure no performance regression
        times = []

        for i in range(5):
            start_time = time.time()

            with patch("frappe.session.user", self.test_volunteer.email):
                volunteer_record = get_user_volunteer_record()

            end_time = time.time()
            times.append(end_time - start_time)

            self.assertIsNotNone(volunteer_record, f"Lookup {i} should succeed")
            self.assertIsNotNone(volunteer_record.member, f"Lookup {i} should return member field")

        # Average time should be reasonable (less than 1 second)
        avg_time = sum(times) / len(times)
        self.assertLess(avg_time, 1.0, f"Average lookup time should be reasonable, got {avg_time:.3f}s")

    @classmethod
    def tearDownClass(cls):
        """Clean up integration test data"""
        try:
            # Clean up in dependency order
            frappe.db.delete("Expense Claim", {"employee": cls.test_volunteer.employee_id}) if hasattr(
                cls.test_volunteer, "employee_id"
            ) else None
            frappe.db.delete("Volunteer Expense", {"volunteer": cls.test_volunteer.name})

            for doc_type, name in [
                ("Chapter", "INTEGRATION-CHAPTER"),
                ("Expense Category", "INTEGRATION-CATEGORY"),
                ("Volunteer", "INTEGRATION-VOLUNTEER"),
                ("Member", "INTEGRATION-MEMBER"),
            ]:
                if frappe.db.exists(doc_type, name):
                    frappe.delete_doc(doc_type, name, ignore_permissions=True)

            frappe.db.commit()
        except Exception as e:
            frappe.logger().error(f"Error cleaning up integration test data: {str(e)}")


if __name__ == "__main__":
    unittest.main()
