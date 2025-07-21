# Membership Dues System - Comprehensive Plan

## Executive Summary

Replace ERPNext's complex subscription system with a purpose-built membership dues system designed for associations. This system treats memberships as perpetual relationships with periodic financial obligations, not commercial subscriptions.

## Problem Statement

### Current Issues:
1. **ERPNext Subscription Limitations**: "Current Invoice Start Date" validation errors prevent automatic processing
2. **Conceptual Mismatch**: Commercial subscription model doesn't fit association membership model
3. **Complex Workarounds**: Custom handlers and database manipulations required
4. **Scheduler Failures**: 0 subscriptions processed due to validation errors
5. **Poor Visibility**: No clear overview of payment status and upcoming dues

### Root Cause:
ERPNext's Subscription system is designed for SaaS/commercial subscriptions with fixed contract periods, not perpetual memberships with annual dues.

## Proposed Solution Architecture

### Core Components

#### 1. **Membership Dues Schedule**
A lightweight billing calendar for each member that tracks:
- Member and Membership reference
- Billing frequency (Annual/Quarterly/Monthly/Custom)
- Amount and currency
- Next invoice date
- Last invoice date (prevents duplicates)
- Status (Active/Paused/Cancelled)
- Grace period settings
- Warning notification settings

#### 2. **Payment Status Tracking**
Leverages existing infrastructure with enhancements:
- **Member Payment History** (existing): Already tracks all invoices and payments
- **Payment Status Dashboard**: New consolidated view of payment health
- **Automated Status Updates**: Based on payment events

#### 3. **Warning & Notification System**

##### **Notification Timeline**:
```
T-30 days: "Upcoming dues" reminder
T-14 days: "Dues invoice generated" + invoice attached
T-0:       Due date - status remains "Current"
T+7 days:  "Gentle reminder" - status changes to "Late"
T+14 days: "Payment overdue" - status changes to "Overdue"
T+30 days: "Final notice" - status changes to "Seriously Overdue"
T+60 days: "Suspension warning" - Board notification
T+90 days: Automatic suspension - status changes to "Suspended"
```

##### **Multi-Channel Notifications**:
- **Email**: Primary channel with customizable templates
- **SMS**: For critical notices (optional)
- **Member Portal**: Dashboard warnings
- **Admin Dashboard**: Consolidated view for staff

##### **Smart Notification Rules**:
- Skip if payment plan exists
- Skip if member contacted recently
- Escalation path for board members
- Respect communication preferences

#### 4. **Grace Period & Recovery System**

##### **Flexible Grace Periods**:
```python
{
    "standard_grace_days": 30,        # Default for all members
    "senior_grace_days": 60,          # Extended for seniors
    "hardship_grace_days": 90,        # Case-by-case basis
    "payment_plan_grace_days": null   # No suspension with active plan
}
```

##### **Recovery Workflows**:
1. **Automatic Recovery**: Payment received → Clear all warnings → Restore status
2. **Payment Plans**: Create installment schedule → Pause warnings
3. **Hardship Cases**: Board approval → Extended grace → Custom schedule
4. **Write-offs**: Board decision → Clear debt → Maintain membership

## Implementation Plan

### Phase 1: Foundation (Week 1-2)

#### 1.1 Core Data Model
```python
# Membership Dues Schedule
- member (Link to Member)
- membership (Link to Membership)
- billing_frequency (Select)
- amount (Currency)
- next_invoice_date (Date)
- last_invoice_date (Date)
- grace_period_days (Int)
- warning_days_before (Int, default: 30)
- status (Select: Active/Paused/Cancelled)

# Membership Payment Status (Virtual/Calculated)
- current_status (Calculated from payment history)
- days_overdue (Calculated)
- total_outstanding (Sum of unpaid invoices)
- last_payment_date (From payment history)
- next_due_date (From dues schedule)
```

#### 1.2 Status Calculation Engine
```python
def calculate_member_payment_status(member):
    """
    Returns: Current, Late, Overdue, Seriously Overdue, Suspended
    Based on oldest unpaid invoice and grace periods
    """
    oldest_unpaid = get_oldest_unpaid_invoice(member)
    if not oldest_unpaid:
        return "Current"

    days_overdue = (today() - oldest_unpaid.due_date).days
    grace_period = get_member_grace_period(member)

    if days_overdue <= 0:
        return "Current"
    elif days_overdue <= 7:
        return "Late"
    elif days_overdue <= grace_period:
        return "Overdue"
    elif days_overdue <= grace_period + 30:
        return "Seriously Overdue"
    else:
        return "Suspended"
```

### Phase 2: Invoice Generation (Week 2-3)

#### 2.1 Invoice Generator
```python
def generate_membership_invoice(schedule):
    """
    Creates invoice with proper references and metadata
    """
    invoice = create_sales_invoice(
        customer=schedule.member,
        due_date=schedule.next_invoice_date,
        items=[{
            "item_code": get_dues_item(schedule),
            "qty": 1,
            "rate": schedule.amount
        }]
    )

    # Add metadata for tracking
    invoice.membership_dues_schedule = schedule.name
    invoice.membership_period_start = schedule.last_invoice_date or schedule.next_invoice_date
    invoice.membership_period_end = calculate_period_end(schedule)

    return invoice
```

