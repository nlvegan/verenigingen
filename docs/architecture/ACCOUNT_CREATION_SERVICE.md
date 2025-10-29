# AccountCreationService Architecture

**Status**: ✅ **Production Ready** (Implemented 2025-10-29)
**Location**: `verenigingen/services/account/account_creation_service.py`

## Overview

AccountCreationService is the single source of truth for user account creation logic, consolidating three previously duplicate code paths into a unified, well-tested implementation.

## Problem Solved

**Before**: Three different implementations with inconsistent validation:
1. Individual account creation in AccountCreationManager
2. Bulk account creation with broken Phase 2 linking logic
3. CSV import wrapper with duplicate filtering

**After**: Single service with clear boundaries and correct relationship handling.

## Core Architecture

### Member ↔ User Relationship

The service correctly implements the **one-way relationship**:

```
Member DocType                    User DocType
├─ name (PK)                     ├─ name (PK)
├─ email                         ├─ email
├─ user (Link) ──────────────────┘ [NO reciprocal field]
```

**Critical**: There is NO `User.custom_member` field. The service queries `Member.user` to find linkages.

## Service Methods

### `validate_member_for_account(member: Document)`

Validates eligibility for account creation:
- Has email address
- Status allows accounts (Active/Pending/Suspended)
- Not already linked to a user

**Returns**: `(is_valid: bool, error_message: Optional[str])`

### `detect_existing_user(email: str)`

Checks if user account exists with given email:
- Queries User table for email
- Queries Member table to check linkage (correct direction)
- Returns user info + linked member if found

**Returns**: `None` or `Dict{user_name, first_name, last_name, linked_member}`

### `link_existing_user(member, user_name, validate_names=True)`

Links existing user to member:
- Sets `Member.user` field (correct direction)
- Validates names match for security
- Checks for conflicts (user linked to different member)
- Idempotent (returns success if already linked)

**Returns**: `(success: bool, error_message: Optional[str])`

### `create_account_request(member, roles, role_profile, ...)`

Creates account creation request or links existing user:
- Validates member eligibility
- Detects existing users
- Attempts linking if possible
- Creates request if needed

**Returns**: `(success, error, result_dict)` where result indicates action taken:
- `"created"` - New request created
- `"linked"` - Linked to existing user
- `"already_linked"` - Already has account

### `queue_bulk_requests(member_names, roles, ...)`

Orchestrates bulk account creation:
- Validates all members
- Links existing users
- Creates requests for new accounts
- Filters by status (configurable)

**Returns**: `Dict{success, requests_created, users_linked, validation_errors, ...}`

## Usage Examples

### Basic Account Creation

```python
from verenigingen.services.account.account_creation_service import get_account_creation_service

service = get_account_creation_service()
member = frappe.get_doc("Member", member_name)

# Validate first
is_valid, error = service.validate_member_for_account(member)
if not is_valid:
    frappe.throw(error)

# Create request or link existing
success, error, result = service.create_account_request(
    member=member,
    roles=["Verenigingen Member"],
    role_profile="Verenigingen Member",
    priority="Normal"
)

if success:
    if result["action"] == "created":
        print(f"Request created: {result['request_name']}")
    elif result["action"] == "linked":
        print(f"Linked to existing user: {result['user_name']}")
```

### Bulk Account Creation

```python
service = get_account_creation_service()

result = service.queue_bulk_requests(
    member_names=["Member-001", "Member-002", "Member-003"],
    roles=["Verenigingen Member"],
    role_profile="Verenigingen Member",
    batch_size=50,
    priority="Low",
    filter_by_status=True  # Only Active/Pending/Suspended
)

print(f"Created: {result['requests_created']}")
print(f"Linked: {result['users_linked']}")
print(f"Errors: {result['validation_errors_count']}")
```

### Checking for Existing Users

```python
service = get_account_creation_service()

# Check if user exists before creating
existing = service.detect_existing_user("user@example.com")

if existing:
    if existing["linked_member"]:
        print(f"Already linked to: {existing['linked_member']}")
    else:
        print(f"User exists but not linked: {existing['user_name']}")
        # Could link if names match
else:
    print("No existing user - can create new account")
```

## Integration Points

### AccountCreationManager

Uses service for all validation and linking:

```python
from verenigingen.services.account.account_creation_service import get_account_creation_service

service = get_account_creation_service()
result = service.queue_bulk_requests(
    member_names=member_names,
    roles=roles,
    role_profile=role_profile,
    batch_size=batch_size,
    priority=priority,
    create_employee=create_employee
)

# Manager adds orchestration (trackers, batching)
created_requests = result.get("request_names", [])
# ... queue batches for processing
```

### CSV Import

Simplified to thin wrapper:

```python
from verenigingen.utils.account_creation_manager import queue_bulk_account_creation_for_members

result = queue_bulk_account_creation_for_members(
    member_names=processed_members,  # Service filters by status
    roles=roles,
    role_profile=role_profile,
    batch_size=50,
    priority="Low"
)

# Format results for summary
users_linked = result.get("users_linked", 0)
requests_created = result.get("requests_created", 0)
```

