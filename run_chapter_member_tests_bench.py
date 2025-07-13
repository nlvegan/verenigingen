"""Runner for chapter member tests using bench"""

import frappe


@frappe.whitelist()
def run_tests():
    """Run the chapter member tests"""
    import unittest

    from verenigingen.tests.test_chapter_members_enhanced import TestChapterMemberEnhanced

    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestChapterMemberEnhanced)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return f"Tests run: {result.testsRun}, Failures: {len(result.failures)}, Errors: {len(result.errors)}"


if __name__ == "__main__":
    # This should be run via bench execute
    print("Use bench --site dev.veganisme.net execute run_chapter_member_tests_bench.run_tests")
