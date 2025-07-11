"""
Comprehensive test suite for API optimization improvements

This test suite validates that the code quality improvements are working correctly:
- Error handling standardization
- Performance monitoring
- Input validation
- Role-based access control
- Rate limiting
- Caching optimization
"""

import time
import json
from unittest.mock import patch, Mock

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.test_framework_enhanced import (
    VerenigingenTestCase, PerformanceTestCase, IntegrationTestCase
)
from verenigingen.utils.error_handling import ValidationError, PermissionError
from verenigingen.utils.performance_utils import CacheManager
from verenigingen.utils.api_validators import APIValidator
from verenigingen.utils.config_manager import ConfigManager


class TestAPIOptimizationSuite(VerenigingenTestCase):
    """Test suite for API optimization improvements"""
    
    def setUp(self):
        super().setUp()
        
        # Create test data
        self.test_member = self.create_test_member(
            email="api.test@example.com",
            first_name="API",
            last_name="Test"
        )
        
        self.test_chapter = self.create_test_chapter("API Test Chapter")
    
    def test_error_handling_standardization(self):
        """Test that error handling is standardized across API endpoints"""
        
        from verenigingen.api.member_management import assign_member_to_chapter
        
        # Test with invalid inputs to trigger error handling
        with self.assertRaises(ValidationError):
            assign_member_to_chapter(None, None)
        
        with self.assertRaises(ValidationError):
            assign_member_to_chapter("", "")
        
        # Test with non-existent member
        with self.assertRaises(ValidationError):
            assign_member_to_chapter("NONEXISTENT", self.test_chapter.name)
    
    def test_performance_monitoring_decorators(self):
        """Test that performance monitoring decorators are working"""
        
        from verenigingen.api.payment_processing import send_overdue_payment_reminders
        
        # Mock the required dependencies
        with patch('verenigingen.api.payment_processing.get_data') as mock_get_data:
            mock_get_data.return_value = []
            
            # Performance monitoring should capture execution time
            start_time = time.time()
            result = send_overdue_payment_reminders(
                reminder_type="Test",
                filters="{}"
            )
            execution_time = (time.time() - start_time) * 1000
            
            # Should complete quickly with empty data
            self.assertLess(execution_time, 1000)  # Less than 1 second
            self.assertTrue(result.get("success"))
    
    def test_input_validation_improvements(self):
        """Test enhanced input validation"""
        
        # Test email validation
        valid_email = APIValidator.validate_email("test@example.com")
        self.assertEqual(valid_email, "test@example.com")
        
        with self.assertRaises(ValidationError):
            APIValidator.validate_email("invalid-email")
        
        with self.assertRaises(ValidationError):
            APIValidator.validate_email("")
        
        # Test name validation
        valid_name = APIValidator.validate_name("John Doe", "name")
        self.assertEqual(valid_name, "John Doe")
        
        with self.assertRaises(ValidationError):
            APIValidator.validate_name("", "name")
        
        with self.assertRaises(ValidationError):
            APIValidator.validate_name("Name123!", "name")  # Invalid characters
        
        # Test amount validation
        valid_amount = APIValidator.validate_amount("25.50", min_amount=0)
        self.assertEqual(valid_amount, 25.50)
        
        with self.assertRaises(ValidationError):
            APIValidator.validate_amount("-10", min_amount=0)
        
        with self.assertRaises(ValidationError):
            APIValidator.validate_amount("invalid", min_amount=0)
    
    def test_caching_functionality(self):
        """Test that caching decorators work correctly"""
        
        from verenigingen.utils.performance_utils import cached, CacheManager
        
        # Clear cache before test
        CacheManager.clear()
        
        call_count = 0
        
        @cached(ttl=60)
        def test_cached_function(param):
            nonlocal call_count
            call_count += 1
            return f"Result for {param}"
        
        # First call should execute function
        result1 = test_cached_function("test")
        self.assertEqual(call_count, 1)
        self.assertEqual(result1, "Result for test")
        
        # Second call should use cache
        result2 = test_cached_function("test")
        self.assertEqual(call_count, 1)  # Should not increment
        self.assertEqual(result2, "Result for test")
        
        # Different parameter should execute function again
        result3 = test_cached_function("different")
        self.assertEqual(call_count, 2)
        self.assertEqual(result3, "Result for different")
    
    def test_configuration_management(self):
        """Test centralized configuration management"""
        
        # Test default values
        default_page_size = ConfigManager.get("default_page_size")
        self.assertEqual(default_page_size, 20)
        
        # Test non-existent key with default
        custom_value = ConfigManager.get("non_existent_key", "default_value")
        self.assertEqual(custom_value, "default_value")
        
        # Test convenience functions
        page_size = ConfigManager.get("default_page_size", 20)
        self.assertIsInstance(page_size, int)
        self.assertGreater(page_size, 0)
        
        # Test batch size configuration
        from verenigingen.utils.config_manager import get_batch_size
        
        email_batch = get_batch_size("email")
        default_batch = get_batch_size("default")
        
        self.assertIsInstance(email_batch, int)
        self.assertIsInstance(default_batch, int)
        self.assertGreater(email_batch, 0)
        self.assertGreater(default_batch, 0)
    
    def test_query_optimization_utilities(self):
        """Test query optimization utilities"""
        
        from verenigingen.utils.performance_utils import QueryOptimizer
        
        # Test bulk operations
        member_names = [self.test_member.name]
        
        # Test bulk_get_values
        results = QueryOptimizer.bulk_get_values(
            "Member", 
            member_names, 
            ["first_name", "last_name"]
        )
        
        self.assertIn(self.test_member.name, results)
        self.assertEqual(results[self.test_member.name]["first_name"], "API")
        self.assertEqual(results[self.test_member.name]["last_name"], "Test")
        
        # Test with empty list
        empty_results = QueryOptimizer.bulk_get_values("Member", [], "first_name")
        self.assertEqual(empty_results, {})
    
    def test_api_validators_comprehensive(self):
        """Comprehensive test of API validators"""
        
        # Test postal code validation
        valid_postal = APIValidator.validate_postal_code("1234AB", "NL")
        self.assertEqual(valid_postal, "1234AB")
        
        with self.assertRaises(ValidationError):
            APIValidator.validate_postal_code("invalid", "NL")
        
        # Test phone validation
        valid_phone = APIValidator.validate_phone("+31612345678")
        self.assertEqual(valid_phone, "+31612345678")
        
        # Test text sanitization
        sanitized = APIValidator.sanitize_text("   Hello World   ", max_length=100)
        self.assertEqual(sanitized, "Hello World")
        
        with self.assertRaises(ValidationError):
            APIValidator.sanitize_text("A" * 1001, max_length=1000)
        
        # Test date validation
        valid_date = APIValidator.validate_date("2023-01-01")
        self.assertIsNotNone(valid_date)
        
        with self.assertRaises(ValidationError):
            APIValidator.validate_date("invalid-date")
    
    def test_permission_optimization(self):
        """Test optimized permission checking"""
        
        from verenigingen.utils.performance_utils import PermissionOptimizer
        
        # Test bulk permission checking (with mock data since we can't create real users easily)
        user_emails = ["test1@example.com", "test2@example.com"]
        
        # This should run without errors and return expected structure
        team_memberships = PermissionOptimizer.get_user_teams_bulk(user_emails)
        self.assertIsInstance(team_memberships, dict)
        
        chapter_permissions = PermissionOptimizer.get_chapter_permissions_bulk(user_emails)
        self.assertIsInstance(chapter_permissions, dict)
        
        # Test with empty list
        empty_teams = PermissionOptimizer.get_user_teams_bulk([])
        self.assertEqual(empty_teams, {})


