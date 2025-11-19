# Error Handling Patterns

**Status**: Architectural Guidelines
**Review Date**: 2025-10-12
**Context**: Phase 2B Service Refactoring

---

## Overview

The Verenigingen codebase uses **two distinct error handling patterns** based on service context and usage. This is **intentional design**, not inconsistency.

## Pattern 1: Dict-Based Result Pattern

### When to Use
- **Utility services** called from multiple contexts
- **API-facing services** with external consumers
- **Batch operations** where partial failure is acceptable
- **Optional operations** where failure should be logged but not abort

### Signature
```python
def service_method(*args) -> Dict[str, Any]:
    """
    Returns:
        dict: {"success": bool, "error": str, ...additional data...}
    """
```

### Example: SEPAService
```python
@staticmethod
def validate_mandate_creation(member: str, iban: str) -> Dict[str, Any]:
    """Validate SEPA mandate creation parameters"""

    if not member:
        return {"success": False, "error": "Member is required"}

    if not SEPAService.validate_iban(iban):
        return {"success": False, "error": "Invalid IBAN format"}

    return {"success": True, "validated": True}
```

### Usage Pattern
```python
result = SEPAService.validate_mandate_creation(member, iban)

if not result["success"]:
    # Handle gracefully - log, show warning, try alternative
    frappe.log_error(result["error"])
    return handle_alternative_flow()

# Continue with success case
mandate = result["mandate"]
```

### Advantages
- ✅ **Graceful degradation** - Callers can handle errors contextually
- ✅ **Batch-friendly** - Can collect errors without aborting
- ✅ **Rich context** - Return additional data with error
- ✅ **No exception overhead** - Better for high-frequency calls

### Disadvantages
- ❌ **Callers must check** - Easy to forget `if not result["success"]`
- ❌ **Verbose** - More code than try/except
- ❌ **Not Frappe standard** - Framework uses exceptions

## Pattern 2: Exception-Based Pattern

### When to Use
- **Business logic** within DocType lifecycle
- **Validation methods** that should halt processing
- **User-facing operations** where errors show in UI
- **Critical operations** where failure must abort transaction

### Signature
```python
def service_method(*args) -> ReturnType:
    """
    Raises:
        frappe.ValidationError: If validation fails
        frappe.PermissionError: If permission denied
    """
```

### Example: MembershipCreationService
```python
@staticmethod
def _validate_and_get_membership_type(member_doc):
    """Validate that member has a selected membership type"""

    if not member_doc.selected_membership_type:
        frappe.throw(_("No membership type selected for this application"))

    return frappe.get_doc("Membership Type", member_doc.selected_membership_type)
```

### Usage Pattern
```python
try:
    membership = MembershipCreationService.create_membership_on_approval(
        member_doc=member,
        start_date=start_date,
    )
except frappe.ValidationError as e:
    # Frappe shows error to user automatically
    # Transaction rolled back automatically
    raise
```

### Advantages
- ✅ **Frappe standard** - Integrates with framework error handling
- ✅ **Automatic rollback** - Transaction management built-in
- ✅ **User-friendly** - Errors shown in UI automatically
- ✅ **Cleaner code** - No need for constant result checking

### Disadvantages
- ❌ **All or nothing** - Hard to partially recover
- ❌ **Exception overhead** - Stack unwinding cost
- ❌ **Less control** - Caller can't easily customize error handling

## Pattern Selection Decision Tree

```
Is this service called from multiple contexts?
├─ YES → Use Dict Pattern (SEPAService style)
│         Examples: Utility services, batch operations
│
└─ NO → Is this part of DocType business logic?
         ├─ YES → Use Exception Pattern (MembershipCreationService style)
         │         Examples: Validation, lifecycle methods
         │
         └─ UNCERTAIN → Default to Exception Pattern
                        (Frappe framework standard)
```

## Comparison Table

| Aspect | Dict Pattern | Exception Pattern |
|--------|-------------|-------------------|
| **Primary Use** | Utility services | Business logic |
| **Error Propagation** | Explicit checking | Automatic |
| **Transaction Rollback** | Manual | Automatic |
| **User Feedback** | Manual | Automatic |
| **Batch Operations** | Excellent | Poor |
| **Code Verbosity** | Higher | Lower |
| **Frappe Integration** | Manual | Native |
| **Performance** | Better (no exceptions) | Slightly slower |

