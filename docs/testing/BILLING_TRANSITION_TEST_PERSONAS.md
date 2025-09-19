# Billing Transition Test Personas

## Overview

This document describes the comprehensive test personas created to validate billing frequency transitions and prevent duplicate charges when members switch between different billing intervals (daily, monthly, quarterly, annual).

## Problem Statement

When members change billing frequencies, there's a risk of:

- **Duplicate billing** for overlapping periods
- **Billing gaps** where members aren't charged
- **Incorrect proration** of unused billing periods
- **Credit calculation errors** when switching mid-cycle

## Test Personas

### 1. Monthly to Annual Mike 🔄

**Scenario**: Switches from €20/month to €200/year mid-month

**Test Validation**:

- ✅ No duplicate billing for transition period
- ✅ Proper credit calculation (€10 for half-month remaining)
- ✅ New annual schedule starts immediately
- ✅ Old monthly schedule becomes inactive

**Key Fields**:

- Current: €20/month, next bill in 15 days
- Requested: €200/year
- Expected Credit: €10.00 (half month unused)

```python
mike = BillingTransitionPersonas.create_monthly_to_annual_mike()
# Creates member with existing monthly billing
# Creates transition request with proper proration
```

### 2. Annual to Quarterly Anna 📅

**Scenario**: Paid €240/year upfront, switches to €80/quarter after 3 months

**Test Validation**:

- ✅ Large credit calculation (€180 for 9 months unused)
- ✅ Quarterly billing delayed by credit amount
- ✅ No immediate charge for first 2+ quarters
- ✅ Proper credit carryover to new schedule

**Key Fields**:

- Current: €240/year paid 3 months ago
- Requested: €80/quarter
- Expected Credit: €180.00 (9/12 months unused)

```python
anna = BillingTransitionPersonas.create_annual_to_quarterly_anna()
# Tests large credit scenarios
# Validates credit application to future billing
```

### 3. Quarterly to Monthly Quinn 📊

**Scenario**: Pays €75/quarter, switches to €30/month mid-quarter

**Test Validation**:

- ✅ Mid-cycle transition handling
- ✅ Credit for remaining quarter portion (€50)
- ✅ Monthly billing starts immediately
- ✅ Proper quarterly period termination

**Key Fields**:

- Current: €75/quarter, paid 1 month ago (2 months remaining)
- Requested: €30/month
- Expected Credit: €50.00 (2/3 quarter unused)

```python
quinn = BillingTransitionPersonas.create_quarterly_to_monthly_quinn()
# Tests mid-period transitions
# Validates fractional credit calculations
```

### 4. Daily to Annual Diana ⚡

**Scenario**: Extreme case - €1/day to €300/year

**Test Validation**:

- ✅ Complex frequent billing transition
- ✅ No billing gaps between daily and annual
- ✅ Proper transition timing
- ✅ Handle high-frequency billing data

**Key Fields**:

- Current: €1/day, paid daily for 30 days
- Requested: €300/year
- Expected Credit: €0.00 (daily billing current)

```python
diana = BillingTransitionPersonas.create_daily_to_annual_diana()
# Tests extreme billing frequency changes
# Validates high-frequency billing scenarios
```

### 5. Mid-Period Switch Sam 🔄🔄

**Scenario**: Multiple transitions - Monthly → Quarterly → Annual in 6 months

**Test Validation**:

- ✅ Multiple sequential transitions
- ✅ Credit accumulation across transitions
- ✅ No duplicate billing through multiple changes
- ✅ Proper transition history tracking

**Key Fields**:

- Transition 1: Monthly (€25) → Quarterly (€70), Credit: €15
- Transition 2: Quarterly → Annual (€250), Additional Credit: €23.33
- Total Accumulated Credit: €38.33

```python
sam = BillingTransitionPersonas.create_mid_period_switch_sam()
# Tests complex multiple transitions
# Validates credit carryover between transitions
```

### 6. Backdated Change Betty ⏰

**Scenario**: Requests Annual → Monthly change backdated 2 months

**Test Validation**:

- ✅ Retroactive billing adjustments
- ✅ Approval workflow for backdated changes
- ✅ Proper retroactive credit and charge calculations
- ✅ Historical billing correction

**Key Fields**:

