#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Frappe Core Integration Boundary Tests
=====================================

Tests integration points between verenigingen custom logic and Frappe core financial apps.
These are the boundaries where "implicit commit" errors typically occur due to 
transaction management conflicts between custom and core code.

Critical Integration Points:
1. **Sales Invoice Integration** - Custom fields + core invoice logic
2. **Payment Entry Integration** - Mollie webhook processing + core payment logic  
3. **Customer Integration** - Member creation + core customer management
4. **ERPNext Accounts Integration** - Financial reporting + core accounting

These tests validate that transaction boundaries are respected at integration points
and that custom logic doesn't interfere with core Frappe/ERPNext transaction management.
"""

import time
from unittest.mock import patch, MagicMock
from contextlib import contextmanager

import frappe
from frappe.utils import flt, today, add_days, now_datetime
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

from verenigingen.tests.fixtures.transaction_boundary_test_framework import (
    TransactionBoundaryTestCase,
    TransactionBoundaryError
)


class TestSalesInvoiceCoreIntegration(TransactionBoundaryTestCase):
    """
    Test Sales Invoice integration boundaries
    
    Validates that custom verenigingen fields and logic integrate properly
    with core ERPNext Sales Invoice functionality without transaction conflicts.
    """
    
    def test_custom_fields_with_core_invoice_workflow(self):
        """Test that custom dues schedule fields don't interfere with core invoice workflow"""
        
        member = self.data_generator.factory.create_member(
            first_name="TestInvoice", 
            last_name="van Integration",
            birth_date="1980-05-20"
        )
        
        def create_invoice_with_custom_fields_and_submit():
            """Create invoice with custom fields, then use core submit workflow"""
            try:
                with self.assert_atomic_operation("custom_fields_core_workflow"):
                    # Create dues schedule (custom logic)
                    dues_schedule = self.data_generator.factory.create_membership_dues_schedule(
                        member=member.name,
                        dues_rate=35.0,
                        billing_frequency="Monthly"
                    )
                    
                    # Create Sales Invoice with custom fields
                    invoice = frappe.get_doc({
                        'doctype': 'Sales Invoice',
                        'customer': member.customer_id,
                        'posting_date': today(),
                        'due_date': add_days(today(), 30),
                        # Custom field integration
                        'custom_dues_schedule': dues_schedule.name,
                        'custom_member_reference': member.name,
                        'items': [{
                            'item_code': 'Membership Fee',
                            'item_name': 'Monthly Membership Fee',
                            'qty': 1,
                            'rate': 35.0,
                            'amount': 35.0
                        }]
                    })
                    
                    # Save with custom field validation
                    invoice.save()
                    
                    # Use core ERPNext submit workflow (integration boundary test)
                    invoice.submit()
                    
                    # Validate custom fields survived core workflow
                    self.assertEqual(invoice.custom_dues_schedule, dues_schedule.name)
                    self.assertEqual(invoice.custom_member_reference, member.name)
                    self.assertEqual(invoice.docstatus, 1)
                    
                    # Validate core ERPNext fields are correct
                    self.assertEqual(invoice.status, "Unpaid")
                    self.assertEqual(flt(invoice.outstanding_amount), 35.0)
                    
                    return {
                        'success': True,
                        'invoice': invoice.name,
                        'dues_schedule': dues_schedule.name
                    }
                    
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        result = create_invoice_with_custom_fields_and_submit()
        self.assertTrue(result['success'], f"Custom field integration failed: {result.get('error')}")
        
        # Additional validation: test invoice amendment (another core workflow)
        invoice = frappe.get_doc('Sales Invoice', result['invoice'])
        
        # Cancel and amend (core ERPNext workflow)
        invoice.cancel()
        amended_invoice = frappe.copy_doc(invoice)
        amended_invoice.amended_from = invoice.name
        amended_invoice.save()
        
        # Validate custom fields carried over in amendment
        self.assertEqual(amended_invoice.custom_dues_schedule, result['dues_schedule'])
        self.assertEqual(amended_invoice.custom_member_reference, member.name)
    
    def test_concurrent_invoice_operations_with_core_posting(self):
        """Test concurrent custom invoice operations don't interfere with core posting logic"""
        
        family_scenario = self.create_test_invoice_generation_scenario()
        members = family_scenario['family_members'][:2]  # Use 2 members for concurrency test
        
        def create_and_post_invoice_with_integration(member, amount, operation_id):
            """Create invoice using custom logic, post using core logic"""
            try:
                # Custom logic: create dues schedule
                dues_schedule = self.data_generator.factory.create_membership_dues_schedule(
                    member=member.name,
                    dues_rate=amount,
                    billing_frequency="Monthly"
                )
                
                # Create invoice with both custom and core fields
                invoice = frappe.get_doc({
                    'doctype': 'Sales Invoice',
                    'customer': member.customer_id,
                    'posting_date': today(),
                    'due_date': add_days(today(), 30),
                    # Custom fields
                    'custom_dues_schedule': dues_schedule.name,
                    'custom_member_reference': member.name,
                    # Core ERPNext fields
                    'items': [{
                        'item_code': 'Membership Fee',
                        'qty': 1,
                        'rate': amount,
                        'amount': amount
                    }]
                })
                
                # Save (triggers both custom and core validation)
                invoice.save()
                
                # Submit using core posting logic (integration test)
                invoice.submit()
                
                # Validate integration worked
                return {
                    'success': True,
                    'invoice': invoice.name,
                    'member': member.name,
                    'operation_id': operation_id,
                    'outstanding_amount': float(invoice.outstanding_amount)
                }
                
            except Exception as e:
                return {
                    'success': False, 
                    'error': str(e),
                    'member': member.name,
                    'operation_id': operation_id
                }
        
        # Execute concurrent operations
        operations = [
            (create_and_post_invoice_with_integration, (members[0], 25.0, 'OP1'), {}),
            (create_and_post_invoice_with_integration, (members[1], 30.0, 'OP2'), {}),
        ]
        
        results = self.execute_concurrent_operations_with_validation(
            operations, expected_success_count=2
        )
        
        # Validate both invoices were created and posted correctly
        for result in results:
            self.assertTrue(result['success'], f"Operation failed: {result}")
            
            # Validate invoice state in database
            invoice_name = result['result']['invoice']
            invoice = frappe.get_doc('Sales Invoice', invoice_name)
            self.assertEqual(invoice.docstatus, 1, "Invoice should be submitted")
            self.assertGreater(invoice.outstanding_amount, 0, "Invoice should have outstanding amount")


