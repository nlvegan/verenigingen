# Balance Transaction Processing

## Overview

The Balance Transaction Processor provides **unlimited historical access** to Mollie transaction data, solving the 90-day limitation of the Settlement API.

## Key Advantages

✅ **No Time Limit** - Access transaction history from any date in the past
✅ **Transaction-Level Detail** - Individual transaction records with full context
✅ **Fee Transparency** - Deductions field provides detailed fee breakdown
✅ **Context Links** - Automatically links to payments and settlements
✅ **Historical Migration** - Batch process years of historical data

## Architecture

```
Balance Transaction → Bank Transaction in ERPNext
- Reference number: baltr_xxxxx (Mollie balance transaction ID)
- Description: Includes payment, settlement, and fee information
- Deposit/Withdrawal: Net amount after fees
- Status: Unreconciled (ready for Bank Reconciliation Tool)
```

## Quick Start

### 1. Verify Configuration

```bash
bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.show_configuration
```

Required settings:
- ✅ Backend API enabled in Mollie Settings
- ✅ Organization Access Token configured
- ✅ Mollie Bank Account configured
- ✅ Company configured

### 2. Check Balance Info

```bash
bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.show_balance_info
```

This shows:
- Primary balance ID
- Available amount
- Pending amount
- Currency

### 3. Process Recent Transactions

```bash
# Process last 30 days
bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_recent_transactions --args "[30]"

# Process last 90 days
bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_recent_transactions --args "[90]"
```

## API Endpoints

### Process Balance Transactions

Process transactions for a specific date range (NO TIME LIMIT):

```bash
# Using API endpoint directly
bench --site dev.veganisme.net execute \
  verenigingen.verenigingen_payments.api.balance_transaction_processing.process_balance_transactions \
  --kwargs "{'from_date': '2024-01-01', 'until_date': '2024-12-31', 'limit': 250}"

# Using test script
bench --site dev.veganisme.net execute \
  scripts.test_balance_transaction_processing.test_date_range \
  --args "['2024-01-01', '2024-12-31']"
```

Parameters:
- `from_date`: Start date (YYYY-MM-DD format)
- `until_date`: End date (YYYY-MM-DD format)
- `limit`: Maximum transactions per batch (default: 250, max: 1000)

### Process Historical Data

Batch process months or years of historical data:

```bash
# Process last 12 months
bench --site dev.veganisme.net execute \
  verenigingen.verenigingen_payments.api.balance_transaction_processing.process_historical_data \
  --kwargs "{'months_back': 12}"

# Process last 24 months with larger batches
bench --site dev.veganisme.net execute \
  verenigingen.verenigingen_payments.api.balance_transaction_processing.process_historical_data \
  --kwargs "{'months_back': 24, 'batch_size': 500}"

# Using test script
bench --site dev.veganisme.net execute \
  scripts.test_balance_transaction_processing.test_historical_migration \
  --args "[12]"
```

Parameters:
- `months_back`: Number of months to look back (max: 120 = 10 years)
- `batch_size`: Transactions per batch (default: 250, max: 1000)

### Check Transaction Status

Check if a transaction has been processed:

```bash
bench --site dev.veganisme.net execute \
  verenigingen.verenigingen_payments.api.balance_transaction_processing.check_transaction_status \
  --kwargs "{'transaction_id': 'baltr_QM24bwP3Ur'}"

# Using test script
bench --site dev.veganisme.net execute \
  scripts.test_balance_transaction_processing.check_transaction_status \
  --args "['baltr_QM24bwP3Ur']"
```

### Get Processing Statistics

View statistics about processed transactions:

```bash
# Last 30 days
bench --site dev.veganisme.net execute \
  verenigingen.verenigingen_payments.api.balance_transaction_processing.get_processing_statistics \
  --kwargs "{'days': 30}"

# Using test script
bench --site dev.veganisme.net execute \
  scripts.test_balance_transaction_processing.show_statistics \
  --args "[30]"
```

## Transaction Description Format

Balance transactions are created with detailed descriptions:

```
Mollie Payment-Refund | Payment: tr_abc123 | Settlement: stl_xyz789 | Fees: EUR 0.29 (Gross: EUR 10.00, Net: EUR 9.71)
```

This includes:
- **Transaction Type**: payment, payment-refund, refund, chargeback, etc.
- **Payment ID**: Links to individual Mollie payment (if applicable)
- **Settlement ID**: Links to settlement batch (if applicable)
- **Fees**: Total deductions/fees charged by Mollie
- **Gross/Net**: Original amount vs. amount after fees

## Use Cases

### Initial Data Migration

When first setting up the system, import all historical transaction data:

```bash
# Import last 2 years of data
bench --site dev.veganisme.net execute \
  scripts.test_balance_transaction_processing.test_historical_migration \
  --args "[24]"
```

### Regular Catchup Processing

Process recent transactions on a regular schedule:

