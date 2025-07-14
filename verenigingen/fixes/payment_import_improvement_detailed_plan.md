# Detailed Payment Import Improvement Plan

## Executive Summary

The current payment import system has a critical flaw: it hardcodes all payments to a cash account instead of using actual bank accounts from E-Boekhouden. This plan addresses this issue while also improving code organization and discoverability.

## Part 1: Code Organization & Discoverability

### 1.1 Create Clear Module Structure

```
vereiningen/utils/eboekhouden/
├── payment_processing/
│   ├── __init__.py
│   ├── payment_processor.py          # Main payment processing logic
│   ├── bank_account_mapper.py        # Bank account determination
│   ├── payment_reconciler.py         # Invoice reconciliation
│   └── payment_validator.py          # Validation and error handling
├── docs/
│   ├── PAYMENT_PROCESSING_GUIDE.md   # How payments are processed
│   ├── CODE_PATHS.md                 # Where to find what
│   └── TROUBLESHOOTING.md           # Common issues and solutions
└── tests/
    └── test_payment_processing.py     # Comprehensive tests
```

### 1.2 Entry Point Documentation

Create a clear entry point map in `CODE_PATHS.md`:

```markdown
# E-Boekhouden Payment Processing Code Paths

## Entry Points

### 1. REST API Migration (Primary)
- **Start**: `doctype/e_boekhouden_migration/e_boekhouden_migration.py` → `start_transaction_import()`
- **Route**: → `eboekhouden_rest_full_migration.py` → `migrate_transactions_via_rest()`
- **Payment Processing**: → `_process_single_mutation()` → `_create_payment_entry()`

### 2. Manual Payment Import
- **Start**: `api/eboekhouden_migration.py` → `import_single_mutation()`
- **Route**: → `_process_single_mutation()` → `_create_payment_entry()`

### 3. Batch Processing
- **Start**: `import_manager.py` → `clean_import_all()`
- **Route**: → `_import_mutations()` → `_process_single_mutation()`

## Key Functions

### Payment Creation
- **Basic (Current)**: `_create_payment_entry()` in `eboekhouden_rest_full_migration.py:2175`
- **Enhanced (New)**: `create_enhanced_payment_entry()` in `payment_processing/payment_processor.py`

### Bank Account Mapping
- **Ledger Mapping**: `payment_processing/bank_account_mapper.py`
- **Configuration**: `eboekhouden_migration_config.py` - `PAYMENT_ACCOUNT_CONFIG`

### Reconciliation
- **Auto-reconciliation**: `payment_processing/payment_reconciler.py`
- **Manual reconciliation**: `api/sepa_reconciliation.py`
```

### 1.3 Function Registry Pattern

Create a central registry for payment processing functions:

```python
# payment_processing/__init__.py
"""
Payment Processing Module for E-Boekhouden Integration

This module handles all payment-related imports from E-Boekhouden, including:
- Payment Entry creation (mutation types 3 & 4)
- Bank account determination from ledger mappings
- Payment-invoice reconciliation
- Money transfers (mutation types 5 & 6)
"""

from .payment_processor import (
    create_enhanced_payment_entry,
    process_payment_mutation,
    get_payment_processor
)
from .bank_account_mapper import (
    get_bank_account_from_ledger,
    get_default_payment_account
)
from .payment_reconciler import (
    reconcile_payment_with_invoices,
    find_matching_invoices
)

__all__ = [
    'create_enhanced_payment_entry',
    'process_payment_mutation',
    'get_payment_processor',
    'get_bank_account_from_ledger',
    'get_default_payment_account',
    'reconcile_payment_with_invoices',
    'find_matching_invoices'
]

# Version info for tracking changes
__version__ = '2.0.0'
__author__ = 'E-Boekhouden Integration Team'
```

## Part 2: Enhanced Payment Processing Implementation

### 2.1 Main Payment Processor

