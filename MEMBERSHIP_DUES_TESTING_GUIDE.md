# Membership Dues System - Testing Guide

## Overview

This guide helps you test the new Membership Dues System alongside the existing subscription system before full migration.

## Architecture Comparison

### Current System (Subscriptions)
```
Member → Membership → Subscription → Invoice (via subscription.process())
```
Problems:
- ERPNext validation errors ("Current Invoice Start Date")
- Complex workarounds needed
- Not designed for perpetual memberships

### New System (Dues Schedules)
```
Member → Membership → Dues Schedule → Invoice (direct generation)
```
Benefits:
- No subscription validation issues
- Natural fit for associations
- Flexible billing management

## Testing Steps

### Step 1: Install New DocTypes

```bash
# Run migration to create new doctypes
cd /home/frappe/frappe-bench
bench --site dev.veganisme.net migrate
```

### Step 2: Test with POC Script

```bash
# Run the proof-of-concept test
bench --site dev.veganisme.net execute verenigingen.scripts.membership_dues_poc.test_dues_system_poc
```

This will:
1. Create a test member (or use existing)
2. Create a test dues schedule
3. Generate a test invoice
4. Test the scheduled job

### Step 3: Test Individual Member Migration

```bash
# Compare systems for a specific member
bench --site dev.veganisme.net execute verenigingen.scripts.membership_dues_poc.compare_with_subscription --args '["Assoc-Member-2025-07-0030"]'

# Test migration (dry run)
bench --site dev.veganisme.net execute verenigingen.scripts.membership_dues_poc.migrate_single_subscription --args '["ACC-SUB-2025-00004", true]'
```

### Step 4: Test Scheduled Job

```bash
# Run the dues generation job in test mode
bench --site dev.veganisme.net execute verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule.generate_dues_invoices --args '[true]'
```

### Step 5: Manual Testing via UI

1. **Create a Dues Schedule**:
   - Go to Membership Dues Schedule List
   - Create New
   - Select Member and Membership
   - Set billing frequency and amount
   - Enable "Test Mode" for testing
   - Save

2. **Generate Invoice Manually**:
   - Open the dues schedule
   - Click "Generate Invoice" button
   - Check the generated invoice

3. **Test Adjustments**:
   - Change amount or frequency
   - Add notes
   - Pause/resume schedule

## Integration Points

### 1. Membership Application Approval

When implementing fully, update the application approval to create dues schedule instead of subscription:

```python
# In membership_application.py approval logic
from verenigingen.utils.membership_dues_integration import create_dues_schedule_from_application

# Replace subscription creation with:
schedule_name, invoice = create_dues_schedule_from_application(application)
```

### 2. Membership Termination

Update termination logic to handle dues schedules:

```python
# In termination processing
from verenigingen.utils.membership_dues_integration import handle_membership_termination

handle_membership_termination(member_name, termination_date)
```

### 3. Member Portal

Add billing status display:

```python
# In member portal
from verenigingen.utils.membership_dues_integration import get_member_billing_status

billing_status = get_member_billing_status(member_name)
```

## Testing Scenarios

### Scenario 1: New Member Application
1. Create membership application
2. Approve application
3. Verify dues schedule created
4. Check if initial invoice generated

### Scenario 2: Annual Billing Cycle
1. Create schedule with annual frequency
2. Set next invoice date to past date
3. Run scheduled job
4. Verify invoice created and dates updated

### Scenario 3: Payment Plan
1. Use create_payment_plan function
2. Verify multiple schedules created
3. Check installment amounts

### Scenario 4: Member Termination
1. Create active dues schedule
2. Terminate membership
3. Verify schedule cancelled
4. Check for prorated amounts

## Monitoring

### Check System Status

```python
# Get all active schedules
active_schedules = frappe.get_all("Membership Dues Schedule",
    filters={"status": "Active"},
    fields=["name", "member_name", "next_invoice_date"]
)

# Get pending invoice generation
pending = frappe.get_all("Membership Dues Schedule",
    filters={
        "status": "Active",
        "next_invoice_date": ["<=", add_days(today(), 30)]
    }
)
```

### Update Zabbix Monitoring

```python
# In zabbix_integration.py, add:
def get_dues_metrics():
    metrics = {}

    # Active dues schedules
    metrics["frappe.dues.active_schedules"] = frappe.db.count(
        "Membership Dues Schedule", {"status": "Active"})

    # Invoices generated today
    metrics["frappe.dues.invoices_today"] = frappe.db.count(
        "Sales Invoice", {
            "membership_dues_schedule": ["!=", ""],
            "creation": [">=", today()]
        })

    return metrics
```

## Rollback Plan

If issues arise during testing:

1. **Disable Scheduled Job**: Comment out the dues generation job in hooks.py
2. **Cancel Test Invoices**: Cancel any test invoices created
3. **Delete Test Schedules**: Delete test dues schedules
4. **Continue with Subscriptions**: Existing subscription system remains functional

## Migration Checklist

Before full migration:

- [ ] All test scenarios pass
- [ ] Performance acceptable (invoice generation time)
- [ ] Member portal integration working
- [ ] Payment processing confirmed
- [ ] Reporting updated
- [ ] Staff trained on new system
- [ ] Backup created
- [ ] Migration script tested on subset
- [ ] Rollback plan documented

## Common Issues and Solutions

### Issue: Invoice not generating
- Check schedule status is "Active"
- Verify auto_generate is enabled
- Check next_invoice_date is not in future
- Look for errors in Error Log

### Issue: Duplicate invoices
- Check last_invoice_date is being updated
- Verify scheduled job not running multiple times
- Check for manual + automatic generation

### Issue: Wrong amounts
- Verify membership type fee settings
- Check if schedule amount overrides type amount
- Look for currency conversion issues

## Next Steps

1. Run POC tests
2. Test with 5-10 real members in parallel
3. Monitor for one billing cycle
4. Plan full migration
5. Update all integration points
6. Disable subscription system
