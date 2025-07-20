# eBoekhouden Configuration Guide

## Overview

This guide covers the complete configuration process for setting up the eBoekhouden integration in ERPNext.

## Prerequisites

### eBoekhouden.nl Account Setup
1. **Active eBoekhouden account** with administrative access
2. **API access enabled** in your eBoekhouden subscription
3. **API token generated** from eBoekhouden account settings

### ERPNext Requirements
- **System Manager** or **eBoekhouden Administrator** role
- **Company configured** with basic chart of accounts
- **Cost center created** and assigned to company
- **Appropriate permissions** for financial data management

## Step 1: eBoekhouden API Token Setup

### 1.1 Generate API Token in eBoekhouden
1. Log in to your eBoekhouden.nl account
2. Navigate to **Account Settings** → **API Access** or **Integrations**
3. Generate a new API token or copy existing token
4. **Save the token securely** - you'll need it for ERPNext configuration

### 1.2 Test API Access
Before configuring ERPNext, verify your API token works:
- Check that your eBoekhouden subscription includes API access
- Verify the token has appropriate permissions
- Note your eBoekhouden company/administration ID if applicable

## Step 2: ERPNext E-Boekhouden Settings

### 2.1 Access Settings
1. In ERPNext, go to **Search** → **E-Boekhouden Settings**
2. This opens the main configuration doctype
3. If it doesn't exist, create a new **E-Boekhouden Settings** document

### 2.2 API Configuration
Configure the core API settings:

```
API Configuration Section:
┌─────────────────────────────────────────┐
│ API Token: [Your eBoekhouden API token] │
│ API URL: https://api.e-boekhouden.nl/v1 │
│ Source Application: ERPNext Integration │
└─────────────────────────────────────────┘
```

**Field Details**:
- **API Token**: The token from your eBoekhouden account (stored securely)
- **API URL**: Leave as default unless using custom endpoint
- **Source Application**: Identifier for API usage tracking

### 2.3 Company Configuration
Set up the ERPNext company mapping:

```
Company Settings Section:
┌────────────────────────────────────────┐
│ Default Company: [Your ERPNext Company]│
│ Default Cost Center: [Auto-populated] │
│ Journal Entry Series: [ACC-JV-.YYYY.-] │
└────────────────────────────────────────┘
```

**Field Details**:
- **Default Company**: Select your primary ERPNext company
- **Default Cost Center**: Automatically populated from company settings
- **Journal Entry Series**: Naming series for imported journal entries

### 2.4 Migration Options
Configure migration behavior:

```
Migration Options Section:
┌──────────────────────────────────────────────┐
│ ☑ Enable Enhanced Item Management           │
│ ☑ Enable Automatic Account Type Detection   │
│ ☑ Enable Opening Balance Import             │
│ ☑ Auto-Balance Opening Entries              │
│ ☑ Skip Stock Accounts in Opening Balances   │
└──────────────────────────────────────────────┘
```

**Option Details**:
- **Enhanced Item Management**: Creates intelligent items from account codes
- **Automatic Account Type Detection**: Smart mapping of account types
- **Opening Balance Import**: Include opening balances in migration
- **Auto-Balance Opening Entries**: Automatically balance unbalanced entries
- **Skip Stock Accounts**: Exclude stock accounts from opening balances

## Step 3: Validation and Testing

### 3.1 Test API Connection
1. In E-Boekhouden Settings, click **"Test REST API Connection"**
2. Verify response: ✅ **REST API: Connection successful**
3. If connection fails, check:
   - API token is correct and not expired
   - Internet connectivity
   - eBoekhouden API service status

### 3.2 Preview Chart of Accounts
1. Click **"Test Chart of Accounts"** button
2. Review the preview dialog showing:
   - Total number of accounts
   - Account structure breakdown
   - Sample account data
3. Verify accounts look correct for your business

### 3.3 Test Connection Status
After successful testing, the settings should show:
```
Connection Status: ✅ API Connection Verified
Last Tested: [Current timestamp]
API Version: v1
```

## Step 4: Advanced Configuration

### 4.1 Account Mapping Configuration
For advanced account mapping needs:

1. Navigate to **E-Boekhouden Account Mapping** doctype
2. Configure custom mappings if needed:
```
eBoekhouden Account: 1000 (Bank Account)
ERPNext Account: Bank - Company
Account Type: Bank
Is Group: No
```

### 4.2 Payment Account Configuration
Set up payment account mappings:

1. Use the API: `setup_default_payment_mappings`
2. Or manually configure in **E-Boekhouden Payment Mapping**:
```
Payment Type: Bank Transfer
eBoekhouden Account: 1000
ERPNext Account: Bank - Company
Is Default: Yes
```

### 4.3 Custom Field Configuration
The system automatically creates custom fields. Verify these exist:

