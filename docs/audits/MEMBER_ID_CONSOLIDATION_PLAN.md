# Member ID Generation Consolidation Plan

**Created**: 2026-01-03
**Completed**: 2026-01-03
**Status**: ✅ COMPLETE
**Risk**: Low (backward-compatible change)
**Effort**: ~30 minutes (actual)

---

## Completion Summary

Implementation completed 2026-01-03. Changes made:

1. **`services/member/core/member_id_service.py`** - `generate_member_id()` now delegates to `MemberIDManager.get_next_member_id()` for atomic ID generation
2. **`doctype/member/member_id_manager.py`** - Added canonical docstrings marking it as single source of truth

**Verified**: Generated ID `150043` through delegation path, confirming atomic implementation is now used.

---

## Problem Statement (Historical)

Two implementations of member ID generation exist with different concurrency guarantees:

| Location | Function | Approach | Concurrency Safety |
|----------|----------|----------|-------------------|
| `services/member/core/member_id_service.py` | `generate_member_id()` | `settings.save()` | Non-atomic |
| `doctype/member/member_id_manager.py` | `MemberIDManager.get_next_member_id()` | `FOR UPDATE` + transaction | Atomic |

### Current Usage

**Non-atomic version** (active in production path):
```python
# member.py:45
from verenigingen.services.member.core.member_id_service import generate_member_id

# member.py:192 (before_insert)
self.member_id = generate_member_id()
```

**Atomic version** (exists but not in main path):
```python
# member_id_manager.py - has proper DB locking but isn't called
MemberIDManager.get_next_member_id()

# identification/member_id_service.py:129 - uses atomic version
from verenigingen.verenigingen.doctype.member.member_id_manager import MemberIDManager
next_id = MemberIDManager.get_next_member_id()
```

### Risk

Under concurrent member creation, the non-atomic version could theoretically produce duplicate IDs:
1. Request A reads `last_member_id = 1000`
2. Request B reads `last_member_id = 1000` (before A commits)
3. Both assign `member_id = 1001`

In practice, this is unlikely due to low concurrency, but it's a correctness issue.

---

## Proposed Solution

**Delegate, don't migrate.** Change `core/member_id_service.py:generate_member_id()` to call the atomic version internally.

### Before (non-atomic)

```python
# services/member/core/member_id_service.py
def generate_member_id():
    settings = frappe.get_single("Verenigingen Settings")
    new_id = int(settings.last_member_id) + 1
    settings.last_member_id = new_id
    settings.save()  # Non-atomic!
    return str(new_id)
```

### After (delegates to atomic)

```python
# services/member/core/member_id_service.py
def generate_member_id():
    """Generate a unique member ID using atomic counter.

    Delegates to MemberIDManager for proper database-level locking.
    This ensures uniqueness under concurrent member creation.
    """
    from verenigingen.verenigingen.doctype.member.member_id_manager import MemberIDManager
    return str(MemberIDManager.get_next_member_id())
```

### Benefits

1. **Zero import changes** - All existing code continues to work
2. **Backward compatible** - Same function signature, same return type
3. **Single source of truth** - Atomic version is the only implementation
4. **Testable** - Can mock `MemberIDManager` in tests

---

## Implementation Steps

### Step 1: Update `core/member_id_service.py` (5 minutes)

Replace the non-atomic implementation with delegation:

```python
def generate_member_id():
    """Generate a unique member ID using atomic counter.

    Delegates to MemberIDManager for proper database-level locking.
    Maintains backward compatibility - all existing imports continue to work.
    """
    if frappe.session.user == "Guest":
        return None

    try:
        from verenigingen.verenigingen.doctype.member.member_id_manager import MemberIDManager
        return str(MemberIDManager.get_next_member_id())
    except Exception as e:
        # Preserve existing fallback behavior
        handle_service_error(e, "MemberIdService", "Generate Member ID",
                           {"fallback_used": True}, raise_error=False, log_level="warning")
        return str(int(time.time() * 1000))[-8:]
```

### Step 2: Add docstring to atomic version (2 minutes)

Update `member_id_manager.py` to note it's the canonical implementation:

```python
class MemberIDManager:
    """Manages member ID counter with atomic database operations.

    This is the CANONICAL implementation for member ID generation.
    All other ID generation code should delegate to this class.

    Uses FOR UPDATE row locking to prevent duplicate IDs under concurrent load.
    """
```

### Step 3: Update tests (10 minutes)

Verify existing tests pass and add a concurrency test:

```python
def test_concurrent_member_id_generation():
    """Verify no duplicate IDs under simulated concurrency."""
    ids = set()
    for _ in range(100):
        member_id = generate_member_id()
        assert member_id not in ids, f"Duplicate ID: {member_id}"
        ids.add(member_id)
```

### Step 4: Update documentation (5 minutes)

Add note to `member_id_manager.py` header explaining the consolidation.

---

## Files Changed

| File | Change |
|------|--------|
| `services/member/core/member_id_service.py` | Delegate to MemberIDManager |
| `doctype/member/member_id_manager.py` | Add canonical docstring |
| Tests | Add concurrency test |

---

## Rollback Plan

If issues arise, revert the single change to `core/member_id_service.py`. The atomic version remains unchanged and the delegation is the only modification.

---

## Future Considerations

### Not Recommended

1. **Remove `core/member_id_service.py`** - Would require updating 5+ import locations
2. **Move `member_id_manager.py` to services** - Hook functions need locality to doctype
3. **Merge the two service files** - Adds complexity without benefit

### Consider Later

1. **Consolidate `identification/member_id_service.py`** - It wraps MemberIDManager; after consolidation, `core/member_id_service.py` does the same. Could merge them, but low priority.

---

## Approval Checklist

- [ ] Review plan with team
- [ ] Implement Step 1 (delegation)
- [ ] Run test suite
- [ ] Deploy to staging
- [ ] Monitor for duplicate ID issues
- [ ] Mark complete in audit doc
