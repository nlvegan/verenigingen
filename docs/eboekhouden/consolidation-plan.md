# E-Boekhouden Code Consolidation Plan

## Implementation Status

| Phase | Status | Commit | Lines Changed |
|-------|--------|--------|---------------|
| Phase 1 | ✅ Complete | c5f79c96 | Deprecation notices, ledger delegation |
| Phase 2 | ✅ Complete | 3ade8bd8 | +108 (date_utils.py), -97 (invoice_helpers) |
| Phase 3 | ✅ Complete | e8f3ca17 | -136 (simple_party_handler.py deleted) |
| Phase 4 | ✅ Complete | (pending) | -70 (wrapper functions removed) |

**Total lines removed**: ~303 lines of duplicated code
**Canonical implementations established**:
- Party resolution: `party_resolver.py` (EBoekhoudenPartyResolver)
- Date utilities: `consolidated/date_utils.py`
- Ledger mapping: `eboekhouden_ledger_mapping.py`

---

## Executive Summary

An external audit identified code duplication in the e-boekhouden module. After detailed analysis, we found **~1,425 lines of duplicated code** across party resolution, ledger mapping, and utility functions.

**Key Finding**: Two competing philosophical approaches exist:
- `party_resolver.py` (852 lines): "API is Single Source of Truth" - always fetches fresh data
- `consolidated/party_manager.py` (504 lines): "DB is cache" - uses API only when needed

**Recommendation**: Keep `party_resolver.py` as canonical (more complete, persistent enrichment queue) and consolidate around it.

---

## Phase 1: Low-Risk Adapter Changes (Week 1)

### 1.1 Replace invoice_helpers party wrappers

**File**: `vereinigingen/e_boekhouden/utils/invoice_helpers.py`

**Current** (lines 115-128):
```python
def resolve_customer(relation_id, debug_info=None):
    from .party_resolver import EBoekhoudenPartyResolver
    resolver = EBoekhoudenPartyResolver()
    return resolver.resolve_customer(relation_id, debug_info)

def resolve_supplier(relation_id, debug_info=None):
    from .party_resolver import EBoekhoudenPartyResolver
    resolver = EBoekhoudenPartyResolver()
    return resolver.resolve_supplier(relation_id, debug_info)
```

**Change**: Keep as-is for now. These are already thin wrappers delegating to the canonical implementation. Mark for potential removal in Phase 3.

**Action**: Add deprecation comment
```python
# DEPRECATED: Import directly from party_resolver instead
# Scheduled for removal in Phase 3 consolidation
```

### 1.2 Replace resolve_ledger_code with delegation

**File**: `vereinigingen/e_boekhouden/utils/invoice_helpers.py` (lines 131-168)

**Current**: Inline DB lookup
```python
def resolve_ledger_code(ledger_id, debug_info=None):
    ledger_code = frappe.db.get_value(
        "E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}, "ledger_code"
    )
    # ... inline logic
```

**Replace with**:
```python
def resolve_ledger_code(ledger_id, debug_info=None):
    """Resolve E-Boekhouden ledger_id to ledger_code.

    Delegates to canonical ledger mapping module.
    """
    from vereinigingen.e_boekhouden.utils.eboekhouden_ledger_mapping import (
        get_account_code_from_ledger_id,
    )

    if not ledger_id:
        return ledger_id

    ledger_code = get_account_code_from_ledger_id(str(ledger_id))

    if ledger_code and debug_info is not None:
        debug_info.append(f"Resolved ledger_id {ledger_id} to ledger_code {ledger_code}")

    return ledger_code or ledger_id
```

**Risk**: Low - same DB lookup, just delegated

### 1.3 Remove deprecated provisional creation wrappers

**File**: `vereinigingen/e_boekhouden/utils/invoice_helpers.py` (lines 197-228)

**Current**: Already marked DEPRECATED, redirects to party_resolver
```python
def create_provisional_customer(relation_id, debug_info=None):
    """DEPRECATED: Use resolve_customer instead..."""
    return resolve_customer(relation_id, debug_info)
```

**Action**:
1. Search for any callers
2. Update callers to use `resolve_customer()` directly
3. Remove deprecated functions

**Command to find callers**:
```bash
grep -rn "create_provisional_customer\|create_provisional_supplier" vereinigingen/ --include="*.py" | grep -v "def create_provisional"
```

---

