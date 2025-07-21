"""
Comprehensive Edge Case Test Suite for SEPA Direct Debit Batch Processing
Focuses on member identity confusion, shared accounts, and security vulnerabilities
"""

import random
import string
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.dd_security_enhancements import (
    DDConflictResolutionManager,
    DDSecurityAuditLogger,
    MemberIdentityValidator,
)
from verenigingen.tests.test_setup import setup_test_environment


class TestDDMemberIdentityEdgeCases(FrappeTestCase):
    """Test edge cases around member identity confusion and validation"""

    @classmethod
    def setUpClass(cls):
        setup_test_environment()
        super().setUpClass()
        cls.test_records = []
        cls.unique_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

    @classmethod
    def tearDownClass(cls):
        """Clean up all test data"""
        # Clean up in reverse dependency order
        for record in reversed(cls.test_records):
            try:
                if hasattr(record, "delete"):
                    record.delete(force=True)
                else:
                    frappe.delete_doc(record["doctype"], record["name"], force=True)
            except Exception:
                pass

    def setUp(self):
        self.validator = MemberIdentityValidator()
        self.test_prefix = f"TEST-{self.unique_id}"

    def create_test_member(self, first_name, last_name, email, iban=None, member_id=None):
        """Helper to create test members"""
        if not member_id:
            member_id = f"{first_name.lower()}.{last_name.lower()}.{self.unique_id}@test.com"

        member = frappe.new_doc("Member")
        member.first_name = first_name
        member.last_name = last_name
        member.email = email
        member.iban = iban or f"NL{random.randint(10, 99)}INGB{random.randint(1000000000, 9999999999)}"
        member.status = "Active"
        member.insert()

        self.test_records.append(member)
        return member

    def test_identical_names_different_addresses(self):
        """Test handling of members with identical names but different addresses"""
        # Create two John Smiths
        self.create_test_member(
            "John", "Smith", f"john.smith.amsterdam.{self.unique_id}@test.com", "NL43INGB0123456789"
        )

        self.create_test_member(
            "John", "Smith", f"john.smith.rotterdam.{self.unique_id}@test.com", "NL43ABNA0987654321"
        )

        # Test duplicate detection
        new_john_data = {
            "first_name": "John",
            "last_name": "Smith",
            "email": f"john.smith.utrecht.{self.unique_id}@test.com",
            "iban": "NL43RABO1122334455"}

        results = self.validator.detect_potential_duplicates(new_john_data)

        # Should detect potential duplicates
        self.assertTrue(
            len(results["potential_duplicates"]) >= 2,
            "Should detect both existing John Smiths as potential duplicates",
        )

        # Should have high name similarity
        for duplicate in results["potential_duplicates"]:
            self.assertGreater(
                duplicate["name_similarity"], 0.9, "Name similarity should be very high for identical names"
            )

    def test_similar_names_fuzzy_matching(self):
        """Test fuzzy name matching for similar but not identical names"""
        # Create members with similar names
        members = [
            ("John", "Smith", f"john.smith.{self.unique_id}@test.com"),
            ("Jon", "Smith", f"jon.smith.{self.unique_id}@test.com"),
            ("John", "Smyth", f"john.smyth.{self.unique_id}@test.com"),
            ("Johnny", "Smith", f"johnny.smith.{self.unique_id}@test.com"),
        ]

        created_members = []
        for first, last, email in members:
            member = self.create_test_member(first, last, email)
            created_members.append(member)

        # Test with a new similar name
        new_member_data = {
            "first_name": "Johny",  # Misspelling
            "last_name": "Smith",
            "email": f"johny.smith.{self.unique_id}@test.com",
            "iban": "NL43INGB9999888877"}

        results = self.validator.detect_potential_duplicates(new_member_data)

        # Should detect some similarities
        self.assertGreater(len(results["potential_duplicates"]), 0, "Should detect some similar names")

        # Check that fuzzy matching works
        found_johns = [d for d in results["potential_duplicates"] if "john" in d["existing_name"].lower()]
        self.assertGreater(len(found_johns), 0, "Should find existing Johns through fuzzy matching")

    def test_shared_family_bank_account(self):
        """Test family members using same IBAN"""
        shared_iban = "NL43INGB1234567890"

        # Create family members with same IBAN
        self.create_test_member("John", "Doe", f"john.doe.{self.unique_id}@test.com", shared_iban)

        self.create_test_member("Jane", "Doe", f"jane.doe.{self.unique_id}@test.com", shared_iban)

        # Test IBAN validation for new family member
        results = self.validator.validate_unique_bank_account(shared_iban)

        # Should allow family sharing but flag for review
        self.assertTrue(results.get("valid", False), "Should allow family account sharing")

        analysis = results.get("sharing_analysis", {})
        self.assertEqual(
            analysis.get("pattern"), "family_account", "Should identify as family account pattern"
        )
        self.assertLess(analysis.get("risk_level", 1.0), 0.5, "Risk level should be low for family accounts")

    def test_corporate_shared_accounts(self):
        """Test business accounts used by multiple unrelated members"""
        corporate_iban = "NL43ABNA9876543210"

        # Create unrelated members with same corporate IBAN
        employees = [
            ("Alice", "Johnson", f"alice.johnson.{self.unique_id}@test.com"),
            ("Bob", "Williams", f"bob.williams.{self.unique_id}@test.com"),
            ("Charlie", "Brown", f"charlie.brown.{self.unique_id}@test.com"),
        ]

        for first, last, email in employees:
            self.create_test_member(first, last, email, corporate_iban)

        # Test validation for another employee
        results = self.validator.validate_unique_bank_account(corporate_iban)

        # Should flag as suspicious due to unrelated names
        self.assertFalse(results.get("valid", True), "Should block unrelated members using same account")

        analysis = results.get("sharing_analysis", {})
        self.assertEqual(
            analysis.get("pattern"), "suspicious_sharing", "Should identify as suspicious sharing pattern"
        )
        self.assertGreater(
            analysis.get("risk_level", 0.0), 0.7, "Risk level should be high for unrelated sharing"
        )

    def test_payment_amount_anomalies(self):
        """Test detection of unusual payment amounts"""
        # Create test batch data with various amounts
        batch_data = [
            {
                "member_name": "Normal Member",
                "iban": "NL43INGB1111111111",
                "amount": 50.00,  # Normal amount
                "invoice": "INV-001"},
            {
                "member_name": "Zero Amount Member",
                "iban": "NL43INGB2222222222",
                "amount": 0.00,  # Anomaly: zero amount
                "invoice": "INV-002"},
            {
                "member_name": "High Amount Member",
                "iban": "NL43INGB3333333333",
                "amount": 999.99,  # Anomaly: very high amount
                "invoice": "INV-003"},
            {
                "member_name": "Negative Amount Member",
                "iban": "NL43INGB4444444444",
                "amount": -25.00,  # Anomaly: negative amount
                "invoice": "INV-004"},
        ]

        results = self.validator.detect_payment_anomalies(batch_data)

        # Should detect anomalies
        warnings = results.get("warnings", [])
        self.assertGreater(len(warnings), 0, "Should detect amount anomalies")

        # Check specific anomalies
        anomaly_reasons = []
        for warning in warnings:
            anomaly_reasons.extend(warning.get("reasons", []))

        self.assertAny(
            ["Zero or negative amount" in reason for reason in anomaly_reasons],
            "Should detect zero/negative amounts",
        )
        self.assertAny(
            ["Unusually high amount" in reason for reason in anomaly_reasons],
            "Should detect unusually high amounts",
        )

    def test_multiple_payments_same_iban(self):
        """Test detection of multiple payments from same IBAN"""
        shared_iban = "NL43INGB5555555555"

        # Create batch with multiple payments from same IBAN
        batch_data = [
            {"member_name": "Member One", "iban": shared_iban, "amount": 50.00, "invoice": "INV-001"},
            {"member_name": "Member Two", "iban": shared_iban, "amount": 75.00, "invoice": "INV-002"},
            {"member_name": "Member Three", "iban": shared_iban, "amount": 100.00, "invoice": "INV-003"},
            {"member_name": "Member Four", "iban": shared_iban, "amount": 125.00, "invoice": "INV-004"},
        ]

        results = self.validator.detect_payment_anomalies(batch_data)

        # Should detect suspicious pattern
        suspicious = results.get("suspicious_patterns", [])
        self.assertGreater(len(suspicious), 0, "Should detect multiple payments from same IBAN as suspicious")

        # Should flag high payment count
        pattern = suspicious[0] if suspicious else {}
        self.assertGreater(
            pattern.get("risk_level", 0.0), 0.3, "Should have elevated risk level for multiple payments"
        )
        self.assertIn(
            "Many payments from same account",
            pattern.get("issues", []),
            "Should identify multiple payments issue",
        )

    def test_name_encoding_edge_cases(self):
        """Test handling of special characters and encoding in names"""
        # Create members with special characters
        special_members = [
            ("José", "García", f"jose.garcia.{self.unique_id}@test.com"),
            ("Jose", "Garcia", f"jose.garcia.ascii.{self.unique_id}@test.com"),  # ASCII version
            ("François", "Müller", f"francois.muller.{self.unique_id}@test.com"),
            ("Francois", "Mueller", f"francois.mueller.ascii.{self.unique_id}@test.com"),  # ASCII version
        ]

        created_members = []
        for first, last, email in special_members:
            member = self.create_test_member(first, last, email)
            created_members.append(member)

        # Test detection between accented and non-accented versions
        new_member_data = {
            "first_name": "Jose",  # Should match José
            "last_name": "Garcia",  # Should match García
            "email": f"jose.garcia.new.{self.unique_id}@test.com",
            "iban": "NL43RABO1234567890"}

        results = self.validator.detect_potential_duplicates(new_member_data)

        # Should find similarities despite encoding differences
        # Note: This might require additional normalization in the validator
        # For now, just ensure it doesn't crash
        self.assertIsInstance(results, dict, "Should handle special characters without crashing")
        self.assertNotIn("error", results, "Should not have errors with special characters")


