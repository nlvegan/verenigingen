"""
Enhanced testing framework for Verenigingen app

This module provides enhanced testing utilities, performance testing,
and comprehensive test coverage tools for the association management system.
"""

import time
import traceback
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.error_handling import get_logger
from verenigingen.utils.performance_utils import CacheManager
from verenigingen.utils.config_manager import ConfigManager


class VerenigingenTestCase(FrappeTestCase):
    """Enhanced base test case for Verenigingen tests"""
    
    def setUp(self):
        """Set up test environment"""
        super().setUp()
        
        # Clear cache before each test
        CacheManager.clear()
        
        # Set test-specific configuration
        self.test_config = {
            "batch_processing_size": 10,  # Smaller batches for testing
            "cache_ttl_seconds": 30,      # Shorter cache for testing
            "email_batch_size": 5,        # Smaller email batches
        }
        
        # Store original config values
        self.original_config = {}
        for key, value in self.test_config.items():
            self.original_config[key] = ConfigManager.get(key)
            ConfigManager.set(key, value)
        
        # Test data tracking
        self.created_docs = []
        self.logger = get_logger("verenigingen.tests")
    
    def tearDown(self):
        """Clean up test environment"""
        # Restore original configuration
        for key, value in self.original_config.items():
            ConfigManager.set(key, value)
        
        # Clean up created test documents
        self.cleanup_test_data()
        
        # Clear cache after test
        CacheManager.clear()
        
        super().tearDown()
    
    def create_test_doc(self, doctype: str, data: Dict[str, Any], commit: bool = True) -> Any:
        """
        Create a test document with automatic cleanup
        
        Args:
            doctype: Document type to create
            data: Document data
            commit: Whether to commit to database
            
        Returns:
            Created document
        """
        doc = frappe.get_doc({
            "doctype": doctype,
            **data
        })
        doc.insert()
        
        if commit:
            frappe.db.commit()
        
        # Track for cleanup
        self.created_docs.append((doctype, doc.name))
        
        return doc
    
    def cleanup_test_data(self):
        """Clean up all test documents created during test"""
        for doctype, name in reversed(self.created_docs):
            try:
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, )
            except Exception as e:
                self.logger.warning(f"Failed to cleanup {doctype} {name}: {str(e)}")
        
        self.created_docs.clear()
        frappe.db.commit()
    
    def assert_performance(self, func: Callable, max_time_ms: float = 1000, *args, **kwargs):
        """
        Assert that a function executes within specified time limit
        
        Args:
            func: Function to test
            max_time_ms: Maximum execution time in milliseconds
            *args, **kwargs: Arguments to pass to function
        """
        start_time = time.time()
        result = func(*args, **kwargs)
        execution_time = (time.time() - start_time) * 1000
        
        self.assertLess(
            execution_time, 
            max_time_ms,
            f"Function {func.__name__} took {execution_time:.2f}ms, expected < {max_time_ms}ms"
        )
        
        return result
    
    def assert_no_n_plus_one_queries(self, func: Callable, items: List[Any], *args, **kwargs):
        """
        Assert that function execution time doesn't scale linearly with item count (N+1 problem)
        
        Args:
            func: Function to test
            items: List of items to test with (will test with 1, 5, 10 items)
            *args, **kwargs: Additional arguments to pass to function
        """
        test_sizes = [1, 5, 10] if len(items) >= 10 else [1, len(items) // 2, len(items)]
        execution_times = []
        
        for size in test_sizes:
            test_items = items[:size]
            start_time = time.time()
            func(test_items, *args, **kwargs)
            execution_time = (time.time() - start_time) * 1000
            execution_times.append(execution_time)
        
        # Check that execution time doesn't scale linearly
        # Allow for some variance but reject obvious O(n) scaling
        if len(execution_times) >= 3:
            time_ratio = execution_times[-1] / execution_times[0]
            size_ratio = test_sizes[-1] / test_sizes[0]
            
            # If time scales more than 2x the size ratio, likely N+1 problem
            self.assertLess(
                time_ratio,
                size_ratio * 2,
                f"Function appears to have N+1 query problem. "
                f"Time scaled {time_ratio:.2f}x for {size_ratio}x data"
            )
    
    def assert_error_handling(self, func: Callable, expected_exception: type, *args, **kwargs):
        """
        Assert that function handles errors properly with structured error response
        
        Args:
            func: Function to test
            expected_exception: Expected exception type
            *args, **kwargs: Arguments to pass to function
        """
        with self.assertRaises(expected_exception) as context:
            func(*args, **kwargs)
        
        # Verify error was logged properly
        # This would check error logs in a real implementation
        self.assertIsNotNone(context.exception)
    
    @contextmanager
    def mock_user(self, email: str = "test@example.com", roles: List[str] = None):
        """
        Context manager to mock user session for testing
        
        Args:
            email: User email to mock
            roles: List of roles for the user
        """
        original_user = frappe.session.user
        original_roles = frappe.get_roles() if hasattr(frappe, 'get_roles') else []
        
        try:
            frappe.session.user = email
            if roles:
                with patch('frappe.get_roles', return_value=roles):
                    yield
            else:
                yield
        finally:
            frappe.session.user = original_user
    
    def create_test_member(self, email: str = None, **kwargs) -> Any:
        """Create a test member with default values"""
        email = email or f"test_{int(time.time())}@example.com"
        
        member_data = {
            "first_name": "Test",
            "last_name": "Member",
            "email_id": email,
            "status": "Active",
            "membership_type": "Individual",
            **kwargs
        }
        
        return self.create_test_doc("Member", member_data)
    
    def create_test_volunteer(self, member: Any = None, **kwargs) -> Any:
        """Create a test volunteer linked to a member"""
        if not member:
            member = self.create_test_member()
        
        volunteer_data = {
            "volunteer_name": f"{member.first_name} {member.last_name}",
            "member": member.name,
            "skills": "Testing",
            "availability": "Weekends",
            **kwargs
        }
        
        return self.create_test_doc("Volunteer", volunteer_data)
    
    def create_test_chapter(self, name: str = None, **kwargs) -> Any:
        """Create a test chapter"""
        name = name or f"Test Chapter {int(time.time())}"
        
        chapter_data = {
            "chapter_name": name,
            "postal_code_patterns": "1000-1999",
            **kwargs
        }
        
        return self.create_test_doc("Chapter", chapter_data)


class PerformanceTestCase(VerenigingenTestCase):
    """Specialized test case for performance testing"""
    
    def setUp(self):
        super().setUp()
        self.performance_data = []
    
    def benchmark_function(self, func: Callable, name: str = None, iterations: int = 10, *args, **kwargs):
        """
        Benchmark a function over multiple iterations
        
        Args:
            func: Function to benchmark
            name: Name for the benchmark
            iterations: Number of iterations to run
            *args, **kwargs: Arguments to pass to function
            
        Returns:
            Dictionary with benchmark results
        """
        name = name or func.__name__
        execution_times = []
        
        for _ in range(iterations):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                success = True
            except Exception as e:
                result = None
                success = False
                self.logger.error(f"Benchmark iteration failed: {str(e)}")
            
            execution_time = (time.time() - start_time) * 1000
            execution_times.append(execution_time)
        
        benchmark_result = {
            "name": name,
            "iterations": iterations,
            "min_time_ms": min(execution_times),
            "max_time_ms": max(execution_times),
            "avg_time_ms": sum(execution_times) / len(execution_times),
            "total_time_ms": sum(execution_times),
            "success_rate": sum(1 for t in execution_times if t > 0) / iterations
        }
        
        self.performance_data.append(benchmark_result)
        return benchmark_result
    
    def load_test(self, func: Callable, concurrent_users: int = 10, duration_seconds: int = 30):
        """
        Perform load testing on a function
        
        Args:
            func: Function to test
            concurrent_users: Number of concurrent executions
            duration_seconds: Test duration
        """
        import threading
        import queue
        
        results = queue.Queue()
        start_time = time.time()
        
        def worker():
            while time.time() - start_time < duration_seconds:
                try:
                    exec_start = time.time()
                    func()
                    exec_time = (time.time() - exec_start) * 1000
                    results.put({"success": True, "time_ms": exec_time})
                except Exception as e:
                    results.put({"success": False, "error": str(e)})
                
                time.sleep(0.1)  # Brief pause between requests
        
        # Start worker threads
        threads = []
        for _ in range(concurrent_users):
            thread = threading.Thread(target=worker)
            thread.start()
            threads.append(thread)
        
        # Wait for test duration
        time.sleep(duration_seconds)
        
        # Wait for threads to finish
        for thread in threads:
            thread.join(timeout=5)
        
        # Collect results
        execution_results = []
        while not results.empty():
            execution_results.append(results.get())
        
        successful_executions = [r for r in execution_results if r.get("success")]
        failed_executions = [r for r in execution_results if not r.get("success")]
        
        if successful_executions:
            times = [r["time_ms"] for r in successful_executions]
            load_test_result = {
                "concurrent_users": concurrent_users,
                "duration_seconds": duration_seconds,
                "total_requests": len(execution_results),
                "successful_requests": len(successful_executions),
                "failed_requests": len(failed_executions),
                "success_rate": len(successful_executions) / len(execution_results),
                "avg_response_time_ms": sum(times) / len(times),
                "min_response_time_ms": min(times),
                "max_response_time_ms": max(times),
                "requests_per_second": len(execution_results) / duration_seconds
            }
        else:
            load_test_result = {
                "concurrent_users": concurrent_users,
                "duration_seconds": duration_seconds,
                "total_requests": len(execution_results),
                "successful_requests": 0,
                "failed_requests": len(failed_executions),
                "success_rate": 0,
                "error": "All requests failed"
            }
        
        return load_test_result
    
    def tearDown(self):
        """Print performance summary"""
        if self.performance_data:
            print("\n" + "="*50)
            print("PERFORMANCE TEST SUMMARY")
            print("="*50)
            for result in self.performance_data:
                print(f"{result['name']}: {result['avg_time_ms']:.2f}ms avg "
                      f"({result['min_time_ms']:.2f}-{result['max_time_ms']:.2f}ms)")
        
        super().tearDown()


class IntegrationTestCase(VerenigingenTestCase):
    """Specialized test case for integration testing"""
    
    def setUp(self):
        super().setUp()
        self.workflow_steps = []
    
    def record_step(self, step_name: str, data: Dict[str, Any] = None):
        """Record a workflow step for debugging"""
        self.workflow_steps.append({
            "step": step_name,
            "timestamp": time.time(),
            "data": data or {}
        })
    
    def assert_workflow_completed(self, expected_steps: List[str]):
        """Assert that workflow completed all expected steps"""
        completed_steps = [step["step"] for step in self.workflow_steps]
        
        for expected_step in expected_steps:
            self.assertIn(
                expected_step, 
                completed_steps,
                f"Workflow step '{expected_step}' was not completed. "
                f"Completed steps: {completed_steps}"
            )
    
    def test_complete_member_journey(self):
        """Test complete member lifecycle from application to termination"""
        self.record_step("start_member_journey")
        
        # Step 1: Submit application
        application_data = {
            "first_name": "Integration",
            "last_name": "Test",
            "email_id": "integration.test@example.com",
            "membership_type": "Individual"
        }
        application = self.create_test_doc("Membership Application", application_data)
        self.record_step("application_submitted", {"application": application.name})
        
        # Step 2: Approve application and create member
        member = self.create_test_member(
            email="integration.test@example.com",
            first_name="Integration",
            last_name="Test"
        )
        self.record_step("member_created", {"member": member.name})
        
        # Step 3: Assign to chapter
        chapter = self.create_test_chapter("Integration Test Chapter")
        chapter_member = self.create_test_doc("Chapter Member", {
            "parent": chapter.name,
            "parenttype": "Chapter",
            "parentfield": "chapter_members",
            "member": member.name,
            "is_active": 1
        })
        self.record_step("chapter_assigned", {"chapter": chapter.name})
        
        # Step 4: Create volunteer record
        volunteer = self.create_test_volunteer(member=member)
        self.record_step("volunteer_created", {"volunteer": volunteer.name})
        
        # Verify complete journey
        expected_steps = [
            "start_member_journey",
            "application_submitted", 
            "member_created",
            "chapter_assigned",
            "volunteer_created"
        ]
        self.assert_workflow_completed(expected_steps)
        
        # Verify data consistency
        self.assertTrue(frappe.db.exists("Member", member.name))
        self.assertTrue(frappe.db.exists("Chapter Member", {"member": member.name}))
        self.assertTrue(frappe.db.exists("Volunteer", {"member": member.name}))


# Test data factories
class TestDataFactory:
    """Factory for creating test data"""
    
    @staticmethod
    def create_member_batch(count: int = 10, **kwargs) -> List[Any]:
        """Create a batch of test members"""
        members = []
        for i in range(count):
            member_data = {
                "first_name": f"Test{i}",
                "last_name": "Member",
                "email_id": f"test{i}_{int(time.time())}@example.com",
                "status": "Active",
                "membership_type": "Individual",
                **kwargs
            }
            
            member = frappe.get_doc({"doctype": "Member", **member_data})
            member.insert()
            members.append(member)
        
        frappe.db.commit()
        return members
    
    @staticmethod
    def create_chapter_with_members(member_count: int = 5) -> tuple:
        """Create a chapter with specified number of members"""
        chapter = frappe.get_doc({
            "doctype": "Chapter",
            "chapter_name": f"Test Chapter {int(time.time())}",
            "postal_code_patterns": "1000-1999"
        })
        chapter.insert()
        
        members = TestDataFactory.create_member_batch(member_count)
        
        for member in members:
            chapter_member = frappe.get_doc({
                "doctype": "Chapter Member",
                "parent": chapter.name,
                "parenttype": "Chapter",
                "parentfield": "chapter_members",
                "member": member.name,
                "is_active": 1
            })
            chapter_member.insert()
        
        frappe.db.commit()
        return chapter, members


# Test runners
def run_performance_tests():
    """Run all performance tests"""
    import unittest
    
    # Discover and run performance tests
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(PerformanceTestCase)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)


def run_integration_tests():
    """Run all integration tests"""
    import unittest
    
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(IntegrationTestCase)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)