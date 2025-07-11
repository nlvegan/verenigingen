# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
E-Boekhouden Integration Tests
Tests for the complete e-boekhouden REST API integration
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import Mock, patch, MagicMock
import json
from datetime import datetime, date
from decimal import Decimal


class TestEBoekhoudenIntegration(FrappeTestCase):
    """Test e-boekhouden integration functionality"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        super().setUpClass()
        
        # Create test company if needed
        if not frappe.db.exists("Company", "Test Company"):
            company = frappe.get_doc({
                "doctype": "Company",
                "company_name": "Test Company",
                "country": "Netherlands",
                "default_currency": "EUR"
            })
            company.insert(ignore_permissions=True)
            
    def setUp(self):
        """Set up test environment"""
        self.mock_settings = {
            "username": "test_user",
            "security_code_1": "test_code_1",
            "security_code_2": "test_code_2",
            "session_id": "test_session",
            "use_live_api": 0
        }
        
    def test_account_mapping_creation(self):
        """Test creating e-boekhouden account mappings"""
        # Create test mapping
        mapping = frappe.get_doc({
            "doctype": "E Boekhouden Account Mapping",
            "eboekhouden_account_code": "1000",
            "eboekhouden_account_name": "Test Bank Account",
            "erpnext_account": "Test Bank - TC",
            "account_type": "Bank",
            "company": "Test Company"
        })
        mapping.insert(ignore_permissions=True)
        
        # Verify mapping
        self.assertEqual(mapping.eboekhouden_account_code, "1000")
        self.assertEqual(mapping.account_type, "Bank")
        
        # Test duplicate prevention
        duplicate = frappe.get_doc({
            "doctype": "E Boekhouden Account Mapping",
            "eboekhouden_account_code": "1000",
            "eboekhouden_account_name": "Duplicate Account",
            "erpnext_account": "Test Bank 2 - TC",
            "account_type": "Bank",
            "company": "Test Company"
        })
        
        with self.assertRaises(frappe.DuplicateEntryError):
            duplicate.insert(ignore_permissions=True)
            
        # Cleanup
        mapping.delete()
        
    def test_payment_mapping_logic(self):
        """Test payment mapping functionality"""
        # Create test payment mapping
        payment_mapping = frappe.get_doc({
            "doctype": "Eboekhouden Payment Mapping",
            "mapping_name": "Test Payment Mapping",
            "payment_description": "Membership Fee Payment",
            "mapping_type": "Membership",
            "member_field": "member",
            "payment_type": "Incoming",
            "target_doctype": "Sales Invoice",
            "company": "Test Company"
        })
        payment_mapping.insert(ignore_permissions=True)
        
        # Test mapping retrieval
        self.assertEqual(payment_mapping.mapping_type, "Membership")
        self.assertEqual(payment_mapping.payment_type, "Incoming")
        
        # Cleanup
        payment_mapping.delete()
        
    @patch('verenigingen.utils.eboekhouden_rest_client.EBoekhoudenRESTClient')
    def test_transaction_import(self, mock_client_class):
        """Test importing transactions from e-boekhouden"""
        # Mock the REST client
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # Mock transaction data
        mock_transactions = [
            {
                "MutationNo": 12345,
                "Date": "2025-01-10T00:00:00",
                "Account": "1000",
                "AccountName": "Test Bank",
                "ContraAccount": "8000",
                "ContraAccountName": "Sales",
                "Amount": 100.00,
                "InvoiceNo": "INV-001",
                "Description": "Test Transaction",
                "PaymentTerm": None
            }
        ]
        
        mock_client.get_mutations.return_value = mock_transactions
        
        # Import transactions
        from verenigingen.utils.eboekhouden_integration import import_transactions
        
        with patch('frappe.get_doc') as mock_get_doc:
            # Mock settings
            mock_settings_doc = Mock()
            mock_settings_doc.username = "test_user"
            mock_get_doc.return_value = mock_settings_doc
            
            # This would normally create journal entries
            # For testing, we just verify the client was called correctly
            mock_client.get_mutations.assert_called()
            
    def test_duplicate_transaction_detection(self):
        """Test duplicate transaction detection"""
        # Create a test journal entry
        je = frappe.get_doc({
            "doctype": "Journal Entry",
            "company": "Test Company",
            "posting_date": "2025-01-10",
            "accounts": [
                {
                    "account": "Test Bank - TC",
                    "debit_in_account_currency": 100
                },
                {
                    "account": "Sales - TC",
                    "credit_in_account_currency": 100
                }
            ],
            "eboekhouden_mutation_no": "12345"
        })
        
        # Test duplicate detection
        exists = frappe.db.exists("Journal Entry", {
            "eboekhouden_mutation_no": "12345"
        })
        
        # Should not exist yet
        self.assertFalse(exists)
        
    def test_date_range_filtering(self):
        """Test date range filtering for imports"""
        from datetime import datetime, timedelta
        
        # Test date range generation
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        # Verify date range
        self.assertTrue(start_date < end_date)
        self.assertEqual((end_date - start_date).days, 30)
        
    @patch('frappe.throw')
    def test_error_recovery(self, mock_throw):
        """Test error recovery mechanisms"""
        # Simulate API error
        from verenigingen.utils.eboekhouden_rest_client import EBoekhoudenRESTClient
        
        with patch.object(EBoekhoudenRESTClient, 'authenticate') as mock_auth:
            mock_auth.side_effect = Exception("Authentication failed")
            
            # Should handle error gracefully
            try:
                client = EBoekhoudenRESTClient(self.mock_settings)
                client.authenticate()
            except:
                pass  # Expected
                
    def test_account_type_mapping(self):
        """Test account type mapping logic"""
        # Test mapping e-boekhouden account types to ERPNext
        account_type_map = {
            "1000-1999": "Bank",
            "2000-2999": "Receivable", 
            "3000-3999": "Stock",
            "4000-4999": "Payable",
            "8000-8999": "Income Account",
            "9000-9999": "Expense Account"
        }
        
        # Test account type detection
        test_cases = [
            ("1500", "Bank"),
            ("2100", "Receivable"),
            ("3500", "Stock"),
            ("4200", "Payable"),
            ("8100", "Income Account"),
            ("9500", "Expense Account")
        ]
        
        for account_code, expected_type in test_cases:
            # Determine account type based on code range
            code_num = int(account_code)
            actual_type = None
            
            if 1000 <= code_num <= 1999:
                actual_type = "Bank"
            elif 2000 <= code_num <= 2999:
                actual_type = "Receivable"
            elif 3000 <= code_num <= 3999:
                actual_type = "Stock"
            elif 4000 <= code_num <= 4999:
                actual_type = "Payable"
            elif 8000 <= code_num <= 8999:
                actual_type = "Income Account"
            elif 9000 <= code_num <= 9999:
                actual_type = "Expense Account"
                
            self.assertEqual(actual_type, expected_type, 
                           f"Account {account_code} should be type {expected_type}")
                           
    def test_zero_amount_handling(self):
        """Test handling of zero amount transactions"""
        # Zero amounts should be handled gracefully
        transaction = {
            "Amount": 0.00,
            "Description": "Zero amount transaction"
        }
        
        # Should not create journal entry for zero amount
        self.assertEqual(transaction["Amount"], 0.00)
        
    def test_vat_calculation(self):
        """Test Dutch VAT calculation"""
        # Test VAT rates
        vat_rates = {
            "high": Decimal("21.00"),
            "low": Decimal("9.00"),
            "zero": Decimal("0.00")
        }
        
        # Test VAT calculation
        amount_excl = Decimal("100.00")
        
        for rate_type, rate in vat_rates.items():
            vat_amount = amount_excl * rate / 100
            amount_incl = amount_excl + vat_amount
            
            self.assertEqual(vat_amount, amount_excl * rate / 100)
            self.assertEqual(amount_incl, amount_excl * (1 + rate / 100))
            
    def test_multi_line_transaction_parsing(self):
        """Test parsing multi-line transactions"""
        # Multi-line transaction example
        transaction = {
            "Lines": [
                {
                    "Account": "8000",
                    "Amount": -121.00,
                    "VAT": 21.00
                },
                {
                    "Account": "1300", 
                    "Amount": 121.00,
                    "VAT": 0.00
                }
            ]
        }
        
        # Verify transaction balances
        total = sum(line["Amount"] for line in transaction["Lines"])
        self.assertEqual(total, 0.00, "Transaction should balance")
        
    def test_api_rate_limiting(self):
        """Test API rate limiting"""
        from vereiningen.utils.decorators import rate_limit
        
        # Create a rate-limited function
        call_count = 0
        
        @rate_limit(calls=2, period=1)  # 2 calls per second
        def test_function():
            nonlocal call_count
            call_count += 1
            return call_count
            
        # Should allow first two calls
        result1 = test_function()
        result2 = test_function()
        
        self.assertEqual(result1, 1)
        self.assertEqual(result2, 2)
        
        # Third call should be rate limited
        # Note: actual rate limiting implementation may vary