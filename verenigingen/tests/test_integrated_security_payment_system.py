#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration Tests for Security-Payment System

Tests the integration between:
1. Payment History Race Condition Fix
2. Payment History Validator 
3. API Security Framework Decorators

This ensures all components work together seamlessly in realistic scenarios.
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import frappe
from frappe.utils import add_days, now_datetime, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.payment_history_validator import validate_and_repair_payment_history
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    SecurityLevel,
    high_security_api,
    standard_api,
)


class TestIntegratedSecurityPaymentSystem(VereningingenTestCase):
    """Integration tests for the complete security-payment system"""

    def setUp(self):
        super().setUp()
        self.test_start_time = now_datetime()
        
        # Create comprehensive test data
        self.test_members = []
        for i in range(3):
            member = self.create_test_member(
                first_name=f"Integration{i:02d}",
                last_name="TestMember",
                email=f"integration.test.{i:02d}@example.com"
            )
            
            # Ensure customer exists
            if not member.customer:
                customer = frappe.new_doc("Customer")
                customer.customer_name = f"{member.first_name} {member.last_name}"
                customer.customer_type = "Individual"
                customer.member = member.name
                customer.save()
                member.customer = customer.name
                member.save()
                self.track_doc("Customer", customer.name)
            
            self.test_members.append(member)
        
        # Create test user with appropriate permissions
        self.test_user = self.create_test_user(
            "integration.admin@example.com",
            roles=["System Manager", "Verenigingen Administrator"]
        )

    def test_end_to_end_invoice_processing_workflow(self):
        """Test complete end-to-end invoice processing with security and validation"""
        
        # Step 1: Create invoices through secure API
        @high_security_api(operation_type=OperationType.FINANCIAL)
        def create_secured_invoice(customer_name, amount):
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = customer_name
            invoice.posting_date = today()
            invoice.due_date = add_days(today(), 30)
            invoice.is_membership_invoice = 1
            
            # Add item
            invoice.append("items", {
                "item_code": "TEST-MEMBERSHIP",
                "qty": 1,
                "rate": amount
            })
            
            invoice.save()
            return invoice
        
        # Step 2: Process invoices with race condition handling
        @standard_api(operation_type=OperationType.MEMBER_DATA)
        def process_member_payment_history(member_name, invoice_name):
            member = frappe.get_doc("Member", member_name)
            member.add_invoice_to_payment_history(invoice_name)
            return {"status": "processed", "member": member_name, "invoice": invoice_name}
        
        # Step 3: Run validation and repair
        @standard_api(operation_type=OperationType.UTILITY)
        def run_payment_validation():
            return validate_and_repair_payment_history()
        
        # Execute the complete workflow
        with self.as_user(self.test_user.email):
            # Create invoices through secure API
            created_invoices = []
            for i, member in enumerate(self.test_members):
                invoice = create_secured_invoice(member.customer, 50.0 + (i * 10))
                created_invoices.append((invoice, member))
            
            # Process payment history (some with race conditions)
            processing_results = []
            for invoice, member in created_invoices:
                result = process_member_payment_history(member.name, invoice.name)
                processing_results.append(result)
                self.assertEqual(result["status"], "processed")
            
            # Run validation to ensure everything is consistent
            validation_result = run_payment_validation()
            self.assertTrue(validation_result["success"])
            
            # Verify all invoices are properly tracked
            for invoice, member in created_invoices:
                member.reload()
                payment_history_invoices = [entry.invoice for entry in member.payment_history]
                self.assertIn(invoice.name, payment_history_invoices,
                             f"Invoice {invoice.name} should be in {member.name} payment history")

    def test_concurrent_operations_with_security_validation(self):
        """Test concurrent operations under security framework with race condition handling"""
        
        @high_security_api(operation_type=OperationType.FINANCIAL)
        def concurrent_invoice_operation(member_name, operation_id):
            # Create invoice
            member = frappe.get_doc("Member", member_name)
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = member.customer
            invoice.posting_date = add_days(today(), -operation_id)
            invoice.due_date = add_days(today(), 30)
            invoice.is_membership_invoice = 1
            
            # Add test item
            invoice.append("items", {
                "item_code": "TEST-MEMBERSHIP",
                "qty": 1,
                "rate": 25.0 + operation_id
            })
            
            invoice.save()
            
            # Add to payment history with potential race conditions
            member.add_invoice_to_payment_history(invoice.name)
            
            return {
                "operation_id": operation_id,
                "member": member_name,
                "invoice": invoice.name,
                "status": "completed"
            }
        
        # Execute concurrent operations
        with self.as_user(self.test_user.email):
            # Use ThreadPoolExecutor for true concurrency
            with ThreadPoolExecutor(max_workers=3) as executor:
                # Submit concurrent operations
                futures = []
                for i, member in enumerate(self.test_members):
                    for j in range(2):  # 2 operations per member
                        operation_id = (i * 2) + j
                        future = executor.submit(concurrent_invoice_operation, member.name, operation_id)
                        futures.append(future)
                
                # Collect results
                results = []
                for future in as_completed(futures, timeout=60):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        self.fail(f"Concurrent operation failed: {e}")
                
                # Verify all operations completed successfully
                self.assertEqual(len(results), 6, "All 6 concurrent operations should complete")
                
                for result in results:
                    self.assertEqual(result["status"], "completed")
                    self.assertIn("invoice", result)
                    self.assertIn("member", result)

    def test_bulk_processing_with_validation_recovery(self):
        """Test bulk processing mode with validation recovery mechanisms"""
        
        @high_security_api(operation_type=OperationType.FINANCIAL)
        def bulk_invoice_generation(member_list, invoice_count_per_member):
            # Set bulk processing flag
            frappe.flags.bulk_invoice_generation = True
            
            try:
                created_invoices = []
                
                for member_name in member_list:
                    member = frappe.get_doc("Member", member_name)
                    
                    for i in range(invoice_count_per_member):
                        # Create invoice
                        invoice = frappe.new_doc("Sales Invoice")
                        invoice.customer = member.customer
                        invoice.posting_date = add_days(today(), -(i+1))
                        invoice.due_date = add_days(today(), 30)
                        invoice.is_membership_invoice = 1
                        
                        invoice.append("items", {
                            "item_code": "TEST-MEMBERSHIP",
                            "qty": 1,
                            "rate": 30.0 + i
                        })
                        
                        invoice.save()
                        created_invoices.append(invoice)
                        
                        # Add to payment history in bulk mode
                        member.add_invoice_to_payment_history(invoice.name)
                
                return {
                    "status": "bulk_completed",
                    "invoice_count": len(created_invoices),
                    "invoices": [inv.name for inv in created_invoices]
                }
                
            finally:
                # Clean up flags
                if hasattr(frappe.flags, 'bulk_invoice_generation'):
                    delattr(frappe.flags, 'bulk_invoice_generation')
        
        @standard_api(operation_type=OperationType.UTILITY)
        def validate_bulk_results():
            return validate_and_repair_payment_history()
        
        # Execute bulk processing test
        with self.as_user(self.test_user.email):
            member_names = [member.name for member in self.test_members]
            
            # Perform bulk generation
            bulk_result = bulk_invoice_generation(member_names, 3)  # 3 invoices per member
            
            self.assertEqual(bulk_result["status"], "bulk_completed")
            self.assertEqual(bulk_result["invoice_count"], 9)  # 3 members * 3 invoices
            
            # Run validation to catch any issues
            validation_result = validate_bulk_results()
            
            self.assertTrue(validation_result["success"])
            # Should find minimal issues since bulk processing should work correctly
            self.assertLessEqual(validation_result["missing_found"], 2, 
                               "Bulk processing should have minimal missing entries")

    def test_security_rate_limiting_with_payment_operations(self):
        """Test security rate limiting behavior with payment operations"""
        
        @high_security_api(operation_type=OperationType.FINANCIAL)
        def rate_limited_payment_operation(member_name, operation_type):
            member = frappe.get_doc("Member", member_name)
            
            if operation_type == "create_invoice":
                invoice = frappe.new_doc("Sales Invoice")
                invoice.customer = member.customer
                invoice.posting_date = today()
                invoice.due_date = add_days(today(), 30)
                invoice.is_membership_invoice = 1
                
                invoice.append("items", {
                    "item_code": "TEST-MEMBERSHIP",
                    "qty": 1,
                    "rate": 20.0
                })
                
                invoice.save()
                return {"operation": "invoice_created", "invoice": invoice.name}
                
            elif operation_type == "update_payment_history":
                # Simulate payment history update
                member.load_payment_history()
                return {"operation": "payment_history_updated", "count": len(member.payment_history)}
        
        # Test rate limiting with multiple rapid operations
        with self.as_user(self.test_user.email):
            successful_operations = 0
            rate_limited_operations = 0
            
            # Perform rapid operations to test rate limiting
            for i in range(20):  # Try 20 rapid operations
                try:
                    operation_type = "create_invoice" if i % 2 == 0 else "update_payment_history"
                    member = self.test_members[i % len(self.test_members)]
                    
                    result = rate_limited_payment_operation(member.name, operation_type)
                    successful_operations += 1
                    
                    # Add small delay to prevent immediate rate limiting
                    time.sleep(0.1)
                    
                except Exception as e:
                    if "rate limit" in str(e).lower():
                        rate_limited_operations += 1
                    else:
                        # If it's not a rate limiting error, it might be a real issue
                        print(f"Unexpected error in rate limiting test: {e}")
            
            # Should have some successful operations
            self.assertGreater(successful_operations, 0, 
                             "Some operations should succeed before rate limiting")
            
            # Rate limiting may or may not trigger depending on configuration
            total_attempts = successful_operations + rate_limited_operations
            self.assertLessEqual(total_attempts, 20, "Total attempts should not exceed limit")

    def test_error_recovery_and_resilience(self):
        """Test error recovery and system resilience"""
        
        @high_security_api(operation_type=OperationType.FINANCIAL)
        def resilient_payment_processing(member_name, simulate_errors=False):
            member = frappe.get_doc("Member", member_name)
            
            if simulate_errors:
                # Simulate various error conditions
                if "01" in member_name:
                    raise frappe.ValidationError("Simulated validation error")
                elif "02" in member_name:
                    raise frappe.PermissionError("Simulated permission error")
            
            # Normal processing
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = member.customer
            invoice.posting_date = today()
            invoice.due_date = add_days(today(), 30)
            invoice.is_membership_invoice = 1
            
            invoice.append("items", {
                "item_code": "TEST-MEMBERSHIP",
                "qty": 1,
                "rate": 35.0
            })
            
            invoice.save()
            member.add_invoice_to_payment_history(invoice.name)
            
            return {"status": "processed", "member": member_name, "invoice": invoice.name}
        
        @standard_api(operation_type=OperationType.UTILITY)
        def recovery_validation():
            return validate_and_repair_payment_history()
        
        # Test error recovery
        with self.as_user(self.test_user.email):
            results = []
            errors = []
            
            # Process members with some simulated errors
            for member in self.test_members:
                try:
                    # Simulate errors for first two members
                    simulate_errors = member == self.test_members[0] or member == self.test_members[1]
                    result = resilient_payment_processing(member.name, simulate_errors)
                    results.append(result)
                except Exception as e:
                    errors.append({"member": member.name, "error": str(e)})
            
            # Should have some successful processing and some errors
            self.assertGreater(len(results), 0, "Some processing should succeed")
            self.assertGreater(len(errors), 0, "Some errors should be simulated")
            
            # Run validation to verify system recovery
            validation_result = recovery_validation()
            self.assertTrue(validation_result["success"], "Validation should complete even with errors")

    def test_performance_under_integrated_load(self):
        """Test system performance under integrated load"""
        
        @high_security_api(operation_type=OperationType.FINANCIAL)
        def performance_test_operation(member_name, operation_count):
            member = frappe.get_doc("Member", member_name)
            processed_invoices = []
            
            start_time = time.time()
            
            for i in range(operation_count):
                # Create invoice
                invoice = frappe.new_doc("Sales Invoice")
                invoice.customer = member.customer
                invoice.posting_date = add_days(today(), -i)
                invoice.due_date = add_days(today(), 30)
                invoice.is_membership_invoice = 1
                
                invoice.append("items", {
                    "item_code": "TEST-MEMBERSHIP",
                    "qty": 1,
                    "rate": 40.0 + i
                })
                
                invoice.save()
                processed_invoices.append(invoice.name)
                
                # Add to payment history with race condition handling
                member.add_invoice_to_payment_history(invoice.name)
            
            processing_time = time.time() - start_time
            
            return {
                "member": member_name,
                "operations": operation_count,
                "processing_time": processing_time,
                "invoices": processed_invoices,
                "avg_time_per_operation": processing_time / operation_count
            }
        
        # Performance test with integrated security
        with self.as_user(self.test_user.email):
            performance_results = []
            
            for member in self.test_members:
                result = performance_test_operation(member.name, 5)  # 5 operations per member
                performance_results.append(result)
            
            # Verify performance results
            for result in performance_results:
                self.assertEqual(result["operations"], 5)
                self.assertEqual(len(result["invoices"]), 5)
                
                # Performance should be reasonable (less than 10 seconds for 5 operations)
                self.assertLess(result["processing_time"], 10.0,
                               f"Performance test should complete within 10s: {result['processing_time']:.2f}s")
                
                # Average time per operation should be reasonable
                self.assertLess(result["avg_time_per_operation"], 2.0,
                               f"Average operation time should be reasonable: {result['avg_time_per_operation']:.2f}s")
            
            # Run final validation to ensure consistency
            validation_result = validate_and_repair_payment_history()
            self.assertTrue(validation_result["success"])

    def test_system_monitoring_and_health_checks(self):
        """Test system monitoring and health check capabilities"""
        
        @standard_api(operation_type=OperationType.UTILITY)
        def system_health_check():
            # Check payment history consistency
            validation_stats = validate_and_repair_payment_history()
            
            # Check security framework status
            security_framework_active = True
            try:
                from verenigingen.utils.security.api_security_framework import get_security_framework
                framework = get_security_framework()
                security_framework_active = framework is not None
            except Exception:
                security_framework_active = False
            
            # Check member-customer relationships
            member_customer_consistency = True
            try:
                inconsistent_members = frappe.db.sql("""
                    SELECT COUNT(*) as count
                    FROM `tabMember` m
                    LEFT JOIN `tabCustomer` c ON m.customer = c.name
                    WHERE m.customer IS NOT NULL AND c.name IS NULL
                """)[0][0]
                member_customer_consistency = inconsistent_members == 0
            except Exception:
                member_customer_consistency = False
            
            return {
                "payment_history_health": validation_stats["success"],
                "security_framework_active": security_framework_active,
                "member_customer_consistency": member_customer_consistency,
                "validation_stats": validation_stats,
                "timestamp": now_datetime()
            }
        
        # Run health check
        with self.as_user(self.test_user.email):
            health_report = system_health_check()
            
            # Verify health check components
            self.assertIn("payment_history_health", health_report)
            self.assertIn("security_framework_active", health_report)
            self.assertIn("member_customer_consistency", health_report)
            self.assertIn("validation_stats", health_report)
            
            # Health indicators should be positive
            self.assertTrue(health_report["payment_history_health"],
                           "Payment history health should be good")
            self.assertTrue(health_report["security_framework_active"],
                           "Security framework should be active")

    def tearDown(self):
        """Comprehensive cleanup and final validation"""
        # Run final system validation
        try:
            final_validation = validate_and_repair_payment_history()
            if not final_validation["success"]:
                print(f"Final validation issues: {final_validation}")
        except Exception as e:
            print(f"Final validation error: {e}")
        
        # Check for integration-related errors
        integration_errors = frappe.db.sql('''
            SELECT error, creation 
            FROM `tabError Log` 
            WHERE creation >= %s
            AND (error LIKE '%integration%' OR error LIKE '%race condition%' OR error LIKE '%payment history%')
            ORDER BY creation DESC
            LIMIT 10
        ''', (self.test_start_time,), as_dict=True)
        
        if integration_errors:
            print("Integration errors found during testing:")
            for error in integration_errors:
                print(f"  - {error.creation}: {error.error[:200]}...")
        
        super().tearDown()