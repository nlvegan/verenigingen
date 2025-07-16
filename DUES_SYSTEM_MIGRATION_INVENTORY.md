# Membership Dues System - Migration Inventory

## Overview
This document inventories the existing code that would become redundant or need modification when implementing the new Membership Dues System.

---

## 1. Files to be Deprecated/Removed

### 1.1 Custom Subscription Handler
**File**: `verenigingen/utils/subscription_processing.py`
- **Status**: DEPRECATE
- **Reason**: Custom workaround for ERPNext subscription limitations no longer needed
- **Contains**: `SubscriptionHandler` class that bypasses validation errors
- **Migration**: Remove after all subscriptions migrated to dues schedules

### 1.2 Subscription-Related Utilities
**Files**:
- Any custom subscription manipulation utilities
- Subscription validation workarounds
- Custom subscription invoice generators

**Migration**: Replace with dues schedule equivalents

---

## 2. Files to be Modified

### 2.1 Monitoring & Metrics

#### `scripts/monitoring/zabbix_integration.py`
**Changes Required**:
```python
# OLD: Checks non-existent tabSubscription Invoice
processed_today = frappe.db.sql("""
    SELECT COUNT(DISTINCT subscription)
    FROM `tabSales Invoice`
    WHERE creation >= %s
    AND subscription IS NOT NULL
""")

# NEW: Check dues schedule invoices
processed_today = frappe.db.sql("""
    SELECT COUNT(*)
    FROM `tabSales Invoice`
    WHERE creation >= %s
    AND membership_dues_schedule IS NOT NULL
""")
```

### 2.2 Reports

#### `verenigingen/report/overdue_member_payments/overdue_member_payments.py`
**Changes Required**:
- Line 68: Remove subscription filter
- Line 108-109: Remove `is_membership_subscription()` check
- Line 213-239: Remove entire `is_membership_subscription()` function
- Add dues schedule awareness to report

**New Logic**:
```python
# Replace subscription check with dues-based check
invoice_filters = {
    "status": ["in", ["Overdue", "Unpaid"]],
    "due_date": ["<", today()],
    "docstatus": 1,
    # Remove: "subscription": ["is", "set"],
    # Add: Custom field or join with dues schedule
}
```

#### `verenigingen/report/orphaned_subscriptions_report/`
**Status**: REPLACE ENTIRELY
- Transform into "Data Integrity Report"
- Check for:
  - Members without dues schedules
  - Dues schedules without valid memberships
  - Mismatched amounts
  - Duplicate schedules

### 2.3 API Endpoints

#### New API Functions Needed
**File**: `verenigingen/api/dues_management.py` (NEW)
```python
# Functions to implement:
- get_member_dues_summary()
- create_payment_plan()
- update_payment_method()
- get_payment_health_dashboard_data()
- send_bulk_payment_reminders()
- get_user_financial_access_level()
```

### 2.4 Hooks and Events

#### `hooks.py`
**Add New Scheduled Events**:
```python
scheduler_events = {
    "daily": [
        # Remove: "verenigingen.utils.subscription_processing.process_subscriptions"
        # Add:
        "verenigingen.utils.dues_processing.daily_dues_processor"
    ],
    "weekly": [
        # Add:
        "verenigingen.utils.dues_processing.weekly_payment_status_update"
    ]
}
```

**Add New DocType Events**:
```python
doc_events = {
    "Sales Invoice": {
        # Add dues schedule tracking
        "on_submit": "verenigingen.utils.dues_invoice_tracking.link_to_dues_schedule",
        "on_cancel": "verenigingen.utils.dues_invoice_tracking.unlink_from_dues_schedule"
    },
    "Payment Entry": {
        # Add cache invalidation
        "on_submit": "verenigingen.utils.dues_processing.invalidate_payment_cache"
    }
}
```

### 2.5 Member DocType Extensions

#### `verenigingen/doctype/member/member.py`
**Changes Required**:
- Remove subscription-related methods
- Add dues schedule methods:
  ```python
  def get_active_dues_schedule(self):
      """Get active dues schedule for this member"""
      pass

  def calculate_payment_status(self):
      """Calculate current payment status"""
      pass
  ```

### 2.6 Membership Application Processing

