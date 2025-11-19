# User Type Assignment System

## Overview

The Verenigingen system implements a granular user type assignment system that distinguishes between regular members (who need portal access) and volunteers (who need full system access).

## User Type Logic

### Website User (Default for Members)
- **Assigned to:** Regular members who are not volunteers
- **Access level:** Portal access only - can view their own information, payment history, membership details
- **Permissions:** Limited to member portal features
- **Use case:** Members who want to track their membership but don't need system access

### System User (For Volunteers)
- **Assigned to:**
  - Members who express interest in volunteering AND have their volunteer record activated
  - Direct volunteer record creation
- **Access level:** Full system access for volunteer operations
- **Permissions:** Can access volunteer expense claims, activities, team assignments
- **Use case:** Active volunteers who need to track hours, submit expenses, manage activities

## Implementation Details

### Account Creation Flow

#### 1. Member Application Approval
```python
# When a member is approved:
# - User account created with Website User type
# - Roles: ["Verenigingen Member"]
# - Role Profile: "Verenigingen Member"
```

**Location:** `account_creation_manager.py:204-207`
```python
# Determine user type based on request type
# Members get Website User for portal access
# Volunteers get System User for full system access
user_type = "System User" if self.request.request_type == "Volunteer" else "Website User"
```

#### 2. Volunteer Activation (Upgrade Path)
When a member who already has a Website User account becomes a volunteer:

**Location:** `membership_application_review.py:652-668`
```python
# Upgrade user account from Website User to System User for volunteer access
if member.user:
    try:
        from verenigingen.utils.account_creation_manager import upgrade_member_to_volunteer_user

        upgrade_result = upgrade_member_to_volunteer_user(member.name)
        if upgrade_result.get("success"):
            frappe.logger().info(
                f"User account upgrade for volunteer: {upgrade_result.get('message')}"
            )
```

#### 3. Direct Volunteer Creation
When a volunteer record is created directly (not from member):

**Location:** `account_creation_manager.py:738-752`
```python
# Create request with volunteer-specific roles
request = frappe.get_doc({
    "doctype": "Account Creation Request",
    "request_type": "Volunteer",  # This triggers System User type
    "source_record": volunteer_name,
    # ...
})

# Add volunteer-specific roles
volunteer_roles = ["Verenigingen Volunteer", "Employee", "Employee Self Service"]
```

### Upgrade Function

The `upgrade_member_to_volunteer_user()` function handles the transition from Website User to System User:

**Location:** `account_creation_manager.py:1370-1427`

**Features:**
- Permission validation before upgrade
- Idempotency check (skips if already System User)
- Comprehensive logging
- Error handling with graceful degradation

**Usage:**
```python
from verenigingen.utils.account_creation_manager import upgrade_member_to_volunteer_user

result = upgrade_member_to_volunteer_user("Member-001")
# Returns:
# {
#     "success": True,
#     "message": "User account upgraded to System User for volunteer access",
#     "user": "user@example.com",
#     "previous_type": "Website User"
# }
```

## Security Considerations

### Permission Requirements
- **Creating user accounts:** Requires `User` create permission
- **Upgrading user types:** Requires `User` write permission
- **All operations:** Subject to chapter-based security validation

### Audit Trail
- All user type assignments logged via `frappe.logger()`
- Account Creation Request tracks complete lifecycle
- User document tracks modification history

### Role Assignment
**Website User roles:**
- `Verenigingen Member` - Portal access
- Limited module access via module profile

**System User roles (additional):**
- `Verenigingen Volunteer` - Volunteer operations
- `Employee` - Expense claim functionality
- `Employee Self Service` - Self-service features

## Module Profile Configuration

### Member Module Access (Website User)
**Allowed Modules:**
- `Verenigingen` - Association management features
- `Core` - Basic Frappe functionality
- `Desk` - Desk interface access
- `Home` - Home page access

**Blocked Modules:** All others (ERPNext, Banking, CRM, etc.)

**Configuration:** Set via `set_member_user_modules()` at line 315 of `account_creation_manager.py`

### Volunteer Module Access (System User)
**Allowed Modules (in addition to member modules):**
- `HRMS` - HR Management System for expense claims
- `HR` - Legacy HR module access

**Configuration:** Automatically expanded during volunteer upgrade via `upgrade_member_to_volunteer_user()`

**Location:** `account_creation_manager.py:1412-1440`

### Verification

To check a user's module access:
```python
user = frappe.get_doc("User", "user@example.com")
blocked = [row.module for row in user.block_modules]
all_modules = frappe.get_all("Module Def", pluck="name")
allowed = [m for m in all_modules if m not in blocked]
print(f"Allowed modules: {allowed}")
```

## Testing

### Test Coverage
1. **Member user type test:** Verify Website User assignment
2. **Volunteer upgrade test:** Verify upgrade from Website User to System User
3. **Direct volunteer test:** Verify System User assignment for direct creation

**Test location:** `/home/frappe/frappe-bench/apps/verenigingen/test_user_type_assignment.py`

### Manual Testing Steps

#### Test 1: Regular Member
1. Create member application without volunteer interest
2. Approve application
3. Verify user account has `user_type = "Website User"`

#### Test 2: Member to Volunteer Upgrade
1. Create member with `interested_in_volunteering = True`
2. Approve application (creates Website User)
3. Activate volunteer record
4. Verify user upgraded to `user_type = "System User"`

#### Test 3: Direct Volunteer
1. Create volunteer record directly
2. Create user account for volunteer
3. Verify user has `user_type = "System User"`

## Migration Considerations

### Existing Users
Existing members with System User accounts will retain their access level. The system only assigns user types during new account creation.

**To retroactively apply the policy:**
```python
# Get all members without volunteer records who have System User accounts
members = frappe.get_all("Member",
    filters={
        "user": ["!=", ""],
        "volunteer_record": ["in", ["", None]]
    },
    fields=["name", "user"]
)

for member in members:
    user = frappe.get_doc("User", member.user)
    if user.user_type == "System User":
        # Check if they should be downgraded
        volunteer = frappe.db.exists("Volunteer", {"member": member.name})
        if not volunteer:
            # Downgrade to Website User
            user.user_type = "Website User"
            user.save()
            print(f"Downgraded {member.name} to Website User")
```

⚠️ **Warning:** Run migration script carefully with proper backup and testing.

## Troubleshooting

### Issue: Member has System User but shouldn't
**Diagnosis:** Check if volunteer record exists:
```python
frappe.db.get_value("Volunteer", {"member": "Member-001"}, "name")
```

**Fix:** If no volunteer record, downgrade manually:
```python
user = frappe.get_doc("User", "user@example.com")
user.user_type = "Website User"
user.save()
```

### Issue: Volunteer still has Website User
**Diagnosis:** Check if upgrade was called:
```bash
# Check logs for upgrade messages
bench --site dev.veganisme.net console
frappe.db.get_list("Error Log", filters={"error": ["like", "%upgrade%"]})
```

**Fix:** Manually trigger upgrade:
```python
from verenigingen.utils.account_creation_manager import upgrade_member_to_volunteer_user
result = upgrade_member_to_volunteer_user("Member-001")
```

## Related Documentation

- `CLAUDE.md` - Account Creation Security Guidelines
- `account_creation_manager.py` - Implementation details
- `membership_application_review.py` - Approval workflow
- `ACCOUNT_CREATION_TEST_SUMMARY.md` - Test suite documentation
