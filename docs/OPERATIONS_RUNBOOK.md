# Operations Runbook

Procedures for operating and maintaining a Verenigingen system. This document covers recurring operational tasks, monitoring, incident response, and common maintenance procedures.

## Table of Contents

1. [Daily Operations](#daily-operations)
2. [Invoice Generation and Billing](#invoice-generation-and-billing)
3. [SEPA Direct Debit Batches](#sepa-direct-debit-batches)
4. [E-Boekhouden Accounting Sync](#e-boekhouden-accounting-sync)
5. [Mollie Payment Operations](#mollie-payment-operations)
6. [Membership Lifecycle Operations](#membership-lifecycle-operations)
7. [Monitoring and Health Checks](#monitoring-and-health-checks)
8. [Incident Response](#incident-response)
9. [Backup and Recovery](#backup-and-recovery)
10. [Maintenance Procedures](#maintenance-procedures)

---

## Daily Operations

### Morning Checklist

```bash
# 1. Check system services
cd ~/frappe-bench && bench status

# 2. Check for errors in recent logs
cd ~/frappe-bench && tail -50 logs/worker.error.log

# 3. Check pending background jobs
cd ~/frappe-bench && bench --site veg11.veganisme.org show-pending-jobs

# 4. Verify scheduled tasks ran overnight
cd ~/frappe-bench && bench --site veg11.veganisme.org console
```

```python
# In console: check recent scheduler activity
import frappe
from datetime import datetime, timedelta
yesterday = datetime.now() - timedelta(days=1)
logs = frappe.get_all("Scheduled Job Log",
    filters={"creation": [">", yesterday], "status": "Failed"},
    fields=["scheduled_job_type", "status", "creation"],
    order_by="creation desc",
    limit=20)
for log in logs:
    print(f"  FAILED: {log.scheduled_job_type} at {log.creation}")
```

### Scheduled Task Summary

All scheduled tasks are defined in `verenigingen/hooks/scheduler.py`. Key daily tasks to verify:

- **Membership processing**: `process_expired_memberships`, `send_renewal_reminders`
- **Invoice generation**: `generate_dues_invoices`, `auto_create_missing_dues_schedules_scheduled`
- **SEPA processing**: `daily_batch_optimization`, `create_monthly_dues_collection_batch`
- **Payment retries**: `execute_scheduled_payment_retries`
- **E-Boekhouden sync**: `update_dashboard_data_periodically`

For the full task reference, see the Scheduled Tasks section in `ADMIN_GUIDE.md`.

---

## Invoice Generation and Billing

### How the Dues Schedule System Works

1. **Dues Schedule Auto-Creation** (daily): Creates Membership Dues Schedule records for members who lack one. Runs via `services/billing/dues_schedule_auto_creator.py`.
2. **Invoice Generation** (daily): Processes due schedules and creates Sales Invoices. Runs via `membership_dues_schedule.generate_dues_invoices`.
3. **Stuck Schedule Detection** (daily): Identifies and alerts about schedules that failed to generate invoices.

### Manual Invoice Operations

#### Check member dues status

Navigate to `/dues-invoice-debugger` to inspect a specific member's dues status, including schedule state, last invoice date, and any errors.

#### Generate invoices manually

Navigate to `/dues-invoice-manager` for the production interface. This dashboard shows the current billing period, member counts, and allows triggering invoice generation.

#### Analyze coverage gaps

Navigate to `/dues-coverage-manager` to identify members with missing dues periods and generate catch-up invoices.

#### Check for orphaned schedules

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org execute \
  verenigingen.verenigingen.report.orphaned_subscriptions_report.orphaned_subscriptions_report.get_data
```

#### Check and fix stuck schedules

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org execute \
  verenigingen.api.fix_stuck_dues_schedule.check_and_notify_stuck_schedules
```

---

## SEPA Direct Debit Batches

### Batch Creation

Batches are created through two mechanisms:

1. **Automated daily**: `dd_batch_scheduler.daily_batch_optimization` and `sepa_processor.create_monthly_dues_collection_batch` run daily.
2. **Manual via dashboard**: Navigate to `/batch-optimizer` to select invoices, preview batch composition, and submit.

### Mandate Management

- Mandates are created by members via the portal.
- Daily checks detect discrepancies between SEPA mandates and member records (`check_sepa_mandate_discrepancies`).
- Expiring mandate notifications are sent daily (`check_and_send_expiry_notifications`).
- Mandate child table sync runs daily (`periodic_sepa_mandate_child_table_sync`).

### Pain.002 Processing

Bank rejection reports (pain.002 XML) are processed hourly by `services/payment/pain002_ingestion_service.py`. This task:
- Scans the configured email inbox for pain.002 attachments
- Parses bank status reports
- Updates Direct Debit Batch item statuses (rejected, returned, etc.)

### Troubleshooting SEPA Issues

1. Check mandate status on the Member document (SEPA Mandate child table).
2. Verify IBAN validation and BIC derivation.
3. Check batch status in the Direct Debit Batch list.
4. Review pain.002 processing logs in the Scheduled Job Log.

---

## E-Boekhouden Accounting Sync

### Dashboard

Navigate to `/e-boekhouden-dashboard` for the migration dashboard showing:
- Migration progress (accounts, cost centers, customers, suppliers)
- Connection status
- Available data for synchronization

A simpler status view is available at `/e-boekhouden-status`.

### Daily Sync

Dashboard data refreshes daily via `eboekhouden_api.update_dashboard_data_periodically`.

### Configuration

E-Boekhouden API credentials and default company settings are configured in the E-Boekhouden Settings DocType (**Setup -- E-Boekhouden Settings**).

### Migration Services

Account migration and data synchronization services are in `e_boekhouden/services/`. Key service: `account_migration_service.py`.

---

## Mollie Payment Operations

### Payment Retry

Failed Mollie payments are retried daily via
`payment_retry.execute_scheduled_payment_retries`, which sweeps every `SEPA Payment
Retry` in status `Scheduled` whose `next_retry_date` has arrived and runs
`execute_payment_retry` per record.

### Bank Transaction Reconciliation

Bank transactions are matched to invoices daily via `bank_transaction_reconciliation.reconcile_bank_transactions`.

### Subscription Audit

Navigate to `/mollie_subscription_audit` to:
- Run subscription audits without report timeout constraints
- Manage webhook URLs for active subscriptions
- Compare Mollie subscription state with local records

### Member Reconciliation

Navigate to `/mollie_member_reconciliation` for a member-centric view that:
- Shows all Mollie subscriptions per member
- Identifies mismatches between Mollie data and Member records
- Allows updating Member fields to match Mollie state

### Mollie Financial Dashboard

Navigate to `/mollie_dashboard` for an overview of Mollie financial data.

### Webhook Processing

Mollie webhooks are processed by the background service user (`background.service@verenigingen.local`) with the Vereinigingen Webhook User role profile. Webhook processing is handled by `services/payment/mollie_webhook_service.py`.

---

## Membership Lifecycle Operations

### Application Processing

1. Review applications at **Verenigingen -- Membership Application**.
2. Approval triggers: member creation, chapter assignment (by postal code), payment link generation.
3. Overdue application notifications are sent daily.

### Termination Processing

- Overdue termination requests are processed daily (`process_overdue_termination_requests`).
- Compliance auditing runs daily (`audit_termination_compliance`).
- Weekly termination summary reports are generated (`generate_weekly_termination_report`).
- The Membership Termination Workflow (deployed as a fixture) manages state transitions: Draft -- Pending -- Approved -- Executed.
- Termination execution uses FOR UPDATE row locks to prevent race conditions (see `services/termination/termination_execution_service.py`).

### Member Merge

For duplicate member records, use `services/member_merge_service.py`. This service handles:
- Merging contact records and secondary emails
- Transferring financial history
- Deleting the source member and dependencies
- All operations are committed atomically.

### MijnRood Sync

External member data is polled every 15 minutes from the MijnRood remote database via `mijnrood_sync/tasks.py`.

---

## Monitoring and Health Checks

### System Monitoring Dashboard

Navigate to `/monitoring_dashboard` for real-time metrics including:
- System performance metrics (via MonitoringMetricsService)
- Compliance tracking (via ComplianceMetricsService)
- Security monitoring (via SecurityMonitor)

### Alert System

- **Daily alerts**: `alert_manager.run_daily_checks`
- **Hourly alerts**: `alert_manager.run_hourly_checks`
- **Auth monitoring**: `auth_monitoring.alert_if_auth_issues` (daily)
- **Analytics alerts**: `analytics_alert_rule.check_all_active_alerts` (hourly)
- **Security digest**: `critical_operation_rule.send_security_policy_change_digest` (hourly)

### Performance Monitoring

- Bulk performance monitoring runs daily (`bulk_performance_monitor.run_performance_monitoring`).
- Bulk queue health is checked daily (`bulk_queue_config.monitor_bulk_queue_health`).
- Financial history batch processing runs every 30 seconds.

### Data Integrity Checks

- Payment history integrity: validated hourly
- Expense history integrity: validated weekly
- SEPA mandate discrepancies: checked daily

---

## Incident Response

### Severity Levels

| Level | Description | Response Time |
|---|---|---|
| P1 - Critical | Service outage, payment processing failure | Immediate |
| P2 - High | Major feature unavailable (e.g., invoice generation, SEPA batches) | 30 minutes |
| P3 - Medium | Minor feature issue, data inconsistency | 2 hours |
| P4 - Low | Cosmetic issue, non-urgent data fix | Next business day |

### P1 - Service Outage

```bash
# 1. Check service status
cd ~/frappe-bench && bench status

# 2. Check error logs
cd ~/frappe-bench && tail -100 logs/web.log
cd ~/frappe-bench && tail -100 logs/worker.error.log

# 3. Restart services
cd ~/frappe-bench && bench restart

# 4. If database issues
cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache
cd ~/frappe-bench && bench --site veg11.veganisme.org migrate
```

### P2 - Failed Scheduled Tasks

```bash
# Check which tasks failed
cd ~/frappe-bench && bench --site veg11.veganisme.org console
```

```python
import frappe
from datetime import datetime, timedelta
failed = frappe.get_all("Scheduled Job Log",
    filters={"status": "Failed", "creation": [">", datetime.now() - timedelta(hours=24)]},
    fields=["scheduled_job_type", "creation", "details"],
    order_by="creation desc")
for f in failed:
    print(f"{f.scheduled_job_type}: {f.creation}")
    if f.details:
        print(f"  Error: {f.details[:200]}")
```

### P2 - SEPA Batch Failure

1. Check batch status in the Direct Debit Batch list view.
2. Check pain.002 ingestion logs for bank rejections.
3. Use `/batch-optimizer` to create a corrected batch if needed.
4. For individual mandate issues, check the Member document's SEPA Mandate section.

---

## Backup and Recovery

### Backup

```bash
# Database and files backup
cd ~/frappe-bench && bench --site veg11.veganisme.org backup --with-files
```

Backups are stored in `sites/veg11.veganisme.org/private/backups/`.

### Recovery

```bash
# 1. Stop services (if running)
cd ~/frappe-bench && bench restart

# 2. Restore database
cd ~/frappe-bench && bench --site veg11.veganisme.org restore /path/to/backup.sql.gz

# 3. Run migrations to ensure schema consistency
cd ~/frappe-bench && bench --site veg11.veganisme.org migrate

# 4. Rebuild assets and clear cache
cd ~/frappe-bench && bench build
cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache

# 5. Restart services
cd ~/frappe-bench && bench restart
```

---

## Maintenance Procedures

### Weekly Maintenance

```bash
# Backup
cd ~/frappe-bench && bench --site veg11.veganisme.org backup

# Check background job queue health
cd ~/frappe-bench && bench --site veg11.veganisme.org show-pending-jobs
```

### Monthly Maintenance

```bash
# Check for orphaned dues schedules
cd ~/frappe-bench && bench --site veg11.veganisme.org execute \
  verenigingen.verenigingen.report.orphaned_subscriptions_report.orphaned_subscriptions_report.get_data
```

### Cache Management

```bash
# Clear all caches (after configuration changes, permission changes, schema changes)
cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache

# Rebuild assets (after frontend code changes)
cd ~/frappe-bench && bench build
```

### Database Migrations

```bash
# Run all pending patches and schema sync
cd ~/frappe-bench && bench --site veg11.veganisme.org migrate

# Reload a specific DocType schema
cd ~/frappe-bench && bench --site veg11.veganisme.org reload-doctype "DocType Name"
```

### Fixture Deployment

Fixtures (roles, role profiles, workflows, reports, dashboard charts, workspaces) are deployed automatically during migration. To force a re-import:

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org migrate
```

Role profiles can also be deployed independently:

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org execute \
  verenigingen.setup.role_profile_setup.setup_role_profiles_cli
```

### Session Cleanup

Expired sessions are cleaned weekly by the scheduled task `scheduled_session_cleanup`. For manual cleanup:

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org console
```

```python
from verenigingen.utils.session_cleanup_enhanced import scheduled_session_cleanup
scheduled_session_cleanup()
```

### Audit Log Cleanup

Old security audit logs are cleaned daily by `cleanup_old_audit_logs`. This is automatic and requires no manual intervention under normal operation.

---

## Logs

| Log | Location | Content |
|---|---|---|
| Application log | `~/frappe-bench/logs/web.log` | Web server requests and errors |
| Worker error log | `~/frappe-bench/logs/worker.error.log` | Background job failures |
| Worker log | `~/frappe-bench/logs/worker.log` | Background job output |
| Site log | `~/frappe-bench/sites/veg11.veganisme.org/logs/` | Site-specific logs |
| Scheduler log | Check Scheduled Job Log DocType in Desk | Task execution history |

---

## Quick Reference: Admin Dashboard URLs

| URL | Purpose |
|---|---|
| `/dues-invoice-manager` | Dues invoice generation and SEPA batch processing |
| `/dues-invoice-debugger` | Debug individual member dues status |
| `/dues-coverage-manager` | Coverage gap analysis and catch-up invoices |
| `/batch-optimizer` | SEPA DD batch creation |
| `/e-boekhouden-dashboard` | E-Boekhouden migration dashboard |
| `/e-boekhouden-status` | E-Boekhouden connection status |
| `/email-group-admin` | Email group management |
| `/mollie_dashboard` | Mollie financial overview |
| `/mollie_subscription_audit` | Mollie subscription audit |
| `/mollie_member_reconciliation` | Mollie-member data reconciliation |
| `/monitoring_dashboard` | System monitoring and compliance |
| `/chapter` | Public chapter directory |