- Current: €240/year paid 100 days ago
- Requested: €20/month, effective 60 days ago
- Net Calculation: €180 credit - €40 retroactive charges = €140 net credit

```python
betty = BillingTransitionPersonas.create_backdated_change_betty()
# Tests backdated billing changes
# Validates retroactive billing adjustments
```

## Test Infrastructure

### Validation Functions

```python
# Extract billing periods from invoice descriptions
period = extract_billing_period("Monthly period: 2025-01-01 to 2025-01-31")
# Returns: {"start": date(2025-01-01), "end": date(2025-01-31)}

# Detect overlapping billing periods
overlap = periods_overlap(period1, period2)
# Returns: True if periods overlap

# Calculate overlap days
days = calculate_overlap_days(period1, period2)
# Returns: Number of overlapping days
```

### Main Validation Function

```python
# Validate no duplicate billing for a member
validation = BillingTransitionPersonas.validate_no_duplicate_billing(
    member_name="Test-Member-001",
    start_date="2025-01-01",
    end_date="2025-03-31"
)

# Returns:
{
    "valid": True/False,
    "overlaps": [list of overlapping periods],
    "total_invoices": int,
    "message": "descriptive message"
}
```

## Running Tests

### Individual Test Execution

```bash
# Run all billing transition tests
python scripts/testing/runners/billing_transition_test_runner.py --type all

# Test only persona creation
python scripts/testing/runners/billing_transition_test_runner.py --type personas

# Test only transition logic
python scripts/testing/runners/billing_transition_test_runner.py --type transitions

# Test validation functions
python scripts/testing/runners/billing_transition_test_runner.py --type validation

# Create interactive scenarios
python scripts/testing/runners/billing_transition_test_runner.py --scenarios
```

### Frappe Test Integration

```bash
# Run via Frappe's test system
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_billing_transitions

# Run with verbose output
python scripts/testing/runners/billing_transition_test_runner.py --verbose
```

## Key Test Cases

### Critical Validations

1. **No Overlap Detection**: Ensure billing periods never overlap
2. **No Gap Detection**: Ensure no billing gaps during transitions
3. **Credit Calculation**: Verify accurate unused period calculations
4. **Multiple Transitions**: Handle sequential billing changes
5. **Retroactive Adjustments**: Properly handle backdated changes
6. **Edge Cases**: Daily billing, large credits, complex scenarios

### Expected Results

- ✅ All transitions complete without duplicate billing
- ✅ Credits are calculated and applied correctly
- ✅ Billing schedules are properly activated/deactivated
- ✅ Invoice periods align with no overlaps
- ✅ Member billing history remains accurate

## Business Rules Tested

### Transition Rules

1. **Immediate Effect**: Transitions take effect on specified date
2. **Credit Carryover**: Unused billing periods become credits
3. **Approval Required**: Backdated changes need approval
4. **History Preservation**: All transitions are tracked
5. **Schedule Management**: Only one active schedule per member

### Financial Rules

1. **No Double Billing**: Members never charged twice for same period
2. **Proportional Credits**: Unused periods calculated accurately
3. **Credit Application**: Credits reduce future billing automatically
4. **Retroactive Handling**: Backdated changes adjust billing correctly

## Error Scenarios Tested

### Common Failure Cases

- Overlapping invoice periods
- Missing proration calculations
- Credit calculation errors
- Schedule activation failures
- Transition approval bypasses

### Edge Case Coverage

- Same-day transitions
- Multiple rapid transitions
- Large credit amounts (> 1 year)
- Micro-billing (daily) to macro-billing (annual)
- Backdated transitions beyond payment history

## Integration with Existing Tests

These billing transition personas complement existing test infrastructure:

- **BaseTestCase**: Inherits automatic cleanup and tracking
- **TestDataFactory**: Uses existing member/membership creation
- **Validation Framework**: Extends current validation patterns
- **Monitoring Integration**: Supports Zabbix metrics validation

## Continuous Validation

The personas support ongoing validation through:

- Automated regression testing
- Billing system health checks
- Production deployment validation
- Member portal testing
- Financial reconciliation verification

This comprehensive test suite ensures the billing system maintains integrity through all frequency transition scenarios, protecting both member experience and organizational revenue.