```bash
# Daily: Process last 7 days
bench --site dev.veganisme.net execute \
  scripts.test_balance_transaction_processing.test_recent_transactions \
  --args "[7]"

# Weekly: Process last 30 days
bench --site dev.veganisme.net execute \
  scripts.test_balance_transaction_processing.test_recent_transactions \
  --args "[30]"
```

### Specific Period Analysis

Process transactions for a specific accounting period:

```bash
# Q1 2024
bench --site dev.veganisme.net execute \
  scripts.test_balance_transaction_processing.test_date_range \
  --args "['2024-01-01', '2024-03-31']"

# Full year 2023
bench --site dev.veganisme.net execute \
  scripts.test_balance_transaction_processing.test_date_range \
  --args "['2023-01-01', '2023-12-31']"
```

## Comparison with Settlement Processing

| Feature | Settlement Processor | Balance Transaction Processor |
|---------|---------------------|------------------------------|
| **Historical Access** | 90 days only | Unlimited (years back) |
| **Data Granularity** | Settlement-level (batches) | Transaction-level (individual) |
| **Fee Information** | Calculated from reconciliation | Direct from deductions field |
| **Context Links** | Settlement only | Payment + Settlement links |
| **Use Case** | Recent bank deposits | Historical data, detailed analysis |

## Best Practices

1. **Configuration First**: Always verify configuration before processing
2. **Start Small**: Test with recent data (7-30 days) before historical migration
3. **Check Statistics**: Use statistics endpoint to monitor processing progress
4. **Idempotency**: Safe to re-run - duplicate checking prevents double-processing
5. **Batch Sizes**: Use larger batches (500-1000) for historical migration, smaller (250) for regular processing
6. **Date Ranges**: For large historical migrations, use `process_historical_data()` which automatically batches by month

## Error Handling

The processor includes comprehensive error handling:

- ✅ **Duplicate Prevention**: Checks existing Bank Transactions before creating
- ✅ **Configuration Validation**: Validates Mollie settings and bank accounts
- ✅ **Transaction Logging**: Full audit trail in Frappe error logs
- ✅ **Partial Success**: Continues processing even if individual transactions fail
- ✅ **Detailed Results**: Returns status for each transaction processed

## Monitoring

### Check Recent Processing

```bash
bench --site dev.veganisme.net execute \
  scripts.test_balance_transaction_processing.show_statistics \
  --args "[30]"
```

Shows:
- Total transactions processed
- Reconciled vs. unreconciled
- Total deposit and withdrawal amounts
- Recent transaction list

### View Transaction Details

In ERPNext:
1. Navigate to **Accounting → Bank Statement → Bank Transaction**
2. Filter by reference number starting with `baltr_`
3. View description for payment/settlement links and fee details

## Troubleshooting

### No Transactions Found

**Problem**: Processing returns 0 transactions
**Solutions**:
- Check date range is correct
- Verify balance ID with `show_balance_info`
- Confirm transactions exist in Mollie dashboard
- Check limit parameter isn't too low

### Configuration Errors

**Problem**: "Mollie Bank Account not configured"
**Solutions**:
- Enable Backend API in Mollie Settings
- Set Organization Access Token
- Configure Mollie Bank Account (GL Account)
- Link Bank Account to GL Account

### Already Processed

**Problem**: All transactions show "already_processed"
**Solutions**:
- This is normal - indicates transactions were processed previously
- Use `check_transaction_status` to verify specific transactions
- Check processing statistics to see overall status

## Python API Usage

For programmatic access:

```python
from verenigingen.verenigingen_payments.services.balance_transaction_processor import BalanceTransactionProcessor
from datetime import datetime, timedelta

# Initialize processor
processor = BalanceTransactionProcessor()

# Get primary balance
balance_id = processor.get_primary_balance_id()

# Process recent transactions
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

result = processor.process_balance_transactions(
    balance_id=balance_id,
    from_date=start_date,
    until_date=end_date,
    limit=250
)

print(f"Processed: {result['processed']}")
print(f"Errors: {result['errors']}")
```

## Files

### Service Layer
- `verenigingen/verenigingen_payments/services/balance_transaction_processor.py` - Core processor
- `verenigingen/verenigingen_payments/clients/balances_client.py` - Mollie API client

### API Endpoints
- `verenigingen/verenigingen_payments/api/balance_transaction_processing.py` - Public API

### Testing Scripts
- `scripts/test_balance_transaction_processing.py` - Manual testing commands
- `test_balance_flow.py` - Integration test script

### Documentation
- `docs/mollie/BALANCE_TRANSACTION_PROCESSING.md` - This document
- `docs/mollie/SETTLEMENT_PROCESSING.md` - Settlement processor docs

## Related Documentation

- [Settlement Processing](SETTLEMENT_PROCESSING.md) - 90-day limited settlement processor
- [Mollie Backend API Integration](MOLLIE_BACKEND_INTEGRATION.md) - Overall architecture
- [Bank Reconciliation](../accounting/BANK_RECONCILIATION.md) - ERPNext reconciliation workflow
