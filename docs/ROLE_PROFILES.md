# Verenigingen Role Profiles Guide

This document describes the role profiles available in the Verenigingen app and their intended use cases.

## Overview

Role profiles in Verenigingen are designed to provide appropriate access levels for different types of users in an association management system. Each profile includes specific roles and module access tailored to the user's responsibilities.

## Role Profiles

### 1. **Verenigingen Member**
- **For**: Regular association members
- **Access**: Basic member portal, view their own information, communication
- **Modules**: Verenigingen, Portal, Communication, Desk
- **Use Case**: Members who need to manage their own profile, view membership status, and access member resources

### 2. **Verenigingen Volunteer**
- **For**: Active volunteers participating in teams or projects
- **Access**: Member access + project participation, expense submission
- **Modules**: Adds Projects, Support, Activity
- **Key Features**:
  - Submit volunteer expenses
  - Participate in team activities
  - Access project documentation
  - Track volunteer hours

### 3. **Verenigingen Team Leader**
- **For**: Volunteers leading teams or specific projects
- **Access**: Volunteer access + team management, expense approval
- **Additional Roles**: Expense Approver, Leave Approver
- **Key Features**:
  - Approve team member expenses
  - Manage project tasks
  - Coordinate team activities
  - Access HR features for team management

### 4. **Verenigingen Chapter Board**
- **For**: Elected board members of local chapters
- **Access**: Enhanced volunteer access + chapter oversight
- **Key Features**:
  - View chapter membership
  - Approve volunteer activities
  - Access chapter reports
  - Participate in governance

### 5. **Verenigingen Treasurer**
- **For**: Chapter treasurers and financial officers
- **Access**: Limited financial management capabilities
- **Modules**: Accounts, Banking, Selling
- **Key Features**:
  - Process member payments
  - Bank reconciliation
  - Generate financial reports
  - Manage chapter budgets

### 6. **Verenigingen Chapter Administrator**
- **For**: Chapter secretaries and operational administrators
- **Access**: Chapter operations and communications
- **Additional Modules**: Website, Newsletter, Blog
- **Key Features**:
  - Manage chapter website content
  - Send member communications
  - Organize events
  - Maintain member records

### 7. **Verenigingen Communications Officer** (NEW)
- **For**: Dedicated communications staff
- **Access**: Full communications and content management
- **Key Features**:
  - Manage all website content
  - Social media management
  - Newsletter campaigns
  - Blog and news updates

### 8. **Verenigingen Event Coordinator** (NEW)
- **For**: Event organizers and coordinators
- **Access**: Project and event management tools
- **Key Features**:
  - Create and manage events
  - Coordinate volunteers
  - Track event participation
  - Generate event reports

### 9. **Verenigingen Manager**
- **For**: National office staff and regional managers
- **Access**: Comprehensive management capabilities
- **Key Features**:
  - Full project management
  - Account management
  - HR functions
  - Support team access
  - Advanced reporting

### 10. **Verenigingen Finance Manager** (NEW)
- **For**: Senior financial staff
- **Access**: Full financial management
- **Additional Modules**: Buying, Stock, Assets
- **Key Features**:
  - Complete accounting access
  - Purchase management
  - Asset tracking
  - Financial planning

### 11. **Verenigingen System Administrator**
- **For**: IT administrators and system managers
- **Access**: Full system access
- **Key Features**:
  - All modules and features
  - System configuration
  - User management
  - Technical administration

### 12. **Verenigingen Auditor**
- **For**: Internal auditors and compliance officers
- **Access**: Read-only access to financial and governance data
- **Key Features**:
  - View all financial records
  - Access audit trails
  - Generate compliance reports
  - Quality management tools

### 13. **Verenigingen Guest** (NEW)
- **For**: Non-members and public users
- **Access**: Public website only
- **Key Features**:
  - View public content
  - Submit membership applications
  - Make donations

## Module Access Summary

### Excluded Modules (Not relevant for associations):
- Manufacturing
- Education
- Healthcare
- Agriculture
- Non Profit (replaced by Verenigingen)
- Hospitality
- Distribution

### Conditionally Included Modules:
- **Stock**: Only for Finance Managers (for inventory if needed)
- **Buying**: Only for Finance Managers (for procurement)
- **Assets**: For Managers and Finance roles (equipment tracking)
- **Payroll**: For Treasurers and Managers (if staff employed)
- **HR**: For Team Leaders and Managers

### Core Modules for All Members:
- Verenigingen (custom association management)
- Portal (member self-service)
- Communication (messaging and notifications)
- Desk (basic navigation)

## Implementation

### Installing Role Profiles

```bash
# Import all fixtures including role profiles
bench --site [sitename] import-fixtures --app verenigingen

# Or specifically import role profiles
bench --site [sitename] import-doc ~/frappe-bench/apps/verenigingen/verenigingen/fixtures/role_profile.json
bench --site [sitename] import-doc ~/frappe-bench/apps/verenigingen/verenigingen/fixtures/module_profile.json
```

### Auto-Assignment Script

Use the provided script to automatically assign role profiles based on existing user roles:

```python
# From bench console
from verenigingen.setup.role_profile_setup import auto_assign_role_profiles
auto_assign_role_profiles()
```

### Manual Assignment

1. Go to User List
2. Select a user
3. In the Role Profile section, add the appropriate Verenigingen role profile
4. Save

## Best Practices

1. **Start with the minimum required access** - Users can always be upgraded to higher profiles
2. **Use role profiles consistently** - Don't mix individual role assignments with profiles
3. **Regular review** - Audit role assignments quarterly
4. **Document exceptions** - If custom roles are needed, document why
5. **Test thoroughly** - Verify access levels before rolling out to users

## Customization

If you need to modify role profiles:

1. Export current profiles: `bench --site [sitename] export-fixtures --app verenigingen`
2. Edit the JSON files in `verenigingen/fixtures/`
3. Re-import: `bench --site [sitename] import-fixtures --app verenigingen`
4. Test with sample users before widespread deployment

## Troubleshooting

### User can't access expected features
1. Check if role profile is properly assigned
2. Verify module profile is linked to role profile
3. Clear cache: `bench --site [sitename] clear-cache`
4. Check individual role permissions

### Too much access
1. Review assigned role profiles (users might have multiple)
2. Check for individually assigned roles outside profiles
3. Verify module profile restrictions are working

### Module not visible
1. Check if module is included in the module profile
2. Verify the module is installed and enabled
3. Check module-level permissions
