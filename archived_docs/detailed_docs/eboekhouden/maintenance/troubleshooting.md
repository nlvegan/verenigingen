# eBoekhouden Troubleshooting Guide

## Overview

This guide provides solutions to common issues encountered during eBoekhouden integration setup, migration, and maintenance.

## Quick Diagnostic Tools

### System Health Check
```python
# Run in ERPNext console
frappe.call('verenigingen.api.test_eboekhouden_connection.test_eboekhouden_connection')
```

### Migration Status Check
```python
# Check current migration status
frappe.call('verenigingen.utils.eboekhouden.import_manager.get_import_status')
```

## Connection Issues

### API Connection Failures

#### Problem: "Connection test failed"
**Symptoms**:
- Red error message during connection test
- Unable to preview chart of accounts
- Migration fails to start

**Diagnosis**:
1. Check API token validity
2. Verify internet connectivity
3. Confirm eBoekhouden API status

**Solutions**:

**Solution 1: API Token Issues**
```python
# Verify token in E-Boekhouden Settings
settings = frappe.get_single("E-Boekhouden Settings")
token = settings.get_password("api_token")
print(f"Token configured: {bool(token)}")
```

**Solution 2: Network Connectivity**
```bash
# Test connectivity to eBoekhouden API
curl -H "Authorization: Bearer YOUR_TOKEN" https://api.e-boekhouden.nl/v1/administraties
```

**Solution 3: Update API URL**
```python
# Ensure modern API endpoint is used
frappe.call('verenigingen.utils.eboekhouden.eboekhouden_api.update_api_url')
```

#### Problem: "Rate limit exceeded"
**Symptoms**:
- Intermittent API failures
- "Too many requests" errors
- Slow response times

**Solution**:
The system includes automatic rate limiting. If issues persist:
1. Wait 60 seconds before retrying
2. Check for concurrent migrations
3. Contact eBoekhouden support if limits seem too restrictive

#### Problem: "SSL Certificate verification failed"
**Symptoms**:
- HTTPS connection errors
- Certificate validation warnings

**Solutions**:
1. Update system certificates: `sudo apt-get update && sudo apt-get install ca-certificates`
2. Check system date/time is correct
3. Verify no proxy interference

## Migration Issues

### Migration Startup Problems

#### Problem: "No default company configured"
**Solution**:
1. Go to **E-Boekhouden Settings**
2. Select your company in **Default Company** field
3. Save and retry migration

#### Problem: "Migration already in progress"
**Symptoms**:
- Cannot start new migration
- Previous migration shows as "In Progress" but no activity

**Solution**:
```python
# Check for stuck migrations
from vereiniginen.utils.eboekhouden.migration_api import reset_stuck_migration
reset_stuck_migration()
```

#### Problem: "Insufficient permissions"
**Solution**:
1. Ensure user has **eBoekhouden Administrator** role
2. Check permissions for:
   - Journal Entry (Create/Write)
   - Account (Create/Write)
   - Customer/Supplier (Create/Write)
   - Item (Create/Write)

### Data Import Issues

#### Problem: "Opening balance entries do not balance"
**Symptoms**:
- Error during opening balance import
- Message shows debit/credit difference

**Solution**: ✅ **Automatically handled** (2025 enhancement)
- System automatically creates balancing entries
- Uses "Temporary" account type for differences
- Check migration logs for balancing entry details

#### Problem: "Stock account cannot be updated via Journal Entry"
**Symptoms**:
- Import fails with stock account errors
- ERPNext prevents stock account updates

**Solution**: ✅ **Automatically handled** (2025 enhancement)
- Stock accounts are automatically detected and skipped
- Opening balances exclude stock accounts
- Detailed logging shows which accounts were skipped

#### Problem: "Account not found" errors
**Symptoms**:
- Missing accounts during transaction import
- Grootboek number mapping failures

**Solutions**:

**Solution 1: Import Chart of Accounts First**
```python
# Import chart of accounts before transactions
frappe.call('verenigingen.utils.eboekhouden.eboekhouden_api.preview_chart_of_accounts')
```

**Solution 2: Fix Account Mappings**
```python
# Fix account type assignments
frappe.call('verenigingen.utils.eboekhouden.eboekhouden_api.fix_account_types')
```

