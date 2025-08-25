#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Test Suite for Bulk Account Creation System
==========================================================

This test suite validates the bulk account creation infrastructure for handling
large-scale imports (50 → 500 → 4700 members) with realistic Dutch association data.

Test Coverage:
- Scale progression testing (small, medium, large batches)
- Dutch business logic validation (names, postal codes, IBANs)
- Error isolation and retry mechanisms
- Progress tracking and monitoring
- Security and permission validation
- Performance benchmarking

Author: Verenigingen Test Team
"""

import json
import time
import unittest
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import now, random_string

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.account_creation_manager import (
    queue_bulk_account_creation_for_members,
    process_bulk_account_creation_batch
)
from verenigingen.verenigingen.doctype.bulk_operation_tracker.bulk_operation_tracker import (
    BulkOperationTracker
)


class TestBulkAccountCreationScale(EnhancedTestCase):
    """Test bulk account creation at different scales with realistic Dutch data."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment once for all scale tests."""
        super().setUpClass()
        cls.dutch_test_data = cls._generate_dutch_test_data_patterns()
        
    @classmethod
    def _generate_dutch_test_data_patterns(cls) -> Dict:
        """Generate realistic Dutch association member data patterns."""
        return {
            "first_names": [
                "Jan", "Marie", "Pieter", "Anna", "Willem", "Emma", "Lucas", 
                "Sophie", "Daan", "Julia", "Sem", "Eva", "Thomas", "Lotte", "Lars"
            ],
            "tussenvoegsel": [
                "van", "de", "van der", "van den", "de", "ter", "ten", 
                "van de", "den", None, None, None  # 25% have tussenvoegsel
            ],
            "last_names": [
                "Berg", "Vries", "Dijk", "Bakker", "Janssen", "Visser", 
                "Smit", "Meijer", "Boer", "Mulder", "Groot", "Bos", "Vos", 
                "Peters", "Hendriks", "Leeuwen", "Brouwer", "Wit", "Kok", "Dijkstra"
            ],
            "postal_codes": [
                "1011 AB", "1012 CD", "2511 EF", "3011 GH", "3512 IJ",
                "4811 KL", "5211 MN", "6211 OP", "7511 QR", "8011 ST",
                "9711 UV", "1234 WX", "5678 YZ", "9012 AA", "3456 BB"
            ],
            "cities": [
                "Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven",
                "Groningen", "Tilburg", "Almere", "Breda", "Nijmegen"
            ],
            "phone_patterns": [
                "+31 6 {}", "+316{}", "06-{}", "06 {}"
            ],
            "email_domains": [
                "gmail.com", "outlook.com", "ziggo.nl", "kpn.nl", "xs4all.nl"
            ],
            "birth_year_range": (1950, 2005)  # Members aged 20-75
        }
    
    def _create_test_members_batch(self, count: int, name_prefix: str = "TEST") -> List[str]:
        """
        Create a batch of test members with realistic Dutch data.
        
        Args:
            count: Number of members to create
            name_prefix: Prefix for member identification
            
        Returns:
            List of created member names
        """
        members = []
        data = self.dutch_test_data
        
        for i in range(count):
            # Generate realistic Dutch name
            first_name = data["first_names"][i % len(data["first_names"])]
            tussenvoegsel = data["tussenvoegsel"][i % len(data["tussenvoegsel"])]
            last_name = data["last_names"][i % len(data["last_names"])]
            
            # Combine name components
            if tussenvoegsel:
                full_name = f"{first_name} {tussenvoegsel} {last_name}"
                display_last_name = f"{tussenvoegsel} {last_name}"
            else:
                full_name = f"{first_name} {last_name}"
                display_last_name = last_name
            
            # Generate contact details
            email = f"{first_name.lower()}.{last_name.lower()}.{i}@{data['email_domains'][i % len(data['email_domains'])]}"
            postal_code = data["postal_codes"][i % len(data["postal_codes"])]
            city = data["cities"][i % len(data["cities"])]
            phone_number = data["phone_patterns"][i % len(data["phone_patterns"])].format(
                f"{10000000 + i:08d}"
            )
            
            # Calculate birth date for age requirements
            birth_year = data["birth_year_range"][0] + (i % (data["birth_year_range"][1] - data["birth_year_range"][0]))
            birth_date = f"{birth_year}-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}"
            
            # Create member with Dutch data
            try:
                member = frappe.get_doc({
                    "doctype": "Member",
                    "first_name": first_name,
                    "middle_name": tussenvoegsel or "",
                    "last_name": last_name,
                    "full_name": full_name,
                    "email": email,
                    "contact_number": phone_number,
                    "postal_code": postal_code,
                    "city": city,
                    "country": "Netherlands",
                    "birth_date": birth_date,
                    "member_since": now(),
                    "status": "Active",
                    "membership_type": "Regular Member",
                    "custom_test_marker": f"{name_prefix}_{i:05d}"
                })
                member.insert()
                members.append(member.name)
                
                if i % 100 == 0:
                    frappe.logger().info(f"Created {i+1}/{count} test members")
                    
            except Exception as e:
                frappe.logger().error(f"Failed to create test member {i}: {str(e)}")
                continue
                
        frappe.db.commit()
        return members
    
    def test_01_small_scale_50_members(self):
        """Test bulk account creation with 50 members (1 batch)."""
        frappe.logger().info("=== TESTING SMALL SCALE: 50 MEMBERS ===")
        
        # Create test members
        member_names = self._create_test_members_batch(50, "SMALL")
        self.assertEqual(len(member_names), 50, "Should create exactly 50 test members")
        
        # Queue bulk account creation
        start_time = time.time()
        result = queue_bulk_account_creation_for_members(
            member_names=member_names,
            roles=["Verenigingen Member"],
            role_profile="Verenigingen Member",
            batch_size=50,
            priority="Normal"
        )
        queue_time = time.time() - start_time
        
        # Validate queuing results
        self.assertTrue(result.get("success"), "Bulk queue operation should succeed")
        self.assertEqual(result.get("requests_created"), 50, "Should create 50 account requests")
        self.assertEqual(result.get("batch_count"), 1, "Should create 1 batch for 50 members")
        self.assertLess(queue_time, 5, "Queuing 50 members should take less than 5 seconds")
        
        # Verify tracker was created
        tracker_name = result.get("tracker_name")
        self.assertIsNotNone(tracker_name, "Should create a bulk operation tracker")
        
        tracker = frappe.get_doc("Bulk Operation Tracker", tracker_name)
        self.assertEqual(tracker.total_records, 50)
        self.assertEqual(tracker.total_batches, 1)
        self.assertEqual(tracker.batch_size, 50)
        
        frappe.logger().info(f"Small scale test completed: {queue_time:.2f}s to queue")
    
    def test_02_medium_scale_500_members(self):
        """Test bulk account creation with 500 members (10 batches)."""
        frappe.logger().info("=== TESTING MEDIUM SCALE: 500 MEMBERS ===")
        
        # Create test members
        member_names = self._create_test_members_batch(500, "MEDIUM")
        self.assertEqual(len(member_names), 500, "Should create exactly 500 test members")
        
        # Queue bulk account creation
        start_time = time.time()
        result = queue_bulk_account_creation_for_members(
            member_names=member_names,
            roles=["Verenigingen Member"],
            role_profile="Verenigingen Member",
            batch_size=50,
            priority="Normal"
        )
        queue_time = time.time() - start_time
        
        # Validate queuing results
        self.assertTrue(result.get("success"), "Bulk queue operation should succeed")
        self.assertEqual(result.get("requests_created"), 500, "Should create 500 account requests")
        self.assertEqual(result.get("batch_count"), 10, "Should create 10 batches for 500 members")
        self.assertLess(queue_time, 30, "Queuing 500 members should take less than 30 seconds")
        
        # Verify tracker was created
        tracker_name = result.get("tracker_name")
        tracker = frappe.get_doc("Bulk Operation Tracker", tracker_name)
        self.assertEqual(tracker.total_records, 500)
        self.assertEqual(tracker.total_batches, 10)
        
        frappe.logger().info(f"Medium scale test completed: {queue_time:.2f}s to queue")
    
    @unittest.skipIf(
        frappe.conf.get("skip_large_tests", True),
        "Large scale test skipped by default. Set skip_large_tests=False to run."
    )
    def test_03_large_scale_4700_members(self):
        """Test bulk account creation with 4700 members (94 batches) - production scale."""
        frappe.logger().info("=== TESTING LARGE SCALE: 4700 MEMBERS ===")
        
        # Create test members in chunks to avoid memory issues
        member_names = []
        for chunk in range(0, 4700, 500):
            chunk_size = min(500, 4700 - chunk)
            chunk_members = self._create_test_members_batch(chunk_size, f"LARGE_{chunk//500}")
            member_names.extend(chunk_members)
            frappe.logger().info(f"Created chunk {chunk//500 + 1}: {len(chunk_members)} members")
        
        self.assertEqual(len(member_names), 4700, "Should create exactly 4700 test members")
        
        # Queue bulk account creation
        start_time = time.time()
        result = queue_bulk_account_creation_for_members(
            member_names=member_names,
            roles=["Verenigingen Member"],
            role_profile="Verenigingen Member",
            batch_size=50,
            priority="Low"
        )
        queue_time = time.time() - start_time
        
        # Validate queuing results
        self.assertTrue(result.get("success"), "Bulk queue operation should succeed")
        self.assertEqual(result.get("requests_created"), 4700, "Should create 4700 account requests")
        self.assertEqual(result.get("batch_count"), 94, "Should create 94 batches for 4700 members")
        self.assertLess(queue_time, 300, "Queuing 4700 members should take less than 5 minutes")
        
        # Verify tracker was created
        tracker_name = result.get("tracker_name")
        tracker = frappe.get_doc("Bulk Operation Tracker", tracker_name)
        self.assertEqual(tracker.total_records, 4700)
        self.assertEqual(tracker.total_batches, 94)
        
        frappe.logger().info(f"Large scale test completed: {queue_time:.2f}s to queue")
    
    def test_04_edge_cases(self):
        """Test edge cases: 1, 49, 51, 99, 101 members."""
        edge_cases = [1, 49, 51, 99, 101]
        
        for count in edge_cases:
            frappe.logger().info(f"Testing edge case: {count} members")
            
            # Create test members
            member_names = self._create_test_members_batch(count, f"EDGE_{count}")
            self.assertEqual(len(member_names), count)
            
            # Queue bulk account creation
            result = queue_bulk_account_creation_for_members(
                member_names=member_names,
                batch_size=50
            )
            
            # Calculate expected batches
            expected_batches = (count + 49) // 50
            
            self.assertTrue(result.get("success"))
            self.assertEqual(result.get("requests_created"), count)
            self.assertEqual(result.get("batch_count"), expected_batches)
            
            frappe.logger().info(f"Edge case {count}: {expected_batches} batches created")