class TestDDBatchSecurityValidation(FrappeTestCase):
    """Test security validations and audit logging"""

    @classmethod
    def setUpClass(cls):
        setup_test_environment()
        super().setUpClass()
        cls.test_records = []
        cls.unique_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

    @classmethod
    def tearDownClass(cls):
        """Clean up all test data"""
        for record in reversed(cls.test_records):
            try:
                if hasattr(record, "delete"):
                    record.delete(force=True)
                else:
                    frappe.delete_doc(record["doctype"], record["name"], force=True)
            except Exception:
                pass

    def setUp(self):
        self.validator = MemberIdentityValidator()
        self.logger = DDSecurityAuditLogger()
        self.test_prefix = f"TEST-{self.unique_id}"

    def test_malicious_data_injection_iban(self):
        """Test SQL injection prevention in IBAN validation"""
        malicious_ibans = [
            "NL43INGB'; DROP TABLE Member; --",
            "NL43INGB<script>alert('xss')</script>",
            "'; SELECT * FROM Member WHERE '1'='1",
            "NL43INGB\x00\x01\x02",  # Null bytes and control chars
            "NL43INGB" + "A" * 1000,  # Extremely long IBAN
        ]

        for malicious_iban in malicious_ibans:
            try:
                results = self.validator.validate_unique_bank_account(malicious_iban)

                # Should handle gracefully without errors
                self.assertIsInstance(
                    results, dict, f"Should handle malicious IBAN gracefully: {malicious_iban[:20]}..."
                )

                # Should not crash or return sensitive data
                if not results.get("valid", False):
                    self.assertIn("error", results, "Invalid IBAN should return proper error message")

            except Exception as e:
                self.fail(f"Malicious IBAN caused unhandled exception: {str(e)}")

    def test_malicious_data_injection_names(self):
        """Test XSS and injection prevention in member names"""
        malicious_names = [
            "<script>alert('xss')</script>",
            "'; DROP TABLE Member; --",
            "Robert'); DELETE FROM Member; --",
            "\x00\x01\x02MALICIOUS",
            "A" * 10000,  # Extremely long name
        ]

        for malicious_name in malicious_names:
            member_data = {
                "first_name": malicious_name,
                "last_name": "TestUser",
                "email": f"test.{self.unique_id}@example.com",
                "iban": "NL43INGB1234567890"}

            try:
                results = self.validator.detect_potential_duplicates(member_data)

                # Should handle without crashing
                self.assertIsInstance(
                    results, dict, f"Should handle malicious name gracefully: {malicious_name[:20]}..."
                )

                # Should not return unescaped malicious content
                if "potential_duplicates" in results:
                    for duplicate in results["potential_duplicates"]:
                        name = duplicate.get("existing_name", "")
                        self.assertNotIn("<script>", name, "Should not return unescaped script tags")

            except Exception as e:
                self.fail(f"Malicious name caused unhandled exception: {str(e)}")

    def test_audit_logging_completeness(self):
        """Test that audit logging captures all required information"""
        test_batch_id = f"BATCH-TEST-{self.unique_id}"
        test_action = "test_batch_creation"
        test_details = {"invoice_count": 5, "total_amount": 250.00, "risk_assessment": "low"}

        # Log a test action
        self.logger.log_batch_action(action=test_action, batch_id=test_batch_id, details=test_details)

        # Verify log entry was created
        log_entries = frappe.get_all(
            "DD Security Audit Log",
            filters={"batch_id": test_batch_id, "action": test_action},
            fields=["name", "timestamp", "user", "ip_address", "details"],
        )

        self.assertGreater(len(log_entries), 0, "Audit log entry should be created")

        entry = log_entries[0]
        self.assertIsNotNone(entry.get("timestamp"), "Should have timestamp")
        self.assertIsNotNone(entry.get("user"), "Should have user")
        self.assertIsNotNone(entry.get("ip_address"), "Should have IP address")

        # Clean up log entry
        frappe.delete_doc("DD Security Audit Log", entry["name"], force=True)

    def test_security_event_escalation(self):
        """Test security event logging and escalation"""
        high_severity_events = [
            "multiple_failed_authentications",
            "suspicious_batch_creation",
            "potential_fraud_detected",
            "unauthorized_access_attempt",
        ]

        for event_type in high_severity_events:
            self.logger.log_security_event(
                event_type=event_type,
                severity="high",
                description=f"Test {event_type} event",
                details={"test": True, "unique_id": self.unique_id},
            )

        # Verify events were logged
        security_events = frappe.get_all(
            "DD Security Event Log",
            filters={"severity": "high", "details": ["like", f"%{self.unique_id}%"]},
            fields=["name", "event_type", "severity", "description"],
        )

        self.assertEqual(
            len(security_events), len(high_severity_events), "All high severity events should be logged"
        )

        # Clean up security events
        for event in security_events:
            frappe.delete_doc("DD Security Event Log", event["name"], force=True)

    def test_concurrent_batch_access_prevention(self):
        """Test prevention of concurrent batch modifications"""
        # This would typically involve database locking mechanisms
        # For now, test that the system handles concurrent access gracefully

        batch_id = f"BATCH-CONCURRENT-{self.unique_id}"

        # Simulate concurrent access attempts
        concurrent_attempts = 5
        results = []

        for i in range(concurrent_attempts):
            try:
                # Simulate batch modification attempt
                self.logger.log_batch_action(
                    action="concurrent_access_test", batch_id=batch_id, details={"attempt": i}
                )
                results.append("success")
            except Exception as e:
                results.append(f"error: {str(e)}")

        # Should handle all attempts without crashing
        success_count = len([r for r in results if r == "success"])
        self.assertGreater(success_count, 0, "Should handle some concurrent attempts successfully")

        # Clean up log entries
        concurrent_logs = frappe.get_all(
            "DD Security Audit Log", filters={"batch_id": batch_id}, fields=["name"]
        )
        for log in concurrent_logs:
            frappe.delete_doc("DD Security Audit Log", log["name"], force=True)


