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

## 8. Complete File Inventory (182 Files Found)

### 8.1 Core DocTypes and Controllers (HIGH PRIORITY)
**Files requiring immediate modification:**
- `verenigingen/doctype/membership/membership.py` - Remove subscription creation logic
- `verenigingen/doctype/membership/membership.json` - Clean subscription field references
- `verenigingen/doctype/membership_type/membership_type.py` - Update subscription plan references
- `verenigingen/doctype/membership_type/membership_type.json` - Update subscription plan field
- `verenigingen/doctype/member/member.py` - Update fee calculation methods
- `verenigingen/doctype/member/member.json` - Review subscription-related fields
- `verenigingen/doctype/member/mixins/financial_mixin.py` - Update subscription references
- `verenigingen/doctype/member/mixins/payment_mixin.py` - Update payment logic
- `verenigingen/doctype/direct_debit_batch/direct_debit_batch.py` - Update subscription filtering

### 8.2 API Endpoints (HIGH PRIORITY)
**Files requiring modification:**
- `verenigingen/api/enhanced_membership_application.py` - Update subscription creation
- `verenigingen/api/membership_application_review.py` - Update approval flow
- `verenigingen/api/payment_processing.py` - Update subscription references
- `verenigingen/api/payment_dashboard.py` - Update subscription queries
- `verenigingen/api/eboekhouden_clean_reimport.py` - Update subscription handling
- `verenigingen/api/sepa_period_duplicate_prevention.py` - Update subscription logic
- `verenigingen/api/generate_test_membership_types.py` - Update subscription plan creation

### 8.3 Reports (HIGH PRIORITY)
**Files requiring significant modification:**
- `verenigingen/report/orphaned_subscriptions_report/orphaned_subscriptions_report.py` - REPLACE ENTIRELY
- `verenigingen/report/orphaned_subscriptions_report/orphaned_subscriptions_report.js` - REPLACE ENTIRELY
- `verenigingen/report/orphaned_subscriptions_report/orphaned_subscriptions_report.json` - REPLACE ENTIRELY
- `verenigingen/report/overdue_member_payments/overdue_member_payments.py` - Remove subscription filters

### 8.4 Utilities and Background Processing (HIGH PRIORITY)
**Files requiring significant modification:**
- `verenigingen/utils/subscription_processing.py` - DEPRECATE ENTIRELY
- `verenigingen/utils/subscription_diagnostics.py` - DEPRECATE ENTIRELY
- `verenigingen/utils/subscription_period_calculator.py` - DEPRECATE ENTIRELY
- `verenigingen/utils/application_helpers.py` - Update subscription references
- `verenigingen/utils/application_payments.py` - Update subscription creation
- `verenigingen/utils/termination_integration.py` - Update subscription handling
- `verenigingen/utils/termination_utils.py` - Update subscription references
- `verenigingen/utils/performance_dashboard.py` - Update subscription metrics

### 8.5 Schedulers and Background Tasks (HIGH PRIORITY)
**Files requiring modification:**
- `verenigingen/doctype/member/scheduler.py` - Update subscription processing
- `verenigingen/doctype/membership/scheduler.py` - Update subscription handling
- `hooks.py` - Update scheduled tasks for dues processing

### 8.6 Monitoring and Diagnostics (MEDIUM PRIORITY)
**Files requiring modification:**
- `scripts/monitoring/zabbix_integration.py` - Update subscription metrics
- `scripts/monitoring/zabbix_template_frappe_v7.2_fixed.yaml` - Update subscription monitoring
- `verenigingen/monitoring/zabbix_integration_2.py` - Update subscription queries
- `verenigingen/page/system_health_dashboard/system_health_dashboard.js` - Update subscription checks

### 8.7 Test Files (MEDIUM PRIORITY)
**Files requiring updates for new test patterns:**
- `verenigingen/tests/backend/components/test_fee_override_subscription.py` - Update for dues schedules
- `verenigingen/tests/backend/components/test_membership_application.py` - Update subscription creation tests
- `verenigingen/tests/backend/components/test_overdue_payments_report.py` - Update subscription filtering tests
- `verenigingen/tests/backend/unit/controllers/test_membership_controller.py` - Update subscription tests
- `verenigingen/tests/backend/workflows/test_member_lifecycle_complete.py` - Update subscription workflow tests
- `verenigingen/tests/backend/workflows/test_member_lifecycle_simple.py` - Update subscription workflow tests
- `verenigingen/doctype/membership/test_membership.py` - Update subscription creation tests
- `verenigingen/doctype/membership_type/test_membership_type.py` - Update subscription plan tests
- `verenigingen/doctype/direct_debit_batch/test_direct_debit_batch.py` - Update subscription filtering tests

### 8.8 Templates and Frontend (MEDIUM PRIORITY)
**Files requiring updates:**
- `verenigingen/templates/pages/enhanced_membership_application.py` - Update subscription creation
- `verenigingen/templates/pages/enhanced_membership_application.html` - Update subscription references
- `verenigingen/templates/pages/volunteer/expenses.py` - Update subscription references
- `verenigingen/public/js/membership_application.js` - Update subscription handling
- `verenigingen/public/js/member/js_modules/payment-utils.js` - Update subscription references
- `verenigingen/public/js/member/js_modules/termination-utils.js` - Update subscription handling