```python
# payment_processing/payment_processor.py
import frappe
from frappe import _
from frappe.utils import flt, now_datetime
from .bank_account_mapper import BankAccountMapper
from .payment_reconciler import PaymentReconciler
from .payment_validator import PaymentValidator

class PaymentProcessor:
    """
    Central payment processing class that handles all E-Boekhouden payment imports.

    This replaces the hardcoded _create_payment_entry function with a flexible,
    configurable system that properly maps bank accounts and handles reconciliation.
    """

    def __init__(self, company, cost_center, debug_mode=False):
        self.company = company
        self.cost_center = cost_center
        self.debug_mode = debug_mode
        self.debug_info = []

        # Initialize components
        self.bank_mapper = BankAccountMapper(company)
        self.reconciler = PaymentReconciler(company)
        self.validator = PaymentValidator()

    def process_payment_mutation(self, mutation_detail):
        """
        Main entry point for processing payment mutations (types 3 & 4).

        Args:
            mutation_detail: Complete mutation data from E-Boekhouden REST API

        Returns:
            Payment Entry document or None if processing fails
        """
        try:
            # Validate mutation data
            validation_result = self.validator.validate_payment_mutation(mutation_detail)
            if not validation_result['valid']:
                self._log(f"Validation failed: {validation_result['errors']}")
                return None

            # Create enhanced payment entry
            payment_entry = self._create_payment_entry(mutation_detail)

            # Attempt reconciliation
            if payment_entry and mutation_detail.get('invoiceNumber'):
                self.reconciler.reconcile_payment(payment_entry, mutation_detail)

            return payment_entry

        except Exception as e:
            self._log(f"Error processing payment mutation: {str(e)}", level='error')
            raise

    def _create_payment_entry(self, mutation_detail):
        """Create payment entry with proper bank account mapping."""

        # Extract key fields
        mutation_id = mutation_detail.get('id')
        amount = flt(mutation_detail.get('amount', 0), 2)
        relation_id = mutation_detail.get('relationId')
        invoice_number = mutation_detail.get('invoiceNumber')
        mutation_type = mutation_detail.get('type', 3)
        main_ledger_id = mutation_detail.get('ledgerId')
        posting_date = mutation_detail.get('date')
        description = mutation_detail.get('description', '')

        self._log(f"Processing payment mutation {mutation_id}: type={mutation_type}, amount={amount}, ledger={main_ledger_id}")

        # Determine payment type
        payment_type = "Receive" if mutation_type == 3 else "Pay"

        # Get bank account from ledger mapping (THE KEY IMPROVEMENT!)
        bank_account = self.bank_mapper.get_bank_account(
            ledger_id=main_ledger_id,
            payment_type=payment_type,
            description=description
        )

        self._log(f"Determined bank account: {bank_account} for ledger {main_ledger_id}")

        # Create payment entry
        pe = frappe.new_doc("Payment Entry")
        pe.company = self.company
        pe.posting_date = posting_date
        pe.payment_type = payment_type

        # Set accounts based on payment type
        if payment_type == "Receive":
            pe.paid_to = bank_account
            pe.received_amount = amount
            pe.paid_from = self._get_party_account(relation_id, "Customer", mutation_detail)
        else:
            pe.paid_from = bank_account
            pe.paid_amount = amount
            pe.paid_to = self._get_party_account(relation_id, "Supplier", mutation_detail)

        # Set party details
        if relation_id:
            pe.party_type = "Customer" if payment_type == "Receive" else "Supplier"
            pe.party = self._get_or_create_party(relation_id, pe.party_type, mutation_detail)

        # Set references and metadata
        pe.reference_no = invoice_number or f"EB-{mutation_id}"
        pe.reference_date = posting_date
        pe.eboekhouden_mutation_nr = str(mutation_id)

        # Add detailed remarks for audit trail
        pe.remarks = self._generate_remarks(mutation_detail, bank_account)

        # Enhanced naming
        pe.title = self._generate_payment_title(mutation_detail, pe.party, payment_type)

        # Save and submit
        pe.save()
        self._log(f"Created Payment Entry: {pe.name}")

        pe.submit()
        self._log(f"Submitted Payment Entry: {pe.name}")

        return pe

    def _log(self, message, level='info'):
        """Centralized logging for debugging and audit trail."""
        self.debug_info.append({
            'timestamp': now_datetime(),
            'level': level,
            'message': message
        })

        if self.debug_mode:
            print(f"[{level.upper()}] {message}")

        if level == 'error':
            frappe.log_error(message, "Payment Processing Error")
```

