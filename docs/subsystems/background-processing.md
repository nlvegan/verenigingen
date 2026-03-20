# Background Processing System

## Overview

The Background Processing System provides asynchronous task management for the Verenigingen association management platform. Scheduled tasks are defined in `hooks/scheduler.py` and document event hooks in `hooks/doc_events.py`. Both are organized into a modular hooks package (`hooks/__init__.py`) rather than a monolithic `hooks.py` file.

## Hooks Package Architecture

The hooks package at `hooks/__init__.py` imports from focused submodules:

- `hooks/scheduler.py` -- Scheduled task definitions
- `hooks/doc_events.py` -- Document event handlers
- `hooks/permissions.py` -- Permission queries and has_permission handlers
- `hooks/assets.py` -- CSS/JS includes
- `hooks/doctypes.py` -- DocType JS mappings
- `hooks/fixtures.py` -- Fixture definitions
- `hooks/portal.py` -- Portal configuration
- `hooks/lifecycle.py` -- Install/migrate hooks

## Scheduled Tasks

### Daily Tasks (29 tasks)

**Member and Membership:**
- `refresh_all_member_financial_histories`
- `process_expired_memberships`, `send_renewal_reminders`, `notify_about_orphaned_records`
- `send_overdue_notifications`

**Billing and Dues:**
- `auto_create_missing_dues_schedules_scheduled`, `generate_dues_invoices`
- `check_and_notify_stuck_schedules`, `update_all_goals`

**Termination:**
- `process_overdue_termination_requests`, `audit_termination_compliance`

**SEPA:**
- `check_sepa_mandate_discrepancies`, `periodic_sepa_mandate_child_table_sync`
- `check_and_send_expiry_notifications`
- `daily_batch_optimization`, `create_monthly_dues_collection_batch`

**Email:**
- `scheduled_email_group_sync`, `process_scheduled_campaigns`
- `process_contact_request_automation`

**Payment:**
- `execute_payment_retry`, `reconcile_bank_transactions`, `process_overdue_installments`

**Volunteer/Expense:**
- `refresh_all_expense_approvers`, `sync_all_department_approvers`
- `process_pending_expense_history_updates`

**E-Boekhouden:** `update_dashboard_data_periodically`

**Security:** `cleanup_old_audit_logs`, `run_daily_checks`, `alert_if_auth_issues`

**Performance:** `run_performance_monitoring`, `monitor_bulk_queue_health`

**Address:** `update_all_member_address_fingerprints`

### Hourly Tasks (7 tasks)

- `send_security_policy_change_digest`
- `check_all_active_alerts`
- `run_hourly_checks`
- `validate_payment_history_integrity`
- `process_retry_queues`
- `process_pending_amendments`
- `run_pain002_ingestion`

### Weekly Tasks (5 tasks)

- `generate_weekly_termination_report`
- `weekly_security_health_check`
- `refresh_member_address_displays`
- `validate_expense_history_integrity`
- `scheduled_session_cleanup`

### Monthly Tasks (2 tasks)

- `cleanup_orphaned_address_data`
- `cleanup_orphaned_expense_history`

### Cron Jobs

- **Every 30 seconds**: `schedule_financial_history_processing`
- **Every 15 minutes**: `run_mijnrood_sync` -- MijnRood remote DB sync

## Document Event Processing

### Event Handlers by DocType

From `hooks/doc_events.py` (17 DocTypes with handlers):

**Core Membership:** Member (before_save, after_save x3, on_update x2), Membership (on_submit x2, on_cancel x2, on_update), Chapter Member (after_save, on_trash)

**Chapter System:** Chapter (after_save, on_update), Chapter Role (on_update)

**Team:** Team (on_update x3)

**Volunteer:** Verenigingen Volunteer (on_update x4)

**Financial - Payments:** Payment Entry (on_submit x6, on_cancel x2, on_trash x2), Sales Invoice (before_validate x3, validate x2, after_validate, on_submit x3, on_update_after_submit x2, on_cancel x2, on_trash), Journal Entry (validate, on_submit), Bank Transaction (on_submit)

**Financial - Expenses:** Expense Claim (validate, on_submit x2, on_update_after_submit, on_cancel x2), Purchase Invoice (validate)

**SEPA:** SEPA Mandate (after_save x2, on_submit, on_cancel, on_trash)

**Donations:** Donation (after_insert x2, on_update x2, on_submit, on_cancel, on_trash), Donor (on_update)

**Customer:** Customer (validate, on_update x2)

**Termination:** Membership Termination Request (on_update_after_submit)

**Settings:** Verenigingen Settings (on_update x2)

**Security:** User (on_update x3, after_insert x2), Role Profile (on_update, after_insert, on_trash), Has Role (on_update, after_insert, on_trash)

### Background Job Queuing

Heavy operations deferred via `utils/background_jobs.py`:

- `queue_member_payment_history_update_handler` -- on Payment Entry events
- `queue_expense_event_processing_handler` -- on Payment Entry submit
- `queue_donor_auto_creation_handler` -- on Payment Entry submit

## Cache Invalidation Architecture

Cache invalidation is event-driven via doc_events:

**Performance Cache (`utils/performance_cache.py`):**
- Invalidated on Member, Membership, Chapter Member changes
- Covers member display data and financial summaries

**Chapter Lookup Cache (`services/chapter/optimized_chapter_lookup.py`):**
- Invalidated on Chapter save and Verenigingen Settings update
- Caches chapter-postal-code mappings

**Security Cache (`utils/security/cache_invalidation.py`):**
- Invalidated on User, Role Profile, Has Role changes
- Caches user role information

**General Cache (`utils/cache_invalidation.py`):**
- Invalidated on Member, Customer, SEPA Mandate, Sales Invoice, Payment Entry changes
- Event-specific handlers: `on_document_update`, `on_document_submit`, `on_document_cancel`

## Error Handling Patterns

### Retry Logic

- `utils/bulk_retry_processor.py` -- Hourly retry of failed bulk operations
- `vereinigingen_payments/utils/payment_retry.py` -- Daily payment retry
- `services/billing/invoice_error_handler_service.py` -- Invoice generation retry

### Monitoring and Alerting

- `utils/alert_manager.py` -- Daily and hourly health checks
- `utils/auth_monitoring.py` -- Authentication issue detection
- `utils/bulk_performance_monitor.py` -- Performance monitoring
- `utils/bulk_queue_config.py` -- Queue health monitoring

## Additional Configuration

### Override DocType Class

```python
override_doctype_class = {
    "Payment Entry": "verenigingen.overrides.payment_entry.PaymentEntry"
}
```

### CLI Commands

- `workspace`, `workspace_health`, `workspace_maintenance`

## Key File Locations

- **Hooks package**: `hooks/__init__.py`
- **Scheduler**: `hooks/scheduler.py` (29 daily + 7 hourly + 5 weekly + 2 monthly + 2 cron)
- **Doc events**: `hooks/doc_events.py` (17 DocTypes)
- **Permissions**: `hooks/permissions.py` (15 query conditions + 12 has_permission)
- **Background jobs**: `utils/background_jobs.py`
- **MijnRood sync**: `mijnrood_sync/tasks.py`