### 8.9 DocType Configurations (MEDIUM PRIORITY)
**Files requiring field updates:**
- `verenigingen/doctype/membership_termination_request/membership_termination_request.py` - Update subscription handling
- `verenigingen/doctype/membership_termination_request/membership_termination_request.json` - Update subscription fields
- `verenigingen/doctype/membership_amendment_request/membership_amendment_request.py` - Update subscription references
- `verenigingen/doctype/membership_amendment_request/membership_amendment_request.json` - Update subscription fields
- `verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.py` - Update subscription handling
- `verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.json` - Update subscription fields

### 8.10 Legacy DocTypes (LOW PRIORITY - DEPRECATE)
**Files to be deprecated:**
- `verenigingen/doctype/member_subscription_history/` - DEPRECATE ENTIRELY
- `verenigingen/doctype/member_fee_change_history/` - DEPRECATE ENTIRELY
- `verenigingen/doctype/membership/enhanced_subscription.py` - DEPRECATE ENTIRELY

### 8.11 Documentation and Configuration (LOW PRIORITY)
**Files requiring updates:**
- `MEMBERSHIP_DUES_SYSTEM_DETAILED_PLAN.md` - Update subscription references (active plan)
- `archived/superseded-versions/MEMBERSHIP_DUES_SYSTEM_DETAILED_PLAN_V2.md` - Update subscription references (archived)
- `archived/superseded-versions/MEMBERSHIP_DUES_SYSTEM_PLAN.md` - Update subscription references (archived)
- `SUBSCRIPTION_STARVATION_INVESTIGATION.md` - Archive as historical reference
- `verenigingen/fixtures/subscription_plan.json` - Update for dues schedules
- `verenigingen/fixtures/membership_type.json` - Update subscription plan references
- `verenigingen/fixtures/workspace.json` - Update workspace references
- `docs/features/membership-management.md` - Update subscription documentation
- `docs/ADMIN_GUIDE.md` - Update subscription administration
- `README.md` - Update subscription feature descriptions

### 8.12 Debug and Maintenance Scripts (LOW PRIORITY)
**Files to be deprecated or updated:**
- `scripts/debug/test_subscription_metrics.py` - DEPRECATE
- `scripts/debug/subscription_diagnostic.py` - DEPRECATE
- `scripts/debug/check_subscription_invoice_table.py` - DEPRECATE
- `scripts/debug/simple_subscription_check.py` - DEPRECATE
- `scripts/debug/subscription_starvation_analysis.py` - DEPRECATE
- `scripts/debug/quick_subscription_check.py` - DEPRECATE
- `scripts/debug/debug_subscription_starvation.py` - DEPRECATE
- `scripts/fixes/fix_subscription_processing.py` - DEPRECATE
- `scripts/api_maintenance/fix_subscription.py` - DEPRECATE
- `scripts/testing/test_subscription_date_alignment.py` - DEPRECATE

### 8.13 Patches and Fixes (LOW PRIORITY)
**Files requiring review:**
- `verenigingen/patches/fix_subscription_date_update.py` - Review for dues schedule equivalent
- `verenigingen/setup/doctype_overrides.py` - Update subscription overrides

---

## 9. Migration Impact Assessment

### 9.1 High Impact Changes (182 Files Total)
- **Core Business Logic**: 25 files requiring significant rewrites
- **API Endpoints**: 15 files requiring subscription-to-dues conversion
- **Reports**: 4 files requiring complete replacement
- **Background Processing**: 12 files requiring logic updates
- **Tests**: 35+ files requiring test pattern updates

### 9.2 Migration Timeline Estimate
- **Phase 1 (Core Changes)**: 2-3 weeks (40 high-priority files)
- **Phase 2 (API and Reports)**: 1-2 weeks (19 medium-priority files)
- **Phase 3 (Tests and Documentation)**: 1-2 weeks (65+ low-priority files)
- **Phase 4 (Cleanup and Deprecation)**: 1 week (58 deprecated files)

### 9.3 Risk Assessment
- **High Risk**: Core DocType changes, API modifications, background task updates
- **Medium Risk**: Report replacements, test updates, monitoring changes
- **Low Risk**: Documentation updates, debug script deprecation

---

## Summary

**Major Changes** (182 files identified):
1. Replace subscription system with dues schedules across entire codebase
2. Update all reports to use dues instead of subscriptions
3. Modify monitoring to track dues processing
4. Add comprehensive access control layer
5. Create new notification system
6. Deprecate 58 subscription-specific files
7. Update 124 files with subscription references

**Minimal Changes**:
1. SEPA integration (just reference updates)
2. Payment Entry processing (stays the same)
3. Member Payment History (already exists, just use it more)

**Data Preservation**:
- Keep subscription data for historical reference
- Maintain audit trail of migration
- Archive rather than delete old data

**Scope Confirmation**: This migration affects **182 files** across the entire codebase, requiring careful planning and phased implementation to ensure system stability.