### 2.2 Bank Account Mapper

```python
# payment_processing/bank_account_mapper.py
import frappe
from frappe import _

class BankAccountMapper:
    """
    Maps E-Boekhouden ledger IDs to ERPNext bank accounts.

    This is the core improvement over the hardcoded system - it dynamically
    determines the correct bank account based on ledger mappings.
    """

    def __init__(self, company):
        self.company = company
        self._cache = {}  # Cache mappings for performance

    def get_bank_account(self, ledger_id, payment_type, description=None):
        """
        Determine the correct bank account for a payment.

        Priority order:
        1. Direct ledger mapping from E-Boekhouden Ledger Mapping
        2. Payment account mapping from configuration
        3. Pattern matching based on description
        4. Default account based on payment type
        """

        # Check cache first
        cache_key = f"{ledger_id}:{payment_type}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        bank_account = None

        # Step 1: Check direct ledger mapping
        if ledger_id:
            bank_account = self._get_account_from_ledger_mapping(ledger_id)
            if bank_account:
                frappe.logger().info(f"Found bank account via ledger mapping: {bank_account} for ledger {ledger_id}")

        # Step 2: Check payment account configuration
        if not bank_account and ledger_id:
            bank_account = self._get_account_from_payment_config(ledger_id)
            if bank_account:
                frappe.logger().info(f"Found bank account via payment config: {bank_account} for ledger {ledger_id}")

        # Step 3: Pattern matching on description
        if not bank_account and description:
            bank_account = self._get_account_from_pattern(description, payment_type)
            if bank_account:
                frappe.logger().info(f"Found bank account via pattern matching: {bank_account}")

        # Step 4: Use intelligent defaults
        if not bank_account:
            bank_account = self._get_default_account(payment_type)
            frappe.logger().info(f"Using default bank account: {bank_account} for payment type {payment_type}")

        # Cache the result
        self._cache[cache_key] = bank_account
        return bank_account

    def _get_account_from_ledger_mapping(self, ledger_id):
        """Get account from E-Boekhouden Ledger Mapping table."""
        result = frappe.db.sql("""
            SELECT
                lm.erpnext_account,
                lm.ledger_code,
                a.account_type
            FROM `tabE-Boekhouden Ledger Mapping` lm
            JOIN `tabAccount` a ON a.name = lm.erpnext_account
            WHERE lm.ledger_id = %s
            AND a.account_type IN ('Bank', 'Cash')
            AND a.disabled = 0
            LIMIT 1
        """, ledger_id, as_dict=True)

        if result:
            return result[0]['erpnext_account']
        return None

    def _get_account_from_payment_config(self, ledger_id):
        """Get account from payment configuration."""
        # Get ledger code from mapping
        ledger_code = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping",
            {"ledger_id": ledger_id},
            "ledger_code"
        )

        if not ledger_code:
            return None

        # Check payment account configuration
        from vereiningen.utils.eboekhouden.eboekhouden_migration_config import get_payment_account_info

        account_info = get_payment_account_info(ledger_code, self.company)
        if account_info and account_info.get('erpnext_account'):
            return account_info['erpnext_account']

        return None

    def _get_account_from_pattern(self, description, payment_type):
        """Match bank account based on description patterns."""
        patterns = {
            'triodos': '10440 - Triodos - 19.83.96.716 - Algemeen - NVV',
            'paypal': '10470 - PayPal - info@veganisme.org - NVV',
            'asn': '10620 - ASN - 97.88.80.455 - NVV',
            'kas': '10000 - Kas - NVV',
            'cash': '10000 - Kas - NVV'
        }

        description_lower = description.lower()
        for pattern, account in patterns.items():
            if pattern in description_lower:
                # Verify account exists
                if frappe.db.exists("Account", {"name": account, "company": self.company}):
                    return account

        return None

    def _get_default_account(self, payment_type):
        """Get intelligent default account based on payment type."""
        if payment_type == "Receive":
            # Customer payments typically go to main bank account
            # Try Triodos first as it's the main account
            triodos = frappe.db.get_value(
                "Account",
                {"account_number": "10440", "company": self.company, "disabled": 0},
                "name"
            )
            if triodos:
                return triodos

        # Fallback to any active bank account
        bank_account = frappe.db.get_value(
            "Account",
            {
                "account_type": "Bank",
                "company": self.company,
                "is_group": 0,
                "disabled": 0
            },
            "name"
        )

        if bank_account:
            return bank_account

        # Last resort - cash account
        return frappe.db.get_value(
            "Account",
            {"account_number": "10000", "company": self.company},
            "name"
        ) or "10000 - Kas - NVV"
```