**On Account DocType**:
- `eboekhouden_grootboek_nummer` (eBoekhouden Grootboek Number)
- `eboekhouden_account_id` (eBoekhouden Account ID)

**On Journal Entry DocType**:
- `eboekhouden_mutation_nr` (eBoekhouden Mutation Number)
- `eboekhouden_import_date` (Import Date)

**On Customer/Supplier DocTypes**:
- `eboekhouden_relation_id` (eBoekhouden Relation ID)

## Step 5: Security and Permissions

### 5.1 Role Configuration
Ensure proper roles are assigned:

**eBoekhouden Administrator Role**:
- Read/Write access to E-Boekhouden Settings
- Read/Write access to E-Boekhouden Migration
- Read access to migration status and logs

**System Manager Role**:
- Full access to all eBoekhouden functionality
- Ability to configure and modify settings
- Access to debug and maintenance functions

### 5.2 Permission Validation
The integration requires these permissions:
```
Document Types Required:
├── Account (Read/Write)
├── Company (Read)
├── Cost Center (Read)
├── Customer (Read/Write/Create)
├── Supplier (Read/Write/Create)
├── Item (Read/Write/Create)
├── Journal Entry (Read/Write/Create)
├── Sales Invoice (Read/Write/Create)
├── Purchase Invoice (Read/Write/Create)
└── Payment Entry (Read/Write/Create)
```

### 5.3 Data Access Security
- **API tokens are encrypted** in the database
- **Connection logs** maintain audit trails
- **Migration records** track all changes
- **User activity** is logged for compliance

## Step 6: Environment-Specific Configuration

### 6.1 Development Environment
For development/testing environments:
```
API Configuration:
├── Use test API tokens when available
├── Limit date ranges for testing
├── Enable enhanced debug logging
└── Use separate test company
```

### 6.2 Production Environment
For production deployments:
```
Security Settings:
├── Restrict access to System Managers only
├── Enable audit logging
├── Set up monitoring and alerts
└── Configure backup procedures before migrations
```

### 6.3 Multi-Company Setup
For organizations with multiple companies:
```
Company-Specific Configuration:
├── Separate E-Boekhouden Settings per company
├── Company-specific API tokens if needed
├── Individual migration schedules
└── Isolated chart of accounts per company
```

## Step 7: Monitoring and Maintenance

### 7.1 Health Monitoring
Set up regular monitoring:
- **API connection status**: Test connectivity weekly
- **Token expiration**: Monitor for expiring tokens
- **Migration performance**: Track import speeds and success rates
- **Error rates**: Monitor for increasing failure rates

### 7.2 Maintenance Tasks
Regular maintenance activities:
```
Weekly Tasks:
├── Review migration logs for errors
├── Verify API connection status
├── Check for eBoekhouden updates
└── Validate data integrity

Monthly Tasks:
├── Review account mappings for new accounts
├── Update configuration if business changes
├── Archive old migration logs
└── Performance optimization review
```

## Troubleshooting Configuration Issues

### Common Configuration Problems

#### API Token Issues
**Problem**: "Invalid API token" error
**Solution**:
1. Verify token in eBoekhouden account
2. Check token hasn't expired
3. Ensure account has API access enabled
4. Re-generate token if necessary

#### Company Configuration Issues
**Problem**: "No default company configured"
**Solution**:
1. Select company in E-Boekhouden Settings
2. Ensure company has cost center configured
3. Verify user has access to selected company

#### Permission Errors
**Problem**: "Insufficient permissions for operation"
**Solution**:
1. Check user roles include eBoekhouden Administrator
2. Verify document permissions are correctly set
3. Ensure user has access to target company

#### Connection Timeouts
**Problem**: API connection timeouts
**Solution**:
1. Check internet connectivity
2. Verify eBoekhouden API service status
3. Check firewall settings for outbound HTTPS
4. Consider proxy configuration if applicable

### Validation Checklist

Before proceeding with migration, verify:

**API Configuration** ✅
- [ ] API token is valid and saved
- [ ] Connection test passes
- [ ] Chart of accounts preview works
- [ ] API URL is correct

**Company Setup** ✅
- [ ] Default company selected
- [ ] Cost center is configured
- [ ] Journal entry series is set
- [ ] User has company access

**Permissions** ✅
- [ ] User has eBoekhouden Administrator role
- [ ] All required document permissions granted
- [ ] Company-level access configured
- [ ] Security settings reviewed

**System Readiness** ✅
- [ ] ERPNext backup completed
- [ ] Custom fields are created
- [ ] Account mappings configured
- [ ] Migration options selected

---

**Next Steps**: Once configuration is complete, proceed to the [Migration Guide](../migration/migration-guide.md) to begin data import.

**Support**: For configuration issues, check the [Troubleshooting Guide](../maintenance/troubleshooting.md) or contact your system administrator.
