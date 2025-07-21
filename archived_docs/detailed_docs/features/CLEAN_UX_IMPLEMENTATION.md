# Clean UX Implementation - Verenigingen App

This document explains how the Verenigingen app provides a clean, association-focused user experience by permanently hiding unwanted ERPNext modules and features.

## Permanent Solution Overview

The implementation uses multiple layers to ensure a consistent, clean experience across all deployments:

### 1. **Hooks-based Configuration** (`hooks.py`)

#### Portal Menu Restriction
```python
standard_portal_menu_items = [
    {"title": "Member Portal", "route": "/member_portal", "reference_doctype": "", "role": "Verenigingen Member"},
    {"title": "Volunteer Portal", "route": "/volunteer_portal", "reference_doctype": "", "role": "Volunteer"}
]
```
- Only shows association-relevant portal items
- Removes duplicates and unwanted items like Newsletter, Projects, etc.

#### Module Restrictions
```python
hidden_modules = [
    "Buying", "Selling", "Stock", "Manufacturing", "CRM", "Assets",
    "Support", "Quality", "Marketplace", "Education", "Healthcare",
    "Agriculture", "Loan Management", "Payroll", "Recruitment",
    "Performance", "Employee Lifecycle", "Shift & Attendance"
]

restricted_doctypes = [
    "Quotation", "Sales Order", "Purchase Order", "Delivery Note",
    "Purchase Receipt", "Stock Entry", "Material Request", "Timesheet",
    "Project", "Newsletter", "Lead", "Opportunity", "Customer",
    "Supplier", "Item", "Warehouse", "BOM", "Work Order"
]
```

#### Permission Overrides
```python
has_permission = {
    # ... existing permissions ...
    "Quotation": "verenigingen.utils.module_restrictions.has_permission",
    "Sales Order": "verenigingen.utils.module_restrictions.has_permission",
    # ... other restricted doctypes ...
}
```

#### Sidebar Override
```python
override_whitelisted_methods = {
    "frappe.desk.desktop.get_workspace_sidebar_items": "verenigingen.overrides.sidebar.get_workspace_sidebar_items"
}
```

### 2. **Permission System** (`utils/module_restrictions.py`)

#### Role-Based Access Control
- **Administrators**: See everything (no restrictions)
- **System Managers**: See association modules + basic accounting/HR
- **Regular Users**: See only association-specific modules

#### Dynamic Permission Filtering
```python
def has_permission(doctype, ptype="read", doc=None, user=None):
    # Allow administrators full access
    if user == "Administrator" or frappe.session.user == "Administrator":
        return _has_permission(doctype, ptype, doc, user)

    # Check if user has System Manager role
    user_roles = frappe.get_roles(user or frappe.session.user)
    if "System Manager" in user_roles:
        return _has_permission(doctype, ptype, doc, user)

    # Restrict access to unwanted doctypes for regular users
    if doctype in RESTRICTED_DOCTYPES:
        return False

    return _has_permission(doctype, ptype, doc, user)
```

### 3. **Sidebar Override** (`overrides/sidebar.py`)

Permanently filters workspace sidebar items based on user permissions:

```python
def get_workspace_sidebar_items():
    result = _get_workspace_sidebar_items()

    if isinstance(result, dict) and "pages" in result:
        result["pages"] = filter_workspace_pages(result["pages"])

    return result
```

### 4. **Client-side Cleanup** (`public/js/sidebar_customization.js`)

Provides additional cleanup for any items that might slip through:

```javascript
const RESTRICTED_ITEMS = [
    'Newsletter', 'Projects', 'Quotations', 'Orders', 'Invoices',
    'Shipments', 'Timesheets', 'Material Request', 'Stock',
    'Manufacturing', 'CRM', 'Assets', 'Support', 'Quality',
    'Buying', 'Selling', 'Payroll', 'Recruitment', 'Performance',
    'Employee Lifecycle', 'Shift & Attendance', 'Issues & Support'
];

function cleanSidebar() {
    if (shouldShowRestrictedItems()) {
        return; // Don't hide anything for admins
    }

    RESTRICTED_ITEMS.forEach(item => {
        // Remove from various UI locations
        $(`.sidebar-item[data-label="${item}"], .sidebar-item[title="${item}"]`).remove();
        $(`.workspace-sidebar-item:contains("${item}")`).remove();
        // ... etc
    });
}
```

## What Users See

### **Regular Association Users**
- Sidebar: Home, Verenigingen
- Portal: Member Portal, Volunteer Portal
- No access to: Commercial, manufacturing, or complex HR modules

### **System Managers**
- Sidebar: Home, Verenigingen, Accounting (basic), HR (basic)
- Full access to association management
- Limited access to essential business functions

### **Administrators**
- Full access to all modules (no restrictions)
- Can access ERPNext modules if needed for system administration

## Deployment Benefits

### ✅ **Consistent Experience**
- Works on all deployments automatically
- No manual configuration required
- Same clean UX everywhere

### ✅ **Role-Based Flexibility**
- Admins can still access everything if needed
- System managers get appropriate access
- Regular users get clean, focused interface

### ✅ **Maintainable**
- All restrictions defined in code
- Version controlled
- Easy to modify or extend

### ✅ **Performance**
- No database queries for restrictions
- Efficient filtering
- Client-side optimizations

## Adding/Removing Restrictions

### To Hide Additional Modules:
1. Add to `hidden_modules` list in `hooks.py`
2. Add to `RESTRICTED_ITEMS` in `sidebar_customization.js`
3. Add permission override in `has_permission` dict

### To Allow Additional Access:
1. Remove from restriction lists
2. Add to `get_permitted_modules()` for appropriate roles
3. Update client-side filtering logic

## Files Modified/Created

### Core Implementation:
- `hooks.py` - Main configuration
- `utils/module_restrictions.py` - Permission system
- `overrides/sidebar.py` - Sidebar filtering
- `public/js/sidebar_customization.js` - Client-side cleanup

### Supporting Files:
- `CLEAN_UX_IMPLEMENTATION.md` - This documentation
- Various workspace configuration files

## Testing

The implementation has been tested to ensure:
- ✅ Clean sidebar for regular users
- ✅ Appropriate access for different roles
- ✅ No interference with admin functions
- ✅ Proper permission enforcement
- ✅ Consistent behavior across browsers
- ✅ Works with dynamic content loading

This provides a permanent, maintainable solution that will work consistently across all deployments of the Verenigingen app.