#### 2.2 Scheduled Job
```python
# Daily at 8 AM
def process_membership_dues():
    """
    1. Find schedules due for invoicing
    2. Generate invoices
    3. Send notifications
    4. Update payment statuses
    """
    schedules = get_schedules_due_for_invoicing()

    for schedule in schedules:
        try:
            invoice = generate_membership_invoice(schedule)
            send_invoice_notification(schedule.member, invoice)
            schedule.update_dates()
        except Exception as e:
            log_and_notify_admin(e, schedule)
```

### Phase 3: Notification System (Week 3-4)

#### 3.1 Notification Templates
```
# Email Templates (Customizable per organization)
- upcoming_dues_reminder
- invoice_generated
- payment_reminder_gentle
- payment_overdue_notice
- final_notice
- suspension_warning
- payment_received_confirmation
- membership_reactivated
```

#### 3.2 Notification Engine
```python
class DuesNotificationEngine:
    def __init__(self):
        self.channels = ['email', 'sms', 'portal']
        self.templates = load_notification_templates()

    def check_and_send_notifications():
        """Runs daily to send appropriate notifications"""

        # Upcoming dues (T-30)
        upcoming = get_members_with_upcoming_dues(30)
        for member in upcoming:
            if should_notify(member, 'upcoming_dues'):
                send_notification(member, 'upcoming_dues_reminder')

        # Overdue reminders (multiple stages)
        overdue_stages = [
            (7, 'payment_reminder_gentle'),
            (14, 'payment_overdue_notice'),
            (30, 'final_notice'),
            (60, 'suspension_warning')
        ]

        for days, template in overdue_stages:
            members = get_members_overdue_exactly(days)
            for member in members:
                if should_notify(member, template):
                    send_notification(member, template)
```

### Phase 4: Admin Tools & Dashboards (Week 4-5)

#### 4.1 Existing Reports (Enhanced)

##### **Overdue Member Payments Report** (Existing - Enhanced)
Current Features:
- Groups overdue invoices by member
- Shows days overdue with color coding (Critical >60, Urgent >30)
- Filters by chapter, membership type, date range
- Chapter-based access control
- Summary statistics and charts

Enhancements for Dues System:
- Add "Last Reminder Sent" column
- Add "Payment Plan Status" indicator
- Add "Grace Period Remaining" calculation
- Quick action buttons: Send Reminder, Create Payment Plan, View History
- Export to CSV for mail merge

##### **Orphaned Subscriptions Report** (Existing - Replaced)
Current Purpose: Find subscriptions without active memberships

Replacement: **Orphaned Dues Schedules Report**
- Find dues schedules without active memberships
- Find dues schedules with mismatched amounts
- Find members without dues schedules
- Bulk actions to fix discrepancies

#### 4.2 New Reports

##### **Payment Health Dashboard**
```
# Real-time Metrics
- Members by Payment Status (pie chart)
- Outstanding Amount by Age (bar chart)
- Payment Trends (line graph)
- Collection Rate by Month
- At-Risk Members (requires immediate attention)

# Quick Actions
- Send bulk reminders
- Create payment plans
- Export for collections
- Suspend/reactivate members
```

##### **Dues Schedule Management Report**
- All active schedules with next invoice dates
- Schedules needing attention (paused, errors)
- Upcoming invoice forecast
- Billing frequency distribution

#### 4.3 Member Payment Portal
```
# Member View
- Current Status (visual indicator)
- Payment History
- Upcoming Dues
- Download Invoices
- Payment Options
- Request Payment Plan
```

#### 4.4 Administrative Functions
```python
# Bulk Operations
- bulk_send_reminders(member_list, template)
- bulk_create_payment_plans(member_list, terms)
- bulk_adjust_grace_periods(member_list, days)
- bulk_waive_late_fees(member_list)

# Reports
- aging_report(): Outstanding by age buckets
- payment_performance(): Collection rates over time
- member_retention(): Correlation with payment status
- notification_effectiveness(): Response rates by template
```

### Phase 5: Edge Cases & Special Handling (Week 5-6)

#### 5.1 Special Scenarios

##### **Deceased Members**
- Automatic suspension of dues
- Grace period for estate settlement
- Special communication templates

##### **Life Members**
- No dues schedule created
- Special status in system
- Excluded from all payment processing

##### **Honorary Members**
- Optional dues (can pay if they want)
- No suspension for non-payment
- Special recognition in communications

##### **Family Memberships**
- Single schedule for household
- Linked member records
- Consolidated communications

##### **Pro-rated Periods**
```python
def calculate_prorated_amount(membership_type, start_date):
    """For mid-year joins"""
    annual_amount = membership_type.fee
    days_remaining = (year_end - start_date).days
    days_in_year = 365

    return round(annual_amount * days_remaining / days_in_year, 2)
```

