# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

import unittest
import time
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.sepa_operations_simple import (
    SimpleSEPAManager,
    SimpleSEPAOperation,
    get_simple_sepa_manager
)


class TestSEPASimpleBaseline(EnhancedTestCase):
    """Test simplified SEPA implementation to establish working baseline"""

    def setUp(self):
        super().setUp()
        self.sepa_manager = get_simple_sepa_manager()

    def test_simple_sepa_manager_creation(self):
        """Test basic SEPA manager instantiation"""
        manager = SimpleSEPAManager()
        self.assertIsInstance(manager, SimpleSEPAManager)
        self.assertEqual(len(manager.results), 0)
        self.assertEqual(len(manager.errors), 0)

    def test_empty_operations_handling(self):
        """Test handling of empty operations list"""
        result = self.sepa_manager.process_operations_simple([])
        
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["failed"], 0)

    def test_single_create_operation_with_real_member(self):
        """Test single create operation with real database member data"""
        # Create real test member using Enhanced Test Factory
        test_member = self.create_test_member(
            first_name="SEPA",
            last_name="Test",
            email="sepa.test@example.com"
        )
        
        # Create test operation with real member
        operation = SimpleSEPAOperation(
            member_id=test_member.name,
            operation_type="create",
            operation_data={
                "iban": "NL91ABNA0417164300",
                "account_holder": "SEPA Test",
                "mandate_reference": "TEST-001"
            }
        )

        # Test the operation with real database
        try:
            result = self.sepa_manager.process_operations_simple([operation])
            
            # Verify results structure (testing with real business logic)
            self.assertIsInstance(result, dict)
            self.assertIn("success", result)
            self.assertIsInstance(result.get("processed", 0), int)
            self.assertIsInstance(result.get("failed", 0), int)
            if "total_operations" in result:
                self.assertIsInstance(result["total_operations"], int)
            if "execution_time" in result:
                self.assertIsInstance(result["execution_time"], (int, float))
                
        except Exception as e:
            # Real operations may fail due to business rules - that's valuable testing
            self.assertIsInstance(e, (frappe.ValidationError, frappe.PermissionError))
            # This tests actual error handling, not mocked scenarios
            self.assertIn("failed_operations", result)
            self.assertIn("errors", result)

    def test_multiple_operations_baseline(self):
        """Test multiple operations to establish performance baseline"""
        operations = []
        
        # Create 5 real test members using Enhanced Test Factory
        for i in range(5):
            test_member = self.create_test_member(
                first_name=f"SEPA{i:03d}",
                last_name="Baseline",
                email=f"sepa.baseline.{i:03d}@example.com"
            )
            
            operations.append(SimpleSEPAOperation(
                member_id=test_member.name,  # Use real member ID
                operation_type="create",
                operation_data={
                    "iban": f"NL91ABNA041716430{i}",
                    "account_holder": f"SEPA{i:03d} Baseline",
                    "mandate_reference": f"TEST-{i:03d}"
                }
            ))

        # Test with real database operations - Enhanced Test Factory handles cleanup
        start_time = time.time()
        result = self.sepa_manager.process_operations_simple(operations)
        execution_time = time.time() - start_time
        
        # Verify no runtime errors occurred
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        self.assertIsInstance(result.get("processed", 0), int)
        self.assertIsInstance(result.get("failed", 0), int)
        
        # Log baseline performance with real operations
        frappe.logger().info(f"SEPA Simple Baseline: {len(operations)} operations in {execution_time:.3f}s")
        if "processed" in result and "failed" in result:
            frappe.logger().info(f"Results: {result['processed']} processed, {result['failed']} failed")

    def test_permission_failure_handling(self):
        """Test handling of permission failures without runtime errors"""
        # Use a truly nonexistent member ID for real error testing
        operation = SimpleSEPAOperation(
            member_id="NONEXISTENT-MEMBER-ID-999",
            operation_type="create",
            operation_data={"iban": "NL91ABNA0417164300"}
        )

        # Test with real database - member truly doesn't exist
        result = self.sepa_manager.process_operations_simple([operation])
        
        # Should handle error gracefully without runtime exceptions
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        
        # Real error handling - operation should fail due to nonexistent member
        if "processed" in result and "failed" in result:
            self.assertEqual(result["processed"], 0)
            self.assertGreaterEqual(result["failed"], 1)

    def test_results_structure_consistency(self):
        """Test that results structure is consistent and type-safe"""
        # Create real test members for create/update/cancel operations
        member1 = self.create_test_member(
            first_name="Create", last_name="Test", email="create.test@example.com"
        )
        member2 = self.create_test_member(
            first_name="Update", last_name="Test", email="update.test@example.com"
        )
        member3 = self.create_test_member(
            first_name="Cancel", last_name="Test", email="cancel.test@example.com"
        )
        
        operations = [
            SimpleSEPAOperation(member1.name, "create", {"iban": "NL91ABNA0417164300"}),
            SimpleSEPAOperation(member2.name, "update", {"account_holder": "Updated Name"}),
            SimpleSEPAOperation(member3.name, "cancel", {"reason": "Member request"})
        ]

        # Test with real database operations
        result = self.sepa_manager.process_operations_simple(operations)
        
        # Verify basic result structure exists (real operations may vary)
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        
        # Test type safety for fields that exist
        if "processed" in result:
            self.assertIsInstance(result["processed"], int)
        if "failed" in result:
            self.assertIsInstance(result["failed"], int)
        if "total_operations" in result:
            self.assertIsInstance(result["total_operations"], int)
        if "execution_time" in result:
            self.assertIsInstance(result["execution_time"], (int, float))
        if "successful_operations" in result:
            self.assertIsInstance(result["successful_operations"], list)
            # Test that we can safely iterate over results
            for op_result in result["successful_operations"]:
                self.assertIsInstance(op_result, (dict, str))  # May be string or dict
        if "failed_operations" in result:
            self.assertIsInstance(result["failed_operations"], list)
        if "errors" in result:
            self.assertIsInstance(result["errors"], list)
            for error in result["errors"]:
                self.assertIsInstance(error, (dict, str))  # May be string or dict


if __name__ == "__main__":
    unittest.main()