### 2.3 Payment Reconciler

```python
# payment_processing/payment_reconciler.py
import frappe
from frappe import _
from frappe.utils import flt

class PaymentReconciler:
    """
    Handles automatic reconciliation of payments with invoices.

    This dramatically improves the payment import process by automatically
    matching payments to their corresponding invoices.
    """

    def __init__(self, company):
        self.company = company
        self.reconciliation_stats = {
            'attempted': 0,
            'successful': 0,
            'failed': 0,
            'partial': 0
        }

    def reconcile_payment(self, payment_entry, mutation_detail):
        """
        Attempt to reconcile payment with outstanding invoices.

        Matching priority:
        1. E-Boekhouden invoice number
        2. Invoice reference in payment description
        3. Amount and date matching
        4. Party-based matching with amount tolerance
        """
        self.reconciliation_stats['attempted'] += 1

        invoice_number = mutation_detail.get('invoiceNumber')
        if not invoice_number and not payment_entry.party:
            frappe.logger().info(f"Cannot reconcile payment {payment_entry.name}: No invoice number or party")
            self.reconciliation_stats['failed'] += 1
            return False

        try:
            # Find matching invoices
            invoices = self._find_matching_invoices(
                payment_entry,
                invoice_number,
                mutation_detail
            )

            if not invoices:
                frappe.logger().info(f"No matching invoices found for payment {payment_entry.name}")
                self.reconciliation_stats['failed'] += 1
                return False

            # Add references to payment entry
            allocated_amount = 0
            payment_amount = payment_entry.paid_amount or payment_entry.received_amount

            for invoice in invoices:
                if allocated_amount >= payment_amount:
                    break

                allocation = min(
                    invoice['outstanding_amount'],
                    payment_amount - allocated_amount
                )

                payment_entry.append('references', {
                    'reference_doctype': invoice['doctype'],
                    'reference_name': invoice['name'],
                    'total_amount': invoice['grand_total'],
                    'outstanding_amount': invoice['outstanding_amount'],
                    'allocated_amount': allocation
                })

                allocated_amount += allocation
                frappe.logger().info(
                    f"Added reference: {invoice['doctype']} {invoice['name']} - "
                    f"Allocated: {allocation}"
                )

            # Update payment entry
            payment_entry.save()

            # Check reconciliation completeness
            if abs(allocated_amount - payment_amount) < 0.01:
                self.reconciliation_stats['successful'] += 1
                frappe.logger().info(f"Fully reconciled payment {payment_entry.name}")
                return True
            else:
                self.reconciliation_stats['partial'] += 1
                frappe.logger().info(
                    f"Partially reconciled payment {payment_entry.name}: "
                    f"Allocated {allocated_amount} of {payment_amount}"
                )
                return True

        except Exception as e:
            frappe.log_error(
                f"Reconciliation error for payment {payment_entry.name}: {str(e)}",
                "Payment Reconciliation Error"
            )
            self.reconciliation_stats['failed'] += 1
            return False

    def _find_matching_invoices(self, payment_entry, invoice_number, mutation_detail):
        """Find invoices matching the payment criteria."""

        invoice_doctype = "Sales Invoice" if payment_entry.payment_type == "Receive" else "Purchase Invoice"
        party_field = "customer" if payment_entry.payment_type == "Receive" else "supplier"

        invoices = []

        # Method 1: Direct E-Boekhouden invoice number match
        if invoice_number:
            invoices = frappe.get_all(
                invoice_doctype,
                filters={
                    party_field: payment_entry.party,
                    'eboekhouden_invoice_number': invoice_number,
                    'docstatus': 1,
                    'outstanding_amount': ['>', 0]
                },
                fields=['name', 'grand_total', 'outstanding_amount'],
                order_by='posting_date'
            )

        # Method 2: Invoice name pattern match
        if not invoices and invoice_number:
            invoices = frappe.get_all(
                invoice_doctype,
                filters={
                    party_field: payment_entry.party,
                    'name': ['like', f'%{invoice_number}%'],
                    'docstatus': 1,
                    'outstanding_amount': ['>', 0]
                },
                fields=['name', 'grand_total', 'outstanding_amount'],
                order_by='posting_date'
            )

        # Method 3: Amount and date matching
        if not invoices and payment_entry.party:
            payment_amount = payment_entry.paid_amount or payment_entry.received_amount
            tolerance = 0.02  # 2% tolerance

            invoices = frappe.get_all(
                invoice_doctype,
                filters={
                    party_field: payment_entry.party,
                    'grand_total': ['between', [
                        payment_amount * (1 - tolerance),
                        payment_amount * (1 + tolerance)
                    ]],
                    'docstatus': 1,
                    'outstanding_amount': ['>', 0]
                },
                fields=['name', 'grand_total', 'outstanding_amount'],
                order_by='posting_date'
            )

        # Method 4: Get all outstanding for party (last resort)
        if not invoices and payment_entry.party:
            invoices = frappe.get_all(
                invoice_doctype,
                filters={
                    party_field: payment_entry.party,
                    'docstatus': 1,
                    'outstanding_amount': ['>', 0]
                },
                fields=['name', 'grand_total', 'outstanding_amount'],
                order_by='posting_date',
                limit=10  # Limit to prevent over-allocation
            )

        # Add doctype to results
        for invoice in invoices:
            invoice['doctype'] = invoice_doctype

        return invoices

    def get_reconciliation_report(self):
        """Get reconciliation statistics."""
        total = self.reconciliation_stats['attempted']
        if total == 0:
            return "No reconciliation attempts made"

        success_rate = (self.reconciliation_stats['successful'] / total) * 100
        partial_rate = (self.reconciliation_stats['partial'] / total) * 100

        return f"""
        Reconciliation Statistics:
        - Total Attempts: {total}
        - Fully Reconciled: {self.reconciliation_stats['successful']} ({success_rate:.1f}%)
        - Partially Reconciled: {self.reconciliation_stats['partial']} ({partial_rate:.1f}%)
        - Failed: {self.reconciliation_stats['failed']}
        - Overall Success Rate: {(success_rate + partial_rate):.1f}%
        """
```

