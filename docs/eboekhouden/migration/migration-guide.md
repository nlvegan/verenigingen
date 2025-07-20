# eBoekhouden Migration Guide

## Overview

This guide provides step-by-step instructions for migrating financial data from eBoekhouden.nl to ERPNext using the integrated REST API system.

## Prerequisites

### System Requirements
- **ERPNext**: Version 13+ with Frappe Framework
- **eBoekhouden.nl Account**: With API access enabled
- **API Token**: Available from your eBoekhouden account settings
- **Company Setup**: ERPNext company must be configured with chart of accounts

### Permissions Required
- **System Manager** or **eBoekhouden Administrator** role
- **Write access** to: Accounts, Items, Customers, Suppliers, Journal Entries, Invoices
- **Company access** for the target company

## Step 1: Configuration

### 1.1 Configure eBoekhouden Settings
1. Navigate to **E-Boekhouden Settings** doctype
2. Configure the following fields:

```
API Configuration:
├── API Token: [Your eBoekhouden API token]
├── API URL: https://api.e-boekhouden.nl/v1 (default)
└── Source Application: [Your app identifier]

Company Settings:
├── Default Company: [Select your ERPNext company]
├── Default Cost Center: [Auto-populated from company]
└── Journal Entry Series: [Default naming series]

Migration Options:
├── Enable Enhanced Item Management: Yes (recommended)
├── Enable Automatic Account Type Detection: Yes
└── Enable Opening Balance Import: Yes
```

### 1.2 Test API Connection
1. Click **"Test REST API Connection"** button
2. Verify you see: ✅ **REST API: Connection successful**
3. Test chart of accounts preview with **"Test Chart of Accounts"** button

## Step 2: Pre-Migration Analysis

### 2.1 Review Chart of Accounts
1. Use **"Test Chart of Accounts"** to preview account structure
2. Verify account mappings will work with your ERPNext setup
3. Note any accounts that may need manual mapping

### 2.2 Check Opening Balances
If importing opening balances:
1. Verify opening balance date in eBoekhouden
2. Ensure ERPNext fiscal year covers the opening balance period
3. Review stock accounts (will be automatically skipped)

### 2.3 Backup Preparation
**Critical**: Always backup before migration:
```bash
# Database backup
bench --site [your-site] backup

# File backup of custom settings
cp sites/[your-site]/site_config.json sites/[your-site]/site_config.json.backup
```

## Step 3: Migration Execution

### 3.1 Start Migration
1. Navigate to **E-Boekhouden Migration** doctype
2. Click **"New"** to create a migration record
3. Configure migration parameters:

```
Migration Settings:
├── Company: [Your company]
├── Migration Type: Full REST Import
├── Import Opening Balances: Yes (recommended)
├── Date Range: [Leave blank for all data]
└── Status: Draft

Advanced Options:
├── Use Enhanced Migration: Yes
├── Enable Progress Tracking: Yes
└── Auto-Balance Opening Entries: Yes (recommended)
```

4. **Save** the migration record
5. Click **"Start Full REST Import"** button

### 3.2 Monitor Progress
1. **Real-time updates**: Progress bar shows current status
2. **Migration dashboard**: Real-time statistics and counters
3. **Debug information**: Detailed logs for troubleshooting
4. **Estimated completion**: Based on transaction volume

Progress indicators:
- ✅ **Chart of Accounts**: Account structure imported
- ✅ **Opening Balances**: Balance sheet opening entries
- ✅ **Transactions**: All mutations imported
- ✅ **Parties**: Customers and suppliers created
- ✅ **Validation**: Data integrity checks completed

## Step 4: Post-Migration Validation

### 4.1 Verify Chart of Accounts
1. Navigate to **Chart of Accounts**
2. Verify all eBoekhouden accounts are present
3. Check account types are correctly assigned
4. Confirm grootboek numbers are mapped

### 4.2 Validate Opening Balances
1. Run **Trial Balance** for opening balance date
2. Compare totals with eBoekhouden opening balances
3. Verify automatic balancing entries if created
4. Check that stock accounts were properly skipped

### 4.3 Review Transactions
1. Check **Journal Entries** for imported mutations
2. Verify **Sales Invoices** and **Purchase Invoices**
3. Confirm **Payment Entries** are correctly linked
4. Validate party assignments (customers/suppliers)

