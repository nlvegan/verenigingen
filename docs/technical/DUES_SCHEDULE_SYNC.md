# Membership Dues Schedule Synchronization

## Overview

This document describes the synchronization mechanism between Membership Dues Schedule records and Member records, ensuring data consistency and proper billing period tracking.

## Architecture

### Key Fields

1. **Member.current_dues_schedule** (Link)
   - Points to the currently active Membership Dues Schedule for the member
   - Automatically maintained by hooks when schedules are created or updated
   - Used as the source of truth for the member's billing configuration

2. **Member.next_invoice_date** (Date)
   - Fetched from `current_dues_schedule.next_invoice_date`
   - Also updated directly when invoices are generated for immediate consistency
   - Shows when the next invoice will be generated

3. **MembershipDuesSchedule.next_billing_period_start_date** (Date)
4. **MembershipDuesSchedule.next_billing_period_end_date** (Date)
   - Shows the period that the NEXT invoice will cover
   - NOT the current/last invoice period
   - Updated after each invoice generation

## Synchronization Strategy

### 1. Schedule Creation (after_insert)
When a new Membership Dues Schedule is created:
- If it's Active and there's no current schedule, it becomes current
- If it's Active and newer than the existing current schedule, it replaces it
- Uses `FOR UPDATE` lock to prevent race conditions

### 2. Schedule Status Change (on_update)
When a schedule's status changes:
- If becoming Active: May become the current schedule
- If becoming Inactive: System finds another active schedule or clears the field
- Maintains referential integrity automatically

### 3. Invoice Generation
When an invoice is generated:
1. Invoice is created for the current period
2. `last_invoice_date` is updated to the actual invoice date
3. `next_invoice_date` is calculated and set
4. Billing period dates are updated to show the NEXT period
5. Member's `next_invoice_date` is updated directly

## Implementation Details

### Hook Functions (`membership_dues_schedule_hooks.py`)

#### `update_member_current_dues_schedule(doc, method=None)`
- Called on after_insert and on_update of Membership Dues Schedule
- Uses atomic SQL with `FOR UPDATE` to prevent race conditions
- Handles both activation and deactivation scenarios
- No explicit commits - lets transaction complete normally

#### `check_and_update_all_members_current_schedule(batch_size=100)`
- Utility for bulk synchronization
- Processes members in batches for performance
- Includes timing metrics and progress logging
- Used for initial migration or fixing sync issues

### Performance Considerations

1. **Batch Processing**: Bulk updates process 100 members at a time
2. **Single Query Optimization**: Fetches all schedules for a batch in one query
3. **Transaction Management**: Commits after each batch to avoid long locks
4. **Progress Monitoring**: Logs progress every 500 members for visibility

## Common Scenarios

### Scenario 1: New Member Signup
1. Member is created
2. Membership is created
3. Dues Schedule is created → automatically set as current
4. Member.next_invoice_date is populated via fetch_from

### Scenario 2: Fee Amendment
1. New schedule created with different rate
2. If active, becomes current (newer creation date)
3. Old schedule may be cancelled
4. Member fields update automatically

### Scenario 3: Daily Invoice Generation
1. Scheduled job runs `generate_dues_invoices()`
2. For each due schedule:
   - Invoice created
   - Schedule dates updated
   - Member.next_invoice_date synced
   - Billing period shows next period

## Troubleshooting

### Issue: Member shows wrong next_invoice_date

**Check:**
1. Is `current_dues_schedule` set correctly?
2. Does the linked schedule exist and is Active?
3. Run `check_and_update_all_members_current_schedule()` to fix

### Issue: Billing period shows current instead of next

**Check:**
1. Verify the `update_schedule_dates()` method is being called
2. Check that billing period calculation uses `next_invoice_date`
3. Manually recalculate: `schedule.calculate_billing_period(schedule.next_invoice_date)`

### Issue: Multiple active schedules for same member

**Resolution:**
- System automatically uses the newest (by creation date)
- Consider adding validation to prevent multiple active schedules
- Use the bulk sync function to clean up

## Testing

Test coverage includes:
- `test_dues_schedule_sync.py` - Comprehensive synchronization tests
- Tests for race condition prevention
- Billing period calculation for different frequencies
- Edge cases like schedule deactivation

## Database Queries

### Find members with sync issues:
```sql
SELECT
    m.name,
    m.current_dues_schedule,
    mds.status,
    mds.next_invoice_date
FROM `tabMember` m
LEFT JOIN `tabMembership Dues Schedule` mds
    ON m.current_dues_schedule = mds.name
WHERE m.status = 'Active'
    AND (mds.status != 'Active' OR mds.name IS NULL);
```

### Find members with multiple active schedules:
```sql
SELECT
    member,
    COUNT(*) as active_count
FROM `tabMembership Dues Schedule`
WHERE status = 'Active'
    AND is_template = 0
GROUP BY member
HAVING COUNT(*) > 1;
```

## Future Improvements

1. **Validation**: Add check to prevent multiple active schedules per member
2. **Async Processing**: Consider background jobs for bulk updates
3. **Caching**: Cache frequently accessed schedule data
4. **Audit Trail**: Add detailed logging of all sync operations
5. **Dashboard**: Create monitoring dashboard for sync health
