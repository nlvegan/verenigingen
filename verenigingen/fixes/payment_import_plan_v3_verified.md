# Payment Import Implementation Plan v3 - API Verified

## Executive Summary

Based on actual API verification of mutations 7833, 5473, and 6217, we've confirmed that E-Boekhouden supports multiple invoice payments through comma-separated invoice numbers. This plan has been updated to reflect the actual API capabilities discovered.

## Verified API Structure

### Key Discoveries from API Analysis

1. **Multiple Invoice Support Confirmed** ✅
   - Mutation 5473: `"invoiceNumber": "7771-2024-15525,7771-2024-15644"` (2 invoices)
   - Mutation 3559: `"invoiceNumber": "760-1,760"` (2 invoices)
   - Single invoice payments use simple string: `"invoiceNumber": "INV-001"`

2. **Payment Structure Pattern**
   ```javascript
   {
     "id": 5473,
     "type": 4,  // 3=Customer Payment, 4=Supplier Payment
     "date": "2024-12-10T00:00:00",
     "ledgerId": 13201869,  // Bank account (e.g., Triodos)
     "amount": 121.79,
     "relationId": "6104885",  // Party reference
     "invoiceNumber": "7771-2024-15525,7771-2024-15644",  // Comma-separated
     "description": "Payment description",
     "rows": [
       {
         "ledgerId": 13201853,  // Payable/Receivable account
         "amount": -60.50
       },
       {
         "ledgerId": 13201853,  // Same account, different allocation
         "amount": -61.29
       }
     ]
   }
   ```

3. **Row-to-Invoice Mapping**
   - When invoice count matches row count, rows typically map 1:1 to invoices
   - Row amounts represent allocations to specific invoices
   - All rows may use the same ledger (receivable/payable account)

## Implementation Architecture

### 1. Core Payment Handler

