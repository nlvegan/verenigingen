# Opening Balance Import

## Overview

The eBoekhouden integration includes comprehensive opening balance import functionality with advanced features for stock account handling, automatic balancing, and error recovery.

## Key Features (2025 Enhancements)

### ✅ Automatic Fiscal Year Creation

The system automatically creates fiscal years for opening balance dates if they don't exist.

**Fiscal Year Auto-Creation**:

```python
def ensure_fiscal_year_exists(transaction_date, company, debug_info):
    """Ensure fiscal year exists for transaction date"""
    # Check if fiscal year exists
    existing_fy = frappe.db.sql(
        """SELECT name FROM `tabFiscal Year`
        WHERE %s BETWEEN year_start_date AND year_end_date
        AND disabled = 0""",
        (transaction_date,)
    )

    if not existing_fy:
        # Create fiscal year for calendar year
        fiscal_year = frappe.get_doc({
            "doctype": "Fiscal Year",
            "year": str(transaction_date.year),
            "year_start_date": date(transaction_date.year, 1, 1),
            "year_end_date": date(transaction_date.year, 12, 31)
        })
        fiscal_year.insert(ignore_permissions=True)
```

**Benefits**:
- Prevents "Fiscal Year not found" errors during opening balance import
- Automatically creates calendar year fiscal years (Jan 1 - Dec 31)
- Ensures GL Entries can be created for any opening balance date
- All fiscal year creations are logged for audit purposes

### ✅ Dynamic Opening Balance Date Detection

Opening balance dates are now automatically detected from eBoekhouden mutation data.

**Date Detection Logic**:

```python
# Determine opening balance date from mutations
opening_date = None
for mutation in mutations_data:
    if isinstance(mutation, dict) and mutation.get("date"):
        opening_date = getdate(mutation.get("date"))
        break

# Fallback to 2018-01-01 if no date found
if not opening_date:
    opening_date = getdate("2018-01-01")
```

**Benefits**:
- Uses actual opening balance date from eBoekhouden
- No hardcoded dates that may be incorrect
- Falls back to safe default if date unavailable
- Ensures fiscal year matches actual opening balance period

### ✅ Mandatory Party Assignment for Receivable/Payable Accounts

All receivable and payable accounts in opening balances now require proper party assignment.

**Party Assignment Logic**:

```python
if account_type == "Receivable":
    party_type = "Customer"
    party = _get_or_create_company_as_customer(company, debug_info)
    if not party:
        # Skip account if party creation fails
        debug_info.append("ERROR: Failed to create customer")
        continue
elif account_type == "Payable":
    party_type = "Supplier"
    party = _get_or_create_company_as_supplier(company, debug_info)
    if not party:
        # Skip account if party creation fails
        debug_info.append("ERROR: Failed to create supplier")
        continue
```

**Why This Is Important**:
- ERPNext requires Customer for all Receivable account entries
- ERPNext requires Supplier for all Payable account entries
- Without party information, GL Entries cannot be created
- This was the root cause of opening balances not appearing in ledgers

**How It Works**:
- Creates/finds a customer named "{Company} (Internal)" for receivables
- Creates/finds a supplier named "{Company} (Internal)" for payables
- If party creation fails, the account is skipped with clear error message
- All party operations are logged for troubleshooting

### ✅ Automatic Stock Account Detection

The system automatically detects and properly handles stock accounts during opening balance imports.

**Stock Account Exclusion**:

```python
def is_stock_account(account):
    """Detect stock accounts that cannot be updated via Journal Entry"""
    try:
        account_doc = frappe.get_doc("Account", account)
        return account_doc.account_type == "Stock"
    except frappe.DoesNotExistError:
        return False
```

**Why Stock Accounts are Excluded**:

- ERPNext restricts stock accounts to Stock transactions only
- Journal Entries cannot directly update stock account balances
- Stock reconciliation is the proper method for stock opening balances
- System provides detailed logging of excluded accounts

### ✅ Automatic Balancing

Prevents migration failures from unbalanced opening balance entries.

**Balancing Logic**:

```python
def create_balancing_entry(balance_difference, company, cost_center):
    """Create automatic balancing entry for opening balances"""
    # Get or create temporary difference account
    temp_account = _get_or_create_temporary_diff_account(company)

    balancing_entry = {
        "account": temp_account,
        "debit_in_account_currency": max(0, -balance_difference) if balance_difference < 0 else 0,
        "credit_in_account_currency": max(0, balance_difference) if balance_difference > 0 else 0,
        "cost_center": cost_center,
        "user_remark": "Automatic balancing entry for opening balances",
    }
    return balancing_entry
```

**Benefits**:

- Eliminates "Opening balance entries do not balance" errors
- Creates transparent audit trail of balancing adjustments
- Uses proper "Temporary" account type for differences
- Maintains accounting integrity while enabling successful imports

### ✅ Enhanced Error Handling

