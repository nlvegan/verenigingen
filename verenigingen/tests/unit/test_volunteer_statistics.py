"""
Unit tests for volunteer statistics utilities

Tests the shared volunteer statistics module to ensure consistent
expense calculations across the volunteer expenses and dashboard pages.

Uses Enhanced Test Factory for reliable integration testing with real data.
"""

import unittest
from unittest.mock import patch, MagicMock
import frappe
from frappe.utils import today, add_months, flt
from verenigingen.utils.volunteer_statistics import (
    get_volunteer_expense_statistics,
    get_volunteer_expense_summary
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerStatistics(EnhancedTestCase):
    """Test cases for volunteer statistics utilities"""
    
    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        
        # Create real test data using Enhanced Test Factory
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Volunteer",
            birth_date="1990-01-01"
        )
        
        # Create volunteer linked to member  
        self.test_volunteer = self.create_test_volunteer(self.test_member.name)
        self.volunteer_name = self.test_volunteer.name
        self.employee_id = "HR-EMP-00001"  # For mock tests
    
    def test_volunteer_statistics_integration_real_data(self):
        """Integration test with real volunteer and expense data"""
        # Test with real volunteer (no expenses initially)
        result = get_volunteer_expense_statistics(self.volunteer_name)
        
        # Should return zero values for volunteer with no expenses
        self.assertEqual(result["total_submitted"], 0)
        self.assertEqual(result["total_approved"], 0)
        self.assertEqual(result["pending_count"], 0)
        self.assertEqual(result["approved_count"], 0)
        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["pending_amount"], 0)
        
        # Verify all keys are present
        expected_keys = [
            "total_submitted", "total_approved", "pending_amount", 
            "pending_count", "approved_count", "total_count"
        ]
        for key in expected_keys:
            self.assertIn(key, result)
    
    def test_volunteer_expense_summary_integration(self):
        """Integration test for expense summary function"""
        result = get_volunteer_expense_summary(self.volunteer_name)
        
        # Should include all stats plus recent_count
        expected_keys = [
            "total_submitted", "total_approved", "pending_amount", 
            "pending_count", "approved_count", "total_count", "recent_count"
        ]
        for key in expected_keys:
            self.assertIn(key, result)
            self.assertIsInstance(result[key], (int, float))
        
        # For new volunteer, recent_count should be 0
        self.assertEqual(result["recent_count"], 0)
    
    # NOTE: test_status_mapping_comprehensive removed - _map_erpnext_status_to_volunteer_status
    # was part of the archived Volunteer Expense DocType. Native Expense Claim uses ERPNext statuses.
    
    def test_volunteer_expense_statistics_with_nonexistent_volunteer(self):
        """Test statistics function handles non-existent volunteer gracefully"""
        result = get_volunteer_expense_statistics("NONEXISTENT-VOLUNTEER")
        
        # Should return safe defaults without throwing exception
        expected_defaults = {
            "total_submitted": 0,
            "total_approved": 0,
            "pending_amount": 0,
            "pending_count": 0,
            "approved_count": 0,
            "total_count": 0,
        }
        
        for key, expected_value in expected_defaults.items():
            self.assertEqual(result[key], expected_value, f"Expected {key}={expected_value}, got {result[key]}")
    
    def test_months_back_parameter_integration(self):
        """Test that months_back parameter works with real data"""
        # Test with different month ranges
        result_12_months = get_volunteer_expense_statistics(self.volunteer_name, months_back=12)
        result_6_months = get_volunteer_expense_statistics(self.volunteer_name, months_back=6)
        result_1_month = get_volunteer_expense_statistics(self.volunteer_name, months_back=1)
        
        # All should return same structure for volunteer with no expenses
        expected_keys = ["total_submitted", "total_approved", "pending_amount", "pending_count", "approved_count", "total_count"]
        
        for result in [result_12_months, result_6_months, result_1_month]:
            for key in expected_keys:
                self.assertIn(key, result)
                self.assertEqual(result[key], 0)  # No expenses means all zeros
        
    def test_get_volunteer_expense_summary_functionality(self):
        """Test expense summary function behavior without inappropriate mocks"""
        # This test validates the expense summary function with real data
        result = get_volunteer_expense_summary(self.volunteer_name)
        basic_result = get_volunteer_expense_statistics(self.volunteer_name)
        
        # Summary should have all basic statistics fields
        basic_fields = ["total_submitted", "total_approved", "pending_count", 
                       "approved_count", "total_count", "pending_amount"]
        for field in basic_fields:
            self.assertIn(field, result)
            self.assertEqual(result[field], basic_result[field], 
                f"Summary field {field} should match basic statistics")
        
        # Summary should have additional recent_count field that basic stats lacks
        self.assertIn("recent_count", result)
        self.assertNotIn("recent_count", basic_result)
        self.assertIsInstance(result["recent_count"], int)
        self.assertGreaterEqual(result["recent_count"], 0)
    
    # NOTE: test_map_erpnext_status_to_volunteer_status removed - function was part of archived
    # Volunteer Expense DocType. Native Expense Claim uses standard ERPNext statuses directly.
        
    def test_error_handling_integration(self):
        """Test error handling with invalid input returns safe defaults"""
        # Test with completely invalid volunteer name
        result = get_volunteer_expense_statistics("INVALID-ID-123-XYZ")
        
        # Should return safe defaults without throwing exception
        expected_defaults = {
            "total_submitted": 0,
            "total_approved": 0,
            "pending_amount": 0,
            "pending_count": 0,
            "approved_count": 0,
            "total_count": 0,
        }
        
        for key, expected_value in expected_defaults.items():
            self.assertEqual(result[key], expected_value, 
                f"Error handling failed: {key}={result[key]}, expected {expected_value}")
        
    def test_months_back_parameter_behavior(self):
        """Test that months_back parameter accepts different values without error"""
        # Test various month ranges - should all work without exception
        test_ranges = [1, 3, 6, 12, 24, 36]
        
        for months in test_ranges:
            with self.subTest(months_back=months):
                result = get_volunteer_expense_statistics(self.volunteer_name, months_back=months)
                
                # Should return consistent structure regardless of month range
                expected_keys = ["total_submitted", "total_approved", "pending_amount", 
                               "pending_count", "approved_count", "total_count"]
                for key in expected_keys:
                    self.assertIn(key, result)
                    self.assertIsInstance(result[key], (int, float))
                    # For volunteer with no expenses, all should be 0
                    self.assertEqual(result[key], 0)


if __name__ == '__main__':
    unittest.main()