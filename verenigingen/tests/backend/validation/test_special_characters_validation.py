"""
Test cases for special character handling in membership applications
"""

import unittest

import frappe


class TestSpecialCharactersValidation(unittest.TestCase):
    """Test special character validation in membership applications"""

    def setUp(self):
        """Set up test environment"""

    def test_validate_name_with_accented_characters(self):
        """Test name validation with accented characters"""
        from verenigingen.utils.validation.application_validators import validate_name

        # Test cases with accented characters
        test_names = ["José", "García", "François", "Müller", "Björn"]

        for name in test_names:
            with self.subTest(name=name):
                result = validate_name(name, "Test Name")
                self.assertTrue(result["valid"], f"Name '{name}' should be valid")
                self.assertIn("sanitized", result, f"Name '{name}' should include sanitized version")

    def test_validate_name_with_hyphens_and_apostrophes(self):
        """Test name validation with hyphens and apostrophes"""
        from verenigingen.utils.validation.application_validators import validate_name

        # Test cases with hyphens and apostrophes
        test_names = ["Anne-Marie", "O'Connor", "Van der Berg", "D'Angelo"]

        for name in test_names:
            with self.subTest(name=name):
                result = validate_name(name, "Test Name")
                self.assertTrue(result["valid"], f"Name '{name}' should be valid")
                self.assertIn("sanitized", result, f"Name '{name}' should include sanitized version")

    def test_validate_name_with_invalid_characters(self):
        """Test name validation rejects invalid characters"""
        from verenigingen.utils.validation.application_validators import validate_name

        # Test cases with invalid characters
        invalid_names = ["<script>", "javascript:", "test@email", "name&symbol", "user<tag>"]

        for name in invalid_names:
            with self.subTest(name=name):
                result = validate_name(name, "Test Name")
                self.assertFalse(result["valid"], f"Name '{name}' should be invalid")

    def test_validate_name_sanitization(self):
        """Test that names are properly sanitized"""
        from verenigingen.utils.validation.application_validators import validate_name

        # Test case with extra whitespace
        result = validate_name("  José García  ", "Test Name")
        self.assertTrue(result["valid"])
        self.assertEqual(result["sanitized"], "José García", "Name should be stripped of extra whitespace")

    def test_create_member_with_special_characters(self):
        """Test member creation with special characters in names"""
        from verenigingen.utils.application_helpers import (
            create_member_from_application,
            generate_application_id,
        )

        # Test data with special characters
        data = {
            "first_name": "José",
            "last_name": "García-López",
            "email": "jose.garcia.test@example.com",
            "birth_date": "1990-01-01",
        }

        application_id = generate_application_id()

        try:
            # This should not raise an exception
            member = create_member_from_application(data, application_id)
            self.assertIsNotNone(member)
            self.assertEqual(member.first_name, "José")
            self.assertEqual(member.last_name, "García-López")

            # Clean up - rollback the transaction to avoid creating test data
            frappe.db.rollback()

        except Exception as e:
            self.fail(f"Member creation with special characters failed: {str(e)}")


def run_tests():
    """Run the special character validation tests"""
    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSpecialCharactersValidation)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


@frappe.whitelist()
def test_special_character_validation():
    """Whitelisted function to test special character validation"""
    try:
        from verenigingen.utils.validation.application_validators import validate_name

        test_cases = [
            {"name": "José", "should_pass": True},
            {"name": "García-López", "should_pass": True},
            {"name": "O'Connor", "should_pass": True},
            {"name": "Anne-Marie", "should_pass": True},
            {"name": "Müller", "should_pass": True},
            {"name": "<script>alert('test')</script>", "should_pass": False},
            {"name": "javascript:void(0)", "should_pass": False},
        ]

        results = []

        for case in test_cases:
            result = validate_name(case["name"], "Test Name")
            passed = result["valid"] == case["should_pass"]

            results.append(
                {
                    "name": case["name"],
                    "expected": case["should_pass"],
                    "actual": result["valid"],
                    "passed": passed,
                    "sanitized": result.get("sanitized", ""),
                    "message": result.get("message", ""),
                }
            )

        # Summary
        total_tests = len(results)
        passed_tests = sum(1 for r in results if r["passed"])

        return {
            "success": True,
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": total_tests - passed_tests,
            "results": results,
            "message": f"Special character validation tests: {passed_tests}/{total_tests} passed",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": f"Test execution failed: {str(e)}"}


if __name__ == "__main__":
    run_tests()