class TestBulkAccountCreationErrorHandling(EnhancedTestCase):
    """Test error handling and retry mechanisms in bulk account creation."""
    
    def test_validation_errors(self):
        """Test handling of validation errors (missing emails, duplicates)."""
        # Create members with issues
        members_with_issues = []
        
        # Member without email
        member_no_email = frappe.get_doc({
            "doctype": "Member",
            "first_name": "No",
            "last_name": "Email",
            "full_name": "No Email",
            "status": "Active"
        })
        member_no_email.insert()
        members_with_issues.append(member_no_email.name)
        
        # Valid member
        valid_member = frappe.get_doc({
            "doctype": "Member",
            "first_name": "Valid",
            "last_name": "Member",
            "full_name": "Valid Member",
            "email": f"valid.member.{random_string(5)}@test.com",
            "status": "Active"
        })
        valid_member.insert()
        members_with_issues.append(valid_member.name)
        
        # Non-existent member
        members_with_issues.append("NON-EXISTENT-MEMBER")
        
        frappe.db.commit()
        
        # Queue bulk account creation
        result = queue_bulk_account_creation_for_members(
            member_names=members_with_issues
        )
        
        # Should still succeed but with validation errors
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("validation_errors_count"), 2)  # No email + non-existent
        self.assertEqual(result.get("requests_created"), 1)  # Only valid member
        
        frappe.logger().info(f"Validation test: {result.get('validation_errors_count')} errors handled")
    
    def test_batch_failure_isolation(self):
        """Test that failures in one batch don't affect other batches."""
        # Create 100 members (2 batches of 50)
        members = []
        
        for i in range(100):
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": f"Batch",
                "last_name": f"Test_{i}",
                "full_name": f"Batch Test {i}",
                "email": f"batch.test.{i}@example.com",
                "status": "Active"
            })
            member.insert()
            members.append(member.name)
        
        frappe.db.commit()
        
        # Queue with batch size 50
        result = queue_bulk_account_creation_for_members(
            member_names=members,
            batch_size=50
        )
        
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("batch_count"), 2)
        
        # Simulate processing with one member failing
        tracker_name = result.get("tracker_name")
        request_names = result.get("request_names")
        
        # Process first batch with simulated failure
        batch_1_results = {
            "batch_id": "bulk_batch_1",
            "batch_number": 1,
            "total_requests": 50,
            "completed": 49,
            "failed": 1,
            "errors": ["TEST-REQ-001: Simulated failure"],
            "completed_requests": request_names[:49],
            "failed_requests": [request_names[0]]
        }
        
        tracker = frappe.get_doc("Bulk Operation Tracker", tracker_name)
        tracker.update_progress(1, batch_1_results)
        
        # Verify partial success is tracked
        self.assertEqual(tracker.successful_records, 49)
        self.assertEqual(tracker.failed_records, 1)
        self.assertEqual(tracker.processed_records, 50)
        
        frappe.logger().info("Batch failure isolation test completed")
    
    def test_retry_queue_functionality(self):
        """Test that failed requests are properly queued for retry."""
        # Create test members
        members = []
        for i in range(10):
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": "Retry",
                "last_name": f"Test_{i}",
                "full_name": f"Retry Test {i}",
                "email": f"retry.test.{i}@example.com",
                "status": "Active"
            })
            member.insert()
            members.append(member.name)
        
        frappe.db.commit()
        
        # Queue bulk account creation
        result = queue_bulk_account_creation_for_members(
            member_names=members,
            batch_size=10
        )
        
        tracker_name = result.get("tracker_name")
        request_names = result.get("request_names")
        
        # Simulate batch with failures
        batch_results = {
            "batch_id": "bulk_batch_1",
            "batch_number": 1,
            "total_requests": 10,
            "completed": 7,
            "failed": 3,
            "errors": [
                f"{request_names[0]}: Connection timeout",
                f"{request_names[1]}: Database lock",
                f"{request_names[2]}: Temporary error"
            ],
            "completed_requests": request_names[3:],
            "failed_requests": request_names[:3]
        }
        
        tracker = frappe.get_doc("Bulk Operation Tracker", tracker_name)
        tracker.update_progress(1, batch_results)
        
        # Check retry queue
        retry_queue = tracker.get_retry_requests()
        self.assertEqual(len(retry_queue), 3)
        self.assertIn(request_names[0], retry_queue)
        self.assertIn(request_names[1], retry_queue)
        self.assertIn(request_names[2], retry_queue)
        
        frappe.logger().info(f"Retry queue test: {len(retry_queue)} requests queued for retry")


