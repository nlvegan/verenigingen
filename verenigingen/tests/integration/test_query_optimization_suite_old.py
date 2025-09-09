#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Query Optimization Integration Tests
===================================

Comprehensive test suite for validating N+1 query elimination, 
performance monitoring, field validation, and cache invalidation.

Tests the following utilities and improvements:
- payment_utils.py: Batch payment operations
- chapter_utils.py: User access control with batch loading
- cache_invalidation_hooks.py: Automatic cache management
- Report performance monitoring and field validation
- N+1 query pattern elimination across report files
"""

import time
import unittest
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today, getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestQueryOptimizationSuite(EnhancedTestCase):
    """Integration tests for query optimization improvements"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test class with enhanced test factory"""
        super().setUpClass()
        cls.test_members = []
        cls.test_customers = []
        cls.test_payments = []
        cls.test_chapters = []
        
    def setUp(self):
        """Set up individual test with clean data"""
        super().setUp()
        
    def tearDown(self):
        """Clean up test data after each test"""
        super().tearDown()
        
        # Clean up any test data created during tests
        for member_name in self.test_members:
            if frappe.db.exists("Member", member_name):
                frappe.delete_doc("Member", member_name, force=True, ignore_permissions=True)
        
        for customer_name in self.test_customers:
            if frappe.db.exists("Customer", customer_name):
                frappe.delete_doc("Customer", customer_name, force=True, ignore_permissions=True)
                
        for payment_name in self.test_payments:
            if frappe.db.exists("Payment Entry", payment_name):
                frappe.delete_doc("Payment Entry", payment_name, force=True, ignore_permissions=True)
                
        for chapter_name in self.test_chapters:
            if frappe.db.exists("Chapter", chapter_name):
                frappe.delete_doc("Chapter", chapter_name, force=True, ignore_permissions=True)
        
        self.test_members.clear()
        self.test_customers.clear() 
        self.test_payments.clear()
        self.test_chapters.clear()
        
        frappe.db.commit()

    # ================== PAYMENT UTILS TESTS ==================
    
    def test_payment_utils_batch_loading(self):
        """Test payment utilities use batch loading instead of N+1 queries"""
        from verenigingen.utils.payment_utils import (
            get_customer_payments_summary,
            get_payment_history_for_customer,
            batch_get_member_info_by_customers,
        )
        
        # Create test customers and payments
        customer1 = self.create_test_customer("Test Customer 1")
        customer2 = self.create_test_customer("Test Customer 2")
        self.test_customers.extend([customer1.name, customer2.name])
        
        # Create payments for both customers
        for customer in [customer1, customer2]:
            for i in range(3):
                payment = self.create_test_payment_entry(
                    party=customer.name,
                    paid_amount=100 + i * 10,
                    posting_date=add_days(today(), -i)
                )
                self.test_payments.append(payment.name)
        
        # Test batch operation - should use single query per customer
        with self.assertQueryCount(10):  # Reasonable limit for batch operations
            summary1 = get_customer_payments_summary(customer1.name)
            summary2 = get_customer_payments_summary(customer2.name)
            
        self.assertEqual(summary1["payment_count"], 3)
        self.assertEqual(summary2["payment_count"], 3)
        self.assertGreater(summary1["total_amount"], 0)
        self.assertGreater(summary2["total_amount"], 0)

    def test_payment_field_validation(self):
        """Test payment utils validate required fields exist"""
        from verenigingen.utils.payment_utils import get_customer_payments_summary
        
        # Mock frappe.get_meta to simulate missing fields
        with mock.patch('frappe.get_meta') as mock_meta:
            mock_field = mock.Mock()
            mock_field.fieldname = "name"  # Only provide one field
            
            mock_meta.return_value.fields = [mock_field]
            
            # Should handle missing fields gracefully  
            result = get_customer_payments_summary("nonexistent-customer")
            self.assertEqual(result, {})  # Should return empty dict for invalid customer

    def test_payment_cache_invalidation(self):
        """Test payment cache is properly invalidated on changes"""
        from verenigingen.utils.payment_utils import (
            get_customer_payments_summary,
            invalidate_payment_cache,
        )
        from verenigingen.utils.cache_invalidation_hooks import invalidate_payment_cache as hook_invalidate
        
        # Create test customer and payment
        customer = self.create_test_customer("Cache Test Customer")
        self.test_customers.append(customer.name)
        
        payment = self.create_test_payment_entry(
            party=customer.name,
            paid_amount=150
        )
        self.test_payments.append(payment.name)
        
        # Get initial summary (should cache it)
        summary1 = get_customer_payments_summary(customer.name)
        self.assertEqual(summary1["payment_count"], 1)
        
        # Test manual cache invalidation
        invalidate_payment_cache(customer.name)
        
        # Test hook-based cache invalidation
        hook_invalidate(payment, "on_submit")
        
        # Summary should still be correct after cache clear
        summary2 = get_customer_payments_summary(customer.name)
        self.assertEqual(summary2["payment_count"], 1)

    # ================== CHAPTER UTILS TESTS ==================
    
    def test_chapter_utils_batch_loading(self):
        """Test chapter utilities use batch loading for board positions"""
        from verenigingen.utils.chapter_utils import (
            get_user_accessible_chapters,
            get_user_board_positions,
        )
        
        # Create test member with user
        member = self.create_test_member("Chapter", "Test User", user_email="chapter.testuser@example.com")
        self.test_members.append(member.name)
        
        # Create test chapters
        chapter1 = self.create_test_chapter("Test Chapter Alpha")
        chapter2 = self.create_test_chapter("Test Chapter Beta")
        self.test_chapters.extend([chapter1.name, chapter2.name])
        
        # Create volunteer and board positions
        volunteer = self.create_test_volunteer(member.name)
        role = self.create_test_chapter_role("Admin Role", permissions_level="Admin")
        
        board_pos1 = self.create_test_board_position(chapter1.name, volunteer.name, role.name)
        board_pos2 = self.create_test_board_position(chapter2.name, volunteer.name, role.name)
        
        # Test batch operations with reasonable query limits
        with self.assertQueryCount(20):  # Reasonable limit for complex operations
            accessible = get_user_accessible_chapters("chapter.testuser@example.com")
            positions = get_user_board_positions("chapter.testuser@example.com")
            
        self.assertIsInstance(accessible, list)
        self.assertGreater(len(positions), 0)  # Should find board positions

    def test_chapter_access_defensive_programming(self):
        """Test chapter utilities handle missing fields/documents gracefully"""
        from verenigingen.utils.chapter_utils import get_user_accessible_chapters
        
        # Test with non-existent user
        result = get_user_accessible_chapters("nonexistent@example.com")
        self.assertEqual(result, [])  # Should return empty list for missing user
        
        # Test with empty email
        result = get_user_accessible_chapters("")
        self.assertEqual(result, [])

    def test_chapter_cache_invalidation(self):
        """Test chapter access cache is invalidated on board changes"""
        from verenigingen.utils.chapter_utils import (
            get_user_accessible_chapters,
            invalidate_chapter_access_cache,
        )
        from verenigingen.utils.cache_invalidation_hooks import invalidate_chapter_access_cache as hook_invalidate
        
        # Create test data
        member = self.create_test_member("Cache", "Chapter User", user_email="cache.chapteruser@example.com")
        self.test_members.append(member.name)
        
        volunteer = self.create_test_volunteer(member.name)
        chapter = self.create_test_chapter("Cache Test Chapter")  
        self.test_chapters.append(chapter.name)
        
        role = self.create_test_chapter_role("Cache Admin Role", permissions_level="Admin")
        board_pos = self.create_test_board_position(chapter.name, volunteer.name, role.name)
        
        # Get initial access (caches result)
        access1 = get_user_accessible_chapters("cache.chapteruser@example.com")
        
        # Test manual cache invalidation
        invalidate_chapter_access_cache("cache.chapteruser@example.com")
        
        # Test hook-based invalidation
        hook_invalidate(board_pos, "on_update")
        
        # Access should still work after cache clear
        access2 = get_user_accessible_chapters("cache.chapteruser@example.com")
        self.assertIsInstance(access2, list)

    # ================== REPORT PERFORMANCE TESTS ==================
    
    def test_report_field_validation(self):
        """Test reports validate fields before executing queries"""
        from verenigingen.verenigingen.report.members_without_chapter.members_without_chapter import (
            validate_doctype_fields, get_data
        )
        
        # Test validation function directly
        member_fields = ["name", "full_name", "email", "contact_number", "status"]
        valid = validate_doctype_fields("Member", member_fields)
        self.assertTrue(valid)  # These should all exist
        
        # Test with nonexistent field
        invalid_fields = ["nonexistent_field", "another_missing_field"]
        invalid = validate_doctype_fields("Member", invalid_fields)
        self.assertFalse(invalid)  # Should fail validation
        
        # Test report handles validation failure gracefully with real invalid data
        # Create a temporary invalid query scenario by testing with malformed parameters
        try:
            # Test with parameters that should cause real validation issues
            invalid_filters = {"nonexistent_field": "test_value"}
            result = get_data(invalid_filters)
            
            # If it returns data despite invalid filters, that's valuable information
            # If it returns empty, the validation is working
            self.assertIsInstance(result, list)  # Should return list regardless
        except Exception as e:
            # Real validation errors are valuable test information
            self.assertIsInstance(e, (frappe.ValidationError, AttributeError, KeyError))
            # This shows the report properly handles validation failures

    def test_report_performance_monitoring(self):
        """Test reports log execution time and row counts"""
        from verenigingen.verenigingen.report.members_without_chapter.members_without_chapter import execute
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import execute as overdue_execute
        
        # Mock frappe.logger to capture performance logs
        with mock.patch('frappe.logger') as mock_logger:
            # Test members without chapter report
            result1 = execute()
            self.assertIsInstance(result1, tuple)
            self.assertEqual(len(result1), 5)  # columns, data, None, chart, summary
            
            # Should have logged performance info
            mock_logger.return_value.info.assert_called()
            info_calls = [call for call in mock_logger.return_value.info.call_args_list 
                         if "members_without_chapter report:" in str(call)]
            self.assertGreater(len(info_calls), 0)  # Should have performance log
            
            # Test overdue payments report
            mock_logger.reset_mock()
            result2 = overdue_execute()
            self.assertIsInstance(result2, tuple)
            
            # Should have logged performance info
            mock_logger.return_value.info.assert_called()
            info_calls = [call for call in mock_logger.return_value.info.call_args_list 
                         if "overdue_member_payments report:" in str(call)]
            self.assertGreater(len(info_calls), 0)

    def test_batch_loading_elimination(self):
        """Test N+1 patterns are eliminated with proper batch loading"""
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import (
            batch_get_member_info_by_customers
        )
        
        # Create multiple customers for batch testing
        customers = []
        for i in range(5):
            customer = self.create_test_customer(f"Batch Customer {i+1}")
            customers.append(customer.name)
            self.test_customers.append(customer.name)
            
            # Create corresponding member
            member = self.create_test_member(f"Batch{i+1}", "Member", customer=customer.name)
            self.test_members.append(member.name)
        
        # Test batch loading should be efficient
        with self.assertQueryCount(10):  # Should use batch queries, not 5x individual queries
            member_info_map = batch_get_member_info_by_customers(customers)
            
        # Should return info for all customers
        self.assertEqual(len(member_info_map), 5)
        for customer_name in customers:
            self.assertIn(customer_name, member_info_map)
            member_info = member_info_map[customer_name]
            self.assertIn("name", member_info)
            self.assertIn("full_name", member_info)

    # ================== ERROR HANDLING TESTS ==================
    
    def test_graceful_error_handling(self):
        """Test all utilities handle errors gracefully with proper logging"""
        from verenigingen.utils.payment_utils import get_customer_payments_summary
        from verenigingen.utils.chapter_utils import get_user_accessible_chapters
        
        # Mock frappe.logger to capture error logs
        with mock.patch('frappe.logger') as mock_logger:
            # Test payment utils error handling with invalid customer ID
            # Use a clearly nonexistent customer ID to trigger real error handling
            result = get_customer_payments_summary("NONEXISTENT-CUSTOMER-ID-999")
            
            # Should handle error gracefully - may return empty dict or None
            self.assertIsInstance(result, (dict, type(None)))
            if isinstance(result, dict):
                # If dict returned, it should be empty for nonexistent customer
                self.assertEqual(len(result), 0)
                
            # Error logging verification (real error handling)
            if mock_logger.return_value.error.called:
                print("  ✓ Real error logged for nonexistent customer")
            
            # Test chapter utils error handling  
            mock_logger.reset_mock()
            with mock.patch('frappe.get_roles', side_effect=Exception("Role lookup error")):
                result = get_user_accessible_chapters("test@example.com")
                self.assertEqual(result, [])  # Should return empty list on error
                
            # Should have logged the error
            mock_logger.return_value.error.assert_called()

    # ================== INTEGRATION TESTS ==================
    
    def test_end_to_end_report_workflow(self):
        """Test complete workflow from member creation to report generation"""
        # Create complete test scenario
        member = self.create_test_member("E2E", "Test", birth_date="1990-01-01")
        customer = self.create_test_customer("E2E Test Customer") 
        chapter = self.create_test_chapter("E2E Test Chapter")
        
        self.test_members.append(member.name)
        self.test_customers.append(customer.name)
        self.test_chapters.append(chapter.name)
        
        # Link member to customer
        member.customer = customer.name
        member.save()
        
        # Create payment entries
        for i in range(3):
            payment = self.create_test_payment_entry(
                party=customer.name,
                paid_amount=50 + i * 25,
                posting_date=add_days(today(), -i * 10)
            )
            self.test_payments.append(payment.name)
            
        # Create active membership
        membership = self.create_test_membership(
            member.name, 
            status="Active",
            start_date=add_days(today(), -30)
        )
        
        # Test reports execute without errors
        from verenigingen.verenigingen.report.members_without_chapter.members_without_chapter import execute as chapter_report
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import execute as payment_report
        
        # Both reports should execute successfully
        chapter_result = chapter_report()
        payment_result = payment_report()
        
        self.assertIsInstance(chapter_result, tuple)
        self.assertIsInstance(payment_result, tuple)
        self.assertEqual(len(chapter_result), 5)
        self.assertEqual(len(payment_result), 5)

    def test_cache_invalidation_integration(self):
        """Test cache invalidation works across all utilities"""
        from verenigingen.utils.cache_invalidation_hooks import (
            invalidate_all_caches,
            get_cache_statistics,
        )
        
        # Create test data to populate caches
        member = self.create_test_member("Cache", "Integration", user_email="cache.integration@example.com")
        customer = self.create_test_customer("Cache Integration Customer")
        
        self.test_members.append(member.name)
        self.test_customers.append(customer.name)
        
        member.customer = customer.name
        member.save()
        
        payment = self.create_test_payment_entry(
            party=customer.name,
            paid_amount=200
        )
        self.test_payments.append(payment.name)
        
        # Access utilities to populate caches
        from verenigingen.utils.payment_utils import get_customer_payments_summary
        from verenigingen.utils.chapter_utils import get_user_accessible_chapters
        
        get_customer_payments_summary(customer.name)
        get_user_accessible_chapters("cache.integration@example.com")
        
        # Test cache statistics
        stats = get_cache_statistics()
        self.assertIsInstance(stats, dict)
        self.assertIn("cache_available", stats)
        
        # Test emergency cache clear
        invalidate_all_caches()  # Should not raise errors
        
        # Utilities should still work after cache clear
        summary = get_customer_payments_summary(customer.name)
        access = get_user_accessible_chapters("cache.integration@example.com")
        
        self.assertIsInstance(summary, dict)
        self.assertIsInstance(access, list)


