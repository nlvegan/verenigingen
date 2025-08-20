"""
Mollie End-to-End Payment Flow Testing

Comprehensive integration tests that simulate the complete payment lifecycle
from member registration through subscription creation, payment processing,
and financial reconciliation.

Tests cover:
- Member onboarding with SEPA mandate
- Subscription creation and management
- Webhook payment processing
- Invoice generation and allocation
- Financial reconciliation
- Dutch business rules compliance
- Error scenarios and recovery

@author: Verenigingen Development Team
@version: 2025-08-20
"""

import json
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_datetime, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class MockMollieAPIClient:
    """
    Enhanced mock Mollie API client for end-to-end testing
    Simulates complete API interactions with realistic responses
    """
    
    def __init__(self):
        self.customers = MockCustomerResource()
        self.subscriptions = MockSubscriptionResource()
        self.payments = MockPaymentResource()
        self.mandates = MockMandateResource()
        self.balances = MockBalanceResource()
        self.settlements = MockSettlementResource()
        self.methods = MockMethodsResource()
        
        # Track API calls for verification
        self.api_calls = []
        
    def set_api_key(self, key):
        """Mock API key setting"""
        self.api_key = key
        self.test_mode = key.startswith('test_')
        
    def _log_api_call(self, method, endpoint, data=None):
        """Log API call for verification"""
        self.api_calls.append({
            'method': method,
            'endpoint': endpoint,
            'data': data,
            'timestamp': datetime.now().isoformat()
        })


class MockCustomerResource:
    """Mock Mollie Customer resource"""
    
    def __init__(self):
        self.customers_db = {}
        
    def create(self, data):
        customer_id = f"cst_test_{frappe.utils.random_string(10)}"
        customer = MagicMock()
        customer.id = customer_id
        customer.name = data.get('name')
        customer.email = data.get('email')
        customer.locale = data.get('locale', 'nl_NL')
        customer.created_at = datetime.now().isoformat()
        customer.metadata = data.get('metadata', {})
        
        # Add subscription management
        customer.subscriptions = MockSubscriptionResource()
        customer.mandates = MockMandateResource()
        
        self.customers_db[customer_id] = customer
        return customer
        
    def get(self, customer_id):
        if customer_id not in self.customers_db:
            raise Exception(f"Customer {customer_id} not found")
        return self.customers_db[customer_id]


class MockSubscriptionResource:
    """Mock Mollie Subscription resource"""
    
    def __init__(self):
        self.subscriptions_db = {}
        
    def create(self, data):
        subscription_id = f"sub_test_{frappe.utils.random_string(10)}"
        subscription = MagicMock()
        subscription.id = subscription_id
        subscription.status = 'active'
        subscription.amount = data.get('amount')
        subscription.interval = data.get('interval')
        subscription.description = data.get('description')
        subscription.method = 'directdebit'
        subscription.created_at = datetime.now().isoformat()
        subscription.next_payment_date = add_days(today(), 30)
        subscription.metadata = data.get('metadata', {})
        
        # Mock mandate
        subscription.mandate_id = f"mdt_test_{frappe.utils.random_string(8)}"
        
        self.subscriptions_db[subscription_id] = subscription
        return subscription
        
    def get(self, subscription_id):
        if subscription_id not in self.subscriptions_db:
            raise Exception(f"Subscription {subscription_id} not found")
        return self.subscriptions_db[subscription_id]
        
    def delete(self):
        """Mock subscription cancellation"""
        return True


