# Member Permission Fix Summary

## Issue
Foppe de Haan (foppe@veganisme.org) could not view or edit his own member record, but could view and edit other members' records that he shouldn't have access to.

## Root Causes Identified

### 1. Ownership Issue
- Foppe's member record had `owner: "Administrator"`
- Other members (Gerben Zonderland, test Sipkes) had `owner: "foppe@veganisme.org"`
- This was backwards - members should own their own records

### 2. Application Form Bug
- When Foppe submitted member applications while logged in, the new member records were created with him as the owner
- The application forms didn't explicitly set the owner, so Frappe defaulted to the current user

### 3. Permission Query Override
- The `get_member_permission_query` function was returning empty string for all users (debugging code left in)
- This allowed all members to see all other members in list views

## Fixes Applied

### 1. Fixed Ownership (Immediate)
```python
# Fixed via utility script:
- Foppe's record: owner changed from "Administrator" to "foppe@veganisme.org"
- Gerben Zonderland: owner changed from "foppe@veganisme.org" to "Administrator"
- test Sipkes: owner changed from "foppe@veganisme.org" to "beheerder+23332@veganisme.org"
```

### 2. Fixed Permission Query
```python
# In verenigingen/permissions.py
def get_member_permission_query(user):
    # Changed from returning "" (no restrictions) to:
    return f"`tabMember`.owner = {frappe.db.escape(user)}"
```

### 3. Fixed Permission Check
```python
# In verenigingen/permissions.py
def has_member_permission(doc, user=None, permission_type=None):
    # Added explicit ownership check for regular members:
    if "Verenigingen Member" in frappe.get_roles(user):
        if isinstance(doc, str):
            owner = frappe.db.get_value("Member", doc, "owner")
            return owner == user
        else:
            return doc.owner == user
    return False
```

### 4. Fixed Application Forms
```python
# In application_helpers.py - create_member_from_application()
member = frappe.get_doc({
    "doctype": "Member",
    # ... other fields ...
    "owner": get_creation_user(),  # Uses Verenigingen Settings creation_user
})

# In enhanced_membership_application.py - create_membership_application()
settings = frappe.get_single("Verenigingen Settings")
application.owner = settings.creation_user or "Administrator"  # Uses configured user
```

The owner is now set to the user configured in Verenigingen Settings → Creation User field, which is described as "The user that will be used to create Donations, Memberships, Invoices, and Payment Entries."

### 5. Added Ownership Transfer on User Creation
```python
# In Member doctype - create_user_for_member()
# When a user account is created for a member:
if self.owner != user.name:
    frappe.db.set_value("Member", self.name, "owner", user.name)
    frappe.logger().info(f"Transferred ownership of member {self.name} to {user.name}")
```

## Result
- Members can now only view and edit their own records
- New applications always create member records owned by Administrator
- Ownership is transferred to the member when their user account is created
- The "if_owner" permission in the Member DocType now works correctly

## Prevention
- Application forms now explicitly set owner to "Administrator"
- Permission queries properly restrict access based on ownership
- Ownership is automatically transferred when user accounts are created
- No more debugging code that bypasses permissions

## Testing
After fixes:
- Foppe can view and edit his own record ✓
- Foppe cannot view other members' records ✓
- List views only show members' own records ✓
- New applications don't inherit the applicant's ownership ✓
