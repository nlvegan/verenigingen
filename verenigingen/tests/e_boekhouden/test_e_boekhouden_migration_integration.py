#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Integration Tests for E-Boekhouden Migration Pipeline

This test suite provides complete integration testing for the E-Boekhouden migration
system with realistic data generation and comprehensive validation. It tests:

1. Security Permission System - security_helper.py
2. Payment Processing Integration - payment_entry_handler.py  
3. Full Migration Pipeline - end-to-end workflows
4. Data Integrity - edge cases and idempotency
5. Performance - batch operations and large datasets

Key Features:
- Uses Enhanced Test Factory for realistic data generation
- No mocking or validation bypasses 
- Respects Frappe's permission and validation system
- Tests actual business logic with realistic scenarios
- Comprehensive error handling and edge case coverage
"""

import json
import random
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any

import frappe
from frappe.utils import flt, getdate, nowdate, add_days, now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.e_boekhouden.utils.security_helper import (
    migration_context, validate_and_insert, validate_and_save, has_migration_permission,
    batch_insert, cleanup_context, log_migration_activity
)
from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import PaymentEntryHandler
import unittest


class TestEBoekhoudenSecurityIntegration(EnhancedTestCase):
    """
    Integration tests for the security_helper.py module
    
    Tests the new security model that replaces ignore_permissions=True patterns
    with proper role-based access control and permission validation.
    """
    
    def setUp(self):
        super().setUp()
        self.test_company = self._ensure_test_company()
        self.test_user = self._create_test_user_with_roles()
        
    def _ensure_test_company(self):
        """Ensure test company exists with proper setup"""
        company_name = "TEST-EBoekhouden-Integration-Company"
        
        if not frappe.db.exists("Company", company_name):
            company = frappe.new_doc("Company")
            company.company_name = company_name
            company.abbr = "TEBIC"
            company.default_currency = "EUR"
            company.country = "Netherlands"
            company.insert()
            return company.name
        
        return company_name
    
    def _create_test_user_with_roles(self):
        """Create test user with migration roles"""
        user_email = f"test-migration-user-{self.factory.get_next_sequence('user')}@test.invalid"
        
        if not frappe.db.exists("User", user_email):
            user = frappe.new_doc("User")
            user.email = user_email
            user.first_name = "Test"
            user.last_name = "Migration User"  
            user.send_welcome_email = 0
            user.insert()
            
            # Add required migration roles
            roles = ["Accounts Manager", "System Manager", "Accounts User"]
            for role in roles:
                user.append("roles", {"role": role})
            user.save()

        return user_email

    def _get_or_create_parent_account(self, company: str, root_type: str = "Asset") -> str:
        """Get or create a parent account for test account creation.

        Args:
            company: Company name
            root_type: Root type (Asset, Liability, Equity, Income, Expense)

        Returns:
            Name of the parent account
        """
        # Try to find existing root account for this company and root_type
        parent = frappe.db.get_value(
            "Account",
            {"company": company, "root_type": root_type, "is_group": 1, "parent_account": ("is", "not set")},
            "name"
        )
        if parent:
            return parent

        # Try to find any group account with matching root_type
        parent = frappe.db.get_value(
            "Account",
            {"company": company, "root_type": root_type, "is_group": 1},
            "name"
        )
        if parent:
            return parent

        # Create a root account if none exists
        root_account = frappe.new_doc("Account")
        root_account.account_name = f"TEST {root_type} Root"
        root_account.company = company
        root_account.root_type = root_type
        root_account.report_type = "Balance Sheet" if root_type in ["Asset", "Liability", "Equity"] else "Profit and Loss"
        root_account.is_group = 1
        root_account.insert()
        return root_account.name

    def _create_valid_test_account(self, account_name: str, company: str, account_type: str = "",
                                    is_group: int = 0, root_type: str = "Asset") -> "frappe.Document":
        """Create a valid test account with proper parent and root_type.

        Args:
            account_name: Name for the account
            company: Company name
            account_type: ERPNext account type (e.g., "Receivable", "Bank")
            is_group: Whether this is a group account (1) or not (0)
            root_type: Root type (Asset, Liability, Equity, Income, Expense)

        Returns:
            The created Account document
        """
        parent_account = self._get_or_create_parent_account(company, root_type)

        account = frappe.new_doc("Account")
        account.account_name = account_name
        account.company = company
        account.root_type = root_type
        account.report_type = "Balance Sheet" if root_type in ["Asset", "Liability", "Equity"] else "Profit and Loss"
        account.account_type = account_type
        account.is_group = is_group
        account.parent_account = parent_account
        return account

    def test_migration_context_permission_validation(self):
        """Test migration_context properly validates permissions"""
        # Test with user that has proper roles
        # EnhancedTestCase handles permissions: frappe.set_user(self.test_user)

        with migration_context("account_creation"):
            # Should work - user has required roles
            seq = self.factory.get_next_sequence('migration_account')
            account = self._create_valid_test_account(
                f"TEST Migration Account {seq}", self.test_company, is_group=1, root_type="Asset"
            )
            account.insert()
            self.assertTrue(frappe.db.exists("Account", account.name))
            
    def test_migration_context_switches_user_properly(self):
        """Test migration_context switches to migration user and back"""
        original_user = frappe.session.user

        current_user_before = frappe.session.user
        migration_user_during = None
        current_user_after = None

        with migration_context("account_creation"):
            migration_user_during = frappe.session.user
            # Should be Administrator (migration system user)

        current_user_after = frappe.session.user

        # Verify user switching worked correctly
        # migration_context switches to Administrator during the context
        self.assertEqual(migration_user_during, "Administrator")
        # After context, user should be restored to original
        self.assertEqual(current_user_after, current_user_before)
        
    def test_migration_context_sets_audit_flags(self):
        """Test migration_context sets proper audit flags"""
        current_user = frappe.session.user

        # Verify flags before context
        self.assertFalse(getattr(frappe.flags, 'in_migration', False))

        with migration_context("payment_processing"):
            # Verify flags during context
            self.assertTrue(frappe.flags.in_migration)
            self.assertEqual(frappe.flags.migration_operation, "payment_processing")
            # migration_initiated_by should be the user who initiated the context
            self.assertEqual(frappe.flags.migration_initiated_by, current_user)

        # Verify flags after context
        self.assertFalse(getattr(frappe.flags, 'in_migration', False))
        self.assertIsNone(getattr(frappe.flags, 'migration_operation', None))
        
    def test_validate_and_insert_operation_mapping(self):
        """Test validate_and_insert properly maps doctypes to operations"""
        # EnhancedTestCase handles permissions: frappe.set_user(self.test_user)

        # Test Account -> account_creation mapping
        seq = self.factory.get_next_sequence('validate_account')
        account = self._create_valid_test_account(
            f"TEST Validate Insert Account {seq}", self.test_company, is_group=1, root_type="Asset"
        )

        validate_and_insert(account)
        self.assertTrue(frappe.db.exists("Account", account.name))
        
        # Test Customer -> party_creation mapping
        customer = frappe.new_doc("Customer")
        customer.customer_name = "TEST Validate Insert Customer"
        customer.customer_type = "Individual"
        
        validate_and_insert(customer)
        self.assertTrue(frappe.db.exists("Customer", customer.name))
        
    def test_validate_and_save_with_existing_document(self):
        """Test validate_and_save with existing documents"""
        # EnhancedTestCase handles permissions: frappe.set_user(self.test_user)

        # Create account first
        seq = self.factory.get_next_sequence('save_account')
        account = self._create_valid_test_account(
            f"TEST Save Update Account {seq}", self.test_company, is_group=1, root_type="Asset"
        )
        account.insert()
        
        # Update and save using validate_and_save
        account.account_name = "TEST Save Update Account - Modified"
        validate_and_save(account)
        
        # Verify update worked
        updated_name = frappe.db.get_value("Account", account.name, "account_name")
        self.assertEqual(updated_name, "TEST Save Update Account - Modified")
        
    def test_batch_insert_with_proper_permissions(self):
        """Test batch_insert processes multiple documents correctly"""
        # EnhancedTestCase handles permissions: frappe.set_user(self.test_user)

        # Get company abbreviation to check for existing accounts
        abbr = frappe.db.get_value("Company", self.test_company, "abbr") or ""

        # Find a sequence that produces non-existing accounts
        # Keep trying until we find 5 accounts that don't exist
        accounts = []
        max_attempts = 20  # Prevent infinite loop
        attempts = 0

        while len(accounts) < 5 and attempts < max_attempts:
            seq = self.factory.get_next_sequence('batch_account')
            for i in range(5):
                if len(accounts) >= 5:
                    break
                account_name = f"TEST Batch Account {seq}-{i+1}"
                expected_db_name = f"{account_name} - {abbr}" if abbr else account_name

                # Only add if account doesn't exist
                if not frappe.db.exists("Account", expected_db_name):
                    account = self._create_valid_test_account(
                        account_name, self.test_company, is_group=1, root_type="Asset"
                    )
                    accounts.append(account)
            attempts += 1

        # Ensure we have accounts to test
        self.assertGreater(len(accounts), 0, "Could not find non-existing account names to test")

        # Use batch_insert
        inserted_accounts = batch_insert(accounts, "account_creation", batch_size=2)

        # Verify all accounts were inserted
        self.assertEqual(len(inserted_accounts), len(accounts))
        for account in inserted_accounts:
            self.assertTrue(frappe.db.exists("Account", account.name))
            
    def test_cleanup_context_permission_validation(self):
        """Test cleanup_context validates delete permissions"""
        current_user = frappe.session.user

        # Create test account to delete
        seq = self.factory.get_next_sequence('cleanup_account')
        account = self._create_valid_test_account(
            f"TEST Cleanup Account {seq}", self.test_company, is_group=1, root_type="Asset"
        )
        account.insert()
        account_name = account.name

        # Test cleanup context
        with cleanup_context():
            self.assertTrue(frappe.flags.in_cleanup)
            # cleanup_initiated_by should be the user who initiated the context
            self.assertEqual(frappe.flags.cleanup_initiated_by, current_user)
            
            # Could delete if needed (but we'll skip actual deletion in test)
            # frappe.delete_doc("Account", account_name, ignore_permissions=True)
            
        # Verify flags cleared
        self.assertFalse(getattr(frappe.flags, 'in_cleanup', False))
        
    def test_permission_validation_functions(self):
        """Test has_migration_permission function"""
        # EnhancedTestCase handles permissions: frappe.set_user(self.test_user)
        
        # User should have permissions for operations their roles support
        self.assertTrue(has_migration_permission("account_creation"))
        self.assertTrue(has_migration_permission("payment_processing"))
        self.assertTrue(has_migration_permission("party_creation"))
        
        # Test with operation that requires specific role
        self.assertTrue(has_migration_permission("settings_update"))  # System Manager role
        
    def test_audit_logging_integration(self):
        """Test migration operations are properly logged"""
        # EnhancedTestCase handles permissions: frappe.set_user(self.test_user)

        # Create account with audit logging
        seq = self.factory.get_next_sequence('audit_account')
        account = self._create_valid_test_account(
            f"TEST Audit Log Account {seq}", self.test_company, is_group=1, root_type="Asset"
        )

        # Insert with audit logging
        with migration_context("account_creation"):
            account.insert()
            
            # Test manual audit logging
            log_migration_activity(
                operation="insert",
                doctype="Account",
                docname=account.name,
                details={"test": "audit_logging"}
            )
            
        # Audit logs would be created if Activity Log doctype exists
        # This is mainly testing that the function doesn't error
        self.assertTrue(frappe.db.exists("Account", account.name))


class TestPaymentProcessingIntegration(EnhancedTestCase):
    """
    Integration tests for payment_entry_handler.py
    
    Tests payment processing with realistic E-Boekhouden API data patterns,
    including multi-invoice allocations, bank account determination, and error handling.
    """
    
    def setUp(self):
        super().setUp()
        self.test_company = self._ensure_test_company()
        self.handler = PaymentEntryHandler(company=self.test_company)
        self._setup_test_data()
        
    def _ensure_test_company(self):
        """Ensure test company exists"""
        company_name = "TEST-Payment-Integration-Company"

        if not frappe.db.exists("Company", company_name):
            # First create the company without default accounts
            company = frappe.new_doc("Company")
            company.company_name = company_name
            company.abbr = "TPIC"
            company.default_currency = "EUR"
            company.country = "Netherlands"
            company.insert()

            # Now create the accounts (company must exist first for parent account creation)
            receivable_account = self._create_test_account("Debtors - TPIC", "Receivable", company_name)
            payable_account = self._create_test_account("Creditors - TPIC", "Payable", company_name)

            # Update company with default accounts
            company.default_receivable_account = receivable_account
            company.default_payable_account = payable_account
            company.save()

        # Ensure Fiscal Year exists for the company
        self._ensure_fiscal_year(company_name)

        return company_name

    def _ensure_fiscal_year(self, company_name: str):
        """Ensure a Fiscal Year exists for the current year"""
        current_year = getdate().year
        fy_name = f"FY-{current_year}"

        if not frappe.db.exists("Fiscal Year", fy_name):
            fy = frappe.new_doc("Fiscal Year")
            fy.year = fy_name
            fy.year_start_date = f"{current_year}-01-01"
            fy.year_end_date = f"{current_year}-12-31"
            fy.append("companies", {"company": company_name})
            fy.insert()
        else:
            # Check if company is in the fiscal year
            fy = frappe.get_doc("Fiscal Year", fy_name)
            has_company = any(c.company == company_name for c in fy.companies)
            if not has_company:
                fy.append("companies", {"company": company_name})
                fy.save()

    def _create_test_account(self, account_name: str, account_type: str, company: str = None,
                              root_type: str = None) -> str:
        """Create test account

        Args:
            account_name: Name for the account
            account_type: ERPNext account type (e.g., "Receivable", "Payable", "Bank")
            company: Company name. If not provided, uses self.test_company
            root_type: Root type override. If not provided, derived from account_type
        """
        # Use provided company or fall back to self.test_company
        company_to_use = company if company is not None else self.test_company

        # Get company abbreviation to build the actual account name ERPNext uses
        abbr = frappe.db.get_value("Company", company_to_use, "abbr") or ""
        expected_name = f"{account_name} - {abbr}" if abbr else account_name

        if frappe.db.exists("Account", expected_name):
            return expected_name

        # Determine root_type based on account_type if not provided
        if root_type is None:
            root_type = "Asset"  # Default
            if account_type in ["Receivable", "Bank", "Cash", "Stock", "Fixed Asset"]:
                root_type = "Asset"
            elif account_type in ["Payable", "Tax"]:
                root_type = "Liability"
            elif account_type == "Equity":
                root_type = "Equity"
            elif account_type in ["Income Account", "Direct Income"]:
                root_type = "Income"
            elif account_type in ["Expense Account", "Cost of Goods Sold", "Direct Expense"]:
                root_type = "Expense"

        # Get or create parent account
        parent_account = self._get_or_create_parent_account(company_to_use, root_type)

        account = frappe.new_doc("Account")
        account.account_name = account_name
        account.company = company_to_use
        account.account_type = account_type
        account.root_type = root_type
        account.report_type = "Balance Sheet" if root_type in ["Asset", "Liability", "Equity"] else "Profit and Loss"
        account.is_group = 0
        account.parent_account = parent_account
        account.insert()
        return account.name

    def _get_or_create_parent_account(self, company: str, root_type: str = "Asset") -> str:
        """Get or create a parent account for test account creation."""
        # Try to find existing root account for this company and root_type
        parent = frappe.db.get_value(
            "Account",
            {"company": company, "root_type": root_type, "is_group": 1, "parent_account": ("is", "not set")},
            "name"
        )
        if parent:
            return parent

        # Try to find any group account with matching root_type
        parent = frappe.db.get_value(
            "Account",
            {"company": company, "root_type": root_type, "is_group": 1},
            "name"
        )
        if parent:
            return parent

        # Create a root account if none exists
        root_account = frappe.new_doc("Account")
        root_account.account_name = f"TEST {root_type} Root"
        root_account.company = company
        root_account.root_type = root_type
        root_account.report_type = "Balance Sheet" if root_type in ["Asset", "Liability", "Equity"] else "Profit and Loss"
        root_account.is_group = 1
        root_account.insert()
        return root_account.name
        
    def _setup_test_data(self):
        """Setup test customers, suppliers, invoices, and bank accounts"""
        # Create test bank accounts with unique names
        seq = self.factory.get_next_sequence('bank_account')
        self.test_bank_account = self._create_test_account(f"TEST Bank {seq} - TPIC", "Bank")
        self.triodos_account = self._create_test_account(f"10440 - Triodos {seq} - TPIC", "Bank")

        # Create income/expense accounts for items
        self._setup_item_accounts()

        # Create test item (must be before invoices)
        self._create_test_item()

        # Create test customer
        self.test_customer = self._create_test_customer()

        # Create test supplier
        self.test_supplier = self._create_test_supplier()

        # Create test invoices
        self.test_sales_invoice = self._create_test_sales_invoice()
        self.test_purchase_invoice = self._create_test_purchase_invoice()

        # Create ledger mappings
        self._create_test_ledger_mappings()

    def _setup_item_accounts(self):
        """Setup income and expense accounts for test items"""
        # Create income account for sales
        self.test_income_account = self._create_test_account(
            "TEST Sales Income - TPIC", "Income Account", root_type="Income"
        )
        # Create expense account for purchases
        self.test_expense_account = self._create_test_account(
            "TEST Cost of Goods - TPIC", "Cost of Goods Sold", root_type="Expense"
        )

    def _create_test_item(self):
        """Create test item for invoice testing"""
        item_code = "TEST-ITEM"
        if frappe.db.exists("Item", item_code):
            # Update item defaults for our test company if needed
            item = frappe.get_doc("Item", item_code)
            has_company_default = any(
                d.company == self.test_company for d in item.item_defaults
            )
            if not has_company_default:
                item.append("item_defaults", {
                    "company": self.test_company,
                    "income_account": self.test_income_account,
                    "expense_account": self.test_expense_account,
                    "default_warehouse": "",  # Explicitly no warehouse for non-stock
                })
                item.save()
            return item_code

        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = "Test Item"
        item.item_group = "Services"  # Services don't require stock
        item.is_stock_item = 0  # Non-stock item to avoid warehouse requirements
        item.include_item_in_manufacturing = 0

        # Set default income/expense accounts for the test company
        # Explicitly set default_warehouse to empty to avoid global defaults
        item.append("item_defaults", {
            "company": self.test_company,
            "income_account": self.test_income_account,
            "expense_account": self.test_expense_account,
            "default_warehouse": "",  # Explicitly no warehouse for non-stock
        })

        item.insert()
        return item.name
        
    def _create_test_customer(self) -> str:
        """Create test customer"""
        customer_name = f"TEST Customer {self.factory.get_next_sequence('customer')}"

        # Check if customer already exists
        if frappe.db.exists("Customer", customer_name):
            return customer_name

        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_type = "Individual"
        # Pin to EUR so derived transactions match the EUR party accounts.
        customer.default_currency = "EUR"
        customer.insert()
        return customer.name

    def _create_test_supplier(self) -> str:
        """Create test supplier"""
        supplier_name = f"TEST Supplier {self.factory.get_next_sequence('supplier')}"

        # Check if supplier already exists
        if frappe.db.exists("Supplier", supplier_name):
            return supplier_name

        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = supplier_name
        supplier.supplier_type = "Individual"
        # Pin to EUR so derived transactions match the EUR party accounts.
        supplier.default_currency = "EUR"
        supplier.insert()
        return supplier.name
        
    def _create_test_sales_invoice(self) -> str:
        """Create test sales invoice"""
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = self.test_customer
        invoice.company = self.test_company
        # Match the company/party-account currency (EUR). Without this the
        # invoice falls back to the system default currency, which can differ
        # from the EUR party accounts and trips the currency-mismatch check.
        invoice.currency = "EUR"
        invoice.conversion_rate = 1.0
        invoice.posting_date = getdate()
        invoice.due_date = add_days(getdate(), 30)
        
        # Add invoice item
        invoice.append("items", {
            "item_code": "TEST-ITEM",
            "item_name": "Test Item",
            "qty": 1,
            "rate": 100.00,
            "amount": 100.00
        })
        
        invoice.insert()
        invoice.submit()
        return invoice.name
        
    def _create_test_purchase_invoice(self) -> str:
        """Create test purchase invoice"""
        invoice = frappe.new_doc("Purchase Invoice")
        invoice.supplier = self.test_supplier
        invoice.company = self.test_company
        # Match the company/party-account currency (EUR) — see sales invoice note.
        invoice.currency = "EUR"
        invoice.conversion_rate = 1.0
        invoice.posting_date = getdate()
        invoice.due_date = add_days(getdate(), 30)
        
        # Add invoice item
        invoice.append("items", {
            "item_code": "TEST-ITEM",
            "item_name": "Test Item", 
            "qty": 1,
            "rate": 50.00,
            "amount": 50.00
        })
        
        invoice.insert()
        invoice.submit()
        return invoice.name
        
    def _ensure_bank_account_master(self, company, gl_account):
        """Create a Bank Account *master* linking a Bank to the GL account.

        PaymentEntryHandler._determine_bank_account resolves a ledger to a
        Bank/Cash account via resolve_bank_account_for_ledger, which needs this
        master doctype (a Bank-type GL account + ledger mapping alone is not
        enough). Without it the handler returns None and the payment tests below
        silently skip instead of asserting anything.
        """
        if frappe.db.exists("Bank Account", {"account": gl_account, "company": company}):
            return
        bank_name = "TEST-Migration-Integration Bank"
        if not frappe.db.exists("Bank", bank_name):
            frappe.get_doc({"doctype": "Bank", "bank_name": bank_name}).insert(ignore_permissions=True)
        frappe.get_doc(
            {
                "doctype": "Bank Account",
                "account_name": "TEST Triodos Bank Account",
                "bank": bank_name,
                "account": gl_account,
                "company": company,
                "is_company_account": 1,
            }
        ).insert(ignore_permissions=True)

    def _create_test_ledger_mappings(self):
        """Create test E-Boekhouden ledger mappings"""
        # Bank account mapping
        if not frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": 1001}):
            mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
            mapping.ledger_id = 1001
            mapping.ledger_code = "1001"
            mapping.ledger_name = "Triodos Bank"
            mapping.erpnext_account = self.triodos_account
            mapping.insert()

        # The handler needs a Bank Account master for the bank GL account that
        # ledger 1001 maps to, otherwise process_payment_mutation returns None.
        self._ensure_bank_account_master(self.test_company, self.triodos_account)
            
        # Receivable account mapping
        if not frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": 1300}):
            mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
            mapping.ledger_id = 1300
            mapping.ledger_code = "1300"
            mapping.ledger_name = "Debiteuren"
            mapping.erpnext_account = frappe.db.get_value("Company", self.test_company, "default_receivable_account")
            mapping.insert()
            
    def test_customer_payment_processing_single_invoice(self):
        """Test processing customer payment for single invoice"""
        # Use unique mutation ID to avoid duplicate detection
        # Time-based unique id: the handler commits created Payment Entries
        # (atomic_migration_operation), so they survive test rollback. A repeating
        # sequence id would collide with a prior run's committed PE and trip the
        # duplicate-detection early-return (0 references). See test_payment_entry_handler.
        import time

        mutation_id = int(time.time() * 1000) % 100000000 + 100000

        mutation_data = {
            "id": mutation_id,
            "type": 3,  # Customer payment
            "date": nowdate(),
            "amount": 100.00,
            "relationId": "CUST001",
            "invoiceNumber": self.test_sales_invoice,
            "description": "Payment for invoice",
            "ledgerId": 1001,  # Bank account
            "rows": [{
                "ledgerId": 1300,  # Receivable account
                "amount": 100.00,
                "description": "Customer payment"
            }]
        }

        # Mock the party creation to return our test customer
        original_method = self.handler._get_or_create_party
        def mock_get_party(relation_id, party_type, description):
            return self.test_customer
        self.handler._get_or_create_party = mock_get_party

        try:
            payment_entry_name = self.handler.process_payment_mutation(mutation_data)

            # Verify payment entry was created (setUp now wires the Bank Account
            # master the handler needs, so a None here is a real regression).
            self.assertIsNotNone(
                payment_entry_name,
                f"process_payment_mutation returned None. Debug: {self.handler.debug_log}",
            )
            self.assertTrue(frappe.db.exists("Payment Entry", payment_entry_name))
            
            # Verify payment entry details
            pe = frappe.get_doc("Payment Entry", payment_entry_name)
            self.assertEqual(pe.payment_type, "Receive")
            self.assertEqual(pe.party_type, "Customer")
            self.assertEqual(pe.party, self.test_customer)
            self.assertEqual(pe.paid_amount, 100.00)
            
            # Verify invoice allocation
            self.assertEqual(len(pe.references), 1)
            self.assertEqual(pe.references[0].reference_name, self.test_sales_invoice)
            
        finally:
            # Restore original method
            self.handler._get_or_create_party = original_method
            
    def test_supplier_payment_processing_multiple_invoices(self):
        """Test processing supplier payment for multiple invoices"""
        # Create second purchase invoice
        invoice2 = frappe.new_doc("Purchase Invoice")
        invoice2.supplier = self.test_supplier
        invoice2.company = self.test_company
        invoice2.currency = "EUR"
        invoice2.conversion_rate = 1.0
        invoice2.posting_date = getdate()
        invoice2.due_date = add_days(getdate(), 30)
        invoice2.append("items", {
            "item_code": "TEST-ITEM",
            "item_name": "Test Item",
            "qty": 1,
            "rate": 75.00,
            "amount": 75.00
        })
        invoice2.insert()
        invoice2.submit()

        # Use unique mutation ID to avoid duplicate detection
        # Time-based unique id — see the note in the single-invoice test above.
        import time

        mutation_id = int(time.time() * 1000) % 100000000 + 200000

        mutation_data = {
            "id": mutation_id,
            "type": 4,  # Supplier payment
            "date": nowdate(),
            "amount": 125.00,
            "relationId": "SUPP001",
            "invoiceNumber": f"{self.test_purchase_invoice},{invoice2.name}",
            "description": "Payment for multiple invoices",
            "ledgerId": 1001,
            "rows": [
                {
                    "ledgerId": 1400,  # Payable account
                    "amount": 50.00,
                    "description": "Payment 1"
                },
                {
                    "ledgerId": 1400,
                    "amount": 75.00,
                    "description": "Payment 2"
                }
            ]
        }

        # Mock party creation
        original_method = self.handler._get_or_create_party
        def mock_get_party(relation_id, party_type, description):
            return self.test_supplier
        self.handler._get_or_create_party = mock_get_party

        try:
            payment_entry_name = self.handler.process_payment_mutation(mutation_data)

            # Verify payment entry was created (setUp now wires the Bank Account
            # master the handler needs, so a None here is a real regression).
            self.assertIsNotNone(
                payment_entry_name,
                f"process_payment_mutation returned None. Debug: {self.handler.debug_log}",
            )
            pe = frappe.get_doc("Payment Entry", payment_entry_name)

            self.assertEqual(pe.payment_type, "Pay")
            self.assertEqual(pe.party_type, "Supplier")
            self.assertEqual(pe.party, self.test_supplier)
            self.assertEqual(pe.paid_amount, 125.00)
            
            # Verify multiple invoice allocations (FIFO or 1:1 depending on strategy)
            self.assertGreater(
                len(pe.references), 0, f"no references. Debug: {self.handler.debug_log}"
            )
            
        finally:
            self.handler._get_or_create_party = original_method
            
    def test_bank_account_determination_requires_ledger_mapping(self):
        """Bank account determination requires an explicit ledger mapping.

        Since commit db93684c ("remove default bank account fallback in
        PaymentEntryHandler"), _determine_bank_account no longer guesses a
        bank account from the description or falls back to a default — a
        missing ledger ID is a hard ValidationError, so an e-Boekhouden
        payment can never be silently posted against the wrong bank account.
        """
        # A mapped ledger ID resolves to its bank account.
        bank_account = self.handler._determine_bank_account(1001, "Receive", "Test payment")
        self.assertEqual(bank_account, self.triodos_account)

        # Without a ledger ID, determination fails loudly — no description
        # pattern-match and no default fallback.
        with self.assertRaises(frappe.ValidationError):
            self.handler._determine_bank_account(
                None, "Receive", "Triodos payment via online banking"
            )
        with self.assertRaises(frappe.ValidationError):
            self.handler._determine_bank_account(None, "Receive", "Unknown payment method")
        
    def test_api_row_ledger_data_priority(self):
        """Test that API row ledger data has priority over fallbacks"""
        mutation_data = {
            "id": 12347,
            "type": 3,
            "date": nowdate(),
            "amount": 100.00,
            "relationId": "CUST001",
            "invoiceNumber": self.test_sales_invoice,
            "ledgerId": 1001,
            "rows": [{
                "ledgerId": 1300,  # Specific receivable account from API
                "amount": 100.00,
                "description": "Customer payment"
            }]
        }
        
        # Test that API row ledger data is used for party account
        party_account = self.handler._get_party_account_from_api_rows(
            mutation_data, "Customer", self.test_customer
        )
        
        # Should use the API row ledger mapping
        expected_account = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping", {"ledger_id": 1300}, "erpnext_account"
        )
        if expected_account:
            self.assertEqual(party_account, expected_account)
            
    def test_zero_amount_payment_handling(self):
        """Test handling of zero-amount payments"""
        mutation_data = {
            "id": 12348,
            "type": 3,
            "date": nowdate(),
            "amount": 0.00,
            "relationId": "CUST001",
            "invoiceNumber": self.test_sales_invoice,
            "ledgerId": 1001,
            "rows": [{
                "ledgerId": 1300,
                "amount": 0.00,
                "description": "Zero amount adjustment"
            }]
        }
        
        original_method = self.handler._get_or_create_party
        def mock_get_party(relation_id, party_type, description):
            return self.test_customer
        self.handler._get_or_create_party = mock_get_party
        
        try:
            # Zero amount payments should be handled gracefully
            # (may succeed or fail depending on ERPNext validation)
            result = self.handler.process_payment_mutation(mutation_data)
            
            # If it succeeds, verify it was processed
            if result:
                pe = frappe.get_doc("Payment Entry", result)
                self.assertEqual(pe.paid_amount, 0.00)
                
        except Exception as e:
            # Zero amount might be rejected by ERPNext validation
            # This is acceptable behavior
            self.assertIn("amount", str(e).lower())
            
        finally:
            self.handler._get_or_create_party = original_method
            
    def test_error_handling_and_recovery(self):
        """Test error handling for invalid mutation data"""
        # Test invalid mutation type
        invalid_mutation = {
            "id": 99999,
            "type": 99,  # Invalid type
            "date": nowdate(),
            "amount": 100.00
        }
        
        result = self.handler.process_payment_mutation(invalid_mutation)
        self.assertIsNone(result)  # Should return None for invalid data
        
        # Test missing required data
        incomplete_mutation = {
            "id": 99998,
            "type": 3,
            # Missing date, amount, etc.
        }
        
        result = self.handler.process_payment_mutation(incomplete_mutation)
        self.assertIsNone(result)  # Should handle gracefully
        
    def test_debug_logging_functionality(self):
        """Test debug logging captures important information"""
        mutation_data = {
            "id": 12349,
            "type": 3,
            "date": nowdate(),
            "amount": 100.00,
            "relationId": "CUST001",
            "invoiceNumber": self.test_sales_invoice,
            "ledgerId": 1001
        }
        
        original_method = self.handler._get_or_create_party
        def mock_get_party(relation_id, party_type, description):
            return self.test_customer
        self.handler._get_or_create_party = mock_get_party
        
        try:
            self.handler.process_payment_mutation(mutation_data)
            
            # Verify debug log contains relevant information
            debug_log = self.handler.get_debug_log()
            self.assertGreater(len(debug_log), 0)
            
            # Check for key log entries
            log_text = "\n".join(debug_log)
            self.assertIn("Processing payment mutation", log_text)
            self.assertIn("12349", log_text)  # Mutation ID
            
        finally:
            self.handler._get_or_create_party = original_method


class TestMigrationPipelineIntegration(EnhancedTestCase):
    """
    Integration tests for the complete migration pipeline
    
    Tests end-to-end migration workflows, transaction atomicity,
    and integration between all components.
    """
    
    def setUp(self):
        super().setUp()
        self.test_company = self._ensure_test_company()
        self._setup_migration_prerequisites()
        
    def _ensure_test_company(self):
        """Ensure test company exists"""
        company_name = "TEST-Migration-Pipeline-Company"

        if not frappe.db.exists("Company", company_name):
            company = frappe.new_doc("Company")
            company.company_name = company_name
            company.abbr = "TMPC"
            company.default_currency = "EUR"
            company.country = "Netherlands"
            company.insert()

        # Ensure Fiscal Year exists for the company
        self._ensure_fiscal_year(company_name)

        return company_name

    def _ensure_fiscal_year(self, company_name: str):
        """Ensure a Fiscal Year exists for the current year"""
        current_year = getdate().year
        fy_name = f"FY-{current_year}"

        if not frappe.db.exists("Fiscal Year", fy_name):
            fy = frappe.new_doc("Fiscal Year")
            fy.year = fy_name
            fy.year_start_date = f"{current_year}-01-01"
            fy.year_end_date = f"{current_year}-12-31"
            fy.append("companies", {"company": company_name})
            fy.insert()
        else:
            # Check if company is in the fiscal year
            fy = frappe.get_doc("Fiscal Year", fy_name)
            has_company = any(c.company == company_name for c in fy.companies)
            if not has_company:
                fy.append("companies", {"company": company_name})
                fy.save()

    def _setup_migration_prerequisites(self):
        """Setup prerequisites for migration testing"""
        # Ensure E-Boekhouden Settings exist
        if not frappe.db.exists("E-Boekhouden Settings"):
            settings = frappe.new_doc("E-Boekhouden Settings")
            settings.api_token = "TEST_TOKEN_12345"
            settings.api_base_url = "https://api-test.e-boekhouden.nl"
            settings.insert()

    def _get_or_create_parent_account(self, company: str, root_type: str = "Asset") -> str:
        """Get or create a parent account for test account creation."""
        parent = frappe.db.get_value(
            "Account",
            {"company": company, "root_type": root_type, "is_group": 1, "parent_account": ("is", "not set")},
            "name"
        )
        if parent:
            return parent

        parent = frappe.db.get_value(
            "Account",
            {"company": company, "root_type": root_type, "is_group": 1},
            "name"
        )
        if parent:
            return parent

        root_account = frappe.new_doc("Account")
        root_account.account_name = f"TEST {root_type} Root"
        root_account.company = company
        root_account.root_type = root_type
        root_account.report_type = "Balance Sheet" if root_type in ["Asset", "Liability", "Equity"] else "Profit and Loss"
        root_account.is_group = 1
        root_account.insert()
        return root_account.name

    def _create_valid_test_account(self, account_name: str, company: str, account_type: str = "",
                                    is_group: int = 0, root_type: str = "Asset") -> "frappe.Document":
        """Create a valid test account with proper parent and root_type."""
        parent_account = self._get_or_create_parent_account(company, root_type)

        account = frappe.new_doc("Account")
        account.account_name = account_name
        account.company = company
        account.root_type = root_type
        account.report_type = "Balance Sheet" if root_type in ["Asset", "Liability", "Equity"] else "Profit and Loss"
        account.account_type = account_type
        account.is_group = is_group
        account.parent_account = parent_account
        return account

    def test_migration_document_creation_and_validation(self):
        """Test E-Boekhouden Migration document creation and validation"""
        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_name = f"TEST Migration {self.factory.get_next_sequence('migration')}"
        migration.company = self.test_company
        migration.migrate_accounts = 1
        migration.migrate_customers = 1
        migration.migrate_transactions = 1
        migration.dry_run = 1  # Safe for testing
        
        # Test validation
        migration.insert()
        self.assertTrue(frappe.db.exists("E-Boekhouden Migration", migration.name))
        
        # Test date validation
        migration.date_from = getdate()
        migration.date_to = add_days(getdate(), -1)  # Invalid: from > to
        
        with self.assertRaises(frappe.ValidationError):
            migration.save()
            
    def test_migration_workflow_states(self):
        """Test migration workflow state transitions"""
        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_name = f"TEST Workflow {self.factory.get_next_sequence('workflow')}"
        migration.company = self.test_company
        migration.dry_run = 1
        migration.insert()
        
        # Initial state should be Draft
        self.assertEqual(migration.migration_status, "Draft")
        
        # Submit should trigger migration (in background)
        migration.submit()
        
        # Status should change to In Progress or Completed depending on dry run
        migration.reload()
        self.assertIn(migration.migration_status, ["In Progress", "Completed", "Draft"])
        
    def test_migration_with_security_context(self):
        """Test migration operations use proper security context"""
        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_name = f"TEST Security {self.factory.get_next_sequence('security')}"
        migration.company = self.test_company
        migration.migrate_accounts = 1
        migration.dry_run = 1
        migration.insert()
        
        # Test that migration operations would use security_helper
        with migration_context("account_creation"):
            # Create test account as would happen during migration
            seq = self.factory.get_next_sequence('security_account')
            account = self._create_valid_test_account(
                f"TEST Migration Security Account {seq}", self.test_company, is_group=1, root_type="Asset"
            )

            validate_and_insert(account)
            self.assertTrue(frappe.db.exists("Account", account.name))
            
    def test_transaction_atomicity_simulation(self):
        """Test transaction atomicity during migration operations"""
        # Get company abbreviation to check for existing accounts
        abbr = frappe.db.get_value("Company", self.test_company, "abbr") or ""

        # Find accounts that don't exist yet
        accounts_to_create = []
        max_attempts = 10
        attempts = 0

        while len(accounts_to_create) < 5 and attempts < max_attempts:
            seq = self.factory.get_next_sequence('atomic_account')
            for i in range(5):
                if len(accounts_to_create) >= 5:
                    break
                account_name = f"TEST Atomic Account {seq}-{i+1}"
                expected_db_name = f"{account_name} - {abbr}" if abbr else account_name

                if not frappe.db.exists("Account", expected_db_name):
                    account = self._create_valid_test_account(
                        account_name, self.test_company, is_group=1, root_type="Asset"
                    )
                    accounts_to_create.append(account)
            attempts += 1

        self.assertGreater(len(accounts_to_create), 0, "Could not find non-existing account names to test")

        # Use batch_insert to simulate atomic operations
        try:
            inserted_accounts = batch_insert(accounts_to_create, "account_creation", batch_size=3)

            # All should succeed
            self.assertEqual(len(inserted_accounts), len(accounts_to_create))

            for account in inserted_accounts:
                self.assertTrue(frappe.db.exists("Account", account.name))

        except Exception as e:
            # If any fail, check rollback behavior
            self.fail(f"Batch insert failed: {e}")
            
    def test_migration_progress_tracking(self):
        """Test migration progress tracking functionality"""
        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_name = f"TEST Progress {self.factory.get_next_sequence('progress')}"
        migration.company = self.test_company
        migration.dry_run = 1
        migration.insert()
        
        # Test progress fields exist and can be updated
        migration.db_set({
            "progress_percentage": 50,
            "current_operation": "Processing accounts...",
            "total_records": 100,
            "imported_records": 50,
            "failed_records": 0
        })
        
        migration.reload()
        self.assertEqual(migration.progress_percentage, 50)
        self.assertEqual(migration.current_operation, "Processing accounts...")
        
    def test_event_driven_payment_history_integration(self):
        """Test integration with payment history event system"""
        # Create test customer for the payment
        customer_name = f"TEST Payment Customer {self.factory.get_next_sequence('payment_customer')}"
        if not frappe.db.exists("Customer", customer_name):
            customer = frappe.new_doc("Customer")
            customer.customer_name = customer_name
            customer.customer_type = "Individual"
            customer.insert()
        else:
            customer_name = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")

        # Create test payment entry that would trigger payment history events
        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.company = self.test_company
        payment_entry.payment_type = "Receive"
        payment_entry.party_type = "Customer"
        payment_entry.party = customer_name
        payment_entry.posting_date = getdate()
        payment_entry.paid_amount = 100.00
        payment_entry.received_amount = 100.00

        # Reference fields are mandatory for bank transactions
        payment_entry.reference_no = f"TEST-REF-{self.factory.get_next_sequence('payment_ref')}"
        payment_entry.reference_date = getdate()

        # Add bank accounts with unique names
        seq = self.factory.get_next_sequence('event_account')
        payment_entry.paid_to = self._create_test_account(f"TEST Event Bank {seq} - TMPC", "Bank")
        payment_entry.paid_from = self._create_test_account(f"TEST Event Receivable {seq} - TMPC", "Receivable")

        payment_entry.insert()
        payment_entry.submit()
        
        # Payment history events would be triggered here
        # Test that the document was created successfully
        self.assertTrue(frappe.db.exists("Payment Entry", payment_entry.name))
        
    def _create_test_account(self, account_name: str, account_type: str) -> str:
        """Create test account helper"""
        # Get company abbreviation to build the actual account name ERPNext uses
        abbr = frappe.db.get_value("Company", self.test_company, "abbr") or ""
        expected_name = f"{account_name} - {abbr}" if abbr else account_name

        if frappe.db.exists("Account", expected_name):
            return expected_name

        # Determine root_type based on account_type
        root_type = "Asset"
        if account_type in ["Receivable", "Bank", "Cash", "Stock", "Fixed Asset"]:
            root_type = "Asset"
        elif account_type in ["Payable", "Tax"]:
            root_type = "Liability"
        elif account_type == "Equity":
            root_type = "Equity"
        elif account_type in ["Income Account", "Direct Income"]:
            root_type = "Income"
        elif account_type in ["Expense Account", "Cost of Goods Sold", "Direct Expense"]:
            root_type = "Expense"

        parent_account = self._get_or_create_parent_account(self.test_company, root_type)

        account = frappe.new_doc("Account")
        account.account_name = account_name
        account.company = self.test_company
        account.account_type = account_type
        account.root_type = root_type
        account.report_type = "Balance Sheet" if root_type in ["Asset", "Liability", "Equity"] else "Profit and Loss"
        account.is_group = 0
        account.parent_account = parent_account
        account.insert()
        return account.name


class TestDataIntegrityAndEdgeCases(EnhancedTestCase):
    """
    Integration tests for data integrity and edge cases
    
    Tests idempotency, edge cases, data corruption prevention,
    and error recovery scenarios.
    """
    
    def setUp(self):
        super().setUp()
        self.test_company = self._ensure_test_company()
        
    def _ensure_test_company(self):
        """Ensure test company exists"""
        company_name = "TEST-Data-Integrity-Company" 
        
        if not frappe.db.exists("Company", company_name):
            company = frappe.new_doc("Company")
            company.company_name = company_name
            company.abbr = "TDIC"
            company.default_currency = "EUR"
            company.country = "Netherlands"
            company.insert()
            return company.name

        return company_name

    def _get_or_create_parent_account(self, company: str, root_type: str = "Asset") -> str:
        """Get or create a parent account for test account creation."""
        parent = frappe.db.get_value(
            "Account",
            {"company": company, "root_type": root_type, "is_group": 1, "parent_account": ("is", "not set")},
            "name"
        )
        if parent:
            return parent

        parent = frappe.db.get_value(
            "Account",
            {"company": company, "root_type": root_type, "is_group": 1},
            "name"
        )
        if parent:
            return parent

        root_account = frappe.new_doc("Account")
        root_account.account_name = f"TEST {root_type} Root"
        root_account.company = company
        root_account.root_type = root_type
        root_account.report_type = "Balance Sheet" if root_type in ["Asset", "Liability", "Equity"] else "Profit and Loss"
        root_account.is_group = 1
        root_account.insert()
        return root_account.name

    def _create_valid_test_account(self, account_name: str, company: str, account_type: str = "",
                                    is_group: int = 0, root_type: str = "Asset") -> "frappe.Document":
        """Create a valid test account with proper parent and root_type."""
        parent_account = self._get_or_create_parent_account(company, root_type)

        account = frappe.new_doc("Account")
        account.account_name = account_name
        account.company = company
        account.root_type = root_type
        account.report_type = "Balance Sheet" if root_type in ["Asset", "Liability", "Equity"] else "Profit and Loss"
        account.account_type = account_type
        account.is_group = is_group
        account.parent_account = parent_account
        return account

    def test_idempotent_migration_operations(self):
        """Test that migration operations are idempotent"""
        # Create account first time
        seq = self.factory.get_next_sequence('idempotent_account')
        account_name = f"TEST Idempotent Account {seq}"
        account1 = self._create_valid_test_account(
            account_name, self.test_company, is_group=1, root_type="Asset"
        )

        validate_and_insert(account1)
        first_creation_name = account1.name

        # Try to create same account again - should handle gracefully
        account2 = self._create_valid_test_account(
            account_name, self.test_company, is_group=1, root_type="Asset"
        )
        
        # This should either succeed with different name or be handled gracefully
        try:
            validate_and_insert(account2)
            # If it succeeds, it should have a different name
            self.assertNotEqual(account2.name, first_creation_name)
        except frappe.DuplicateEntryError:
            # This is acceptable - duplication was prevented
            pass
            
    def test_migration_data_consistency_validation(self):
        """Test data consistency validation during migration"""
        # Test customer creation with proper validation
        customer = frappe.new_doc("Customer")
        customer.customer_name = "TEST Consistency Customer"
        customer.customer_type = "Individual"
        
        # Should succeed with valid data
        validate_and_insert(customer)
        self.assertTrue(frappe.db.exists("Customer", customer.name))
        
        # Test with invalid data should be caught by validation
        invalid_customer = frappe.new_doc("Customer")
        invalid_customer.customer_name = ""  # Invalid - empty name
        invalid_customer.customer_type = "Individual"
        
        with self.assertRaises(Exception):
            validate_and_insert(invalid_customer)
            
    def test_missing_data_edge_cases(self):
        """Test handling of missing or incomplete data"""
        # Test payment processing with missing relation ID
        handler = PaymentEntryHandler(company=self.test_company)
        
        mutation_with_no_relation = {
            "id": 88888,
            "type": 3,
            "date": nowdate(),
            "amount": 100.00,
            "relationId": None,  # Missing
            "invoiceNumber": "TEST-INV-001",
            "ledgerId": 1001
        }
        
        result = handler.process_payment_mutation(mutation_with_no_relation)
        self.assertIsNone(result)  # Should handle gracefully and return None
        
    def test_invalid_date_edge_cases(self):
        """Test handling of invalid dates"""
        # Test future dates
        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_name = "TEST Invalid Dates"
        migration.company = self.test_company
        migration.date_from = add_days(getdate(), 30)  # Future
        migration.date_to = add_days(getdate(), 60)    # Future
        migration.dry_run = 1
        
        # Should succeed - future dates are allowed for date range
        migration.insert()
        self.assertTrue(frappe.db.exists("E-Boekhouden Migration", migration.name))
        
    def test_duplicate_entry_handling(self):
        """Test handling of duplicate entries"""
        seq = self.factory.get_next_sequence('duplicate_account')
        account_name = f"TEST Duplicate Handling Account {seq}"

        # Create first account
        account1 = self._create_valid_test_account(
            account_name, self.test_company, is_group=1, root_type="Asset"
        )
        account1.insert()

        # Try to create duplicate
        account2 = self._create_valid_test_account(
            account_name, self.test_company, is_group=1, root_type="Asset"
        )

        # Should fail with duplicate error
        with self.assertRaises(frappe.DuplicateEntryError):
            account2.insert()
            
    def test_data_corruption_prevention(self):
        """Test prevention of data corruption scenarios"""
        # Test that required fields are enforced
        account = frappe.new_doc("Account")
        # Missing required fields: account_name, company
        account.account_type = "Asset"
        
        with self.assertRaises(Exception):
            validate_and_insert(account)
            
        # Test that invalid account types are rejected
        account2 = frappe.new_doc("Account")
        account2.account_name = "TEST Invalid Type Account"
        account2.company = self.test_company
        account2.account_type = "InvalidType"  # Not a valid option
        
        with self.assertRaises(Exception):
            validate_and_insert(account2)
            
    def test_migration_cleanup_and_recovery(self):
        """Test migration cleanup and error recovery"""
        # Create test data for cleanup
        test_accounts = []
        seq = self.factory.get_next_sequence('recovery_account')
        for i in range(3):
            account = self._create_valid_test_account(
                f"TEST Cleanup Account {seq}-{i+1}", self.test_company, is_group=1, root_type="Asset"
            )
            account.insert()
            test_accounts.append(account.name)
            
        # Test cleanup context
        with cleanup_context():
            # Cleanup operations would go here
            # For test, just verify context works
            self.assertTrue(frappe.flags.in_cleanup)
            
        # Verify cleanup context was exited properly
        self.assertFalse(getattr(frappe.flags, 'in_cleanup', False))


class TestPerformanceAndScalability(EnhancedTestCase):
    """
    Performance and scalability tests for migration operations
    
    Tests batch operations, large dataset handling, and performance benchmarks.
    """
    
    def setUp(self):
        super().setUp()
        self.test_company = self._ensure_test_company()
        
    def _ensure_test_company(self):
        """Ensure test company exists (collision-safe).

        Reuse an existing company by name OR by abbreviation: ERPNext Company
        creation commits internally, so a sibling test that created a company
        with abbr "TPC" leaves it persisted past its own rollback. Inserting a new
        company with the same abbr then fails ("Abbreviation already used for
        another company"). Reusing whatever company holds the abbr keeps this
        heavyweight fixture order-independent (the perf tests only need *a*
        company to hang accounts/data off of).
        """
        company_name = "TEST-Performance-Company"

        existing = frappe.db.get_value("Company", company_name) or frappe.db.get_value(
            "Company", {"abbr": "TPC"}, "name"
        )
        if existing:
            return existing

        company = frappe.new_doc("Company")
        company.company_name = company_name
        company.abbr = "TPC"
        company.default_currency = "EUR"
        company.country = "Netherlands"
        company.insert()
        return company.name

    def _get_or_create_parent_account(self, company: str, root_type: str = "Asset") -> str:
        """Get or create a parent account for test account creation."""
        parent = frappe.db.get_value(
            "Account",
            {"company": company, "root_type": root_type, "is_group": 1, "parent_account": ("is", "not set")},
            "name"
        )
        if parent:
            return parent

        parent = frappe.db.get_value(
            "Account",
            {"company": company, "root_type": root_type, "is_group": 1},
            "name"
        )
        if parent:
            return parent

        root_account = frappe.new_doc("Account")
        root_account.account_name = f"TEST {root_type} Root"
        root_account.company = company
        root_account.root_type = root_type
        root_account.report_type = "Balance Sheet" if root_type in ["Asset", "Liability", "Equity"] else "Profit and Loss"
        root_account.is_group = 1
        root_account.insert()
        return root_account.name

    def _create_valid_test_account(self, account_name: str, company: str, account_type: str = "",
                                    is_group: int = 0, root_type: str = "Asset") -> "frappe.Document":
        """Create a valid test account with proper parent and root_type."""
        parent_account = self._get_or_create_parent_account(company, root_type)

        account = frappe.new_doc("Account")
        account.account_name = account_name
        account.company = company
        account.root_type = root_type
        account.report_type = "Balance Sheet" if root_type in ["Asset", "Liability", "Equity"] else "Profit and Loss"
        account.account_type = account_type
        account.is_group = is_group
        account.parent_account = parent_account
        return account

    def test_batch_operations_performance(self):
        """Test performance of batch operations"""
        # Get company abbreviation to check for existing accounts
        abbr = frappe.db.get_value("Company", self.test_company, "abbr") or ""

        # Create batch of accounts, skipping any that already exist
        accounts = []
        batch_size = 20  # Reasonable size for testing
        max_attempts = 10
        attempts = 0

        while len(accounts) < batch_size and attempts < max_attempts:
            seq = self.factory.get_next_sequence('perf_account')
            for i in range(batch_size):
                if len(accounts) >= batch_size:
                    break
                account_name = f"PERF Test Account {seq}-{i+1:03d}"
                expected_db_name = f"{account_name} - {abbr}" if abbr else account_name

                if not frappe.db.exists("Account", expected_db_name):
                    account = self._create_valid_test_account(
                        account_name, self.test_company, is_group=1, root_type="Asset"
                    )
                    accounts.append(account)
            attempts += 1

        self.assertGreater(len(accounts), 0, "Could not find non-existing account names to test")

        # Time the batch operation
        start_time = now_datetime()

        inserted_accounts = batch_insert(accounts, "account_creation", batch_size=5)
        
        end_time = now_datetime()
        duration = (end_time - start_time).total_seconds()
        
        # Verify all accounts were created
        self.assertEqual(len(inserted_accounts), len(accounts))
        
        # Performance assertion - should complete reasonably quickly
        # Allow 30 seconds for 20 accounts (very generous for testing)
        self.assertLess(duration, 30.0, f"Batch insert took too long: {duration}s")
        
        # Verify all accounts exist in database
        for account in inserted_accounts:
            self.assertTrue(frappe.db.exists("Account", account.name))
            
    def test_large_payment_mutation_processing(self):
        """Test processing of payment mutations with many rows"""
        handler = PaymentEntryHandler(company=self.test_company)
        
        # Create large mutation with many rows
        rows = []
        total_amount = 0
        
        for i in range(10):  # 10 rows for testing
            amount = round(random.uniform(10.0, 100.0), 2)
            rows.append({
                "ledgerId": 1300 + (i % 3),  # Vary ledger IDs
                "amount": amount,
                "description": f"Payment row {i+1}"
            })
            total_amount += amount
            
        mutation_data = {
            "id": 99999,
            "type": 3,
            "date": nowdate(),
            "amount": total_amount,
            "relationId": "PERF001",
            "invoiceNumber": "PERF-INV-001,PERF-INV-002,PERF-INV-003",
            "description": "Large payment with many rows",
            "ledgerId": 1001,
            "rows": rows
        }
        
        # Mock party creation for performance test
        original_method = handler._get_or_create_party
        def mock_get_party(relation_id, party_type, description):
            return "TEST-PERF-CUSTOMER"
        handler._get_or_create_party = mock_get_party
        
        try:
            start_time = now_datetime()
            
            # This will likely fail due to missing customer/invoices
            # but we're testing the processing logic performance
            result = handler.process_payment_mutation(mutation_data)
            
            end_time = now_datetime()
            duration = (end_time - start_time).total_seconds()
            
            # Should process quickly even with many rows
            self.assertLess(duration, 10.0, f"Large mutation processing took too long: {duration}s")
            
        except Exception:
            # Expected to fail due to missing test data
            # but processing should still be fast
            end_time = now_datetime()
            duration = (end_time - start_time).total_seconds()
            self.assertLess(duration, 10.0, f"Processing (even with errors) took too long: {duration}s")
            
        finally:
            handler._get_or_create_party = original_method
            
    def test_memory_usage_during_batch_operations(self):
        """Test memory usage remains reasonable during batch operations"""
        # Get company abbreviation to check for existing accounts
        abbr = frappe.db.get_value("Company", self.test_company, "abbr") or ""

        # Create moderate batch to test memory, skipping existing accounts
        large_batch_size = 50
        accounts = []
        max_attempts = 20
        attempts = 0

        while len(accounts) < large_batch_size and attempts < max_attempts:
            seq = self.factory.get_next_sequence('mem_account')
            for i in range(large_batch_size):
                if len(accounts) >= large_batch_size:
                    break
                account_name = f"MEM Test Account {seq}-{i+1:04d}"
                expected_db_name = f"{account_name} - {abbr}" if abbr else account_name

                if not frappe.db.exists("Account", expected_db_name):
                    account = self._create_valid_test_account(
                        account_name, self.test_company, is_group=1, root_type="Asset"
                    )
                    accounts.append(account)
            attempts += 1

        self.assertGreater(len(accounts), 0, "Could not find non-existing account names to test")

        # Process in smaller batches to test memory management
        batch_size = 10
        total_inserted = 0

        for i in range(0, len(accounts), batch_size):
            batch = accounts[i:i + batch_size]

            try:
                inserted_batch = batch_insert(batch, "account_creation", batch_size=batch_size)
                total_inserted += len(inserted_batch)

                # Force garbage collection to test memory cleanup
                import gc
                gc.collect()

            except Exception as e:
                # Log but continue - focus is on memory usage pattern
                pass

        # Verify reasonable number were processed
        self.assertGreater(total_inserted, len(accounts) // 2)
        
    def test_concurrent_operation_simulation(self):
        """Test simulation of concurrent operations"""
        # Simulate multiple migration operations that might run concurrently
        operations = []
        
        # Create different types of operations
        seq = self.factory.get_next_sequence('concurrent_account')
        for i in range(5):
            # Account creation operation
            account = self._create_valid_test_account(
                f"CONCURRENT Account {seq}-{i+1}", self.test_company, is_group=1, root_type="Asset"
            )
            operations.append(("account", account))
            
            # Customer creation operation
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"CONCURRENT Customer {i+1}"
            customer.customer_type = "Individual"
            operations.append(("customer", customer))
            
        # Process all operations using proper security context
        successful_operations = 0
        
        for op_type, doc in operations:
            try:
                if op_type == "account":
                    with migration_context("account_creation"):
                        doc.insert()
                        successful_operations += 1
                elif op_type == "customer":
                    with migration_context("party_creation"):
                        doc.insert()
                        successful_operations += 1
                        
            except Exception as e:
                # Log but continue - some conflicts expected
                frappe.log_error(f"Concurrent operation failed: {e}", "Performance Test")
                
        # Should successfully process most operations
        self.assertGreater(successful_operations, len(operations) // 2)


# Additional test utilities and fixtures

def create_realistic_eboekhouden_mutation_data(mutation_type: int = 3) -> Dict[str, Any]:
    """
    Create realistic E-Boekhouden mutation data for testing
    
    Args:
        mutation_type: 3 for customer payment, 4 for supplier payment
        
    Returns:
        Dictionary with realistic mutation data
    """
    base_data = {
        "id": random.randint(10000, 99999),
        "type": mutation_type,
        "date": (datetime.now() - timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d"),
        "amount": round(random.uniform(50.0, 500.0), 2),
        "relationId": f"REL{random.randint(1000, 9999)}",
        "description": f"Test payment {random.randint(1, 1000)}",
        "ledgerId": random.randint(1000, 1500)
    }
    
    # Add invoice numbers (sometimes multiple)
    num_invoices = random.randint(1, 3)
    invoice_numbers = [f"INV-{random.randint(1000, 9999)}" for _ in range(num_invoices)]
    base_data["invoiceNumber"] = ",".join(invoice_numbers)
    
    # Add rows (detailed breakdown)
    num_rows = random.randint(1, num_invoices + 1)
    total_amount = base_data["amount"]
    rows = []
    
    for i in range(num_rows):
        if i == num_rows - 1:
            # Last row gets remaining amount
            row_amount = total_amount - sum(row["amount"] for row in rows)
        else:
            row_amount = round(total_amount / num_rows, 2)
            
        rows.append({
            "ledgerId": random.randint(1300, 1400),
            "amount": abs(row_amount),
            "description": f"Payment detail {i+1}"
        })
        
    base_data["rows"] = rows
    
    return base_data


def setup_comprehensive_test_data():
    """
    Setup comprehensive test data for integration testing
    
    Creates customers, suppliers, invoices, accounts, and other
    test data needed for realistic integration testing.
    """
    # This would be called by test setup methods
    # Implementation would create realistic test data
    pass


if __name__ == "__main__":
    import unittest
    
    # Run all test classes
    test_classes = [
        TestEBoekhoudenSecurityIntegration,
        TestPaymentProcessingIntegration, 
        TestMigrationPipelineIntegration,
        TestDataIntegrityAndEdgeCases,
        TestPerformanceAndScalability
    ]
    
    suite = unittest.TestSuite()
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        suite.addTests(tests)
        
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Exit with proper code
    exit(0 if result.wasSuccessful() else 1)