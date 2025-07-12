#!/usr/bin/env python3
"""Test runner for member status transitions tests"""

import os
import sys
import unittest

import frappe

# Add the app path to sys.path
app_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_path)


def run_tests():
    """Run the member status transitions tests"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    # Set as Administrator
    frappe.set_user("Administrator")

    # Import the test module
    from verenigingen.tests.test_member_status_transitions_enhanced import TestMemberStatusTransitionsEnhanced

    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMemberStatusTransitionsEnhanced)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Clean up
    frappe.db.rollback()
    frappe.destroy()

    # Return exit code based on results
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    exit_code = run_tests()
    sys.exit(exit_code)
