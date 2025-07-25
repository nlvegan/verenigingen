# Edge Case Testing Guide

## Overview

This guide describes the enhanced edge case testing capabilities added to `VereningingenTestCase` based on a user suggestion for better validation testing.

## The Problem

Previously, testing validation logic for edge cases was difficult because:

1. **Business rules prevented invalid scenarios** - You couldn't create the "bad" configurations needed to test if validation caught them
2. **Auto-creation interference** - Creating members/memberships would auto-create schedules, interfering with controlled test data
3. **Workarounds were complex** - Using templates, unsaved documents, and mocking made tests hard to understand

## The Solution

The new approach works **with** business rules rather than against them:

1. **Create normal test data** (member, membership) - gets auto-schedules as expected
2. **Cancel auto-schedules** - removes business rule blocks safely
3. **Create controlled test schedules** - now you can create edge cases and conflicts
4. **Test validation logic** - verify your validation methods catch the problems

## New Methods in VereningingenTestCase

### `clear_member_auto_schedules(member_name)`

Cancels all active dues schedules for a member to enable controlled testing.

```python
# Returns list of cancelled schedule details
cancelled = self.clear_member_auto_schedules(member.name)
```

### `create_controlled_dues_schedule(member_name, billing_frequency, dues_rate, **kwargs)`

Creates a dues schedule with specific parameters for testing.

```python
# Create schedules with specific configurations
monthly = self.create_controlled_dues_schedule(member.name, "Monthly", 25.0)
annual = self.create_controlled_dues_schedule(member.name, "Annual", 250.0)
```

### `setup_edge_case_testing(member_name)`

Complete setup combining schedule clearing with context information.

```python
# One-step setup for edge case testing
context = self.setup_edge_case_testing(member.name)
# Returns: cancelled schedules, member info, active memberships, helper methods
```

## Usage Patterns

### Pattern 1: Billing Frequency Conflicts

```python
def test_billing_frequency_conflict(self):
    # 1. Standard setup
    member = self.create_test_member()
    membership = self.create_test_membership(member=member.name)

    # 2. Enable edge case testing
    self.clear_member_auto_schedules(member.name)

    # 3. Create conflicting schedules
    monthly = self.create_controlled_dues_schedule(member.name, "Monthly", 25.0)
    annual = self.create_controlled_dues_schedule(member.name, "Annual", 250.0)

    # 4. Test validation logic
    validation_result = annual.validate_billing_frequency_consistency()
    self.assertFalse(validation_result["valid"])
```

### Pattern 2: Membership Type Mismatches

```python
def test_membership_type_mismatch(self):
    # 1. Setup with specific membership type
    member = self.create_test_member()
    correct_type = self.create_test_membership_type(name="Correct Type")
    wrong_type = self.create_test_membership_type(name="Wrong Type")

    membership = self.create_test_membership(
        member=member.name,
        membership_type=correct_type.name
    )

    # 2. Clear auto-schedules
    self.clear_member_auto_schedules(member.name)

    # 3. Create schedule with wrong type
    schedule = self.create_controlled_dues_schedule(
        member.name,
        "Monthly",
        30.0,
        membership_type=wrong_type.name  # Mismatch!
    )

    # 4. Test validation catches it
    result = schedule.validate_membership_type_consistency()
    self.assertFalse(result["valid"])
```

### Pattern 3: Rate Validation Edge Cases

```python
def test_inappropriate_zero_rates(self):
    # Setup free and paid membership types
    free_type = self.create_test_membership_type(minimum_amount=0.0)
    paid_type = self.create_test_membership_type(minimum_amount=25.0)

    member = self.create_test_member()
    membership = self.create_test_membership(member=member.name, membership_type=free_type.name)

    self.clear_member_auto_schedules(member.name)

    # Test 1: Zero rate with free type (should be valid)
    free_schedule = self.create_controlled_dues_schedule(
        member.name, "Monthly", 0.0, membership_type=free_type.name
    )
    result = free_schedule.validate_dues_rate()
    self.assertTrue(result["valid"])

    # Test 2: Zero rate with paid type (should be invalid)
    paid_schedule = self.create_controlled_dues_schedule(
        member.name, "Annual", 0.0, membership_type=paid_type.name
    )
    result = paid_schedule.validate_dues_rate()
    self.assertFalse(result["valid"])
```

## Benefits of This Approach

### ✅ **Works with Business Rules**
- Respects the system's protective mechanisms
- Tests realistic scenarios that could occur through admin actions
- No need for complex mocking or validation bypassing

### ✅ **Comprehensive Testing**
- Can test both the protection (business rules) and the validation (your code)
- Tests what happens when business rules are bypassed through normal workflows
- Enables testing of complex multi-schedule scenarios

### ✅ **Maintainable Tests**
- Clear, readable test flow that matches real-world admin actions
- Self-documenting test scenarios
- Automatic cleanup through existing tracking mechanisms

### ✅ **Realistic Edge Cases**
- Tests scenarios that could actually happen in production
- Validates defensive programming against admin errors
- Covers gaps between business rules and validation logic

## Best Practices

### 1. **Use Clear Test Names**
```python
def test_billing_frequency_conflict_detection(self):
def test_membership_type_mismatch_validation(self):
def test_inappropriate_zero_rate_prevention(self):
```

### 2. **Document Test Scenarios**
```python
def test_complex_edge_case(self):
    """
    Test scenario: Admin cancels auto-schedule and creates multiple schedules
    with different billing frequencies. System should detect conflict.
    """
```

### 3. **Test Both Valid and Invalid Cases**
```python
# Test that valid configurations pass
result = valid_schedule.validate_something()
self.assertTrue(result["valid"])

# Test that invalid configurations are caught
result = invalid_schedule.validate_something()
self.assertFalse(result["valid"])
```

### 4. **Use Appropriate Assertions**
```python
# Test validation results structure
self.assertIn("valid", result)
self.assertIn("reason", result)

# Test specific error messages
self.assertIn("billing frequency", result["reason"])
self.assertIn("Type mismatch", result["reason"])
```

## Migration Guide

### Before (Complex Workarounds)
```python
def test_validation_old_way(self):
    # Create template schedule to avoid business rules
    schedule = frappe.new_doc("Membership Dues Schedule")
    schedule.is_template = 1
    schedule.member = None  # No member to avoid validation

    # Test validation method directly on unsaved document
    # Limited testing, doesn't match real scenarios
```

### After (Clean Edge Case Testing)
```python
def test_validation_new_way(self):
    # Create realistic test data
    member = self.create_test_member()
    membership = self.create_test_membership(member=member.name)

    # Enable edge case testing
    self.clear_member_auto_schedules(member.name)

    # Create realistic edge case scenario
    schedule = self.create_controlled_dues_schedule(member.name, "Monthly", 25.0)

    # Test validation in realistic context
    result = schedule.validate_something()
    self.assertFalse(result["valid"])
```

## See Also

- `verenigingen/tests/test_edge_case_testing_demo.py` - Complete examples
- `verenigingen/tests/utils/base.py` - Method implementations
- `verenigingen/tests/test_erpnext_inspired_validations.py` - Updated to use new approach
