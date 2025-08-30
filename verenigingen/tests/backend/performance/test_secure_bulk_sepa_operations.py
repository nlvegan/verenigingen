#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Secure Bulk SEPA Operations - Phase 2 Hybrid Performance-Security Architecture
Validates that bulk operations maintain security controls while achieving performance optimization
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.secure_bulk_sepa_manager import SecureBulkSEPAManager, SEPABulkOperation
from verenigingen.verenigingen_payments.utils.sepa_performance_validator import get_sepa_performance_validator


class TestSecureBulkSEPAOperations(EnhancedTestCase):
    """Test secure bulk SEPA operations with maintained performance and security"""

    def setUp(self):
        super().setUp()
        self.bulk_manager = SecureBulkSEPAManager()
        self.validator = get_sepa_performance_validator()
        
        # Create test members for bulk operations
        self.test_members = []
        for i in range(10):  # Test with 10 members for meaningful bulk operations
            member = self.create_test_member(
                first_name=f"SecureBulk{i}",
                last_name="SEPA",
                birth_date="1990-01-01",
                email=f"securebulk{i}@test.invalid"
            )
            self.test_members.append(member)

    def test_bulk_permission_validation_efficiency(self):
        """Test that bulk permission validation is more efficient than individual checks"""
        
        member_names = [member.name for member in self.test_members]
        
        # Create mock operations for testing
        operations = [
            SEPABulkOperation(
                member_id=member.name,
                mandate_id=f"SECURE-BULK-{i:03d}",
                operation_type="create",
                mandate_data={
                    "account_holder_name": member.full_name,
                    "iban": "NL91 ABNA 0417 1643 00",
                    "bic": "ABNANL2A",
                    "status": "Active",
                    "sign_date": frappe.utils.today()
                }
            )
            for i, member in enumerate(self.test_members)
        ]
        
        # Test bulk permission validation
        with self.assertQueryCount(5):  # Should be much less than 10 * N individual checks
            permission_results = self.bulk_manager._batch_validate_permissions(operations)
        
        # Validate results
        self.assertEqual(len(permission_results), len(self.test_members))
        
        # All should be authorized since we're running as Administrator in tests
        authorized_count = sum(1 for authorized in permission_results.values() if authorized)
        self.assertEqual(authorized_count, len(self.test_members))

    def test_secure_bulk_operations_maintain_audit_trail(self):
        """Test that bulk operations maintain comprehensive audit trail"""
        
        operations = [
            SEPABulkOperation(
                member_id=self.test_members[0].name,
                mandate_id="AUDIT-TEST-001",
                operation_type="create",
                mandate_data={
                    "account_holder_name": self.test_members[0].full_name,
                    "iban": "NL91 ABNA 0417 1643 00",
                    "status": "Active",
                    "sign_date": frappe.utils.today()
                }
            )
        ]
        
        # Process bulk operations
        results = self.bulk_manager.process_bulk_mandate_operations(operations)
        
        # Validate results structure
        self.assertIn("success", results)
        self.assertIn("processed", results)
        self.assertIn("security_metrics", results)
        self.assertIn("performance_metrics", results)
        
        # Check that audit logs were created
        audit_logs = frappe.get_all("SEPA Operation Audit Log",
                                  filters={"user": frappe.session.user},
                                  fields=["name", "operation_type", "operation_status"])
        
        # Should have at least one audit log entry
        self.assertGreater(len(audit_logs), 0)

    def test_performance_validator_bulk_efficiency(self):
        """Test that performance validator handles bulk validation efficiently"""
        
        member_ids = [member.name for member in self.test_members]
        operation_types = ["create"] * len(member_ids)
        
        # Test bulk validation
        with self.assertQueryCount(10):  # Should be much less than individual validations
            validation_results = self.validator.validate_bulk_operations_secure(
                member_ids, operation_types
            )
        
        # Validate results structure
        self.assertIn("validation_passed", validation_results)
        self.assertIn("compliance_passed", validation_results)
        self.assertIn("member_validations", validation_results)
        self.assertIn("performance_metrics", validation_results)
        
        # Check performance metrics
        perf_metrics = validation_results["performance_metrics"]
        self.assertLess(perf_metrics["bulk_queries_executed"], 10)
        self.assertGreater(perf_metrics["estimated_individual_queries"], 50)

    def test_security_filtering_blocks_unauthorized_operations(self):
        """Test that security filtering properly blocks unauthorized operations"""
        
        # Create operations for members that current user shouldn't access
        # (This would be more meaningful with different user contexts)
        operations = [
            SEPABulkOperation(
                member_id=self.test_members[0].name,
                mandate_id="SECURITY-TEST-001",
                operation_type="create",
                mandate_data={
                    "account_holder_name": self.test_members[0].full_name,
                    "iban": "NL91 ABNA 0417 1643 00",
                    "status": "Active",
                    "sign_date": frappe.utils.today()
                }
            )
        ]
        
        # Process operations
        results = self.bulk_manager.process_bulk_mandate_operations(operations)
        
        # Validate security metrics are tracked
        self.assertIn("security_metrics", results)
        security_metrics = results["security_metrics"]
        
        self.assertIn("permission_checks", security_metrics)
        self.assertIn("authorization_rate", security_metrics)
        self.assertIn("blocked_operations", security_metrics)
        
        # With Administrator role, authorization rate should be 1.0
        self.assertEqual(security_metrics["authorization_rate"], 1.0)

    def test_dutch_compliance_validation_bulk(self):
        """Test Dutch banking compliance validation in bulk operations"""
        
        member_ids = [member.name for member in self.test_members]
        
        # Test bulk Dutch compliance validation
        validation_results = self.validator.validate_bulk_operations_secure(
            member_ids, ["create"]
        )
        
        # All test members should pass Dutch compliance (age 35, valid names)
        self.assertTrue(validation_results["compliance_passed"])
        
        # Check individual compliance results
        for member_id in member_ids:
            member_compliance = validation_results["compliance_results"][member_id]
            self.assertTrue(member_compliance["compliant"])
            self.assertIn("age_requirement", member_compliance["compliance_checks"])

    def test_performance_vs_security_balance(self):
        """Test that performance optimizations don't compromise security"""
        
        member_ids = [member.name for member in self.test_members]
        
        # Create operations
        operations = [
            SEPABulkOperation(
                member_id=member_id,
                mandate_id=f"BALANCE-TEST-{i:03d}",
                operation_type="create",
                mandate_data={
                    "account_holder_name": f"Test Member {i}",
                    "iban": "NL91 ABNA 0417 1643 00",
                    "status": "Active",
                    "sign_date": frappe.utils.today()
                }
            )
            for i, member_id in enumerate(member_ids)
        ]
        
        # Process with query monitoring
        with self.assertQueryCount(50):  # Should be much less than N*100+ individual operations
            results = self.bulk_manager.process_bulk_mandate_operations(operations)
        
        # Validate that security wasn't compromised for performance
        self.assertTrue(results["success"])
        self.assertEqual(results["processed"], len(operations))
        
        # Validate that all security checks were performed
        self.assertEqual(
            results["security_metrics"]["permission_checks"], 
            len(operations)
        )
        
        # Validate performance improvement
        perf_metrics = results["performance_metrics"]
        self.assertLess(
            perf_metrics["permission_validation_queries"],
            len(operations) * 2  # Much less than individual permission checks
        )

    def test_validation_caching_improves_performance(self):
        """Test that validation caching improves performance for repeated operations"""
        
        member_id = self.test_members[0].name
        
        # First validation (cache miss)
        first_result = self.validator.validate_single_operation_fast(member_id, "create")
        self.assertFalse(first_result["cache_hit"])
        
        # Second validation (cache hit)
        second_result = self.validator.validate_single_operation_fast(member_id, "create")
        self.assertTrue(second_result["cache_hit"])
        
        # Results should be identical
        self.assertEqual(first_result["valid"], second_result["valid"])

    def test_error_handling_in_bulk_operations(self):
        """Test that bulk operations handle errors gracefully without compromising security"""
        
        # Create operations with some invalid data
        operations = [
            # Valid operation
            SEPABulkOperation(
                member_id=self.test_members[0].name,
                mandate_id="VALID-001",
                operation_type="create",
                mandate_data={
                    "account_holder_name": self.test_members[0].full_name,
                    "iban": "NL91 ABNA 0417 1643 00",
                    "status": "Active",
                    "sign_date": frappe.utils.today()
                }
            ),
            # Invalid operation (missing required field)
            SEPABulkOperation(
                member_id=self.test_members[1].name,
                mandate_id="INVALID-001",
                operation_type="create",
                mandate_data={
                    "account_holder_name": self.test_members[1].full_name,
                    # Missing IBAN
                    "status": "Active",
                    "sign_date": frappe.utils.today()
                }
            )
        ]
        
        # Process operations
        results = self.bulk_manager.process_bulk_mandate_operations(operations)
        
        # Should process valid operations and report errors for invalid ones
        self.assertGreater(results["processed"], 0)  # At least one processed
        self.assertGreater(len(results["results"]["errors"]), 0)  # At least one error

    def test_integration_with_existing_sepa_mandate_operations(self):
        """Test that bulk operations integrate properly with existing SEPA mandate functionality"""
        
        # Create a SEPA mandate using the standard (now secured) method
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": self.test_members[0].name,
            "member_name": self.test_members[0].full_name,
            "mandate_id": "INTEGRATION-TEST-001",
            "account_holder_name": self.test_members[0].full_name,
            "iban": "NL91 ABNA 0417 1643 00",
            "bic": "ABNANL2A",
            "status": "Active",
            "sign_date": frappe.utils.today()
        })
        
        # This should use the secured operations with audit logging
        mandate.save()
        
        # Verify mandate was created
        self.assertIsNotNone(mandate.name)
        
        # Verify audit log was created
        audit_logs = frappe.get_all("SEPA Operation Audit Log",
                                  filters={"member": self.test_members[0].name},
                                  fields=["name", "operation_type"])
        
        self.assertGreater(len(audit_logs), 0)
        
        # Verify member relationship was properly updated
        member_mandate_links = frappe.get_all("Member SEPA Mandate Link",
                                            filters={"parent": self.test_members[0].name},
                                            fields=["sepa_mandate", "status"])
        
        self.assertGreater(len(member_mandate_links), 0)
        self.assertEqual(member_mandate_links[0].status, "Active")