### 2.4 Integration Points

Update the main migration file to use the enhanced system:

```python
# In eboekhouden_rest_full_migration.py

def _create_payment_entry(mutation, company, cost_center, debug_info):
    """
    DEPRECATED: This function uses hardcoded bank accounts.
    Use payment_processing.create_enhanced_payment_entry instead.

    Kept for backward compatibility only.
    """
    # Add deprecation warning
    frappe.logger().warning(
        "Using deprecated _create_payment_entry. "
        "Switch to payment_processing.create_enhanced_payment_entry"
    )

    # Check if enhanced processing is enabled
    if frappe.db.get_single_value("E-Boekhouden Settings", "use_enhanced_payment_processing"):
        from vereiningen.utils.eboekhouden.payment_processing import create_enhanced_payment_entry
        return create_enhanced_payment_entry(mutation, company, cost_center, debug_info)

    # ... existing hardcoded logic ...
```

## Part 3: Migration Tools

### 3.1 Payment Correction Script

```python
# utils/eboekhouden/fix_payment_bank_accounts.py
"""
Script to correct bank accounts for existing payments.

This script:
1. Identifies payments with incorrect bank accounts
2. Determines the correct bank account from ledger mappings
3. Updates the payments (creates reversal and new entry)
4. Generates a correction report
"""

import frappe
from frappe.utils import nowdate
from vereiningen.utils.eboekhouden.payment_processing import BankAccountMapper

@frappe.whitelist()
def fix_payment_bank_accounts(dry_run=True, limit=None):
    """
    Fix bank accounts for existing payment entries.

    Args:
        dry_run: If True, only report what would be changed
        limit: Maximum number of payments to process
    """
    company = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")
    bank_mapper = BankAccountMapper(company)

    # Find payments that might have wrong bank accounts
    payments = frappe.db.sql("""
        SELECT
            pe.name,
            pe.payment_type,
            pe.paid_to,
            pe.paid_from,
            pe.eboekhouden_mutation_nr,
            pe.posting_date,
            pe.party_type,
            pe.party
        FROM `tabPayment Entry` pe
        WHERE pe.eboekhouden_mutation_nr IS NOT NULL
        AND pe.docstatus = 1
        AND (
            (pe.payment_type = 'Receive' AND pe.paid_to = '10000 - Kas - NVV')
            OR (pe.payment_type = 'Pay' AND pe.paid_from = '10000 - Kas - NVV')
        )
        ORDER BY pe.posting_date DESC
        LIMIT %s
    """, limit or 1000, as_dict=True)

    corrections = []

    for payment in payments:
        # Get mutation details from cache or API
        mutation_detail = get_mutation_detail(payment.eboekhouden_mutation_nr)

        if not mutation_detail:
            continue

        # Determine correct bank account
        correct_account = bank_mapper.get_bank_account(
            ledger_id=mutation_detail.get('ledgerId'),
            payment_type=payment.payment_type,
            description=mutation_detail.get('description')
        )

        current_account = payment.paid_to if payment.payment_type == 'Receive' else payment.paid_from

        if correct_account != current_account:
            corrections.append({
                'payment_entry': payment.name,
                'current_account': current_account,
                'correct_account': correct_account,
                'mutation_id': payment.eboekhouden_mutation_nr,
                'posting_date': payment.posting_date
            })

            if not dry_run:
                # Create correction entry
                create_payment_correction(payment, correct_account)

    # Generate report
    report = generate_correction_report(corrections, dry_run)

    return {
        'success': True,
        'corrections_found': len(corrections),
        'dry_run': dry_run,
        'report': report
    }
```

