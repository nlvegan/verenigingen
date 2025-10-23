# Phase 3.2: GL Account Validation Consolidation

**Date**: 2025-10-23
**Status**: Planning → Implementation
**Duration**: 1 week estimate
**Effort**: 6-8 hours

---

## Executive Summary

Consolidate scattered GL account validation logic into MollieConfigurationService with proper validation, caching, and error handling. Currently, GL account validation is duplicated across 4+ files with inconsistent patterns.

**Goal**: Single source of truth for GL account validation with proper error messages and audit trails.

---

## Current State Analysis

### GL Account Usage Patterns

**Found 122 occurrences** of GL account references across 11 files:

| File | Occurrences | Pattern |
|------|-------------|---------|
| `bank_transaction_reconciliation.py` | 29 | Custom validation with DocumentExistenceValidator |
| `mollie_configuration_service.py` | 30 | Configuration getters, no deep validation |
| `test_mollie_configuration_service.py` | 19 | Test coverage for config service |
| `settlement_bank_transaction_processor.py` | 17 | Uses config service, no validation |
| `bank_transaction_creator.py` | 10 | Direct GL account references |
| `balance_transaction_processor.py` | 3 | Uses config service |
| Others | 14 | Mixed patterns |

### Validation Patterns Found

#### Pattern 1: Configuration Service + Manual Validation
**File**: `bank_transaction_reconciliation.py:45-66`

```python
def _validate_mollie_accounts(self):
    """Validate that Mollie accounts are properly configured"""
    try:
        # Use configuration service (will raise ValidationError if not configured)
        bank_account = self.config.get_bank_account_gl()
        clearing_account = self.config.get_clearing_account()

        # Validate accounts exist in database
        if not DocumentExistenceValidator.check_document_exists("Account", bank_account):
            frappe.log_error(
                f"Mollie Bank Account {bank_account} does not exist", "Mollie Account Configuration"
            )

        if not frappe.db.exists("Account", clearing_account):
            frappe.log_error(
                f"Mollie Clearing Account {clearing_account} does not exist",
                "Mollie Account Configuration",
            )
    except frappe.ValidationError:
        # Configuration not complete - log error but don't break
        frappe.log_error("Mollie accounts not properly configured", "Mollie Account Configuration")
```

**Issues**:
- Uses two different validation methods (`DocumentExistenceValidator` vs `frappe.db.exists`)
- Inconsistent error handling (log vs throw)
- No account type validation
- Duplicated across files

#### Pattern 2: Configuration Service Only
**File**: Multiple files using `get_clearing_account()`, `get_bank_account_gl()`, `get_fees_account()`

**Issues**:
- Configuration service returns account names but doesn't validate they exist
- No type checking (Asset, Liability, etc.)
- No validation that account is active/not frozen

#### Pattern 3: Direct GL Account Reference
**File**: `bank_transaction_creator.py` and others

```python
# Direct reference without validation
bank_account = mollie_config.get_bank_account_gl()
# Assume it exists and use it
```

**Issues**:
- No validation
- Silent failures if account deleted/renamed
- No error recovery

---

## Proposed Solution

### New Methods in MollieConfigurationService

#### 1. `validate_gl_account()`

```python
@classmethod
def validate_gl_account(
    cls,
    account_name: str,
    account_type: Optional[str] = None,
    company: Optional[str] = None,
    allow_frozen: bool = False
) -> Dict[str, Any]:
    """
    Validate GL account exists and meets requirements.

    Args:
        account_name: GL Account name to validate (e.g., "10460 - Mollie - NVV")
        account_type: Expected account type ("Asset", "Liability", "Expense", etc.)
        company: Company name (validates account belongs to company)
        allow_frozen: Whether to allow frozen accounts (default: False)

    Returns:
        Dict with account details:
        {
            "valid": True,
            "account_name": "10460 - Mollie - NVV",
            "account_type": "Asset",
            "company": "Vegan Netwerk Nederland",
            "is_group": False,
            "frozen": False
        }

    Raises:
        frappe.ValidationError: If account invalid with specific reason

    Example:
        result = MollieConfigurationService.validate_gl_account(
            "10460 - Mollie - NVV",
            account_type="Asset",
            company="Vegan Netwerk Nederland"
        )
    """
```

**Implementation Strategy**:
1. Check account exists using `frappe.db.exists()`
2. Fetch account details in single query
3. Validate account type if specified
4. Check frozen status
5. Validate company ownership
6. Cache validation results (5 min TTL)
7. Return detailed validation result

#### 2. `get_all_mollie_accounts()`

```python
@classmethod
def get_all_mollie_accounts(cls, validate: bool = True) -> Dict[str, str]:
    """
    Get all configured Mollie GL accounts with optional validation.

    Args:
        validate: Whether to validate accounts exist (default: True)

    Returns:
        Dict mapping account purpose to account name:
        {
            "clearing_account": "10460 - Mollie - NVV",
            "bank_account": "10500 - Triodos Bank - NVV",
            "fees_account": "70100 - Payment Fees - NVV"
        }

    Raises:
        frappe.ValidationError: If validation enabled and any account invalid

    Example:
        accounts = MollieConfigurationService.get_all_mollie_accounts()
        clearing = accounts["clearing_account"]
    """
```

**Implementation Strategy**:
1. Get all account names from configuration
2. If validate=True, call `validate_gl_account()` for each
3. Return dict with all accounts
4. Cache results (5 min TTL)

#### 3. `validate_all_mollie_accounts()`

