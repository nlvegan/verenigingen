#!/usr/bin/env python3
"""
Regression tests for volunteer expense validation to prevent chapter membership validation bugs
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today


class TestVolunteerExpenseValidationRegression(unittest.TestCase):
    """Regression tests specifically for the chapter membership validation bug"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        frappe.set_user("Administrator")

        # Create test member
        if not frappe.db.exists("Member", "TEST-MEMBER-REGRESSION"):
            cls.test_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "name": "TEST-MEMBER-REGRESSION",
                    "first_name": "Test",
                    "last_name": "Member",
                    "email": "test.member.regression@example.com",
                    "join_date": today(),
                }
            )
            cls.test_member.insert(ignore_permissions=True)
        else:
            cls.test_member = frappe.get_doc("Member", "TEST-MEMBER-REGRESSION")

        # Create test volunteer linked to member
        if not frappe.db.exists("Volunteer", "TEST-VOLUNTEER-REGRESSION"):
            cls.test_volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "name": "TEST-VOLUNTEER-REGRESSION",
                    "volunteer_name": "Test Volunteer Regression",
                    "email": "test.member.regression@example.com",
                    "member": cls.test_member.name,
                    "status": "Active",
                    "start_date": today(),
                }
            )
            cls.test_volunteer.insert(ignore_permissions=True)
        else:
            cls.test_volunteer = frappe.get_doc("Volunteer", "TEST-VOLUNTEER-REGRESSION")

        # Create test chapter
        if not frappe.db.exists("Chapter", "TEST-CHAPTER-REGRESSION"):
            cls.test_chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": "TEST-CHAPTER-REGRESSION",
                    "chapter_name": "Test Chapter Regression",
                }
            )
            cls.test_chapter.insert(ignore_permissions=True)
        else:
            cls.test_chapter = frappe.get_doc("Chapter", "TEST-CHAPTER-REGRESSION")

        # Create chapter membership
        f"{cls.test_chapter.name}-{cls.test_member.name}"
        if not frappe.db.exists(
            "Chapter Member", {"parent": cls.test_chapter.name, "member": cls.test_member.name}
        ):
            cls.test_chapter.append(
                "members",
                {
                    "member": cls.test_member.name,
                    "member_name": cls.test_volunteer.volunteer_name,
                    "enabled": 1,
                },
            )
            cls.test_chapter.save(ignore_permissions=True)

        # Create expense category
        if not frappe.db.exists("Expense Category", "TEST-CATEGORY-REGRESSION"):
            cls.test_category = frappe.get_doc(
                {
                    "doctype": "Expense Category",
                    "name": "TEST-CATEGORY-REGRESSION",
                    "category_name": "Test Category Regression",
                    "is_active": 1,
                }
            )
            cls.test_category.insert(ignore_permissions=True)

    def test_get_user_volunteer_record_includes_member_field(self):
        """Test that get_user_volunteer_record returns the member field - REGRESSION TEST"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        # Mock session user to test volunteer
        with patch("frappe.session.user", self.test_volunteer.email):
            volunteer_record = get_user_volunteer_record()

            # Critical regression test - ensure member field is included
            self.assertIsNotNone(
                volunteer_record, "get_user_volunteer_record should return a volunteer record"
            )
            self.assertTrue(
                hasattr(volunteer_record, "member"), "Volunteer record must include 'member' field"
            )
            self.assertIsNotNone(volunteer_record.member, "Member field should not be None")
            self.assertEqual(
                volunteer_record.member, self.test_member.name, "Member field should match expected member"
            )

            # Additional fields that should always be present
            self.assertTrue(hasattr(volunteer_record, "name"), "Volunteer record must include 'name' field")
            self.assertTrue(
                hasattr(volunteer_record, "volunteer_name"),
                "Volunteer record must include 'volunteer_name' field",
            )

    def test_get_user_volunteer_record_via_member_lookup(self):
        """Test volunteer lookup via member email includes member field"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        # Test the member-based lookup path
        with patch("frappe.session.user", self.test_member.email):
            volunteer_record = get_user_volunteer_record()

            self.assertIsNotNone(volunteer_record, "Should find volunteer via member email")
            self.assertTrue(
                hasattr(volunteer_record, "member"), "Member field must be included in member-based lookup"
            )
            self.assertEqual(volunteer_record.member, self.test_member.name, "Member field should be correct")

    def test_chapter_membership_validation_with_valid_member(self):
        """Test that chapter membership validation passes when volunteer has valid membership"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Test expense for regression testing",
            "amount": 25.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter.name,
            "category": self.test_category.name,
            "notes": "Regression test for chapter membership validation",
        }

        # Mock session user and test submission
        with patch("frappe.session.user", self.test_volunteer.email):
            result = submit_expense(expense_data)

            # Should succeed because volunteer has chapter membership
            self.assertTrue(
                result.get("success"), f"Expense submission should succeed. Error: {result.get('message')}"
            )
            self.assertIn(
                "successfully", result.get("message", "").lower(), "Success message should indicate success"
            )

    def test_chapter_membership_validation_without_member_field_fails(self):
        """Test that missing member field causes validation to fail - REGRESSION TEST"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Create a volunteer record without member field (simulating the bug)
        mock_volunteer_without_member = frappe._dict(
            {
                "name": self.test_volunteer.name,
                "volunteer_name": self.test_volunteer.volunteer_name,
                # Intentionally missing 'member' field to simulate the bug
            }
        )

        expense_data = {
            "description": "Test expense for regression testing",
            "amount": 25.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter.name,
            "category": self.test_category.name,
            "notes": "Regression test for chapter membership validation failure",
        }

        # Mock get_user_volunteer_record to return volunteer without member field
        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer_without_member,
        ):
            with patch("frappe.session.user", self.test_volunteer.email):
                result = submit_expense(expense_data)

                # Should fail because volunteer record lacks member field
                self.assertFalse(
                    result.get("success"), "Expense submission should fail when member field is missing"
                )
                self.assertIn(
                    "membership required",
                    result.get("message", "").lower(),
                    "Error should mention membership requirement",
                )

    def test_volunteer_record_field_completeness(self):
        """Test that volunteer records returned by lookup functions have all required fields"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        with patch("frappe.session.user", self.test_volunteer.email):
            volunteer_record = get_user_volunteer_record()

            # Required fields for expense validation
            required_fields = ["name", "volunteer_name", "member"]

            for field in required_fields:
                self.assertTrue(
                    hasattr(volunteer_record, field), f"Volunteer record must include '{field}' field"
                )

                if field == "member":
                    # Member field should not be None for volunteers with member links
                    self.assertIsNotNone(
                        getattr(volunteer_record, field),
                        f"'{field}' field should not be None for linked volunteers",
                    )

    def test_chapter_membership_query_correctness(self):
        """Test that chapter membership queries use correct field relationships"""
        # Direct test of the query logic used in validation

        # Test the corrected query (using member field)
        correct_result = frappe.db.exists(
            "Chapter Member", {"parent": self.test_chapter.name, "member": self.test_member.name}
        )
        self.assertTrue(correct_result, "Chapter membership query should find existing membership")

        # Test the incorrect query (using volunteer field - this should not work)
        incorrect_result = frappe.db.exists(
            "Chapter Member",
            {
                "parent": self.test_chapter.name,
                "volunteer": self.test_volunteer.name,  # This field doesn't exist in Chapter Member
            },
        )
        self.assertFalse(
            incorrect_result, "Incorrect query using 'volunteer' field should not find membership"
        )

    def test_expense_submission_flow_integration(self):
        """Integration test for the complete expense submission flow"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record, submit_expense

        # Step 1: Verify volunteer lookup works correctly
        with patch("frappe.session.user", self.test_volunteer.email):
            volunteer_record = get_user_volunteer_record()
            self.assertIsNotNone(volunteer_record.member, "Volunteer lookup must return member field")

        # Step 2: Verify expense submission uses the correct volunteer data
        expense_data = {
            "description": "Integration test expense",
            "amount": 15.75,
            "expense_date": add_days(today(), -1),
            "organization_type": "Chapter",
            "chapter": self.test_chapter.name,
            "category": self.test_category.name,
            "notes": "Full integration test",
        }

        with patch("frappe.session.user", self.test_volunteer.email):
            result = submit_expense(expense_data)

            self.assertTrue(
                result.get("success"), f"Integration test should succeed. Error: {result.get('message')}"
            )

            # Verify expense claim was created
            if result.get("expense_claim_name"):
                expense_claim = frappe.get_doc("Expense Claim", result.get("expense_claim_name"))
                self.assertEqual(expense_claim.status, "Draft", "Expense claim should be in Draft status")

    def test_multiple_chapter_memberships(self):
        """Test validation works correctly when volunteer has multiple chapter memberships"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Create second test chapter
        if not frappe.db.exists("Chapter", "TEST-CHAPTER-2-REGRESSION"):
            test_chapter_2 = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": "TEST-CHAPTER-2-REGRESSION",
                    "chapter_name": "Test Chapter 2 Regression",
                }
            )
            test_chapter_2.insert(ignore_permissions=True)

            # Add member to second chapter
            test_chapter_2.append(
                "members",
                {
                    "member": self.test_member.name,
                    "member_name": self.test_volunteer.volunteer_name,
                    "enabled": 1,
                },
            )
            test_chapter_2.save(ignore_permissions=True)

        # Test expense submission to second chapter
        expense_data = {
            "description": "Multi-chapter test expense",
            "amount": 30.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": "TEST-CHAPTER-2-REGRESSION",
            "category": self.test_category.name,
            "notes": "Testing multiple chapter memberships",
        }

        with patch("frappe.session.user", self.test_volunteer.email):
            result = submit_expense(expense_data)

            self.assertTrue(result.get("success"), "Should succeed for second chapter membership")

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        try:
            # Clean up in reverse order due to dependencies
            frappe.db.delete("Expense Claim", {"employee": cls.test_volunteer.employee_id}) if hasattr(
                cls.test_volunteer, "employee_id"
            ) else None
            frappe.db.delete("Volunteer Expense", {"volunteer": cls.test_volunteer.name})
            frappe.db.delete(
                "Chapter Member", {"parent": cls.test_chapter.name, "member": cls.test_member.name}
            )

            for chapter_name in ["TEST-CHAPTER-REGRESSION", "TEST-CHAPTER-2-REGRESSION"]:
                if frappe.db.exists("Chapter", chapter_name):
                    frappe.delete_doc("Chapter", chapter_name, ignore_permissions=True)

            if frappe.db.exists("Expense Category", "TEST-CATEGORY-REGRESSION"):
                frappe.delete_doc("Expense Category", "TEST-CATEGORY-REGRESSION", ignore_permissions=True)

            if frappe.db.exists("Volunteer", "TEST-VOLUNTEER-REGRESSION"):
                frappe.delete_doc("Volunteer", "TEST-VOLUNTEER-REGRESSION", ignore_permissions=True)

            if frappe.db.exists("Member", "TEST-MEMBER-REGRESSION"):
                frappe.delete_doc("Member", "TEST-MEMBER-REGRESSION", ignore_permissions=True)

            frappe.db.commit()
        except Exception as e:
            frappe.logger().error(f"Error cleaning up test data: {str(e)}")


if __name__ == "__main__":
    unittest.main()
