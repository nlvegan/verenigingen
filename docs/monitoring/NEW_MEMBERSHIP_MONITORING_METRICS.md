# New Membership System Monitoring Metrics

## Overview

Three new critical monitoring metrics have been added to the Zabbix integration to monitor membership system health:

## New Metrics

### 1. Past Next Invoice Dates
- **Metric Key**: `frappe.dues_schedules.past_invoice_dates`
- **Description**: Counts active dues schedules with `next_invoice_date` in the past
- **Purpose**: Detects overdue billing schedules that need attention
- **Query**:
  ```sql
  SELECT COUNT(*)
  FROM `tabMembership Dues Schedule`
  WHERE status = 'Active'
  AND next_invoice_date < CURDATE()
  AND next_invoice_date IS NOT NULL
  ```

**Triggers**:
- **WARNING**: Any value > 0 (indicates billing issues)
- **HIGH**: Value > 10 (critical billing backlog)

### 2. Members Without Membership
- **Metric Key**: `frappe.members.without_membership`
- **Description**: Counts active members without active membership records
- **Purpose**: Identifies data integrity issues in the membership system
- **Query**:
  ```sql
  SELECT COUNT(*)
  FROM `tabMember` m
  WHERE m.status = 'Active'
  AND NOT EXISTS (
      SELECT 1 FROM `tabMembership` mb
      WHERE mb.member = m.name
      AND mb.status = 'Active'
      AND mb.docstatus = 1
  )
  ```

**Triggers**:
- **WARNING**: Any value > 0 (data integrity issue)
- **HIGH**: Value > 10 (significant data problems)

### 3. Members Without Dues Schedule
- **Metric Key**: `frappe.members.without_dues_schedule`
- **Description**: Counts active members without active billing dues schedules
- **Purpose**: Identifies members who won't be billed (revenue loss risk)
- **Query**:
  ```sql
  SELECT COUNT(*)
  FROM `tabMember` m
  WHERE m.status = 'Active'
  AND NOT EXISTS (
      SELECT 1 FROM `tabMembership Dues Schedule` mds
      WHERE mds.member = m.name
      AND mds.status = 'Active'
  )
  ```

**Triggers**:
- **INFO**: Any value > 0 (informational)
- **WARNING**: Value > 20 (potential revenue impact)
- **HIGH**: Value > 50 (significant revenue impact)

## Implementation Details

### Zabbix Integration
- **Endpoint**: `/api/method/verenigingen.monitoring.zabbix_integration.get_metrics_for_zabbix`
- **Update Frequency**: 5-10 minutes
- **Historical Data**: 30 days history, 90 days trends
- **Error Handling**: Returns 0 on query failures

### Template Items
All metrics include:
- HTTP Agent monitoring
- JSON Path preprocessing
- Error handling with fallback values
- Appropriate units (schedules/members)
- Component and scope tags

### Configurable Thresholds

| Threshold Macro | Default | Description |
|----------------|---------|-------------|
| `{$PAST_INVOICE_DATES_HIGH}` | 10 | Critical past invoice dates |
| `{$MEMBERS_WITHOUT_MEMBERSHIP_HIGH}` | 10 | Critical membership gaps |
| `{$MEMBERS_WITHOUT_DUES_SCHEDULE_WARN}` | 20 | Warning billing gaps |
| `{$MEMBERS_WITHOUT_DUES_SCHEDULE_HIGH}` | 50 | Critical billing gaps |

## Current Status (July 22, 2025)

Based on test data:
- **Past Invoice Dates**: 2 schedules (requires attention)
- **Members Without Membership**: 69 members (data cleanup needed)
- **Members Without Dues Schedule**: 69 members (billing setup needed)

## Recommended Actions

### For Past Invoice Dates > 0
1. Run dues schedule date validation:
   ```python
   from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import validate_and_fix_schedule_dates
   validate_and_fix_schedule_dates()
   ```

### For Members Without Membership > 0
1. Review inactive members and update status
2. Create missing membership records
3. Run data integrity checks

### For Members Without Dues Schedule > 0
1. Use auto-creation tool:
   ```python
   from verenigingen.utils.dues_schedule_auto_creator import auto_create_missing_dues_schedules
   auto_create_missing_dues_schedules()
   ```

## Files Modified

1. **`scripts/monitoring/zabbix_integration.py`**
   - Added new metrics to `get_dues_schedule_metrics()`
   - Added error handling for all metrics

2. **`scripts/monitoring/zabbix_template_frappe_v7.2_fixed.yaml`**
   - Added 3 new monitoring items
   - Added 9 new triggers (INFO, WARNING, HIGH levels)
   - Added 4 new configurable threshold macros

## Monitoring Best Practices

- **Monitor daily** for past invoice dates (should be 0)
- **Review weekly** for members without membership (data cleanup)
- **Review monthly** for members without dues schedules (revenue impact)
- **Set up notifications** for HIGH priority alerts
- **Adjust thresholds** based on organization size and tolerance

## Integration with Existing Monitoring

These metrics complement existing financial and business metrics:
- Works with existing error rate and performance monitoring
- Integrates with health check system
- Uses same authentication and endpoint structure
- Follows established Zabbix 7.2 template patterns
