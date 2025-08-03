# Frappe/ERPNext Permissions System - Complete Guide

## Overview

Frappe's permission system operates on multiple layers that work together to control access to data. Understanding these layers and their interaction is crucial for proper security implementation.

## Permission Architecture Layers

### Layer 1: Role-Based DocType Permissions (JSON Configuration)
**Location**: `doctype_name.json` → `"permissions"` array
**Purpose**: Basic access control at the DocType level

```json
{
  "permissions": [
    {
      "create": 1,
      "delete": 1,
      "email": 1,
      "print": 1,
      "read": 1,
      "role": "System Manager",
      "share": 1,
      "write": 1
    }
  ]
}
```

**Permission Types**:
- `read`: View documents and lists
- `write`: Modify existing documents
- `create`: Create new documents
- `delete`: Delete documents
- `submit`: Submit submittable documents
- `cancel`: Cancel submitted documents
- `amend`: Amend cancelled documents
- `print`: Access print views
- `email`: Send emails
- `share`: Share documents with other users
- `export`: Export data
- `report`: Access reports
- `import`: Import data

**Critical Rules**:
1. **Order matters**: Frappe processes permissions sequentially
2. **First match wins**: If a user has multiple roles, the first matching permission applies
3. **No read = no access**: Without `"read": 1`, users cannot access the DocType at all
4. **Admin bypass**: System Manager role typically bypasses most restrictions

### Layer 2: User Permissions (Runtime Data Filtering)
**Purpose**: Restrict which specific records a user can access
**Configuration**: Setup → Users and Permissions → User Permissions

**Example**: User can only see Customer records for "Customer A" and "Customer B"

**Integration with DocType Permissions**:
```json
{
  "read": 1,
  "role": "Sales User",
  "user_permission_doctypes": "[\"Customer\"]"
}
```

### Layer 3: Permission Query Conditions (Server-Side SQL Filtering)
**Location**: `hooks.py` → `permission_query_conditions`
**Purpose**: Add SQL WHERE conditions to limit list views

```python
permission_query_conditions = {
    "Member": "verenigingen.permissions.get_member_permission_query"
}
```

**Function signature**:
```python
def get_member_permission_query(user=None):
    if not user:
        user = frappe.session.user

    # Return SQL WHERE condition as string
    return "`tabMember`.company = 'My Company'"
```

### Layer 4: Document-Level Permission Handlers (Individual Document Access)
**Location**: `hooks.py` → `has_permission`
**Purpose**: Control access to individual documents

```python
has_permission = {
    "Member": "verenigingen.permissions.has_member_permission"
}
```

**Function signature**:
```python
def has_member_permission(doc, user=None, permission_type="read"):
    if not user:
        user = frappe.session.user

    # Return True/False for access
    return doc.owner == user
```

## Permission Processing Flow

### List View Access (DocType List)
1. **Role Check**: Does user have `"read": 1` for this DocType?
2. **Query Conditions**: Apply `permission_query_conditions` to filter results
3. **User Permissions**: Apply user permission filters if configured
4. **Display**: Show filtered list to user

### Individual Document Access
1. **Role Check**: Does user have required permission (`read`/`write`/etc.)?
2. **Document Handler**: Call `has_permission` function if configured
3. **User Permissions**: Check if user has permission to this specific record
4. **Access**: Grant or deny access based on all checks

## Permission Interaction Rules

### Rule 1: Layered Security (AND Logic)
All layers must pass for access to be granted:
- DocType permission: `"read": 1` ✓
- Query conditions: Record matches SQL filter ✓
- Document handler: `has_permission()` returns True ✓
- User permissions: User has access to referenced records ✓

### Rule 2: Role Hierarchy vs Permission Specificity
- **System Manager**: Usually bypasses all restrictions
- **Admin Roles**: Often have unrestricted access
- **Specific Roles**: Subject to all permission layers

### Rule 3: Permission Conflicts Resolution
When user has multiple roles with different permissions:
1. **Most Permissive Wins**: If any role grants access, access is granted
2. **Order Dependency**: In some cases, JSON order in permissions array matters

## Common Permission Patterns

### Pattern 1: Owner-Only Access
```json
{
  "read": 1,
  "role": "Customer",
  "if_owner": 1
}
```

### Pattern 2: Template + Personal Records
```python
def get_permission_query_conditions(user=None):
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if user_member:
        return f"(is_template = 1 OR member = '{user_member}')"
    return "is_template = 1"
```

### Pattern 3: Hierarchical Access (Chapter/Team)
```python
def has_permission(doc, user=None, permission_type="read"):
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if user_member:
        # Check if user is in same chapter as document
        return check_chapter_membership(doc, user_member)
    return False
```

## Best Practices

### Security Best Practices
1. **Principle of Least Privilege**: Grant minimum required permissions
2. **Layer Defense**: Use multiple permission layers for sensitive data
3. **Explicit Deny**: Don't rely on implicit restrictions
4. **Regular Audits**: Periodically review permission configurations

### Performance Best Practices
1. **Query Conditions**: Use for list filtering (more efficient than document handlers)
2. **Document Handlers**: Use for complex business logic only
3. **User Permissions**: Limit scope to avoid performance impact
4. **Caching**: Consider caching for expensive permission checks

### Development Best Practices
1. **Test All Roles**: Verify permissions work for each role
2. **Test Edge Cases**: Empty results, no permissions, etc.
3. **Document Permissions**: Clearly document permission logic
4. **Version Control**: Track permission changes carefully

## Debugging Permission Issues

### Step 1: Check DocType Permissions
```python
meta = frappe.get_meta("DocType Name")
for perm in meta.permissions:
    if perm.role == "Target Role":
        print(f"Read: {perm.read}, Write: {perm.write}")
```

### Step 2: Test Query Conditions
```python
from module.permissions import get_permission_query
condition = get_permission_query("user@example.com")
sql = f"SELECT name FROM `tabDocType` WHERE {condition}"
results = frappe.db.sql(sql)
```

### Step 3: Test Document Handler
```python
from module.permissions import has_permission
doc = frappe.get_doc("DocType", "DOC-001")
access = has_permission(doc, "user@example.com", "read")
```

### Step 4: Check User Permissions
```python
user_perms = frappe.db.sql("""
    SELECT allow, for_value
    FROM `tabUser Permission`
    WHERE user = %s AND allow = %s
""", ("user@example.com", "Reference DocType"))
```

## Common Pitfalls

### Pitfall 1: Permission Order Dependency
**Problem**: Later permissions in JSON array never processed
**Solution**: Order permissions from most restrictive to least restrictive

### Pitfall 2: Missing Read Permission
**Problem**: Custom handlers not called when `"read": 0`
**Solution**: Always grant basic `"read": 1` and use handlers for filtering

### Pitfall 3: Performance Issues
**Problem**: Document handlers called for every record in large lists
**Solution**: Use query conditions for list filtering, handlers for individual access

### Pitfall 4: User Permission Complexity
**Problem**: Complex user permission setups become unmaintainable
**Solution**: Use custom query conditions or document handlers instead

## Permission Testing Strategy

### Unit Tests
- Test each permission layer independently
- Verify edge cases (no permissions, empty results)
- Test with different user roles

### Integration Tests
- Test complete permission flow
- Verify list and document access
- Test permission interactions

### Security Tests
- Attempt unauthorized access
- Test privilege escalation scenarios
- Verify data isolation between users/chapters

This comprehensive permission system ensures data security while maintaining flexibility for complex business requirements.
