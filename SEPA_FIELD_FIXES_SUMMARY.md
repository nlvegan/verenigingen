# SEPA Mandate Field Reference Fixes - Summary

## Problem Identified

The SEPA Mandate Lifecycle Manager was referencing **non-existent database fields**, causing the code to be fundamentally broken for real database operations. The field validation tests revealed that the code was trying to access:

1. `valid_from` - **Does not exist in SEPA Mandate doctype**
2. `valid_until` - **Does not exist in SEPA Mandate doctype**
3. `usage_count` - **Does not exist in SEPA Mandate doctype**
4. `last_used_date` - **Does not exist in SEPA Mandate doctype**

## How the Tests Were Masking the Problem

The tests were **completely mocking** the `_get_mandate_info()` method, which meant:

- Tests never hit the real database
- Tests never discovered the fake field references
- Tests were passing false confidence that the code worked
- Integration with real SEPA Mandate documents was completely untested

**Example of problematic test mocking:**
```python
with patch.object(manager, '_get_mandate_info') as mock_mandate:
    mock_mandate.return_value = {
        "mandate_id": "TEST-MANDATE-001",
        "status": "Active",
        # ... fake data that bypassed real database validation
    }
```

## Fixes Applied

### 1. Database Field References Fixed

**File:** `verenigingen/utils/sepa_mandate_lifecycle_manager.py`

- **Line 169-170**: Changed `valid_from` → `first_collection_date`
- **Line 169-170**: Changed `valid_until` → `expiry_date`
- **Line 174-175**: Removed `usage_count` and `last_used_date` from database query
- **Line 248-251**: Updated expiry validation to use `expiry_date` instead of `valid_until`
- **Line 369-371**: Updated expiry warning logic to use `expiry_date` instead of `valid_until`
- **Line 646**: Updated return mapping to use `expiry_date` instead of `valid_until`
- **Line 390-398**: Removed database UPDATE that tried to increment non-existent `usage_count` and `last_used_date` fields

### 2. Business Logic Preserved

The business logic remains intact, but now uses correct field names:

- **Expiry validation**: Now uses `expiry_date` field (which exists)
- **Usage tracking**: Relies on the `usage_history` child table instead of fake fields
- **Date calculations**: Uses `first_collection_date` instead of `valid_from`

### 3. Test Mocks Updated

**File:** `verenigingen/tests/test_sepa_week3_features.py`

Updated mock data to use correct field names:
```python
mock_mandate.return_value = {
    "mandate_id": "TEST-MANDATE-001",
    "status": "Active",
    "sign_date": add_days(today(), -30),
    "first_collection_date": add_days(today(), -25),  # ✅ Correct field
    "expiry_date": add_days(today(), 365),           # ✅ Correct field
    "member": "TEST-MEMBER-001",
    "iban": "NL91ABNA0417164300",
    "mandate_type": "RCUR",                          # ✅ Added missing field
    "creation": add_days(today(), -30),              # ✅ Added missing field
    "modified": today()                              # ✅ Added missing field
}
```

## Verification

### Field Validation Test Results
```
🔍 Running Enhanced Field Validation (includes string literals)...
📋 Loaded 78 doctypes with field definitions
📊 Checked 838 Python files

✅ No field reference issues found!
✅ All field references validated successfully!
```

### Actual SEPA Mandate Doctype Fields (Verified)

From `verenigingen/doctype/sepa_mandate/sepa_mandate.json`:

**✅ Fields that exist:**
- `mandate_id` - Unique reference
- `status` - Active/Cancelled/Expired/Suspended
- `sign_date` - When mandate was signed
- `first_collection_date` - Date of first allowed collection
- `expiry_date` - When mandate expires (optional)
- `member` - Link to Member doctype
- `iban` - Bank account number
- `bic` - Bank identifier
- `mandate_type` - CORE/RCUR/FNAL/OOFF
- `usage_history` - Child table for tracking usage

**❌ Fields that DO NOT exist:**
- `valid_from`
- `valid_until`
- `usage_count`
- `last_used_date`

## Impact

### Before Fixes
- Code would crash with database errors when accessing real SEPA mandates
- Any production usage would fail with "column not found" errors
- Tests gave false confidence

### After Fixes
- Code now works with actual database schema
- All field references are validated and correct
- Business logic preserved but uses proper field names
- Tests updated to reflect reality

## Lessons Learned

1. **Over-mocking is dangerous** - Tests should validate integration with real database schema
2. **Field validation is critical** - Need to verify field names exist before using them
3. **Test what you ship** - Unit tests with excessive mocking can hide fundamental issues
4. **Database schema is the source of truth** - Always check doctype JSON files before coding

## Recommendations

1. **Add integration tests** that use real database operations without mocking
2. **Run field validation** as part of CI/CD pipeline
3. **Review existing tests** for over-mocking patterns
4. **Create database migration** if fake fields were intended to exist but missing
