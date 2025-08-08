# Dues Invoice and Payment Tracking Analysis

**Date**: 2025-08-08
**Analysis**: Event handlers and hooks for tracking dues invoices and payments

## Key Event Handlers for Dues & Payment Tracking

### 1. Payment Entry Events (Lines 333-342)

**Payment Entry on_submit handlers:**
```python
"Payment Entry": {
    "on_submit": [
        "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
        "verenigingen.utils.payment_notifications.on_payment_submit",
        "verenigingen.utils.background_jobs.queue_expense_event_processing_handler",
        "verenigingen.utils.background_jobs.queue_donor_auto_creation_handler",
    ],
    "on_cancel": "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
    "on_trash": "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
}
```

**Key Functions:**
- **`queue_member_payment_history_update_handler`** - Updates member payment history when payments are made/cancelled
- **`on_payment_submit`** - Immediate payment notifications (synchronous for speed)
- **`queue_donor_auto_creation_handler`** - Creates donor records from payments

### 2. Sales Invoice Events (Lines 343-355)

**Sales Invoice event handlers:**
```python
"Sales Invoice": {
    "before_validate": [
        "verenigingen.utils.apply_tax_exemption_from_source",
        "verenigingen.utils.sales_invoice_hooks.set_member_from_customer",
    ],
    "validate": ["verenigingen.overrides.sales_invoice.custom_validate"],
    "after_validate": ["verenigingen.overrides.sales_invoice.after_validate"],
    # Event-driven approach for payment history updates
    "on_submit": "verenigingen.events.invoice_events.emit_invoice_submitted",
    "on_update_after_submit": "verenigingen.events.invoice_events.emit_invoice_updated_after_submit",
    "on_cancel": "verenigingen.events.invoice_events.emit_invoice_cancelled",
}
```

**Key Functions:**
- **`set_member_from_customer`** - Links invoices to members via customer relationship
- **`emit_invoice_submitted`** - Event-driven payment history updates (prevents validation errors)
- **`emit_invoice_updated_after_submit`** - Tracks invoice changes after submission
- **`emit_invoice_cancelled`** - Handles cancelled invoice cleanup

### 3. Member Events (Lines 423-430)

**Member document events:**
```python
"Member": {
    "before_save": "verenigingen.verenigingen.doctype.member.member_utils.update_termination_status_display",
    "after_save": [
        "verenigingen.verenigingen.doctype.member.member.handle_fee_override_after_save",
        "verenigingen.email.email_group_sync.sync_member_on_change",
    ],
    "on_update": "verenigingen.utils.chapter_role_events.on_member_on_update",
}
```

**Key Function:**
- **`handle_fee_override_after_save`** - Processes fee changes and updates billing history

## Scheduled Tasks for Dues & Payment Processing

### Daily Tasks (Lines 441-498)

**Member Financial Tracking:**
```python
"daily": [
    # Member financial history refresh - runs once daily
    "verenigingen.verenigingen.doctype.member.scheduler.refresh_all_member_financial_histories",

    # Generate invoices from membership dues schedules
    "verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule.generate_dues_invoices",

    # Auto-create missing dues schedules
    "verenigingen.utils.dues_schedule_auto_creator.auto_create_missing_dues_schedules_scheduled",

    # Check for stuck dues schedules and notify administrators
    "verenigingen.api.fix_stuck_dues_schedule.check_and_notify_stuck_schedules",

    # SEPA Direct Debit batch optimization
    "verenigingen.api.dd_batch_scheduler.daily_batch_optimization",

    # Membership dues collection processing
    "verenigingen.verenigingen.doctype.direct_debit_batch.sepa_processor.create_monthly_dues_collection_batch",

    # Payment plan processing
    "verenigingen.verenigingen.doctype.payment_plan.payment_plan.process_overdue_installments",

    # SEPA payment retry processing
    "verenigingen.utils.payment_retry.execute_payment_retry",

    # Bank transaction reconciliation
    "verenigingen.utils.sepa_reconciliation.reconcile_bank_transactions",

    # SEPA mandate expiry notifications
    "verenigingen.utils.sepa_notifications.check_and_send_expiry_notifications",
]
```

### Hourly Tasks (Lines 500-507)

**Payment Monitoring:**
```python
"hourly": [
    # Payment history validation and repair
    "verenigingen.utils.payment_history_validator.validate_payment_history_integrity",
]
```

## Key Components for Billing History Tracking

### 1. Member Payment History Updates

**Background Job Handler:**
- **File**: `verenigingen/utils/background_jobs.py`
- **Function**: `queue_member_payment_history_update_handler`
- **Triggers**: Payment Entry submit/cancel/trash
- **Purpose**: Asynchronous updates to member payment history

### 2. Invoice Event System

**Event Emitters:**
- **File**: `verenigingen/events/invoice_events.py`
- **Functions**:
  - `emit_invoice_submitted`
  - `emit_invoice_updated_after_submit`
  - `emit_invoice_cancelled`
- **Purpose**: Event-driven approach to prevent validation errors during invoice processing

### 3. Member Financial History Refresh

**Scheduled Processor:**
- **File**: `verenigingen/verenigingen/doctype/member/scheduler.py`
- **Function**: `refresh_all_member_financial_histories`
- **Schedule**: Daily
- **Purpose**: Comprehensive refresh of all member financial data

### 4. Fee Change Tracking

**Member Controller:**
- **File**: `verenigingen/verenigingen/doctype/member/member.py`
- **Function**: `handle_fee_override_after_save`
- **Trigger**: Member after_save
- **Purpose**: Track fee changes and update billing history

## Billing History Architecture

### Current Implementation

Based on the hooks and earlier analysis:

1. **Fee Change History** (Child Table on Member)
   - DocType: `Member Fee Change History`
   - Field: `fee_change_history` on Member
   - Tracks: Rate changes, schedules, amendments

2. **Member Billing History** (Potential)
   - DocType: `Member Billing History` (exists but unused)
   - Purpose: Could track invoice generation, payment status, billing events
   - Status: Not implemented/not connected

3. **Payment History** (Member-linked)
   - Tracked via Payment Entry events
   - Background job processing for performance
   - Comprehensive refresh via daily scheduler

## Identified Gap: Billing History vs Fee Change History

### What Exists:
- ✅ **Fee Change History**: Tracks dues rate changes
- ✅ **Payment History**: Tracks payments made
- ✅ **Invoice Events**: Tracks invoice lifecycle

### What's Missing:
- ❓ **Billing History**: Track billing events (invoice generation, due dates, late fees, etc.)

### Potential Use for Member Billing History DocType:

The unused `Member Billing History` DocType could potentially track:
- Invoice generation events
- Due date notifications sent
- Late payment penalties applied
- Billing frequency changes
- Payment plan modifications
- Collection attempt records

This would be **separate from** fee change history (rate changes) and payment history (actual payments), focusing on the **billing process itself**.

## Conclusion

The system has comprehensive hooks for:
1. **Payment tracking** (via Payment Entry events)
2. **Invoice lifecycle** (via Sales Invoice events)
3. **Fee change tracking** (via Member events and fee_change_history child table)
4. **Financial data refresh** (via scheduled tasks)

The `Member Billing History` DocType appears to be **planned but not implemented** - it could serve as a billing event audit trail separate from payment and fee change tracking.