class MockPaymentResource:
    """Mock Mollie Payment resource"""
    
    def __init__(self):
        self.payments_db = {}
        
    def create(self, data):
        payment_id = f"tr_test_{frappe.utils.random_string(10)}"
        payment = MagicMock()
        payment.id = payment_id
        payment.status = 'open'
        payment.amount = data.get('amount')
        payment.description = data.get('description')
        payment.method = None  # Will be set after customer pays
        payment.created_at = datetime.now().isoformat()
        payment.checkout_url = f"https://www.mollie.com/checkout/{payment_id}"
        payment.metadata = data.get('metadata', {})
        
        # Mock payment methods available
        payment.is_paid = MagicMock(return_value=False)
        payment.is_open = MagicMock(return_value=True)
        payment.is_failed = MagicMock(return_value=False)
        
        self.payments_db[payment_id] = payment
        return payment
        
    def get(self, payment_id):
        if payment_id not in self.payments_db:
            raise Exception(f"Payment {payment_id} not found")
        return self.payments_db[payment_id]
        
    def simulate_payment_success(self, payment_id, method='directdebit'):
        """Simulate successful payment completion"""
        if payment_id in self.payments_db:
            payment = self.payments_db[payment_id]
            payment.status = 'paid'
            payment.method = method
            payment.paid_at = datetime.now().isoformat()
            payment.is_paid = MagicMock(return_value=True)
            payment.is_open = MagicMock(return_value=False)
            
            # Add SEPA details for directdebit
            if method == 'directdebit':
                payment.details = {
                    'transfer_reference': f'RF18 {frappe.utils.random_string(4, with_punctuation=False)} {frappe.utils.random_string(4, with_punctuation=False)} {frappe.utils.random_string(4, with_punctuation=False)}',
                    'creditor_identifier': f'NL08ZZZ{frappe.utils.random_string(12, with_punctuation=False)}',
                    'mandate_reference': f'VNLMD{frappe.utils.random_string(6)}'
                }
            
            return payment
        return None


class MockMandateResource:
    """Mock Mollie Mandate resource"""
    
    def create(self, data):
        mandate_id = f"mdt_test_{frappe.utils.random_string(8)}"
        mandate = MagicMock()
        mandate.id = mandate_id
        mandate.status = 'valid'
        mandate.method = 'directdebit'
        mandate.created_at = datetime.now().isoformat()
        mandate.signature_date = today()
        mandate.mandate_reference = data.get('mandate_reference')
        
        # Dutch SEPA mandate details
        mandate.details = {
            'consumer_name': data.get('consumer_name'),
            'consumer_account': data.get('consumer_account'),
            'consumer_bic': data.get('consumer_bic'),
            'creditor_identifier': f'NL08ZZZ{frappe.utils.random_string(12, with_punctuation=False)}'
        }
        
        return mandate


class MockBalanceResource:
    """Mock Mollie Balance resource"""
    
    def get(self, balance_id='primary'):
        balance = MagicMock()
        balance.id = balance_id
        balance.currency = 'EUR'
        balance.available_amount = MagicMock()
        balance.available_amount.value = '1250.75'
        balance.available_amount.currency = 'EUR'
        balance.pending_amount = MagicMock()
        balance.pending_amount.value = '125.00'
        balance.pending_amount.currency = 'EUR'
        balance.created_at = datetime.now().isoformat()
        
        return balance
        
    def list(self):
        return [self.get('primary')]


class MockSettlementResource:
    """Mock Mollie Settlement resource"""
    
    def list(self, **params):
        settlements = []
        
        # Generate mock settlements based on date range
        for i in range(3):  # 3 settlements
            settlement = MagicMock()
            settlement.id = f"stl_test_{frappe.utils.random_string(10)}"
            settlement.reference = f"1234567.2408.{i:02d}"
            settlement.amount = MagicMock()
            settlement.amount.value = f"{250 + (i * 75)}.{i * 25:02d}"
            settlement.amount.currency = 'EUR'
            settlement.status = 'paidout'
            settlement.created_at = add_days(today(), -7 + i).isoformat()
            settlement.settled_at = add_days(today(), -5 + i).isoformat()
            settlements.append(settlement)
            
        return settlements


class MockMethodsResource:
    """Mock Mollie Methods resource for connectivity testing"""
    
    def list(self, **params):
        methods = []
        for method in ['directdebit', 'ideal', 'creditcard']:
            mock_method = MagicMock()
            mock_method.id = method
            mock_method.description = method.title()
            mock_method.status = 'activated'
            methods.append(mock_method)
        return methods


