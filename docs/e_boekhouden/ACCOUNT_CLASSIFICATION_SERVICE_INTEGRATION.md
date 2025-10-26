# Account Classification Service Integration Guide

## Overview

The AccountClassificationService consolidates all E-Boekhouden account classification logic into a single, well-tested service. Integration follows a phased approach to minimize risk.

## Current Status: Phase 1 (Parallel Execution)

**Status**: ✅ **COMPLETE** - Ready for validation testing
**Date**: 2025-10-26
**QCE Score**: 7.5/10 (after critical fixes)

### What Phase 1 Does

- Runs new classification service **in parallel** with existing logic
- **Does NOT change** any account creation behavior
- Logs comparison results for validation
- Identifies mismatches between old and new logic

### How to Enable Phase 1

Add to your `site_config.json`:

```json
{
  "enable_account_classification_service_comparison": true
}
```

Or via bench CLI:

```bash
bench --site dev.veganisme.net set-config enable_account_classification_service_comparison true
```

### Running a Test Migration

```bash
# 1. Enable comparison mode
bench --site dev.veganisme.net set-config enable_account_classification_service_comparison true

# 2. Run a migration with chart of accounts
bench --site dev.veganisme.net execute "verenigingen.e_boekhouden.api.eboekhouden_migration.start_migration" \
  --args '["Migration-001", false]'

# 3. Check logs for comparison results
tail -f ~/frappe-bench/logs/dev.veganisme.net.log | grep -E "(CLASSIFICATION|NEW SERVICE)"

# 4. Review mismatches in Error Log
# Navigate to: Desk → Error Log → Filter by "Account Classification Mismatch"
```

### Log Output Examples

**Match Example:**
```
INFO - NEW SERVICE - 1010: Bank/Asset (Confidence: high, Strategy: category_mapping)
INFO - CLASSIFICATION MATCH - 1010: Bank/Asset (Confidence: high)
```

**Mismatch Example:**
```
WARNING - CLASSIFICATION MISMATCH - 6100 (Kosten debiteuren administratie)
  Old: Current Asset/Asset
  New: Expense Account/Expense
  Confidence: medium
  Strategy: code_pattern_personnel_expense
  Notes: 6xxx = Personnel Expenses (RGS)
  Category: , Group:
ERROR LOG - Account Classification Mismatch [Full details in Error Log doctype]
```

### Expected Results

**Target Match Rate**: 95%+ for HIGH confidence classifications

**Common Expected Mismatches** (new logic is BETTER):
1. **Expense accounts with receivable/payable keywords**
   - Old: Classifies as Receivable/Payable (keyword match)
   - New: Classifies as Expense (6xxx code pattern)
   - **New is correct** - Code pattern should override keywords for P&L accounts

2. **Income accounts with expense-related keywords**
   - Old: Might classify as Expense
   - New: Classifies as Income (8xxx/9xxx code pattern)
   - **New is correct** - RGS patterns are definitive

3. **DEB/CRED categories**
   - Old: Current Asset/Current Liability
   - New: Current Asset/Current Liability (same)
   - **Match expected** - Both avoid Receivable/Payable to prevent party linking issues

### Validation Checklist

After running 50-100 account migrations:

- [ ] Check match rate (should be 90%+ overall)
- [ ] Review all mismatches in Error Log
- [ ] Verify mismatches where new logic is BETTER (code pattern fixing keyword issues)
- [ ] Investigate mismatches where new logic might be WORSE
- [ ] Check that no HIGH confidence classifications are wrong
- [ ] Verify no security validation errors (long strings, invalid characters)

### Known Limitations

**Phase 1 does NOT**:
- Change any account creation behavior
- Fix existing classification issues
- Prevent incorrect classifications

**Phase 1 is ONLY for validation** - actual changes come in Phase 2/3.

---

## Phase 2 (Future): High-Confidence Cutover

**Status**: ⏸️ **PLANNED** - Not yet implemented
**Prerequisites**: Phase 1 validation showing 95%+ match rate for HIGH confidence

### What Phase 2 Will Do

- Use new service for **HIGH confidence** classifications only
- Fall back to old logic for MEDIUM/LOW confidence
- Gradually increases new service usage
- Still maintains safety net

### Configuration (Future)

