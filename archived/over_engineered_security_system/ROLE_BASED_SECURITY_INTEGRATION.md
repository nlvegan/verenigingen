# Role-Based Security Integration Guide

**Date**: September 15, 2025
**Status**: ✅ IMPLEMENTED
**Version**: 1.0

## Overview

This guide demonstrates how the new DocType-based Security Level Mapping system integrates with the existing API security framework to solve complex access control challenges like volunteer expense submissions.

## The Challenge: Volunteer Expense Submissions

**Problem**: Volunteers need to submit their own expenses but shouldn't access other financial operations. Traditional role hierarchies don't handle this context-dependent access well.

**Previous Approach** (hardcoded):
```python
# In Critical Operation Rules
"required_roles": "Verenigingen Member\nVerenigingen Volunteer\nVerenigingen Staff"
```

**Problems with Previous Approach**:
- Volunteers could potentially access other members' expenses
- No distinction between self-service and administrative operations
- Required code changes for role modifications
- Difficult to audit who has what access

## The Solution: Contextual Security Levels

### 1. Security Level Mapping DocType

```python
# Example mapping for volunteer expense submission
{
    "security_level": "Contextual",
    "operation_context": "self_service",
    "role_profile": "Verenigingen Volunteer",
    "context_validation_method": "validate_self_service_access"
}
```

### 2. Context Validator Implementation

```python
def validate_self_service_access(user: str, operation_data: Dict[str, Any]) -> bool:
    """Volunteers can only submit their own expenses"""
    target_member = operation_data.get('member_id')
    user_member = get_user_member_record(user)

    return user_member == target_member
```

### 3. Integration with API Security Framework

```python
# Updated API endpoint
@frappe.whitelist()
@contextual_api(
    security_level=SecurityLevel.CONTEXTUAL,
    operation_context="self_service",
    operation_type=OperationType.FINANCIAL
)
def submit_volunteer_expense(expense_data):
    """Submit volunteer expense with contextual validation"""

    # The security framework automatically:
    # 1. Checks if user has "Verenigingen Volunteer" role profile
    # 2. Validates via validate_self_service_access()
    # 3. Ensures user can only submit their own expenses

    return process_expense_submission(expense_data)
```

## Implementation Examples

### Financial Operations by Role

**Treasurers** (Critical Level):
```python
# Can process all payments
@critical_api(operation_context="financial")
def process_payment(payment_data):
    pass
```

**Board Members** (Contextual Level):
```python
# Can only approve expenses for their chapter
@contextual_api(
    security_level=SecurityLevel.CONTEXTUAL,
    operation_context="financial",
    context_validator="validate_chapter_specific_access"
)
def approve_chapter_expense(expense_id):
    pass
```

**Volunteers** (Contextual Level):
```python
# Can only submit their own expenses
@contextual_api(
    security_level=SecurityLevel.CONTEXTUAL,
    operation_context="self_service"
)
def submit_expense(expense_data):
    pass
```

### Member Data Operations

**Staff** (Medium Level):
```python
# Can access all member data for administrative support
@medium_security_api(operation_context="member_data")
def search_members(filters):
    pass
```

**Members** (Contextual Level):
```python
# Can only access their own member data
@contextual_api(
    security_level=SecurityLevel.CONTEXTUAL,
    operation_context="self_service"
)
def get_my_member_details():
    pass
```

## Business Benefits

### 1. Granular Access Control
- **Volunteers**: Can submit expenses but not approve them
- **Board Members**: Can approve chapter expenses but not other chapters
- **Treasurers**: Can process all payments and financial operations
- **Kascommissie**: Can audit but not modify financial records

### 2. Runtime Configuration
- System Managers can modify role mappings without code deployment
- New role profiles can be added through the UI
- Temporary access can be granted with effective dates

### 3. Audit Trail
- All security mapping changes are tracked
- Business justification required for each mapping
- Complete visibility into who has what access

### 4. RBAC Compliance
```python
# Security flows naturally from existing role structure:

# Kascommissie Role Profile → Verenigingen Kascommissie role → audit access
# Board Member Role Profile → Chapter-specific access via context validator
# Volunteer Role Profile → Self-service access via context validator
# Treasurer Role Profile → Full financial access
```

## Migration Path

### Phase 1: Add New DocTypes
1. Deploy Security Level Mapping DocType
2. Import initial fixture with sensible defaults
3. Deploy context validators

### Phase 2: Update API Endpoints
```python
# Before (hardcoded)
@frappe.whitelist()
def submit_expense():
    if not has_role(["Verenigingen Volunteer", "Verenigingen Staff"]):
        frappe.throw("Access denied")

# After (contextual)
@contextual_api(security_level=SecurityLevel.CONTEXTUAL, operation_context="self_service")
def submit_expense():
    # Security handled automatically by framework
```

### Phase 3: Remove Hardcoded Roles
1. Replace hardcoded role checks with security level decorators
2. Update Critical Operation Rules to use contextual security
3. Remove individual role requirements where appropriate

## Context Validator Patterns

### Self-Service Operations
```python
# Pattern: User can only act on their own data
contexts = ["expense_submission", "profile_update", "password_change"]
validator = "validate_self_service_access"
```

### Chapter-Specific Operations
```python
# Pattern: Board members limited to their chapter
contexts = ["expense_approval", "member_management", "event_creation"]
validator = "validate_chapter_specific_access"
```

### Team Leadership Operations
```python
# Pattern: Team leaders can manage their team
contexts = ["team_management", "volunteer_coordination", "project_approval"]
validator = "validate_team_leadership_access"
```

### Financial Threshold Operations
```python
# Pattern: Different approval limits by role
contexts = ["expense_approval", "invoice_creation", "payment_processing"]
validator = "validate_financial_threshold_access"
```

## Configuration Examples

### Adding New Role Profile Mapping
```json
{
    "security_level": "Medium",
    "operation_context": "financial",
    "role_profile": "Verenigingen Chapter Treasurer",
    "priority": 750,
    "business_justification": "Chapter treasurers need financial access for their specific chapter operations"
}
```

### Temporary Access Grant
```json
{
    "security_level": "High",
    "operation_context": "operations",
    "role_profile": "Verenigingen Special Project Manager",
    "effective_from": "2025-10-01",
    "effective_to": "2025-12-31",
    "business_justification": "Temporary elevated access for Q4 special project coordination"
}
```

## Security Validation

The system automatically validates:
- ✅ User has required role profile
- ✅ Mapping is currently effective (date-based)
- ✅ Context-specific business rules pass
- ✅ Additional conditions are met (if specified)
- ✅ Operation audit requirements are satisfied

## Conclusion

This DocType-based security mapping system transforms hardcoded role requirements into flexible, maintainable, auditable access control that flows naturally from your existing RBAC structure.

**Key Achievement**: Volunteers can now submit their own expenses securely without being able to access other financial operations - exactly what your business logic requires.

**Operational Benefit**: System Managers can now adjust security mappings through the UI without requiring developer intervention or code deployments.

**Governance Benefit**: Complete audit trail of who has what access, why they have it, and when the access was granted or modified.

---

**Next Steps**: Update existing API endpoints to use contextual decorators and deploy the Security Level Mapping fixtures to production.