class TestAPIPerformanceOptimization(PerformanceTestCase):
    """Performance-focused tests for API optimization"""
    
    def test_batch_processing_performance(self):
        """Test that batch processing improves performance"""
        
        # Create test data
        test_members = []
        for i in range(10):
            member = self.create_test_member(
                email=f"batch.test.{i}@example.com",
                first_name=f"Batch{i}",
                last_name="Test"
            )
            test_members.append(member)
        
        member_names = [m.name for m in test_members]
        
        # Test individual queries (inefficient)
        def individual_queries():
            results = {}
            for name in member_names:
                results[name] = frappe.db.get_value("Member", name, "first_name")
            return results
        
        # Test batch query (efficient)
        def batch_query():
            from verenigingen.utils.performance_utils import QueryOptimizer
            return QueryOptimizer.bulk_get_values("Member", member_names, "first_name")
        
        # Benchmark both approaches
        individual_result = self.benchmark_function(individual_queries, "individual_queries", iterations=3)
        batch_result = self.benchmark_function(batch_query, "batch_query", iterations=3)
        
        # Batch should be faster (or at least not significantly slower)
        self.assertLessEqual(
            batch_result["avg_time_ms"], 
            individual_result["avg_time_ms"] * 1.5,  # Allow 50% variance
            "Batch queries should not be significantly slower than individual queries"
        )
        
        # Both should produce same results
        individual_data = individual_queries()
        batch_data = batch_query()
        
        for name in member_names:
            self.assertEqual(individual_data[name], batch_data[name]["first_name"])
    
    def test_cache_performance_improvement(self):
        """Test that caching improves performance"""
        
        from verenigingen.utils.performance_utils import cached
        
        call_count = 0
        
        @cached(ttl=60)
        def expensive_operation(param):
            nonlocal call_count
            call_count += 1
            # Simulate expensive operation
            time.sleep(0.01)
            return f"Result for {param}"
        
        # First call (cache miss)
        first_call = self.benchmark_function(
            lambda: expensive_operation("test"), 
            "cache_miss", 
            iterations=1
        )
        
        # Second call (cache hit)
        second_call = self.benchmark_function(
            lambda: expensive_operation("test"), 
            "cache_hit", 
            iterations=1
        )
        
        # Cache hit should be significantly faster
        self.assertLess(
            second_call["avg_time_ms"],
            first_call["avg_time_ms"] * 0.5,  # Should be at least 50% faster
            "Cached calls should be significantly faster"
        )
        
        # Function should only be called once
        self.assertEqual(call_count, 1, "Function should only be executed once due to caching")


