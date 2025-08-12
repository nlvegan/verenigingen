# Kascommissie (Audit Committee) Fixtures Setup

## Overview

The kascommissie (audit committee) fixtures provide a complete solution for establishing an audit committee with proper access to the accounting suite for financial oversight and compliance monitoring.

## Created Fixtures

### 1. Team Role: `kascommissie_auditor`
**File:** `verenigingen/fixtures/team_role.json`

- **Role Name:** Kascommissie Auditor
- **Description:** Audit committee member with read-only access to all financial records, accounting transactions, and compliance reports
- **Permissions Level:** Coordinator
- **Unique:** No (multiple auditors allowed)
- **Active:** Yes

### 2. Team: `kascommissie`
**File:** `verenigingen/fixtures/team.json`

- **Team Name:** Kascommissie
- **Type:** Committee
- **Scope:** Association-wide
- **Status:** Active
- **Responsibilities:** Financial oversight, audit functions, compliance monitoring

### 3. System Role: `Verenigingen Kascommissie`
**File:** `verenigingen/fixtures/role.json`

- **Role Name:** Verenigingen Kascommissie
- **Desk Access:** Yes
- **Home Page:** /app/verenigingen

### 4. Role Profile: `Verenigingen Kascommissie`
**File:** `verenigingen/fixtures/role_profile_kascommissie.json`

Combined roles for comprehensive audit access:
- **Verenigingen Member** - Basic app access
- **Employee** - Employee module access
- **Auditor** - Built-in ERPNext audit permissions
- **Accounts User** - Read access to accounting data
- **Verenigingen Kascommissie** - Custom role for specific permissions

## Audit Access Capabilities

The kascommissie role profile provides read-only access to:

### Financial Data
- Bank transactions and reconciliation
- Payment entries and requests
- Sales and purchase invoices
- Journal entries
- Account balances and statements

### SEPA & Payment Processing
- SEPA mandates and batch processing
- Direct debit transactions
- Payment retry logs
- Member payment histories

### E-Boekhouden Integration
- Migration logs and status
- Account mappings
- Import/export records
- Synchronization audit trails

### Membership Financial Data
- Membership dues schedules
- Payment collections
- Overdue payment reports
- Financial compliance reports

### Volunteer Expenses
- Expense claims and approvals
- Reimbursement tracking
- Budget utilization reports

## Installation

1. **Install Fixtures:**
   ```bash
   bench --site [sitename] install-app verenigingen
   ```

2. **Load Specific Fixtures:**
   ```bash
   bench --site [sitename] migrate
   ```

3. **Verify Installation:**
   - Check that "Kascommissie" team exists
   - Verify "Kascommissie Auditor" team role is available
   - Confirm "Verenigingen Kascommissie" role profile is created

## Usage

### Setting Up Audit Committee

1. **Create the Team:**
   - Navigate to Teams list
   - Find or create "Kascommissie" team
   - Set team lead and members

2. **Assign Users:**
   - Add team members with "Kascommissie Auditor" role
   - Assign "Verenigingen Kascommissie" role profile to users

3. **Access Verification:**
   - Users should have read access to financial data
   - Cannot modify transactions (audit/read-only access)
   - Can generate reports and export data

### Key Responsibilities

The kascommissie team has defined responsibilities:

1. **Monthly Financial Review**
   - Review financial statements
   - Verify transaction accuracy
   - Check compliance with policies

2. **Payment Processing Audit**
   - Monitor SEPA direct debit processes
   - Verify mandate compliance
   - Review payment reconciliation

3. **Expense Management Oversight**
   - Audit volunteer expense claims
   - Review approval workflows
   - Monitor budget compliance

4. **Reporting and Documentation**
   - Generate audit reports
   - Document findings and recommendations
   - Coordinate with external auditors

## Security Considerations

- **Read-Only Access:** Kascommissie members cannot modify financial data
- **Audit Trail:** All access is logged for compliance
- **Segregation of Duties:** Clear separation between operational and audit functions
- **Data Privacy:** Access limited to financial and operational data necessary for audit functions

## Compliance Features

- **Dutch Regulatory Compliance:** Meets requirements for non-profit audit committees
- **SEPA Compliance:** Full access to SEPA mandate and transaction audit trails
- **Financial Reporting:** Access to all standard financial reports and custom audit reports
- **Document Management:** Access to financial documents and supporting materials

## Troubleshooting

### Common Issues

1. **Missing Access:** Ensure user has "Verenigingen Kascommissie" role profile assigned
2. **Workspace Visibility:** Check that workspaces are public and not restricted
3. **Permission Errors:** Verify fixtures are properly installed and migrated

### Support

For technical issues or questions about the kascommissie setup, refer to:
- System administrator
- Frappe/ERPNext documentation for role and permission management
- Verenigingen app documentation

## Future Enhancements

Potential improvements for the kascommissie functionality:
- Custom audit reports and dashboards
- Automated compliance checking
- Integration with external audit tools
- Enhanced workflow for audit processes
