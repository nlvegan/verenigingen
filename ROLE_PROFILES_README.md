# Verenigingen Role Profiles Guide

This guide explains the role profiles available in the Verenigingen association management system and how to use them.

## Overview

Role profiles simplify user access management by bundling related roles together based on common user functions within the association.

## Available Role Profiles

### 1. Verenigingen Member
- **For**: All registered association members
- **Access**: Basic member portal, view own data
- **Use case**: Default profile for all members

### 2. Verenigingen Volunteer
- **For**: Active volunteers
- **Access**: Member access + volunteer activities, team participation
- **Use case**: Members who participate in volunteer activities

### 3. Verenigingen Team Leader
- **For**: Volunteer team leaders
- **Access**: Volunteer access + team management, expense approval
- **Use case**: Volunteers who lead teams or projects

### 4. Verenigingen Chapter Board
- **For**: Elected chapter board members
- **Access**: Chapter governance, member management for chapter
- **Use case**: Board members at chapter level

### 5. Verenigingen Treasurer
- **For**: Financial administrators and treasurers
- **Access**: Financial reports, payment processing, SEPA management
- **Use case**: Users responsible for financial administration

### 6. Verenigingen Chapter Administrator
- **For**: Chapter secretaries and administrators
- **Access**: Chapter member management, communications, events
- **Use case**: Administrative staff at chapter level

### 7. Verenigingen Manager
- **For**: National board and senior management
- **Access**: Organization-wide management, all modules
- **Use case**: Senior management positions

### 8. Verenigingen System Administrator
- **For**: IT administrators
- **Access**: Full system access
- **Use case**: Technical system administration

### 9. Verenigingen Auditor
- **For**: Internal auditors and compliance officers
- **Access**: Read-only access to all data for audit purposes
- **Use case**: Compliance and audit functions

## Installation

### 1. Install Fixtures

```bash
cd /home/frappe/frappe-bench
bench --site [site-name] migrate
bench --site [site-name] install-app verenigingen
```

### 2. Setup Role Profiles

```python
# In bench console
bench --site [site-name] console

# Import and run setup
from verenigingen.verenigingen.setup.role_profile_setup import install_fixtures, auto_assign_role_profiles

# Install fixtures
install_fixtures()

# Auto-assign profiles to existing users
auto_assign_role_profiles()
```

## Manual Assignment

### Via User Interface

1. Go to User List
2. Open a user record
3. Scroll to "Role Profile" section
4. Add the appropriate role profile
5. Save

### Via Code

```python
from verenigingen.verenigingen.setup.role_profile_setup import assign_role_profile_to_user

# Assign role profile to user
assign_role_profile_to_user("user@example.com", "Verenigingen Volunteer")
```

## Best Practices

1. **Start with the lowest required access** - Assign the minimum role profile needed
2. **Use single profile per user** - Avoid assigning multiple Verenigingen profiles
3. **Regular audits** - Review role assignments quarterly
4. **Document exceptions** - If custom roles are needed, document why

## Module Access

Each role profile has associated module access:

- **Basic Access**: Verenigingen, Portal, Communication
- **Volunteer Access**: + Projects, Support
- **Financial Access**: + Accounts, Banking, Selling
- **Management Access**: + CRM, Assets, Setup
- **Audit Access**: + Quality Management (read-only)

## Troubleshooting

### User can't access expected features
1. Check role profile assignment
2. Verify module profile is linked
3. Check individual role permissions
4. Clear cache: `bench --site [site-name] clear-cache`

### Role profile not appearing
1. Ensure fixtures are installed
2. Run: `bench --site [site-name] reload-doc verenigingen`
3. Check Role Profile list in system

### Permissions conflicts
1. Check for multiple role profiles
2. Review individual role assignments
3. Use Role Permission Manager to debug

## Security Notes

1. Role profiles are additive - they add roles, not remove them
2. System Manager role overrides most restrictions
3. Audit profiles should remain read-only
4. Financial roles should be carefully controlled

## Support

For issues or questions about role profiles:
1. Check this documentation
2. Review the role profile definitions in `/fixtures/role_profile.json`
3. Contact system administrator