## Part 4: Testing Strategy

### 4.1 Comprehensive Test Suite

```python
# tests/test_payment_processing.py
import unittest
import frappe
from frappe.tests.utils import FrappeTestCase
from vereiningen.utils.eboekhouden.payment_processing import PaymentProcessor

class TestPaymentProcessing(FrappeTestCase):
    """
    Comprehensive test suite for enhanced payment processing.

    Tests cover:
    1. Bank account mapping accuracy
    2. Payment creation with various scenarios
    3. Reconciliation logic
    4. Error handling and edge cases
    """

    def setUp(self):
        self.company = frappe.get_doc("Company", frappe.defaults.get_user_default("Company"))
        self.processor = PaymentProcessor(self.company.name, "Main - TC")

    def test_bank_account_mapping_triodos(self):
        """Test that Triodos payments map correctly."""
        mutation = {
            'id': 12345,
            'type': 3,  # Customer payment
            'amount': 100.00,
            'ledgerId': 13201869,  # Triodos ledger ID
            'relationId': 'CUST001',
            'date': '2025-01-01'
        }

        payment = self.processor.process_payment_mutation(mutation)
        self.assertEqual(payment.paid_to, '10440 - Triodos - 19.83.96.716 - Algemeen - NVV')

    def test_bank_account_fallback(self):
        """Test fallback when ledger mapping not found."""
        mutation = {
            'id': 12346,
            'type': 3,
            'amount': 50.00,
            'ledgerId': 99999,  # Unknown ledger
            'relationId': 'CUST002',
            'date': '2025-01-01'
        }

        payment = self.processor.process_payment_mutation(mutation)
        # Should fallback to Triodos as default for customer payments
        self.assertIn('Triodos', payment.paid_to)

    def test_payment_reconciliation(self):
        """Test automatic invoice reconciliation."""
        # Create test invoice
        invoice = create_test_sales_invoice(
            customer='CUST001',
            amount=100.00,
            eboekhouden_invoice_number='INV-2025-001'
        )

        mutation = {
            'id': 12347,
            'type': 3,
            'amount': 100.00,
            'ledgerId': 13201869,
            'relationId': 'CUST001',
            'invoiceNumber': 'INV-2025-001',
            'date': '2025-01-01'
        }

        payment = self.processor.process_payment_mutation(mutation)

        # Check reconciliation
        self.assertEqual(len(payment.references), 1)
        self.assertEqual(payment.references[0].reference_name, invoice.name)
        self.assertEqual(payment.references[0].allocated_amount, 100.00)

    def test_payment_types(self):
        """Test both customer and supplier payments."""
        # Customer payment (type 3)
        customer_mutation = {
            'id': 12348,
            'type': 3,
            'amount': 200.00,
            'ledgerId': 13201869,
            'relationId': 'CUST001',
            'date': '2025-01-01'
        }

        customer_payment = self.processor.process_payment_mutation(customer_mutation)
        self.assertEqual(customer_payment.payment_type, 'Receive')
        self.assertEqual(customer_payment.party_type, 'Customer')

        # Supplier payment (type 4)
        supplier_mutation = {
            'id': 12349,
            'type': 4,
            'amount': 150.00,
            'ledgerId': 13201869,
            'relationId': 'SUPP001',
            'date': '2025-01-01'
        }

        supplier_payment = self.processor.process_payment_mutation(supplier_mutation)
        self.assertEqual(supplier_payment.payment_type, 'Pay')
        self.assertEqual(supplier_payment.party_type, 'Supplier')
```

