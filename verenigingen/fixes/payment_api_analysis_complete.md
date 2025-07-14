# Complete E-Boekhouden Payment API Analysis

## Executive Summary

Analysis of mutations 7833, 5473, 6217, and 3559 confirms that the E-Boekhouden API **DOES support multiple invoice payments** through comma-separated invoice numbers.

## Key Discoveries

### 🎯 Multiple Invoice Payments ARE Supported!

Two mutations prove this capability:

1. **Mutation 5473** (Supplier Payment):
   - Invoice field: `"7771-2024-15525,7771-2024-15644"`
   - Two invoices paid in one transaction
   - Two rows with amounts: €78.65 and €80.16

2. **Mutation 3559** (Customer Payment):
   - Invoice field: `"760-1,760"`
   - Two invoices paid: 760-1 and 760
   - Two rows with amounts: €247.50 and €742.50

## Detailed Mutation Analysis

### Mutation 7833 - Simple Customer Payment
```json
{
  "type": 3,
  "date": "2025-06-04",
  "invoiceNumber": "2025-55297",
  "relationId": 62976771,
  "ledgerId": 43981046,  // Bank account
  "rows": [
    {
      "ledgerId": 13201873,  // Customer receivable account
      "amount": 40.30
    }
  ]
}
```
**Pattern**: Single invoice, single row, straightforward payment

### Mutation 5473 - Multi-Invoice Supplier Payment ⭐
```json
{
  "type": 4,
  "date": "2024-02-08",
  "invoiceNumber": "7771-2024-15525,7771-2024-15644",  // TWO INVOICES!
  "relationId": 20301647,
  "ledgerId": 13201869,  // Bank account
  "rows": [
    {
      "ledgerId": 13201883,  // Supplier payable account
      "amount": 78.65       // Payment for first invoice
    },
    {
      "ledgerId": 13201883,  // Same payable account
      "amount": 80.16       // Payment for second invoice
    }
  ]
}
```
**Pattern**: Two invoices with comma separator, two rows matching invoice count

### Mutation 6217 - Direct Payment (No Invoice)
```json
{
  "type": 6,
  "date": "2024-11-28",
  "invoiceNumber": "",  // No invoice
  "relationId": 0,      // No relation
  "ledgerId": 13201869, // Bank account
  "rows": [
    {
      "ledgerId": 31890946,  // Expense account
      "amount": 75.00
    },
    {
      "ledgerId": 44031841,  // Another expense account
      "amount": 75.00
    }
  ]
}
```
**Pattern**: Direct expense payment without invoice reference

### Mutation 3559 - Multi-Invoice Customer Payment ⭐
```json
{
  "type": 3,
  "date": "2021-12-27",
  "invoiceNumber": "760-1,760",  // TWO INVOICES!
  "relationId": 22982915,
  "ledgerId": 13201869,  // Bank account
  "rows": [
    {
      "ledgerId": 13201876,  // Customer receivable account
      "amount": 247.50      // Payment for invoice 760-1
    },
    {
      "ledgerId": 13201876,  // Same receivable account
      "amount": 742.50      // Payment for invoice 760
    }
  ]
}
```
**Pattern**: Two invoices, two rows with different amounts

## API Structure Patterns

### Payment Entry Structure
```typescript
interface PaymentMutation {
  id: number;
  type: 3 | 4;  // 3 = Customer Payment, 4 = Supplier Payment
  date: string;
  description: string;
  ledgerId: number;  // Bank/Cash account
  relationId: number;  // Customer/Supplier ID
  invoiceNumber: string;  // Can be comma-separated for multiple invoices
  rows: Array<{
    ledgerId: number;  // Receivable/Payable account
    amount: number;    // Amount allocated to specific invoice
    vatCode: string;
    description: string;
  }>;
}
```

### Multiple Invoice Patterns

1. **Comma-Separated Invoice Numbers**:
   - Format: `"invoice1,invoice2,invoice3"`
   - Examples: `"760-1,760"` or `"7771-2024-15525,7771-2024-15644"`

2. **Row-to-Invoice Mapping**:
   - When row count matches invoice count, rows likely map 1:1 to invoices
   - Row order appears to match invoice order in the comma-separated list

3. **Amount Allocation**:
   - Each row amount represents payment for a specific invoice
   - Total payment = sum of all row amounts

## Implementation Requirements

### 1. Invoice Number Parsing
```python
def parse_invoice_numbers(invoice_field):
    """Parse comma-separated invoice numbers"""
    if not invoice_field:
        return []

    # Split by comma and clean up
    invoices = [inv.strip() for inv in invoice_field.split(",")]
    return [inv for inv in invoices if inv]

# Examples:
# "760-1,760" → ["760-1", "760"]
# "7771-2024-15525,7771-2024-15644" → ["7771-2024-15525", "7771-2024-15644"]
```

