# Verenigingen Role Profiles Guide

This document describes the 11 role profiles defined in `verenigingen/fixtures/role_profile.json` and their intended use cases.

## Overview

Role profiles in Verenigingen provide appropriate access levels for different types of users in an association management system. Each profile bundles specific Frappe roles tailored to the user's responsibilities.

## Role Profiles

### 1. Verenigingen Member

- **For**: Regular association members
- **Roles**: Verenigingen Member, All
- **Use Case**: Members who need to manage their own profile, view membership status, and access member resources

### 2. Verenigingen Volunteer

- **For**: Active volunteers participating in teams or projects
- **Roles**: Verenigingen Member, Verenigingen Volunteer, Employee, Employee Self Service, Projects User
- **Use Case**: Volunteers who participate in team activities, submit expenses, and track project work

### 3. Verenigingen Team Leader

- **For**: Volunteers leading teams or specific projects
- **Roles**: Verenigingen Member, Verenigingen Volunteer, Employee, Employee Self Service, Projects User, Expense Approver
- **Use Case**: Team leads who approve expenses and coordinate team activities

### 4. Verenigingen Chapter Board Member

- **For**: Elected board members of local chapters
- **Roles**: Verenigingen Member, Verenigingen Chapter Board Member, Verenigingen Volunteer, Employee, Employee Self Service, Projects User, Projects Manager, Expense Approver, Accounts User, Sales User, Purchase User
- **Use Case**: Chapter governance, financial oversight, volunteer coordination at the chapter level

### 5. Verenigingen National Board Member

- **For**: Members of the national board
- **Roles**: Verenigingen Member, Verenigingen Staff, Verenigingen Chapter Board Member, Verenigingen Volunteer, Employee, Employee Self Service, Projects User, Projects Manager, Expense Approver, Website Manager, Auditor
- **Module Profile**: Verenigingen Management Access
- **Use Case**: National oversight, governance, audit access, website management

### 6. Verenigingen Treasurer

- **For**: Chapter treasurers and financial officers
- **Roles**: Verenigingen Member, Verenigingen Staff, Accounts Manager, Purchase Manager, Sales Manager, Stock Manager, Verenigingen Chapter Board Member, Verenigingen National Board Member, Projects Manager, Employee, Employee Self Service, Verenigingen Financial Manager, Dashboard Manager, Expense Approver
- **Use Case**: Full financial management including payments, reconciliation, reporting, and budgets

### 7. Verenigingen Staff

- **For**: National office staff and support team members
- **Roles**: Verenigingen Staff, Verenigingen Member, Employee, Employee Self Service, Projects User, Support Team, Accounts User, Sales User, Purchase User
- **Use Case**: Day-to-day administrative and support operations

### 8. Verenigingen Administrator

- **For**: Association administrators managing the application
- **Roles**: Verenigingen Administrator, Verenigingen Member, Verenigingen Staff, Employee, System Manager, Accounts Manager, Sales Manager, Purchase Manager, Projects User
- **Use Case**: Application administration, user management, configuration

### 9. Verenigingen System Administrator

- **For**: IT administrators with full system access
- **Roles**: Verenigingen Administrator, System Manager, Administrator, All
- **Use Case**: Full system access, technical administration, infrastructure management

### 10. Verenigingen Auditor

- **For**: Internal auditors and compliance officers
- **Roles**: Verenigingen Member, Verenigingen Volunteer, Employee, Auditor
- **Use Case**: Read-only access to financial and governance data for audit and compliance

### 11. Verenigingen Webhook User

- **For**: Service accounts handling webhook and automation integrations
- **Roles**: Verenigingen Webhook User, Accounts User, Sales User
- **Use Case**: Processing incoming webhooks (e.g., Mollie payment notifications) and background automation

## Role Count Summary

| # | Role Profile | Role Count |
|---|-------------|-----------|
| 1 | Verenigingen Member | 2 |
| 2 | Verenigingen Volunteer | 5 |
| 3 | Verenigingen Team Leader | 6 |
| 4 | Verenigingen Chapter Board Member | 11 |
| 5 | Verenigingen National Board Member | 11 |
| 6 | Verenigingen Treasurer | 14 |
| 7 | Verenigingen Staff | 9 |
| 8 | Verenigingen Administrator | 9 |
| 9 | Verenigingen System Administrator | 4 |
| 10 | Verenigingen Auditor | 4 |
| 11 | Verenigingen Webhook User | 3 |

## API Security Level Mapping

Role profiles are mapped to API security levels in `verenigingen/utils/security/authorization_policy.py`. See [security/ROLE_PROFILE_INTEGRATION_GUIDE.md](security/ROLE_PROFILE_INTEGRATION_GUIDE.md) for details.

| Role Profile | Security Levels |
|-------------|----------------|
| Verenigingen System Administrator | CRITICAL, HIGH, MEDIUM, LOW |
| Verenigingen Administrator | CRITICAL, HIGH, MEDIUM, LOW |
| Verenigingen Treasurer | CRITICAL, HIGH, MEDIUM |
| Verenigingen National Board Member | CRITICAL, HIGH, MEDIUM |
| Verenigingen Staff | HIGH, MEDIUM, LOW |
| Verenigingen Chapter Board Member | HIGH, MEDIUM, LOW |
| Verenigingen Auditor | MEDIUM, LOW |
| Verenigingen Volunteer | MEDIUM, LOW |
| Verenigingen Team Leader | LOW |
| Verenigingen Member | LOW |
| Verenigingen Webhook User | HIGH, MEDIUM, LOW, PUBLIC |

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
2. **Use role profiles consistently** - Avoid mixing individual role assignments with profiles
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

### User cannot access expected features

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
