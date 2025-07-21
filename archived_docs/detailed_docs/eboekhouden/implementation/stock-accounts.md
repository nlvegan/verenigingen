# Stock Account Handling in Opening Balance Import

## Overview

ERPNext restricts stock accounts to only be updated via Stock transactions (Stock Reconciliation, Stock Entry, etc.). Journal entries cannot directly update stock accounts. This document explains how the opening balance import handles this restriction.

## Enhanced Stock Account Detection

The opening balance import now includes robust stock account detection and handling:

### 1. **Automatic Stock Account Skipping**
- Stock accounts are automatically detected and skipped during opening balance import
- Comprehensive error handling for account access issues
- Detailed logging of all skipped accounts

### 2. **Improved Error Handling**
```python
try:
    account_doc = frappe.get_doc("Account", account)
    account_type = account_doc.account_type
except frappe.DoesNotExistError:
    # Account not found - skip gracefully
    continue
except Exception as e:
    # Other errors - log and skip
    continue
```

### 3. **Detailed Reporting**
The import now provides comprehensive reporting of what was skipped:
- Stock accounts with their balances
- P&L accounts (also excluded from opening balances)
- Accounts with errors (not found, access issues)

## How It Works

### During Opening Balance Import:
1. **Account Validation**: Each account is validated before processing
2. **Stock Account Detection**: Accounts with `account_type = "Stock"` are identified
3. **Automatic Skipping**: Stock accounts are skipped with detailed logging
4. **Import Continuation**: Import continues with remaining valid accounts

### Result Information:
```json
{
  "success": true,
  "journal_entry": "JE-2025-00001",
  "message": "Opening balances imported successfully",
  "skipped_accounts": {
    "stock": [
      {"account": "Stock Account - Company", "balance": 5000.00}
    ],
    "pnl": [
      {"account": "Sales - Company", "type": "Income"}
    ],
    "errors": []
  },
  "accounts_processed": 25
}
```

## For Future Imports

### No Action Required
- Stock accounts will be automatically skipped
- No manual intervention needed
- Import will complete successfully

### If You Need Stock Balances
If you actually need to set opening stock balances:

1. **Set up Stock Reconciliation** instead of opening balances
2. **Configure Item masters** for all stock items
3. **Use Stock Entry** or **Stock Reconciliation** documents
4. **Set up Warehouses** for proper stock management

### Best Practices
- **For associations not using stock**: Stock accounts being skipped is correct
- **For organizations with actual stock**: Use proper Stock Reconciliation
- **Monitor the logs**: Review skipped accounts to ensure they're expected

## Technical Details

### Files Modified
- `eboekhouden_rest_full_migration.py` - Enhanced main import function
- `opening_balance_processor.py` - Added stock account validation
- `stock_account_handler.py` - Comprehensive stock account utilities

### Key Functions
- `is_stock_account()` - Detect stock accounts
- `validate_opening_balance()` - Validate accounts before processing
- Enhanced error handling throughout the import process

### Logging
All stock account skipping is logged with:
- Account name
- Account type
- Balance amount
- Reason for skipping

This ensures full transparency and auditability of the import process.
