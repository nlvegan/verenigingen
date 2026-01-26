# Bug: FinancialReportEngine returns closing balance of 0 for accounts without period movements

## Description

The `FinancialReportEngine` (introduced in #49098) incorrectly returns a closing balance of 0 for accounts that have no GL entries within the selected reporting period, even when those accounts have a non-zero opening balance carried forward from prior periods.

This causes Balance Sheet reports using Financial Report Templates to show incorrect values (and fail to balance) when equity or other accounts have no transactions in the current fiscal year.

## Steps to Reproduce

1. Create an equity account (e.g., "Reserves") with transactions in 2024
2. Create a Financial Report Template for Balance Sheet with a row filtering that account using "Closing Balance"
3. Run the Balance Sheet report for fiscal year 2025 (where the account has no transactions)
4. Observe the account shows €0 instead of the carried-forward balance

## Expected Behavior

For an account with:
- Opening balance: €60,000 (from prior year transactions)
- Period movement: €0 (no transactions in 2025)

The closing balance should be: **€60,000**

## Actual Behavior

The closing balance is: **€0**

Debug output showing the issue:
```
0610 - Vrij besteedbaar eigen vermogen:
  dec_2025:
    Opening: -52729.57  ← Correct
    Closing: 0          ← Wrong (should be -52729.57)
    Movement: 0         ← Correct
```

## Root Cause

Two issues in `erpnext/accounts/doctype/financial_report_template/financial_report_engine.py`:

### Issue 1: `_rebase_closing_balances()` (line ~573)

Sets initial closing to 0 instead of opening_balance:

```python
# Current (wrong):
account_data.add_period(PeriodValue(first_period_key, opening_balance, 0, 0))

# Should be:
account_data.add_period(PeriodValue(first_period_key, opening_balance, opening_balance, 0))
```

### Issue 2: `_calculate_running_balances()` (lines ~661-666)

The fallback for accounts without movements doesn't carry forward the previous period's closing balance:

```python
# Current (wrong):
for account_data in balances_data.values():
    for period in self.periods:
        period_key = period["key"]
        if period_key not in account_data.period_values:
            account_data.add_period(PeriodValue(period_key, 0.0, 0.0, 0.0))

# Should be:
for account_data in balances_data.values():
    previous_closing = 0.0
    for period in self.periods:
        period_key = period["key"]
        if period_key in account_data.period_values:
            previous_closing = account_data.period_values[period_key].closing
        else:
            account_data.add_period(PeriodValue(period_key, previous_closing, previous_closing, 0.0))
```

## Suggested Fix

I have a working fix for both issues. Happy to submit a PR if desired.

## Environment

- ERPNext: v16 (develop branch)
- Frappe: v16
- Introduced in: #49098

## Impact

- Balance sheets using Financial Report Templates fail to balance
- Equity accounts with no current-year transactions show as €0
- Any account type (assets, liabilities) without period activity shows incorrect closing balance

/cc @vorasmit