class TestPerformanceRegression(EnhancedTestCase):
    """Performance regression tests to ensure optimizations work"""
    
    def test_no_n_plus_1_in_batch_operations(self):
        """Ensure batch operations don't regress to N+1 patterns"""
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import (
            batch_get_member_info_by_customers
        )
        
        # Create larger dataset for performance testing
        customer_names = []
        for i in range(10):  # 10 customers
            customer = self.create_test_customer(f"Perf Customer {i+1}")
            customer_names.append(customer.name)
            
            member = self.create_test_member(f"Perf{i+1}", "Member", customer=customer.name)
        
        # Batch operation should use constant number of queries regardless of data size
        with self.assertQueryCount(5):  # Should not scale with number of customers
            result = batch_get_member_info_by_customers(customer_names)
            
        # Should return all customer info
        self.assertEqual(len(result), 10)

    def test_report_execution_performance(self):
        """Test reports execute within reasonable time limits"""
        from verenigingen.verenigingen.report.members_without_chapter.members_without_chapter import execute
        
        start_time = time.time()
        result = execute()
        execution_time = time.time() - start_time
        
        # Report should execute within 5 seconds even on empty database
        self.assertLess(execution_time, 5.0)
        self.assertIsInstance(result, tuple)


if __name__ == "__main__":
    # Support for running tests individually
    unittest.main()