"""Runner for chapter members tests"""

import frappe
import unittest
from frappe.utils import cint

@frappe.whitelist()
def run_tests():
    """Run chapter members tests and return results"""
    
    try:
        # Import test module
        from verenigingen.tests.test_chapter_members_enhanced import TestChapterMemberEnhanced
        
        # Create test suite
        suite = unittest.TestLoader().loadTestsFromTestCase(TestChapterMemberEnhanced)
        
        # Run tests with custom result collector
        result = unittest.TestResult()
        suite.run(result)
        
        # Format results
        output = []
        output.append(f"Tests run: {result.testsRun}")
        output.append(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
        output.append(f"Failures: {len(result.failures)}")
        output.append(f"Errors: {len(result.errors)}")
        output.append("")
        
        if result.failures:
            output.append("FAILURES:")
            for test, traceback in result.failures:
                output.append(f"\n{test}:")
                output.append(traceback)
        
        if result.errors:
            output.append("\nERRORS:")
            for test, traceback in result.errors:
                output.append(f"\n{test}:")
                output.append(traceback)
        
        # Clean up any test data
        frappe.db.rollback()
        
        return "\n".join(output)
        
    except Exception as e:
        import traceback
        return f"Error running tests: {str(e)}\n\n{traceback.format_exc()}"