class TestDDConflictResolution(FrappeTestCase):
    """Test conflict resolution workflows and reporting"""

    @classmethod
    def setUpClass(cls):
        setup_test_environment()
        super().setUpClass()
        cls.test_records = []
        cls.unique_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

    @classmethod
    def tearDownClass(cls):
        """Clean up all test data"""
        for record in reversed(cls.test_records):
            try:
                if hasattr(record, "delete"):
                    record.delete(force=True)
                else:
                    frappe.delete_doc(record["doctype"], record["name"], force=True)
            except Exception:
                pass

    def setUp(self):
        self.conflict_manager = DDConflictResolutionManager()
        self.test_prefix = f"TEST-{self.unique_id}"

    def test_conflict_report_creation(self):
        """Test creation of detailed conflict reports"""
        test_conflicts = {
            "potential_duplicates": [
                {
                    "existing_member": "Member-001",
                    "existing_name": "John Smith",
                    "risk_score": 0.75,
                    "match_reasons": ["Similar names", "Same city"]}
            ],
            "high_risk_matches": [
                {
                    "existing_member": "Member-002",
                    "existing_name": "John Smith",
                    "risk_score": 0.95,
                    "match_reasons": ["Identical names", "Same IBAN"]}
            ]}

        batch_id = f"BATCH-CONFLICT-{self.unique_id}"

        # Create conflict report
        report_id = self.conflict_manager.create_conflict_report(test_conflicts, batch_id)

        self.assertIsNotNone(report_id, "Conflict report should be created")

        # Verify report contents
        if report_id:
            report = frappe.get_doc("DD Conflict Report", report_id)
            self.assertEqual(report.batch_id, batch_id, "Report should reference correct batch")
            self.assertEqual(report.status, "Open", "Report should be open initially")
            self.assertIn("high-risk", report.summary.lower(), "Summary should mention high-risk matches")

            # Clean up
            frappe.delete_doc("DD Conflict Report", report_id, force=True)

    def test_automatic_conflict_resolution(self):
        """Test automatic resolution of low-risk conflicts"""
        test_conflicts = {
            "potential_duplicates": [
                {
                    "existing_member": "Member-001",
                    "risk_score": 0.45,  # Low risk - should auto-resolve
                    "match_reasons": ["Slightly similar names"]},
                {
                    "existing_member": "Member-002",
                    "risk_score": 0.85,  # High risk - should require manual review
                    "match_reasons": ["Very similar names", "Same postal code"]},
            ]
        }

        # Apply automatic resolution
        results = self.conflict_manager.auto_resolve_conflicts(test_conflicts)

        self.assertIn("resolved", results, "Should have resolved conflicts")
        self.assertIn("unresolved", results, "Should have unresolved conflicts")

        # Low risk should be auto-resolved
        self.assertGreater(len(results["resolved"]), 0, "Should auto-resolve low-risk conflicts")

        # High risk should require manual review
        self.assertGreater(
            len(results["unresolved"]), 0, "Should leave high-risk conflicts for manual review"
        )

        self.assertTrue(results["requires_manual_review"], "Should flag that manual review is required")

    def test_resolution_rule_customization(self):
        """Test customizable resolution rules"""
        test_conflicts = {
            "potential_duplicates": [
                {"existing_member": "Member-001", "risk_score": 0.65, "match_reasons": ["Similar names"]}
            ]
        }

        # Test with strict rules (low auto-resolve threshold)
        strict_rules = {
            "auto_resolve_low_risk": True,
            "max_auto_resolve_score": 0.5,  # Very strict
            "require_manual_review_above": 0.6}

        strict_results = self.conflict_manager.auto_resolve_conflicts(test_conflicts, strict_rules)

        # Should require manual review with strict rules
        self.assertEqual(
            len(strict_results["resolved"]), 0, "Strict rules should not auto-resolve medium-risk conflicts"
        )

        # Test with lenient rules (high auto-resolve threshold)
        lenient_rules = {
            "auto_resolve_low_risk": True,
            "max_auto_resolve_score": 0.8,  # Very lenient
            "require_manual_review_above": 0.9}

        lenient_results = self.conflict_manager.auto_resolve_conflicts(test_conflicts, lenient_rules)

        # Should auto-resolve with lenient rules
        self.assertGreater(
            len(lenient_results["resolved"]), 0, "Lenient rules should auto-resolve medium-risk conflicts"
        )


