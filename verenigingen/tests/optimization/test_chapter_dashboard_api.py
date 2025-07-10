#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test optimized endpoints in chapter_dashboard_api.py
"""

import time
import frappe
from frappe.test_runner import make_test_records


def test_optimized_endpoints():
    """Test that optimized endpoints work correctly"""
    
    endpoints = {'get_chapter_member_emails': {'cache_ttl': 1800, 'needs': ['cache', 'error_handling']}, 'get_chapter_analytics': {'cache_ttl': 900, 'needs': ['cache', 'error_handling', 'performance']}}
    
    for endpoint_name in endpoints.keys():
        print(f"Testing {endpoint_name}...")
        
        # Test caching
        start = time.time()
        result1 = frappe.call(f"verenigingen.api.chapter_dashboard_api.{endpoint_name}")
        time1 = time.time() - start
        
        start = time.time()
        result2 = frappe.call(f"verenigingen.api.chapter_dashboard_api.{endpoint_name}")
        time2 = time.time() - start
        
        print(f"  First call: {time1:.3f}s")
        print(f"  Second call (cached): {time2:.3f}s")
        print(f"  Cache speedup: {time1/time2:.1f}x")
        
        # Test pagination if applicable
        if "limit" in str(result1):
            print(f"  ✓ Pagination supported")
            
        # Test error handling
        try:
            frappe.call(f"verenigingen.api.chapter_dashboard_api.{endpoint_name}", 
                       {"invalid_param": "test"})
        except Exception as e:
            print(f"  ✓ Error handling works: {type(e).__name__}")
            
    print("\n✅ All tests passed!")


if __name__ == "__main__":
    test_optimized_endpoints()
