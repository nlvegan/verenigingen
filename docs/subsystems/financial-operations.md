# Financial Operations System

## Overview

The Financial Operations System provides comprehensive financial management for Dutch non-profit associations, integrating SEPA direct debit processing, automated dues collection, and European banking compliance. This system handles the complete payment lifecycle from member onboarding through payment collection, reconciliation, and accounting integration.

## Core Architecture

### Billing Services (`services/billing/`)

The billing service layer contains 22 specialized modules:

**Invoice Generation Pipeline:**

- `invoice_generation_orchestrator.py` -- Top-level orchestrator for the invoice pipeline
- `invoice_generator.py` -- Core invoice creation logic
- `bulk_invoice_generation_service.py` -- Batch invoice generation for multiple members
- `invoice_management.py` -- Invoice lifecycle operations
- `invoice_error_handler_service.py` -- Error recovery and retry for failed invoice generation
- `invoice_matcher.py` -- Payment-to-invoice matching logic
- `duplicate_invoice_detector.py` -- Prevents duplicate invoice creation
- `sales_invoice_hooks.py` -- Doc event hooks for Sales Invoice (set_member_from_customer, populate_member_chapter, on_trash)
- `sales_invoice_account_handler.py` -- Sets membership receivable account on validation

**Dues Schedule Management:**

- `dues_schedule_creation_service.py` -- Creates new dues schedules for members
- `dues_schedule_auto_creator.py` -- Daily scheduled auto-creation of missing dues schedules
- `dues_schedule_lifecycle_service.py` -- Schedule status transitions and lifecycle management
- `dues_schedule_validation_service.py` -- Validates schedule configuration and business rules
- `dues_schedule_permission_service.py` -- Permission checks for schedule operations
- `dues_schedule_health_manager.py` -- Monitors and reports stuck/unhealthy schedules
- `template_configuration_service.py` -- Manages dues schedule templates
- `template_creation_service.py` -- Creates new schedule templates

**Calculation and Period Management:**

- `billing_period_calculator.py` -- Calculates billing period start/end dates
- `billing_date_service.py` -- Date arithmetic for billing operations
- `billing_constants.py` -- Shared constants for billing logic
- `coverage_calculator.py` -- Calculates dues coverage periods
- `coverage_overlap_detector.py` -- Detects overlapping coverage periods
- `eligibility_checker.py` -- Checks member eligibility for invoicing

**Fee Management:**

- `fee_change_tracking_service.py` -- Tracks changes to membership fees
- `progressive_dues_service.py` -- Progressive/tiered dues calculation

### Payment Services (`services/payment/`)

Specialized payment processing modules:

- `sepa_mandate_manager.py` -- SEPA mandate lifecycle management
- `sepa_batch_approval_service.py` -- Approval workflow for direct debit batches
- `sepa_batch_state_machine.py` -- State transitions for batch processing
- `sepa_upload_guard.py` -- Safety checks before SEPA file upload to bank
- `pain002_ingestion_service.py` -- Parses bank pain.002 status reports (hourly scheduled task)
- `validation_service.py` -- Payment data validation
- `mollie_reconciliation_service.py` -- Reconciles Mollie payments with invoices
- `mollie_webhook_service.py` -- Processes Mollie webhook events
- `alert_manager.py` -- Payment-related alerts and notifications

### SEPA Direct Debit Infrastructure

#### SEPA Mandate Management (`SEPA Mandate`)

European banking compliance system for payment authorization:

**Core Fields:**

- **Mandate Details**: mandate_id (unique reference), member, status, mandate_type, scheme
- **Bank Information**: account_holder_name, iban, bic, bank_name
- **Validity Management**: sign_date, first_collection_date, expiry_date, is_active
- **Usage Tracking**: frequency, maximum_amount, used_for_memberships, used_for_donations
- **History**: usage_history (table), cancellation_reason

**Business Rules:**

- SEPA compliance with pre-notification requirements
- Mandate reference uniqueness across organization
- Dutch IBAN format validation
- Daily discrepancy checks via `check_sepa_mandate_discrepancies` and `periodic_sepa_mandate_child_table_sync`

#### Direct Debit Batch Processing (`Direct Debit Batch`)

SEPA XML file generation and batch payment management:

**Workflow States:**

1. **Draft**: Initial batch creation and invoice addition
2. **Generated**: SEPA file generated and validated
3. **Submitted**: Batch submitted for processing
4. **Processed**: Successfully processed by bank
5. **Failed**: Processing failed, requires intervention

**Scheduled Tasks:**

- Daily: `daily_batch_optimization` and `create_monthly_dues_collection_batch`
- Hourly: `run_pain002_ingestion` (bank status report processing)

### Membership Dues Management

#### Dues Schedule System (`Membership Dues Schedule`)

Automated billing system with flexible frequency and contribution models:

**Billing Frequencies:**

- Annual, Semi-Annual, Quarterly, Monthly, Daily, Custom

**Contribution Modes:**

1. **Tier**: Predefined membership tier amounts
2. **Calculator**: Algorithm-based calculation with multipliers
3. **Custom**: Manually set amounts with approval workflow

**Scheduled Processing:**

- Daily: `generate_dues_invoices` scans schedules approaching invoice date
- Daily: `auto_create_missing_dues_schedules_scheduled` creates schedules for members without one
- Daily: `check_and_notify_stuck_schedules` identifies schedules that failed to generate invoices
- Hourly: `process_pending_amendments` handles contribution amendment requests

### Document Event Hooks

From `hooks/doc_events.py`:

**Sales Invoice:**
- `before_validate`: Tax exemption, set member from customer, populate member chapter
- `validate`: Custom validation, set membership receivable account
- `on_submit`/`on_cancel`: Invoice event emission, cache invalidation

**Payment Entry:**
- `on_submit`: Queue payment history update, payment notifications, donor auto-creation, expense event processing
- `on_cancel`/`on_trash`: Queue payment history update, cache invalidation

**SEPA Mandate:**
- `after_save`/`on_submit`/`on_cancel`/`on_trash`: Cache invalidation and performance event handlers

### Error Handling and Recovery

- Failed invoice generation retry via `invoice_error_handler_service.py`
- Payment retry processing: daily `execute_scheduled_payment_retries`
- Bulk retry processor: hourly `process_retry_queues`
- Amendment processing: hourly for same-day turnaround

### Background Job Architecture

#### Scheduled Financial Operations (from `hooks/scheduler.py`)

**Daily:**
- Member financial history refresh
- Dues invoice generation
- Auto-create missing dues schedules
- Stuck schedule notifications
- SEPA mandate discrepancy checks
- Payment retry processing
- Bank transaction reconciliation
- SEPA expiry notifications
- Direct debit batch optimization and monthly collection
- Payment plan overdue installment processing

**Hourly:**
- Payment history validation and repair
- Bulk retry processor
- Contribution amendment processing
- pain.002 bank status report ingestion

**High-Frequency (30s cron):**
- Financial history batch processing

## Key File Locations

- **Billing services**: `services/billing/` (22 modules)
- **Payment services**: `services/payment/` (9 modules)
- **Member financial**: `services/member/financial/` (6 modules)
- **Member payment**: `services/member/payment/` (2 modules)
- **Payment DocTypes**: `verenigingen_payments/` package
- **Hooks**: `hooks/doc_events.py` (Sales Invoice, Payment Entry, SEPA Mandate sections)