#### 5.2 Payment Plans
```python
class PaymentPlanManager:
    def create_plan(member, total_amount, installments, start_date):
        """Creates multiple small dues schedules"""

        # Pause main schedule
        main_schedule.pause("Payment plan active")

        # Create installment schedules
        for i in range(installments):
            create_dues_schedule(
                member=member,
                amount=total_amount/installments,
                frequency="Custom",
                next_date=add_months(start_date, i)
            )

        return payment_plan_id

    def monitor_compliance(plan_id):
        """Check if payments are being made"""
        # Run weekly to check plan adherence
```

### Phase 6: Migration & Rollout (Week 6-7)

#### 6.1 Data Migration
```python
def migrate_from_subscriptions():
    """
    1. Map active subscriptions → dues schedules
    2. Preserve payment history (already in Member)
    3. Handle edge cases (partial periods, credits)
    4. Create audit trail
    """

    # Parallel run period
    # - Keep subscriptions active
    # - Create dues schedules in test mode
    # - Compare outputs
    # - Fix discrepancies
    # - Switch over when confident
```

#### 6.2 Rollout Plan
1. **Pilot Group** (10 members, 2 weeks)
2. **Expanded Test** (100 members, 2 weeks)
3. **Soft Launch** (all new members)
4. **Full Migration** (all existing members)
5. **Decommission** old subscription system

## Success Metrics

### Operational Metrics
- **Invoice Generation Success Rate**: Target >99.9%
- **Payment Collection Rate**: Improve by 10%
- **Days Sales Outstanding (DSO)**: Reduce by 15%
- **Manual Intervention Required**: <1% of invoices

### Member Experience Metrics
- **Portal Adoption**: 60% members use self-service
- **Payment Plan Requests**: Processed within 24 hours
- **Complaint Rate**: <0.5% regarding billing

### Technical Metrics
- **System Uptime**: 99.9%
- **Invoice Generation Time**: <2 seconds per invoice
- **Notification Delivery Rate**: >98%

## Report Integration Strategy

### Existing Reports Adaptation

#### **Overdue Member Payments Report**
- **Keep As-Is**: Core functionality remains valuable
- **Enhance With**:
  - Direct links to dues schedules
  - Reminder history tracking
  - Grace period awareness
  - Payment plan indicators
  - One-click actions (send reminder, create plan)

#### **Orphaned Subscriptions Report** → **Data Integrity Report**
- **Transform Into**: Comprehensive data health check
- **Checks For**:
  - Members without dues schedules
  - Dues schedules without valid memberships
  - Mismatched amounts (dues vs membership type)
  - Duplicate schedules
  - Schedules in wrong status

### Report Access Flow
```
Staff Dashboard → Payment Management
├── Overdue Member Payments (existing, enhanced)
├── Payment Health Dashboard (new)
├── Dues Schedule Management (new)
└── Data Integrity Report (replaces Orphaned Subscriptions)

Member Portal → My Account
├── Payment Status
├── Invoice History
└── Payment Options
```

## Risk Mitigation

### Technical Risks
- **Risk**: Migration data loss
- **Mitigation**: Comprehensive backup, parallel run, rollback plan

### Business Risks
- **Risk**: Member confusion during transition
- **Mitigation**: Clear communication, FAQ, support channels

### Compliance Risks
- **Risk**: SEPA mandate issues
- **Mitigation**: Maintain existing SEPA integration, legal review

## Resource Requirements

### Development Team
- 1 Senior Developer (lead)
- 1 Developer
- 1 QA Engineer
- 0.5 Business Analyst

### Timeline
- **Total Duration**: 7 weeks
- **Buffer**: 2 weeks
- **Post-Launch Support**: 4 weeks

### Infrastructure
- No additional infrastructure required
- Uses existing ERPNext/Frappe setup

## Decision Points for Stakeholders

1. **Grace Period Policy**: How many days before suspension?
2. **Notification Frequency**: How aggressive should reminders be?
3. **Payment Plan Terms**: Standard offerings or case-by-case?
4. **Suspension Policy**: Automatic or manual review required?
5. **Write-off Authority**: Who can approve debt forgiveness?
6. **Special Member Categories**: Which types need different treatment?

## Next Steps

1. **Review & Feedback**: Circulate this plan for stakeholder input
2. **Policy Decisions**: Board/management decisions on business rules
3. **Technical Review**: Validate approach with Frappe experts
4. **Resource Allocation**: Confirm team and timeline
5. **Kick-off**: Begin Phase 1 development

## Appendix: Comparison with Current System

| Aspect | Current (Subscription) | New (Dues Schedule) |
|--------|------------------------|-------------------|
| Concept | Commercial contract | Membership obligation |
| Duration | Fixed periods | Perpetual |
| Invoicing | Complex validation | Simple date check |
| Flexibility | Limited | High |
| Payment Plans | Difficult | Native support |
| Grace Periods | Not supported | Built-in |
| Notifications | Basic | Comprehensive |
| Member Portal | Limited info | Full self-service |
| Reporting | Generic | Association-specific |
| Maintenance | High (workarounds) | Low (purpose-built) |
