# Workspace Cleanup Summary

## What was fixed:

### ✅ **Hidden Unwanted Modules**
The following ERPNext modules have been hidden from the front page:
- Buying, Selling, Stock, Manufacturing
- CRM, Assets, Support, Quality
- Marketplace, Education, Healthcare, Agriculture
- Loan Management, Frappe CRM
- Payroll, Shift & Attendance, Performance
- Employee Lifecycle, Recruitment
- Payables, Receivables, Financial Reports
- ALYF Banking

### ✅ **Cleaned Portal Menu**
- Removed duplicate "Projects" entries
- Removed unwanted portal items like "Newsletter"
- Kept only essential items:
  - Member Portal (with role requirement)
  - Volunteer Portal (with role requirement)
  - Issues & Support
  - My Addresses

### ✅ **Simplified Home Workspace**
The Home workspace now shows only:
- Quick Access shortcuts to Member Portal, Volunteer Portal, and Verenigingen
- Essential Tools cards for Members, Volunteers, and Reports

### ✅ **Removed Unwanted Shortcuts**
Deleted shortcuts to modules you don't need:
- Quotations, Sales Orders, Purchase Orders
- Delivery Notes, Stock Entries, Material Requests
- Timesheets, Manufacturing, Quality, etc.

## How to verify the changes:

1. **Refresh your browser** and clear cache (Ctrl+F5)
2. **Check the sidebar** - you should now see only:
   - Home
   - Verenigingen
   - Accounting (limited, for invoicing only)
   - HR (limited, for basic employee management)
3. **Check the front page** - should show clean interface without unwanted modules
4. **Portal menu** should be clean without duplicates

## Automatic application:

- This cleanup runs automatically after fresh installations
- A migration ensures existing installations get cleaned up
- Future installations will start with a clean workspace

## Manual cleanup (if needed):

If you still see unwanted modules, run:
```bash
bench --site dev.veganisme.net execute verenigingen.setup.workspace_setup.setup_clean_workspace
```

Then refresh your browser and clear cache.