class TestPaymentEntryCoreIntegration(TransactionBoundaryTestCase):
    """
    Test Payment Entry integration boundaries
    
    Validates Mollie webhook processing integrates with core ERPNext payment logic
    without causing transaction conflicts or data inconsistencies.
    """
    
    def test_mollie_webhook_core_payment_entry_integration(self):
        """Test Mollie webhook creates Payment Entry using core ERPNext logic"""
        
        scenario = self.create_test_mollie_webhook_scenario()
        member = scenario['member']
        
        # Create and submit an unpaid invoice
        invoice = frappe.get_doc({
            'doctype': 'Sales Invoice',
            'customer': member.customer_id,
            'posting_date': today(),
            'items': [{
                'item_code': 'Membership Fee',
                'qty': 1,
                'rate': 25.0,
                'amount': 25.0
            }]
        })
        invoice.save()
        invoice.submit()
        
        def process_mollie_webhook_with_core_payment_creation(payment_id, amount):
            """Process webhook using core Payment Entry creation logic"""
            try:
                with self.assert_atomic_operation("webhook_core_payment_integration"):
                    # Step 1: Validate payment with Mollie (simulated)
                    payment_validated = True  # Mock Mollie API validation
                    
                    if not payment_validated:
                        raise ValueError("Payment validation failed")
                    
                    # Step 2: Create Payment Entry using core ERPNext logic
                    # This is the integration boundary - using get_payment_entry()
                    payment_entry = get_payment_entry(invoice.doctype, invoice.name)
                    
                    # Customize with Mollie-specific data
                    payment_entry.paid_amount = amount
                    payment_entry.received_amount = amount  
                    payment_entry.reference_no = payment_id
                    payment_entry.reference_date = today()
                    payment_entry.remarks = f"Mollie payment {payment_id}"
                    
                    # Save and submit using core logic (critical integration test)
                    payment_entry.save()
                    payment_entry.submit()
                    
                    # Validate core ERPNext automatically updated invoice
                    invoice.reload()
                    expected_outstanding = 25.0 - amount
                    self.assertAlmostEqual(
                        flt(invoice.outstanding_amount), expected_outstanding,
                        places=2,
                        msg="Core ERPNext should auto-update invoice outstanding amount"
                    )
                    
                    return {
                        'success': True,
                        'payment_entry': payment_entry.name,
                        'invoice': invoice.name,
                        'outstanding_after': float(invoice.outstanding_amount)
                    }
                    
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        result = process_mollie_webhook_with_core_payment_creation('tr_test_12345', 25.0)
        
        self.assertTrue(result['success'], f"Webhook-core integration failed: {result.get('error')}")
        self.assertEqual(result['outstanding_after'], 0.0, "Invoice should be fully paid")
    
    def test_concurrent_webhook_and_manual_payment_core_integration(self):
        """Test race condition between webhook and manual payment using core logic"""
        
        member = self.data_generator.factory.create_member(
            first_name="TestConcur",
            last_name="van PaymentRace",
            birth_date="1985-07-10"
        )
        
        # Create invoice for 50.0 (will be paid by two 25.0 payments concurrently)
        invoice = frappe.get_doc({
            'doctype': 'Sales Invoice',
            'customer': member.customer_id,
            'posting_date': today(),
            'items': [{
                'item_code': 'Membership Fee',
                'qty': 1,
                'rate': 50.0,
                'amount': 50.0
            }]
        })
        invoice.save()
        invoice.submit()
        
        def create_webhook_payment(reference, amount):
            """Create payment via webhook simulation using core logic"""
            try:
                payment_entry = get_payment_entry(invoice.doctype, invoice.name)
                payment_entry.paid_amount = amount
                payment_entry.received_amount = amount
                payment_entry.reference_no = f"WEBHOOK_{reference}"
                payment_entry.reference_date = today()
                
                # Simulate processing delay
                time.sleep(0.1)
                
                payment_entry.save()
                payment_entry.submit()
                
                return {
                    'success': True,
                    'payment': payment_entry.name,
                    'type': 'webhook',
                    'amount': amount
                }
                
            except Exception as e:
                return {'success': False, 'error': str(e), 'type': 'webhook'}
        
        def create_manual_payment(reference, amount):
            """Create payment via manual entry using core logic"""
            try:
                payment_entry = get_payment_entry(invoice.doctype, invoice.name)
                payment_entry.paid_amount = amount
                payment_entry.received_amount = amount
                payment_entry.reference_no = f"MANUAL_{reference}"
                payment_entry.reference_date = today()
                
                # Simulate processing delay
                time.sleep(0.15)
                
                payment_entry.save()
                payment_entry.submit()
                
                return {
                    'success': True,
                    'payment': payment_entry.name,
                    'type': 'manual',
                    'amount': amount
                }
                
            except Exception as e:
                return {'success': False, 'error': str(e), 'type': 'manual'}
        
        # Execute concurrent payments (race condition test)
        operations = [
            (create_webhook_payment, ('WH001', 25.0), {}),
            (create_manual_payment, ('MAN001', 25.0), {}),
        ]
        
        results = self.execute_concurrent_operations_with_validation(operations)
        
        # Both payments should succeed (ERPNext core should handle this)
        success_count = sum(1 for r in results if r['success'])
        self.assertEqual(success_count, 2, "Both payments should succeed with proper core integration")
        
        # Validate final invoice state
        invoice.reload()
        self.assertEqual(flt(invoice.outstanding_amount), 0.0, "Invoice should be fully paid")
        self.assertEqual(invoice.status, "Paid", "Invoice status should be Paid")