```json
{
  "enable_account_classification_service": true,
  "account_classification_min_confidence": "high"
}
```

---

## Phase 3 (Future): Full Replacement

**Status**: ⏸️ **PLANNED** - Not yet implemented
**Prerequisites**: Phase 2 validation showing no regressions

### What Phase 3 Will Do

- Complete replacement of old classification logic
- Use new service for ALL classifications
- Remove old category_mapping dict
- Deprecate scattered classification functions

### Benefits

- Single source of truth for all classification logic
- Better test coverage (58 unit tests)
- Confidence tracking for troubleshooting
- Security validation (input length limits, format checks)
- Improved strategy ordering (code patterns before keywords for P&L)

---

## Service Architecture

### Classification Strategies (Priority Order)

1. **Category Mapping** (HIGH confidence)
   - E-Boekhouden category codes (DEB, CRED, FIN, BAL, VW, etc.)

2. **Keyword Detection** (MEDIUM/HIGH confidence)
   - Balance sheet accounts (0xxx-3xxx): Keywords checked BEFORE code patterns
   - P&L accounts (4xxx-9xxx): Keywords checked AFTER code patterns

3. **RGS Code Patterns** (MEDIUM confidence)
   - Dutch RGS (Reference Code System) patterns
   - Definitive for P&L ranges (4xxx-9xxx)

4. **Fallback** (LOW confidence)
   - First digit classification when all else fails

### Security Features

- **Length validation**: Max 20/500/20/10 chars for code/description/category/group
- **Format validation**: Alphanumeric codes only (allows spaces/dashes)
- **Exception handling**: Graceful degradation on errors

### Test Coverage

- **58 unit tests** (all passing)
- **14 edge case tests** added in Phase 1:
  - Conflicting signals (expense code + receivable keyword)
  - Malicious input (SQL injection, long strings)
  - Unicode Dutch characters
  - Code boundaries (1999, 3999, 4000)
  - Strategy ordering validation

---

## Troubleshooting

### "Classification Mismatch" Errors Flooding Error Log

**Cause**: Normal during Phase 1 validation
**Solution**: This is expected - review mismatches to determine if new logic is better

### "AccountClassificationService Error" in Logs

**Cause**: Service exception (input validation, unexpected data)
**Solution**: Check error details - may indicate malformed E-Boekhouden data

### No Comparison Logs Appearing

**Cause**: Comparison mode not enabled
**Check**:
```bash
bench --site dev.veganisme.net get-config enable_account_classification_service_comparison
```

**Solution**: Ensure config value is `true` (boolean, not string)

### Service Import Errors

**Cause**: Module path issues
**Solution**:
```bash
cd /home/frappe/frappe-bench/apps/verenigingen
bench --site dev.veganisme.net console
>>> from verenigingen.e_boekhouden.services import AccountClassificationService
>>> # Should work without errors
```

---

## Migration Path

### From Old Functions

**Before** (multiple scattered implementations):
```python
# In eboekhouden_smart_account_typing.py
account_type, root_type = get_smart_account_type(account_data)

# In e_boekhouden_migration.py
account_type = get_recommended_account_type(code, name)

# Inline in create_account()
category_mapping = {...}  # 80 lines of hardcoded logic
```

**After** (unified service):
```python
from verenigingen.e_boekhouden.services import AccountClassificationService

service = AccountClassificationService()
result = service.classify_account(account_data)

account_type = result.account_type
root_type = result.root_type
confidence = result.confidence
strategy = result.strategy_used
notes = result.notes
```

### Deprecation Timeline

**Phase 1** (Current): Old logic still primary, new service for comparison only
**Phase 2** (Q1 2026): New service for HIGH confidence, old logic for fallback
**Phase 3** (Q2 2026): New service for all, old logic deprecated
**Phase 4** (Q3 2026): Old logic removed from codebase

---

## References

- **Service Implementation**: `verenigingen/e_boekhouden/services/account_classification_service.py`
- **Unit Tests**: `verenigingen/tests/unit/test_account_classification_service.py`
- **Integration Point**: `verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.py:1063-1407`
- **QCE Review**: See audit report from 2025-10-26

---

## Questions?

Contact the development team or review:
- Service docstrings for usage examples
- Unit tests for expected behavior
- QCE review for known issues and recommendations