## Phase 2: Create Shared Utilities Module (Week 2)

### 2.1 Create consolidated date utilities

**New file**: `vereinigingen/e_boekhouden/utils/consolidated/date_utils.py`

```python
"""
Shared date utilities for E-Boekhouden integration.

This module contains cross-cutting date helpers used by invoices,
payments, and migrations.
"""

import frappe
from frappe.utils import getdate, formatdate


def ensure_fiscal_year_exists(transaction_date, company, debug_info=None):
    """
    Ensure a fiscal year exists for the given transaction date.

    Creates the fiscal year if it doesn't exist, using calendar year boundaries.

    Args:
        transaction_date: Date or date string
        company: Company name
        debug_info: Optional list to append debug messages

    Returns:
        str: Fiscal year name (e.g., "2024")
    """
    # Move implementation from invoice_helpers.py lines 18-112
    ...
```

### 2.2 Update imports across codebase

**Files to update**:
- `vereinigingen/e_boekhouden/utils/invoice_helpers.py`
- `vereinigingen/e_boekhouden/utils/payment_processing/payment_entry_handler.py`
- Any other files importing `ensure_fiscal_year_exists`

**Change**:
```python
# Old
from vereinigingen.e_boekhouden.utils.invoice_helpers import ensure_fiscal_year_exists

# New
from vereinigingen.e_boekhouden.utils.consolidated.date_utils import ensure_fiscal_year_exists
```

### 2.3 Keep backward compatibility in invoice_helpers

```python
# invoice_helpers.py - add at top for backward compatibility
from vereinigingen.e_boekhouden.utils.consolidated.date_utils import ensure_fiscal_year_exists

# This re-export maintains backward compatibility for existing callers
__all__ = [..., 'ensure_fiscal_year_exists']
```

---

## Phase 3: Consolidate Party Resolution (Week 3-4)

### 3.1 Decision: Keep party_resolver.py as canonical

**Rationale**:
- More complete implementation (852 lines vs 504 lines)
- Has persistent enrichment queue via `Party Enrichment Queue` DocType
- Implements "API as SSoT" which is correct for data integrity
- Already used by invoice_helpers (the main consumer)

### 3.2 Delete simple_party_handler.py

**File**: `vereinigingen/e_boekhouden/utils/simple_party_handler.py`

**Rationale**: 100% duplicated in consolidated/party_manager.py

**Steps**:
1. Find all imports:
   ```bash
   grep -rn "from.*simple_party_handler import\|import simple_party_handler" vereinigingen/
   ```
2. Replace imports with party_resolver equivalents
3. Delete file

### 3.3 Migrate consolidated/party_manager.py callers

**File**: `vereinigingen/e_boekhouden/utils/consolidated/party_manager.py`

The `EBoekhoudenPartyManager` class has these callers:
- `migration_coordinator.py`

**Migration mapping**:
| party_manager method | Replace with (party_resolver) |
|---------------------|-------------------------------|
| `resolve_customer()` | `EBoekhoudenPartyResolver().resolve_customer()` |
| `resolve_supplier()` | `EBoekhoudenPartyResolver().resolve_supplier()` |
| `get_or_create_customer_simple()` | `EBoekhoudenPartyResolver().resolve_customer()` |
| `get_or_create_supplier_simple()` | `EBoekhoudenPartyResolver().resolve_supplier()` |
| `process_enrichment_queue()` | `EBoekhoudenPartyResolver().enrich_provisional_parties()` |

### 3.4 Deprecate consolidated/party_manager.py

After migrating callers:
1. Add deprecation warning to class
2. Keep file for one release cycle
3. Remove in next major version

---

## Phase 4: Remove Wrappers and Clean Up (Week 5)

### 4.1 Remove invoice_helpers wrappers

After confirming no external callers:
- Remove `resolve_customer()` wrapper (lines 115-120)
- Remove `resolve_supplier()` wrapper (lines 123-128)
- Remove `create_provisional_customer()` (lines 197-211)
- Remove `create_provisional_supplier()` (lines 214-228)

Update any internal callers to import directly from party_resolver.

### 4.2 Clean up imports

Search and replace across codebase:
```python
# Old
from vereinigingen.e_boekhouden.utils.invoice_helpers import resolve_customer

# New
from vereinigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver
resolver = EBoekhoudenPartyResolver()
customer = resolver.resolve_customer(relation_id, debug_info)
```

