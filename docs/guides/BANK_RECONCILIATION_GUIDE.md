# Bank Transaction Import & Reconciliation Workflows

This guide covers the complete bank transaction import and reconciliation process for the Verenigingen app.

## Overview

The process has two main phases:
1. **Import**: Getting bank data into the system (your custom functionality)
2. **Reconciliation**: Matching imported transactions with existing accounting entries (Banking app)

## Phase 1: Bank Transaction Import

### Your Custom Import Functionality
```
Bank CSV/OFX files → Custom import logic → Bank Transaction records
```

**Key Components:**
- Custom import parsers for bank file formats
- Validation and data cleaning
- Creation of Bank Transaction records
- Duplicate detection and prevention

### Bank Transaction Doctype Fields
Important fields created during import:
- `date`: Transaction date
- `description`: Bank description/reference
- `deposit`: Credit amount
- `withdrawal`: Debit amount
- `bank_account`: Associated bank account
- `reference_number`: Bank reference
- `party_type` & `party`: If known (Customer/Supplier)

## Phase 2: Bank Reconciliation

### Banking App Reconciliation Process

#### 1. Access Bank Reconciliation Tool
Navigate to: **Banking** → **Bank Reconciliation Tool**

#### 2. Select Bank Account & Period
- Choose bank account to reconcile
- Set date range for transactions
- Load unmatched transactions

#### 3. Auto-Matching Process
The system automatically attempts to match based on:
- **Amount matching**: Exact amount matches
- **Reference matching**: Invoice numbers, payment references
- **Date proximity**: Transactions within reasonable date ranges
- **Party matching**: Known customers/suppliers

#### 4. Manual Matching Interface
For unmatched transactions:
- **Search function**: Find related invoices/payments
- **Filter options**: By party, amount range, date
- **Match suggestions**: System-recommended matches
- **Create new entries**: For unmatched transactions

### Reconciliation Workflows

#### A. Member Payment Reconciliation
**Scenario**: Bank transaction shows member payment

1. **Auto-match attempt**:
   ```
   Bank Transaction (€15.00, Ref: "Member 12345")
   → Sales Invoice (€15.00, Customer: "John Doe")
   ```

2. **Manual matching if needed**:
   - Search by member ID or name
   - Filter by amount range
   - Check payment status in member portal

3. **Result**: Payment Entry created linking bank transaction to invoice

#### B. SEPA Direct Debit Reconciliation
**Scenario**: SEPA Direct Debit batch processed

1. **Batch Processing**:
   ```
   SEPA Direct Debit Batch → Multiple Bank Transactions
   ```

2. **Bulk Reconciliation**:
   - Match each transaction to corresponding invoice
   - Handle failed/returned payments
   - Update member payment status

#### C. Volunteer Expense Reconciliation
**Scenario**: Expense reimbursement paid

1. **Expense Payment**:
   ```
   Bank Transaction (€50.00, Ref: "Expense Claim EXP-001")
   → Expense Claim (€50.00, Volunteer: "Jane Smith")
   ```

2. **Create Payment Entry**:
   - Link to expense claim
   - Update expense status to "Paid"
   - Record in volunteer's expense history

### Advanced Reconciliation Features

#### 1. Reconciliation Rules
Create automatic matching rules:
```python
# Example rule for member payments
{
    "name": "Member Payment Rule",
    "conditions": [
        {"field": "description", "operator": "contains", "value": "Member"},
        {"field": "deposit", "operator": ">", "value": 0}
    ],
    "actions": [
        {"field": "party_type", "value": "Customer"},
        {"field": "account", "value": "Membership Revenue"}
    ]
}
```

#### 2. Bank Statement Reconciliation
Monthly reconciliation process:
1. **Import bank statement**
2. **Match all transactions**
3. **Generate reconciliation report**
4. **Identify discrepancies**
5. **Create adjustment entries**

#### 3. Multi-Currency Handling
For international transactions:
- **Exchange rate application**
- **Currency conversion records**
- **Gain/loss accounting**

## Integration Points

### Your Import → Banking App
```python
# Example integration flow
def process_bank_file(file_path):
    # 1. Parse bank file (your code)
    transactions = parse_bank_csv(file_path)

    # 2. Create Bank Transaction records
    for txn in transactions:
        bank_transaction = frappe.get_doc({
            "doctype": "Bank Transaction",
            "date": txn.date,
            "description": txn.description,
            "deposit": txn.credit_amount,
            "withdrawal": txn.debit_amount,
            "bank_account": txn.account,
            "reference_number": txn.reference
        })
        bank_transaction.insert()

    # 3. Banking app processes these for reconciliation
    # (automatic via Banking app interface)
```

### Custom Reconciliation Hooks
Add custom logic for your specific use cases:
```python
# In hooks.py
doc_events = {
    "Bank Transaction": {
        "after_insert": "verenigingen.banking.auto_match_member_payments"
    }
}

def auto_match_member_payments(doc, method):
    """Custom auto-matching for member payments"""
    if "Member" in doc.description:
        # Extract member ID and find related invoice
        # Create automatic payment entry
        pass
```

## Workspace Access

With the recent workspace updates, you now have quick access to:

**Main Links:**
- Bank Transaction (list and forms)
- Bank Reconciliation Tool
- Bank Statement Import
- Payment Entry
- SEPA Mandate
- SEPA Direct Debit Batch

**Quick Shortcuts:**
- Bank Reconciliation (one-click access)
- Bank Transactions (quick list view)
- Payment Entries (payment management)
- SEPA Mandates (direct debit setup)

## Best Practices

### 1. Regular Reconciliation Schedule
- **Daily**: For high-volume accounts
- **Weekly**: For member payment processing
- **Monthly**: Complete statement reconciliation

### 2. Transaction Coding
Use consistent description patterns:
```
Member Payment - ID: 12345 - Invoice: INV-2024-001
Expense Claim - EXP-001 - Volunteer: Jane Smith
SEPA Direct Debit - Batch: DD-2024-03 - Multiple invoices
```

### 3. Exception Handling
Document processes for:
- **Returned payments**: Failed direct debits
- **Duplicate transactions**: Bank errors
- **Unidentified payments**: Unknown sources
- **Currency differences**: Exchange rate variations

### 4. Audit Trail
Maintain records of:
- **Reconciliation reports**: Monthly summaries
- **Manual adjustments**: Why and by whom
- **Unmatched transactions**: Follow-up required
- **Bank charges**: Fees and interest

## Troubleshooting Common Issues

### Issue: Transactions Not Auto-Matching
**Solution**:
- Check amount precision (rounding differences)
- Verify date ranges (payment delays)
- Review description patterns
- Update reconciliation rules

### Issue: Duplicate Bank Transactions
**Solution**:
- Implement duplicate detection in import
- Check bank account mapping
- Review import date ranges

### Issue: Missing Party Information
**Solution**:
- Enhance description parsing
- Create party matching rules
- Manual party assignment workflow

### Issue: Reconciliation Performance
**Solution**:
- Index frequently searched fields
- Batch process large imports
- Archive old reconciled transactions

## Future Enhancements

Consider implementing:
1. **AI-powered matching**: Machine learning for better auto-matching
2. **API integrations**: Direct bank feeds
3. **Mobile reconciliation**: On-the-go matching
4. **Automated reporting**: Scheduled reconciliation reports
5. **Dashboard analytics**: Real-time reconciliation metrics

This workflow ensures complete financial control while automating routine reconciliation tasks for your association management system.
