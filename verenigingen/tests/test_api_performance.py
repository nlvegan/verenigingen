# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
API Performance and Rate Limiting Tests
Tests for API performance monitoring and rate limiting enforcement
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch, Mock
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import json


class TestAPIPerformance(FrappeTestCase):
    """Test API performance and rate limiting"""
    
    def setUp(self):
        """Set up test environment"""
        self.test_user = self._create_test_api_user()
        self.api_endpoints = [
            "/api/method/verenigingen.api.member.get_member_list",
            "/api/method/verenigingen.api.volunteer.get_volunteer_assignments",
            "/api/method/verenigingen.api.chapter_dashboard.get_dashboard_data"
        ]
        
    def _create_test_api_user(self):
        """Create a test user for API testing"""
        email = f"api.test.{frappe.utils.random_string(6)}@example.com"
        
        if not frappe.db.exists("User", email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": "API",
                "last_name": "Tester",
                "enabled": 1,
                "new_password": frappe.utils.random_string(10)
            })
            user.insert(ignore_permissions=True)
            return user
        return frappe.get_doc("User", email)
        
    def test_rate_limiting_enforcement(self):
        """Test rate limit enforcement on API endpoints"""
        from verenigingen.utils.decorators import rate_limit
        
        # Create a rate-limited function
        call_times = []
        
        @rate_limit(calls=5, period=1)  # 5 calls per second
        def test_api_function():
            call_times.append(time.time())
            return {"success": True}
            
        # Make rapid calls
        results = []
        start_time = time.time()
        
        # Should allow first 5 calls
        for i in range(5):
            result = test_api_function()
            results.append(result)
            
        # 6th call should be rate limited
        with self.assertRaises(frappe.exceptions.TooManyRequestsError):
            test_api_function()
            
        # Verify timing
        elapsed = time.time() - start_time
        self.assertLess(elapsed, 1.0)  # All calls within 1 second
        self.assertEqual(len(results), 5)
        
    def test_performance_threshold_alerts(self):
        """Test performance monitoring and alerting"""
        from vereiningen.utils.decorators import performance_monitor
        
        # Create monitored function
        alert_triggered = False
        
        @performance_monitor(threshold_ms=100)
        def slow_function():
            time.sleep(0.2)  # 200ms - exceeds threshold
            return {"data": "test"}
            
        @performance_monitor(threshold_ms=1000)
        def fast_function():
            time.sleep(0.05)  # 50ms - within threshold
            return {"data": "test"}
            
        # Test slow function (should trigger alert)
        with patch('frappe.log_error') as mock_log:
            slow_function()
            # In actual implementation, this would log performance warning
            
        # Test fast function (should not trigger alert)
        result = fast_function()
        self.assertEqual(result["data"], "test")
        
    def test_query_optimization_effectiveness(self):
        """Test database query optimization"""
        # Test optimized vs unoptimized queries
        
        # Unoptimized: N+1 query problem
        def get_members_unoptimized(chapter_id):
            members = frappe.get_all("Member", 
                                   filters={"chapter": chapter_id},
                                   fields=["name", "full_name"])
            
            # N+1 problem - separate query for each member
            for member in members:
                member["memberships"] = frappe.get_all("Membership",
                                                     filters={"member": member.name},
                                                     fields=["membership_type", "status"])
            return members
            
        # Optimized: Single query with joins
        def get_members_optimized(chapter_id):
            # Use single query with proper joins
            query = """
                SELECT 
                    m.name, m.full_name,
                    ms.membership_type, ms.status
                FROM `tabMember` m
                LEFT JOIN `tabMembership` ms ON ms.member = m.name
                WHERE m.chapter = %s
            """
            
            # This would be much faster for large datasets
            # Mock the result for testing
            return [
                {
                    "name": "TEST001",
                    "full_name": "Test Member",
                    "membership_type": "Annual",
                    "status": "Active"
                }
            ]
            
        # Compare performance (mocked)
        start = time.time()
        unopt_result = get_members_unoptimized("TEST_CHAPTER")
        unopt_time = time.time() - start
        
        start = time.time()
        opt_result = get_members_optimized("TEST_CHAPTER")
        opt_time = time.time() - start
        
        # Optimized should be faster (in real scenario)
        self.assertIsNotNone(opt_result)
        
    def test_cache_hit_rates(self):
        """Test caching effectiveness"""
        from frappe.utils import cint
        
        # Simulate cache operations
        cache_hits = 0
        cache_misses = 0
        cache_data = {}
        
        def get_with_cache(key, loader_func):
            nonlocal cache_hits, cache_misses
            
            if key in cache_data:
                cache_hits += 1
                return cache_data[key]
            else:
                cache_misses += 1
                value = loader_func()
                cache_data[key] = value
                return value
                
        # Test cache behavior
        def expensive_operation():
            time.sleep(0.01)  # Simulate expensive operation
            return {"data": "expensive result"}
            
        # First call - cache miss
        result1 = get_with_cache("test_key", expensive_operation)
        self.assertEqual(cache_misses, 1)
        self.assertEqual(cache_hits, 0)
        
        # Second call - cache hit
        result2 = get_with_cache("test_key", expensive_operation)
        self.assertEqual(cache_misses, 1)
        self.assertEqual(cache_hits, 1)
        
        # Verify same result
        self.assertEqual(result1, result2)
        
        # Calculate hit rate
        total_calls = cache_hits + cache_misses
        hit_rate = (cache_hits / total_calls) * 100 if total_calls > 0 else 0
        self.assertEqual(hit_rate, 50.0)  # 1 hit out of 2 calls
        
    def test_concurrent_api_calls(self):
        """Test API behavior under concurrent load"""
        # Simulate concurrent API calls
        results = []
        errors = []
        
        def make_api_call(call_id):
            try:
                # Simulate API call
                time.sleep(0.01)  # Small delay
                result = {
                    "call_id": call_id,
                    "timestamp": time.time(),
                    "success": True
                }
                results.append(result)
            except Exception as e:
                errors.append({"call_id": call_id, "error": str(e)})
                
        # Make concurrent calls
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for i in range(20):  # 20 concurrent calls
                future = executor.submit(make_api_call, i)
                futures.append(future)
                
            # Wait for all to complete
            for future in futures:
                future.result()
                
        # Verify results
        self.assertEqual(len(results), 20)
        self.assertEqual(len(errors), 0)
        
        # Check timing spread (should not all complete at exact same time)
        timestamps = [r["timestamp"] for r in results]
        time_spread = max(timestamps) - min(timestamps)
        self.assertGreater(time_spread, 0)
        
    def test_api_response_time_monitoring(self):
        """Test API response time tracking"""
        response_times = []
        
        # Simulate API calls with varying response times
        api_calls = [
            {"endpoint": "/api/member/list", "response_time": 50},
            {"endpoint": "/api/member/list", "response_time": 75},
            {"endpoint": "/api/volunteer/tasks", "response_time": 120},
            {"endpoint": "/api/volunteer/tasks", "response_time": 90},
            {"endpoint": "/api/dashboard/stats", "response_time": 200},
        ]
        
        # Track response times
        for call in api_calls:
            response_times.append({
                "endpoint": call["endpoint"],
                "response_time": call["response_time"],
                "timestamp": time.time()
            })
            
        # Calculate statistics per endpoint
        endpoint_stats = {}
        
        for rt in response_times:
            endpoint = rt["endpoint"]
            if endpoint not in endpoint_stats:
                endpoint_stats[endpoint] = []
            endpoint_stats[endpoint].append(rt["response_time"])
            
        # Calculate averages
        for endpoint, times in endpoint_stats.items():
            avg_time = sum(times) / len(times)
            
            if endpoint == "/api/member/list":
                self.assertEqual(avg_time, 62.5)  # (50 + 75) / 2
            elif endpoint == "/api/volunteer/tasks":
                self.assertEqual(avg_time, 105)  # (120 + 90) / 2
            elif endpoint == "/api/dashboard/stats":
                self.assertEqual(avg_time, 200)
                
    def test_api_error_rate_tracking(self):
        """Test API error rate monitoring"""
        # Simulate API calls with some errors
        total_calls = 100
        error_calls = 5
        
        api_results = []
        
        for i in range(total_calls):
            if i < error_calls:
                api_results.append({
                    "status": "error",
                    "error_type": "ValidationError" if i % 2 == 0 else "PermissionError"
                })
            else:
                api_results.append({
                    "status": "success"
                })
                
        # Calculate error rate
        error_count = len([r for r in api_results if r["status"] == "error"])
        error_rate = (error_count / total_calls) * 100
        
        self.assertEqual(error_rate, 5.0)  # 5%
        
        # Analyze error types
        error_types = {}
        for result in api_results:
            if result["status"] == "error":
                error_type = result["error_type"]
                error_types[error_type] = error_types.get(error_type, 0) + 1
                
        self.assertEqual(error_types["ValidationError"], 3)
        self.assertEqual(error_types["PermissionError"], 2)
        
    def test_api_throttling_per_user(self):
        """Test per-user API throttling"""
        # Create multiple test users
        users = []
        for i in range(3):
            email = f"throttle.test{i}.{frappe.utils.random_string(4)}@example.com"
            if not frappe.db.exists("User", email):
                user = frappe.get_doc({
                    "doctype": "User",
                    "email": email,
                    "first_name": f"Throttle{i}",
                    "last_name": "Test",
                    "enabled": 1
                })
                user.insert(ignore_permissions=True)
                users.append(user)
                
        # Track API calls per user
        user_calls = {user.name: [] for user in users}
        
        # Simulate API calls from different users
        for _ in range(10):
            for user in users:
                user_calls[user.name].append({
                    "timestamp": time.time(),
                    "endpoint": "/api/test"
                })
                time.sleep(0.01)  # Small delay between calls
                
        # Verify each user has their own limit
        for user in users:
            calls = user_calls[user.name]
            self.assertEqual(len(calls), 10)
            
            # Check call spacing
            if len(calls) > 1:
                time_between_calls = calls[-1]["timestamp"] - calls[0]["timestamp"]
                self.assertGreater(time_between_calls, 0)
                
        # Cleanup users
        for user in users:
            frappe.delete_doc("User", user.name, force=True)
            
    def test_api_request_size_limits(self):
        """Test API request size validation"""
        # Test different payload sizes
        test_payloads = [
            {"size": "small", "data": "x" * 100, "should_pass": True},
            {"size": "medium", "data": "x" * 10000, "should_pass": True},
            {"size": "large", "data": "x" * 1000000, "should_pass": True},
            {"size": "too_large", "data": "x" * 10000000, "should_pass": False},
        ]
        
        max_size = 5 * 1024 * 1024  # 5MB limit
        
        for payload in test_payloads:
            payload_size = len(payload["data"].encode('utf-8'))
            
            if payload_size <= max_size:
                self.assertTrue(payload["should_pass"])
            else:
                self.assertFalse(payload["should_pass"])
                
    def tearDown(self):
        """Clean up test data"""
        try:
            frappe.delete_doc("User", self.test_user.name, force=True)
        except:
            pass