## Real-World Examples

### Dict Pattern: SEPAService

**Context**: Utility service called from:
- Member DocType (validate method)
- API endpoints (mandate creation)
- Batch processes (mandate renewal)
- Admin tools (validation checks)

**Why Dict Pattern:**
- Different callers need different error handling
- Batch operations can't abort on first failure
- Some contexts just log errors, others show UI

```python
# From batch process - collect all errors
errors = []
for member in members:
    result = SEPAService.validate_mandate_creation(member, iban)
    if not result["success"]:
        errors.append(f"{member}: {result['error']}")
    continue processing...

# From UI - show specific error
result = SEPAService.create_and_link_mandate_enhanced(...)
if not result["success"]:
    frappe.msgprint(result["error"], indicator="red")
    return
```

### Exception Pattern: MembershipCreationService

**Context**: Internal business logic called from:
- Member.create_membership_on_approval() method
- Approval workflow (single member operation)
- Always user-initiated, always transactional

**Why Exception Pattern:**
- Single-member operation (no batching needed)
- Must halt on any error (transactional)
- Errors shown to user via Frappe UI
- Integrates with DocType lifecycle

```python
# From Member DocType
def create_membership_on_approval(self, ...):
    try:
        # Exception pattern - validates and throws
        membership = MembershipCreationService.create_membership_on_approval(
            member_doc=self,
            ...
        )
        # Success - Frappe shows success message
        return membership

    except frappe.ValidationError:
        # Frappe shows error to user
        # Transaction rolled back automatically
        raise
```

## Anti-Patterns to Avoid

### ❌ Mixing Patterns in Same Service
```python
# BAD: Inconsistent within same service
class MyService:
    @staticmethod
    def method_a():
        return {"success": False, "error": "..."}  # Dict

    @staticmethod
    def method_b():
        frappe.throw("Error")  # Exception
```

### ❌ Returning Success Dict on Exception
```python
# BAD: Catching exception just to return dict
def method():
    try:
        do_something()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

# GOOD: Let exception propagate if that's the pattern
def method():
    do_something()
    return {"success": True}
```

### ❌ Throwing Exception When Dict Expected
```python
# BAD: Changing pattern mid-execution
def method():
    if some_check:
        return {"success": False, "error": "..."}  # Dict pattern

    if other_check:
        frappe.throw("Error")  # Exception pattern - inconsistent!
```

## Migration Strategy

When refactoring existing code:

1. **Identify service context** (utility vs. business logic)
2. **Choose pattern** based on decision tree above
3. **Be consistent** within that service
4. **Document choice** in module docstring
5. **Update all callers** to match pattern

## Service-Level Documentation

Add to service docstrings:

```python
class SEPAService:
    """
    SEPA Mandate Utility Service

    Error Handling: Dict-based result pattern
    - All methods return {"success": bool, "error": str, ...}
    - Callers must check result["success"] before using data
    - Exceptions only for unexpected errors (not validation)

    Rationale: Called from multiple contexts requiring different error handling
    """
```

```python
class MembershipCreationService:
    """
    Membership Creation Business Logic Service

    Error Handling: Exception-based pattern
    - Validation errors throw frappe.ValidationError
    - Permission errors throw frappe.PermissionError
    - Callers use try/except for error handling

    Rationale: Part of DocType lifecycle requiring transactional behavior
    """
```

## Code Review Checklist

- [ ] Pattern matches service context (utility vs. business logic)
- [ ] All methods in service use same pattern
- [ ] Callers handle errors correctly for chosen pattern
- [ ] Documentation explains pattern choice
- [ ] Error messages are user-friendly and translatable
- [ ] Transaction handling is correct for pattern

## Related Patterns

- **Security Validation**: See `docs/patterns/SYSTEM_UPDATE_PATTERN.md`
- **Service Design**: See `docs/architecture/SERVICE_LAYER_GUIDELINES.md`
- **Transaction Management**: See `docs/patterns/DOCUMENT_COORDINATION.md`

## References

- Code: `verenigingen/utils/services/sepa_service.py` (Dict pattern)
- Code: `verenigingen/services/member/approval/membership_creation_service.py` (Exception pattern)
- Code Review: Phase 2B Security Review (error pattern discussion)
- Frappe Documentation: Exception Handling and Transaction Management