class TestCustomerCoreIntegration(TransactionBoundaryTestCase):
    """
    Test Customer integration boundaries
    
    Validates Member creation integrates with core ERPNext Customer management
    without transaction conflicts.
    """
    
    def test_member_customer_core_integration_workflow(self):
        """Test complete Member->Customer workflow using core Customer logic"""
        
        def create_member_with_core_customer_workflow(member_data, create_transactions=False):
            """Create member using core Customer creation and validation logic"""
            try:
                with self.assert_atomic_operation("member_customer_core_integration"):
                    # Step 1: Create Member (triggers Customer creation via hooks)
                    member = self.data_generator.factory.create_member(**member_data)
                    
                    # Step 2: Validate Customer was created with core ERPNext logic
                    customer = frappe.get_doc('Customer', member.customer_id)
                    
                    # Validate core Customer fields are properly set
                    self.assertEqual(customer.customer_name, member.full_name)
                    self.assertEqual(customer.customer_type, "Individual")
                    
                    # Step 3: Test core Customer functionality works
                    if create_transactions:
                        # Create transaction using core logic to validate integration
                        invoice = frappe.get_doc({
                            'doctype': 'Sales Invoice',
                            'customer': customer.name,
                            'posting_date': today(),
                            'items': [{
                                'item_code': 'Membership Fee',
                                'qty': 1,
                                'rate': 30.0,
                                'amount': 30.0
                            }]
                        })
                        invoice.save()
                        
                        # Validate core Customer-Invoice relationship
                        self.assertEqual(invoice.customer, customer.name)
                        
                        return {
                            'success': True,
                            'member': member.name,
                            'customer': customer.name,
                            'invoice': invoice.name
                        }
                    
                    return {
                        'success': True,
                        'member': member.name,
                        'customer': customer.name
                    }
                    
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        # Test concurrent member creation with core Customer integration
        member_data_list = [
            {
                'first_name': 'TestCore1',
                'last_name': 'van Customer',
                'birth_date': '1990-01-15',
                'email': 'testcore1@test.invalid'
            },
            {
                'first_name': 'TestCore2', 
                'last_name': 'van Customer',
                'birth_date': '1985-03-20',
                'email': 'testcore2@test.invalid'
            }
        ]
        
        operations = [
            (create_member_with_core_customer_workflow, (member_data_list[0], True), {}),
            (create_member_with_core_customer_workflow, (member_data_list[1], True), {}),
        ]
        
        results = self.execute_concurrent_operations_with_validation(
            operations, expected_success_count=2
        )
        
        # Validate both integrations succeeded
        customer_names = set()
        for result in results:
            self.assertTrue(result['success'])
            customer_name = result['result']['customer']
            
            # Ensure unique customers
            self.assertNotIn(customer_name, customer_names)
            customer_names.add(customer_name)
            
            # Validate core ERPNext Customer functionality
            customer = frappe.get_doc('Customer', customer_name)
            self.assertTrue(customer.disabled == 0, "Customer should be enabled")


