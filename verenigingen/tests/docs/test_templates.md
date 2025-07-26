# Test Templates - Verenigingen Testing Infrastructure

This document provides ready-to-use templates for creating different types of tests using our sophisticated testing infrastructure.

## Template Index

1. [Basic Unit Test](#basic-unit-test)
2. [Integration Test](#integration-test)
3. [Edge Case Test](#edge-case-test)
4. [Performance Test](#performance-test)
5. [Security Test](#security-test)
6. [API Test](#api-test)
7. [Workflow Test](#workflow-test)
8. [Validation Test](#validation-test)

---

## Basic Unit Test

**File**: `test_[component]_[feature].py`

```python
"""
Test module for [Component] [Feature]
Tests basic functionality of [brief description]
"""

from verenigingen.tests.utils.base import VereningingenTestCase
import frappe


class Test[Component][Feature](VereningingenTestCase):
    """Test suite for [Component] [Feature] functionality"""
    
    @classmethod
    def setUpClass(cls):
        """One-time setup for entire test class"""
        super().setUpClass()
        # Add any class-level setup here
        
    def setUp(self):
        """Setup for each individual test"""
        super().setUp()
        # Add test-specific setup here
        
    def test_[feature]_happy_path(self):
        """Test normal successful scenario for [feature]"""
        # Arrange
        test_data = self._create_test_data()
        
        # Act
        result = self._perform_action(test_data)
        
        # Assert
        self.assertTrue(result.success)
        self.assertFieldEqual(result, "status", "completed")
        
    def test_[feature]_with_invalid_input(self):
        """Test [feature] with invalid input"""
        # Arrange
        invalid_data = self._create_invalid_data()
        
        # Act & Assert
        with self.assertRaisesRegex(frappe.ValidationError, "Expected error message"):
            self._perform_action(invalid_data)
            
    def test_[feature]_edge_case(self):
        """Test edge case: [describe the specific edge case]"""
        # Arrange
        edge_case_data = self._create_edge_case_data()
        
        # Act
        result = self._perform_action(edge_case_data)
        
        # Assert
        self.assertIsNotNone(result)
        # Add specific assertions for edge case
        
    def _create_test_data(self):
        """Helper method to create standard test data"""
        return self.create_test_member(
            first_name="Test",
            last_name="User",
            email="test.user@example.com"
        )
        
    def _create_invalid_data(self):
        """Helper method to create invalid test data"""
        # Return data that should cause validation errors
        pass
        
    def _create_edge_case_data(self):
        """Helper method to create edge case test data"""
        # Return data for edge case testing
        pass
        
    def _perform_action(self, data):
        """Helper method to perform the action being tested"""
        # Implement the actual functionality being tested
        pass
```

---

## Integration Test

**File**: `test_[component1]_[component2]_integration.py`

```python
"""
Integration test for [Component1] and [Component2]
Tests the interaction between [brief description]
"""

from verenigingen.tests.utils.base import VereningingenTestCase
import frappe


class Test[Component1][Component2]Integration(VereningingenTestCase):
    """Test suite for [Component1] and [Component2] integration"""
    
    def test_end_to_end_workflow(self):
        """Test complete workflow from [start] to [end]"""
        # Step 1: Create initial data
        member = self.create_test_member()
        chapter = self.create_test_chapter()
        
        # Step 2: Perform first action
        membership = self.create_test_membership(
            member=member.name,
            chapter=chapter.name
        )
        
        # Step 3: Verify intermediate state
        self.assertDocumentExists("Membership", membership.name)
        self.assertFieldEqual(membership, "status", "Active")
        
        # Step 4: Perform second action
        volunteer = self.create_test_volunteer(member=member.name)
        
        # Step 5: Verify final state and relationships
        self.assertDocumentLinked(member, volunteer, "member")
        self.assertFieldEqual(volunteer, "status", "Active")
        
    def test_data_synchronization(self):
        """Test data sync between [Component1] and [Component2]"""
        # Create test data
        source_doc = self.create_test_member()
        
        # Trigger synchronization
        sync_result = self._trigger_sync(source_doc)
        
        # Verify sync results
        self.assertTrue(sync_result.success)
        
        # Verify target data was created/updated
        target_doc = frappe.get_doc("TargetDocType", sync_result.target_id)
        self.assertFieldEqual(target_doc, "synced_field", source_doc.source_field)
        
    def test_cross_component_validation(self):
        """Test validation that spans multiple components"""
        # Create related documents
        member = self.create_test_member()
        existing_membership = self.create_test_membership(member=member.name)
        
        # Test cross-component validation
        with self.assertValidationError("Member already has active membership"):
            duplicate_membership = self.create_test_membership(member=member.name)
            
    def _trigger_sync(self, source_doc):
        """Helper method to trigger synchronization"""
        # Implement sync trigger logic
        pass
```

---

## Edge Case Test

**File**: `test_[component]_edge_cases.py`

```python
"""
Edge case tests for [Component]
Tests boundary conditions, error scenarios, and unusual data combinations
"""

from verenigingen.tests.utils.base import VereningingenTestCase
import frappe


class Test[Component]EdgeCases(VereningingenTestCase):
    """Comprehensive edge case testing for [Component]"""
    
    def test_boundary_values(self):
        """Test with boundary values (min/max limits)"""
        # Test minimum boundary
        min_data = self.create_test_member(birth_date="1900-01-01")  # Very old
        result = self._process_member(min_data)
        self.assertTrue(result.success)
        
        # Test maximum boundary  
        max_data = self.create_test_member(birth_date="2024-12-31")  # Very young
        result = self._process_member(max_data)
        self.assertTrue(result.success)
        
    def test_empty_and_null_values(self):
        """Test handling of empty and null values"""
        # Test empty string
        with self.assertValidationError("Field cannot be empty"):
            self.create_test_member(first_name="")
            
        # Test None values
        with self.assertValidationError("Field is required"):
            self.create_test_member(first_name=None)
            
    def test_special_characters(self):
        """Test handling of special characters and unicode"""
        special_chars_member = self.create_test_member(
            first_name="José María",
            last_name="O'Connor-Smith",
            email="josé.maría@test-domain.com"
        )
        
        self.assertFieldEqual(special_chars_member, "first_name", "José María")
        
    def test_very_long_inputs(self):
        """Test handling of extremely long inputs"""
        long_name = "A" * 1000  # Very long name
        
        with self.assertValidationError("Name too long"):
            self.create_test_member(first_name=long_name)
            
    def test_concurrent_operations(self):
        """Test handling of concurrent operations"""
        member = self.create_test_member()
        
        # Simulate concurrent modifications
        doc1 = frappe.get_doc("Member", member.name)
        doc2 = frappe.get_doc("Member", member.name)
        
        # Modify both concurrently
        doc1.first_name = "Updated1"
        doc2.first_name = "Updated2"
        
        doc1.save()
        
        # Second save should handle conflict appropriately
        with self.assertRaisesRegex(frappe.TimestampMismatchError, "Document has been modified"):
            doc2.save()
            
    def test_data_corruption_scenarios(self):
        """Test handling of corrupted or inconsistent data"""
        # Create member with controlled test data
        member = self.create_test_member()
        self.clear_member_auto_schedules(member.name)
        
        # Create conflicting schedules manually
        schedule1 = self.create_controlled_dues_schedule(
            member.name, "Monthly", 25.0,
            start_date="2024-01-01"
        )
        schedule2 = self.create_controlled_dues_schedule(
            member.name, "Annual", 300.0,
            start_date="2024-01-15"  # Overlapping period
        )
        
        # Test system's ability to detect and handle conflicts
        conflict_check = self._check_schedule_conflicts(member.name)
        self.assertTrue(conflict_check["has_conflicts"])
        self.assertEqual(len(conflict_check["conflicts"]), 1)
        
    def test_resource_exhaustion(self):
        """Test behavior under resource constraints"""
        # Test with large data sets
        large_member_list = [
            self.create_test_member(email=f"member{i}@example.com") 
            for i in range(100)
        ]
        
        # Monitor performance with large dataset
        with self.assertQueryCount(200):  # Should remain efficient
            result = self._process_bulk_members(large_member_list)
            
        self.assertEqual(len(result["processed"]), 100)
        
    def _process_member(self, member):
        """Helper method to process member"""
        # Implement processing logic
        return {"success": True}
        
    def _check_schedule_conflicts(self, member_name):
        """Helper method to check schedule conflicts"""
        # Implement conflict detection logic
        return {"has_conflicts": True, "conflicts": [{"type": "overlap"}]}
        
    def _process_bulk_members(self, members):
        """Helper method to process bulk members"""
        # Implement bulk processing logic
        return {"processed": members}
```

---

## Performance Test

**File**: `test_[component]_performance.py`

```python
"""
Performance tests for [Component]
Tests execution speed, query efficiency, and scalability
"""

from verenigingen.tests.utils.base import VereningingenTestCase
import time
import frappe


class Test[Component]Performance(VereningingenTestCase):
    """Performance testing for [Component]"""
    
    def test_single_operation_performance(self):
        """Test performance of single operation"""
        member = self.create_test_member()
        
        # Test single operation performance
        with self.assertMaxExecutionTime(0.1):  # Should complete in < 100ms
            with self.assertQueryCount(5):  # Should use minimal queries
                result = self._perform_single_operation(member)
                
        self.assertTrue(result.success)
        
    def test_bulk_operation_performance(self):
        """Test performance of bulk operations"""
        # Create test data
        members = [
            self.create_test_member(email=f"bulk{i}@example.com")
            for i in range(50)
        ]
        
        # Test bulk operation performance
        start_time = time.time()
        
        with self.assertQueryCount(100):  # Should batch queries efficiently
            result = self._perform_bulk_operation(members)
            
        duration = time.time() - start_time
        
        # Performance assertions
        self.assertLess(duration, 2.0)  # Should complete in < 2 seconds
        self.assertEqual(len(result["processed"]), 50)
        
        # Verify performance metrics
        avg_time_per_item = duration / len(members)
        self.assertLess(avg_time_per_item, 0.04)  # < 40ms per item
        
    def test_scalability_with_large_dataset(self):
        """Test scalability with increasingly large datasets"""
        dataset_sizes = [10, 50, 100, 200]
        performance_metrics = []
        
        for size in dataset_sizes:
            # Create dataset
            members = [
                self.create_test_member(email=f"scale{size}_{i}@example.com")
                for i in range(size)
            ]
            
            # Measure performance
            start_time = time.time()
            initial_queries = self._get_query_count()
            
            result = self._perform_bulk_operation(members)
            
            duration = time.time() - start_time
            query_count = self._get_query_count() - initial_queries
            
            performance_metrics.append({
                "size": size,
                "duration": duration,
                "queries": query_count,
                "time_per_item": duration / size,
                "queries_per_item": query_count / size
            })
            
        # Analyze scalability
        self._assert_linear_scalability(performance_metrics)
        
    def test_memory_usage(self):
        """Test memory efficiency"""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        # Create large dataset
        large_dataset = [
            self.create_test_member(email=f"memory{i}@example.com")
            for i in range(100)
        ]
        
        # Process dataset
        result = self._perform_bulk_operation(large_dataset)
        
        # Check memory usage
        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory
        
        # Memory should not increase excessively
        max_allowed_increase = 50 * 1024 * 1024  # 50MB
        self.assertLess(memory_increase, max_allowed_increase)
        
    def test_database_query_optimization(self):
        """Test database query efficiency"""
        members = [self.create_test_member() for _ in range(20)]
        
        # Test N+1 query prevention
        with self.assertQueryCount(5):  # Should batch queries, not do N+1
            results = []
            for member in members:
                # This should use cached/batched queries
                member_data = self._get_member_with_relationships(member.name)
                results.append(member_data)
                
        self.assertEqual(len(results), 20)
        
    def _perform_single_operation(self, member):
        """Helper method for single operation"""
        # Implement single operation logic
        return {"success": True}
        
    def _perform_bulk_operation(self, members):
        """Helper method for bulk operation"""
        # Implement bulk operation logic
        return {"processed": members}
        
    def _get_query_count(self):
        """Helper method to get current query count"""
        return getattr(frappe.db, 'debug_queries', 0)
        
    def _assert_linear_scalability(self, metrics):
        """Helper method to assert linear scalability"""
        # Check that time/queries per item remain relatively constant
        times_per_item = [m["time_per_item"] for m in metrics]
        queries_per_item = [m["queries_per_item"] for m in metrics]
        
        # Time per item should not increase dramatically
        self.assertLess(max(times_per_item) / min(times_per_item), 3.0)
        
        # Queries per item should remain constant (or improve with batching)
        self.assertLess(max(queries_per_item) / min(queries_per_item), 2.0)
        
    def _get_member_with_relationships(self, member_name):
        """Helper method to get member with relationships"""
        # Implement relationship loading logic
        return {"name": member_name, "relationships": []}
```

---

## Security Test

**File**: `test_[component]_security.py`

```python
"""
Security tests for [Component]
Tests permissions, access control, data validation, and security vulnerabilities
"""

from verenigingen.tests.utils.base import VereningingenTestCase
import frappe


class Test[Component]Security(VereningingenTestCase):
    """Security testing for [Component]"""
    
    def test_permission_enforcement(self):
        """Test role-based permission enforcement"""
        # Create test data
        member = self.create_test_member()
        
        # Test with different user roles
        with self.set_user("member@example.com"):  # Regular member
            # Should have read access to own data
            own_data = self._get_member_data(member.name)
            self.assertIsNotNone(own_data)
            
            # Should NOT have admin access
            with self.assertRaises(frappe.PermissionError):
                self._perform_admin_action(member.name)
                
        with self.set_user("admin@example.com"):  # Admin user
            # Should have full access
            admin_data = self._get_member_data(member.name)
            self.assertIsNotNone(admin_data)
            
            result = self._perform_admin_action(member.name)
            self.assertTrue(result.success)
            
    def test_data_access_isolation(self):
        """Test that users can only access authorized data"""
        # Create test data for different chapters
        chapter1 = self.create_test_chapter(chapter_name="Chapter 1")
        chapter2 = self.create_test_chapter(chapter_name="Chapter 2")
        
        member1 = self.create_test_member(chapter=chapter1.name)
        member2 = self.create_test_member(chapter=chapter2.name)
        
        # Test chapter isolation
        with self.set_user("chapter1.admin@example.com"):
            # Should access chapter1 data
            data1 = self._get_chapter_members(chapter1.name)
            self.assertIn(member1.name, [m.name for m in data1])
            
            # Should NOT access chapter2 data
            data2 = self._get_chapter_members(chapter2.name)
            self.assertEqual(len(data2), 0)  # No access
            
    def test_input_validation_security(self):
        """Test security-focused input validation"""
        # Test SQL injection prevention
        malicious_input = "'; DROP TABLE tabMember; --"
        
        with self.assertValidationError("Invalid characters"):
            self.create_test_member(first_name=malicious_input)
            
        # Test XSS prevention
        xss_input = "<script>alert('xss')</script>"
        
        with self.assertValidationError("Invalid characters"):
            self.create_test_member(first_name=xss_input)
            
    def test_authentication_bypass_prevention(self):
        """Test prevention of authentication bypass"""
        member = self.create_test_member()
        
        # Test direct access without authentication
        frappe.session.user = None  # Simulate unauthenticated state
        
        with self.assertRaises(frappe.AuthenticationError):
            self._get_member_data(member.name)
            
        # Restore authentication for cleanup
        frappe.session.user = "Administrator"
        
    def test_csrf_protection(self):
        """Test CSRF protection on state-changing operations"""
        member = self.create_test_member()
        
        # Test POST operation without CSRF token
        with self.assertRaises(frappe.CSRFTokenError):
            self._perform_state_changing_operation(member.name, csrf_token=None)
            
        # Test with valid CSRF token
        valid_token = frappe.sessions.get_csrf_token()
        result = self._perform_state_changing_operation(member.name, csrf_token=valid_token)
        self.assertTrue(result.success)
        
    def test_rate_limiting(self):
        """Test rate limiting on sensitive operations"""
        member = self.create_test_member()
        
        # Perform multiple rapid requests
        for i in range(10):
            try:
                self._perform_rate_limited_operation(member.name)
            except frappe.RateLimitExceededError:
                # Rate limiting should kick in before 10 requests
                self.assertGreater(i, 3)  # Should allow at least 3 requests
                break
        else:
            self.fail("Rate limiting did not activate")
            
    def test_sensitive_data_exposure(self):
        """Test that sensitive data is not exposed inappropriately"""
        member = self.create_test_member()
        
        # Get member data through API
        api_response = self._get_member_api_response(member.name)
        
        # Sensitive fields should not be exposed
        sensitive_fields = ["password", "reset_token", "session_id"]
        for field in sensitive_fields:
            self.assertNotIn(field, api_response)
            
    def test_file_upload_security(self):
        """Test file upload security"""
        member = self.create_test_member()
        
        # Test malicious file upload prevention
        malicious_files = [
            {"name": "test.php", "content": "<?php system($_GET['cmd']); ?>"},
            {"name": "test.exe", "content": "executable content"},
            {"name": "../../../etc/passwd", "content": "path traversal attempt"}
        ]
        
        for file_data in malicious_files:
            with self.assertValidationError("File type not allowed"):
                self._upload_member_file(member.name, file_data)
                
    def _get_member_data(self, member_name):
        """Helper method to get member data"""
        # Implement data retrieval logic
        return frappe.get_doc("Member", member_name)
        
    def _perform_admin_action(self, member_name):
        """Helper method for admin-only actions"""
        # Implement admin action logic
        return {"success": True}
        
    def _get_chapter_members(self, chapter_name):
        """Helper method to get chapter members"""
        # Implement chapter member retrieval with permission checks
        return frappe.get_all("Member", filters={"chapter": chapter_name})
        
    def _perform_state_changing_operation(self, member_name, csrf_token=None):
        """Helper method for CSRF-protected operations"""
        # Implement state-changing operation with CSRF protection
        if not csrf_token:
            raise frappe.CSRFTokenError("CSRF token required")
        return {"success": True}
        
    def _perform_rate_limited_operation(self, member_name):
        """Helper method for rate-limited operations"""
        # Implement rate-limited operation
        # This would check against rate limiting logic
        pass
        
    def _get_member_api_response(self, member_name):
        """Helper method to get API response"""
        # Implement API response logic
        return {"name": member_name, "first_name": "Test"}
        
    def _upload_member_file(self, member_name, file_data):
        """Helper method for file upload"""
        # Implement file upload logic with security checks
        if file_data["name"].endswith((".php", ".exe")) or ".." in file_data["name"]:
            raise frappe.ValidationError("File type not allowed")
```

---

## API Test

**File**: `test_[component]_api.py`

```python
"""
API tests for [Component]
Tests REST API endpoints, request/response handling, and API contracts
"""

from verenigingen.tests.utils.base import VereningingenTestCase
import frappe
import json


class Test[Component]API(VereningingenTestCase):
    """API testing for [Component]"""
    
    def setUp(self):
        """Setup for each API test"""
        super().setUp()
        self.api_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._get_test_token()}"
        }
        
    def test_api_get_endpoint(self):
        """Test GET API endpoint"""
        # Create test data
        member = self.create_test_member()
        
        # Test API call
        response = self._api_get(f"/api/resource/Member/{member.name}")
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], member.name)
        self.assertEqual(data["first_name"], member.first_name)
        
    def test_api_post_endpoint(self):
        """Test POST API endpoint"""
        # Prepare test data
        member_data = {
            "first_name": "API",
            "last_name": "Test",
            "email": "api.test@example.com"
        }
        
        # Test API call
        response = self._api_post("/api/resource/Member", member_data)
        
        # Verify response
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("name", data)
        
        # Verify data was created
        created_member = frappe.get_doc("Member", data["name"])
        self.assertEqual(created_member.first_name, "API")
        
        # Track for cleanup
        self.track_doc("Member", data["name"])
        
    def test_api_put_endpoint(self):
        """Test PUT API endpoint"""
        # Create test data
        member = self.create_test_member()
        
        # Prepare update data
        update_data = {
            "first_name": "Updated",
            "last_name": "Name"
        }
        
        # Test API call
        response = self._api_put(f"/api/resource/Member/{member.name}", update_data)
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        
        # Verify data was updated
        updated_member = frappe.get_doc("Member", member.name)
        self.assertEqual(updated_member.first_name, "Updated")
        
    def test_api_delete_endpoint(self):
        """Test DELETE API endpoint"""
        # Create test data
        member = self.create_test_member()
        member_name = member.name
        
        # Test API call
        response = self._api_delete(f"/api/resource/Member/{member_name}")
        
        # Verify response
        self.assertEqual(response.status_code, 204)
        
        # Verify data was deleted
        self.assertFalse(frappe.db.exists("Member", member_name))
        
    def test_api_validation_errors(self):
        """Test API validation error handling"""
        # Test missing required fields
        invalid_data = {"last_name": "Test"}  # Missing required first_name
        
        response = self._api_post("/api/resource/Member", invalid_data)
        
        # Verify error response
        self.assertEqual(response.status_code, 400)
        error_data = response.json()
        self.assertIn("error", error_data)
        self.assertIn("first_name", error_data["error"]["message"])
        
    def test_api_authentication_required(self):
        """Test API authentication requirements"""
        member = self.create_test_member()
        
        # Test without authentication
        response = self._api_get_unauthenticated(f"/api/resource/Member/{member.name}")
        
        # Verify authentication required
        self.assertEqual(response.status_code, 401)
        
    def test_api_permission_enforcement(self):
        """Test API permission enforcement"""
        member = self.create_test_member()
        
        # Test with limited permission user
        limited_token = self._get_limited_permission_token()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {limited_token}"
        }
        
        response = self._api_delete_with_headers(f"/api/resource/Member/{member.name}", headers)
        
        # Verify permission denied
        self.assertEqual(response.status_code, 403)
        
    def test_api_response_format(self):
        """Test API response format consistency"""
        member = self.create_test_member()
        
        response = self._api_get(f"/api/resource/Member/{member.name}")
        data = response.json()
        
        # Verify response structure
        required_fields = ["name", "creation", "modified", "owner"]
        for field in required_fields:
            self.assertIn(field, data)
            
        # Verify data types
        self.assertIsInstance(data["name"], str)
        self.assertIsInstance(data["creation"], str)
        
    def test_api_pagination(self):
        """Test API pagination"""
        # Create multiple test records
        members = [
            self.create_test_member(email=f"page{i}@example.com")
            for i in range(25)
        ]
        
        # Test pagination
        response = self._api_get("/api/resource/Member?limit=10&start=0")
        
        # Verify pagination
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertLessEqual(len(data["data"]), 10)
        self.assertIn("total_count", data)
        
    def test_api_filtering(self):
        """Test API filtering capabilities"""
        # Create test data with different attributes
        active_member = self.create_test_member(status="Active")
        inactive_member = self.create_test_member(status="Inactive")
        
        # Test filtering
        response = self._api_get("/api/resource/Member?filters=[[\"status\",\"=\",\"Active\"]]")
        
        # Verify filtering
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        member_names = [item["name"] for item in data["data"]]
        self.assertIn(active_member.name, member_names)
        self.assertNotIn(inactive_member.name, member_names)
        
    def _get_test_token(self):
        """Helper method to get test authentication token"""
        # Implement token generation logic
        return "test_token_123"
        
    def _get_limited_permission_token(self):
        """Helper method to get limited permission token"""
        # Implement limited token generation logic
        return "limited_token_456"
        
    def _api_get(self, endpoint):
        """Helper method for GET requests"""
        # Implement API GET request logic
        class MockResponse:
            status_code = 200
            def json(self):
                return {"name": "test", "first_name": "Test"}
        return MockResponse()
        
    def _api_post(self, endpoint, data):
        """Helper method for POST requests"""
        # Implement API POST request logic
        class MockResponse:
            status_code = 201
            def json(self):
                return {"name": "new_member_id"}
        return MockResponse()
        
    def _api_put(self, endpoint, data):
        """Helper method for PUT requests"""
        # Implement API PUT request logic
        class MockResponse:
            status_code = 200
            def json(self):
                return {"success": True}
        return MockResponse()
        
    def _api_delete(self, endpoint):
        """Helper method for DELETE requests"""
        # Implement API DELETE request logic
        class MockResponse:
            status_code = 204
        return MockResponse()
        
    def _api_get_unauthenticated(self, endpoint):
        """Helper method for unauthenticated requests"""
        # Implement unauthenticated request logic
        class MockResponse:
            status_code = 401
        return MockResponse()
        
    def _api_delete_with_headers(self, endpoint, headers):
        """Helper method for DELETE with custom headers"""
        # Implement DELETE with headers logic
        class MockResponse:
            status_code = 403
        return MockResponse()
```

---

## Workflow Test

**File**: `test_[workflow_name]_workflow.py`

```python
"""
Workflow test for [Workflow Name]
Tests complete business workflow from start to finish
"""

from verenigingen.tests.utils.base import VereningingenTestCase
import frappe


class Test[WorkflowName]Workflow(VereningingenTestCase):
    """Test suite for [Workflow Name] complete workflow"""
    
    def test_complete_workflow_happy_path(self):
        """Test complete workflow under normal conditions"""
        # Phase 1: Initial setup
        chapter = self.create_test_chapter()
        
        # Phase 2: Application submission
        application_data = {
            "first_name": "Workflow",
            "last_name": "Test",
            "email": "workflow.test@example.com",
            "chapter": chapter.name
        }
        
        application = self.create_membership_application(**application_data)
        self.assertFieldEqual(application, "status", "Pending")
        
        # Phase 3: Application review
        review_result = self._review_application(application, "approved")
        self.assertTrue(review_result.success)
        
        # Phase 4: Member creation
        member = self._create_member_from_application(application)
        self.assertIsNotNone(member)
        self.assertFieldEqual(member, "status", "Active")
        
        # Phase 5: Membership activation
        membership = self._activate_membership(member, chapter)
        self.assertFieldEqual(membership, "status", "Active")
        
        # Phase 6: Initial payment setup
        payment_setup = self._setup_initial_payment(member)
        self.assertTrue(payment_setup.success)
        
        # Phase 7: Verify workflow completion
        self._verify_workflow_completion(member, application, membership)
        
    def test_workflow_with_rejection(self):
        """Test workflow when application is rejected"""
        # Setup
        application = self.create_membership_application()
        
        # Reject application
        review_result = self._review_application(application, "rejected")
        self.assertTrue(review_result.success)
        
        # Verify rejection handling
        updated_application = frappe.get_doc("Membership Application", application.name)
        self.assertFieldEqual(updated_application, "status", "Rejected")
        
        # Verify no member was created
        members = frappe.get_all("Member", filters={"email": application.email})
        self.assertEqual(len(members), 0)
        
    def test_workflow_with_interruption(self):
        """Test workflow recovery after interruption"""
        # Start workflow
        application = self.create_membership_application()
        
        # Simulate interruption after partial processing
        member = self._create_member_from_application(application)
        
        # Simulate system interruption (member created but workflow incomplete)
        # ... system restart ...
        
        # Resume workflow
        recovery_result = self._resume_workflow_from_interruption(member.name)
        self.assertTrue(recovery_result.success)
        
        # Verify workflow completed properly
        membership = frappe.get_value("Membership", {"member": member.name})
        self.assertIsNotNone(membership)
        
    def test_workflow_with_validation_errors(self):
        """Test workflow error handling"""
        # Create application with data that will cause validation errors later
        application = self.create_membership_application(
            email="invalid.email.format"  # Invalid email for later validation
        )
        
        # Attempt workflow progression
        with self.assertValidationError("Invalid email format"):
            self._review_application(application, "approved")
            
    def test_parallel_workflow_instances(self):
        """Test handling of multiple concurrent workflow instances"""
        # Create multiple applications
        applications = [
            self.create_membership_application(email=f"parallel{i}@example.com")
            for i in range(5)
        ]
        
        # Process all applications concurrently
        results = []
        for app in applications:
            result = self._process_application_async(app)
            results.append(result)
            
        # Verify all processed successfully
        for result in results:
            self.assertTrue(result.success)
            
        # Verify no data corruption
        for app in applications:
            member = frappe.get_value("Member", {"email": app.email})
            self.assertIsNotNone(member)
            
    def test_workflow_rollback(self):
        """Test workflow rollback on error"""
        application = self.create_membership_application()
        
        # Start workflow
        member = self._create_member_from_application(application)
        
        # Simulate error during membership creation
        with self.assertRaises(Exception):
            self._activate_membership_with_error(member)
            
        # Verify rollback occurred
        # Member should be cleaned up
        self.assertFalse(frappe.db.exists("Member", member.name))
        
        # Application should be reset to pending
        updated_app = frappe.get_doc("Membership Application", application.name)
        self.assertFieldEqual(updated_app, "status", "Pending")
        
    def test_workflow_performance(self):
        """Test workflow performance under load"""
        # Create test applications
        applications = [
            self.create_membership_application(email=f"perf{i}@example.com")
            for i in range(20)
        ]
        
        # Process workflows with performance monitoring
        with self.assertMaxExecutionTime(10.0):  # Should complete in < 10 seconds
            with self.assertQueryCount(200):  # Should be query-efficient
                results = [self._process_complete_workflow(app) for app in applications]
                
        # Verify all completed successfully
        successful_results = [r for r in results if r.success]
        self.assertEqual(len(successful_results), 20)
        
    def _review_application(self, application, decision):
        """Helper method to review application"""
        # Implement application review logic
        application.status = decision.title()
        application.save()
        return frappe._dict({"success": True})
        
    def _create_member_from_application(self, application):
        """Helper method to create member from application"""
        # Implement member creation logic
        member = self.create_test_member(
            first_name=application.first_name,
            last_name=application.last_name,
            email=application.email
        )
        return member
        
    def _activate_membership(self, member, chapter):
        """Helper method to activate membership"""
        # Implement membership activation logic
        membership = self.create_test_membership(
            member=member.name,
            chapter=chapter.name
        )
        return membership
        
    def _setup_initial_payment(self, member):
        """Helper method to setup initial payment"""
        # Implement payment setup logic
        return frappe._dict({"success": True})
        
    def _verify_workflow_completion(self, member, application, membership):
        """Helper method to verify workflow completion"""
        # Verify all components are properly linked and configured
        self.assertFieldEqual(member, "status", "Active")
        self.assertFieldEqual(membership, "member", member.name)
        
        # Verify application is closed
        updated_app = frappe.get_doc("Membership Application", application.name)
        self.assertFieldEqual(updated_app, "status", "Approved")
        
    def _resume_workflow_from_interruption(self, member_name):
        """Helper method to resume interrupted workflow"""
        # Implement workflow recovery logic
        return frappe._dict({"success": True})
        
    def _process_application_async(self, application):
        """Helper method for async application processing"""
        # Implement async processing logic
        return frappe._dict({"success": True})
        
    def _activate_membership_with_error(self, member):
        """Helper method that simulates membership activation error"""
        # Implement error simulation
        raise Exception("Simulated membership activation error")
        
    def _process_complete_workflow(self, application):
        """Helper method to process complete workflow"""
        # Implement complete workflow processing
        return frappe._dict({"success": True})
```

---

## Validation Test

**File**: `test_[component]_validation.py`

```python
"""
Validation tests for [Component]
Tests all validation rules, business constraints, and data integrity checks
"""

from verenigingen.tests.utils.base import VereningingenTestCase
import frappe


class Test[Component]Validation(VereningingenTestCase):
    """Comprehensive validation testing for [Component]"""
    
    def test_required_field_validation(self):
        """Test required field validation"""
        # Test missing required fields
        required_fields = ["first_name", "last_name", "email"]
        
        for field in required_fields:
            with self.subTest(field=field):
                with self.assertValidationError(f"{field} is required"):
                    member_data = self._get_valid_member_data()
                    del member_data[field]  # Remove required field
                    self._create_member_with_validation(member_data)
                    
    def test_field_format_validation(self):
        """Test field format validation"""
        # Test email format validation
        invalid_emails = [
            "invalid.email",
            "test@",
            "@example.com",
            "test..test@example.com",
            "test@example..com"
        ]
        
        for email in invalid_emails:
            with self.subTest(email=email):
                with self.assertValidationError("Invalid email format"):
                    self.create_test_member(email=email)
                    
    def test_business_rule_validation(self):
        """Test business rule validation"""
        # Test unique email constraint
        email = "unique.test@example.com"
        member1 = self.create_test_member(email=email)
        
        with self.assertValidationError("Email already exists"):
            member2 = self.create_test_member(email=email)
            
    def test_data_integrity_validation(self):
        """Test data integrity and consistency validation"""
        # Create member with membership
        member = self.create_test_member()
        membership = self.create_test_membership(member=member.name)
        
        # Test cascade validation - cannot delete member with active membership
        with self.assertValidationError("Cannot delete member with active membership"):
            frappe.delete_doc("Member", member.name)
            
    def test_date_validation(self):
        """Test date field validation"""
        # Test invalid date formats
        invalid_dates = [
            "invalid-date",
            "2024-13-01",  # Invalid month
            "2024-02-30",  # Invalid day for February
            "2024/02/15",  # Wrong format
        ]
        
        for date in invalid_dates:
            with self.subTest(date=date):
                with self.assertValidationError("Invalid date"):
                    self.create_test_member(birth_date=date)
                    
        # Test logical date validation
        future_date = "2050-01-01"
        with self.assertValidationError("Birth date cannot be in the future"):
            self.create_test_member(birth_date=future_date)
            
    def test_numeric_validation(self):
        """Test numeric field validation"""
        # Test negative values where not allowed
        with self.assertValidationError("Amount cannot be negative"):
            self.create_controlled_dues_schedule(
                "test_member", "Monthly", -25.0  # Negative amount
            )
            
        # Test zero values where not allowed
        with self.assertValidationError("Amount must be greater than zero"):
            self.create_controlled_dues_schedule(
                "test_member", "Monthly", 0.0  # Zero amount
            )
            
    def test_string_length_validation(self):
        """Test string length validation"""
        # Test maximum length constraints
        long_name = "A" * 200  # Assuming max length is 100
        
        with self.assertValidationError("Name too long"):
            self.create_test_member(first_name=long_name)
            
        # Test minimum length constraints
        short_name = "A"  # Assuming min length is 2
        
        with self.assertValidationError("Name too short"):
            self.create_test_member(first_name=short_name)
            
    def test_selection_field_validation(self):
        """Test selection field validation"""
        # Test invalid selection values
        invalid_status = "InvalidStatus"
        
        with self.assertValidationError("Invalid status"):
            member = self.create_test_member()
            member.status = invalid_status
            member.save()
            
    def test_link_field_validation(self):
        """Test link field validation"""
        # Test linking to non-existent record
        with self.assertValidationError("Chapter does not exist"):
            self.create_test_member(chapter="NonExistentChapter")
            
        # Test linking to deleted record
        chapter = self.create_test_chapter()
        chapter_name = chapter.name
        frappe.delete_doc("Chapter", chapter_name)
        
        with self.assertValidationError("Chapter does not exist"):
            self.create_test_member(chapter=chapter_name)
            
    def test_conditional_validation(self):
        """Test conditional validation rules"""
        # Test validation that depends on other field values
        # Example: If member type is "Student", birth date must indicate age < 25
        
        old_birth_date = "1980-01-01"  # Over 25 years old
        
        with self.assertValidationError("Students must be under 25 years old"):
            self.create_test_member(
                member_type="Student",
                birth_date=old_birth_date
            )
            
    def test_cross_document_validation(self):
        """Test validation across multiple documents"""
        member = self.create_test_member()
        
        # Create first membership
        membership1 = self.create_test_membership(
            member=member.name,
            start_date="2024-01-01",
            end_date="2024-12-31"
        )
        
        # Test overlapping membership validation
        with self.assertValidationError("Membership periods cannot overlap"):
            membership2 = self.create_test_membership(
                member=member.name,
                start_date="2024-06-01",  # Overlaps with existing membership
                end_date="2025-05-31"
            )
            
    def test_bulk_validation(self):
        """Test validation during bulk operations"""
        # Prepare bulk data with some invalid records
        bulk_data = [
            {"first_name": "Valid1", "last_name": "User1", "email": "valid1@example.com"},
            {"first_name": "", "last_name": "User2", "email": "valid2@example.com"},  # Invalid
            {"first_name": "Valid3", "last_name": "User3", "email": "valid3@example.com"},
        ]
        
        # Test bulk validation
        results = self._bulk_create_members(bulk_data)
        
        # Verify validation results
        self.assertEqual(len(results["successful"]), 2)
        self.assertEqual(len(results["failed"]), 1)
        self.assertIn("first_name is required", results["failed"][0]["error"])
        
    def test_validation_error_messages(self):
        """Test validation error message quality"""
        # Test that error messages are helpful and specific
        with self.assertRaisesRegex(frappe.ValidationError, r"Email.*invalid.*format"):
            self.create_test_member(email="invalid-email")
            
        # Test that error messages include field context
        with self.assertRaisesRegex(frappe.ValidationError, r"First name.*required"):
            self.create_test_member(first_name="")
            
    def _get_valid_member_data(self):
        """Helper method to get valid member data"""
        return {
            "first_name": "Test",
            "last_name": "User",
            "email": "test.user@example.com",
            "birth_date": "1990-01-01"
        }
        
    def _create_member_with_validation(self, member_data):
        """Helper method to create member with validation"""
        member = frappe.new_doc("Member")
        for key, value in member_data.items():
            setattr(member, key, value)
        member.save()
        return member
        
    def _bulk_create_members(self, bulk_data):
        """Helper method for bulk member creation"""
        successful = []
        failed = []
        
        for data in bulk_data:
            try:
                member = self._create_member_with_validation(data)
                successful.append(member)
                self.track_doc("Member", member.name)
            except Exception as e:
                failed.append({"data": data, "error": str(e)})
                
        return {"successful": successful, "failed": failed}
```

---

## Usage Instructions

1. **Choose the appropriate template** based on your testing needs
2. **Copy the template** to a new file with appropriate naming
3. **Replace placeholders** (marked with [brackets]) with actual values
4. **Implement helper methods** marked with `pass` or placeholder logic
5. **Add specific test cases** relevant to your component
6. **Run tests** using the enhanced test runner:

```bash
# Run with coverage reporting
python scripts/testing/runners/enhanced_test_runner.py --suite comprehensive --coverage

# Run with performance analysis
python scripts/testing/runners/enhanced_test_runner.py --suite performance

# Run with all reports
python scripts/testing/runners/enhanced_test_runner.py --suite all --all-reports --html-report
```

## Template Customization

Each template is designed to be:
- **Modular** - Use only the parts you need
- **Extensible** - Add more test methods as needed
- **Consistent** - Follows established patterns in the codebase
- **Comprehensive** - Covers common testing scenarios

Remember to always use the **VereningingenTestCase** base class to take advantage of:
- Automatic cleanup
- Enhanced assertions  
- Performance monitoring
- Edge case testing capabilities
- Mock bank support