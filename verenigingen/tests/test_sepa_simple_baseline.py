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

    def test_single_create_operation_with_mock_member(self):
        """Test single create operation with mocked member data"""
        # Create test operation
        operation = SimpleSEPAOperation(
            member_id="test-member-001",
            operation_type="create",
            operation_data={
                "iban": "NL91ABNA0417164300",
                "account_holder": "Test User",
                "mandate_reference": "TEST-001"
            }
        )

        # Mock member existence check to avoid database dependency
        with patch('frappe.get_doc') as mock_get_doc:
            # Mock member doc for permission check
            mock_member = frappe._dict({"name": "test-member-001"})
            
            # Mock mandate doc for creation
            mock_mandate = frappe._dict({
                "name": "SEPA-MANDATE-001",
                "insert": lambda: None
            })
            
            def mock_get_doc_side_effect(doctype, name=None):
                if doctype == "Member":
                    return mock_member
                elif doctype == "SEPA Mandate":
                    return mock_mandate
                else:
                    return mock_mandate
            
            mock_get_doc.side_effect = mock_get_doc_side_effect
            
            # Test the operation
            result = self.sepa_manager.process_operations_simple([operation])
            
            # Verify results structure (no runtime errors)
            self.assertTrue(result["success"])
            self.assertIsInstance(result["processed"], int)
            self.assertIsInstance(result["failed"], int)
            self.assertIsInstance(result["total_operations"], int)
            self.assertIn("execution_time", result)
            self.assertIn("successful_operations", result)
            self.assertIn("failed_operations", result)
            self.assertIn("errors", result)

    def test_multiple_operations_baseline(self):
        """Test multiple operations to establish performance baseline"""
        operations = []
        
        # Create 10 test operations
        for i in range(10):
            operations.append(SimpleSEPAOperation(
                member_id=f"test-member-{i:03d}",
                operation_type="create",
                operation_data={
                    "iban": f"NL91ABNA041716430{i}",
                    "account_holder": f"Test User {i}",
                    "mandate_reference": f"TEST-{i:03d}"
                }
            ))

        # Mock all database operations
        with patch('frappe.get_doc') as mock_get_doc, \
             patch('frappe.db.commit') as mock_commit:
            
            # Mock member docs for permission checks
            def mock_get_doc_side_effect(doctype, name=None):
                if doctype == "Member":
                    return frappe._dict({"name": name})
                else:
                    # Return mandate doc with insert method
                    mock_mandate = frappe._dict({"name": f"SEPA-MANDATE-{name[-3:]}"})
                    mock_mandate.insert = lambda: None
                    return mock_mandate
            
            mock_get_doc.side_effect = mock_get_doc_side_effect
            
            # Measure baseline performance
            start_time = time.time()
            result = self.sepa_manager.process_operations_simple(operations)
            execution_time = time.time() - start_time
            
            # Verify no runtime errors occurred
            self.assertTrue(result["success"])
            self.assertIsInstance(result["processed"], int)
            self.assertIsInstance(result["failed"], int)
            
            # Log baseline performance
            frappe.logger().info(f"SEPA Simple Baseline: {len(operations)} operations in {execution_time:.3f}s")
            frappe.logger().info(f"Results: {result['processed']} processed, {result['failed']} failed")

    def test_permission_failure_handling(self):
        """Test handling of permission failures without runtime errors"""
        operation = SimpleSEPAOperation(
            member_id="nonexistent-member",
            operation_type="create",
            operation_data={"iban": "NL91ABNA0417164300"}
        )

        # Mock member not found scenario
        with patch('frappe.get_doc') as mock_get_doc:
            mock_get_doc.side_effect = frappe.DoesNotExistError
            
            result = self.sepa_manager.process_operations_simple([operation])
            
            # Should handle error gracefully without runtime exceptions
            self.assertTrue(result["success"])
            self.assertEqual(result["processed"], 0)
            self.assertEqual(result["failed"], 1)

    def test_results_structure_consistency(self):
        """Test that results structure is consistent and type-safe"""
        operations = [
            SimpleSEPAOperation("member-001", "create", {"iban": "NL91ABNA0417164300"}),
            SimpleSEPAOperation("member-002", "update", {"account_holder": "Updated Name"}),
            SimpleSEPAOperation("member-003", "cancel", {"reason": "Member request"})
        ]

        # Mock all operations
        with patch('frappe.get_doc') as mock_get_doc, \
             patch('frappe.get_all') as mock_get_all, \
             patch('frappe.db.commit') as mock_commit:
            
            # Mock member docs
            mock_get_doc.return_value = frappe._dict({
                "name": "SEPA-MANDATE-001",
                "insert": lambda: None,
                "save": lambda: None,
                "status": "Active"
            })
            
            # Mock mandate lookup for update/cancel
            mock_get_all.return_value = [frappe._dict({"name": "SEPA-MANDATE-001"})]
            
            result = self.sepa_manager.process_operations_simple(operations)
            
            # Verify all result fields have correct types
            self.assertIsInstance(result["success"], bool)
            self.assertIsInstance(result["processed"], int)
            self.assertIsInstance(result["failed"], int)
            self.assertIsInstance(result["total_operations"], int)
            self.assertIsInstance(result["execution_time"], (int, float))
            self.assertIsInstance(result["successful_operations"], list)
            self.assertIsInstance(result["failed_operations"], list)
            self.assertIsInstance(result["errors"], list)
            
            # Test that we can safely iterate over results without len() errors
            for op_result in result["successful_operations"]:
                self.assertIsInstance(op_result, dict)
                self.assertIn("success", op_result)
            
            for error in result["errors"]:
                self.assertIsInstance(error, dict)


if __name__ == "__main__":
    unittest.main()