class TestERPNextAccountsIntegration(TransactionBoundaryTestCase):
    """
    Test ERPNext Accounts module integration boundaries
    
    Validates financial reporting and accounting integration points
    with custom verenigingen logic.
    """
    
    def test_financial_reporting_core_integration(self):
        """Test that custom fields integrate with core ERPNext financial reports"""
        
        # Create complex scenario with multiple financial documents
        family_scenario = self.create_test_invoice_generation_scenario()
        members = family_scenario['family_members']
        
        invoices_created = []
        payments_created = []
        
        # Create invoices and payments for reporting test
        for i, member in enumerate(members):
            amount = 25.0 + (i * 5)  # Different amounts for variety
            
            # Create invoice with custom fields
            invoice = frappe.get_doc({
                'doctype': 'Sales Invoice',
                'customer': member.customer_id,
                'posting_date': today(),
                'custom_member_reference': member.name,  # Custom field
                'items': [{
                    'item_code': 'Membership Fee',
                    'qty': 1,
                    'rate': amount,
                    'amount': amount
                }]
            })
            invoice.save()
            invoice.submit()
            invoices_created.append(invoice)
            
            # Create payment for first invoice only (partial payment scenario)
            if i == 0:
                payment_entry = get_payment_entry(invoice.doctype, invoice.name)
                payment_entry.paid_amount = amount
                payment_entry.received_amount = amount
                payment_entry.reference_no = f"TEST_PAY_{i}"
                payment_entry.save()
                payment_entry.submit()
                payments_created.append(payment_entry)
        
        def generate_accounts_receivable_report():
            """Generate core ERPNext Accounts Receivable report"""
            try:
                # Use core ERPNext reporting logic
                from erpnext.accounts.report.accounts_receivable.accounts_receivable import execute
                
                filters = {
                    'company': frappe.defaults.get_user_default('Company'),
                    'report_date': today(),
                    'ageing_based_on': 'Posting Date',
                    'range1': 30,
                    'range2': 60,
                    'range3': 90,
                    'range4': 120
                }
                
                columns, data = execute(filters)
                
                return {
                    'success': True,
                    'report_type': 'accounts_receivable',
                    'rows': len(data),
                    'columns': len(columns)
                }
                
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        def generate_sales_register_report():
            """Generate core ERPNext Sales Register report"""
            try:
                from erpnext.accounts.report.sales_register.sales_register import execute
                
                filters = {
                    'company': frappe.defaults.get_user_default('Company'),
                    'from_date': today(),
                    'to_date': today()
                }
                
                columns, data = execute(filters)
                
                return {
                    'success': True,
                    'report_type': 'sales_register',
                    'rows': len(data),
                    'columns': len(columns)
                }
                
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        # Generate reports concurrently while financial data exists
        operations = [
            (generate_accounts_receivable_report, (), {}),
            (generate_sales_register_report, (), {}),
        ]
        
        results = self.execute_concurrent_operations_with_validation(
            operations, expected_success_count=2
        )
        
        # Validate reports generated successfully
        for result in results:
            self.assertTrue(result['success'], f"Report generation failed: {result}")
            self.assertGreater(result['result']['rows'], 0, "Report should contain data rows")
        
        # Validate reports reflect the correct data
        ar_result = next(r for r in results if r['result']['report_type'] == 'accounts_receivable')
        sales_result = next(r for r in results if r['result']['report_type'] == 'sales_register')
        
        # Should have data from our test invoices
        self.assertGreaterEqual(ar_result['result']['rows'], 2, "AR report should show unpaid invoices")
        self.assertGreaterEqual(sales_result['result']['rows'], 3, "Sales register should show all invoices")
    
    def test_gl_entry_integration_with_custom_fields(self):
        """Test that custom transactions create proper GL entries via core logic"""
        
        member = self.data_generator.factory.create_member(
            first_name="TestGL",
            last_name="van GLEntry",
            birth_date="1975-09-15"
        )
        
        def create_transaction_and_validate_gl_entries():
            """Create financial transaction and validate GL entries are created"""
            try:
                with self.assert_atomic_operation("gl_entry_custom_integration"):
                    # Create and submit invoice (should create GL entries via core)
                    invoice = frappe.get_doc({
                        'doctype': 'Sales Invoice',
                        'customer': member.customer_id,
                        'posting_date': today(),
                        'custom_member_reference': member.name,
                        'items': [{
                            'item_code': 'Membership Fee',
                            'qty': 1,
                            'rate': 40.0,
                            'amount': 40.0
                        }]
                    })
                    invoice.save()
                    invoice.submit()
                    
                    # Create payment (should create additional GL entries)
                    payment_entry = get_payment_entry(invoice.doctype, invoice.name)
                    payment_entry.paid_amount = 40.0
                    payment_entry.received_amount = 40.0
                    payment_entry.reference_no = "GL_TEST_001"
                    payment_entry.save()
                    payment_entry.submit()
                    
                    # Validate GL entries were created by core logic
                    invoice_gl_entries = frappe.get_all(
                        'GL Entry',
                        filters={'voucher_no': invoice.name},
                        fields=['account', 'debit', 'credit']
                    )
                    
                    payment_gl_entries = frappe.get_all(
                        'GL Entry', 
                        filters={'voucher_no': payment_entry.name},
                        fields=['account', 'debit', 'credit']
                    )
                    
                    # Basic validation that GL entries exist
                    self.assertGreater(len(invoice_gl_entries), 0, "Invoice should create GL entries")
                    self.assertGreater(len(payment_gl_entries), 0, "Payment should create GL entries")
                    
                    # Validate debit/credit balance
                    invoice_total_debit = sum(flt(entry.debit) for entry in invoice_gl_entries)
                    invoice_total_credit = sum(flt(entry.credit) for entry in invoice_gl_entries)
                    
                    self.assertAlmostEqual(
                        invoice_total_debit, invoice_total_credit,
                        places=2,
                        msg="Invoice GL entries should be balanced"
                    )
                    
                    return {
                        'success': True,
                        'invoice': invoice.name,
                        'payment': payment_entry.name,
                        'invoice_gl_count': len(invoice_gl_entries),
                        'payment_gl_count': len(payment_gl_entries)
                    }
                    
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        result = create_transaction_and_validate_gl_entries()
        self.assertTrue(result['success'], f"GL entry integration failed: {result.get('error')}")
        self.assertGreater(result['invoice_gl_count'], 0, "Should create invoice GL entries")
        self.assertGreater(result['payment_gl_count'], 0, "Should create payment GL entries")


if __name__ == '__main__':
    frappe.init(site='dev.veganisme.net')
    frappe.connect()
    
    import unittest
    
    # Create integration boundary test suite
    integration_suite = unittest.TestSuite()
    
    # Add core integration tests
    integration_suite.addTest(TestSalesInvoiceCoreIntegration('test_custom_fields_with_core_invoice_workflow'))
    integration_suite.addTest(TestSalesInvoiceCoreIntegration('test_concurrent_invoice_operations_with_core_posting'))
    
    integration_suite.addTest(TestPaymentEntryCoreIntegration('test_mollie_webhook_core_payment_entry_integration'))
    integration_suite.addTest(TestPaymentEntryCoreIntegration('test_concurrent_webhook_and_manual_payment_core_integration'))
    
    integration_suite.addTest(TestCustomerCoreIntegration('test_member_customer_core_integration_workflow'))
    
    integration_suite.addTest(TestERPNextAccountsIntegration('test_financial_reporting_core_integration'))
    integration_suite.addTest(TestERPNextAccountsIntegration('test_gl_entry_integration_with_custom_fields'))
    
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(integration_suite)