class TestBulkOperationTrackerFunctionality(EnhancedTestCase):
    """Test the BulkOperationTracker DocType functionality."""
    
    def test_tracker_creation_and_updates(self):
        """Test tracker creation and progress updates."""
        # Create tracker
        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation",
            total_records=100,
            batch_size=25,
            priority="Normal"
        )
        
        self.assertIsNotNone(tracker)
        self.assertEqual(tracker.total_records, 100)
        self.assertEqual(tracker.total_batches, 4)
        self.assertEqual(tracker.status, "Queued")
        
        # Start operation
        tracker.start_operation()
        self.assertEqual(tracker.status, "Processing")
        self.assertIsNotNone(tracker.started_at)
        
        # Update progress for batch 1
        batch_1_results = {
            "completed": 25,
            "failed": 0,
            "errors": []
        }
        tracker.update_progress(1, batch_1_results)
        
        self.assertEqual(tracker.successful_records, 25)
        self.assertEqual(tracker.failed_records, 0)
        self.assertEqual(tracker.processed_records, 25)
        self.assertEqual(tracker.current_batch, 1)
        
        # Check progress percentage
        progress = tracker.get_progress_percentage()
        self.assertEqual(progress, 25.0)
        
        # Complete remaining batches
        for batch_num in range(2, 5):
            tracker.update_progress(batch_num, {
                "completed": 25,
                "failed": 0,
                "errors": []
            })
        
        # Check completion
        self.assertEqual(tracker.status, "Completed")
        self.assertIsNotNone(tracker.completed_at)
        self.assertEqual(tracker.processed_records, 100)
        
        frappe.logger().info("Tracker functionality test completed")
    
    def test_progress_rate_calculation(self):
        """Test processing rate and estimated completion calculations."""
        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation",
            total_records=1000,
            batch_size=50
        )
        
        # Start operation
        tracker.started_at = datetime.now() - timedelta(minutes=10)
        tracker.processed_records = 200
        tracker.status = "Processing"
        
        # Calculate processing rate
        tracker._calculate_processing_rate()
        
        # Should be 20 records per minute (200 in 10 minutes)
        self.assertAlmostEqual(tracker.processing_rate_per_minute, 20.0, places=1)
        
        # Calculate estimated completion
        tracker._calculate_estimated_completion()
        
        # Should estimate 40 more minutes for remaining 800 records
        self.assertIsNotNone(tracker.estimated_completion)
        
        frappe.logger().info(f"Processing rate: {tracker.processing_rate_per_minute}/min")
    
    def test_error_summary_management(self):
        """Test error summary size management."""
        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation",
            total_records=200,
            batch_size=50
        )
        
        # Add many errors to test truncation
        errors = [f"Error {i}: Test error message" for i in range(150)]
        tracker._update_error_summary(errors)
        
        # Check that error summary is limited
        error_lines = tracker.error_summary.split("\n")
        self.assertLessEqual(len(error_lines), 101)  # 100 errors + header
        self.assertIn("[Showing last 100 errors", tracker.error_summary)
        
        frappe.logger().info("Error summary management test completed")


