# Automation Schedule Reference
## When Things Happen Automatically

This quick reference card shows exactly when automated processes run and what to expect. Use this to understand timing, plan manual work, and troubleshoot issues.

## Daily Schedule (All times are server time)

### Early Morning Processing (2:00-6:00 AM)
| Time | Process | Duration | What It Does | User Impact |
|------|---------|----------|--------------|-------------|
| 2:00 AM | **Member Financial History Refresh** | 10-30 min | Updates payment history, invoice status for all members | Member portal shows current data |
| 2:30 AM | **Membership Duration Updates** | 5-15 min | Calculates membership length for all members | Analytics reports current |
| 3:00 AM | **Expired Membership Processing** | 1-5 min | Marks expired memberships, triggers renewals | Member statuses current |
| 3:15 AM | **Renewal Reminder Processing** | 2-10 min | Sends renewal emails (30, 15, 7, 1 day warnings) | Members receive timely reminders |
| 3:30 AM | **Dues Schedule Auto-Creation** | 5-20 min | Creates missing billing schedules | All members have proper billing |
| 4:00 AM | **Invoice Generation** | 10-30 min | Creates invoices from dues schedules | New invoices ready for collection |
| 4:30 AM | **SEPA Batch Creation** * | 15-45 min | Creates payment batches on configured days | Batches ready for review/approval |
| 5:00 AM | **Amendment Request Processing** | 2-8 min | Processes approved fee changes | Fee changes take effect |
| 5:30 AM | **Termination Processing** | 3-10 min | Handles termination requests and compliance | Termination status updated |
| 6:00 AM | **Payment Retry Processing** | 5-20 min | Retries failed SEPA payments | Failed payments recovered automatically |

*Only runs on configured batch creation days (e.g., 1st and 15th of month)

### Business Hours Processing (6:00 AM - 6:00 PM)
| Time | Process | Frequency | Duration | Purpose |
|------|---------|-----------|----------|---------|
| Every hour | **Analytics Alert Checking** | Hourly | 1-3 min | Monitor membership metrics, trigger alerts |
| Every hour | **Payment History Validation** | Hourly | 2-8 min | Ensure payment data accuracy |
| Every 4 hours | **System Health Monitoring** | Every 4 hrs | 1-2 min | Check system performance, resource usage |

### Evening Processing (6:00-10:00 PM)
| Time | Process | Condition | Purpose |
|------|---------|-----------|---------|
| 6:00-10:00 PM | **Member History Refresh** (Optional) | If morning run failed or >24hrs since last run | Backup data refresh window |

## Weekly Schedule (Sundays, 1:00-3:00 AM)

| Time | Process | Duration | Purpose |
|------|---------|----------|---------|
| 1:00 AM | **Termination Compliance Reports** | 5-15 min | Generate governance oversight reports |
| 1:30 AM | **Security Health Checks** | 10-20 min | Validate system security configurations |
| 2:00 AM | **Address Data Refresh** | 5-10 min | Update member address display formats |
| 2:30 AM | **Expense History Validation** | 5-15 min | Verify volunteer expense data integrity |

## Monthly Schedule (1st day of month, 12:00-2:00 AM)

| Time | Process | Duration | Purpose |
|------|---------|----------|---------|
| 12:00 AM | **Address Data Cleanup** | 10-30 min | Remove orphaned address records |
| 12:30 AM | **Expense History Cleanup** | 5-20 min | Archive old expense history |
| 1:00 AM | **Analytics Data Archival** | 15-45 min | Archive old analytics snapshots |
| 1:30 AM | **System Configuration Validation** | 5-15 min | Check system settings consistency |

## Real-Time Background Processing

### Immediate Processing (30 seconds - 2 minutes)
| Trigger | Process | Duration | What Happens |
|---------|---------|----------|--------------|
| Payment submitted | **Payment Entry Processing** | 30 sec - 2 min | Updates member history, creates donors |
| Invoice created | **Invoice Processing** | 15 sec - 1 min | Links to members, applies tax rules |
| Member application approved | **New Member Processing** | 1-5 min | Creates customer, assigns chapter, sets up billing |
| Donation submitted | **Donor Auto-Creation** | 30 sec - 2 min | Creates donor records if enabled |

### Standard Processing (2-10 minutes)
| Trigger | Process | Duration | What Happens |
|---------|---------|----------|--------------|
| Large payment batch | **Bulk Payment Processing** | 2-10 min | Processes multiple payments |
| Member data update | **Related Record Updates** | 1-5 min | Updates linked records |
| SEPA mandate submission | **Mandate Validation** | 2-8 min | Validates IBAN, creates mandate |

## SEPA Batch Creation Schedule

### Automatic Batch Creation
- **Default schedule**: 1st and 15th of each month (configurable)
- **Time**: 4:30 AM on scheduled days
- **Business day adjustment**: Automatically moves to next business day if weekend/holiday
- **Conditions**: Only runs if auto-creation enabled and eligible invoices exist

### Manual Override Available
- **Emergency batches**: Can be created manually anytime
- **Override timing**: Available 24/7 for authorized users
- **Validation**: Same validation rules apply to manual creation

## Payment Processing Timing

