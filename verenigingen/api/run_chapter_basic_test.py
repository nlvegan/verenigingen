"""Run basic chapter member tests"""

import frappe


@frappe.whitelist()
def run_test():
    """Run the basic chapter member test"""
    import unittest

    from verenigingen.tests.test_chapter_members_basic import TestChapterMemberBasic

    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestChapterMemberBasic)

    # Run tests
    result = unittest.TestResult()
    suite.run(result)

    # Format output
    output = []
    output.append(f"Tests run: {result.testsRun}")
    output.append(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    output.append(f"Failures: {len(result.failures)}")
    output.append(f"Errors: {len(result.errors)}")

    if result.failures:
        output.append("\nFAILURES:")
        for test, traceback in result.failures:
            output.append(f"\n{test}:\n{traceback}")

    if result.errors:
        output.append("\nERRORS:")
        for test, traceback in result.errors:
            output.append(f"\n{test}:\n{traceback}")

    # Rollback any changes
    frappe.db.rollback()

    return "\n".join(output)