```python
# payment_processing/payment_entry_handler.py
"""
Enhanced payment entry handler that correctly processes E-Boekhouden payments
including multi-invoice allocations.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate
from typing import Dict, List, Optional, Tuple
import re

class PaymentEntryHandler:
    """
    Handles creation of Payment Entries from E-Boekhouden mutations.

    Key capabilities:
    - Parses comma-separated invoice numbers
    - Maps rows to specific invoices
    - Handles both single and multi-invoice payments
    - Intelligent bank account determination
    """

    def __init__(self, company: str, cost_center: str):
        self.company = company
        self.cost_center = cost_center
        self.debug_log = []

    def process_payment_mutation(self, mutation: Dict) -> Optional[str]:
        """
        Process a payment mutation (types 3 & 4) and create Payment Entry.

        Returns:
            Payment Entry name if successful, None otherwise
        """
        try:
            # Parse invoice numbers
            invoice_numbers = self._parse_invoice_numbers(mutation.get('invoiceNumber'))
            self._log(f"Processing mutation {mutation['id']} with {len(invoice_numbers)} invoices")

            # Determine payment type and party
            payment_type = "Receive" if mutation['type'] == 3 else "Pay"
            party_type = "Customer" if payment_type == "Receive" else "Supplier"

            # Get or create party
            party = self._get_or_create_party(
                mutation.get('relationId'),
                party_type,
                mutation.get('description', '')
            )

            if not party:
                self._log(f"ERROR: Could not determine party for mutation {mutation['id']}")
                return None

            # Determine bank account
            bank_account = self._determine_bank_account(
                mutation.get('ledgerId'),
                payment_type
            )

            # Create payment entry
            pe = self._create_payment_entry(
                mutation=mutation,
                payment_type=payment_type,
                party_type=party_type,
                party=party,
                bank_account=bank_account
            )

            # Handle invoice allocations
            if invoice_numbers and mutation.get('rows'):
                self._allocate_to_invoices(
                    pe,
                    invoice_numbers,
                    mutation['rows'],
                    party_type
                )
            elif invoice_numbers:
                # Single invoice or no rows - simple allocation
                self._simple_invoice_allocation(
                    pe,
                    invoice_numbers,
                    party_type
                )

            # Save and submit
            pe.insert(ignore_permissions=True)
            pe.submit()

            self._log(f"Successfully created Payment Entry {pe.name}")
            return pe.name

        except Exception as e:
            self._log(f"ERROR processing mutation {mutation.get('id')}: {str(e)}")
            frappe.log_error(
                f"Payment mutation processing failed: {str(e)}",
                "E-Boekhouden Payment Import"
            )
            return None

    def _parse_invoice_numbers(self, invoice_str: str) -> List[str]:
        """Parse comma-separated invoice numbers."""
        if not invoice_str:
            return []

        # Split by comma and clean up
        invoices = [inv.strip() for inv in invoice_str.split(',')]
        return [inv for inv in invoices if inv]

    def _determine_bank_account(self, ledger_id: int, payment_type: str) -> str:
        """
        Determine bank account from ledger mapping.

        Priority:
        1. Direct ledger mapping
        2. Payment configuration
        3. Intelligent defaults
        """
        if ledger_id:
            # Try direct mapping
            mapping = frappe.db.get_value(
                "E-Boekhouden Ledger Mapping",
                {"ledger_id": ledger_id},
                ["erpnext_account", "ledger_code"],
                as_dict=True
            )

            if mapping and mapping.get('erpnext_account'):
                # Verify it's a bank account
                account_type = frappe.db.get_value(
                    "Account",
                    mapping['erpnext_account'],
                    "account_type"
                )

                if account_type in ["Bank", "Cash"]:
                    self._log(f"Mapped ledger {ledger_id} to {mapping['erpnext_account']}")
                    return mapping['erpnext_account']

        # Fallback to defaults
        return self._get_default_bank_account(payment_type)

    def _allocate_to_invoices(
        self,
        payment_entry: frappe.Document,
        invoice_numbers: List[str],
        rows: List[Dict],
        party_type: str
    ):
        """
        Allocate payment to multiple invoices based on row data.

        Strategy:
        1. If row count matches invoice count - 1:1 mapping
        2. Otherwise, use FIFO allocation
        """
        invoice_doctype = "Sales Invoice" if party_type == "Customer" else "Purchase Invoice"

        # Get invoice details
        invoices = self._find_invoices(invoice_numbers, invoice_doctype, payment_entry.party)

        if not invoices:
            self._log("WARNING: No matching invoices found for allocation")
            return

        # Prepare row amounts (absolute values)
        row_amounts = [abs(flt(row.get('amount', 0))) for row in rows]

        # Allocate based on strategy
        if len(invoices) == len(rows):
            # 1:1 mapping
            self._allocate_one_to_one(payment_entry, invoices, row_amounts)
        else:
            # FIFO allocation
            self._allocate_fifo(payment_entry, invoices, row_amounts)

    def _allocate_one_to_one(
        self,
        payment_entry: frappe.Document,
        invoices: List[Dict],
        row_amounts: List[float]
    ):
        """Allocate with 1:1 mapping between rows and invoices."""
        for invoice, amount in zip(invoices, row_amounts):
            allocation = min(amount, invoice['outstanding_amount'])

            payment_entry.append('references', {
                'reference_doctype': invoice['doctype'],
                'reference_name': invoice['name'],
                'total_amount': invoice['grand_total'],
                'outstanding_amount': invoice['outstanding_amount'],
                'allocated_amount': allocation
            })

            self._log(f"Allocated {allocation} to {invoice['name']} (1:1 mapping)")

    def _allocate_fifo(
        self,
        payment_entry: frappe.Document,
        invoices: List[Dict],
        row_amounts: List[float]
    ):
        """Allocate using FIFO strategy."""
        total_to_allocate = sum(row_amounts)

        for invoice in invoices:
            if total_to_allocate <= 0:
                break

            allocation = min(total_to_allocate, invoice['outstanding_amount'])

            payment_entry.append('references', {
                'reference_doctype': invoice['doctype'],
                'reference_name': invoice['name'],
                'total_amount': invoice['grand_total'],
                'outstanding_amount': invoice['outstanding_amount'],
                'allocated_amount': allocation
            })

            total_to_allocate -= allocation
            self._log(f"Allocated {allocation} to {invoice['name']} (FIFO)")

    def _find_invoices(
        self,
        invoice_numbers: List[str],
        doctype: str,
        party: str
    ) -> List[Dict]:
        """Find invoices matching the given numbers."""
        invoices = []
        party_field = "customer" if doctype == "Sales Invoice" else "supplier"

        for invoice_num in invoice_numbers:
            # Try multiple matching strategies
            matches = self._find_invoice_by_number(
                invoice_num,
                doctype,
                party_field,
                party
            )
            invoices.extend(matches)

        # Sort by date for FIFO
        invoices.sort(key=lambda x: x.get('posting_date', ''))

        return invoices

    def _find_invoice_by_number(
        self,
        invoice_num: str,
        doctype: str,
        party_field: str,
        party: str
    ) -> List[Dict]:
        """Find invoice using multiple strategies."""
        # Strategy 1: E-Boekhouden invoice number field
        invoices = frappe.get_all(
            doctype,
            filters={
                party_field: party,
                'eboekhouden_invoice_number': invoice_num,
                'docstatus': 1,
                'outstanding_amount': ['>', 0]
            },
            fields=['name', 'grand_total', 'outstanding_amount', 'posting_date']
        )

        if invoices:
            for inv in invoices:
                inv['doctype'] = doctype
            return invoices

        # Strategy 2: Exact name match
        invoices = frappe.get_all(
            doctype,
            filters={
                party_field: party,
                'name': invoice_num,
                'docstatus': 1,
                'outstanding_amount': ['>', 0]
            },
            fields=['name', 'grand_total', 'outstanding_amount', 'posting_date']
        )

        if invoices:
            for inv in invoices:
                inv['doctype'] = doctype
            return invoices

        # Strategy 3: Partial match
        invoices = frappe.get_all(
            doctype,
            filters={
                party_field: party,
                'name': ['like', f'%{invoice_num}%'],
                'docstatus': 1,
                'outstanding_amount': ['>', 0]
            },
            fields=['name', 'grand_total', 'outstanding_amount', 'posting_date'],
            limit=1
        )

        if invoices:
            for inv in invoices:
                inv['doctype'] = doctype
            return invoices

        return []

    def _log(self, message: str):
        """Add to debug log."""
        self.debug_log.append(f"{nowdate()} {message}")
        frappe.logger().info(f"PaymentHandler: {message}")
```