### Performance Issues

#### Problem: Slow migration performance
**Symptoms**:
- Migration takes much longer than expected
- High memory usage
- System responsiveness issues

**Solutions**:

**Solution 1: Optimize Batch Size**
```python
# Reduce batch size for large datasets
# Configure in migration settings or contact administrator
```

**Solution 2: Check System Resources**
```bash
# Monitor system resources during migration
htop
df -h  # Check disk space
```

**Solution 3: Database Optimization**
```sql
-- Optimize database for large imports
OPTIMIZE TABLE `tabJournal Entry`;
OPTIMIZE TABLE `tabGL Entry`;
```

#### Problem: Memory errors during large imports
**Symptoms**:
- "Memory allocation" errors
- Python process crashes
- System becomes unresponsive

**Solutions**:
1. **Increase system memory** if possible
2. **Migrate in smaller date ranges**:
   ```python
   # Import by year instead of all data
   clean_import_all(from_date='2024-01-01', to_date='2024-12-31')
   ```
3. **Restart services** before large migrations:
   ```bash
   bench restart
   ```

## Data Quality Issues

### Account and Party Issues

#### Problem: Duplicate accounts created
**Symptoms**:
- Multiple accounts with similar names
- Grootboek number conflicts

**Solution**:
```python
# Check for duplicate grootboek numbers
accounts = frappe.get_all('Account',
    filters={'eboekhouden_grootboek_nummer': ['!=', '']},
    fields=['name', 'eboekhouden_grootboek_nummer'])

# Look for duplicates
grootboek_numbers = {}
for acc in accounts:
    gb_nr = acc.eboekhouden_grootboek_nummer
    if gb_nr in grootboek_numbers:
        print(f"Duplicate grootboek number {gb_nr}: {acc.name}")
    grootboek_numbers[gb_nr] = acc.name
```

#### Problem: Customer/Supplier creation failures
**Symptoms**:
- "Customer already exists" errors
- Party information missing

**Solutions**:

**Solution 1: Check Existing Parties**
```python
# Find existing parties with eBoekhouden IDs
customers = frappe.get_all('Customer',
    filters={'eboekhouden_relation_id': ['!=', '']},
    fields=['name', 'eboekhouden_relation_id'])
```

**Solution 2: Clean Party Names**
```python
# Clean up party names if they contain invalid characters
# The system handles this automatically but check for edge cases
```

### Transaction Issues

#### Problem: "Service Item not found" errors
**Solution**: ✅ **Automatically handled** (2025 enhancement)
- System now creates intelligent items based on account codes
- No dependency on hardcoded "Service Item"
- Items are automatically created with meaningful names

#### Problem: Unlinked transactions
**Symptoms**:
- Journal entries created but not linked to invoices
- Payment entries missing references

**Solution**:
```python
# Validate transaction linking
def check_transaction_links():
    # Check for unlinked journal entries
    unlinked_je = frappe.get_all('Journal Entry',
        filters={'eboekhouden_mutation_nr': ['!=', ''], 'voucher_type': ['in', ['Sales Invoice', 'Purchase Invoice']]},
        fields=['name', 'eboekhouden_mutation_nr'])

    for je in unlinked_je:
        print(f"Checking linking for JE: {je.name}")
```

## System Configuration Issues

### Settings and Permissions

#### Problem: E-Boekhouden Settings doctype not found
**Symptoms**:
- Cannot access settings
- "DocType E-Boekhouden Settings not found"

**Solution**:
```bash
# Reinstall the app
bench migrate
bench build
bench restart
```

#### Problem: Custom fields missing
**Symptoms**:
- Fields like "eBoekhouden Grootboek Number" not visible
- Account mapping failures

**Solution**:
```python
# Recreate custom fields
frappe.call('verenigingen.utils.eboekhouden.create_eboekhouden_custom_fields.create_custom_fields')
```

#### Problem: Migration dashboard not loading
**Symptoms**:
- Dashboard shows errors
- Progress information missing

**Solution**:
```python
# Reset dashboard data
frappe.call('verenigingen.utils.eboekhouden.eboekhouden_api.get_dashboard_data_api')
```

