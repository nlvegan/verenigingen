#!/usr/bin/env python3
"""
Comprehensive QA Test Suite for Mollie Bulk Transaction Consumer Data Capture

This test suite provides comprehensive quality assurance testing for the enhanced consumer
data capture implementation in Mollie bulk transaction imports, focusing on:

1. Consumer Data Extraction Testing
2. IBAN Validation Testing  
3. Member Matching Algorithm Testing
4. Bank Transaction Field Mapping Testing
5. Integration Testing with Realistic Data
6. Security & Data Quality Testing
7. Performance Testing

Architecture:
- Uses EnhancedTestCase for robust test infrastructure
- Generates realistic Dutch association member data
- Tests with actual Mollie API response formats
- Validates security measures and data integrity
- Provides performance benchmarking for bulk operations
"""

import unittest
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
import json
import time

import frappe
from frappe.utils import getdate, add_days, now_datetime, random_string

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import BulkTransactionImporter
from verenigingen.verenigingen_payments.core.compliance.audit_trail import ImmutableAuditTrail


class TestMollieBulkTransactionConsumerDataQA(EnhancedTestCase):
    """
    Comprehensive QA test suite for enhanced consumer data capture in Mollie bulk imports
    
    Test Categories:
    - Consumer Data Extraction (iDEAL, bank transfer, direct debit)
    - IBAN Validation (European formats, edge cases)
    - Member Matching (IBAN-based, name matching, Dutch tussenvoegsel)
    - Field Mapping (standard ERPNext fields, custom Mollie fields)
    - Security Testing (SQL injection, input sanitization)
    - Performance Testing (bulk operations, large datasets)
    - Integration Testing (end-to-end with realistic data)
    """
    
    def setUp(self):
        """Set up test environment with realistic Dutch association data"""
        super().setUp()
        
        # Track created documents for cleanup
        self.test_documents = []
        
        # Initialize bulk importer for testing
        self.bulk_importer = BulkTransactionImporter()
        
        # Create test company and bank account
        self.test_company = self._create_test_company()
        self.test_bank_account = self._create_test_bank_account()
        
        # Create test members with SEPA mandates for matching tests
        self.test_members = self._create_test_members_with_sepa()
        
    def tearDown(self):
        """Clean up test data"""
        super().tearDown()
        
        # Additional cleanup for bulk transaction test data
        try:
            # Clean up any Bank Transactions created during testing
            test_transactions = frappe.get_all(
                "Bank Transaction",
                filters={"description": ["like", "%TEST%"]},
                fields=["name"]
            )
            for tx in test_transactions:
                try:
                    frappe.delete_doc("Bank Transaction", tx.name, force=True)
                except Exception:
                    pass  # May already be deleted by rollback
        except Exception:
            pass  # Database may already be rolled back
    
    # ============================================================================
    # 1. Consumer Data Extraction Testing
    # ============================================================================
    
    def test_ideal_consumer_data_extraction(self):
        """Test extraction of consumer data from iDEAL payments"""
        # Mock iDEAL payment with consumer data
        ideal_payment = {
            "id": "tr_TEST_ideal_001",
            "amount": {"value": "25.00", "currency": "EUR"},
            "description": "Membership fee payment",
            "createdAt": "2024-01-15T10:30:00.000Z",
            "method": "ideal",
            "status": "paid",
            "details": {
                "consumerName": "Jan van der Berg",
                "consumerAccount": "NL91ABNA0417164300",
                "consumerBic": "ABNANL2A"
            }
        }
        
        # Test consumer data extraction
        payment_date = datetime.fromisoformat("2024-01-15T10:30:00+00:00")
        
        with self.assertQueryCount(50):  # Performance monitoring
            bank_transaction = self.bulk_importer._create_bank_transaction_from_payment(
                ideal_payment, payment_date, self.test_company.name, self.test_bank_account.name
            )
        
        # Validate extracted consumer data
        self.assertIsNotNone(bank_transaction)
        self.assertEqual(bank_transaction.bank_party_name, "Jan van der Berg")
        self.assertEqual(bank_transaction.bank_party_iban, "NL91ABNA0417164300")
        self.assertEqual(bank_transaction.bank_party_account_number, "NL91ABNA0417164300")
        self.assertEqual(bank_transaction.transaction_type, "Mollie Payment")
        
        # Validate custom Mollie fields
        self.assertEqual(bank_transaction.get("custom_mollie_payment_id"), "tr_TEST_ideal_001")
        self.assertEqual(bank_transaction.get("custom_mollie_method"), "ideal")
        self.assertEqual(bank_transaction.get("custom_mollie_status"), "paid")
        
        self.test_documents.append(("Bank Transaction", bank_transaction.name))
    
    def test_bank_transfer_consumer_data_extraction(self):
        """Test extraction of consumer data from bank transfer payments"""
        # Mock bank transfer payment with consumer data
        bank_transfer_payment = {
            "id": "tr_TEST_banktransfer_001",
            "amount": {"value": "50.00", "currency": "EUR"},
            "description": "Annual membership fee",
            "createdAt": "2024-01-15T14:45:00.000Z",
            "method": "banktransfer",
            "status": "paid",
            "details": {
                "bankHolderName": "Maria de Jong-van Aalst", 
                "bankAccount": "NL20INGB0001234567",
                "bankName": "ING Bank N.V."
            }
        }
        
        payment_date = datetime.fromisoformat("2024-01-15T14:45:00+00:00")
        
        bank_transaction = self.bulk_importer._create_bank_transaction_from_payment(
            bank_transfer_payment, payment_date, self.test_company.name, self.test_bank_account.name
        )
        
        # Validate extracted consumer data for bank transfers
        self.assertIsNotNone(bank_transaction)
        self.assertEqual(bank_transaction.bank_party_name, "Maria de Jong-van Aalst")
        self.assertEqual(bank_transaction.bank_party_iban, "NL20INGB0001234567")
        self.assertEqual(bank_transaction.bank_party_account_number, "NL20INGB0001234567")
        
        self.test_documents.append(("Bank Transaction", bank_transaction.name))
    
    def test_direct_debit_consumer_data_extraction(self):
        """Test extraction of consumer data from direct debit payments"""
        # Mock direct debit payment with consumer data
        direct_debit_payment = {
            "id": "tr_TEST_directdebit_001",
            "amount": {"value": "15.00", "currency": "EUR"},
            "description": "Monthly contribution",
            "createdAt": "2024-01-15T08:00:00.000Z",
            "method": "directdebit",
            "status": "paid",
            "details": {
                "consumerName": "Pieter van den Heuvel",
                "consumerAccount": "NL68RABO0123456789",
                "mandateReference": "MNDTEST001"
            }
        }
        
        payment_date = datetime.fromisoformat("2024-01-15T08:00:00+00:00")
        
        bank_transaction = self.bulk_importer._create_bank_transaction_from_payment(
            direct_debit_payment, payment_date, self.test_company.name, self.test_bank_account.name
        )
        
        # Validate extracted consumer data for direct debit
        self.assertIsNotNone(bank_transaction)
        self.assertEqual(bank_transaction.bank_party_name, "Pieter van den Heuvel")
        self.assertEqual(bank_transaction.bank_party_iban, "NL68RABO0123456789")
        self.assertEqual(bank_transaction.bank_party_account_number, "NL68RABO0123456789")
        
        self.test_documents.append(("Bank Transaction", bank_transaction.name))
    
    def test_consumer_data_extraction_edge_cases(self):
        """Test consumer data extraction with edge cases (missing fields, special chars, etc.)"""
        edge_cases = [
            # Missing consumer name
            {
                "id": "tr_TEST_missing_name",
                "amount": {"value": "25.00", "currency": "EUR"},
                "method": "ideal",
                "createdAt": "2024-01-15T10:30:00.000Z",
                "details": {
                    "consumerAccount": "NL91ABNA0417164300"
                    # Missing consumerName
                }
            },
            # Missing consumer account  
            {
                "id": "tr_TEST_missing_account",
                "amount": {"value": "25.00", "currency": "EUR"},
                "method": "ideal", 
                "createdAt": "2024-01-15T10:30:00.000Z",
                "details": {
                    "consumerName": "Test User"
                    # Missing consumerAccount
                }
            },
            # Special characters in name
            {
                "id": "tr_TEST_special_chars",
                "amount": {"value": "25.00", "currency": "EUR"},
                "method": "ideal",
                "createdAt": "2024-01-15T10:30:00.000Z",
                "details": {
                    "consumerName": "José María Ñoño-O'Connor",
                    "consumerAccount": "ES9121000418450200051332"
                }
            },
            # Empty details object
            {
                "id": "tr_TEST_empty_details",
                "amount": {"value": "25.00", "currency": "EUR"}, 
                "method": "ideal",
                "createdAt": "2024-01-15T10:30:00.000Z",
                "details": {}
            }
        ]
        
        payment_date = datetime.fromisoformat("2024-01-15T10:30:00+00:00")
        
        for i, payment in enumerate(edge_cases):
            with self.subTest(case=i, payment_id=payment["id"]):
                # Should not raise exceptions even with missing data
                bank_transaction = self.bulk_importer._create_bank_transaction_from_payment(
                    payment, payment_date, self.test_company.name, self.test_bank_account.name
                )
                
                self.assertIsNotNone(bank_transaction)
                # Should still create transaction even with missing consumer data
                self.assertEqual(bank_transaction.get("custom_mollie_payment_id"), payment["id"])
                
                self.test_documents.append(("Bank Transaction", bank_transaction.name))
    
    # ============================================================================
    # 2. IBAN Validation Testing
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
    # 3. Member Matching Algorithm Testing
    # ============================================================================
    
    def test_member_matching_by_iban_exact_match(self):
        """Test exact IBAN matching via SEPA Mandates"""
        # Use one of our test members with known IBAN
        test_member = self.test_members[0]
        test_sepa = self._get_member_sepa_mandate(test_member.name)
        
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
    
    def test_member_matching_fuzzy_name_single_result(self):
        """Test fuzzy name matching when only one result is found"""
        test_member = self.test_members[2]
        
        # Test partial name match (should return single result)
        partial_name = test_member.full_name.split()[0]  # First name only
        
        # Ensure this partial name only matches one member
        similar_members = frappe.get_all(
            "Member", 
            filters={"full_name": ["like", f"%{partial_name}%"]},
            fields=["name"]
        )
        
        if len(similar_members) == 1:
            matched_member = self.bulk_importer._find_member_by_payment_details(
                consumer_name=partial_name,
                consumer_iban=None
            )
            self.assertEqual(matched_member, test_member.name, "Should match member by partial name when unique")
    
    def test_member_matching_fuzzy_name_multiple_results(self):
        """Test fuzzy name matching when multiple results are found (should return None)"""
        # Create additional test members with similar names
        similar_member1 = self.create_test_member(
            first_name="TestJan",
            last_name="van der Berg",
            email=self.factory.generate_test_email("similar1")
        )
        similar_member2 = self.create_test_member(
            first_name="TestJan", 
            last_name="van den Berg",
            email=self.factory.generate_test_email("similar2")
        )
        
        # Test partial name that matches multiple members
        matched_member = self.bulk_importer._find_member_by_payment_details(
            consumer_name="TestJan",
            consumer_iban=None
        )
        
        # Should return None when multiple matches found (ambiguous)
        self.assertIsNone(matched_member, "Should return None for ambiguous name matches")
        
        self.test_documents.extend([
            ("Member", similar_member1.name),
            ("Member", similar_member2.name)
        ])
    
    def test_member_matching_dutch_tussenvoegsel_handling(self):
        """Test proper handling of Dutch name particles (tussenvoegsel)"""
        # Create test member with tussenvoegsel
        dutch_member = self.create_test_member(
            first_name="Pieter",
            last_name="van den Berg", 
            email=self.factory.generate_test_email("dutch")
        )
        
        tussenvoegsel_variations = [
            "Pieter van den Berg",  # Full name
            "P. van den Berg",      # Abbreviated first name
            "Pieter v.d. Berg",     # Abbreviated tussenvoegsel
            "Berg, Pieter van den", # Surname-first format
        ]
        
        for name_variation in tussenvoegsel_variations:
            with self.subTest(name=name_variation):
                # Note: Current implementation does exact matching
                # This test documents expected behavior for future fuzzy matching improvements
                if name_variation == "Pieter van den Berg":
                    matched_member = self.bulk_importer._find_member_by_payment_details(
                        consumer_name=name_variation,
                        consumer_iban=None
                    )
                    self.assertEqual(matched_member, dutch_member.name, 
                                   f"Should match member with exact tussenvoegsel format: {name_variation}")
        
        self.test_documents.append(("Member", dutch_member.name))
    
    def test_member_matching_priority_iban_over_name(self):
        """Test that IBAN matching takes priority over name matching"""
        # Create member with SEPA mandate
        priority_member = self.create_test_member(
            first_name="Priority",
            last_name="Test",
            email=self.factory.generate_test_email("priority")
        )
        
        # Create SEPA mandate for this member
        sepa_mandate = self._create_test_sepa_mandate(priority_member.name)
        
        # Create another member with same name but no SEPA mandate
        duplicate_name_member = self.create_test_member(
            first_name="Priority",
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
        
        self.test_documents.extend([
            ("Member", priority_member.name),
            ("Member", duplicate_name_member.name),
            ("SEPA Mandate", sepa_mandate.name)
        ])
    
    def test_member_matching_inactive_sepa_mandate(self):
        """Test that inactive SEPA mandates are not used for matching"""
        # Create member with inactive SEPA mandate
        inactive_member = self.create_test_member(
            first_name="Inactive",
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
        
        self.test_documents.extend([
            ("Member", inactive_member.name),
            ("SEPA Mandate", inactive_sepa.name)
        ])
    
    # ============================================================================
    # 4. Bank Transaction Field Mapping Testing
    # ============================================================================
    
    def test_standard_bank_transaction_field_mapping(self):
        """Test mapping of standard ERPNext Bank Transaction fields"""
        test_payment = {
            "id": "tr_TEST_field_mapping",
            "amount": {"value": "75.50", "currency": "EUR"},
            "description": "Test payment for field mapping",
            "createdAt": "2024-01-15T12:00:00.000Z",
            "method": "ideal",
            "status": "paid",
            "details": {
                "consumerName": "Field Test User",
                "consumerAccount": "NL91ABNA0417164300"
            }
        }
        
        payment_date = datetime.fromisoformat("2024-01-15T12:00:00+00:00")
        
        bank_transaction = self.bulk_importer._create_bank_transaction_from_payment(
            test_payment, payment_date, self.test_company.name, self.test_bank_account.name
        )
        
        # Validate standard ERPNext fields
        self.assertEqual(bank_transaction.date, payment_date.date())
        self.assertEqual(bank_transaction.bank_account, self.test_bank_account.name)
        self.assertEqual(bank_transaction.company, self.test_company.name)
        self.assertEqual(bank_transaction.deposit, 75.50)
        self.assertEqual(bank_transaction.withdrawal, 0)
        self.assertEqual(bank_transaction.currency, "EUR")
        self.assertEqual(bank_transaction.description, "Test payment for field mapping")
        self.assertEqual(bank_transaction.reference_number, "tr_TEST_field_mapping")
        self.assertEqual(bank_transaction.transaction_type, "Mollie Payment")
        
        self.test_documents.append(("Bank Transaction", bank_transaction.name))
    
    def test_party_assignment_for_matched_member(self):
        """Test party_type and party assignment when member is matched"""
        # Use test member with SEPA mandate for matching
        test_member = self.test_members[0]
        test_sepa = self._get_member_sepa_mandate(test_member.name)
        
        test_payment = {
            "id": "tr_TEST_party_mapping",
            "amount": {"value": "25.00", "currency": "EUR"},
            "description": "Payment with member matching",
            "createdAt": "2024-01-15T15:30:00.000Z",
            "method": "directdebit",
            "status": "paid",
            "details": {
                "consumerName": test_member.full_name,
                "consumerAccount": test_sepa.iban
            }
        }
        
        payment_date = datetime.fromisoformat("2024-01-15T15:30:00+00:00")
        
        bank_transaction = self.bulk_importer._create_bank_transaction_from_payment(
            test_payment, payment_date, self.test_company.name, self.test_bank_account.name
        )
        
        # Validate party assignment
        self.assertEqual(bank_transaction.party_type, "Member")
        self.assertEqual(bank_transaction.party, test_member.name)
        
        self.test_documents.append(("Bank Transaction", bank_transaction.name))
    
    def test_bank_party_fields_population(self):
        """Test population of bank_party_name, bank_party_iban, bank_party_account_number fields"""
        test_cases = [
            # iDEAL payment
            {
                "payment": {
                    "id": "tr_TEST_ideal_party",
                    "method": "ideal",
                    "details": {
                        "consumerName": "iDEAL Test User",
                        "consumerAccount": "NL91ABNA0417164300"
                    }
                },
                "expected_name": "iDEAL Test User",
                "expected_iban": "NL91ABNA0417164300",
                "expected_account": "NL91ABNA0417164300"
            },
            # Bank transfer payment
            {
                "payment": {
                    "id": "tr_TEST_banktransfer_party",
                    "method": "banktransfer", 
                    "details": {
                        "bankHolderName": "Bank Transfer User",
                        "bankAccount": "DE89370400440532013000"
                    }
                },
                "expected_name": "Bank Transfer User",
                "expected_iban": "DE89370400440532013000",
                "expected_account": "DE89370400440532013000"
            },
            # Direct debit payment
            {
                "payment": {
                    "id": "tr_TEST_directdebit_party",
                    "method": "directdebit",
                    "details": {
                        "consumerName": "Direct Debit User", 
                        "consumerAccount": "BE68539007547034"
                    }
                },
                "expected_name": "Direct Debit User",
                "expected_iban": "BE68539007547034", 
                "expected_account": "BE68539007547034"
            }
        ]
        
        payment_date = datetime.fromisoformat("2024-01-15T16:00:00+00:00")
        
        for i, case in enumerate(test_cases):
            with self.subTest(case=i, method=case["payment"]["method"]):
                # Complete the payment data
                payment = {
                    "amount": {"value": "30.00", "currency": "EUR"},
                    "description": f"Test {case['payment']['method']} payment",
                    "createdAt": "2024-01-15T16:00:00.000Z",
                    "status": "paid",
                    **case["payment"]
                }
                
                bank_transaction = self.bulk_importer._create_bank_transaction_from_payment(
                    payment, payment_date, self.test_company.name, self.test_bank_account.name
                )
                
                # Validate bank party fields
                self.assertEqual(bank_transaction.bank_party_name, case["expected_name"])
                self.assertEqual(bank_transaction.bank_party_iban, case["expected_iban"])
                self.assertEqual(bank_transaction.bank_party_account_number, case["expected_account"])
                
                self.test_documents.append(("Bank Transaction", bank_transaction.name))
    
    def test_custom_mollie_fields_population(self):
        """Test population of custom Mollie fields for audit trail"""
        test_payment = {
            "id": "tr_TEST_custom_fields",
            "amount": {"value": "45.00", "currency": "EUR"},
            "description": "Custom fields test payment",
            "createdAt": "2024-01-15T17:00:00.000Z",
            "method": "creditcard",
            "status": "paid",
            "details": {}
        }
        
        payment_date = datetime.fromisoformat("2024-01-15T17:00:00+00:00")
        
        bank_transaction = self.bulk_importer._create_bank_transaction_from_payment(
            test_payment, payment_date, self.test_company.name, self.test_bank_account.name
        )
        
        # Validate custom Mollie fields (if they exist in the schema)
        expected_fields = {
            "custom_mollie_payment_id": "tr_TEST_custom_fields",
            "custom_mollie_status": "paid", 
            "custom_mollie_method": "creditcard",
            "custom_mollie_import_source": "Bulk Import",
            "custom_import_batch_id": self.bulk_importer.import_id
        }
        
        for field_name, expected_value in expected_fields.items():
            if hasattr(bank_transaction, field_name):
                actual_value = getattr(bank_transaction, field_name)
                self.assertEqual(actual_value, expected_value, 
                               f"Custom field {field_name} should be {expected_value}")
        
        self.test_documents.append(("Bank Transaction", bank_transaction.name))
    
    # ============================================================================
    # 5. Security & Data Quality Testing
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
        """Test input sanitization for consumer names"""
        malicious_names = [
            "<script>alert('XSS')</script>",
            "'; DROP TABLE members; --",
            "Robert\"; DROP TABLE members; --",
            "<img src=x onerror=alert('XSS')>",
            "' UNION SELECT password FROM tabUser WHERE name='Administrator' --",
            "Test\x00User",  # Null byte injection
            "Test\r\nUser",  # CRLF injection
        ]
        
        test_payment_base = {
            "id": "tr_TEST_sanitization",
            "amount": {"value": "25.00", "currency": "EUR"},
            "description": "Sanitization test",
            "createdAt": "2024-01-15T18:00:00.000Z",
            "method": "ideal",
            "status": "paid"
        }
        
        payment_date = datetime.fromisoformat("2024-01-15T18:00:00+00:00")
        
        for i, malicious_name in enumerate(malicious_names):
            with self.subTest(name_index=i, name_snippet=malicious_name[:20]):
                test_payment = {
                    **test_payment_base,
                    "id": f"tr_TEST_sanitization_{i}",
                    "details": {
                        "consumerName": malicious_name,
                        "consumerAccount": "NL91ABNA0417164300"
                    }
                }
                
                # Should not raise exceptions or cause SQL errors
                try:
                    bank_transaction = self.bulk_importer._create_bank_transaction_from_payment(
                        test_payment, payment_date, self.test_company.name, self.test_bank_account.name
                    )
                    
                    # Consumer name should be stored (potentially sanitized)
                    self.assertIsNotNone(bank_transaction.bank_party_name)
                    self.test_documents.append(("Bank Transaction", bank_transaction.name))
                    
                except Exception as e:
                    # Should not fail due to SQL injection
                    self.assertNotIn("SQL syntax", str(e).upper())
                    self.assertNotIn("MYSQL", str(e).upper())
    
    def test_data_validation_prevents_invalid_transactions(self):
        """Test that data validation prevents creation of invalid transactions"""
        invalid_payments = [
            # Missing required amount
            {
                "id": "tr_TEST_no_amount",
                "description": "Missing amount test",
                "createdAt": "2024-01-15T19:00:00.000Z",
                "method": "ideal",
                # Missing amount field
            },
            # Invalid amount format
            {
                "id": "tr_TEST_invalid_amount", 
                "amount": {"value": "not_a_number", "currency": "EUR"},
                "description": "Invalid amount test",
                "createdAt": "2024-01-15T19:00:00.000Z",
                "method": "ideal",
            },
            # Missing created date
            {
                "id": "tr_TEST_no_date",
                "amount": {"value": "25.00", "currency": "EUR"},
                "description": "Missing date test",
                "method": "ideal",
                # Missing createdAt
            }
        ]
        
        for i, invalid_payment in enumerate(invalid_payments):
            with self.subTest(case=i, payment_id=invalid_payment.get("id", f"case_{i}")):
                try:
                    payment_date = datetime.fromisoformat("2024-01-15T19:00:00+00:00")
                    
                    bank_transaction = self.bulk_importer._create_bank_transaction_from_payment(
                        invalid_payment, payment_date, self.test_company.name, self.test_bank_account.name
                    )
                    
                    # If transaction is created, it should handle the invalid data gracefully
                    if bank_transaction:
                        # Should have default/fallback values for missing data
                        self.assertIsNotNone(bank_transaction.name)
                        self.test_documents.append(("Bank Transaction", bank_transaction.name))
                        
                except (ValueError, TypeError) as e:
                    # Expected for invalid data
                    self.assertIn("validation", str(e).lower(), 
                                "Should provide clear validation error messages")
                except Exception as e:
                    # Should not cause system crashes
                    self.fail(f"Invalid payment data should not cause system errors: {e}")
    
    # ============================================================================
    # 6. Performance Testing 
    # ============================================================================
    
    def test_bulk_processing_performance(self):
        """Test performance of bulk transaction processing with large datasets"""
        # Generate large batch of test payments
        batch_size = 50  # Reasonable size for test environment
        test_payments = []
        
        base_date = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        
        for i in range(batch_size):
            payment = {
                "id": f"tr_TEST_bulk_{i:03d}",
                "amount": {"value": f"{25 + (i % 50):.2f}", "currency": "EUR"},
                "description": f"Bulk test payment {i}",
                "createdAt": (base_date + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
                "method": ["ideal", "banktransfer", "directdebit"][i % 3],
                "status": "paid",
                "details": {
                    "consumerName": f"Bulk Test User {i}",
                    "consumerAccount": f"NL{91 + (i % 9):02d}ABNA{i:010d}"
                }
            }
            test_payments.append(payment)
        
        # Time the bulk processing
        start_time = time.time()
        created_transactions = []
        
        for payment in test_payments:
            payment_date = datetime.fromisoformat(payment["createdAt"].replace("Z", "+00:00"))
            
            bank_transaction = self.bulk_importer._create_bank_transaction_from_payment(
                payment, payment_date, self.test_company.name, self.test_bank_account.name
            )
            
            if bank_transaction:
                created_transactions.append(bank_transaction)
        
        end_time = time.time()
        
        # Performance assertions
        total_time = end_time - start_time
        transactions_per_second = len(created_transactions) / total_time
        
        self.assertGreater(transactions_per_second, 5, 
                          f"Processing rate too slow: {transactions_per_second:.2f} transactions/second")
        self.assertLess(total_time, 30, 
                       f"Total processing time too long: {total_time:.2f}s for {batch_size} transactions")
        
        # Quality assertions
        self.assertEqual(len(created_transactions), batch_size, 
                        "All transactions should be created successfully")
        
        # Add to cleanup list
        for tx in created_transactions:
            self.test_documents.append(("Bank Transaction", tx.name))
    
    def test_member_matching_performance(self):
        """Test performance of member matching with various scenarios"""
        # Create additional test members for performance testing
        performance_members = []
        for i in range(20):
            member = self.create_test_member(
                first_name=f"PerfTest{i}",
                last_name=f"User{i}",
                email=self.factory.generate_test_email(f"perf{i}")
            )
            performance_members.append(member)
            self.test_documents.append(("Member", member.name))
            
            # Create SEPA mandate for some members
            if i % 3 == 0:
                sepa = self._create_test_sepa_mandate(member.name)
                self.test_documents.append(("SEPA Mandate", sepa.name))
        
        # Test IBAN matching performance
        start_time = time.time()
        iban_matches = 0
        
        for member in performance_members[:10]:  # Test with members that have SEPA mandates
            try:
                sepa = self._get_member_sepa_mandate(member.name)
                if sepa:
                    matched = self.bulk_importer._find_member_by_payment_details(
                        consumer_name=None,
                        consumer_iban=sepa.iban
                    )
                    if matched:
                        iban_matches += 1
            except:
                pass  # Skip if no SEPA mandate
        
        iban_time = time.time() - start_time
        
        # Test name matching performance
        start_time = time.time()
        name_matches = 0
        
        for member in performance_members:
            matched = self.bulk_importer._find_member_by_payment_details(
                consumer_name=member.full_name,
                consumer_iban=None
            )
            if matched:
                name_matches += 1
        
        name_time = time.time() - start_time
        
        # Performance assertions
        self.assertLess(iban_time, 5.0, f"IBAN matching took too long: {iban_time:.2f}s")
        self.assertLess(name_time, 5.0, f"Name matching took too long: {name_time:.2f}s")
        
        # Quality assertions
        self.assertGreater(iban_matches, 0, "Should find some IBAN matches")
        self.assertGreater(name_matches, 0, "Should find some name matches")
    
    # ============================================================================
    # 7. Integration Testing
    # ============================================================================
    
    def test_end_to_end_bulk_import_with_consumer_data(self):
        """Test complete end-to-end bulk import with realistic consumer data"""
        # Mock realistic payment data with Dutch names and IBANs
        realistic_payments = [
            {
                "id": "tr_E2E_001",
                "amount": {"value": "25.00", "currency": "EUR"},
                "description": "Maandelijkse contributie januari",
                "createdAt": "2024-01-15T08:00:00.000Z",
                "method": "directdebit",
                "status": "paid", 
                "details": {
                    "consumerName": "Jan van der Berg",
                    "consumerAccount": "NL91ABNA0417164300"
                }
            },
            {
                "id": "tr_E2E_002",
                "amount": {"value": "50.00", "currency": "EUR"}, 
                "description": "Jaarlidmaatschap 2024",
                "createdAt": "2024-01-15T10:30:00.000Z",
                "method": "ideal",
                "status": "paid",
                "details": {
                    "consumerName": "Maria de Jong-van Aalst",
                    "consumerAccount": "NL20INGB0001234567"
                }
            },
            {
                "id": "tr_E2E_003",
                "amount": {"value": "75.00", "currency": "EUR"},
                "description": "Donatie voor goede doelen",
                "createdAt": "2024-01-15T14:45:00.000Z",
                "method": "banktransfer",
                "status": "paid",
                "details": {
                    "bankHolderName": "Pieter van den Heuvel",
                    "bankAccount": "NL68RABO0123456789"
                }
            }
        ]
        
        # Process each payment through the bulk importer
        created_transactions = []
        member_matches = 0
        
        for payment in realistic_payments:
            payment_date = datetime.fromisoformat(payment["createdAt"].replace("Z", "+00:00"))
            
            bank_transaction = self.bulk_importer._create_bank_transaction_from_payment(
                payment, payment_date, self.test_company.name, self.test_bank_account.name
            )
            
            self.assertIsNotNone(bank_transaction, f"Failed to create transaction for {payment['id']}")
            created_transactions.append(bank_transaction)
            
            # Check if member matching worked
            if bank_transaction.party_type == "Member" and bank_transaction.party:
                member_matches += 1
            
            # Validate consumer data extraction
            self.assertIsNotNone(bank_transaction.bank_party_name, "Consumer name should be extracted")
            if payment["method"] in ["ideal", "directdebit"]:
                self.assertEqual(bank_transaction.bank_party_iban, 
                               payment["details"].get("consumerAccount") or payment["details"].get("bankAccount"))
            
            self.test_documents.append(("Bank Transaction", bank_transaction.name))
        
        # Integration assertions
        self.assertEqual(len(created_transactions), len(realistic_payments), 
                        "All payments should result in bank transactions")
        
        # Verify transaction data integrity
        for i, tx in enumerate(created_transactions):
            payment = realistic_payments[i]
            self.assertEqual(tx.deposit, float(payment["amount"]["value"]))
            self.assertEqual(tx.currency, payment["amount"]["currency"])
            self.assertEqual(tx.description, payment["description"])
            self.assertEqual(tx.get("custom_mollie_payment_id"), payment["id"])
    
    def test_integration_with_existing_member_data(self):
        """Test integration with existing member and SEPA mandate data"""
        # Use our existing test members
        test_member = self.test_members[0]
        test_sepa = self._get_member_sepa_mandate(test_member.name)
        
        # Create payment that should match this member
        matching_payment = {
            "id": "tr_INTEGRATION_match",
            "amount": {"value": "30.00", "currency": "EUR"},
            "description": "Integration test payment",
            "createdAt": "2024-01-15T20:00:00.000Z",
            "method": "directdebit",
            "status": "paid",
            "details": {
                "consumerName": test_member.full_name,
                "consumerAccount": test_sepa.iban
            }
        }
        
        payment_date = datetime.fromisoformat("2024-01-15T20:00:00+00:00")
        
        bank_transaction = self.bulk_importer._create_bank_transaction_from_payment(
            matching_payment, payment_date, self.test_company.name, self.test_bank_account.name
        )
        
        # Verify complete integration
        self.assertIsNotNone(bank_transaction)
        self.assertEqual(bank_transaction.party_type, "Member")
        self.assertEqual(bank_transaction.party, test_member.name)
        self.assertEqual(bank_transaction.bank_party_name, test_member.full_name)
        self.assertEqual(bank_transaction.bank_party_iban, test_sepa.iban)
        
        # Verify the member record is accessible and valid
        member_doc = frappe.get_doc("Member", test_member.name)
        self.assertEqual(member_doc.email, test_member.email)
        
        # Verify the SEPA mandate is accessible and active
        sepa_doc = frappe.get_doc("SEPA Mandate", test_sepa.name)
        self.assertEqual(sepa_doc.status, "Active")
        
        self.test_documents.append(("Bank Transaction", bank_transaction.name))
    
    # ============================================================================
    # Helper Methods
    # ============================================================================
    
    def _create_test_company(self):
        """Create test company for transactions"""
        company_name = f"TEST Company {random_string(8)}"
        
        if not frappe.db.exists("Company", company_name):
            company = frappe.get_doc({
                "doctype": "Company", 
                "company_name": company_name,
                "abbr": f"TC{random_string(3)}",
                "default_currency": "EUR",
                "country": "Netherlands"
            })
            company.insert()
            self.test_documents.append(("Company", company.name))
            return company
        return frappe.get_doc("Company", company_name)
    
    def _create_test_bank_account(self):
        """Create test bank account for transactions"""
        # Try to find an existing bank account first
        existing_account = frappe.db.get_value(
            "Bank Account", 
            {"company": self.test_company.name}, 
            "name"
        )
        
        if existing_account:
            return frappe.get_doc("Bank Account", existing_account)
        
        # Create a test bank first
        bank_name = f"TEST Bank {random_string(6)}"
        if not frappe.db.exists("Bank", bank_name):
            bank = frappe.get_doc({
                "doctype": "Bank",
                "bank_name": bank_name
            })
            bank.insert()
            self.test_documents.append(("Bank", bank.name))
        
        # Create bank account with minimal required fields
        account_name = f"TEST Bank Account {random_string(8)}"
        if not frappe.db.exists("Bank Account", account_name):
            bank_account = frappe.get_doc({
                "doctype": "Bank Account",
                "account_name": account_name,
                "bank": bank_name,
                "company": self.test_company.name,
                "is_default": 1,
                "is_company_account": 1
            })
            bank_account.insert()
            self.test_documents.append(("Bank Account", bank_account.name))
            return bank_account
        return frappe.get_doc("Bank Account", account_name)
    
    def _create_test_members_with_sepa(self):
        """Create test members with SEPA mandates for matching tests"""
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
            self.test_documents.append(("Member", member.name))
            
            # Create SEPA mandate
            sepa = self._create_test_sepa_mandate(member.name, iban=data["iban"])
            self.test_documents.append(("SEPA Mandate", sepa.name))
        
        return members
    
    def _create_test_sepa_mandate(self, member_name, iban=None, status="Active"):
        """Create test SEPA mandate for member"""
        if not iban:
            iban = self.factory.create_test_iban()
        
        sepa_mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": member_name,
            "iban": iban,
            "status": status,
            "mandate_reference": f"MNDTEST{random_string(8)}",
            "signature_date": getdate(),
            "mandate_type": "Recurring"
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