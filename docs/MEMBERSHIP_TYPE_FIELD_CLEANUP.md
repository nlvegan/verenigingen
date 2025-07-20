# Membership Type Field Cleanup - References Found

## Summary
Found extensive references to the removed Membership Type fields across the codebase. These need to be cleaned up to prevent runtime errors.

## Fields Being Removed
- minimum_contribution
- suggested_contribution
- maximum_contribution
- contribution_mode (in membership type context)
- enable_income_calculator
- income_percentage_rate
- calculator_description
- predefined_tiers
- fee_slider_max_multiplier
- allow_custom_amounts
- custom_amount_requires_approval
- currency (in membership type context)

## Files Requiring Updates

### 1. Test Files
These test files directly set removed fields on Membership Type objects:

**test_enhanced_membership_portal.py**
- Sets contribution_mode, minimum_contribution, suggested_contribution, maximum_contribution
- Sets fee_slider_max_multiplier, allow_custom_amounts, enable_income_calculator
- Sets income_percentage_rate, calculator_description
- Appends to predefined_tiers

**test_new_membership_system.py**
- Sets all contribution fields
- Appends to predefined_tiers
- Uses predefined_tiers.append()

**test_contribution_system.py**
- Sets contribution_mode, minimum/suggested contribution
- Sets fee_slider_max_multiplier, enable_income_calculator

### 2. Template/Page Files
These files read from Membership Type expecting these fields:

**enhanced_membership_application.py**
- Checks for enable_income_calculator, income_percentage_rate
- Falls back to default values when fields don't exist
- Uses getattr() with defaults - relatively safe

**membership_fee_adjustment.py**
- References enable_income_calculator, income_percentage_rate
- Uses getattr() from verenigingen_settings - safe

**apply_for_membership.py**
- Similar pattern, uses getattr() with defaults

### 3. API Files

**enhanced_membership_application.py**
- References template values for contribution fields
- Uses getattr() with fallbacks

**test_dues_validation.py**
- Checks for suggested_contribution, minimum_contribution
- Uses getattr() - safe

**test_validation_fixes.py**
- References minimum_contribution, suggested_contribution
- Uses getattr() - safe

### 4. Utility Files

**membership_dues_test_validator.py**
- Sets contribution_mode, minimum_contribution, suggested_contribution
- Appends to predefined_tiers

**dues_schedule_auto_creator.py**
- Sets contribution_mode = "Custom"

### 5. JavaScript Files

**membership_application.js**
- References membershipType.currency || 'EUR'
- Safe with fallback

### 6. Workflow Test Files

**test_enhanced_membership_lifecycle.py**
- Sets contribution_mode, enable_income_calculator
- Accesses predefined_tiers array
- Multiple references to tier data

### 7. Backend Component Tests

**test_membership_dues_real_world_scenarios.py**
- Sets all contribution fields
- Appends to predefined_tiers
- Multiple membership type configurations

**test_membership_dues_edge_cases.py**
- Sets contribution fields
- References calculator_description

**test_membership_dues_enhanced_features.py**
- Sets contribution fields
- References custom_amount_requires_approval

## Migration Impact

The migration script `migrate_membership_type_billing_to_dues_schedule.py` handles moving these fields to Membership Dues Schedule Template. However, any code that directly accesses these fields on Membership Type will fail after the migration.

## Recommended Approach

1. **Update Test Files First**
   - Modify tests to use Membership Dues Schedule Template instead
   - Remove direct field assignments on Membership Type

2. **Update Template/Page Files**
   - These mostly use getattr() with defaults, so they're relatively safe
   - Consider adding explicit checks or migration helpers

3. **Add Deprecation Warnings**
   - Before removing fields, add warnings when they're accessed
   - This helps identify any missed references

4. **Create Helper Functions**
   - Add functions to get contribution settings from the new location
   - Update all references to use these helpers

## Critical Files to Update Immediately

1. test_enhanced_membership_portal.py
2. test_new_membership_system.py
3. test_contribution_system.py
4. membership_dues_test_validator.py
5. test_enhanced_membership_lifecycle.py
6. test_membership_dues_real_world_scenarios.py

These files directly set the fields and will fail immediately after field removal.