## Error Recovery Procedures

### Recovering from Failed Migrations

#### Partial Migration Recovery
If migration fails partway through:

1. **Assess the situation**:
   ```python
   # Check what was imported
   migration_doc = frappe.get_last_doc('E-Boekhouden Migration')
   print(f"Status: {migration_doc.status}")
   print(f"Progress: {migration_doc.progress_percentage}%")
   ```

2. **Clean up partial data** (if needed):
   ```python
   # Remove incomplete migration data
   # WARNING: Only do this if migration is definitely failed
   migration_id = "EBMIG-2025-00001"
   cleanup_failed_migration(migration_id)
   ```

3. **Restart migration**:
   ```python
   # Start new migration with lessons learned
   clean_import_all(from_date='2024-01-01')  # Adjust date range if needed
   ```

#### Database Consistency Issues
If database becomes inconsistent:

1. **Check GL entries**:
   ```sql
   -- Find unbalanced GL entries
   SELECT voucher_no, SUM(debit - credit) as imbalance
   FROM `tabGL Entry`
   WHERE creation > '2025-07-01'  -- Adjust date
   GROUP BY voucher_no
   HAVING ABS(imbalance) > 0.01;
   ```

2. **Validate account balances**:
   ```python
   # Run balance validation
   from erpnext.accounts.utils import validate_account_balances
   validate_account_balances()
   ```

## Monitoring and Prevention

### Proactive Monitoring

#### Set up regular health checks:
```python
# Weekly health check script
def weekly_health_check():
    # Test API connection
    connection_test = frappe.call('verenigingen.api.test_eboekhouden_connection.test_eboekhouden_connection')

    # Check for orphaned records
    orphaned_gl = frappe.db.count('GL Entry', {'voucher_no': ['like', 'EBH-%'], 'is_cancelled': 0})

    # Monitor error rates
    failed_migrations = frappe.db.count('E-Boekhouden Migration', {'status': 'Failed'})

    return {
        'api_healthy': connection_test.get('success'),
        'orphaned_entries': orphaned_gl,
        'failed_migrations': failed_migrations
    }
```

#### Performance monitoring:
```python
# Monitor migration performance
def track_migration_performance():
    recent_migrations = frappe.get_all('E-Boekhouden Migration',
        filters={'creation': ['>', '2025-07-01']},
        fields=['name', 'status', 'creation', 'modified', 'total_records'])

    for migration in recent_migrations:
        duration = migration.modified - migration.creation
        records_per_hour = migration.total_records / (duration.total_seconds() / 3600)
        print(f"Migration {migration.name}: {records_per_hour:.1f} records/hour")
```

### Backup and Recovery

#### Before major operations:
```bash
# Create comprehensive backup
bench --site your-site backup --with-files

# Export eBoekhouden settings
bench --site your-site export-doc "E-Boekhouden Settings"
```

#### Emergency recovery procedures:
1. **Restore from backup** if major data corruption
2. **Reset migration status** for stuck processes
3. **Reinitialize settings** if configuration is corrupted
4. **Contact support** with detailed error logs

## Getting Help

### Information to Collect
When seeking support, gather:

1. **Error messages** (exact text)
2. **Migration ID** and status
3. **System information**:
   ```python
   # Collect system info
   import frappe
   print(f"Frappe version: {frappe.__version__}")
   print(f"Site: {frappe.local.site}")
   print(f"User: {frappe.session.user}")
   ```
4. **Recent migration logs**
5. **Steps to reproduce** the issue

### Log Locations
- **Migration logs**: E-Boekhouden Migration doctype
- **System logs**: ERPNext Error Log
- **API logs**: Check console output during operations
- **Database logs**: MySQL/MariaDB error logs

### Support Escalation
1. **Level 1**: Check this troubleshooting guide
2. **Level 2**: Review system logs and recent changes
3. **Level 3**: Contact system administrator with detailed information
4. **Level 4**: Engage eBoekhouden integration specialists

---

**Quick Reference**: For immediate help with common issues, check the error message against the solutions above. Most 2025 issues are automatically handled by the enhanced system.

**Emergency Contact**: In case of data corruption or system failure, immediately create a backup and contact your system administrator before making further changes.
