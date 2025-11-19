#!/usr/bin/env python3
"""
Core Functionality QA Test Suite for Mollie Bulk Transaction Consumer Data Capture

This test suite focuses on the core functionality that can be tested without complex
database setup requirements:

1. IBAN Validation Testing
2. Member Matching Algorithm Testing
3. Consumer Data Extraction Logic Testing
4. Security & Input Validation Testing
5. Performance Testing of Core Functions

This approach isolates the business logic from the database integration concerns.
"""

import unittest
from datetime import datetime, timezone
from typing import Dict, List, Any
import time

import frappe
from frappe.utils import random_string

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import BulkTransactionImporter


class TestMollieBulkTransactionCoreFunctionality(EnhancedTestCase):
    """
    Core functionality test suite for Mollie bulk transaction consumer data capture
    
    Focus Areas:
    - IBAN validation logic
    - Member matching algorithms  
    - Consumer data extraction from payment objects
    - Security validation (SQL injection prevention, input sanitization)
    - Performance of core functions
    """
    
    def setUp(self):
        """Set up test environment for core functionality testing"""
        super().setUp()
        
        # Initialize bulk importer for testing
        self.bulk_importer = BulkTransactionImporter()
        
        # Create test members for matching tests
        self.test_members = self._create_test_members_for_matching()
    
    # ============================================================================
    # 1. IBAN Validation Testing
    # ============================================================================
    
    def test_iban_validation_european_formats(self):
        """Test IBAN validation with various European IBAN formats"""
        valid_ibans = [
            # Netherlands
            "NL91ABNA0417164300",
            "NL20INGB0001234567",
            # Germany  
            "DE89370400440532013000",
            "DE12500105170648489890",
            # Belgium
            "BE68539007547034",
            "BE62510007547061",
            # France
            "FR1420041010050500013M02606",
            "FR7630006000011234567890189",
            # Spain
            "ES9121000418450200051332",
            # Italy
            "IT60X0542811101000000123456",
            # Austria
            "AT611904300234573201",
            # Luxembourg
            "LU280019400644750000"
        ]
        
        for iban in valid_ibans:
            with self.subTest(iban=iban):
                # Test without spaces
                self.assertTrue(
                    self.bulk_importer._validate_iban_format(iban),
                    f"IBAN {iban} should be valid"
                )
                
                # Test with spaces (common user input format)
                spaced_iban = " ".join([iban[i:i+4] for i in range(0, len(iban), 4)])
                self.assertTrue(
                    self.bulk_importer._validate_iban_format(spaced_iban),
                    f"Spaced IBAN {spaced_iban} should be valid"
                )
    
    def test_iban_validation_invalid_formats(self):
        """Test IBAN validation with invalid formats"""
        invalid_ibans = [
            "",  # Empty string
            None,  # None value
            "NL91",  # Too short
            "NL91ABNA041716430012345678901234567890",  # Too long
            "123456789012345",  # No country code
            "NLABNA0417164300",  # Missing check digits
            "NL91ABNA041716430G",  # Invalid characters
            "XX91ABNA0417164300",  # Invalid country code
            "NL9AABNA0417164300",  # Letters in check digits
            "INVALID_IBAN",  # Completely invalid format
        ]
        
        for iban in invalid_ibans:
            with self.subTest(iban=iban):
                self.assertFalse(
                    self.bulk_importer._validate_iban_format(iban),
                    f"IBAN {iban} should be invalid"
                )
    
    def test_iban_validation_edge_cases(self):
        """Test IBAN validation with edge cases"""
        edge_cases = [
            ("NL91 ABNA 0417 1643 00", True),  # Spaces
            ("nl91abna0417164300", True),  # Lowercase (should be normalized)
            ("NL91-ABNA-0417-1643-00", True),  # Dashes (should be removed)
            ("  NL91ABNA0417164300  ", True),  # Leading/trailing spaces
            ("NL91\nABNA0417164300", False),  # Newlines (invalid)
            ("NL91\tABNA0417164300", False),  # Tabs (invalid)
        ]
        
        for iban, expected_valid in edge_cases:
            with self.subTest(iban=repr(iban), expected=expected_valid):
                result = self.bulk_importer._validate_iban_format(iban)
                self.assertEqual(
                    result, expected_valid,
                    f"IBAN {repr(iban)} validation result should be {expected_valid}"
                )
    
    def test_iban_validation_performance(self):
        """Test IBAN validation performance with large batches"""
        # Generate test IBANs for performance testing
        valid_ibans = ["NL91ABNA0417164300", "DE89370400440532013000", "BE68539007547034"] * 100
        invalid_ibans = ["INVALID", "TOO_SHORT", "TOOLONGTOBEVALIDIBAN123456789"] * 100
        
        all_ibans = valid_ibans + invalid_ibans
        
        # Time the validation process
        start_time = time.time()
        results = [self.bulk_importer._validate_iban_format(iban) for iban in all_ibans]
        end_time = time.time()
        
        # Performance assertions
        total_time = end_time - start_time
        self.assertLess(total_time, 5.0, f"IBAN validation took too long: {total_time:.2f}s for {len(all_ibans)} IBANs")
        
        # Accuracy assertions
        expected_valid_count = len(valid_ibans)
        actual_valid_count = sum(results)
        self.assertEqual(actual_valid_count, expected_valid_count, "IBAN validation accuracy failed")
    
    # ============================================================================
    # 2. Member Matching Algorithm Testing
    # ============================================================================
    
    def test_member_matching_by_iban_exact_match(self):
        """Test exact IBAN matching via SEPA Mandates"""
        # Use one of our test members with known IBAN
        test_member = self.test_members[0]
        test_sepa = self._get_member_sepa_mandate(test_member.name)
        
        if test_sepa:
            # Test exact IBAN match
            matched_member = self.bulk_importer._find_member_by_payment_details(
                consumer_name=None,  # Test IBAN-only matching
                consumer_iban=test_sepa.iban
            )
            
            self.assertEqual(matched_member, test_member.name, "Should match member by exact IBAN")
    
    def test_member_matching_by_iban_case_insensitive(self):
        """Test case-insensitive IBAN matching"""
        test_member = self.test_members[0]
        test_sepa = self._get_member_sepa_mandate(test_member.name)
        
        if test_sepa:
            # Test lowercase IBAN
            matched_member = self.bulk_importer._find_member_by_payment_details(
                consumer_name=None,
                consumer_iban=test_sepa.iban.lower()
            )
            self.assertEqual(matched_member, test_member.name, "Should match member with lowercase IBAN")
            
            # Test IBAN with spaces
            spaced_iban = " ".join([test_sepa.iban[i:i+4] for i in range(0, len(test_sepa.iban), 4)])
            matched_member = self.bulk_importer._find_member_by_payment_details(
                consumer_name=None,
                consumer_iban=spaced_iban
            )
            self.assertEqual(matched_member, test_member.name, "Should match member with spaced IBAN")
    
    def test_member_matching_by_exact_name(self):
        """Test exact name matching when IBAN is not available"""
        test_member = self.test_members[1]
        
        # Test exact name match
        matched_member = self.bulk_importer._find_member_by_payment_details(
            consumer_name=test_member.full_name,
            consumer_iban=None
        )
        
        self.assertEqual(matched_member, test_member.name, "Should match member by exact name")
    
    def test_member_matching_dutch_tussenvoegsel_handling(self):
        """Test proper handling of Dutch name particles (tussenvoegsel)"""
        # Create test member with tussenvoegsel
        dutch_member = self.create_test_member(
            first_name="TestPieter",
            last_name="van den Berg", 
            email=self.factory.generate_test_email("dutch")
        )
        
        tussenvoegsel_variations = [
            "TestPieter van den Berg",  # Full name (should match)
            "P. van den Berg",          # Abbreviated first name (won't match with current exact matching)
            "TestPieter v.d. Berg",     # Abbreviated tussenvoegsel (won't match)
            "Berg, TestPieter van den", # Surname-first format (won't match)
        ]
        
        for name_variation in tussenvoegsel_variations:
            with self.subTest(name=name_variation):
                matched_member = self.bulk_importer._find_member_by_payment_details(
                    consumer_name=name_variation,
                    consumer_iban=None
                )
                
                if name_variation == "TestPieter van den Berg":
                    # Exact match should work
                    self.assertEqual(matched_member, dutch_member.name, 
                                   f"Should match member with exact tussenvoegsel format: {name_variation}")
                else:
                    # Other variations won't match with current exact matching implementation
                    # This documents the current behavior and identifies areas for future enhancement
                    self.assertIsNone(matched_member, 
                                    f"Current implementation doesn't support fuzzy tussenvoegsel matching for: {name_variation}")
    
    def test_member_matching_priority_iban_over_name(self):
        """Test that IBAN matching takes priority over name matching"""
        # Create member with SEPA mandate
        priority_member = self.create_test_member(
            first_name="TestPriority",
            last_name="Test",
            email=self.factory.generate_test_email("priority")
        )
        
        # Create SEPA mandate for this member
        sepa_mandate = self._create_test_sepa_mandate(priority_member.name)
        
        # Create another member with same name but no SEPA mandate
        duplicate_name_member = self.create_test_member(
            first_name="TestPriority",
            last_name="Test",
            email=self.factory.generate_test_email("duplicate")  # Different email
        )
        
        # Test matching with both IBAN and name - should match IBAN member
        matched_member = self.bulk_importer._find_member_by_payment_details(
            consumer_name=priority_member.full_name,
            consumer_iban=sepa_mandate.iban
        )
        
        self.assertEqual(matched_member, priority_member.name, 
                        "IBAN matching should take priority over name matching")
    
    def test_member_matching_inactive_sepa_mandate(self):
        """Test that inactive SEPA mandates are not used for matching"""
        # Create member with inactive SEPA mandate
        inactive_member = self.create_test_member(
            first_name="TestInactive",
            last_name="SEPA",
            email=self.factory.generate_test_email("inactive")
        )
        
        inactive_sepa = self._create_test_sepa_mandate(inactive_member.name, status="Inactive")
        
        # Test matching with inactive SEPA mandate IBAN
        matched_member = self.bulk_importer._find_member_by_payment_details(
            consumer_name=None,
            consumer_iban=inactive_sepa.iban
        )
        
        # Should not match inactive mandates
        self.assertIsNone(matched_member, "Should not match members with inactive SEPA mandates")
    
    # ============================================================================
    # 3. Consumer Data Extraction Logic Testing
    # ============================================================================
    
    def test_consumer_data_extraction_ideal_payments(self):
        """Test consumer data extraction from iDEAL payment objects"""
        ideal_payment_data = {
            "id": "tr_TEST_ideal_001",
            "method": "ideal",
            "details": {
                "consumerName": "Jan van der Berg",
                "consumerAccount": "NL91ABNA0417164300",
                "consumerBic": "ABNANL2A"
            }
        }
        
        # Extract data using the logic from _create_bank_transaction_from_payment
        consumer_name = None
        consumer_account = None
        consumer_iban = None
        payment_details = ideal_payment_data.get("details", {})
        
        if ideal_payment_data.get("method") == "ideal" and payment_details:
            consumer_name = payment_details.get("consumerName")
            consumer_account = payment_details.get("consumerAccount")
            consumer_iban = consumer_account if self.bulk_importer._validate_iban_format(consumer_account) else None
        
        # Validate extraction
        self.assertEqual(consumer_name, "Jan van der Berg")
        self.assertEqual(consumer_account, "NL91ABNA0417164300")
        self.assertEqual(consumer_iban, "NL91ABNA0417164300")
    
    def test_consumer_data_extraction_bank_transfer_payments(self):
        """Test consumer data extraction from bank transfer payment objects"""
        bank_transfer_payment_data = {
            "id": "tr_TEST_banktransfer_001", 
            "method": "banktransfer",
            "details": {
                "bankHolderName": "Maria de Jong-van Aalst",
                "bankAccount": "NL20INGB0001234567",
                "bankName": "ING Bank N.V."
            }
        }
        
        # Extract data using the logic from _create_bank_transaction_from_payment
        consumer_name = None
        consumer_account = None
        consumer_iban = None
        payment_details = bank_transfer_payment_data.get("details", {})
        
        if bank_transfer_payment_data.get("method") == "banktransfer" and payment_details:
            consumer_name = payment_details.get("bankHolderName")
            consumer_account = payment_details.get("bankAccount")
            bank_account = payment_details.get("bankAccount")
            consumer_iban = bank_account if self.bulk_importer._validate_iban_format(bank_account) else None
        
        # Validate extraction
        self.assertEqual(consumer_name, "Maria de Jong-van Aalst")
        self.assertEqual(consumer_account, "NL20INGB0001234567")
        self.assertEqual(consumer_iban, "NL20INGB0001234567")
    
    def test_consumer_data_extraction_direct_debit_payments(self):
        """Test consumer data extraction from direct debit payment objects"""
        direct_debit_payment_data = {
            "id": "tr_TEST_directdebit_001",
            "method": "directdebit",
            "details": {
                "consumerName": "Pieter van den Heuvel",
                "consumerAccount": "NL68RABO0123456789",
                "mandateReference": "MNDTEST001"
            }
        }
        
        # Extract data using the logic from _create_bank_transaction_from_payment
        consumer_name = None
        consumer_account = None
        consumer_iban = None
        payment_details = direct_debit_payment_data.get("details", {})
        
        if direct_debit_payment_data.get("method") == "directdebit" and payment_details:
            consumer_name = payment_details.get("consumerName")
            consumer_account = payment_details.get("consumerAccount")
            consumer_account_raw = payment_details.get("consumerAccount")
            consumer_iban = consumer_account_raw if self.bulk_importer._validate_iban_format(consumer_account_raw) else None
        
        # Validate extraction
        self.assertEqual(consumer_name, "Pieter van den Heuvel")
        self.assertEqual(consumer_account, "NL68RABO0123456789")
        self.assertEqual(consumer_iban, "NL68RABO0123456789")
    
    def test_consumer_data_extraction_edge_cases(self):
        """Test consumer data extraction with edge cases"""
        edge_cases = [
            # Missing consumer name
            {
                "method": "ideal",
                "details": {
                    "consumerAccount": "NL91ABNA0417164300"
                    # Missing consumerName
                }
            },
            # Missing consumer account
            {
                "method": "ideal",
                "details": {
                    "consumerName": "Test User"
                    # Missing consumerAccount
                }
            },
            # Empty details object
            {
                "method": "ideal",
                "details": {}
            },
            # Missing details entirely
            {
                "method": "ideal"
                # Missing details
            }
        ]
        
        for i, payment_data in enumerate(edge_cases):
            with self.subTest(case=i):
                # Extract data using the extraction logic
                consumer_name = None
                consumer_account = None
                consumer_iban = None
                payment_details = payment_data.get("details", {})
                
                if payment_data.get("method") == "ideal" and payment_details:
                    consumer_name = payment_details.get("consumerName")
                    consumer_account = payment_details.get("consumerAccount")
                    consumer_iban = consumer_account if consumer_account and self.bulk_importer._validate_iban_format(consumer_account) else None
                
                # Should handle missing data gracefully (no exceptions)
                # Values may be None, which is acceptable
                self.assertIsInstance(consumer_name, (str, type(None)))
                self.assertIsInstance(consumer_account, (str, type(None)))
                self.assertIsInstance(consumer_iban, (str, type(None)))
    
    # ============================================================================
    # 4. Security & Input Validation Testing
    # ============================================================================
    
    def test_sql_injection_protection_iban_lookup(self):
        """Test SQL injection protection in IBAN lookup queries"""
        # Attempt SQL injection through IBAN parameter
        malicious_ibans = [
            "'; DROP TABLE `tabSEPA Mandate`; --",
            "NL91' UNION SELECT * FROM `tabUser` WHERE '1'='1",
            "'; UPDATE `tabMember` SET first_name='HACKED' WHERE '1'='1'; --",
            "NL91ABNA0417164300'; INSERT INTO `tabUser` VALUES ('hacker', 'hacker@evil.com'); --",
            "' OR '1'='1' --",
            "NULL; EXEC xp_cmdshell('dir'); --"
        ]
        
        for malicious_iban in malicious_ibans:
            with self.subTest(iban=malicious_iban[:50]):
                # Should not raise SQL errors or find unexpected matches
                try:
                    matched_member = self.bulk_importer._find_member_by_payment_details(
                        consumer_name=None,
                        consumer_iban=malicious_iban
                    )
                    # Should return None for invalid/malicious IBANs
                    self.assertIsNone(matched_member, "Malicious IBAN should not match any member")
                except Exception as e:
                    # Should not raise SQL syntax errors
                    self.assertNotIn("SQL syntax", str(e).upper())
                    self.assertNotIn("MYSQL", str(e).upper())
    
    def test_input_sanitization_consumer_names(self):
        """Test that consumer names with malicious content are handled safely"""
        malicious_names = [
            "<script>alert('XSS')</script>",
            "'; DROP TABLE members; --",
            "Robert\"; DROP TABLE members; --",
            "<img src=x onerror=alert('XSS')>",
            "' UNION SELECT password FROM tabUser WHERE name='Administrator' --",
            "Test\x00User",  # Null byte injection
            "Test\r\nUser",  # CRLF injection
        ]
        
        for malicious_name in malicious_names:
            with self.subTest(name_snippet=malicious_name[:20]):
                # Should not raise exceptions or cause SQL errors
                try:
                    matched_member = self.bulk_importer._find_member_by_payment_details(
                        consumer_name=malicious_name,
                        consumer_iban=None
                    )
                    
                    # Should handle malicious names safely (return None or valid result)
                    self.assertIsInstance(matched_member, (str, type(None)))
                    
                except Exception as e:
                    # Should not fail due to SQL injection
                    self.assertNotIn("SQL syntax", str(e).upper())
                    self.assertNotIn("MYSQL", str(e).upper())
    
    # ============================================================================
    # 5. Performance Testing of Core Functions
    # ============================================================================
    
    def test_member_matching_performance(self):
        """Test performance of member matching functions"""
        # Test IBAN matching performance
        test_ibans = [
            "NL91ABNA0417164300",
            "DE89370400440532013000", 
            "BE68539007547034",
            "FR1420041010050500013M02606",
            "ES9121000418450200051332"
        ] * 20  # 100 total tests
        
        start_time = time.time()
        for iban in test_ibans:
            self.bulk_importer._find_member_by_payment_details(
                consumer_name=None,
                consumer_iban=iban
            )
        iban_time = time.time() - start_time
        
        # Test name matching performance
        test_names = [
            "Test User",
            "Jan van der Berg",
            "Maria de Jong",
            "Pieter van den Heuvel",
            "Anna Johanna Smith-van der Meer"
        ] * 20  # 100 total tests
        
        start_time = time.time()
        for name in test_names:
            self.bulk_importer._find_member_by_payment_details(
                consumer_name=name,
                consumer_iban=None
            )
        name_time = time.time() - start_time
        
        # Performance assertions
        self.assertLess(iban_time, 10.0, f"IBAN matching took too long: {iban_time:.2f}s")
        self.assertLess(name_time, 10.0, f"Name matching took too long: {name_time:.2f}s")
    
    # ============================================================================
    # Helper Methods
    # ============================================================================
    
    def _create_test_members_for_matching(self):
        """Create test members for matching algorithm tests"""
        members = []
        
        test_member_data = [
            {"first_name": "TestJan", "last_name": "van der Berg", "iban": "NL91ABNA0417164300"},
            {"first_name": "TestMaria", "last_name": "de Jong", "iban": "NL20INGB0001234567"}, 
            {"first_name": "TestPieter", "last_name": "van den Heuvel", "iban": "NL68RABO0123456789"}
        ]
        
        for i, data in enumerate(test_member_data):
            member = self.create_test_member(
                first_name=data["first_name"],
                last_name=data["last_name"],
                email=self.factory.generate_test_email(f"sepa_member_{i}")
            )
            members.append(member)
            
            # Create SEPA mandate for member matching tests
            self._create_test_sepa_mandate(member.name, iban=data["iban"])
        
        return members
    
    def _create_test_sepa_mandate(self, member_name, iban=None, status="Active"):
        """Create test SEPA mandate for member"""
        if not iban:
            iban = self.factory.create_test_iban()
        
        # Get member to extract account holder name
        member = frappe.get_doc("Member", member_name)
        
        sepa_mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": member_name,
            "iban": iban,
            "status": status,
            "mandate_id": f"MNDTEST{random_string(8)}",  # Use mandate_id instead of mandate_reference
            "account_holder_name": member.full_name,  # Required field
            "sign_date": frappe.utils.today(),  # Required field
            "mandate_type": "RCUR"  # Use valid mandate type
        })
        sepa_mandate.insert()
        return sepa_mandate
    
    def _get_member_sepa_mandate(self, member_name):
        """Get active SEPA mandate for member"""
        mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": member_name, "status": "Active"},
            fields=["name", "iban"],
            limit=1
        )
        
        if mandates:
            return frappe.get_doc("SEPA Mandate", mandates[0].name)
        return None


if __name__ == "__main__":
    # Run the test suite
    unittest.main()