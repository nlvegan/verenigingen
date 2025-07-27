# Bandit Critical Fixes Checklist

**Generated:** 2025-07-27
**Priority:** Immediate action required

## High Priority Fixes (Complete within 1 week)

### 1. MD5 Hash Usage (4 instances)

#### Fix 1: Test Base Class
**File:** `verenigingen/tests/utils/base.py:1224`
**Current:**
```python
test_id = hashlib.md5(test_context.encode()).hexdigest()[:4]
```
**Fix:**
```python
test_id = hashlib.md5(test_context.encode(), usedforsecurity=False).hexdigest()[:4]
```
**Risk Level:** LOW (test code only)

#### Fix 2-4: SEPA Race Condition Manager
**File:** `verenigingen/utils/sepa_race_condition_manager.py`
**Locations:** Lines 70, 312, 420

**Current:**
```python
# Line 70
return hashlib.md5(session_data.encode()).hexdigest()[:16]

# Line 312
return hashlib.md5(lock_data.encode()).hexdigest()

# Line 420
batch_resource = f"batch_creation_{hashlib.md5(str(sorted(invoice_names)).encode()).hexdigest()[:16]}"
```

**Fix:**
```python
# Line 70
return hashlib.md5(session_data.encode(), usedforsecurity=False).hexdigest()[:16]

# Line 312
return hashlib.md5(lock_data.encode(), usedforsecurity=False).hexdigest()

# Line 420
batch_resource = f"batch_creation_{hashlib.md5(str(sorted(invoice_names)).encode(), usedforsecurity=False).hexdigest()[:16]}"
```
**Risk Level:** MEDIUM (production code, but non-cryptographic use)

### 2. Hardcoded Temporary Directory
**File:** `verenigingen/api/payment_processing.py:134`
**Current:**
```python
file_path = f"/tmp/{file_name}"
```
**Fix:**
```python
import tempfile
import os
file_path = os.path.join(tempfile.gettempdir(), file_name)
```
**Risk Level:** MEDIUM (security and portability issue)

## Implementation Commands

```bash
# 1. Fix MD5 usage in test base class
sed -i 's/hashlib.md5(test_context.encode())/hashlib.md5(test_context.encode(), usedforsecurity=False)/' vereiningen/tests/utils/base.py

# 2. Fix SEPA race condition manager (requires manual edit due to multiple patterns)
# Edit verenigingen/utils/sepa_race_condition_manager.py manually

# 3. Fix temporary directory usage
# Edit verenigingen/api/payment_processing.py manually
```

## Validation Commands

```bash
# Verify fixes
bandit -r verenigingen/ --skip B101,B601 --exclude archived_removal,archived_unused --severity-level high

# Should show 0 high severity issues after fixes
```

## Review Priority Order

1. **SEPA Race Condition Manager** - Production critical
2. **Payment Processing Temp Files** - Security and portability
3. **Test Base Class** - Development quality

## Test After Fixes

```bash
# Run relevant tests to ensure functionality not broken
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.test_sepa_mandate_creation
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.test_payment_processing
```

## Pre-commit Hook Update

After fixes, update `.pre-commit-config.yaml` to catch future instances:

```yaml
- repo: https://github.com/PyCQA/bandit
  rev: '1.8.6'
  hooks:
    - id: bandit
      args: ['-r', 'verenigingen/', '--skip', 'B101,B601', '--severity-level', 'medium']
      exclude: '^(archived_removal|archived_unused)/'
```

This will catch medium and high severity issues while allowing low-severity patterns that are common in Frappe applications.
