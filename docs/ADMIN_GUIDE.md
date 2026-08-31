# Administrator Guide

This guide covers administering a Verenigingen system, from initial setup to daily operations and maintenance.

## Table of Contents

- [Getting Started](#getting-started)
- [User Management](#user-management)
- [System Configuration](#system-configuration)
- [Admin Dashboards (www/)](#admin-dashboards-www)
- [Member Management](#member-management)
- [Financial Management](#financial-management)
- [Scheduled Tasks](#scheduled-tasks)
- [Communication Management](#communication-management)
- [Reporting and Analytics](#reporting-and-analytics)
- [Maintenance and Troubleshooting](#maintenance-and-troubleshooting)

## Getting Started

### First Login and Orientation

After installation, your first steps as an administrator:

1. **Access the System**
   - Navigate to your site URL
   - Login with Administrator credentials
   - You will see the ERPNext desktop with Verenigingen modules

2. **Key Areas Overview**
   - **Verenigingen Module**: Core association management
   - **Accounting**: Financial management and reporting
   - **CRM**: Contact and communication management
   - **HRMS**: Employee and volunteer management
   - **Settings**: System configuration

## User Management

### Roles

The following custom roles are defined in fixtures and deployed with the app:

| Role | Purpose |
|------|---------|
| Verenigingen Administrator | Full association management access |
| Verenigingen Staff | Day-to-day operational access |
| Verenigingen Governance Auditor | Read-only audit and compliance access |
| Verenigingen Chapter Board Member | Chapter-level management |
| Verenigingen Member | Member portal self-service |
| Verenigingen Volunteer | Volunteer portal self-service |

### Role Profiles

Role profiles bundle multiple roles for assignment to users. These are defined in `verenigingen/fixtures/role_profile.json` and deployed as fixtures during migration.

| Role Profile | Included Roles | Use Case |
|---|---|---|
| Verenigingen System Administrator | Verenigingen Administrator, System Manager, Administrator, All | Full system access |
| Verenigingen Administrator | Verenigingen Administrator, Verenigingen Staff, System Manager, Accounts Manager, Sales Manager, Purchase Manager, Projects User, Employee, Verenigingen Member | Association administrators |
| Verenigingen Treasurer | Verenigingen Staff, Accounts Manager, Purchase Manager, Sales Manager, Stock Manager, Projects Manager, Expense Approver, Dashboard Manager, Verenigingen Financial Manager, Verenigingen Chapter Board Member, Verenigingen National Board Member, Employee, Employee Self Service, Verenigingen Member | Financial operations |
| Verenigingen National Board Member | Verenigingen Staff, Verenigingen Chapter Board Member, Verenigingen Volunteer, Projects User, Projects Manager, Expense Approver, Website Manager, Auditor, Employee, Employee Self Service, Verenigingen Member | National board oversight |
| Verenigingen Chapter Board Member | Verenigingen Chapter Board Member, Verenigingen Volunteer, Projects User, Projects Manager, Expense Approver, Accounts User, Sales User, Purchase User, Employee, Employee Self Service, Verenigingen Member | Chapter-level management |
| Verenigingen Staff | Verenigingen Staff, Support Team, Accounts User, Sales User, Purchase User, Projects User, Employee, Employee Self Service, Verenigingen Member | Office staff |
| Verenigingen Team Leader | Verenigingen Volunteer, Projects User, Expense Approver, Employee, Employee Self Service, Verenigingen Member | Volunteer team leads |
| Verenigingen Volunteer | Verenigingen Volunteer, Projects User, Employee, Employee Self Service, Verenigingen Member | Active volunteers |
| Verenigingen Auditor | Verenigingen Volunteer, Auditor, Employee, Verenigingen Member | Governance auditors |
| Verenigingen Member | Verenigingen Member, All | Regular members (portal access) |
| Verenigingen Webhook User | Verenigingen Webhook User, Accounts User, Sales User | Background service account for Mollie webhooks |

### Creating User Accounts

1. Go to **Users and Permissions -- User** and click **New**.
2. Fill in email, first name, last name, and check **Send Welcome Email**.
3. Assign the appropriate role profile from the table above.
4. Optionally link the user account to an existing Member or Volunteer record.

### Automated Role Profile Deployment

Deploy all role profiles from fixtures:

```bash
bench --site [site_name] execute vereinigingen.setup.role_profile_setup.setup_role_profiles_cli
```

Alternative methods:

```bash
bench --site [site_name] execute vereinigingen.setup.role_profile_setup.setup_role_profiles
bench --site [site_name] execute vereinigingen.setup.role_profile_setup.deploy_role_profiles
```

### Permission Model

Row-level security is enforced via permission query conditions and has_permission handlers (defined in `vereinigingen/hooks/permissions.py`) for these DocTypes:

- **Member**, **Membership**, **Membership Termination Request** -- scoped by chapter/role
- **Chapter**, **Chapter Member** -- scoped by chapter board membership
- **Team**, **Team Member** -- scoped by team membership
- **Volunteer** -- scoped by chapter/team
- **Address**, **Donor**, **Donation** -- scoped by member ownership
- **Membership Dues Schedule** -- scoped by member
- **Project** -- scoped by team membership
- **Expense Claim** -- scoped by employee/approver
- **Event Contact Campaign** -- scoped by creator/assignee

### Chapter-Based Access Control

Users see only data from their assigned chapters. This is configured through Chapter Member assignments and enforced automatically in list views and reports.

## System Configuration

### Organization Setup

#### Company Configuration

1. Go to **Accounting -- Company** and update organization information.
2. Set fiscal year and accounting settings.
3. For e-Boekhouden integration, go to **Setup -- E-Boekhouden Settings** and configure API credentials.

#### Chapter Management

1. Go to **Verenigingen -- Chapter** to create geographic regions.
2. Define postal code patterns for automatic member assignment.
3. Assign board members and configure chapter-specific permissions.

### Brand Settings

Brand settings are automatically created with defaults during migration (via `after_migrate` hook). The Brand Settings DocType controls primary, secondary, and accent colors applied across portal pages via CSS variables (`var(--brand-primary)`, `var(--brand-secondary)`).

### Email System Configuration

#### Email Templates

Install the comprehensive email template system:

```bash
bench --site [site_name] execute vereinigingen.api.email_template_manager.create_comprehensive_email_templates
```

Template categories: membership communications, payment notifications, SEPA mandate notifications, volunteer assignment notifications, and system alerts.

All notification routing is controlled by the Email Configuration DocType, not by Frappe's built-in Notification system. This is documented in `hooks/fixtures.py`.

## Admin Dashboards (www/)

The following admin dashboards are served as web pages from `vereinigingen/www/`. Access them by navigating to the URL path on your site.

| URL Path | HTML File | Purpose | Access |
|---|---|---|---|
| `/dues-invoice-manager` | `dues-invoice-manager.html` | Production interface for managing membership dues invoicing and SEPA batch processing. Shows current billing period, member status, and invoice generation controls. | System Manager or Vereinigingen Staff |
| `/dues-invoice-debugger` | `dues-invoice-debugger.html` | Debugging interface for checking individual member dues status and diagnosing invoicing issues. | System Manager |
| `/dues-coverage-manager` | `dues-coverage-manager.html` | Interactive coverage gap analysis tool. Identifies members with missing dues periods and generates catch-up invoices. | System Manager or Vereinigingen Staff |
| `/batch-optimizer` | `batch-optimizer.html` | Interface for creating optimized SEPA Direct Debit batches. Allows selecting invoices, previewing batches, and submitting for processing. | Users with Direct Debit Batch create permission |
| `/e-boekhouden-dashboard` | `e-boekhouden-dashboard.html` | Migration dashboard for the e-Boekhouden accounting integration. Shows migration progress (accounts, cost centers, customers, suppliers), connection status, and data synchronization state. | Logged-in users (guest blocked) |
| `/e-boekhouden-status` | `e-boekhouden-status.html` | Simpler status view for e-Boekhouden connection and sync status. Uses direct API calls for data retrieval. | Logged-in users |
| `/email-group-admin` | `email-group-admin.html` | Email group administration for managing mailing lists and member subscriptions. | System Manager or Vereinigingen Staff |
| `/mollie_dashboard` | `mollie_dashboard.html` | Mollie financial dashboard. No server-side Python context (static/client-side). | Depends on client-side checks |
| `/mollie_subscription_audit` | `mollie_subscription_audit.html` | Audit interface for Mollie subscriptions. Runs subscription audits without report timeout constraints and manages webhook URLs for active subscriptions. | Critical API access (admin) |
| `/mollie_member_reconciliation` | `mollie_member_reconciliation.html` | Member-centric view for reconciling Mollie subscription data with Member records. Shows all subscriptions per member and allows updating Member fields. | Critical API access (admin) |
| `/monitoring_dashboard` | `monitoring_dashboard.html` | System monitoring dashboard with real-time metrics, security monitoring, and compliance tracking. Delegates to MonitoringMetricsService, ComplianceMetricsService, and SecurityMonitor. | Logged-in users |
| `/chapter` | `chapter.html` | Public-facing chapter directory. Allows visitors to explore chapters; provides enhanced features for authenticated members (chapter joining, volunteer sign-up). | Public (enhanced for members) |

### Portal Menu Items

These portal links appear in the user sidebar menu for users with the corresponding roles (defined in `hooks/portal.py`):

| Title | Route | Required Role |
|---|---|---|
| Member Portal | `/member_portal` | Verenigingen Member |
| Volunteer Portal | `/volunteer_portal` | Verenigingen Volunteer |
| Upload Documents | `/board/document_upload` | Verenigingen Chapter Board Member |
| Browse Documents | `/board/document_browser` | Verenigingen Member |

## Member Management

### Membership Types and Pricing

Go to **Verenigingen -- Membership Type** to create membership types with fee amounts, billing frequency, grace periods, auto-renewal settings, and SEPA eligibility.

Members can adjust their own fee amounts via the member portal.

### Member Lifecycle

1. **Application Review**: Go to **Verenigingen -- Membership Application** to review submitted applications. Chapter assignment happens based on postal codes.
2. **Approval**: Approve or reject applications. Approval triggers automatic member creation and payment link generation.
3. **Status Management**: Members transition through Active, Inactive, Suspended, and Terminated statuses.
4. **Termination**: Handled through Membership Termination Request documents with a workflow (Draft -- Pending -- Approved -- Executed).

### Chapter Assignment

Configure postal code patterns on Chapter documents for automatic assignment. Manual overrides and reassignment history are tracked through the Chapter Member DocType.

## Financial Management

### Invoice Generation (Dues Schedule System)

The dues schedule system handles recurring membership fee invoicing:

1. **Auto-creation**: Missing dues schedules are created daily by `dues_schedule_auto_creator.auto_create_missing_dues_schedules_scheduled`.
2. **Invoice generation**: `membership_dues_schedule.generate_dues_invoices` runs daily to create Sales Invoices from due schedules.
3. **Stuck schedule monitoring**: `fix_stuck_dues_schedule.check_and_notify_stuck_schedules` alerts administrators about schedules that failed to process.

Use the `/dues-invoice-manager` dashboard for manual invoice generation and the `/dues-coverage-manager` for gap analysis.

### SEPA Direct Debit

1. **Configuration**: Go to **Accounting -- SEPA Direct Debit Settings** to set up creditor identifier and mandate parameters.
2. **Mandate management**: Members create mandates via the member portal. BIC derivation is automatic for Dutch IBANs.
3. **Batch creation**: Use `/batch-optimizer` or the daily scheduler task (`dd_batch_scheduler.daily_batch_optimization`).
4. **Monthly collection**: `sepa_processor.create_monthly_dues_collection_batch` runs daily.
5. **Mandate monitoring**: Daily tasks check for mandate discrepancies and expiring mandates.
6. **Pain.002 ingestion**: Hourly task scans inbox for bank status reports and updates batch statuses.

### Mollie Payment Processing

- Payment retries execute daily via `payment_retry.execute_scheduled_payment_retries`
  (a sweep over due `SEPA Payment Retry` records).
- Bank transaction reconciliation runs daily.
- Subscription auditing and member reconciliation are available via the admin dashboards listed above.
- Webhooks are processed by the background service user (Vereinigingen Webhook User role profile).

### E-Boekhouden Accounting Sync

- Dashboard data updates daily via `eboekhouden_api.update_dashboard_data_periodically`.
- Monitor sync status at `/e-boekhouden-dashboard` or `/e-boekhouden-status`.
- Migration services are in `e_boekhouden/services/`.

### Donation Tracking

Donations are tracked through the Donation DocType with automatic Donor record creation on payment submission. Campaign progress updates automatically.

### Financial Reporting

- **Membership Revenue Projection** report (fixture)
- Payment status and SEPA batch reports via ERPNext Report Builder
- Dashboard charts: Member Count by Chapter, Monthly Dues Revenue, Outstanding Dues Invoices by Month, Dues Revenue by Payment Status, SEPA Payment Status, and more (deployed as fixtures)

## Scheduled Tasks

All scheduled tasks are defined in `vereinigingen/hooks/scheduler.py`. Tasks are idempotent and handle their own error recovery.

### Daily Tasks

| Task | Description |
|---|---|
| `refresh_all_member_financial_histories` | Rebuild financial history for all members |
| `scheduled_email_group_sync` | Sync member data to email groups |
| `process_scheduled_campaigns` | Process scheduled email campaigns |
| `process_expired_memberships` | Mark expired memberships as inactive |
| `send_renewal_reminders` | Send membership renewal reminder emails |
| `notify_about_orphaned_records` | Alert about memberships without active members |
| `send_overdue_notifications` | Notify about overdue membership applications |
| `auto_create_missing_dues_schedules_scheduled` | Create dues schedules for members missing them |
| `generate_dues_invoices` | Generate Sales Invoices from due schedules |
| `check_and_notify_stuck_schedules` | Alert about stuck dues schedules |
| `update_all_goals` | Update membership goal progress metrics |
| `process_overdue_termination_requests` | Process termination requests past their date |
| `audit_termination_compliance` | Check termination process compliance |
| `check_sepa_mandate_discrepancies` | Detect mismatches between SEPA mandates and member records |
| `periodic_sepa_mandate_child_table_sync` | Sync SEPA mandate child table entries |
| `process_contact_request_automation` | Process queued member contact requests |
| `update_dashboard_data_periodically` | Refresh e-Boekhouden dashboard data |
| `execute_scheduled_payment_retries` | Retry failed Mollie payments (sweeps due retries) |
| `reconcile_bank_transactions` | Match bank transactions to invoices |
| `check_and_send_expiry_notifications` | Notify about expiring SEPA mandates |
| `refresh_all_expense_approvers` | Update expense claim approver assignments |
| `sync_all_department_approvers` | Sync department-level expense approvers |
| `process_pending_expense_history_updates` | Process queued expense history updates |
| `daily_batch_optimization` | Optimize SEPA DD batch scheduling |
| `create_monthly_dues_collection_batch` | Create monthly SEPA DD collection batch |
| `create_scheduled_snapshots` | Create membership analytics snapshots |
| `process_overdue_installments` | Handle overdue payment plan installments |
| `cleanup_old_audit_logs` | Remove old security audit log entries |
| `run_daily_checks` | Daily system health alert checks |
| `alert_if_auth_issues` | Check for authentication anomalies |
| `run_performance_monitoring` | Collect performance metrics |
| `monitor_bulk_queue_health` | Check bulk operation queue health |
| `update_all_member_address_fingerprints` | Update address deduplication fingerprints |

### Hourly Tasks

| Task | Description |
|---|---|
| `send_security_policy_change_digest` | Digest of critical operation rule changes |
| `check_all_active_alerts` | Evaluate all analytics alert rules |
| `run_hourly_checks` | Hourly system health alert checks |
| `validate_payment_history_integrity` | Verify payment history data consistency |
| `process_retry_queues` | Process bulk operation retry queues |
| `process_pending_amendments` | Process contribution amendment requests |
| `run_pain002_ingestion` | Scan inbox for SEPA pain.002 bank status reports and update batch statuses |

### Weekly Tasks

| Task | Description |
|---|---|
| `generate_weekly_termination_report` | Weekly summary of termination activity |
| `weekly_security_health_check` | Security posture assessment |
| `refresh_member_address_displays` | Update cached address display strings |
| `validate_expense_history_integrity` | Check expense history data consistency |
| `scheduled_session_cleanup` | Clean up expired user sessions |

### Monthly Tasks

| Task | Description |
|---|---|
| `cleanup_orphaned_address_data` | Remove orphaned address records |
| `cleanup_orphaned_expense_history` | Remove orphaned expense history entries |

### Cron Jobs (High Frequency)

| Schedule | Task | Description |
|---|---|---|
| Every 30 seconds | `schedule_financial_history_processing` | Process queued financial history batch updates |
| Every 15 minutes | `run_mijnrood_sync` | Poll MijnRood remote database for member changes |

## Communication Management

### Email Group Sync

Member data syncs to email groups daily. Changes to Member documents also trigger immediate sync via the `after_save` doc event. Manage email groups at `/email-group-admin`.

### Automated Notifications

All notifications are handled by custom code that reads from the Email Configuration DocType. Frappe's built-in Notification system is not used. Notification types include:

- Member approval/rejection
- SEPA mandate status changes
- Member status changes
- Invoice overdue alerts
- New application alerts (admin)
- Expense approval notifications

## Reporting and Analytics

### Dashboard Charts (Fixtures)

These charts are deployed as fixtures and appear in the Verenigingen workspace:

- Member Count by Chapter
- Member Count Trends
- Member Applications and Exits
- Member Age Distribution
- Member Pronoun Distribution
- Members with Outstanding Invoices
- SEPA Payment Status
- Monthly Dues Revenue
- Outstanding Dues Invoices by Month
- Dues Revenue by Payment Status
- Dues Revenue by Quarter

### Dashboards (Fixtures)

- **Member Analytics**: Member statistics and demographic analysis
- **Member payment development**: Payment collection trends

### Reports (Fixtures)

- **Termination Audit Report**: Audit trail for membership terminations
- **Termination Compliance Report**: Compliance verification for termination processes
- **Membership Revenue Projection**: Revenue forecasting based on active memberships

## Maintenance and Troubleshooting

### Regular Maintenance

**Daily**:

```bash
# Check system status
cd ~/frappe-bench && bench status

# Review error logs
cd ~/frappe-bench && bench logs
```

**Weekly**:

```bash
# Backup database
cd ~/frappe-bench && bench --site veg11.veganisme.org backup
```

**Monthly**:

```bash
# Check for orphaned dues schedules
cd ~/frappe-bench && bench --site veg11.veganisme.org execute \
  verenigingen.verenigingen.report.orphaned_subscriptions_report.orphaned_subscriptions_report.get_data
```

### After-Migrate Hooks

These run automatically after `bench migrate` (defined in `hooks/lifecycle.py`):

1. Ensure required payment modes exist
2. Create default brand settings
3. Set up security framework
4. Create database indexes for coverage duplicate checks and chapter dashboard performance
5. Run performance optimization setup
6. Sync document category options to DocType metadata

### Troubleshooting Common Issues

#### Payment Processing Issues

1. Check SEPA mandate status and IBAN validation on the Member document.
2. Review payment retry logs -- retries execute daily.
3. For Mollie issues, use `/mollie_subscription_audit` to audit subscription state.
4. Use `/mollie_member_reconciliation` to reconcile Mollie data with member records.

#### Dues Invoice Issues

1. Use `/dues-invoice-debugger` to check individual member dues status.
2. Use `/dues-coverage-manager` to identify coverage gaps.
3. Check for stuck schedules -- the daily task sends notifications, or run manually:
   ```bash
   bench --site [site_name] execute \
     vereinigingen.api.fix_stuck_dues_schedule.check_and_notify_stuck_schedules
   ```

#### User Access Issues

1. Verify role profile assignment on the User document.
2. Check chapter-based access restrictions via Chapter Member records.
3. For permission debugging:
   ```python
   frappe.has_permission("DocType", "read", doc="document-name")
   ```

#### Cache Issues

```bash
cd ~/frappe-bench && bench --site [site_name] clear-cache
```

#### Schema Out of Sync

```bash
cd ~/frappe-bench && bench --site [site_name] migrate
# Or for a specific DocType:
cd ~/frappe-bench && bench --site [site_name] reload-doctype "DocType Name"
```

### Emergency Procedures

#### Service Restart

```bash
cd ~/frappe-bench && bench restart
```

#### Database Recovery

```bash
cd ~/frappe-bench && bench --site [site_name] restore /path/to/backup.sql.gz
```

#### Post-Recovery

```bash
cd ~/frappe-bench && bench --site [site_name] migrate
cd ~/frappe-bench && bench build
cd ~/frappe-bench && bench --site [site_name] clear-cache
```

### Fixtures Reference

The following data is deployed via fixtures during migration (defined in `hooks/fixtures.py`):

- **Property Setter** and **Custom DocPerm**: Schema customizations for ERPNext DocTypes
- **Workflow**: Membership Termination Workflow (with states: Draft, Pending, Approved, Executed, etc.)
- **Roles**: The 6 custom Verenigingen roles listed above
- **Role Profiles**: The 11 role profiles listed above
- **Reports**: Termination Audit, Termination Compliance, Membership Revenue Projection
- **Custom Fields**: BTW (VAT) fields, e-Boekhouden grootboek nummer field
- **Workspaces**: E-Boekhouden, Verenigingen, Verenigingen Payments
- **Dashboard Charts**: 11 charts covering membership and financial metrics
- **Dashboards**: Member Analytics, Member payment development
- **Vereinigingen Settings**: Singleton configuration document
- **Background Service User**: `background.service@verenigingen.local` with Webhook User role

---

This administrator guide covers core system administration tasks. For technical details on services and transaction handling, see `CLAUDE.md`. For operational procedures, see `OPERATIONS_RUNBOOK.md`.
