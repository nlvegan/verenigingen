# OperationResult Migration Example

This document demonstrates the migration pattern from dict-based results to `OperationResult` using real code from the codebase.

## Overview

The `MemberLifecycleService` has been migrated from dict-based return values to the type-safe `OperationResult` pattern, providing:

- ✅ **Type Safety**: Generic type parameter specifies return data type
- ✅ **Consistency**: Standardized error handling across services
- ✅ **IDE Support**: Better autocomplete and type checking
- ✅ **Clarity**: Explicit success/failure states

## Migration Pattern

### 1. Add Import

```python
from verenigingen.utils.operation_result import OperationResult
```

### 2. Update Method Signature

**Before:**
```python
def approve_application(self, member: "Document") -> Dict[str, Any]:
    """Approve member application."""
```

**After:**
```python
def approve_application(self, member: "Document") -> OperationResult[str]:
    """Approve member application.

    Returns:
        OperationResult[str]: OperationResult with member_id on success
    """
```

### 3. Convert Success Returns

**Before:**
```python
return {
    "success": True,
    "member_id": member.member_id,
    "errors": [],
}
```

**After:**
```python
return OperationResult.ok(member.member_id, approved=True)
```

**Note:** Additional metadata goes into keyword arguments.

### 4. Convert Failure Returns

**Before:**
```python
return {
    "success": False,
    "member_id": None,
    "errors": [f"Application validation failed: {str(e)}"],
}
```

**After:**
```python
return OperationResult.fail(f"Application validation failed: {str(e)}")
```

For multiple errors:
```python
return OperationResult.fail(
    "Validation failed",
    errors=validation_result.get("errors", [])
)
```

### 5. Convert Validation Checks

**Before:**
```python
validation_result = self._validate_application_approval(member)
if not validation_result["success"]:
    return validation_result
```

**After:**
```python
validation_result = self._validate_application_approval(member)
if not validation_result["success"]:
    return OperationResult.fail(
        "Application validation failed",
        errors=validation_result.get("errors", [])
    )
```

**Note:** Helper methods can still return dicts during transition. Convert them later.

### 6. Update Callers

**Before:**
```python
result = member_lifecycle_service.approve_application(self)

if not result["success"]:
    if result["errors"]:
        frappe.throw(_(result["errors"][0]))
    else:
        frappe.throw(_("Application approval failed"))
```

**After:**
```python
result = member_lifecycle_service.approve_application(self)

if not result.success:
    if result.errors:
        frappe.throw(_(result.errors[0]))
    else:
        frappe.throw(_(result.error_message or "Application approval failed"))
```

**Alternative (using unwrap):**
```python
try:
    member_id = result.unwrap()  # Raises ValueError if failed
    # ... use member_id ...
except ValueError as e:
    frappe.throw(_(str(e)))
```

## Complete Example

Here's the complete before/after for `approve_application`:

### Before

```python
def approve_application(self, member: "Document") -> Dict[str, Any]:
    """Approve member application."""
    try:
        # Validate pre-conditions
        validation_result = self._validate_application_approval(member)
        if not validation_result["success"]:
            return validation_result

        # Assign member ID if needed
        if not member.member_id:
            member.member_id = member.generate_member_id()
            member.save()

        return {
            "success": True,
            "member_id": member.member_id,
            "errors": [],
        }

    except Exception as e:
        logger.error(f"Error validating application: {str(e)}")
        return {
            "success": False,
            "member_id": None,
            "errors": [f"Application validation failed: {str(e)}"],
        }
```

### After

```python
def approve_application(self, member: "Document") -> OperationResult[str]:
    """Approve member application.

    Returns:
        OperationResult[str]: OperationResult with member_id on success
    """
    try:
        # Validate pre-conditions
        validation_result = self._validate_application_approval(member)
        if not validation_result["success"]:
            return OperationResult.fail(
                "Application validation failed",
                errors=validation_result.get("errors", [])
            )

        # Assign member ID if needed
        if not member.member_id:
            member.member_id = member.generate_member_id()
            member.save()

        return OperationResult.ok(member.member_id, approved=True)

    except Exception as e:
        logger.error(f"Error validating application: {str(e)}")
        return OperationResult.fail(f"Application validation failed: {str(e)}")
```

## Working with Metadata

For operations that return multiple values, use the metadata parameter:

**Before:**
```python
return {
    "success": True,
    "status": member.status,
    "review_date": member.review_date,
    "cleanup_results": cleanup_result,
    "errors": [],
}
```

**After:**
```python
return OperationResult.ok(
    member.status,  # Primary data value
    rejected=True,  # Additional metadata as kwargs
    review_date=str(member.review_date),
    cleanup_results=cleanup_result
)
```

**Accessing metadata:**
```python
result = member_lifecycle_service.reject_application(member, reason)
if result.success:
    status = result.data  # The primary value
    review_date = result.metadata["review_date"]
    cleanup_results = result.metadata["cleanup_results"]
```

## Migration Checklist

When migrating a service method:

- [ ] Add `OperationResult` import
- [ ] Update method signature with `OperationResult[T]`
- [ ] Update docstring to describe OperationResult return
- [ ] Convert all `return {"success": True, ...}` to `OperationResult.ok(...)`
- [ ] Convert all `return {"success": False, ...}` to `OperationResult.fail(...)`
- [ ] Update all callers to use `.success`, `.errors`, `.error_message`, `.data`
- [ ] Test the migration with unit tests
- [ ] Verify Python syntax with `python -m py_compile`

## Benefits Realized

After migration:

1. **Type Safety**: IDEs can autocomplete `.success`, `.data`, `.errors`
2. **Consistency**: All services use the same error handling pattern
3. **Less Boilerplate**: No need to manually construct error dicts
4. **Better Testing**: Clear success/failure states
5. **API Ready**: Easy conversion to HTTP responses via `.to_dict()`

## Files Migrated

- `verenigingen/services/member/core/member_lifecycle_service.py`
  - `approve_application()` - Lines 48-84
  - `reject_application()` - Lines 86-133

- `verenigingen/verenigingen/doctype/member/member.py`
  - `approve_application()` - Lines 510-525 (caller updated)
  - `reject_application()` - Lines 556-571 (caller updated)

## Next Steps

Continue migrating other service methods following this pattern:

1. Start with services (cleanest separation)
2. Then migrate API endpoints
3. Finally update helper functions

See `docs/development/ERROR_HANDLING_CONVENTIONS.md` for complete guide.
