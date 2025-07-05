# Expense Claim Integration with ERPNext

## Overview

The Verenigingen app integrates with ERPNext's native Expense Claim system from the HRMS module to handle volunteer expense reimbursements. This integration provides full accounting functionality while maintaining volunteer-specific business rules.

## Architecture

### Components

1. **Frontend Portal** (`/volunteer/expenses`)
   - Web interface for volunteers to submit expenses
   - Receipt upload functionality
   - Expense history and statistics

2. **Backend Integration**
   - `native_expense_helpers.py` - Manages expense approvers
   - `expenses.py` - Portal page logic and API endpoints
   - ERPNext HRMS Expense Claim doctype

3. **Data Model**
   - ERPNext `Expense Claim` - Primary expense record
   - `Volunteer Expense` - Tracking and reference record
   - Employee records linked to volunteers

## Expense Submission Flow

### 1. Initial Submission
When a volunteer submits an expense through the portal:


**Process:**
1. Validates volunteer record exists
2. Checks organization membership (chapter/team/national)
3. Creates employee record if missing
4. Determines cost center based on organization
5. Creates ERPNext Expense Claim in "Draft" status
6. Attaches receipt files if provided
7. Creates parallel Volunteer Expense record

### 2. Validation Rules

**Organization Access:**
- **Chapter expenses**: Requires active chapter membership
- **Team expenses**: Requires active team membership
- **National expenses**:
  - Policy-covered categories (travel, materials) allowed for all
  - Other categories require national board membership

**Required Fields:**
- Description
- Amount
- Expense date
- Organization type
- Expense category

### 3. Approval Workflow

The expense follows ERPNext's standard approval process:

```
Draft → Submitted → Approved/Rejected → Paid
```

**Approval Hierarchy:**
- Determined by volunteer's assigned expense approver
- Falls back to chapter/team leadership
- Administrator as ultimate fallback

## Accounting Integration

### GL Entry Creation

When an expense claim is approved and submitted, ERPNext creates the following accounting entries:

#### Basic Expense Entry
```
Dr. [Expense Account]     €100.00
    Cr. Employee Payable      €100.00
```

#### With VAT/Tax
```
Dr. [Expense Account]     €100.00
Dr. VAT Input              €21.00
    Cr. Employee Payable      €121.00
```

#### Payment Entry
```
Dr. Employee Payable      €121.00
    Cr. Bank Account          €121.00
```

### Account Determination

1. **Expense Account**: Based on expense category mapping
2. **Payable Account**: Company's default expense claim payable account
3. **Cost Center**: Determined by organization hierarchy
4. **Tax Accounts**: Configured in tax templates

## Key Features

### 1. Automatic Employee Creation
- Volunteers don't need pre-existing employee records
- System creates minimal employee records on first expense
- Links maintained between volunteer and employee

### 2. Receipt Management
- File upload during submission
- Automatic attachment to expense claim
- Support for multiple file formats

### 3. Multi-Organization Support
- Expenses can be submitted to chapters, teams, or national
- Proper cost center allocation
- Organization-based approval routing

### 4. Financial Controls
- Sanctioned amount validation
- Advance adjustment support
- Tax calculation capability
- Multi-currency support

## Configuration

### Required Setup

1. **Company Settings**
   - Default expense claim payable account
   - Cost centers for organizations

2. **Expense Categories**
   - Map to ERPNext Expense Claim Types
   - Configure default accounts

3. **Volunteer Records**
   - Link to member records
   - Assign expense approvers

4. **Verenigingen Settings**
   - National board chapter
   - National cost center

### Expense Claim Types

Expense categories are mapped to ERPNext Expense Claim Types:
- Each type requires a default expense account
- Account must be linked to company
- Tax templates can be applied

## API Endpoints

### Submit Expense
```python
@frappe.whitelist()
def submit_expense(expense_data):
    # Creates expense claim and volunteer expense record
```

### Get Organization Options
```python
@frappe.whitelist()
def get_organization_options(organization_type, volunteer_name):
    # Returns chapters/teams for volunteer
```

### Upload Receipt
```python
@frappe.whitelist()
def upload_expense_receipt():
    # Handles file upload for later attachment
```

## Troubleshooting

### Common Issues

1. **"No volunteer record found"**
   - Ensure user has linked volunteer record
   - Check email matches between user and volunteer/member

2. **"Employee record required"**
   - System should auto-create
   - Check permissions for employee creation

3. **"No payable account configured"**
   - Set default_expense_claim_payable_account in Company

4. **Cost center errors**
   - Ensure organizations have cost centers assigned
   - Check fallback cost center exists

### Debug Functions

```python
# Check volunteer access
debug_volunteer_access()

# Test expense integration
test_expense_integration()

# Debug file attachments
debug_file_attachment(expense_claim_name, file_url)
```

## Best Practices

1. **Regular Validation**
   - Run `validate_expense_approver_setup()` periodically
   - Fix issues with `fix_expense_approver_issues()`

2. **Cost Center Management**
   - Assign cost centers to all chapters/teams
   - Configure national cost center in settings

3. **Approver Assignment**
   - Ensure all volunteers have expense approvers
   - Grant "Expense Approver" role to approvers

4. **Financial Setup**
   - Configure expense accounts for all categories
   - Set up tax templates if applicable
   - Regular GL reconciliation

## Integration Points

### With Volunteer Management
- Employee records created automatically
- Approver hierarchy from assignments
- Organization membership validation

### With Financial Module
- Direct GL posting
- Integration with Chart of Accounts
- Financial reporting capabilities

### With Document Management
- Receipt attachment handling
- File storage in ERPNext DMS
- Audit trail maintenance