#### `verenigingen/doctype/membership_application/membership_application.py`
**In `approve_application()` method**:
```python
# OLD: Create subscription
# subscription = create_subscription_for_member(member)

# NEW: Create dues schedule
dues_schedule = create_dues_schedule_for_member(member, membership)
```

### 2.7 Payment Processing

#### SEPA Integration Files
**Minimal Changes** - SEPA integration remains largely the same, just references dues instead of subscriptions:
- Update batch descriptions
- Update pre-notification templates
- Link to dues schedules instead of subscriptions

---

## 3. New Files to Create

### 3.1 Core DocTypes
```
verenigingen/doctype/
├── membership_dues_schedule/
│   ├── membership_dues_schedule.json
│   ├── membership_dues_schedule.py
│   ├── membership_dues_schedule.js
│   └── test_membership_dues_schedule.py
├── member_payment_plan/
│   ├── member_payment_plan.json
│   ├── member_payment_plan.py
│   └── test_member_payment_plan.py
└── financial_access_log/
    ├── financial_access_log.json
    └── financial_access_log.py
```

### 3.2 Utilities
```
verenigingen/utils/
├── dues_processing.py          # Main processing engine
├── dues_notifications.py       # Notification engine
├── payment_status_calculator.py # Status calculations
└── dues_migration.py           # Migration utilities
```

### 3.3 Templates
```
verenigingen/templates/
├── emails/
│   ├── upcoming_dues_reminder.html
│   ├── payment_overdue_notice.html
│   ├── payment_plan_confirmation.html
│   └── suspension_warning.html
└── pages/
    └── payment_health_dashboard.html
```

### 3.4 Reports
```
verenigingen/report/
├── payment_health_dashboard/
├── dues_schedule_management/
└── data_integrity_report/  # Replaces orphaned subscriptions
```

---

## 4. Database Migrations

### 4.1 New Tables
```sql
-- Core tables
CREATE TABLE `tabMembership Dues Schedule` (...)
CREATE TABLE `tabMember Payment Plan` (...)
CREATE TABLE `tabFinancial Access Log` (...)

-- Child tables
CREATE TABLE `tabPayment Plan Installment` (...)
CREATE TABLE `tabDues Notification Log` (...)
```

### 4.2 Modified Tables
```sql
-- Add to Sales Invoice
ALTER TABLE `tabSales Invoice`
ADD COLUMN membership_dues_schedule VARCHAR(140);

-- Add indexes for performance
CREATE INDEX idx_dues_schedule ON `tabSales Invoice` (membership_dues_schedule);
```

---

## 5. Migration Strategy

### Phase 1: Parallel Run (Weeks 1-2)
- Deploy new system alongside existing
- Create dues schedules for new members only
- Existing members continue on subscriptions

### Phase 2: Gradual Migration (Weeks 3-4)
- Migrate members in batches
- Maintain mapping table between old subscriptions and new schedules
- Run reconciliation reports daily

### Phase 3: Cutover (Week 5)
- Switch all remaining members
- Disable subscription creation
- Keep subscription system read-only for historical data

### Phase 4: Cleanup (Week 6+)
- Archive subscription data
- Remove deprecated code
- Update all documentation

---

## 6. Testing Requirements

### 6.1 Test Files to Update
- `test_member_creation.py` - Remove subscription tests, add dues tests
- `test_membership_application.py` - Update approval flow tests
- `test_payment_processing.py` - Update for dues-based payments

### 6.2 New Test Files
- `test_membership_dues_schedule.py`
- `test_payment_status_calculation.py`
- `test_dues_notifications.py`
- `test_financial_access_control.py`

---

## 7. Configuration Changes

### 7.1 Remove Configuration
- Subscription-related settings
- Subscription plan references

### 7.2 Add Configuration
- Dues notification templates
- Grace period settings
- Payment plan terms
- Financial access audit settings

---

## Summary

**Major Changes**:
1. Replace subscription system with dues schedules
2. Update all reports to use dues instead of subscriptions
3. Modify monitoring to track dues processing
4. Add comprehensive access control layer
5. Create new notification system

**Minimal Changes**:
1. SEPA integration (just reference updates)
2. Payment Entry processing (stays the same)
3. Member Payment History (already exists, just use it more)

**Data Preservation**:
- Keep subscription data for historical reference
- Maintain audit trail of migration
- Archive rather than delete old data