### 2. Integration Points

```python
# In eboekhouden_rest_full_migration.py

def _create_payment_entry(mutation_detail, company, cost_center, debug_info):
    """
    ENHANCED: Create payment entry with multi-invoice support.
    """
    # Use new handler
    from vereiningen.utils.eboekhouden.payment_processing import PaymentEntryHandler

    handler = PaymentEntryHandler(company, cost_center)
    payment_name = handler.process_payment_mutation(mutation_detail)

    # Add handler logs to debug info
    debug_info.extend(handler.debug_log)

    return payment_name
```

### 3. Testing Strategy

```python
# tests/test_payment_multi_invoice.py

class TestMultiInvoicePayments(FrappeTestCase):
    """Test multi-invoice payment handling."""

    def test_comma_separated_invoices(self):
        """Test parsing and allocation of comma-separated invoices."""
        # Create test invoices
        inv1 = create_purchase_invoice(amount=60.50)
        inv2 = create_purchase_invoice(amount=61.29)

        # Create mutation matching API structure
        mutation = {
            "id": 5473,
            "type": 4,
            "ledgerId": 13201869,
            "amount": 121.79,
            "relationId": "SUPP001",
            "invoiceNumber": f"{inv1.name},{inv2.name}",
            "rows": [
                {"ledgerId": 13201853, "amount": -60.50},
                {"ledgerId": 13201853, "amount": -61.29}
            ]
        }

        # Process payment
        handler = PaymentEntryHandler(get_default_company(), "Main - TC")
        pe_name = handler.process_payment_mutation(mutation)

        # Verify allocations
        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(len(pe.references), 2)
        self.assertEqual(pe.references[0].allocated_amount, 60.50)
        self.assertEqual(pe.references[1].allocated_amount, 61.29)

    def test_single_amount_multiple_invoices(self):
        """Test FIFO allocation when no row breakdown exists."""
        inv1 = create_sales_invoice(amount=50.00)
        inv2 = create_sales_invoice(amount=75.00)

        mutation = {
            "id": 1234,
            "type": 3,
            "ledgerId": 13201869,
            "amount": 100.00,
            "relationId": "CUST001",
            "invoiceNumber": f"{inv1.name},{inv2.name}",
            "rows": [
                {"ledgerId": 13201852, "amount": 100.00}
            ]
        }

        handler = PaymentEntryHandler(get_default_company(), "Main - TC")
        pe_name = handler.process_payment_mutation(mutation)

        pe = frappe.get_doc("Payment Entry", pe_name)
        # Should allocate 50 to first invoice, 50 to second (FIFO)
        self.assertEqual(pe.references[0].allocated_amount, 50.00)
        self.assertEqual(pe.references[1].allocated_amount, 50.00)
```

## Implementation Phases

### Phase 1: Core Implementation (Days 1-2)
1. Implement `PaymentEntryHandler` class
2. Add invoice parsing and allocation logic
3. Integrate with existing migration system
4. Create comprehensive test suite

### Phase 2: Bank Account Mapping (Days 3-4)
1. Enhance ledger-to-bank mapping
2. Add fallback strategies
3. Create configuration UI
4. Test with real ledger data

### Phase 3: Testing & Validation (Days 5-6)
1. Test with actual E-Boekhouden data
2. Validate multi-invoice allocations
3. Performance testing
4. Edge case handling

### Phase 4: Migration & Cleanup (Day 7)
1. Update existing payment processing
2. Remove hardcoded logic
3. Update documentation
4. Deploy to production

## Key Improvements Over Previous Plans

1. **API-Verified Design**: Based on actual API responses, not assumptions
2. **Multi-Invoice Support**: Correctly handles comma-separated invoice numbers
3. **Row-Based Allocation**: Maps payment rows to specific invoices
4. **Flexible Strategies**: 1:1 mapping when possible, FIFO fallback
5. **Production Ready**: Comprehensive error handling and logging

## Success Metrics

1. **Correct Bank Accounts**: 100% of payments use proper bank accounts
2. **Invoice Matching**: >95% of invoiced payments correctly allocated
3. **Processing Speed**: <1 second per payment
4. **Error Rate**: <0.1% failed imports
5. **Reconciliation**: >95% automatic reconciliation rate

## Conclusion

This verified implementation plan addresses all discovered API capabilities:
- Comma-separated invoice support
- Row-based invoice allocation
- Proper bank account mapping
- Comprehensive error handling

The implementation is ready for development and will significantly improve payment import accuracy and reconciliation rates.