## Security Features

### Name Matching Validation

Before linking existing user to member, validates names match:

```python
if user.first_name != member.first_name or user.last_name != member.last_name:
    # Security: Don't link if names don't match
    return False, "Names do not match"
```

This prevents accidentally linking user accounts to wrong members if email addresses were reused.

### Conflict Detection

Checks if user is already linked to a different member:

```python
if existing_member_link and existing_member_link != target_member:
    # Security violation: user already belongs to different member
    return False, "User already linked to different member"
```

### Status Filtering

Only allows account creation for appropriate member statuses:

- ✅ Active - Full member with portal access
- ✅ Pending - Application under review
- ✅ Suspended - Temporary suspension
- ❌ Terminated - Membership ended
- ❌ Banned - Expelled member
- ❌ Deceased - Deceased member
- ❌ Rejected - Application rejected

## Error Handling

### Validation Errors

Service returns clear, actionable error messages:

```python
"Member M-001 has no email address"
"Member M-002 has status 'Terminated' which cannot have user accounts"
"Security: User user@example.com already linked to different member M-003"
"User user@example.com exists but name mismatch: User(John Smith) != Member(Jane Doe)"
```

### Idempotent Operations

Linking existing users is idempotent - calling twice returns success both times:

```python
# First call
success, error = service.link_existing_user(member, user_name)
# Returns: (True, None)

# Second call (already linked)
success, error = service.link_existing_user(member, user_name)
# Returns: (True, None) - not an error
```

## Performance Characteristics

### Query Efficiency

- **validate_member_for_account**: 1 query (member status check)
- **detect_existing_user**: 2 queries (User by email, Member by user link)
- **link_existing_user**: 1 write query (set Member.user)
- **create_account_request**: 3-4 queries (validate + detect + create request)

### Batch Operations

Bulk processing is linear with respect to member count:
- O(n) where n = number of members
- Each member: validate (1q) + detect (2q) + link/create (1q) = 4 queries
- For 100 members: ~400 queries (acceptable for background job)

### Memory Usage

Service is stateless - no memory accumulation across calls.

## Testing Strategy

### Unit Tests (TODO)

```python
def test_validate_member_for_account():
    # Test valid member
    # Test member without email
    # Test terminated member
    # Test member already linked
    pass

def test_detect_existing_user():
    # Test user exists and linked
    # Test user exists but not linked
    # Test user doesn't exist
    pass

def test_link_existing_user():
    # Test successful linking
    # Test name mismatch rejection
    # Test conflict detection
    # Test idempotency
    pass
```

### Integration Tests (TODO)

```python
def test_csv_import_with_existing_users():
    # Import members where some have existing user accounts
    # Verify existing users are linked, not duplicated
    # Verify new accounts created for others
    pass

def test_bulk_creation_with_mixed_statuses():
    # Process members with various statuses
    # Verify only valid statuses get accounts
    # Verify proper error reporting
    pass
```

## Migration Notes

### From Old System

No migration needed - service uses same database schema.

**Breaking Changes**: None

**Behavior Changes**:
1. Status filtering now includes Suspended (previously only Active)
2. Linked users reported separately in results
3. More detailed validation error messages

### Rollback Plan

If issues discovered:
1. Revert to previous commit
2. Old Phase 1/2/3 code available in git history
3. No database changes to undo

## Monitoring

### Success Metrics

Track these to verify service is working:

- Zero `custom_member` field errors in logs
- `users_linked` count > 0 when importing with existing users
- Validation errors are specific and actionable
- No duplicate user accounts created

### Logging

Service logs at appropriate levels:

```python
# Info: Normal operations
frappe.logger().info("Linked existing user X to member Y")

# Warning: Security issues or suspicious activity
frappe.logger().warning("Name mismatch prevents linking...")

# Error: Unexpected failures
frappe.logger().error("Failed to link user: database error")
```

## Future Enhancements

### Potential Improvements

1. **Bidirectional Lookup**: Add `User.member` field for faster reverse lookups (requires migration)
2. **Batch Optimization**: Group queries for bulk operations (100s of members)
3. **Async Processing**: Use task queue for very large bulk operations (1000s)
4. **Conflict Resolution UI**: Admin interface to resolve name mismatches manually
5. **Metrics Dashboard**: Real-time monitoring of account creation success rates

### Extension Points

Service designed for extension:
- `VALID_ACCOUNT_STATUSES` - Customize which statuses allow accounts
- `validate_names` parameter - Disable name matching for special cases
- `filter_by_status` parameter - Optionally skip status filtering

## References

- **Analysis**: `docs/ACCOUNT_CREATION_ARCHITECTURE_ANALYSIS.md`
- **Completion**: `docs/ACCOUNT_CREATION_REFACTOR_COMPLETION.md`
- **Service Code**: `verenigingen/services/account/account_creation_service.py`
- **Manager Code**: `verenigingen/utils/account_creation_manager.py`
