# System Update Pattern Guidelines

**Status**: Approved Pattern
**Review Date**: 2025-10-12
**Approved By**: Code Review (Phase 2B Security Review)

---

## Overview

The `_system_update` flag is a Frappe framework pattern for bypassing **business rule validation** in system-initiated workflows. This document defines when this pattern is acceptable and how to use it safely.

## Critical Distinction

**What `_system_update` Bypasses:**
- ✅ Business rule validation in `Document.validate()`
- ✅ Custom validation logic checking field constraints
- ✅ Example: Fee override validation, date range checks

**What `_system_update` Does NOT Bypass:**
- ❌ Permission validation (`has_permission`)
- ❌ DocType-level permissions
- ❌ Field-level permissions
- ❌ Audit trail creation

## When to Use `_system_update`

### ✅ APPROVED Use Cases

**1. System-Initiated Approval Workflows**
```python
# Context: Admin approved application → system creates membership
# Permissions: Validated at approval action
# Bypass: Fee override validation shouldn't block system processing

member_doc._system_update = True
frappe.logger().warning(
    f"SECURITY_AUDIT: Business rule bypassed for system workflow "
    f"user={frappe.session.user}, context=approval_workflow"
)
member_doc.save()
```

**2. Scheduled Jobs with Data Correction**
```python
# Context: Nightly job fixing historical data
# Permissions: Job runs as Administrator
# Bypass: Date validation shouldn't block historical corrections

for doc in frappe.get_all("DocType", ...):
    doc._system_update = True
    doc.historical_field = corrected_value
    doc.save()
```

**3. Migration Scripts**
```python
# Context: Database migration during upgrade
# Permissions: Migration runs in system context
# Bypass: New validation rules shouldn't break migration

doc._system_update = True
doc.new_required_field = default_value
doc.save()
```

### ❌ PROHIBITED Use Cases

**1. User-Initiated Operations**
```python
# ❌ WRONG: User action bypassing validation
@frappe.whitelist()
def update_member_fee(member_name, new_fee):
    member = frappe.get_doc("Member", member_name)
    member._system_update = True  # ❌ Bypasses user permission checks
    member.dues_rate = new_fee
    member.save()
```

**Correct Pattern:**
```python
@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def update_member_fee(member_name, new_fee):
    member = frappe.get_doc("Member", member_name)

    # Use secure_document_operation for user actions
    result = secure_document_operation(
        operation="save",
        doc=member,
        justification=f"User updated fee to {new_fee}",
        required_permissions=["Member:write", "Member:set_dues_rate"],
    )
```

**2. External API Endpoints**
```python
# ❌ WRONG: External system bypassing validation
@frappe.whitelist(allow_guest=True)
def webhook_update(data):
    doc = frappe.get_doc("DocType", data["name"])
    doc._system_update = True  # ❌ Security risk
    doc.update(data)
    doc.save()
```

**Correct Pattern: Validate at API layer, use normal save:**
```python
@frappe.whitelist(allow_guest=True)
@validate_webhook_signature
def webhook_update(data):
    # Validate business rules explicitly
    validate_webhook_data(data)

    doc = frappe.get_doc("DocType", data["name"])
    doc.update(data)
    doc.save()  # No bypass - validation runs normally
```

## Safety Requirements

When using `_system_update`, ALL of these are REQUIRED:

### 1. Comprehensive Audit Logging ✅
```python
member_doc._system_update = True

# REQUIRED: Log who, when, why, what
frappe.logger().warning(
    f"SECURITY_AUDIT: Business rule bypassed via _system_update "
    f"doc={member_doc.doctype}:{member_doc.name}, "
    f"user={frappe.session.user}, "
    f"context=specific_workflow_name, "
    f"bypassed_rule=fee_override_validation"
)
```

### 2. Clear Documentation ✅
```python
def save_method(doc):
    """
    SECURITY PATTERN: _system_update Usage

    Context: System-initiated approval workflow
    Bypass Type: Business rule (fee override check)
    Permission Validation: Done at API layer (approval action)
    Compensation: SECURITY_AUDIT logging
    """
    doc._system_update = True
```

### 3. Permission Validation at API Layer ✅
```python
@frappe.whitelist()
@high_security_api(operation_type=OperationType.WORKFLOW)
def approve_application(member_name):
    # Permission validated HERE (API layer)

    # Business logic uses _system_update for rule bypass
    result = MembershipCreationService.create_membership_on_approval(
        member_doc=member,
        # ... service internally uses _system_update
    )
```

## Comparison: Permission Validation vs Business Rule Bypass

| Aspect | `secure_document_operation` | `_system_update` |
|--------|----------------------------|------------------|
| **Validates Permissions** | ✅ Yes | ❌ No |
| **Bypasses Business Rules** | ❌ No | ✅ Yes |
| **Creates Audit Trail** | ✅ Yes | Requires manual logging |
| **Supports Rollback Coordination** | ❌ No | Via `save_with_rollback` |
| **Use Case** | User actions, API endpoints | System workflows |

## Decision Tree

```
Is this operation user-initiated?
├─ YES → Use secure_document_operation
│         (validates permissions, creates audit trail)
│
└─ NO → Is this a system workflow?
         ├─ YES → Can use _system_update IF:
         │         1. Permission validated at API layer
         │         2. Comprehensive audit logging added
         │         3. Clear documentation provided
         │
         └─ NO → Use normal .save()
                  (validation runs normally)
```

## Examples from Codebase

### ✅ Good: MembershipCreationService
```python
# Location: verenigingen/services/member/approval/membership_creation_service.py:492
# Context: Admin approved application (permission validated)
# Bypass: Fee override check (business rule)
# Compensation: SECURITY_AUDIT logging, comprehensive documentation

member_doc._system_update = True
frappe.logger().warning(f"SECURITY_AUDIT: ...")
save_with_rollback(member_doc, rollback_docs=[membership])
```

**Why Approved:**
- System-initiated workflow (approval processing)
- Permission validated when admin clicked "Approve"
- Comprehensive audit logging present
- Rollback coordination protects data integrity
- Clear documentation of pattern and rationale

## Review Checklist

Before approving `_system_update` usage:

- [ ] Is this a system-initiated workflow? (not user action)
- [ ] Are permissions validated at API/entry point layer?
- [ ] Is SECURITY_AUDIT logging comprehensive?
- [ ] Is the bypass type documented (which business rule)?
- [ ] Is the rationale clearly explained?
- [ ] Are there alternatives that don't require bypass?
- [ ] Is rollback/error handling robust?

## Related Patterns

- **Permission Validation**: Use `secure_document_operation`
- **Multi-Document Atomicity**: Use `save_with_rollback`
- **Both Needs**: See `docs/patterns/FUTURE_COMBINED_PATTERN.md`

## References

- Frappe Documentation: Document Flags and System Context
- Security Review: Phase 2B Post-Review Analysis
- Code: `verenigingen/services/member/approval/membership_creation_service.py:452-540`
- Code: `verenigingen/utils/document_save_retry.py:116-205`
