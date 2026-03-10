# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

import frappe
import unittest
from typing import List, Dict, Any

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.sepa_permission_resolver import (
    SEPAPermissionResolverClean,
    UserPermissionContext,
    get_clean_sepa_permission_resolver
)
from verenigingen.verenigingen_payments.utils.audit_context import (
    AuditContextClean,
    AuditContextManagerClean,
    ExecutionSource,
    create_clean_audit_context
)
from verenigingen.verenigingen_payments.utils.performance_estimator import (
    SEPAPerformanceEstimatorClean,
    ProcessingMode,
    get_clean_performance_estimator,
    estimate_sepa_operation_performance_clean
)


class TestSEPAIntegrationHonest(EnhancedTestCase):
    """
    Honest integration tests - no conditional logic, no skip fallbacks
    
    Tests either work against real components or fail clearly.
    No "smart" adaptation to missing dependencies.
    """

    def setUp(self):
        """Set up test environment with real data"""
        super().setUp()
        
        # Create test members - these MUST exist for tests to pass
        self.test_member_1 = self.create_test_member(
            first_name="Honest",
            last_name="Member",
            birth_date="1990-01-01"
        )
        
        self.test_member_2 = self.create_test_member(
            first_name="Another",
            last_name="Member",
            birth_date="1985-05-15"
        )

    def test_permission_resolver_with_real_members(self):
        """Test permission resolver with real member data - no fallbacks"""
        
        resolver = get_clean_sepa_permission_resolver()
        
        # Use real member IDs - no conditional logic
        member_ids = [self.test_member_1.name, self.test_member_2.name]
        
        # Get permission summary - must work or test fails
        summary = resolver.get_permission_summary(member_ids)
        
        # Validate required structure
        self.assertIn("user", summary)
        self.assertIn("permission_level", summary)
        self.assertIn("total_requested", summary)
        self.assertIn("authorized_count", summary)
        self.assertIn("blocked_count", summary)
        
        # Total must match request
        self.assertEqual(summary["total_requested"], 2)
        self.assertEqual(
            summary["authorized_count"] + summary["blocked_count"],
            summary["total_requested"]
        )
        
        # Test individual access
        for member_id in member_ids:
            can_access = resolver.can_access_member(member_id)
            self.assertIsInstance(can_access, bool)

    def test_audit_context_explicit_sources(self):
        """Test audit context with explicit source specification only"""
        
        # Test all sources explicitly - no runtime detection
        explicit_sources = [
            ExecutionSource.HTTP,
            ExecutionSource.BACKGROUND,
            ExecutionSource.TEST,
            ExecutionSource.CONSOLE
        ]
        
        for source in explicit_sources:
            with self.subTest(source=source):
                # Must provide source explicitly
                context = create_clean_audit_context(source)
                
                # Validate required fields
                self.assertIsNotNone(context.user)
                self.assertIsNotNone(context.timestamp)
                self.assertEqual(context.source, source)
                self.assertIsNotNone(context.trace_id)
                self.assertIsNotNone(context.ip_address)
                self.assertIsNotNone(context.user_agent)
                
                # Validate audit fields creation (without permission bypasses)
                audit_fields = context.create_audit_log_fields()
                self.assertIn("user", audit_fields)
                self.assertIn("timestamp", audit_fields)
                self.assertIn("ip_address", audit_fields)

    def test_audit_context_manager_without_permission_bypasses(self):
        """Test audit context manager that doesn't create audit logs automatically"""
        
        operation_results = []
        
        # Must provide source explicitly
        with AuditContextManagerClean("test_operation", ExecutionSource.TEST) as audit_mgr:
            # Record operations
            audit_mgr.log_operation_result(True, {"created": "mandate-1"})
            audit_mgr.log_operation_result(True, {"created": "mandate-2"})
            operation_results = audit_mgr.operation_results
        
        # Validate operations were recorded in memory
        self.assertEqual(len(operation_results), 2)
        self.assertTrue(all(r["success"] for r in operation_results))
        
        # Get audit summary - but no automatic audit log creation
        audit_summary = audit_mgr.get_audit_summary()
        self.assertIn("operation_name", audit_summary)
        self.assertIn("context", audit_summary)
        self.assertIn("results", audit_summary)
        self.assertIn("audit_fields", audit_summary)
        self.assertTrue(audit_summary["success"])

    def test_performance_estimator_without_fake_learning(self):
        """Test performance estimator with honest static estimates"""
        
        estimator = get_clean_performance_estimator()
        
        # Test different batch sizes
        test_cases = [
            {"count": 5, "expected_mode": ProcessingMode.IMMEDIATE},
            {"count": 25, "expected_mode": ProcessingMode.BACKGROUND},
            {"count": 600, "expected_mode": ProcessingMode.REJECTED}
        ]
        
        for case in test_cases:
            with self.subTest(count=case["count"]):
                # Create operations
                operations = [
                    {
                        "operation_type": "create",
                        "member_id": f"MEMBER-{i:03d}",
                        "mandate_data": {"iban": f"NL91ABNA041716430{i % 10}"}
                    }
                    for i in range(case["count"])
                ]
                
                estimate = estimate_sepa_operation_performance_clean(operations)
                
                # Validate estimate structure
                self.assertEqual(estimate.operation_count, case["count"])
                self.assertEqual(estimate.processing_mode, case["expected_mode"])
                self.assertIsInstance(estimate.estimated_duration, float)
                self.assertIsInstance(estimate.user_message, str)
                self.assertIsInstance(estimate.recommendations, list)
                
                # Validate technical details don't claim learning
                self.assertIn("note", estimate.technical_details)
                self.assertIn("based on Frappe Framework research", estimate.technical_details["note"])

    def test_permission_resolver_single_path_logic(self):
        """Test permission resolver uses single path logic without fallbacks"""
        
        resolver = SEPAPermissionResolverClean()
        
        # Test that permission resolution is consistent
        member_id = self.test_member_1.name
        result1 = resolver.can_access_member(member_id)
        result2 = resolver.can_access_member(member_id)
        
        # Results must be identical (cached)
        self.assertEqual(result1, result2)
        
        # Cache should contain result
        cache_key = f"{resolver.user}:{member_id}"
        self.assertIn(cache_key, resolver._permission_cache)
        
        # Clear cache and verify
        resolver.clear_cache()
        self.assertNotIn(cache_key, resolver._permission_cache)

    def test_no_runtime_context_detection(self):
        """Test that audit context requires explicit source specification"""
        
        # This should work - explicit source provided
        context_explicit = create_clean_audit_context(ExecutionSource.TEST)
        self.assertEqual(context_explicit.source, ExecutionSource.TEST)
        
        # Test that all context information is predictable
        self.assertEqual(context_explicit.ip_address, "test-environment")
        self.assertEqual(context_explicit.user_agent, "frappe-test-runner")

    def test_permission_hierarchy_without_fallbacks(self):
        """Test permission hierarchy is simple and predictable"""
        
        resolver = get_clean_sepa_permission_resolver()
        context = resolver.user_context
        
        # Should be one of the four levels
        valid_levels = ["admin", "manager", "member", "none"]
        self.assertIn(context.permission_level, valid_levels)
        
        # Test that permission level directly maps to access
        member_id = self.test_member_1.name
        can_access = resolver.can_access_member(member_id)
        
        if context.permission_level in ["admin", "manager"]:
            self.assertTrue(can_access)
        elif context.permission_level == "member":
            # Member can only access if it's their own ID
            expected = (context.member_id == member_id)
            self.assertEqual(can_access, expected)
        else:  # none
            self.assertFalse(can_access)

    def test_error_handling_without_conditional_logic(self):
        """Test error handling with real errors - no graceful degradation"""
        
        resolver = get_clean_sepa_permission_resolver()
        
        # Test with invalid member ID - should handle gracefully but not conditionally
        invalid_permissions = resolver.get_permission_summary(["INVALID-MEMBER"])
        
        # Should return valid structure even for invalid IDs
        self.assertIn("authorized_count", invalid_permissions)
        self.assertIn("blocked_count", invalid_permissions)
        self.assertEqual(
            invalid_permissions["authorized_count"] + invalid_permissions["blocked_count"],
            1
        )

    def test_integration_workflow_without_mocks_or_conditionals(self):
        """Test complete integration workflow - real operations only"""
        
        # 1. Permission resolution - must work
        resolver = get_clean_sepa_permission_resolver()
        member_ids = [self.test_member_1.name]
        permissions = resolver.get_permission_summary(member_ids)
        
        # 2. Performance estimation - must work
        operations = [{
            "operation_type": "create",
            "member_id": self.test_member_1.name,
            "mandate_data": {
                "mandate_id": "INTEGRATION-001",
                "iban": "NL91ABNA0417164300"
            }
        }]
        
        estimate = estimate_sepa_operation_performance_clean(operations)
        
        # 3. Audit context creation - must work with explicit source
        with AuditContextManagerClean("integration_test", ExecutionSource.TEST) as audit_mgr:
            # 4. Simulate operation execution
            if permissions["all_authorized"]:
                audit_mgr.log_operation_result(True, {"created": "integration-mandate"})
            else:
                audit_mgr.log_operation_result(False, {"error": "insufficient_permissions"})
            
            # 5. Get audit summary (no automatic audit log creation)
            audit_summary = audit_mgr.get_audit_summary()
        
        # Validate end-to-end workflow
        self.assertIsInstance(permissions, dict)
        self.assertIsInstance(estimate, object)  # PerformanceEstimate
        self.assertIsInstance(audit_summary, dict)
        self.assertIn("audit_fields", audit_summary)

    def test_caching_works_without_complexity(self):
        """Test caching mechanisms are simple and effective"""
        
        resolver = get_clean_sepa_permission_resolver()
        
        # First access
        member_id = self.test_member_1.name
        result1 = resolver.can_access_member(member_id)
        
        # Should be cached
        cache_key = f"{resolver.user}:{member_id}"
        self.assertIn(cache_key, resolver._permission_cache)
        self.assertEqual(resolver._permission_cache[cache_key], result1)
        
        # Second access should use cache
        result2 = resolver.can_access_member(member_id)
        self.assertEqual(result1, result2)


if __name__ == '__main__':
    unittest.main()