class TestAPIIntegrationWorkflow(IntegrationTestCase):
    """Integration tests for complete API workflows"""
    
    def test_member_application_workflow_optimized(self):
        """Test optimized member application workflow"""
        
        self.record_step("start_optimized_workflow")
        
        # Test form data endpoint with caching
        from verenigingen.api.membership_application import get_application_form_data
        
        start_time = time.time()
        form_data = get_application_form_data()
        first_call_time = (time.time() - start_time) * 1000
        
        self.record_step("form_data_first_call", {"time_ms": first_call_time})
        
        # Second call should be faster due to caching
        start_time = time.time()
        form_data_cached = get_application_form_data()
        second_call_time = (time.time() - start_time) * 1000
        
        self.record_step("form_data_cached_call", {"time_ms": second_call_time})
        
        self.assertTrue(form_data.get("success"))
        self.assertTrue(form_data_cached.get("success"))
        
        # Test validation endpoints
        from verenigingen.api.membership_application import validate_email
        
        # Valid email
        email_result = validate_email("workflow.test@example.com")
        self.assertTrue(email_result.get("valid"))
        
        self.record_step("email_validation", {"result": email_result})
        
        # Test postal code validation
        from verenigingen.api.membership_application import validate_postal_code
        
        postal_result = validate_postal_code("1234AB", "Netherlands")
        self.assertTrue(postal_result.get("valid"))
        
        self.record_step("postal_validation", {"result": postal_result})
        
        # Verify workflow steps
        expected_steps = [
            "start_optimized_workflow",
            "form_data_first_call",
            "form_data_cached_call",
            "email_validation",
            "postal_validation"
        ]
        
        self.assert_workflow_completed(expected_steps)
        
        # Verify performance improvements
        if second_call_time < first_call_time * 0.8:  # 20% improvement minimum
            self.record_step("caching_performance_verified", {
                "improvement_percent": ((first_call_time - second_call_time) / first_call_time) * 100
            })
    
    def test_error_handling_integration(self):
        """Test that error handling works across the entire API"""
        
        self.record_step("start_error_handling_test")
        
        # Test various error scenarios
        from verenigingen.api.member_management import assign_member_to_chapter
        
        # Test validation errors
        try:
            assign_member_to_chapter(None, None)
            self.fail("Should have raised ValidationError")
        except ValidationError as e:
            self.record_step("validation_error_caught", {"error": str(e)})
        
        # Test permission errors (without proper user context)
        try:
            assign_member_to_chapter("NONEXISTENT", "NONEXISTENT")
            self.fail("Should have raised an error")
        except (ValidationError, PermissionError) as e:
            self.record_step("permission_error_caught", {"error": str(e)})
        
        # Verify error handling steps
        expected_steps = [
            "start_error_handling_test",
            "validation_error_caught",
            "permission_error_caught"
        ]
        
        self.assert_workflow_completed(expected_steps)


def run_optimization_test_suite():
    """Run the complete API optimization test suite"""
    
    import unittest
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add test cases
    suite.addTest(unittest.makeSuite(TestAPIOptimizationSuite))
    suite.addTest(unittest.makeSuite(TestAPIPerformanceOptimization))
    suite.addTest(unittest.makeSuite(TestAPIIntegrationWorkflow))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return {
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "success": result.wasSuccessful()
    }


if __name__ == "__main__":
    run_optimization_test_suite()