### 2. Row-to-Invoice Allocation Logic
```python
def allocate_rows_to_invoices(invoice_numbers, rows):
    """Map payment rows to specific invoices"""

    if len(rows) == len(invoice_numbers):
        # Direct 1:1 mapping
        allocations = []
        for i, invoice_num in enumerate(invoice_numbers):
            allocations.append({
                "invoice": invoice_num,
                "amount": rows[i]["amount"],
                "ledger_id": rows[i]["ledgerId"]
            })
        return allocations
    else:
        # Need more complex allocation strategy
        return proportional_allocation(invoice_numbers, rows)
```

### 3. Payment Entry Creation
```python
def create_payment_entry_with_multiple_invoices(mutation_data):
    """Create payment entry that can handle multiple invoices"""

    # Parse invoice numbers
    invoice_numbers = parse_invoice_numbers(mutation_data["invoiceNumber"])

    # Create payment entry
    payment_entry = frappe.new_doc("Payment Entry")
    payment_entry.payment_type = "Receive" if mutation_data["type"] == 3 else "Pay"

    # Add references for each invoice
    allocations = allocate_rows_to_invoices(invoice_numbers, mutation_data["rows"])

    for allocation in allocations:
        invoice = find_invoice(allocation["invoice"])
        if invoice:
            payment_entry.append("references", {
                "reference_doctype": get_invoice_doctype(payment_entry.payment_type),
                "reference_name": invoice.name,
                "allocated_amount": allocation["amount"]
            })

    return payment_entry
```

## Critical Implementation Notes

### 1. Invoice Matching
- Invoice numbers in E-Boekhouden might not match ERPNext exactly
- May need fuzzy matching or mapping table
- Consider partial invoice number matching (e.g., "760-1" might be "ACC-SINV-2021-00760-1" in ERPNext)

### 2. Amount Validation
- Ensure sum of row amounts equals total payment
- Validate individual allocations against invoice outstanding amounts
- Handle over/under payments appropriately

### 3. Missing Invoice Handling
- If invoice not found in ERPNext, options:
  1. Create unallocated payment
  2. Hold in queue for later matching
  3. Create placeholder invoice
  4. Log for manual review

### 4. Bank Account Mapping
- Main `ledgerId` is the bank/cash account
- Must have proper ledger mapping to ERPNext account
- Validate account type is Bank or Cash

## Testing Scenarios

1. **Single Invoice Payment** ✓
   - Mutation 7833 demonstrates this
   - Standard case, should work smoothly

2. **Multiple Invoice Payment - Same Party** ✓
   - Mutations 5473 and 3559 demonstrate this
   - Parse comma-separated invoices
   - Allocate amounts from rows

3. **Partial Payments**
   - Need to find examples where payment < invoice total
   - Test allocation logic

4. **Overpayments**
   - Need examples where payment > invoice total
   - Test advance/credit handling

5. **Mixed Invoice Types**
   - Can a payment cover both sales and purchase invoices?
   - Need more data to confirm

## Recommendations

### High Priority
1. ✅ Implement comma-separated invoice parsing
2. ✅ Create row-to-invoice allocation logic
3. ✅ Update PaymentEntry creation to handle multiple references
4. ✅ Add validation for total amounts

### Medium Priority
1. 🔄 Create invoice matching/mapping system
2. 🔄 Implement unallocated payment handling
3. 🔄 Add payment reconciliation reports
4. 🔄 Create manual matching interface

### Low Priority
1. ⏳ Optimize for large payment batches
2. ⏳ Add payment reversal detection
3. ⏳ Implement payment splitting UI

## Next Steps

1. **Search for more complex examples**:
   - Partial payments across multiple invoices
   - Payments with advances
   - Cross-type payments

2. **Implement core logic**:
   - Start with PaymentEntryHandler class
   - Add multi-invoice support
   - Test with real data

3. **Create test suite**:
   - Unit tests for parsing logic
   - Integration tests for payment creation
   - End-to-end tests for full import

## Conclusion

The E-Boekhouden API is more sophisticated than initially assumed. It supports:
- ✅ Multiple invoice payments via comma-separated invoice numbers
- ✅ Row-level amount allocation
- ✅ Both customer and supplier payments
- ✅ Direct payments without invoices

The implementation should focus on properly parsing and allocating these multi-invoice payments to maintain accurate financial records in ERPNext.