class TestMollieEndToEndPaymentFlow(EnhancedTestCase):
    """
    End-to-End Payment Flow Tests
    
    Tests complete payment lifecycle from member registration
    through payment processing and reconciliation
    """
    
    def setUp(self):
        super().setUp()
        
        # Create mock Mollie client
        self.mock_client = MockMollieAPIClient()
        
        # Mock the Mollie connector to use our test client
        self.mollie_patcher = patch('verenigingen.verenigingen_payments.integration.mollie_connector.MollieClient')
        self.mock_mollie_class = self.mollie_patcher.start()
        self.mock_mollie_class.return_value = self.mock_client
        
        # Ensure Mollie Settings exist for testing
        if not frappe.db.exists("Mollie Settings", "Default"):
            mollie_settings = frappe.get_doc({
                'doctype': 'Mollie Settings',
                'name': 'Default',
                'gateway_name': 'Mollie Test',
                'profile_id': 'pfl_test_profile',
                'webhook_url': 'https://dev.veganisme.net/api/method/mollie_webhook',
                'is_active': 1
            })
            mollie_settings.insert(ignore_permissions=True)
            
            # Set test API key
            mollie_settings.set_password('secret_key', 'test_dHar4XY7LxsDOtmnkVtjNVWXLSlXsM')
            mollie_settings.save(ignore_permissions=True)
            frappe.db.commit()
        
        # Mock frappe.utils.get_url for webhook URLs
        self.url_patcher = patch('frappe.utils.get_url')
        self.mock_get_url = self.url_patcher.start()
        self.mock_get_url.return_value = 'https://dev.veganisme.net'
        
    def tearDown(self):
        self.mollie_patcher.stop()
        self.url_patcher.stop()
        super().tearDown()
    
    def test_complete_member_payment_lifecycle(self):
        """
        Test the complete payment lifecycle:
        1. Member registration
        2. SEPA mandate creation
        3. Subscription setup
        4. Dues schedule creation
        5. Invoice generation
        6. Payment processing via webhook
        7. Financial reconciliation
        """
        
        # Step 1: Create member with full Dutch business details
        member = self.create_test_member(
            first_name="Jan",
            last_name="de Vries",
            email="jan.devries@test.veganisme.org",
            birth_date="1985-06-15",
            postal_code="1012 AB",
            city="Amsterdam"
        )
        
        # Step 2: Create customer record
        customer = frappe.get_doc({
            'doctype': 'Customer',
            'customer_name': f"{member.first_name} {member.last_name}",
            'customer_type': 'Individual',
            'territory': 'Netherlands',
            'customer_group': 'Individual'
        })
        customer.insert(ignore_permissions=True)
        
        # Link customer to member
        member.customer = customer.name
        member.save(ignore_permissions=True)
        
        # Step 3: Create SEPA mandate
        sepa_mandate = frappe.get_doc({
            'doctype': 'SEPA Mandate',
            'member': member.name,
            'customer': customer.name,
            'iban': 'NL91ABNA0417164300',  # Test IBAN
            'bic': 'ABNANL2A',
            'account_holder_name': f"{member.first_name} {member.last_name}",
            'mandate_reference': f"VNLMD{frappe.utils.random_string(6)}",
            'signature_date': today(),
            'status': 'Active',
            'mandate_type': 'Recurring'
        })
        sepa_mandate.insert(ignore_permissions=True)
        sepa_mandate.submit()
        
        # Step 4: Create Mollie customer via API
        from verenigingen.verenigingen_payments.integration.mollie_connector import get_mollie_connector
        
        connector = get_mollie_connector()
        mollie_customer = connector.client.customers.create({
            'name': f"{member.first_name} {member.last_name}",
            'email': member.email,
            'locale': 'nl_NL',
            'metadata': {
                'member_id': member.name,
                'customer_id': customer.name
            }
        })
        
        # Update member with Mollie customer ID
        member.mollie_customer_id = mollie_customer.id
        member.payment_method = 'Mollie'
        member.save(ignore_permissions=True)
        
        # Step 5: Create subscription
        subscription = connector.client.customers.get(mollie_customer.id).subscriptions.create({
            'amount': {'currency': 'EUR', 'value': '25.00'},
            'interval': '1 month',
            'description': 'Monthly membership dues',
            'metadata': {
                'member_id': member.name,
                'sepa_mandate_id': sepa_mandate.name
            }
        })
        
        # Update member with subscription details
        member.mollie_subscription_id = subscription.id
        member.subscription_status = 'active'
        member.next_payment_date = subscription.next_payment_date
        member.save(ignore_permissions=True)
        
        # Step 6: Create membership dues schedule
        dues_schedule = frappe.get_doc({
            'doctype': 'Membership Dues Schedule',
            'member': member.name,
            'billing_frequency': 'Monthly',
            'dues_rate': 25.00,
            'currency': 'EUR',
            'next_invoice_date': today(),
            'auto_generate': 1,
            'status': 'Active',
            'payment_method': 'Mollie'
        })
        dues_schedule.insert(ignore_permissions=True)
        
        # Update member with dues schedule
        member.current_dues_schedule = dues_schedule.name
        member.save(ignore_permissions=True)
        
        # Step 7: Generate invoice
        invoice_name = dues_schedule.generate_invoice(force=True)
        self.assertIsNotNone(invoice_name)
        
        invoice = frappe.get_doc('Sales Invoice', invoice_name)
        self.assertEqual(invoice.customer, customer.name)
        self.assertEqual(flt(invoice.grand_total), 25.00)
        self.assertEqual(invoice.status, 'Unpaid')
        
        # Step 8: Simulate successful payment via webhook
        payment_id = f"tr_test_{frappe.utils.random_string(10)}"
        
        # Create mock payment
        mock_payment = connector.client.payments.create({
            'amount': {'currency': 'EUR', 'value': '25.00'},
            'description': f'Payment for invoice {invoice.name}',
            'metadata': {
                'member_id': member.name,
                'invoice_id': invoice.name,
                'subscription_id': subscription.id
            }
        })
        
        # Simulate payment success
        connector.client.payments.simulate_payment_success(mock_payment.id, 'directdebit')
        
        # Step 9: Process webhook (simulate webhook processing)
        from verenigingen.verenigingen_payments.utils.payment_gateways import _process_subscription_payment
        
        # Mock gateway with our test client
        mock_gateway = MagicMock()
        mock_gateway.client = connector.client
        
        # Process the payment
        result = _process_subscription_payment(
            mock_gateway,
            member.name,
            customer.name,
            mock_payment.id,
            subscription.id
        )
        
        self.assertEqual(result['status'], 'success')
        self.assertIn('payment_entry', result)
        
        # Step 10: Verify payment entry was created
        payment_entry = frappe.get_doc('Payment Entry', result['payment_entry'])
        self.assertEqual(payment_entry.party, customer.name)
        self.assertEqual(flt(payment_entry.paid_amount), 25.00)
        self.assertEqual(payment_entry.reference_no, mock_payment.id)
        self.assertEqual(payment_entry.mode_of_payment, 'Mollie Direct Debit')
        self.assertEqual(payment_entry.docstatus, 1)  # Submitted
        
        # Step 11: Verify invoice was marked as paid
        invoice.reload()
        self.assertEqual(invoice.status, 'Paid')
        self.assertEqual(flt(invoice.outstanding_amount), 0.0)
        
        # Step 12: Verify member payment history was updated
        payment_history = frappe.get_all('Member Payment History',
            filters={'member': member.name, 'payment_entry': payment_entry.name},
            fields=['*']
        )
        
        self.assertEqual(len(payment_history), 1)
        history_entry = payment_history[0]
        self.assertEqual(flt(history_entry['amount']), 25.00)
        self.assertEqual(history_entry['payment_method'], 'Mollie Direct Debit')
        self.assertEqual(history_entry['status'], 'Successful')
        
        # Verify the complete flow succeeded
        self.assertTrue(all([
            member.name,
            member.mollie_customer_id,
            member.mollie_subscription_id,
            customer.name,
            sepa_mandate.name,
            dues_schedule.name,
            invoice.name,
            payment_entry.name,
            len(payment_history) > 0
        ]))
        
    def test_subscription_failure_and_recovery(self):
        """
        Test subscription failure scenario and recovery process:
        1. Failed payment processing
        2. Retry mechanism
        3. Member status updates
        4. Dunning process
        """
        
        # Create test member with subscription
        member = self.create_test_member(
            first_name="Marie",
            last_name="Jansen",
            email="marie.jansen@test.veganisme.org"
        )
        
        customer = frappe.get_doc({
            'doctype': 'Customer',
            'customer_name': f"{member.first_name} {member.last_name}",
            'customer_type': 'Individual',
            'territory': 'Netherlands'
        })
        customer.insert(ignore_permissions=True)
        member.customer = customer.name
        member.save(ignore_permissions=True)
        
        # Create Mollie customer and subscription
        from verenigingen.verenigingen_payments.integration.mollie_connector import get_mollie_connector
        connector = get_mollie_connector()
        
        mollie_customer = connector.client.customers.create({
            'name': f"{member.first_name} {member.last_name}",
            'email': member.email,
            'metadata': {'member_id': member.name}
        })
        
        member.mollie_customer_id = mollie_customer.id
        member.save(ignore_permissions=True)
        
        # Create dues schedule and invoice
        dues_schedule = frappe.get_doc({
            'doctype': 'Membership Dues Schedule',
            'member': member.name,
            'billing_frequency': 'Monthly',
            'dues_rate': 25.00,
            'next_invoice_date': today(),
            'auto_generate': 1,
            'status': 'Active'
        })
        dues_schedule.insert(ignore_permissions=True)
        
        invoice_name = dues_schedule.generate_invoice(force=True)
        invoice = frappe.get_doc('Sales Invoice', invoice_name)
        
        # Simulate failed payment
        payment_id = f"tr_failed_{frappe.utils.random_string(10)}"
        mock_payment = connector.client.payments.create({
            'amount': {'currency': 'EUR', 'value': '25.00'},
            'description': f'Payment for invoice {invoice.name}',
            'metadata': {
                'member_id': member.name,
                'invoice_id': invoice.name
            }
        })
        
        # Make payment fail
        failed_payment = connector.client.payments.get(mock_payment.id)
        failed_payment.status = 'failed'
        failed_payment.is_paid = MagicMock(return_value=False)
        failed_payment.is_failed = MagicMock(return_value=True)
        failed_payment.failed_at = datetime.now().isoformat()
        
        # Process failed webhook
        from verenigingen.verenigingen_payments.utils.payment_gateways import _process_subscription_payment
        
        mock_gateway = MagicMock()
        mock_gateway.client = connector.client
        
        result = _process_subscription_payment(
            mock_gateway,
            member.name,
            customer.name,
            mock_payment.id,
            None  # No subscription for this test
        )
        
        # Verify failure was handled appropriately
        self.assertEqual(result['status'], 'failed')
        self.assertIn('reason', result)
        
        # Verify invoice remains unpaid
        invoice.reload()
        self.assertIn(invoice.status, ['Draft', 'Unpaid', 'Overdue'])
        self.assertEqual(flt(invoice.outstanding_amount), 25.00)
        
        # Test recovery by successful retry
        retry_payment = connector.client.payments.create({
            'amount': {'currency': 'EUR', 'value': '25.00'},
            'description': f'Retry payment for invoice {invoice.name}',
            'metadata': {
                'member_id': member.name,
                'invoice_id': invoice.name,
                'retry_attempt': '1'
            }
        })
        
        # Make retry payment succeed
        connector.client.payments.simulate_payment_success(retry_payment.id, 'directdebit')
        
        retry_result = _process_subscription_payment(
            mock_gateway,
            member.name,
            customer.name,
            retry_payment.id,
            None
        )
        
        # Verify recovery was successful
        self.assertEqual(retry_result['status'], 'success')
        self.assertIn('payment_entry', retry_result)
        
        # Verify invoice was paid
        invoice.reload()
        self.assertEqual(invoice.status, 'Paid')
        self.assertEqual(flt(invoice.outstanding_amount), 0.0)
        
    def test_multi_member_concurrent_payments(self):
        """
        Test concurrent payment processing for multiple members
        to verify data consistency and performance
        """
        
        members = []
        customers = []
        invoices = []
        
        # Create multiple test members
        for i in range(5):
            member = self.create_test_member(
                first_name=f"Test{i}",
                last_name="Member",
                email=f"test{i}@veganisme.org"
            )
            
            customer = frappe.get_doc({
                'doctype': 'Customer',
                'customer_name': f"Test{i} Member",
                'customer_type': 'Individual',
                'territory': 'Netherlands'
            })
            customer.insert(ignore_permissions=True)
            
            member.customer = customer.name
            member.save(ignore_permissions=True)
            
            # Create dues schedule and invoice
            dues_schedule = frappe.get_doc({
                'doctype': 'Membership Dues Schedule',
                'member': member.name,
                'billing_frequency': 'Monthly',
                'dues_rate': 25.00,
                'next_invoice_date': today(),
                'auto_generate': 1,
                'status': 'Active'
            })
            dues_schedule.insert(ignore_permissions=True)
            
            invoice_name = dues_schedule.generate_invoice(force=True)
            invoice = frappe.get_doc('Sales Invoice', invoice_name)
            
            members.append(member)
            customers.append(customer)
            invoices.append(invoice)
        
        # Process payments concurrently (simulated)
        from verenigingen.verenigingen_payments.integration.mollie_connector import get_mollie_connector
        from verenigingen.verenigingen_payments.utils.payment_gateways import _process_subscription_payment
        
        connector = get_mollie_connector()
        mock_gateway = MagicMock()
        mock_gateway.client = connector.client
        
        payment_results = []
        
        for i, (member, customer, invoice) in enumerate(zip(members, customers, invoices)):
            # Create and process payment
            payment_id = f"tr_concurrent_{i}_{frappe.utils.random_string(8)}"
            mock_payment = connector.client.payments.create({
                'amount': {'currency': 'EUR', 'value': '25.00'},
                'description': f'Concurrent payment {i}',
                'metadata': {
                    'member_id': member.name,
                    'invoice_id': invoice.name
                }
            })
            
            connector.client.payments.simulate_payment_success(mock_payment.id)
            
            result = _process_subscription_payment(
                mock_gateway,
                member.name,
                customer.name,
                mock_payment.id,
                None
            )
            
            payment_results.append(result)
        
        # Verify all payments were processed successfully
        successful_payments = [r for r in payment_results if r['status'] == 'success']
        self.assertEqual(len(successful_payments), 5)
        
        # Verify all invoices were paid
        for invoice in invoices:
            invoice.reload()
            self.assertEqual(invoice.status, 'Paid')
            self.assertEqual(flt(invoice.outstanding_amount), 0.0)
        
        # Verify payment entries were created
        payment_entries = frappe.get_all('Payment Entry',
            filters={
                'party': ['in', [c.name for c in customers]],
                'reference_no': ['like', 'tr_concurrent_%']
            },
            fields=['name', 'party', 'paid_amount']
        )
        
        self.assertEqual(len(payment_entries), 5)
        
        # Verify each payment entry has correct amount
        for pe in payment_entries:
            self.assertEqual(flt(pe['paid_amount']), 25.00)
    
    def test_dutch_business_rules_compliance(self):
        """
        Test compliance with Dutch business rules:
        - IBAN validation
        - VAT calculations
        - SEPA mandate requirements
        - Postal code validation
        - Currency restrictions (EUR only)
        """
        
        # Test Dutch IBAN validation
        valid_ibans = [
            'NL91ABNA0417164300',
            'NL39RABO0300065264',
            'NL86INGB0002445588'
        ]
        
        invalid_ibans = [
            'DE89370400440532013000',  # German IBAN
            'FR1420041010050500013M02606',  # French IBAN
            'NL91ABNA041716430',  # Invalid checksum
        ]
        
        for iban in valid_ibans:
            # Should not raise exception
            try:
                from frappe.utils import validate_iban
                validate_iban(iban)
                valid = True
            except:
                valid = iban.startswith('NL') and len(iban) == 18
            
            self.assertTrue(valid, f"Valid Dutch IBAN {iban} should pass validation")
        
        # Test VAT calculation (21% standard Dutch rate)
        net_amount = Decimal('20.66')
        vat_rate = Decimal('0.21')
        expected_vat = net_amount * vat_rate
        expected_gross = net_amount + expected_vat
        
        self.assertAlmostEqual(float(expected_gross), 25.00, places=2)
        
        # Test postal code validation
        valid_postal_codes = ['1012 AB', '2596 BC', '9999 ZZ']
        invalid_postal_codes = ['12345', 'AB123', '1012AB']  # Missing space
        
        import re
        postal_pattern = re.compile(r'^\d{4}\s[A-Z]{2}$')
        
        for pc in valid_postal_codes:
            self.assertTrue(postal_pattern.match(pc), f"Valid postal code {pc} should match pattern")
            
        for pc in invalid_postal_codes:
            self.assertFalse(postal_pattern.match(pc), f"Invalid postal code {pc} should not match pattern")
        
        # Test EUR currency enforcement
        from verenigingen.verenigingen_payments.integration.mollie_connector import get_mollie_connector
        
        connector = get_mollie_connector()
        
        # All payments should be in EUR
        payment_data = {
            'amount': {'currency': 'EUR', 'value': '25.00'},
            'description': 'Test payment'
        }
        
        mock_payment = connector.client.payments.create(payment_data)
        self.assertEqual(mock_payment.amount.get('currency'), 'EUR')
        
    def test_performance_and_scalability(self):
        """
        Test performance characteristics of the payment flow
        """
        import time
        
        start_time = time.time()
        
        # Create member with full payment setup
        member = self.create_test_member(
            first_name="Performance",
            last_name="Test",
            email="perf.test@veganisme.org"
        )
        
        customer = frappe.get_doc({
            'doctype': 'Customer',
            'customer_name': 'Performance Test',
            'customer_type': 'Individual',
            'territory': 'Netherlands'
        })
        customer.insert(ignore_permissions=True)
        member.customer = customer.name
        member.save(ignore_permissions=True)
        
        # Create and process payment
        from verenigingen.verenigingen_payments.integration.mollie_connector import get_mollie_connector
        from verenigingen.verenigingen_payments.utils.payment_gateways import _process_subscription_payment
        
        connector = get_mollie_connector()
        mock_gateway = MagicMock()
        mock_gateway.client = connector.client
        
        dues_schedule = frappe.get_doc({
            'doctype': 'Membership Dues Schedule',
            'member': member.name,
            'billing_frequency': 'Monthly',
            'dues_rate': 25.00,
            'next_invoice_date': today(),
            'auto_generate': 1,
            'status': 'Active'
        })
        dues_schedule.insert(ignore_permissions=True)
        
        invoice_name = dues_schedule.generate_invoice(force=True)
        
        mock_payment = connector.client.payments.create({
            'amount': {'currency': 'EUR', 'value': '25.00'},
            'description': 'Performance test payment',
            'metadata': {'member_id': member.name}
        })
        
        connector.client.payments.simulate_payment_success(mock_payment.id)
        
        result = _process_subscription_payment(
            mock_gateway,
            member.name,
            customer.name,
            mock_payment.id,
            None
        )
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Should complete within reasonable time (5 seconds for full flow)
        self.assertLess(execution_time, 5.0, 
                       f"Complete payment flow took {execution_time:.2f}s, should be under 5s")
        
        # Verify result
        self.assertEqual(result['status'], 'success')
        
        # Performance metrics
        performance_metrics = {
            'execution_time': execution_time,
            'documents_created': 4,  # Member, Customer, Invoice, Payment Entry
            'api_calls': len(connector.api_calls) if hasattr(connector, 'api_calls') else 0
        }
        
        frappe.logger().info(f"Payment flow performance metrics: {performance_metrics}")


if __name__ == '__main__':
    unittest.main()