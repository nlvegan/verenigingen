# Updated E-Boekhouden Payment Implementation Plan

Based on the API analysis of mutations 7833, 5473, and 6217, here's the updated implementation plan that reflects the actual API capabilities.

## Key API Discoveries

1. **Multiple Invoice Support EXISTS**: The API supports multiple invoice payments through comma-separated invoice numbers in the `invoiceNumber` field
2. **Payment Structure**: Uses `ledgerId` for bank account and `rows` for allocations
3. **Direct Payments**: Type 6 mutations handle non-invoice payments

## Implementation Plan

### Phase 1: Update Mutation Type Handlers

#### 1.1 Create Payment Entry Handler (payment_entry_handler.py)
```python
class PaymentEntryHandler:
    """Handles Type 3 (Customer Payment) and Type 4 (Supplier Payment) mutations"""

    def create_payment_entry(self, mutation_data, company):
        # Parse potentially multiple invoice numbers
        invoice_numbers = self._parse_invoice_numbers(mutation_data.get("invoiceNumber", ""))

        # Determine payment type
        payment_type = "Receive" if mutation_data["type"] == 3 else "Pay"
        party_type = "Customer" if mutation_data["type"] == 3 else "Supplier"

        # Get party from relation
        party = self._get_or_create_party(mutation_data["relationId"], party_type)

        # Get bank account from main ledgerId
        bank_account = self._get_bank_account(mutation_data["ledgerId"])

        # Create payment entry
        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.payment_type = payment_type
        payment_entry.party_type = party_type
        payment_entry.party = party
        payment_entry.posting_date = mutation_data["date"]
        payment_entry.paid_from = bank_account if payment_type == "Pay" else self._get_party_account(party_type, party)
        payment_entry.paid_to = self._get_party_account(party_type, party) if payment_type == "Pay" else bank_account

        # Handle single or multiple invoices
        if invoice_numbers:
            self._add_invoice_references(payment_entry, invoice_numbers, mutation_data["rows"])
        else:
            # Direct payment without invoice
            payment_entry.paid_amount = sum(row["amount"] for row in mutation_data["rows"])
            payment_entry.received_amount = payment_entry.paid_amount

        return payment_entry

    def _parse_invoice_numbers(self, invoice_field):
        """Parse comma-separated invoice numbers"""
        if not invoice_field:
            return []
        # Handle comma-separated format like "7771-2024-15525,7771-2024-15644"
        invoices = [inv.strip() for inv in invoice_field.split(",")]
        return [inv for inv in invoices if inv]

    def _add_invoice_references(self, payment_entry, invoice_numbers, rows):
        """Add references for single or multiple invoices"""
        if len(invoice_numbers) == 1:
            # Single invoice - straightforward
            invoice = self._find_invoice(invoice_numbers[0], payment_entry.party_type)
            if invoice:
                payment_entry.append("references", {
                    "reference_doctype": "Sales Invoice" if payment_entry.party_type == "Customer" else "Purchase Invoice",
                    "reference_name": invoice.name,
                    "outstanding_amount": invoice.outstanding_amount,
                    "allocated_amount": sum(row["amount"] for row in rows)
                })
        else:
            # Multiple invoices - need to allocate amounts
            self._allocate_multiple_invoices(payment_entry, invoice_numbers, rows)

    def _allocate_multiple_invoices(self, payment_entry, invoice_numbers, rows):
        """Allocate payment across multiple invoices"""
        # Strategy 1: If rows match invoice count, map directly
        if len(rows) == len(invoice_numbers):
            for i, invoice_num in enumerate(invoice_numbers):
                invoice = self._find_invoice(invoice_num, payment_entry.party_type)
                if invoice and i < len(rows):
                    payment_entry.append("references", {
                        "reference_doctype": "Sales Invoice" if payment_entry.party_type == "Customer" else "Purchase Invoice",
                        "reference_name": invoice.name,
                        "outstanding_amount": invoice.outstanding_amount,
                        "allocated_amount": rows[i]["amount"]
                    })
        else:
            # Strategy 2: Allocate proportionally or by outstanding amount
            total_amount = sum(row["amount"] for row in rows)
            self._proportional_allocation(payment_entry, invoice_numbers, total_amount)
```

#### 1.2 Update Direct Payment Handler
```python
class DirectPaymentHandler:
    """Handles Type 5 (Money Received) and Type 6 (Money Spent) mutations"""

    def create_journal_entry(self, mutation_data, company):
        je = frappe.new_doc("Journal Entry")
        je.posting_date = mutation_data["date"]
        je.company = company

        # Bank/Cash account from main ledgerId
        bank_account = self._get_account_from_ledger(mutation_data["ledgerId"])

        # Process rows
        for row in mutation_data["rows"]:
            account = self._get_account_from_ledger(row["ledgerId"])

            # Determine debit/credit based on type
            if mutation_data["type"] == 5:  # Money Received
                # Bank = Debit, Other = Credit
                je.append("accounts", {
                    "account": bank_account,
                    "debit_in_account_currency": row["amount"]
                })
                je.append("accounts", {
                    "account": account,
                    "credit_in_account_currency": row["amount"]
                })
            else:  # Money Spent
                # Bank = Credit, Other = Debit
                je.append("accounts", {
                    "account": account,
                    "debit_in_account_currency": row["amount"]
                })
                je.append("accounts", {
                    "account": bank_account,
                    "credit_in_account_currency": row["amount"]
                })

        return je
```

### Phase 2: Enhanced Mutation Processing