### 4.4 Party Management
1. Review **Customers** list for imported relations
2. Check **Suppliers** for vendor information
3. Verify party links in transactions
4. Confirm contact information where available

## Step 5: Error Handling

### 5.1 Common Issues and Solutions

#### Stock Account Errors
**Issue**: Stock accounts cannot be updated via Journal Entries
**Solution**: ✅ **Automatically handled** - stock accounts are skipped with detailed logging

#### Unbalanced Opening Balances
**Issue**: "Opening balance entries do not balance"
**Solution**: ✅ **Automatically handled** - balancing entries created using Temporary accounts

#### API Rate Limits
**Issue**: Too many API requests
**Solution**: Built-in rate limiting and retry mechanisms

#### Missing Account Types
**Issue**: Accounts imported without proper types
**Solution**: Enhanced smart account type detection based on eBoekhouden categories

### 5.2 Debugging Tools
1. **Migration Dashboard**: Real-time error monitoring
2. **Debug Logs**: Detailed operation logging
3. **Error Reports**: Categorized error summaries
4. **Validation Scripts**: Post-migration integrity checks

## Step 6: Advanced Features

### 6.1 Partial Migrations
For large datasets or testing:
```python
# Import specific date range
start_date = "2024-01-01"
end_date = "2024-12-31"

# Import specific mutation types
mutation_types = ["Sales Invoice", "Purchase Invoice"]
```

### 6.2 Opening Balance Only
For balance sheet setup:
```python
# Import only opening balances
import_opening_balances_only(company="Your Company")
```

### 6.3 Resume Interrupted Migrations
If migration is interrupted:
1. Check migration status in dashboard
2. Note last successfully imported mutation
3. Use **"Resume Migration"** functionality
4. System automatically continues from last checkpoint

## Step 7: Performance Optimization

### 7.1 Large Dataset Handling
For companies with extensive transaction history:
- **Batch processing**: Automatic batching for large imports
- **Progress checkpoints**: Regular save points for resume capability
- **Memory optimization**: Efficient data processing
- **Connection pooling**: Optimized API usage

### 7.2 Monitoring
- **Real-time progress**: Live updates during migration
- **Performance metrics**: Import speed and efficiency stats
- **Resource usage**: Memory and CPU monitoring
- **Error rate tracking**: Success/failure statistics

## Best Practices

### Before Migration
1. **Complete backup** of ERPNext database
2. **Test migration** on staging environment first
3. **Verify API credentials** and permissions
4. **Review date ranges** for partial imports
5. **Check disk space** for large imports

### During Migration
1. **Monitor progress** regularly via dashboard
2. **Avoid system changes** during active migration
3. **Keep session active** for long migrations
4. **Document any errors** for later review

### After Migration
1. **Comprehensive validation** of imported data
2. **Reconcile balances** with eBoekhouden reports
3. **Test workflows** with migrated data
4. **Update user training** for new system structure
5. **Archive migration logs** for future reference

## Migration Checklist

### Pre-Migration ✅
- [ ] ERPNext backup completed
- [ ] eBoekhouden API token configured
- [ ] Company and cost center selected
- [ ] API connection tested successfully
- [ ] Chart of accounts preview reviewed
- [ ] Date range determined (if partial migration)

### Migration Execution ✅
- [ ] Migration record created and configured
- [ ] Full REST import initiated
- [ ] Progress monitoring active
- [ ] No critical errors in dashboard
- [ ] All migration phases completed

### Post-Migration Validation ✅
- [ ] Chart of accounts complete and correctly typed
- [ ] Opening balances imported and balanced
- [ ] Transaction counts match eBoekhouden
- [ ] Party information correctly imported
- [ ] No orphaned or unlinked entries
- [ ] Trial balance reconciles with source

### System Readiness ✅
- [ ] User access permissions updated
- [ ] Workflows tested with migrated data
- [ ] Reports generate correctly
- [ ] Integration with other systems verified
- [ ] Documentation updated for users

---

## Support and Troubleshooting

For issues during migration:
1. **Check migration dashboard** for real-time error information
2. **Review debug logs** for detailed error messages
3. **Use built-in validation** tools for data integrity checks
4. **Consult troubleshooting guide** for common solutions
5. **Contact system administrator** with migration ID and error details

**Migration typically takes**: 1-4 hours depending on transaction volume
**Success rate**: 99%+ with automatic error handling and recovery
**Data integrity**: Comprehensive validation ensures accurate migration