Or create a simpler function-based API in party_resolver:
```python
# Add to party_resolver.py
_resolver = None

def get_resolver():
    global _resolver
    if _resolver is None:
        _resolver = EBoekhoudenPartyResolver()
    return _resolver

def resolve_customer(relation_id, debug_info=None):
    """Convenience function for customer resolution."""
    return get_resolver().resolve_customer(relation_id, debug_info)

def resolve_supplier(relation_id, debug_info=None):
    """Convenience function for supplier resolution."""
    return get_resolver().resolve_supplier(relation_id, debug_info)
```

---

## Testing Strategy

### Required Tests Before Each Phase

1. **Phase 1 (Adapters)**:
   - Run existing invoice import tests
   - Run ledger mapping tests
   - Verify resolve_ledger_code returns same results

2. **Phase 2 (Date Utils)**:
   - Test fiscal year creation for various dates
   - Test payment entry handler still works
   - Test invoice creation with historical dates

3. **Phase 3 (Party Consolidation)**:
   - Run full e-boekhouden migration test
   - Test customer/supplier resolution
   - Test enrichment queue processing
   - Verify party data integrity

4. **Phase 4 (Cleanup)**:
   - Full regression test
   - Run all e-boekhouden tests

### Test Commands

```bash
# Run e-boekhouden tests
bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.e_boekhouden

# Run specific payment tests
bench --site veg11.veganisme.org run-tests --app vereinigingen --doctype "Payment Entry"

# Run migration tests
bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.test_e_boekhouden_migration_integration
```

---

## Files Inventory

### Files to Modify

| File | Phase | Changes |
|------|-------|---------|
| `invoice_helpers.py` | 1, 4 | Replace resolve_ledger_code, remove wrappers |
| `payment_entry_handler.py` | 2 | Update ensure_fiscal_year_exists import |
| `party_resolver.py` | 4 | Add convenience functions |
| `migration_coordinator.py` | 3 | Replace party_manager with party_resolver |

### Files to Create

| File | Phase | Purpose |
|------|-------|---------|
| `consolidated/date_utils.py` | 2 | Shared date utilities |

### Files to Delete

| File | Phase | Reason |
|------|-------|--------|
| `simple_party_handler.py` | 3 | 100% duplicated |
| `consolidated/party_manager.py` | 3 (deprecate), 5 (delete) | Superseded by party_resolver |

---

## Risk Assessment

| Change | Risk | Mitigation |
|--------|------|------------|
| resolve_ledger_code delegation | Low | Same DB query, just delegated |
| ensure_fiscal_year_exists move | Low | Keep re-export for backward compat |
| Remove simple_party_handler | Medium | Find all callers first |
| Deprecate party_manager | Medium | Keep for one release cycle |
| Remove invoice_helpers wrappers | Medium | Extensive grep for callers |

---

## Success Criteria

1. **Lines of code removed**: Target ~800 lines (simple_party_handler + party_manager)
2. **Single source of truth**: One party resolution implementation
3. **No test regressions**: All existing tests pass
4. **Clear import paths**: Callers know where to import from
5. **Documented deprecation**: Clear migration path for external callers

---

## Timeline

| Week | Phase | Deliverable |
|------|-------|-------------|
| 1 | Phase 1 | Adapter changes, deprecation comments |
| 2 | Phase 2 | date_utils.py created, imports updated |
| 3-4 | Phase 3 | Party resolution consolidated |
| 5 | Phase 4 | Wrappers removed, cleanup complete |

---

## Appendix: Grep Commands for Finding Usages

```bash
# Find party_resolver imports
grep -rn "from.*party_resolver import\|import party_resolver" vereinigingen/ --include="*.py"

# Find party_manager imports
grep -rn "from.*party_manager import\|import party_manager" vereinigingen/ --include="*.py"

# Find simple_party_handler imports
grep -rn "from.*simple_party_handler import\|import simple_party_handler" vereinigingen/ --include="*.py"

# Find ensure_fiscal_year_exists usage
grep -rn "ensure_fiscal_year_exists" vereinigingen/ --include="*.py"

# Find resolve_ledger_code usage
grep -rn "resolve_ledger_code" vereinigingen/ --include="*.py"

# Find create_provisional_customer/supplier usage
grep -rn "create_provisional_customer\|create_provisional_supplier" vereinigingen/ --include="*.py"
```