#### 2.1 Update process_mutation in REST Iterator
```python
def process_mutation(self, mutation_data):
    """Enhanced mutation processing with proper type handling"""

    mutation_type = mutation_data.get("type")

    # Skip if already imported
    if self._is_already_imported(mutation_data["id"]):
        return None

    # Route to appropriate handler
    if mutation_type in [3, 4]:  # Payment mutations
        handler = PaymentEntryHandler()
        doc = handler.create_payment_entry(mutation_data, self.company)
    elif mutation_type in [5, 6]:  # Direct money transactions
        handler = DirectPaymentHandler()
        doc = handler.create_journal_entry(mutation_data, self.company)
    elif mutation_type in [1, 2]:  # Invoices
        handler = InvoiceHandler()
        doc = handler.create_invoice(mutation_data, self.company)
    elif mutation_type == 7:  # Memorial with enhanced logic
        handler = MemorialHandler()
        doc = handler.create_appropriate_entry(mutation_data, self.company)
    else:
        # Default to journal entry
        handler = JournalEntryHandler()
        doc = handler.create_journal_entry(mutation_data, self.company)

    # Set common fields
    doc.eboekhouden_mutation_nr = str(mutation_data["id"])

    return doc
```

### Phase 3: Testing Strategy

#### 3.1 Find More Multi-Invoice Examples
```python
@frappe.whitelist()
def find_multi_invoice_payments():
    """Search for more examples of multiple invoice payments"""
    api = EBoekhoudenAPI()

    # Get recent payments
    result = api.get_mutations({
        "dateFrom": "2024-01-01",
        "dateTo": "2024-12-31",
        "limit": 1000
    })

    if result["success"]:
        mutations = json.loads(result["data"])["items"]

        # Filter for payment types with comma in invoice number
        multi_invoice_payments = [
            m for m in mutations
            if m.get("type") in [3, 4] and "," in m.get("invoiceNumber", "")
        ]

        return {
            "count": len(multi_invoice_payments),
            "examples": multi_invoice_payments[:10]
        }
```

#### 3.2 Test Payment Import
```python
@frappe.whitelist()
def test_payment_import(mutation_id):
    """Test importing a specific payment mutation"""
    api = EBoekhoudenAPI()
    result = api.make_request(f"v1/mutation/{mutation_id}")

    if result["success"]:
        mutation_data = json.loads(result["data"])

        # Test the handler
        if mutation_data["type"] in [3, 4]:
            handler = PaymentEntryHandler()
            payment_entry = handler.create_payment_entry(mutation_data, frappe.defaults.get_user_default("Company"))

            # Don't save, just validate
            payment_entry.validate()

            return {
                "success": True,
                "payment_type": payment_entry.payment_type,
                "party": payment_entry.party,
                "references": [ref.as_dict() for ref in payment_entry.references],
                "total_allocated": sum(ref.allocated_amount for ref in payment_entry.references)
            }
```

### Phase 4: Migration Updates

#### 4.1 Update E-Boekhouden Migration DocType
Add progress tracking for payment imports:
```python
# In migrate_transactions method
payment_mutations = [m for m in all_mutations if m["type"] in [3, 4]]
self.log_migration_step(f"Found {len(payment_mutations)} payment mutations to import")

for mutation in payment_mutations:
    try:
        handler = PaymentEntryHandler()
        payment = handler.create_payment_entry(mutation, self.company)
        payment.insert()
        payment.submit()

        self.imported_payments += 1
    except Exception as e:
        self.log_migration_step(f"Failed to import payment {mutation['id']}: {str(e)}")
        self.failed_payments += 1
```

### Phase 5: Validation and Reconciliation

#### 5.1 Payment Validation
```python
def validate_payment_import(payment_entry, mutation_data):
    """Validate that payment was imported correctly"""

    # Check total amount
    total_mutation = sum(row["amount"] for row in mutation_data["rows"])
    total_payment = payment_entry.paid_amount

    if abs(total_mutation - total_payment) > 0.01:
        frappe.throw(f"Amount mismatch: {total_mutation} vs {total_payment}")

    # Check invoice references
    invoice_numbers = parse_invoice_numbers(mutation_data.get("invoiceNumber", ""))
    if len(invoice_numbers) != len(payment_entry.references):
        frappe.log_error(f"Invoice reference count mismatch for mutation {mutation_data['id']}")

    return True
```

## Implementation Priority

1. **High Priority**:
   - Implement PaymentEntryHandler with multi-invoice support
   - Update mutation router to use new handlers
   - Add validation for payment imports

2. **Medium Priority**:
   - Implement DirectPaymentHandler for type 5/6
   - Add progress tracking to migration
   - Create reconciliation reports

3. **Low Priority**:
   - Optimize allocation strategies
   - Add UI for manual payment matching
   - Implement payment reversal handling

## Testing Checklist

- [ ] Test single invoice payment (Type 3)
- [ ] Test multiple invoice payment (Type 4 with comma-separated)
- [ ] Test direct payment without invoice (Type 6)
- [ ] Test payment allocation accuracy
- [ ] Test party account detection
- [ ] Test bank account mapping
- [ ] Verify no duplicate imports
- [ ] Test error handling for missing invoices

## Notes

1. The comma-separated invoice format (e.g., "7771-2024-15525,7771-2024-15644") is the key to handling multiple invoices
2. Row amounts might correspond to individual invoices or need proportional allocation
3. Always validate bank account mappings before import
4. Consider creating unallocated payments if invoices aren't found yet