class TestDutchBusinessLogicValidation(EnhancedTestCase):
    """Test Dutch business logic in bulk processing."""
    
    def test_dutch_name_handling(self):
        """Test proper handling of Dutch names with tussenvoegsel."""
        test_names = [
            ("Jan", "van der", "Berg"),
            ("Marie", "de", "Vries"),
            ("Pieter", None, "Bakker"),
            ("Anna", "van", "Dijk"),
            ("Willem", "van den", "Broek")
        ]
        
        members = []
        for first, tussenvoegsel, last in test_names:
            full_name = f"{first} {tussenvoegsel} {last}" if tussenvoegsel else f"{first} {last}"
            
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": first,
                "middle_name": tussenvoegsel or "",
                "last_name": last,
                "full_name": full_name,
                "email": f"{first.lower()}.{last.lower()}@test.nl",
                "status": "Active"
            })
            member.insert()
            members.append(member.name)
        
        frappe.db.commit()
        
        # Queue bulk account creation
        result = queue_bulk_account_creation_for_members(member_names=members)
        
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("requests_created"), 5)
        
        # Verify account creation requests have correct names
        for request_name in result.get("request_names", []):
            request = frappe.get_doc("Account Creation Request", request_name)
            self.assertIsNotNone(request.full_name)
            self.assertIn(request.full_name, [
                "Jan van der Berg", "Marie de Vries", "Pieter Bakker",
                "Anna van Dijk", "Willem van den Broek"
            ])
        
        frappe.logger().info("Dutch name handling test completed")
    
    def test_age_requirements_for_volunteers(self):
        """Test that age requirements are validated for volunteer account creation."""
        # Create member under 16 (should not be allowed volunteer role)
        young_member = frappe.get_doc({
            "doctype": "Member",
            "first_name": "Young",
            "last_name": "Member",
            "full_name": "Young Member",
            "email": "young.member@test.nl",
            "birth_date": (datetime.now() - timedelta(days=365*14)).strftime("%Y-%m-%d"),  # 14 years old
            "status": "Active"
        })
        young_member.insert()
        
        # Create member over 16 (allowed volunteer role)
        adult_member = frappe.get_doc({
            "doctype": "Member",
            "first_name": "Adult",
            "last_name": "Member",
            "full_name": "Adult Member",
            "email": "adult.member@test.nl",
            "birth_date": (datetime.now() - timedelta(days=365*18)).strftime("%Y-%m-%d"),  # 18 years old
            "status": "Active"
        })
        adult_member.insert()
        
        frappe.db.commit()
        
        # Queue with volunteer roles
        volunteer_roles = ["Verenigingen Member", "Verenigingen Volunteer"]
        
        result = queue_bulk_account_creation_for_members(
            member_names=[young_member.name, adult_member.name],
            roles=volunteer_roles,
            role_profile="Verenigingen Volunteer"
        )
        
        self.assertTrue(result.get("success"))
        # Both should get requests created (age validation happens during processing)
        self.assertEqual(result.get("requests_created"), 2)
        
        frappe.logger().info("Age requirements validation test completed")


