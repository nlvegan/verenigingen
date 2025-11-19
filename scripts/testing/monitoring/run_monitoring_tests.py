#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Bench-compatible runner for monitoring system tests
"""

import frappe

@frappe.whitelist()
def run_monitoring_tests():
    """Run comprehensive monitoring system tests"""
    from verenigingen.scripts.testing.monitoring.test_monitoring_system import run_comprehensive_monitoring_tests
    
    # Set up test environment
    frappe.set_user("Administrator")
    
    # Run tests
    results = run_comprehensive_monitoring_tests()
    
    return results

if __name__ == "__main__":
    print("This script should be run via bench execute")
    print("Usage: bench --site dev.veganisme.net execute verenigingen.scripts.testing.monitoring.run_monitoring_tests.run_monitoring_tests")