## Part 5: Configuration & Settings

### 5.1 Add Settings to E-Boekhouden Settings DocType

```javascript
// In e_boekhouden_settings.js
frappe.ui.form.on('E-Boekhouden Settings', {
    refresh: function(frm) {
        // Add section for payment processing
        frm.add_custom_button(__('Test Payment Processing'), function() {
            frappe.call({
                method: 'vereiningen.utils.eboekhouden.payment_processing.test_configuration',
                args: {
                    company: frm.doc.default_company
                },
                callback: function(r) {
                    if (r.message) {
                        frappe.msgprint({
                            title: __('Payment Processing Configuration Test'),
                            message: r.message,
                            indicator: 'green'
                        });
                    }
                }
            });
        });

        // Add help text
        frm.set_df_property('use_enhanced_payment_processing', 'description',
            `When enabled, payments will use intelligent bank account mapping instead of defaulting to Cash account.
            <br><br>Features:
            <ul>
                <li>Automatic bank account detection from E-Boekhouden ledgers</li>
                <li>Support for multiple bank accounts (Triodos, PayPal, ASN)</li>
                <li>Automatic payment-invoice reconciliation</li>
                <li>Comprehensive audit trail and debugging</li>
            </ul>`
        );
    }
});
```

### 5.2 Add Fields to E-Boekhouden Settings

```json
{
    "fields": [
        {
            "fieldname": "payment_processing_section",
            "fieldtype": "Section Break",
            "label": "Payment Processing Configuration"
        },
        {
            "fieldname": "use_enhanced_payment_processing",
            "fieldtype": "Check",
            "label": "Use Enhanced Payment Processing",
            "default": 1,
            "description": "Enable intelligent bank account mapping and auto-reconciliation"
        },
        {
            "fieldname": "default_customer_payment_account",
            "fieldtype": "Link",
            "label": "Default Customer Payment Account",
            "options": "Account",
            "description": "Default bank account for customer payments when mapping not found"
        },
        {
            "fieldname": "default_supplier_payment_account",
            "fieldtype": "Link",
            "label": "Default Supplier Payment Account",
            "options": "Account",
            "description": "Default account for supplier payments when mapping not found"
        },
        {
            "fieldname": "payment_reconciliation_tolerance",
            "fieldtype": "Percent",
            "label": "Payment Reconciliation Tolerance",
            "default": 2,
            "description": "Percentage tolerance for amount matching during reconciliation"
        },
        {
            "fieldname": "enable_payment_debug_logging",
            "fieldtype": "Check",
            "label": "Enable Payment Debug Logging",
            "default": 0,
            "description": "Enable detailed logging for payment processing (impacts performance)"
        }
    ]
}
```

