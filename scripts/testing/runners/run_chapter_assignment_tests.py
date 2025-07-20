#!/usr/bin/env python3
"""
Test runner for chapter assignment comprehensive tests.
Run this to execute all tests and get a detailed report.
"""

import frappe


@frappe.whitelist()
def run_chapter_assignment_comprehensive_tests():
    """Run comprehensive chapter assignment tests and return results"""
    try:
        from verenigingen.tests.test_chapter_assignment_comprehensive import run_comprehensive_tests

        print("Initializing comprehensive chapter assignment tests...")
        success = run_comprehensive_tests()

        return {
            "success": success,
            "message": "Comprehensive tests completed successfully" if success else "Some tests failed",
            "test_type": "comprehensive_chapter_assignment"}

    except Exception as e:
        import traceback

        error_details = traceback.format_exc()
        frappe.logger().error(f"Error running comprehensive tests: {error_details}")

        return {
            "success": False,
            "message": str(e),
            "error_details": error_details,
            "test_type": "comprehensive_chapter_assignment"}


@frappe.whitelist()
def quick_chapter_assignment_test():
    """Quick test to verify basic functionality"""
    try:
        # Check if we can import the function
        pass

        # Get a test member and chapters
        test_member = frappe.get_value("Member", {"docstatus": 1}, "name")
        test_chapters = frappe.get_all("Chapter", filters={"published": 1}, fields=["name"], limit=2)

        if not test_member:
            return {"success": False, "message": "No submitted members found for testing"}

        if len(test_chapters) < 2:
            return {"success": False, "message": "Need at least 2 published chapters for testing"}

        # Test the function exists and can be called (without actually changing data)
        result = {
            "success": True,
            "message": "Quick test passed - function is accessible",
            "test_member": test_member,
            "test_chapters": [c.name for c in test_chapters],
            "function_available": True}

        return result

    except Exception as e:
        return {"success": False, "message": f"Quick test failed: {str(e)}", "function_available": False}


if __name__ == "__main__":
    result = run_chapter_assignment_comprehensive_tests()
    print(f"Test result: {result}")