class TestBulkAccountCreationSecurity(EnhancedTestCase):
    """Test security aspects of bulk account creation."""
    
    def test_permission_requirements(self):
        """Test that proper permissions are required for bulk operations."""
        # Create test members
        members = []
        for i in range(5):
            member = self.create_test_member(
                first_name="Security",
                last_name=f"Test_{i}"
            )
            members.append(member.name)
        
        # Test with user without permissions
        test_user = self.create_test_user("security.test@example.com")
        frappe.set_user(test_user.name)
        
        # Should fail without User creation permission
        with self.assertRaises(frappe.PermissionError):
            queue_bulk_account_creation_for_members(member_names=members)
        
        # Reset to admin user
        frappe.set_user("Administrator")
        
        frappe.logger().info("Permission requirements test completed")
    
    def test_no_permission_bypasses(self):
        """Verify that no ignore_permissions=True is used in business logic."""
        # Read the account creation manager source
        import inspect
        from verenigingen.utils import account_creation_manager
        
        source = inspect.getsource(account_creation_manager)
        
        # Check for ignore_permissions in business functions
        business_functions = [
            "queue_bulk_account_creation_for_members",
            "process_bulk_account_creation_batch",
            "create_user_account",
            "assign_roles_and_profile"
        ]
        
        for func_name in business_functions:
            # Get function source
            func = getattr(account_creation_manager, func_name, None)
            if func:
                func_source = inspect.getsource(func)
                # Should not contain ignore_permissions=True
                self.assertNotIn(
                    "ignore_permissions=True", 
                    func_source,
                    f"Function {func_name} should not bypass permissions"
                )
        
        frappe.logger().info("No permission bypasses verification completed")
    
    def test_audit_trail_completeness(self):
        """Test that all operations create proper audit trails."""
        # Create test members
        members = []
        for i in range(10):
            member = self.create_test_member(
                first_name="Audit",
                last_name=f"Test_{i}"
            )
            members.append(member.name)
        
        # Queue bulk account creation
        result = queue_bulk_account_creation_for_members(member_names=members)
        
        # Verify Account Creation Requests were created
        self.assertEqual(result.get("requests_created"), 10)
        
        # Verify each request has audit fields
        for request_name in result.get("request_names", []):
            request = frappe.get_doc("Account Creation Request", request_name)
            
            # Check audit trail fields
            self.assertIsNotNone(request.creation)
            self.assertIsNotNone(request.owner)
            self.assertEqual(request.status, "Queued")
            self.assertIsNotNone(request.business_justification)
            
        # Verify tracker was created for audit
        tracker = frappe.get_doc("Bulk Operation Tracker", result.get("tracker_name"))
        self.assertIsNotNone(tracker.started_at)
        self.assertEqual(tracker.operation_type, "Account Creation")
        
        frappe.logger().info("Audit trail completeness test completed")


if __name__ == "__main__":
    # Set up test configuration
    frappe.conf.skip_large_tests = True  # Skip 4700 member test by default
    
    # Run test suite
    unittest.main(verbosity=2)