## Part 6: Monitoring & Reporting

### 6.1 Payment Processing Dashboard

```python
# vereiningen/utils/eboekhouden/payment_dashboard.py
@frappe.whitelist()
def get_payment_processing_stats(from_date=None, to_date=None):
    """Get statistics for payment processing dashboard."""

    stats = {
        'total_payments': 0,
        'correctly_mapped': 0,
        'using_default': 0,
        'reconciled': 0,
        'by_bank_account': {},
        'reconciliation_rate': 0,
        'common_issues': []
    }

    # Query payment statistics
    payments = frappe.db.sql("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN paid_to != '10000 - Kas - NVV' THEN 1 ELSE 0 END) as non_cash,
            SUM(CASE WHEN LENGTH(references) > 2 THEN 1 ELSE 0 END) as with_references,
            paid_to as bank_account,
            COUNT(*) as account_count
        FROM `tabPayment Entry`
        WHERE eboekhouden_mutation_nr IS NOT NULL
        AND payment_type = 'Receive'
        AND posting_date BETWEEN %s AND %s
        GROUP BY paid_to
    """, (from_date or '2000-01-01', to_date or nowdate()), as_dict=True)

    # Process statistics
    for payment in payments:
        stats['total_payments'] += payment.account_count
        if payment.bank_account != '10000 - Kas - NVV':
            stats['correctly_mapped'] += payment.account_count
        stats['by_bank_account'][payment.bank_account] = payment.account_count

    # Calculate rates
    if stats['total_payments'] > 0:
        stats['mapping_rate'] = (stats['correctly_mapped'] / stats['total_payments']) * 100
        stats['reconciliation_rate'] = (stats['reconciled'] / stats['total_payments']) * 100

    # Identify common issues
    if stats['mapping_rate'] < 90:
        stats['common_issues'].append({
            'issue': 'Low bank account mapping rate',
            'description': f"Only {stats['mapping_rate']:.1f}% of payments have correct bank accounts",
            'action': 'Review ledger mappings and run correction script'
        })

    return stats
```

## Part 7: Implementation Rollout Plan

### Phase 1: Preparation (Week 1)
1. Create new module structure
2. Implement core classes (PaymentProcessor, BankAccountMapper, PaymentReconciler)
3. Write comprehensive tests
4. Create documentation

### Phase 2: Testing (Week 2)
1. Test with sample data
2. Run parallel processing (old vs new) to compare results
3. Validate bank account mappings
4. Test reconciliation accuracy

### Phase 3: Migration (Week 3)
1. Enable enhanced processing for new imports
2. Run correction script for existing payments
3. Monitor results and reconciliation rates
4. Address any issues

### Phase 4: Full Deployment (Week 4)
1. Make enhanced processing the default
2. Deprecate old hardcoded function
3. Update all documentation
4. Train users on new features

## Expected Outcomes

1. **Bank Account Accuracy**: >95% of payments will have correct bank accounts
2. **Reconciliation Rate**: >90% automatic reconciliation (up from current manual process)
3. **Code Maintainability**: Clear module structure makes finding and updating code easy
4. **Debugging**: Comprehensive logging makes troubleshooting straightforward
5. **Performance**: Caching and optimized queries ensure fast processing

This implementation plan addresses both the technical debt of hardcoded bank accounts and the organizational issue of hard-to-find code paths, resulting in a robust, maintainable payment processing system.