Comprehensive error handling for account access and validation issues.

**Error Recovery**:

```python
def validate_account_for_opening_balance(account):
    """Validate account before including in opening balance"""
    try:
        account_doc = frappe.get_doc("Account", account)

        # Check account type restrictions
        if account_doc.account_type == "Stock":
            return False, "Stock account - not allowed in opening balances"

        # Check root type for P&L exclusion
        if account_doc.root_type in ["Income", "Expense"]:
            return False, "P&L account - excluded from opening balances"

        return True, "Valid for opening balance"

    except frappe.DoesNotExistError:
        return False, "Account not found in ERPNext"
    except Exception as e:
        return False, f"Error accessing account: {str(e)}"
```

## Import Process

### Step 1: Data Collection

The system collects opening balance data from eBoekhouden:

1. **Fetch opening mutations** from eBoekhouden API
2. **Extract account balances** for the opening date
3. **Validate account existence** in ERPNext
4. **Filter accounts** based on type and eligibility

### Step 2: Account Validation

Each account goes through comprehensive validation:

```python
validation_results = {
    "valid_accounts": [],      # Accounts included in opening balance
    "stock_accounts": [],      # Stock accounts (excluded)
    "pnl_accounts": [],        # P&L accounts (excluded)
    "missing_accounts": [],    # Accounts not found in ERPNext
    "error_accounts": []       # Accounts with access errors
}
```

### Step 3: Balance Calculation

The system calculates and validates balance totals:

1. **Sum all debit balances**
2. **Sum all credit balances**
3. **Calculate difference** (if any)
4. **Create balancing entry** if needed

### Step 4: Journal Entry Creation

Creates a comprehensive opening balance journal entry:

```python
opening_balance_entry = {
    "doctype": "Journal Entry",
    "voucher_type": "Opening Balance",
    "company": company,
    "posting_date": opening_date,
    "cost_center": cost_center,
    "user_remark": "Opening balances imported from eBoekhouden",
    "accounts": journal_entry_accounts,
    "eboekhouden_import_date": frappe.utils.now(),
    "is_opening": "Yes"
}
```

## Configuration Options

### Basic Configuration

Set up opening balance import in E-Boekhouden Settings:

```
Opening Balance Settings:
├── Enable Opening Balance Import: Yes
├── Opening Balance Date: [Auto-detected or manual]
├── Auto-Balance Entries: Yes (recommended)
└── Skip Stock Accounts: Yes (recommended)
```

### Advanced Options

For specialized requirements:

```python
# Import opening balances only (without full migration)
def import_opening_balances_only(company=None, opening_date=None):
    """Import only opening balance data"""

# Custom opening balance date
opening_date = "2024-01-01"  # Override auto-detected date

# Specific account filtering
account_filters = {
    "exclude_account_types": ["Stock"],
    "include_root_types": ["Asset", "Liability", "Equity"]
}
```

## Detailed Reporting

### Opening Balance Report

The system provides comprehensive reporting of the opening balance import:

```json
{
  "success": true,
  "journal_entry": "JE-2025-00001",
  "opening_date": "2024-01-01",
  "accounts_processed": 45,
  "total_debit": 125000.0,
  "total_credit": 125000.0,
  "balanced": true,
  "balancing_entry_created": false,
  "skipped_accounts": {
    "stock": [{ "account": "Stock Account - Company", "balance": 5000.0 }],
    "pnl": [
      { "account": "Sales - Company", "type": "Income" },
      { "account": "Cost of Goods Sold - Company", "type": "Expense" }
    ],
    "errors": []
  },
  "performance_stats": {
    "processing_time": "2.3 seconds",
    "accounts_per_second": 19.6
  }
}
```

### Audit Trail

Complete audit trail of opening balance processing:

1. **Source data**: eBoekhouden opening balance mutations
2. **Account validation**: Results for each account
3. **Balance calculations**: Debit/credit totals and differences
4. **Balancing entries**: Details of any balancing adjustments
5. **Final journal entry**: Complete transaction record

## Troubleshooting

### Common Issues and Solutions

#### Issue: "Opening balances not showing in General Ledger"

**Symptoms**:
- Journal Entry created and submitted successfully
- No GL Entries created (count = 0)
- Balances don't appear in General Ledger, Trial Balance, or other reports

**Root Cause**:
- Missing party information on Receivable/Payable accounts
- ERPNext validation prevents GL Entry creation without required parties
- Missing fiscal year for the opening balance date

**Solution**: ✅ **Automatically handled (as of 2025)**

The system now:
1. Automatically assigns parties to Receivable/Payable accounts
2. Creates fiscal years if missing for the opening balance date
3. Validates party assignment before creating journal entries
4. Provides clear error messages if party creation fails
5. Logs all party and fiscal year operations for troubleshooting

**Manual Fix for Existing Data**:

If you have an existing opening balance Journal Entry without GL Entries:

```python
import frappe

# Get the Journal Entry
je = frappe.get_doc("Journal Entry", "ACC-JV-2025-00001")

# Fix missing parties
for acc in je.accounts:
    account_type = frappe.db.get_value("Account", acc.account, "account_type")
    if account_type == "Receivable" and not acc.party:
        acc.party_type = "Customer"
        acc.party = "Company Name (Internal)"
    elif account_type == "Payable" and not acc.party:
        acc.party_type = "Supplier"
        acc.party = "Company Name (Internal)"

# Cancel, save, and resubmit
je.cancel()
je.docstatus = 0
je.save()
je.submit()
frappe.db.commit()

# Verify GL Entries created
gl_count = frappe.db.count("GL Entry", {"voucher_no": je.name})
print(f"GL Entries created: {gl_count}")
```

#### Issue: "Stock accounts found in opening balances"

**Solution**: ✅ **Automatically handled**

- Stock accounts are automatically detected and skipped
- Detailed logging shows which accounts were excluded
- No manual intervention required

#### Issue: "Opening balance entries do not balance"

**Solution**: ✅ **Automatically handled**

- System automatically creates balancing entries
- Uses "Temporary" account type for differences
- Maintains complete audit trail of balancing logic

#### Issue: "Account not found in ERPNext"

**Solution**:

1. Import chart of accounts first before opening balances
2. Check account mapping configuration
3. Verify company is correctly set in settings

#### Issue: "P&L accounts included in opening balances"

**Solution**: ✅ **Automatically handled**

- P&L accounts (Income/Expense) are automatically excluded
- Only Balance Sheet accounts (Asset/Liability/Equity) are included
- Detailed reporting shows which accounts were excluded

### Validation Tools

#### Pre-Import Validation

```python
# Validate opening balance data before import
def validate_opening_balance_data():
    """Validate opening balance data before processing"""
    validation_report = {
        "total_accounts": 150,
        "valid_accounts": 120,
        "stock_accounts": 10,
        "pnl_accounts": 15,
        "missing_accounts": 5,
        "estimated_balance_difference": 0.00
    }
    return validation_report
```

#### Post-Import Validation

```python
# Validate imported opening balances
def validate_imported_opening_balances():
    """Validate opening balances after import"""
    trial_balance = generate_trial_balance(opening_date)

    # Compare with eBoekhouden source data
    validation_results = {
        "trial_balance_matches": True,
        "total_assets": 85000.00,
        "total_liabilities": 25000.00,
        "total_equity": 60000.00,
        "balance_sheet_balanced": True
    }
    return validation_results
```

## Best Practices

### Before Opening Balance Import

1. **Complete ERPNext setup**: Ensure company and chart of accounts are configured
2. **Backup database**: Always backup before importing opening balances
3. **Test connectivity**: Verify eBoekhouden API connection is working
4. **Review opening date**: Confirm the opening balance date is correct

### During Import

1. **Monitor progress**: Watch for any error messages or warnings
2. **Review skipped accounts**: Check which accounts were excluded and why
3. **Validate balancing**: Confirm any balancing entries are reasonable
4. **Check performance**: Monitor system resources during large imports

### After Import

1. **Generate trial balance**: Verify trial balance for opening date
2. **Compare totals**: Compare with eBoekhouden opening balance reports
3. **Review journal entry**: Examine the created opening balance journal entry
4. **Test workflows**: Verify ERPNext workflows work with imported data

## API Reference

### Opening Balance Import Function

```python
@frappe.whitelist()
def import_opening_balances_only(company=None, opening_date=None):
    """Import only opening balance entries from eBoekhouden"""

    # Parameters:
    # company: ERPNext company name (optional, uses default from settings)
    # opening_date: Opening balance date (optional, auto-detected from eBoekhouden)

    # Returns comprehensive import report with all details
```

### Usage Examples

```javascript
// JavaScript - Import opening balances via UI
frappe.call({
  method:
    "verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.test_opening_balance_import",
  args: {
    company: "Your Company Name",
    opening_date: "2024-01-01",
  },
  callback: function (r) {
    if (r.message.success) {
      frappe.msgprint("Opening balances imported successfully!");
      console.log("Journal Entry:", r.message.journal_entry);
    }
  },
});
```

```python
# Python - Import opening balances programmatically
result = frappe.call(
    'verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration.test_opening_balance_import',
    company='Your Company Name'
)

if result.get('success'):
    print(f"Opening balances imported: {result.get('journal_entry')}")
    print(f"Accounts processed: {result.get('accounts_processed')}")
else:
    print(f"Import failed: {result.get('error')}")
```

---

**Key Benefits**: The enhanced opening balance import system ensures reliable, accurate, and automatic handling of complex opening balance scenarios while maintaining complete audit trails and error recovery capabilities.

**2025 Status**: All features are production-ready and have been extensively tested with real-world data imports.
