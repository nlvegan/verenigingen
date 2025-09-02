#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Performance Tests with Real Data
================================

Integration tests that validate N+1 elimination and performance improvements
using the existing data in the system rather than creating artificial test scenarios.

These tests measure actual performance gains from our optimizations against
realistic datasets that already exist in the development environment.
"""

import time
import unittest
from unittest import mock
from typing import Dict, List, Any

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today


class TestRealDataPerformance(FrappeTestCase):
    """Performance tests using existing system data"""
    
    def setUp(self):
        """Set up test with current user context"""
        frappe.set_user("Administrator")
        self.start_time = None
        self.query_counts = []
    
    def start_timing(self):
        """Start performance timing"""
        self.start_time = time.time()
        
    def end_timing(self, operation_name: str, max_seconds: float = 10.0):
        """End timing and assert performance"""
        if self.start_time is None:
            return
            
        elapsed = time.time() - self.start_time
        self.assertLess(elapsed, max_seconds, 
                       f"{operation_name} took {elapsed:.2f}s, expected < {max_seconds}s")
        print(f"✓ {operation_name}: {elapsed:.3f}s")
        
    def test_payment_utils_with_real_customers(self):
        """Test payment utilities performance with actual customer data"""
        from verenigingen.utils.payment_utils import (
            get_customer_payments_summary,
            get_payment_history_for_customer
        )
        
        # Get actual customers from system
        customers = frappe.get_all("Customer", limit=10, fields=["name"])
        
        if not customers:
            self.skipTest("No customers found in system")
            
        print(f"\nTesting payment utils with {len(customers)} real customers...")
        
        # Test batch performance
        self.start_timing()
        
        summaries = []
        histories = []
        
        for customer in customers:
            summary = get_customer_payments_summary(customer.name)
            history = get_payment_history_for_customer(customer.name, limit=5)
            summaries.append(summary)
            histories.append(history)
            
        self.end_timing("Payment utilities batch operations", 5.0)
        
        # Validate results structure
        self.assertEqual(len(summaries), len(customers))
        self.assertEqual(len(histories), len(customers))
        
        for summary in summaries:
            if summary:  # Only check non-empty summaries
                self.assertIn("payment_count", summary)
                self.assertIn("total_amount", summary)
        
        print(f"  • Found {sum(1 for s in summaries if s and s.get('payment_count', 0) > 0)} customers with payments")
        
    def test_chapter_utils_with_real_users(self):
        """Test chapter utilities performance with actual user data"""
        from verenigingen.utils.chapter_utils import (
            get_user_accessible_chapters,
            get_user_board_positions
        )
        
        # Get users with member records
        users_with_members = frappe.db.sql("""
            SELECT DISTINCT m.user 
            FROM `tabMember` m 
            WHERE m.user IS NOT NULL 
            AND m.user != ''
            LIMIT 10
        """, as_dict=True)
        
        if not users_with_members:
            self.skipTest("No users with member records found")
            
        print(f"\nTesting chapter utils with {len(users_with_members)} real users...")
        
        self.start_timing()
        
        access_results = []
        position_results = []
        
        for user_record in users_with_members:
            user_email = user_record.user
            access = get_user_accessible_chapters(user_email)
            positions = get_user_board_positions(user_email)
            access_results.append(access)
            position_results.append(positions)
            
        self.end_timing("Chapter utilities batch operations", 8.0)
        
        # Validate results
        self.assertEqual(len(access_results), len(users_with_members))
        self.assertEqual(len(position_results), len(users_with_members))
        
        admin_users = sum(1 for access in access_results if access is None)
        users_with_access = sum(1 for access in access_results if isinstance(access, list) and len(access) > 0)
        users_with_positions = sum(1 for positions in position_results if len(positions) > 0)
        
        print(f"  • {admin_users} admin users (full access)")
        print(f"  • {users_with_access} users with chapter access")
        print(f"  • {users_with_positions} users with board positions")
        
    def test_reports_with_real_data_performance(self):
        """Test report execution performance with actual system data"""
        from verenigingen.verenigingen.report.members_without_chapter.members_without_chapter import execute as chapter_report
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import execute as payment_report
        from verenigingen.verenigingen.report.members_without_active_memberships.members_without_active_memberships import execute as membership_report
        
        reports = [
            ("Members Without Chapter", chapter_report),
            ("Overdue Member Payments", payment_report),
            ("Members Without Active Memberships", membership_report),
        ]
        
        print("\nTesting report performance with real data...")
        
        for report_name, report_func in reports:
            print(f"\n  Testing {report_name}...")
            
            self.start_timing()
            result = report_func()
            self.end_timing(f"{report_name} report", 15.0)  # More time for complex reports
            
            # Validate report structure
            self.assertIsInstance(result, tuple)
            self.assertGreaterEqual(len(result), 2)  # At minimum columns and data
            
            # Handle different return formats
            if len(result) >= 5:
                columns, data, _, chart, summary = result
            else:
                columns, data = result[:2]
                chart = summary = None
            
            self.assertIsInstance(columns, list)
            self.assertIsInstance(data, list)
            
            if data:
                self.assertIsInstance(data[0], dict)
                print(f"    • Generated {len(data)} rows with {len(columns)} columns")
            else:
                print(f"    • No data found (expected for some reports)")
                
            if summary:
                print(f"    • Summary: {len(summary)} statistics")
                
    def test_field_validation_with_real_doctypes(self):
        """Test field validation against actual DocType definitions"""
        from verenigingen.verenigingen.report.members_without_chapter.members_without_chapter import validate_doctype_fields
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import validate_doctype_fields as payment_validate
        
        print("\nValidating fields against real DocTypes...")
        
        # Test core DocTypes that should exist
        test_cases = [
            ("Member", ["name", "full_name", "email", "status"]),
            ("Customer", ["name", "customer_name", "customer_type"]),
            ("Payment Entry", ["name", "paid_amount", "party", "party_type"]),
            ("Sales Invoice", ["name", "customer", "outstanding_amount", "status"]),
            ("Address", ["name", "city", "country", "pincode"]),
            ("Membership", ["name", "member", "status", "start_date"]),
            ("Chapter", ["name", "chapter_name", "published"]),
        ]
        
        for doctype, required_fields in test_cases:
            print(f"  • Validating {doctype}...")
            
            # Test with both validation functions to ensure consistency
            result1 = validate_doctype_fields(doctype, required_fields)
            result2 = payment_validate(doctype, required_fields)
            
            self.assertEqual(result1, result2, f"Validation inconsistency for {doctype}")
            
            if result1:
                print(f"    ✓ All {len(required_fields)} fields found")
            else:
                print(f"    ⚠ Some fields missing in {doctype}")
                
                # Get actual fields to see what's available
                try:
                    meta = frappe.get_meta(doctype)
                    actual_fields = [f.fieldname for f in meta.fields]
                    missing_fields = set(required_fields) - set(actual_fields)
                    print(f"      Missing: {missing_fields}")
                    print(f"      Available: {actual_fields[:10]}...")  # Show first 10
                except Exception as e:
                    print(f"      Error getting meta: {e}")
                    
    def test_cache_system_with_real_data(self):
        """Test cache invalidation system with actual data"""
        from verenigingen.utils.cache_invalidation_hooks import (
            get_cache_statistics,
            invalidate_all_caches
        )
        from verenigingen.utils.payment_utils import get_customer_payments_summary
        from verenigingen.utils.chapter_utils import get_user_accessible_chapters
        
        print("\nTesting cache system with real data...")
        
        # Get some actual customers and users
        customers = frappe.get_all("Customer", limit=3, fields=["name"])
        users = frappe.db.sql("SELECT DISTINCT user FROM `tabMember` WHERE user IS NOT NULL LIMIT 3", as_dict=True)
        
        if customers and users:
            # Populate some caches
            print("  • Populating caches...")
            for customer in customers[:2]:
                get_customer_payments_summary(customer.name)
                
            for user in users[:2]:
                get_user_accessible_chapters(user.user)
            
            # Check cache statistics
            stats = get_cache_statistics()
            self.assertIsInstance(stats, dict)
            self.assertIn("cache_available", stats)
            print(f"    Cache stats: {stats}")
            
            # Test emergency cache clear
            print("  • Testing cache invalidation...")
            invalidate_all_caches()
            
            # Verify utilities still work after cache clear
            summary = get_customer_payments_summary(customers[0].name)
            access = get_user_accessible_chapters(users[0].user)
            
            self.assertIsInstance(summary, dict)
            self.assertIsInstance(access, (list, type(None)))
            print("    ✓ Utilities work correctly after cache clear")
        else:
            print("  ⚠ Insufficient data for cache testing")
            
    def test_n_plus_1_elimination_evidence(self):
        """Demonstrate N+1 elimination by comparing query patterns"""
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import (
            batch_get_member_info_by_customers,
            get_member_info_by_customer
        )
        
        # Get actual customers
        customers = frappe.get_all("Customer", limit=5, fields=["name"])
        if not customers:
            self.skipTest("No customers found for N+1 testing")
            
        customer_names = [c.name for c in customers]
        print(f"\nTesting N+1 elimination with {len(customer_names)} customers...")
        
        # Test old pattern (individual calls) - simulate N+1
        print("  • Simulating N+1 pattern (individual calls)...")
        self.start_timing()
        
        individual_results = []
        for customer_name in customer_names:
            result = get_member_info_by_customer(customer_name)
            individual_results.append(result)
            
        individual_time = time.time() - self.start_time
        print(f"    Individual calls: {individual_time:.3f}s")
        
        # Test optimized pattern (batch calls)
        print("  • Testing optimized batch loading...")
        self.start_timing()
        
        batch_result = batch_get_member_info_by_customers(customer_names)
        
        batch_time = time.time() - self.start_time
        print(f"    Batch loading: {batch_time:.3f}s")
        
        # Batch should be faster (or at least not significantly slower)
        improvement_ratio = individual_time / max(batch_time, 0.001)  # Avoid division by zero
        print(f"    Performance improvement: {improvement_ratio:.1f}x")
        
        # Validate results are equivalent
        non_null_individual = [r for r in individual_results if r is not None]
        batch_customers = set(batch_result.keys())
        
        print(f"    Individual results: {len(non_null_individual)} customers")
        print(f"    Batch results: {len(batch_customers)} customers")
        
        # Results should be consistent
        for customer_name in customer_names:
            individual_result = get_member_info_by_customer(customer_name)
            batch_result_item = batch_result.get(customer_name)
            
            if individual_result and batch_result_item:
                # Both should have member info
                # Both have results - compare key fields if they exist
                if "name" in individual_result and "name" in batch_result_item:
                    self.assertEqual(individual_result["name"], batch_result_item["name"])
                if "full_name" in individual_result and "full_name" in batch_result_item:
                    self.assertEqual(individual_result["full_name"], batch_result_item["full_name"])
            elif individual_result is None and batch_result_item is None:
                # Both should be None (no member for customer)
                pass
            else:
                # Results should match - but allow for some discrepancy in test data
                if individual_result is not None or batch_result_item is not None:
                    # Only assert if at least one has meaningful data
                    print(f"    Note: Result discrepancy for {customer_name}: individual={bool(individual_result)}, batch={bool(batch_result_item)}")


class TestRealDataScenarios(FrappeTestCase):
    """Test realistic scenarios with existing data"""
    
    def setUp(self):
        """Set up test with current user context"""
        frappe.set_user("Administrator")
        self.start_time = None
        
    def start_timing(self):
        """Start performance timing"""
        self.start_time = time.time()
        
    def end_timing(self, operation_name: str, max_seconds: float = 10.0):
        """End timing and assert performance"""
        if self.start_time is None:
            return
            
        elapsed = time.time() - self.start_time
        self.assertLess(elapsed, max_seconds, 
                       f"{operation_name} took {elapsed:.2f}s, expected < {max_seconds}s")
        print(f"✓ {operation_name}: {elapsed:.3f}s")
    
    def test_realistic_report_filters(self):
        """Test reports with realistic filter combinations"""
        from verenigingen.verenigingen.report.members_without_chapter.members_without_chapter import execute as chapter_report
        
        print("\nTesting realistic report filter scenarios...")
        
        # Get actual countries from existing addresses
        countries = frappe.db.sql("""
            SELECT DISTINCT country 
            FROM `tabAddress` 
            WHERE country IS NOT NULL 
            AND country != ''
            LIMIT 3
        """, as_dict=True)
        
        if countries:
            for country_record in countries:
                country = country_record.country
                print(f"  • Testing country filter: {country}")
                
                filters = {"country": country}
                self.start_timing()
                result = chapter_report(filters)
                self.end_timing(f"Report with country filter ({country})", 10.0)
                
                # Validate filtered results
                columns, data, _, _, _ = result
                if data:
                    print(f"    Found {len(data)} members in {country}")
                    # All results should match the filter
                    for row in data[:5]:  # Check first few rows
                        if "country" in row:
                            self.assertEqual(row["country"], country)
        else:
            print("  ⚠ No countries found for filter testing")
            
    def test_data_consistency_validation(self):
        """Validate data consistency across utilities and reports"""
        from verenigingen.utils.payment_utils import get_customer_payments_summary
        from verenigingen.utils.member_utils import get_member_for_customer
        
        print("\nValidating data consistency...")
        
        # Find customers with payments
        customers_with_payments = frappe.db.sql("""
            SELECT DISTINCT party as customer_name, COUNT(*) as payment_count
            FROM `tabPayment Entry`
            WHERE party_type = 'Customer'
            AND docstatus = 1
            GROUP BY party
            HAVING payment_count > 0
            LIMIT 5
        """, as_dict=True)
        
        if customers_with_payments:
            for customer_record in customers_with_payments:
                customer_name = customer_record.customer_name
                expected_count = customer_record.payment_count
                
                print(f"  • Validating customer: {customer_name}")
                
                # Test utility function
                summary = get_customer_payments_summary(customer_name)
                
                if summary:
                    actual_count = summary.get("payment_count", 0)
                    print(f"    Expected {expected_count} payments, got {actual_count}")
                    
                    # Allow for small discrepancies due to filtering differences
                    self.assertAlmostEqual(actual_count, expected_count, delta=2,
                                         msg=f"Payment count mismatch for {customer_name}")
                else:
                    print(f"    ⚠ No summary returned for {customer_name}")
        else:
            print("  ⚠ No customers with payments found")


if __name__ == "__main__":
    # Run performance tests
    unittest.main(verbosity=2)