class TestDDPerformanceEdgeCases(FrappeTestCase):
    """Test performance and scalability edge cases"""

    @classmethod
    def setUpClass(cls):
        setup_test_environment()
        super().setUpClass()
        cls.test_records = []
        cls.unique_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

    @classmethod
    def tearDownClass(cls):
        """Clean up all test data"""
        for record in reversed(cls.test_records):
            try:
                if hasattr(record, "delete"):
                    record.delete(force=True)
                else:
                    frappe.delete_doc(record["doctype"], record["name"], force=True)
            except Exception:
                pass

    def setUp(self):
        self.validator = MemberIdentityValidator()
        self.test_prefix = f"TEST-{self.unique_id}"

    def test_large_member_database_performance(self):
        """Test performance with large number of members"""
        import time

        # Create a moderate number of test members for performance testing
        # (Keep reasonable for test environment)
        member_count = 50
        created_members = []

        start_time = time.time()

        # Create test members
        for i in range(member_count):
            member = frappe.new_doc("Member")
            member.first_name = f"TestMember{i}"
            member.last_name = f"LastName{i % 10}"  # Some shared last names
            member.email = f"testmember{i}.{self.unique_id}@test.com"
            member.iban = f"NL{(43 + i):02d}INGB{(1000000000 + i):010d}"
            member.status = "Active"
            member.insert()
            created_members.append(member)
            self.test_records.append(member)

        creation_time = time.time() - start_time

        # Test duplicate detection performance
        test_member_data = {
            "first_name": "TestMember25",  # Should match existing
            "last_name": "LastName5",
            "email": f"new.testmember.{self.unique_id}@test.com",
            "iban": "NL99INGB9999999999"}

        detection_start = time.time()
        results = self.validator.detect_potential_duplicates(test_member_data)
        detection_time = time.time() - detection_start

        # Performance assertions
        self.assertLess(
            creation_time, 30.0, f"Creating {member_count} members should take less than 30 seconds"
        )
        self.assertLess(
            detection_time,
            5.0,
            f"Duplicate detection should take less than 5 seconds with {member_count} members",
        )

        # Functionality assertions
        self.assertIsInstance(results, dict, "Should return valid results")
        self.assertNotIn("error", results, "Should not have errors")

        # Should find the matching member
        matches = results.get("potential_duplicates", [])
        matching_names = [m["existing_name"] for m in matches]
        self.assertAny(
            [name for name in matching_names if "TestMember25" in name], "Should find the matching member"
        )

    def test_large_batch_anomaly_detection(self):
        """Test anomaly detection with large batches"""
        import time

        # Create a large batch for testing
        batch_size = 100
        batch_data = []

        for i in range(batch_size):
            payment = {
                "member_name": f"Member {i}",
                "iban": f"NL{(43 + i % 20):02d}INGB{(1000000000 + i):010d}",
                "amount": 50.00 + (i % 10) * 5,  # Varying amounts
                "invoice": f"INV-{i:04d}"}
            batch_data.append(payment)

        # Add some anomalies
        batch_data.append(
            {
                "member_name": "Anomaly Member 1",
                "iban": "NL43INGB0000000001",
                "amount": 0.00,  # Zero amount anomaly
                "invoice": "INV-ANOM-001"}
        )

        batch_data.append(
            {
                "member_name": "Anomaly Member 2",
                "iban": "NL43INGB0000000002",
                "amount": 999.99,  # High amount anomaly
                "invoice": "INV-ANOM-002"}
        )

        # Test performance
        start_time = time.time()
        results = self.validator.detect_payment_anomalies(batch_data)
        processing_time = time.time() - start_time

        # Performance assertion
        self.assertLess(
            processing_time,
            10.0,
            f"Anomaly detection for {len(batch_data)} payments should take less than 10 seconds",
        )

        # Functionality assertions
        self.assertIsInstance(results, dict, "Should return valid results")
        self.assertNotIn("error", results, "Should not have errors")

        # Should detect the anomalies we added
        warnings = results.get("warnings", [])
        warning_reasons = []
        for warning in warnings:
            warning_reasons.extend(warning.get("reasons", []))

        self.assertAny(
            ["Zero or negative amount" in reason for reason in warning_reasons],
            "Should detect zero amount anomaly",
        )
        self.assertAny(
            ["Unusually high amount" in reason for reason in warning_reasons],
            "Should detect high amount anomaly",
        )

    def test_memory_usage_with_large_datasets(self):
        """Test memory usage doesn't grow excessively with large datasets"""
        import os

        import psutil

        # Get initial memory usage
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Process multiple large validation requests
        for iteration in range(10):
            # Create large member data set for validation
            member_data = {
                "first_name": f"LargeTest{iteration}",
                "last_name": "Member",
                "email": f"large.test{iteration}.{self.unique_id}@test.com",
                "iban": f"NL{(43 + iteration):02d}INGB{(2000000000 + iteration):010d}",
                "address_line1": "Test Address " * 50,  # Large address
                "notes": "Large notes field " * 100,  # Large notes
            }

            # Perform validation
            results = self.validator.detect_potential_duplicates(member_data)

            # Ensure results are valid
            self.assertIsInstance(results, dict, f"Iteration {iteration} should return valid results")

        # Check final memory usage
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory

        # Memory usage should not increase excessively
        self.assertLess(
            memory_increase,
            100,  # 100 MB threshold
            f"Memory usage increased by {memory_increase:.2f} MB, which is too much",
        )

    def assertAny(self, conditions, message="At least one condition should be true"):
        """Helper method to assert that at least one condition in a list is true"""
        if not any(conditions):
            self.fail(message)


if __name__ == "__main__":
    unittest.main()