```python
@classmethod
def validate_all_mollie_accounts(cls, raise_on_error: bool = True) -> Dict[str, Any]:
    """
    Validate all Mollie GL accounts configuration.

    Args:
        raise_on_error: Whether to raise exception on validation failure

    Returns:
        Dict with validation results:
        {
            "valid": True,
            "accounts": {
                "clearing_account": {"valid": True, "account_name": "...", ...},
                "bank_account": {"valid": True, "account_name": "...", ...},
                "fees_account": {"valid": False, "error": "Account not found"}
            },
            "errors": []
        }

    Example:
        # Use in __init__ methods to validate configuration
        validation = MollieConfigurationService.validate_all_mollie_accounts(raise_on_error=False)
        if not validation["valid"]:
            frappe.log_error(f"GL Account validation failed: {validation['errors']}")
    """
```

**Use Case**: Initialization methods can validate all accounts without stopping execution.

---

## Migration Strategy

### Phase 1: Implement Core Methods (2-3 hours)

1. Add `validate_gl_account()` to MollieConfigurationService
2. Add `get_all_mollie_accounts()` method
3. Add `validate_all_mollie_accounts()` method
4. Add caching for validation results
5. Add comprehensive docstrings

### Phase 2: Update Existing Account Getters (1 hour)

Enhance existing methods to use validation:

```python
@classmethod
def get_clearing_account(cls, validate: bool = True) -> str:
    """
    Get Mollie clearing account with optional validation.

    Args:
        validate: Whether to validate account exists (default: True)

    Returns:
        GL Account name

    Raises:
        frappe.ValidationError: If account not configured or validation fails
    """
    settings = cls.get_settings()
    account = settings.get("mollie_clearing_account")

    if not account:
        frappe.throw(...)

    # NEW: Optional validation
    if validate:
        validation = cls.validate_gl_account(account, account_type="Asset")
        if not validation["valid"]:
            frappe.throw(_(
                "Mollie Clearing Account {0} is invalid: {1}"
            ).format(account, validation.get("error", "Unknown error")))

    return account
```

### Phase 3: Migrate Files (2-3 hours)

| File | Current Lines | Migration |
|------|---------------|-----------|
| `bank_transaction_reconciliation.py` | 45-66 (22 lines) | Use `validate_all_mollie_accounts()` |
| `settlement_bank_transaction_processor.py` | Various | Use validated getters |
| `balance_transaction_processor.py` | Various | Use validated getters |
| `bank_transaction_creator.py` | Various | Use validated getters |

**Estimated Reduction**: ~40-50 lines of duplicated validation code

### Phase 4: Add Tests (1-2 hours)

```python
def test_validate_gl_account_success(self):
    """Test GL account validation with valid account"""
    result = MollieConfigurationService.validate_gl_account(
        "10460 - Mollie - NVV",
        account_type="Asset"
    )
    self.assertTrue(result["valid"])
    self.assertEqual(result["account_type"], "Asset")

def test_validate_gl_account_not_found(self):
    """Test GL account validation with non-existent account"""
    with self.assertRaises(frappe.ValidationError):
        MollieConfigurationService.validate_gl_account("NonExistent Account")

def test_validate_gl_account_wrong_type(self):
    """Test GL account validation with wrong account type"""
    with self.assertRaises(frappe.ValidationError):
        MollieConfigurationService.validate_gl_account(
            "10460 - Mollie - NVV",
            account_type="Liability"  # Wrong type
        )

def test_get_all_mollie_accounts(self):
    """Test getting all Mollie accounts"""
    accounts = MollieConfigurationService.get_all_mollie_accounts()
    self.assertIn("clearing_account", accounts)
    self.assertIn("bank_account", accounts)
    self.assertIsInstance(accounts["clearing_account"], str)
```

---

## Benefits

### Immediate Benefits

1. **Consistency**: Single validation logic across all files
2. **Better Error Messages**: Specific reasons for validation failure
3. **Type Safety**: Validates account types match expected usage
4. **Performance**: Cached validation results reduce DB queries
5. **Maintainability**: Changes in one place, not 4+ files

### Long-term Benefits

1. **Easier Debugging**: Validation errors have full context
2. **Audit Trail**: Centralized logging of validation failures
3. **Extensibility**: Easy to add new validation rules
4. **Testing**: Single source of truth for test coverage

---

## Risk Assessment

### Low Risk
- Configuration service already in use and battle-tested
- Validation logic is additive (doesn't break existing code)
- Backward compatible (validation optional parameter)

### Mitigation
- Thorough test coverage (10+ test cases)
- Gradual migration (file by file)
- Keep existing code working during migration
- Add deprecation warnings for old patterns

---

## Success Criteria

1. ✅ All GL account validation uses centralized methods
2. ✅ No duplicated validation logic across files
3. ✅ Comprehensive test coverage (>95%)
4. ✅ Better error messages with validation details
5. ✅ Performance maintained or improved (cached validation)
6. ✅ All pre-commit checks passing

---

## Timeline

| Phase | Duration | Tasks |
|-------|----------|-------|
| **Analysis** | ✅ Complete | Pattern analysis, design document |
| **Implementation** | 2-3 hours | Core validation methods |
| **Migration** | 2-3 hours | Update existing code |
| **Testing** | 1-2 hours | Comprehensive test suite |
| **Documentation** | 30 min | Update docstrings, examples |

**Total**: 6-8 hours over 1 week

---

## Next Steps

1. ✅ Analysis complete
2. 🔄 Start implementation of `validate_gl_account()`
3. Implement `get_all_mollie_accounts()`
4. Migrate `bank_transaction_reconciliation.py`
5. Add comprehensive tests
6. Update documentation

**Status**: Ready to proceed with implementation

---

**Analyst**: Claude
**Review Status**: Pending team review
**Priority**: Medium (improves code quality and maintainability)
