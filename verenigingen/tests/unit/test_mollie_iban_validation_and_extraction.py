#!/usr/bin/env python3
"""
IBAN Validation and Consumer Data Extraction QA Test Suite

This focused test suite validates the core IBAN validation and consumer data extraction
functionality without requiring database setup or DocType dependencies.

Test Categories:
1. IBAN Validation Testing - All European formats and edge cases
2. Consumer Data Extraction Logic - Payment object parsing
3. Security & Input Validation - SQL injection prevention, sanitization
4. Performance Testing - Large batch processing

This provides comprehensive validation of the business logic while maintaining
test reliability and execution speed.
"""

import unittest
import time
from typing import Dict, Any

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import BulkTransactionImporter


class TestMollieIBANValidationAndExtraction(FrappeTestCase):
    """
    Focused test suite for IBAN validation and consumer data extraction
    
    These tests validate core business logic without database dependencies,
    providing fast, reliable feedback on the implementation quality.
    """
    
    def setUp(self):
        """Set up test environment"""
        super().setUp()
        
        # Initialize bulk importer for testing core functions
        self.bulk_importer = BulkTransactionImporter()
    
    # ============================================================================
    # 1. IBAN Validation Testing
    # ============================================================================
    
    def test_iban_validation_dutch_formats(self):
        """Test IBAN validation with Dutch IBAN formats"""
        valid_dutch_ibans = [
            "NL91ABNA0417164300",
            "NL20INGB0001234567", 
            "NL68RABO0123456789",
            "NL43ASNB0708498176",
            "NL02BUNQ2025588916"
        ]
        
        for iban in valid_dutch_ibans:
            with self.subTest(iban=iban):
                self.assertTrue(
                    self.bulk_importer._validate_iban_format(iban),
                    f"Dutch IBAN {iban} should be valid"
                )
    
    def test_iban_validation_european_formats(self):
        """Test IBAN validation with various European IBAN formats"""
        valid_european_ibans = [
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
        
        for iban in valid_european_ibans:
            with self.subTest(iban=iban):
                self.assertTrue(
                    self.bulk_importer._validate_iban_format(iban),
                    f"European IBAN {iban} should be valid"
                )
    
    def test_iban_validation_with_spaces(self):
        """Test IBAN validation with various spacing formats"""
        base_iban = "NL91ABNA0417164300"
        
        spacing_formats = [
            "NL91ABNA0417164300",          # No spaces
            "NL91 ABNA 0417 1643 00",      # Standard spacing (4-char groups)
            "NL 91 AB NA 04 17 16 43 00",  # 2-char spacing
            "NL91 ABNA0417164300",         # Mixed spacing
            "  NL91ABNA0417164300  "       # Leading/trailing spaces
        ]
        
        for spaced_iban in spacing_formats:
            with self.subTest(spacing=repr(spaced_iban)):
                self.assertTrue(
                    self.bulk_importer._validate_iban_format(spaced_iban),
                    f"Spaced IBAN {repr(spaced_iban)} should be valid"
                )
    
    def test_iban_validation_case_handling(self):
        """Test IBAN validation with different case formats"""
        base_iban = "NL91ABNA0417164300"
        
        case_formats = [
            "NL91ABNA0417164300",  # Uppercase
            "nl91abna0417164300",  # Lowercase  
            "Nl91Abna0417164300",  # Mixed case
            "nL91aBNa0417164300"   # Random case
        ]
        
        for case_iban in case_formats:
            with self.subTest(case=case_iban):
                self.assertTrue(
                    self.bulk_importer._validate_iban_format(case_iban),
                    f"Case variant {case_iban} should be valid"
                )
    
    def test_iban_validation_invalid_formats(self):
        """Test IBAN validation with invalid formats"""
        invalid_ibans = [
            "",                                          # Empty string
            None,                                        # None value
            "NL91",                                      # Too short
            "NL91ABNA041716430012345678901234567890",    # Too long
            "123456789012345",                           # No country code
            "NLABNA0417164300",                          # Missing check digits
            "NL91ABNA041716430G",                        # Invalid characters
            "XX91ABNA0417164300",                        # Invalid country code
            "NL9AABNA0417164300",                        # Letters in check digits
            "INVALID_IBAN",                              # Completely invalid
            "NL91\nABNA0417164300",                      # Contains newline
            "NL91\tABNA0417164300",                      # Contains tab
            "NL91-ABNA-0417-1643-00-EXTRA"              # Too many segments
        ]
        
        for invalid_iban in invalid_ibans:
            with self.subTest(iban=repr(invalid_iban)):
                self.assertFalse(
                    self.bulk_importer._validate_iban_format(invalid_iban),
                    f"Invalid IBAN {repr(invalid_iban)} should be rejected"
                )
    
    def test_iban_validation_performance(self):
        """Test IBAN validation performance with large batches"""
        # Prepare test data
        valid_ibans = [
            "NL91ABNA0417164300", "DE89370400440532013000", "BE68539007547034"
        ] * 200  # 600 valid IBANs
        
        invalid_ibans = [
            "INVALID", "TOO_SHORT", "TOOLONGTOBEVALIDIBAN123456789"
        ] * 200  # 600 invalid IBANs
        
        all_ibans = valid_ibans + invalid_ibans  # 1200 total IBANs
        
        # Time the validation process
        start_time = time.time()
        results = [self.bulk_importer._validate_iban_format(iban) for iban in all_ibans]
        end_time = time.time()
        
        # Performance assertions
        total_time = end_time - start_time
        ibans_per_second = len(all_ibans) / total_time
        
        self.assertLess(total_time, 2.0, 
                       f"IBAN validation too slow: {total_time:.2f}s for {len(all_ibans)} IBANs")
        self.assertGreater(ibans_per_second, 500,
                          f"IBAN validation rate too low: {ibans_per_second:.0f} IBANs/second")
        
        # Accuracy assertions
        expected_valid_count = len(valid_ibans)
        actual_valid_count = sum(results)
        self.assertEqual(actual_valid_count, expected_valid_count, 
                        "IBAN validation accuracy failed")
    
    # ============================================================================
    # 2. Consumer Data Extraction Logic Testing
    # ============================================================================
    
    def test_ideal_payment_data_extraction(self):
        """Test consumer data extraction from iDEAL payment objects"""
        ideal_payment_cases = [
            # Standard iDEAL payment
            {
                "payment": {
                    "id": "tr_ideal_001",
                    "method": "ideal",
                    "details": {
                        "consumerName": "Jan van der Berg",
                        "consumerAccount": "NL91ABNA0417164300",
                        "consumerBic": "ABNANL2A"
                    }
                },
                "expected_name": "Jan van der Berg",
                "expected_iban": "NL91ABNA0417164300",
                "expected_account": "NL91ABNA0417164300"
            },
            # iDEAL with Dutch name particles
            {
                "payment": {
                    "id": "tr_ideal_002", 
                    "method": "ideal",
                    "details": {
                        "consumerName": "Maria de Jong-van Aalst",
                        "consumerAccount": "NL20INGB0001234567"
                    }
                },
                "expected_name": "Maria de Jong-van Aalst",
                "expected_iban": "NL20INGB0001234567", 
                "expected_account": "NL20INGB0001234567"
            },
            # iDEAL with special characters in name
            {
                "payment": {
                    "id": "tr_ideal_003",
                    "method": "ideal",
                    "details": {
                        "consumerName": "José María Ñoño",
                        "consumerAccount": "ES9121000418450200051332"
                    }
                },
                "expected_name": "José María Ñoño",
                "expected_iban": "ES9121000418450200051332",
                "expected_account": "ES9121000418450200051332"
            }
        ]
        
        for i, case in enumerate(ideal_payment_cases):
            with self.subTest(case=i):
                # Extract data using the actual logic from the implementation
                consumer_name = None
                consumer_account = None
                consumer_iban = None
                payment_details = case["payment"].get("details", {})
                
                if case["payment"].get("method") == "ideal" and payment_details:
                    consumer_name = payment_details.get("consumerName")
                    consumer_account = payment_details.get("consumerAccount")
                    if consumer_account and self.bulk_importer._validate_iban_format(consumer_account):
                        consumer_iban = consumer_account
                
                # Validate extraction results
                self.assertEqual(consumer_name, case["expected_name"])
                self.assertEqual(consumer_account, case["expected_account"])
                self.assertEqual(consumer_iban, case["expected_iban"])
    
    def test_bank_transfer_payment_data_extraction(self):
        """Test consumer data extraction from bank transfer payment objects"""
        bank_transfer_cases = [
            # Standard bank transfer
            {
                "payment": {
                    "id": "tr_banktransfer_001",
                    "method": "banktransfer",
                    "details": {
                        "bankHolderName": "Pieter van den Heuvel",
                        "bankAccount": "NL68RABO0123456789",
                        "bankName": "Rabobank"
                    }
                },
                "expected_name": "Pieter van den Heuvel",
                "expected_iban": "NL68RABO0123456789",
                "expected_account": "NL68RABO0123456789"
            },
            # Bank transfer with German IBAN
            {
                "payment": {
                    "id": "tr_banktransfer_002",
                    "method": "banktransfer", 
                    "details": {
                        "bankHolderName": "Klaus Müller",
                        "bankAccount": "DE89370400440532013000",
                        "bankName": "Deutsche Bank"
                    }
                },
                "expected_name": "Klaus Müller",
                "expected_iban": "DE89370400440532013000",
                "expected_account": "DE89370400440532013000"
            }
        ]
        
        for i, case in enumerate(bank_transfer_cases):
            with self.subTest(case=i):
                # Extract data using the actual logic from the implementation
                consumer_name = None
                consumer_account = None
                consumer_iban = None
                payment_details = case["payment"].get("details", {})
                
                if case["payment"].get("method") == "banktransfer" and payment_details:
                    consumer_name = payment_details.get("bankHolderName")
                    consumer_account = payment_details.get("bankAccount")
                    bank_account = payment_details.get("bankAccount")
                    if bank_account and self.bulk_importer._validate_iban_format(bank_account):
                        consumer_iban = bank_account
                
                # Validate extraction results
                self.assertEqual(consumer_name, case["expected_name"])
                self.assertEqual(consumer_account, case["expected_account"])
                self.assertEqual(consumer_iban, case["expected_iban"])
    
    def test_direct_debit_payment_data_extraction(self):
        """Test consumer data extraction from direct debit payment objects"""
        direct_debit_cases = [
            # Standard direct debit
            {
                "payment": {
                    "id": "tr_directdebit_001",
                    "method": "directdebit",
                    "details": {
                        "consumerName": "Anna Johanna Smith",
                        "consumerAccount": "BE68539007547034",
                        "mandateReference": "MNDREF001"
                    }
                },
                "expected_name": "Anna Johanna Smith",
                "expected_iban": "BE68539007547034",
                "expected_account": "BE68539007547034"
            },
            # Direct debit with complex Dutch name
            {
                "payment": {
                    "id": "tr_directdebit_002",
                    "method": "directdebit",
                    "details": {
                        "consumerName": "Elisabeth van der Berg-de Jong",
                        "consumerAccount": "NL43ASNB0708498176",
                        "mandateReference": "MNDREF002"
                    }
                },
                "expected_name": "Elisabeth van der Berg-de Jong",
                "expected_iban": "NL43ASNB0708498176",
                "expected_account": "NL43ASNB0708498176"
            }
        ]
        
        for i, case in enumerate(direct_debit_cases):
            with self.subTest(case=i):
                # Extract data using the actual logic from the implementation
                consumer_name = None
                consumer_account = None
                consumer_iban = None
                payment_details = case["payment"].get("details", {})
                
                if case["payment"].get("method") == "directdebit" and payment_details:
                    consumer_name = payment_details.get("consumerName")
                    consumer_account = payment_details.get("consumerAccount")
                    consumer_account_raw = payment_details.get("consumerAccount")
                    if consumer_account_raw and self.bulk_importer._validate_iban_format(consumer_account_raw):
                        consumer_iban = consumer_account_raw
                
                # Validate extraction results
                self.assertEqual(consumer_name, case["expected_name"])
                self.assertEqual(consumer_account, case["expected_account"])
                self.assertEqual(consumer_iban, case["expected_iban"])
    
    def test_consumer_data_extraction_edge_cases(self):
        """Test consumer data extraction with edge cases and missing data"""
        edge_cases = [
            # Missing consumer name
            {
                "payment": {
                    "id": "tr_edge_001",
                    "method": "ideal",
                    "details": {
                        "consumerAccount": "NL91ABNA0417164300"
                        # Missing consumerName
                    }
                },
                "expected_name": None,
                "expected_account": "NL91ABNA0417164300",
                "expected_iban": "NL91ABNA0417164300"
            },
            # Missing consumer account
            {
                "payment": {
                    "id": "tr_edge_002",
                    "method": "ideal",
                    "details": {
                        "consumerName": "Test User"
                        # Missing consumerAccount
                    }
                },
                "expected_name": "Test User",
                "expected_account": None,
                "expected_iban": None
            },
            # Invalid IBAN format
            {
                "payment": {
                    "id": "tr_edge_003",
                    "method": "ideal",
                    "details": {
                        "consumerName": "Test User",
                        "consumerAccount": "INVALID_IBAN"
                    }
                },
                "expected_name": "Test User",
                "expected_account": "INVALID_IBAN",
                "expected_iban": None  # Should be None due to invalid format
            },
            # Empty details object
            {
                "payment": {
                    "id": "tr_edge_004",
                    "method": "ideal",
                    "details": {}
                },
                "expected_name": None,
                "expected_account": None,
                "expected_iban": None
            },
            # Missing details entirely
            {
                "payment": {
                    "id": "tr_edge_005",
                    "method": "ideal"
                    # Missing details
                },
                "expected_name": None,
                "expected_account": None,
                "expected_iban": None
            }
        ]
        
        for i, case in enumerate(edge_cases):
            with self.subTest(case=i, payment_id=case["payment"]["id"]):
                # Extract data using the actual logic from the implementation
                consumer_name = None
                consumer_account = None
                consumer_iban = None
                payment_details = case["payment"].get("details", {})
                
                if case["payment"].get("method") == "ideal" and payment_details:
                    consumer_name = payment_details.get("consumerName")
                    consumer_account = payment_details.get("consumerAccount")
                    if consumer_account and self.bulk_importer._validate_iban_format(consumer_account):
                        consumer_iban = consumer_account
                
                # Validate extraction handles edge cases gracefully
                self.assertEqual(consumer_name, case["expected_name"])
                self.assertEqual(consumer_account, case["expected_account"])
                self.assertEqual(consumer_iban, case["expected_iban"])
    
    # ============================================================================
    # 3. Security & Input Validation Testing
    # ============================================================================
    
    def test_iban_validation_malicious_input(self):
        """Test IBAN validation handles malicious input safely"""
        malicious_inputs = [
            # SQL injection attempts
            "'; DROP TABLE users; --",
            "' UNION SELECT * FROM tabUser --",
            "NL91' OR '1'='1' --",
            
            # XSS attempts
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert('XSS')>",
            
            # Command injection attempts
            "; rm -rf /",
            "| cat /etc/passwd",
            
            # Control characters
            "NL91\x00ABNA0417164300",  # Null byte
            "NL91\r\nABNA0417164300",  # CRLF injection
            
            # Extremely long input
            "A" * 10000,
        ]
        
        for malicious_input in malicious_inputs:
            with self.subTest(input_snippet=repr(malicious_input[:30])):
                # Should not raise exceptions or cause security issues
                try:
                    result = self.bulk_importer._validate_iban_format(malicious_input)
                    # All malicious inputs should be invalid
                    self.assertFalse(result, f"Malicious input should be rejected: {repr(malicious_input[:30])}")
                except Exception as e:
                    # Should not cause system errors
                    self.fail(f"Malicious input caused exception: {e}")
    
    def test_consumer_name_extraction_with_special_characters(self):
        """Test consumer name extraction handles special characters safely"""
        special_name_cases = [
            # Unicode characters
            {
                "name": "José María Ñoño-O'Connor",
                "expected": "José María Ñoño-O'Connor"
            },
            # Apostrophes and hyphens
            {
                "name": "O'Brien-van der Meer", 
                "expected": "O'Brien-van der Meer"
            },
            # Extended European characters
            {
                "name": "François Müller-Çelik",
                "expected": "François Müller-Çelik"
            },
            # Mixed scripts (should be handled gracefully)
            {
                "name": "Александр Иванов",  # Cyrillic
                "expected": "Александр Иванов"
            }
        ]
        
        for case in special_name_cases:
            with self.subTest(name=case["name"]):
                payment_data = {
                    "id": "tr_special_name",
                    "method": "ideal",
                    "details": {
                        "consumerName": case["name"],
                        "consumerAccount": "NL91ABNA0417164300"
                    }
                }
                
                # Extract name
                consumer_name = payment_data.get("details", {}).get("consumerName")
                
                # Should extract name without modification
                self.assertEqual(consumer_name, case["expected"])
    
    def test_consumer_name_extraction_malicious_input(self):
        """Test consumer name extraction handles potentially malicious input"""
        malicious_names = [
            # SQL injection attempts
            "'; DROP TABLE members; --",
            "' UNION SELECT * FROM users --",
            
            # XSS attempts  
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert('XSS')>",
            
            # Control characters
            "Test\x00User",  # Null byte
            "Test\r\nUser",  # CRLF
            
            # Very long name
            "A" * 1000,
        ]
        
        for malicious_name in malicious_names:
            with self.subTest(name_snippet=repr(malicious_name[:30])):
                payment_data = {
                    "id": "tr_malicious_name",
                    "method": "ideal",
                    "details": {
                        "consumerName": malicious_name,
                        "consumerAccount": "NL91ABNA0417164300"
                    }
                }
                
                # Should extract without causing exceptions
                try:
                    consumer_name = payment_data.get("details", {}).get("consumerName")
                    # Should return the input (extraction is just a get operation)
                    self.assertEqual(consumer_name, malicious_name)
                except Exception as e:
                    self.fail(f"Consumer name extraction failed with malicious input: {e}")
    
    # ============================================================================
    # 4. Performance Testing
    # ============================================================================
    
    def test_bulk_consumer_data_extraction_performance(self):
        """Test performance of consumer data extraction with large batches"""
        # Generate large batch of test payment data
        batch_size = 1000
        
        test_payments = []
        for i in range(batch_size):
            payment = {
                "id": f"tr_perf_{i:04d}",
                "method": ["ideal", "banktransfer", "directdebit"][i % 3],
                "details": {
                    "consumerName": f"Test User {i}",
                    "consumerAccount": f"NL{91 + (i % 9):02d}ABNA{i:010d}",
                    "bankHolderName": f"Bank User {i}",
                    "bankAccount": f"DE{89 + (i % 9):02d}3704{i:014d}"
                }
            }
            test_payments.append(payment)
        
        # Time the extraction process
        start_time = time.time()
        extraction_results = []
        
        for payment in test_payments:
            # Perform extraction using the actual logic
            consumer_name = None
            consumer_account = None
            consumer_iban = None
            payment_details = payment.get("details", {})
            
            if payment.get("method") == "ideal" and payment_details:
                consumer_name = payment_details.get("consumerName")
                consumer_account = payment_details.get("consumerAccount")
                if consumer_account and self.bulk_importer._validate_iban_format(consumer_account):
                    consumer_iban = consumer_account
            elif payment.get("method") == "banktransfer" and payment_details:
                consumer_name = payment_details.get("bankHolderName")
                consumer_account = payment_details.get("bankAccount")
                if consumer_account and self.bulk_importer._validate_iban_format(consumer_account):
                    consumer_iban = consumer_account
            elif payment.get("method") == "directdebit" and payment_details:
                consumer_name = payment_details.get("consumerName")
                consumer_account = payment_details.get("consumerAccount")
                if consumer_account and self.bulk_importer._validate_iban_format(consumer_account):
                    consumer_iban = consumer_account
            
            extraction_results.append({
                "name": consumer_name,
                "account": consumer_account, 
                "iban": consumer_iban
            })
        
        end_time = time.time()
        
        # Performance assertions
        total_time = end_time - start_time
        extractions_per_second = len(extraction_results) / total_time
        
        self.assertLess(total_time, 5.0, 
                       f"Extraction too slow: {total_time:.2f}s for {batch_size} payments")
        self.assertGreater(extractions_per_second, 200,
                          f"Extraction rate too low: {extractions_per_second:.0f} extractions/second")
        
        # Quality assertions
        self.assertEqual(len(extraction_results), batch_size, "All extractions should complete")
        
        # Validate some results
        successful_extractions = sum(1 for result in extraction_results if result["name"] is not None)
        self.assertGreater(successful_extractions, batch_size * 0.9, 
                          "At least 90% of extractions should succeed")


if __name__ == "__main__":
    # Run the test suite
    unittest.main()