### SEPA Payment Collection Timeline
| Step | Timing | What Happens |
|------|--------|--------------|
| Batch Creation | Day 0 | Batches created and validated |
| Bank Submission | Day 0-1 | Batches submitted to bank |
| Pre-notification | Day 1-5 | Banks process and validate |
| Collection Date | Day 5+ | Actual money movement |
| Return Processing | Day 6-8 | Failed payments returned |

### Payment Retry Schedule
| Attempt | Timing | Conditions |
|---------|--------|------------|
| 1st Retry | 2 hours after failure | For transient errors only |
| 2nd Retry | 24 hours after 1st retry | If mandate still valid |
| 3rd Retry | 72 hours after 2nd retry | Final automatic attempt |
| Manual Review | 7 days after 3rd retry | Staff intervention required |

## Email and Notification Timing

### Membership Renewal Reminders
| Days Before Expiry | Email Type | Time Sent |
|-------------------|------------|-----------|
| 30 days | First reminder | 3:15 AM daily process |
| 15 days | Second reminder | 3:15 AM daily process |
| 7 days | Final reminder | 3:15 AM daily process |
| 1 day | Last chance | 3:15 AM daily process |

### Grace Period Notifications
| Grace Period Status | Notification Time | Content |
|--------------------|------------------|---------|
| Grace period starts | Immediately when triggered | Welcome to grace period |
| 7 days before expiry | 3:15 AM daily process | First warning |
| 3 days before expiry | 3:15 AM daily process | Urgent warning |
| 1 day before expiry | 3:15 AM daily process | Final notice |

### System Alert Notifications
| Alert Type | Check Frequency | Notification Timing |
|-----------|----------------|-------------------|
| Payment failures | Every hour | Immediate if threshold exceeded |
| System errors | Every 15 minutes | Immediate for critical errors |
| Batch processing | After batch creation | Within 30 minutes of completion |
| Data inconsistencies | Daily at 6:00 AM | Morning summary report |

## Performance Expectations

### Normal Processing Times
| Process Type | Expected Duration | Warning Threshold | Critical Threshold |
|-------------|-------------------|-------------------|-------------------|
| Daily member refresh | 10-30 minutes | >45 minutes | >2 hours |
| Invoice generation | 10-30 minutes | >45 minutes | >90 minutes |
| SEPA batch creation | 15-45 minutes | >60 minutes | >2 hours |
| Payment history update | 30 sec - 2 min | >5 minutes | >15 minutes |

### System Load Impact
| Time Period | Expected Load | Performance Impact |
|------------|---------------|-------------------|
| 2:00-6:00 AM | High | System slower for manual users |
| 6:00 AM-6:00 PM | Medium | Normal performance |
| 6:00 PM-2:00 AM | Low | Best performance for manual work |
| Weekends | Low-Medium | Good performance except Sunday 1-3 AM |

## Configuration Dependencies

### Required System Settings
| Process | Required Setting | Default Value | Impact if Missing |
|---------|-----------------|---------------|-------------------|
| Auto batch creation | `enable_auto_batch_creation` | False | No automatic batches |
| Grace period | `default_grace_period_days` | 30 | No automatic grace periods |
| Email reminders | Email templates exist | N/A | No renewal reminders |
| Payment retries | `payment_retry_enabled` | True | Failed payments not retried |

### Business Day Calculations
- **Weekends**: Saturday and Sunday automatically skipped
- **Holidays**: Configurable holiday calendar respected
- **Business hours**: 6:00 AM - 6:00 PM for most processing
- **Emergency processing**: Available 24/7 with proper permissions

## Troubleshooting Schedule Issues

### Common Timing Problems
| Symptom | Likely Cause | Check These Settings |
|---------|--------------|---------------------|
| Batches not created on schedule | Auto-creation disabled or wrong days | `enable_auto_batch_creation`, `batch_creation_days` |
| Member data outdated | Daily refresh failed | Check system logs for 2:00-2:30 AM |
| No renewal reminders | Missing email templates | Verify renewal email templates exist |
| Payments not retried | Retry system disabled | Check `payment_retry_enabled` setting |

### Performance Issues
| Time Period | Expected Issue | Recommended Action |
|------------|---------------|-------------------|
| 2:00-6:00 AM | System slowness | Schedule heavy manual work for other times |
| First of month | Extended processing | Allow extra time for monthly processes |
| After holidays | Catch-up processing | System may take longer to catch up |
| High member count | Longer process times | Consider upgrading system resources |

## Planning Around Automation

### Best Times for Manual Work
- **Early morning** (6:00-9:00 AM): After daily processing completes
- **Midday** (11:00 AM-2:00 PM): Low system load
- **Evening** (7:00-11:00 PM): Lowest system load
- **Avoid**: 2:00-6:00 AM (heavy processing), Sunday 1:00-3:00 AM (weekly tasks)

### Scheduling Manual Operations
- **SEPA batch review**: Plan for 5:30-7:00 AM on batch creation days
- **Member data imports**: Best during low-load periods (evening/weekend)
- **System maintenance**: Schedule during weekly maintenance window
- **Report generation**: Avoid peak processing times

### Emergency Overrides
- **Manual batch creation**: Available 24/7 with proper permissions
- **Payment processing**: Can override automatic schedules
- **Member updates**: Real-time processing always available
- **Email notifications**: Can be triggered manually anytime

---

This schedule reference helps you understand when automatic processes run and plan your work accordingly. For specific configuration changes or troubleshooting, consult the main Automated Processes Guide or contact your system administrator.
