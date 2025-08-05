# Membership Dues System - Detailed Implementation Guide

> **Version History**: This is the most comprehensive version of the membership dues system plan.
> Previous versions (V1, V2, Enhanced) have been archived in `/docs/archived/superseded-versions/`
> for reference but this version supersedes them all with the most complete implementation details.

## Table of Contents
1. [System Architecture Details](#system-architecture-details)
2. [Data Model & Relationships](#data-model--relationships)
3. [Business Process Flows](#business-process-flows)
4. [Technical Implementation Details](#technical-implementation-details)
5. [User Experience Flows](#user-experience-flows)
6. [Integration Points](#integration-points)
7. [Migration Strategy](#migration-strategy)
8. [Operational Procedures](#operational-procedures)

---

## 1. System Architecture Details

### Core Philosophy
The system treats memberships as **perpetual relationships** with **periodic financial obligations**, not commercial subscriptions. This fundamental shift drives all design decisions.

### Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Member Portal                           │
│  (Payment Status, History, Self-Service)                    │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────────────────┐
│                   Dues Management Layer                      │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │   Schedule   │  │   Invoice    │  │  Notification   │   │
│  │   Engine     │  │  Generator   │  │    Engine       │   │
│  └─────────────┘  └──────────────┘  └─────────────────┘   │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────────────────┐
│                    Data Layer (ERPNext)                      │
│  ┌─────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ Member  │  │  Membership  │  │  Sales Invoice     │    │
│  │         │  │              │  │  Payment Entry     │    │
│  │ Payment │  │  Dues        │  │  SEPA Mandate      │    │
│  │ History │  │  Schedule    │  │                    │    │
│  └─────────┘  └──────────────┘  └────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Separation of Concerns**
   - Membership status ≠ Payment status
   - Billing schedule ≠ Membership validity
   - Invoice generation ≠ Subscription processing

2. **Fail-Safe Operations**
   - Never suspend without human review option
   - Always log decisions for audit
   - Graceful degradation for edge cases

3. **Member-Centric Design**
   - Clear communication at every step
   - Self-service options
   - Respect for member circumstances

---

## 2. Data Model & Relationships

### Enhanced Membership Dues Schedule

```python
# Core Fields
member: Link[Member] (required)
membership: Link[Membership] (required)
billing_frequency: Select["Annual", "Semi-Annual", "Quarterly", "Monthly", "Custom"]
amount: Currency  # Current active amount

# Price History Management
base_membership_type: Link[Membership Type] (required)
use_custom_amount: Check (default: 0)
custom_amount_reason: Text
custom_amount_approved_by: Link[User]
custom_amount_approved_date: Date

# Schedule Management
next_invoice_date: Date
last_invoice_date: Date
invoice_days_before: Int (default: 30)
status: Select["Active", "Paused", "Cancelled", "Test"]

# Grace Period Configuration
grace_period_days: Int (default: 30)
grace_period_type: Select["Standard", "Extended", "Hardship", "Custom"]
grace_period_reason: Text

# Notification Settings
notification_enabled: Check (default: 1)
notification_channels: Table[
  - channel: Select["Email", "SMS", "Portal"]
  - enabled: Check
  - template_override: Link[Email Template]
]
reminder_frequency_days: Int (default: 14)
last_reminder_date: Date

# Payment Plan Integration
has_payment_plan: Check (readonly)
payment_plan_reference: Link[Member Payment Plan] (readonly)
original_schedule: Link[Membership Dues Schedule]

# Audit Trail
created_from: Select["Application", "Migration", "Manual", "Payment Plan"]
notes: Text
modification_history: Table[
  - date: Datetime
  - user: Link[User]
  - change_type: Data
  - old_value: Data
  - new_value: Data
  - reason: Text
]
```

### Membership Fee Price History

```python
# New DocType: Membership Fee Price History
member: Link[Member] (required)
membership_type: Link[Membership Type] (required)
effective_date: Date (required)
amount: Currency (required)
previous_amount: Currency (readonly)
change_reason: Select["Annual Adjustment", "Hardship Rate", "Student Rate", "Custom Approval", "System Migration"]
approved_by: Link[User]
notes: Text

# Automatic validation to prevent overlapping effective dates
# Only one active rate per member per date range
```

### Enhanced Membership Type Configuration

```python
# Enhanced Membership Type fields
minimum_annual_fee: Currency (required)  # Base rate - minimum any member can pay
standard_annual_fee: Currency (required)  # Standard recommended rate
suggested_contribution_tiers: Table[
  - tier_name: Data  # e.g., "Student", "Standard", "Supporter", "Patron"
  - annual_amount: Currency
  - description: Text
]

# Special rate categories
student_discount_percentage: Float (default: 50)
hardship_minimum_amount: Currency
enable_custom_amounts: Check (default: 1)
```

### Price History Management Functions

```python
def get_effective_dues_amount(member_name, effective_date=None):
    """
    Get the effective dues amount for a member on a specific date
    Accounts for price history and custom rates
    """
    effective_date = effective_date or today()

    # Check for custom rate in effect on this date
    custom_rate = frappe.db.sql("""
        SELECT amount, change_reason
        FROM `tabMembership Fee Price History`
        WHERE member = %(member)s
        AND effective_date <= %(date)s
        ORDER BY effective_date DESC
        LIMIT 1
    """, {"member": member_name, "date": effective_date}, as_dict=True)

    if custom_rate:
        return {
            "amount": custom_rate[0].amount,
            "source": "custom_rate",
            "reason": custom_rate[0].change_reason
        }

    # Fall back to membership type minimum rate
    membership = get_current_membership(member_name)
    membership_type = frappe.get_doc("Membership Type", membership.membership_type)

    return {
        "amount": membership_type.minimum_annual_fee,
        "source": "membership_type_minimum",
        "reason": "Standard minimum rate"
    }

def create_fee_adjustment(member_name, new_amount, reason, effective_date=None, approved_by=None):
    """
    Create a new fee adjustment with proper validation
    """
    effective_date = effective_date or today()

    # Get current amount for history
    current_amount = get_effective_dues_amount(member_name, add_days(effective_date, -1))

    # Validate new amount against minimums
    membership = get_current_membership(member_name)
    membership_type = frappe.get_doc("Membership Type", membership.membership_type)

    if new_amount < membership_type.minimum_annual_fee:
        if reason not in ["Hardship Rate", "Student Rate"] or not approved_by:
            frappe.throw(f"Amount below minimum €{membership_type.minimum_annual_fee}. Requires approval for hardship/student rates.")

    # Create price history record
    price_history = frappe.new_doc("Membership Fee Price History")
    price_history.member = member_name
    price_history.membership_type = membership.membership_type
    price_history.effective_date = effective_date
    price_history.amount = new_amount
    price_history.previous_amount = current_amount["amount"]
    price_history.change_reason = reason
    price_history.approved_by = approved_by or frappe.session.user
    price_history.insert()

    # Update active dues schedule if exists
    active_schedule = get_active_dues_schedule(member_name)
    if active_schedule:
        # Create audit trail entry
        active_schedule.append("modification_history", {
            "date": now_datetime(),
            "user": frappe.session.user,
            "change_type": "Amount Adjustment",
            "old_value": str(current_amount["amount"]),
            "new_value": str(new_amount),
            "reason": f"{reason} - Effective {effective_date}"
        })

        # Update amount if effective immediately
        if effective_date <= today():
            active_schedule.amount = new_amount
            active_schedule.use_custom_amount = 1
            active_schedule.custom_amount_reason = reason
            active_schedule.custom_amount_approved_by = approved_by
            active_schedule.custom_amount_approved_date = today()

        active_schedule.save()

    return price_history
```

### Calculated Fields & Virtual Properties

```python
# Payment Status (calculated from Member Payment History)
@property
def payment_status(self):
    """
    Returns: Current, Late, Overdue, Seriously Overdue, Suspended
    """
    return calculate_payment_status(self.member, self.grace_period_days)

@property
def days_until_next_invoice(self):
    return (self.next_invoice_date - today()).days

@property
def outstanding_amount(self):
    return get_outstanding_dues(self.member, self.name)

@property
def can_generate_invoice(self):
    # Complex logic considering:
    # - Schedule status
    # - Date calculations
    # - Existing invoices
    # - Payment plans
    # - Special circumstances
    pass
```

---

## 3. Business Process Flows

### 3.1 New Member Onboarding Flow

```mermaid
graph TD
    A[Member Application Approved] --> B{Payment Made During Application?}
    B -->|Yes| C[Create Dues Schedule<br/>Next Date = Today + 1 Year]
    B -->|No| D[Create Dues Schedule<br/>Next Date = Today]

    C --> E[Record Prepayment]
    D --> F[Generate First Invoice]

    E --> G[Send Welcome Email<br/>with Payment Confirmation]
    F --> H[Send Welcome Email<br/>with Invoice]

    G --> I[Member Active]
    H --> I[Member Active]
```

**Implementation Details:**

```python
def handle_approved_application(application):
    # 1. Create member and membership (existing process)
    member = create_member_from_application(application)
    membership = create_membership(member, application.membership_type)

    # 2. Determine billing parameters
    membership_type = frappe.get_doc("Membership Type", application.membership_type)

    # Check for special pricing
    if application.custom_amount and application.custom_amount_approved:
        amount = application.custom_amount
    else:
        amount = membership_type.fee

    # 3. Create dues schedule
    schedule = frappe.new_doc("Membership Dues Schedule")
    schedule.member = member.name
    schedule.membership = membership.name
    schedule.billing_frequency = membership_type.billing_frequency or "Annual"
    schedule.amount = amount

    # 4. Handle payment timing
    if application.payment_id:
        # Payment already made
        schedule.last_invoice_date = today()
        schedule.next_invoice_date = calculate_next_billing_date(
            today(),
            schedule.billing_frequency
        )
        schedule.notes = f"Initial payment: {application.payment_id}"
    else:
        # Need to invoice
        schedule.next_invoice_date = today()
        schedule.invoice_days_before = 0  # Invoice immediately

    # 5. Set grace period based on member type
    if member.is_senior:
        schedule.grace_period_days = 60
        schedule.grace_period_type = "Extended"
    elif member.is_student:
        schedule.grace_period_days = 45
        schedule.grace_period_type = "Extended"
    else:
        schedule.grace_period_days = 30
        schedule.grace_period_type = "Standard"

    schedule.created_from = "Application"
    schedule.insert()

    # 6. Generate invoice if needed
    if not application.payment_id:
        invoice = schedule.generate_invoice(force=True)
        send_welcome_with_invoice(member, invoice)
    else:
        send_welcome_with_confirmation(member, application.payment_id)
```

### 3.2 Invoice Generation Cycle

**Daily Process (Runs at 6 AM):**

```python
def daily_dues_processor():
    """
    Main scheduled job for dues processing
    Runs every day at 6 AM
    """

    # 1. Generate new invoices
    generate_upcoming_invoices()

    # 2. Update payment statuses
    update_all_payment_statuses()

    # 3. Send notifications
    process_payment_notifications()

    # 4. Handle status changes
    process_membership_status_changes()

    # 5. Generate daily report
    create_daily_dues_report()

def generate_upcoming_invoices():
    """Generate invoices for schedules within the invoice window"""

    schedules = frappe.db.sql("""
        SELECT name
        FROM `tabMembership Dues Schedule`
        WHERE status = 'Active'
        AND auto_generate = 1
        AND next_invoice_date <= DATE_ADD(CURDATE(), INTERVAL invoice_days_before DAY)
        AND (last_invoice_date IS NULL OR last_invoice_date != next_invoice_date)
    """, as_dict=True)

    results = {
        "generated": 0,
        "errors": [],
        "skipped": []
    }

    for schedule_data in schedules:
        try:
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_data.name)

            # Additional checks
            if has_recent_payment_plan(schedule.member):
                results["skipped"].append({
                    "schedule": schedule.name,
                    "reason": "Active payment plan"
                })
                continue

            if is_member_deceased(schedule.member):
                schedule.pause_schedule("Member deceased")
                results["skipped"].append({
                    "schedule": schedule.name,
                    "reason": "Member deceased"
                })
                continue

            # Generate invoice with current effective rate
            effective_amount = get_effective_dues_amount(schedule.member, schedule.next_invoice_date)

            # Update schedule amount if rate has changed
            if effective_amount["amount"] != schedule.amount:
                schedule.amount = effective_amount["amount"]
                schedule.add_comment("Info", f"Amount updated to €{effective_amount['amount']} - {effective_amount['reason']}")
                schedule.save()

            invoice = schedule.generate_invoice()
            if invoice:
                results["generated"] += 1

                # Send invoice notification
                send_invoice_notification(schedule.member, invoice)

        except Exception as e:
            results["errors"].append({
                "schedule": schedule_data.name,
                "error": str(e)
            })
            frappe.log_error(f"Invoice generation error: {str(e)}",
                           f"Schedule: {schedule_data.name}")

    return results
```

### 3.3 Payment Status Lifecycle

```
┌─────────┐     T+0      ┌──────┐    T+7     ┌─────────┐
│ Current │─────────────>│ Due  │───────────>│  Late   │
└─────────┘              └──────┘            └─────────┘
                                                   │
                                                   │ T+14
                                                   ▼
┌───────────┐   T+90    ┌───────────────┐   ┌──────────┐
│ Suspended │<──────────│ Seriously     │<──│ Overdue  │
└───────────┘           │ Overdue       │   └──────────┘
                        └───────────────┘         ▲
                              │ T+30              │
                              └───────────────────┘
```

**Status Calculation Logic:**

```python
def calculate_member_payment_status(member_name, grace_period_days=30):
    """
    Calculate payment status based on oldest unpaid invoice
    """

    # Get oldest unpaid invoice
    oldest_unpaid = frappe.db.sql("""
        SELECT
            si.due_date,
            si.name as invoice,
            si.outstanding_amount,
            DATEDIFF(CURDATE(), si.due_date) as days_overdue
        FROM `tabSales Invoice` si
        LEFT JOIN `tabMember Payment History` mph
            ON mph.invoice = si.name AND mph.parent = %(member)s
        WHERE si.customer = %(member)s
        AND si.outstanding_amount > 0
        AND si.docstatus = 1
        AND (mph.payment_status != 'Paid' OR mph.payment_status IS NULL)
        ORDER BY si.due_date ASC
        LIMIT 1
    """, {"member": member_name}, as_dict=True)

    if not oldest_unpaid:
        return {
            "status": "Current",
            "days_overdue": 0,
            "oldest_invoice": None,
            "outstanding_amount": 0
        }

    days_overdue = oldest_unpaid.days_overdue

    # Determine status based on days and grace period
    if days_overdue <= 0:
        status = "Current"
    elif days_overdue <= 7:
        status = "Late"
    elif days_overdue <= grace_period_days:
        status = "Overdue"
    elif days_overdue <= grace_period_days + 30:
        status = "Seriously Overdue"
    else:
        status = "Suspended"

    # Check for mitigating factors
    if status in ["Seriously Overdue", "Suspended"]:
        # Check if payment plan exists
        if has_active_payment_plan(member_name):
            status = "Payment Plan"

        # Check if hardship exemption
        elif has_hardship_exemption(member_name):
            status = "Hardship"

    return {
        "status": status,
        "days_overdue": days_overdue,
        "oldest_invoice": oldest_unpaid.invoice,
        "outstanding_amount": oldest_unpaid.outstanding_amount,
        "grace_period_remaining": max(0, grace_period_days - days_overdue)
    }
```

### 3.4 Notification Engine Details

**Multi-Stage Notification System:**

```python
class DuesNotificationEngine:
    def __init__(self):
        self.stages = [
            # (days_relative_to_due, template, condition)
            (-30, "upcoming_dues", self.should_send_upcoming),
            (-14, "invoice_ready", self.should_send_invoice),
            (0, "due_date_reminder", self.should_send_due_reminder),
            (7, "gentle_reminder", self.should_send_gentle),
            (14, "overdue_notice", self.should_send_overdue),
            (30, "final_notice", self.should_send_final),
            (60, "suspension_warning", self.should_send_suspension_warning),
            (90, "suspension_notice", self.should_send_suspension)
        ]

    def process_notifications(self):
        """Run daily to process all notification stages"""

        for days_offset, template, condition_func in self.stages:
            members = self.get_members_at_stage(days_offset)

            for member in members:
                if condition_func(member):
                    self.send_notification(member, template)

    def should_send_upcoming(self, member):
        """Check if upcoming dues reminder should be sent"""
        # Skip if:
        # - Member opted out of early reminders
        # - Member has auto-pay enabled
        # - Member is on payment plan

        if member.notification_preferences.get("skip_upcoming_reminder"):
            return False

        if has_active_sepa_mandate(member.name):
            return False

        if has_active_payment_plan(member.name):
            return False

        return True

    def send_notification(self, member, template_name):
        """Send notification with smart delivery"""

        # Get member's preferred channels
        channels = get_notification_channels(member)

        # Get template
        template = get_notification_template(template_name, member.language)

        # Prepare context
        context = self.prepare_context(member, template_name)

        # Send via each channel
        for channel in channels:
            if channel == "email":
                send_email_notification(member, template, context)
            elif channel == "sms" and template.sms_enabled:
                send_sms_notification(member, template, context)
            elif channel == "portal":
                create_portal_notification(member, template, context)

        # Log notification
        log_notification_sent(member, template_name, channels)

    def prepare_context(self, member, template_name):
        """Prepare template context with member-specific data"""

        payment_status = calculate_member_payment_status(member.name)

        context = {
            "member": member,
            "first_name": member.first_name,
            "payment_status": payment_status,
            "outstanding_amount": payment_status.outstanding_amount,
            "days_overdue": payment_status.days_overdue,
            "portal_link": get_member_portal_link(member),
            "payment_link": get_payment_link(member),
            "contact_link": get_contact_link()
        }

        # Add template-specific context
        if template_name == "upcoming_dues":
            schedule = get_active_dues_schedule(member.name)
            context.update({
                "due_date": schedule.next_invoice_date,
                "amount": schedule.amount,
                "billing_period": get_billing_period_description(schedule)
            })

        elif template_name == "suspension_warning":
            context.update({
                "suspension_date": add_days(today(), 30),
                "prevention_options": get_suspension_prevention_options(),
                "consequences": get_suspension_consequences()
            })

        return context
```

### 3.5 Payment Plan Management

**Creating Payment Plans:**

```python
def create_payment_plan_wizard(member_name, outstanding_amount):
    """
    Interactive payment plan creation
    """

    # 1. Analyze member's payment history
    payment_analysis = analyze_payment_history(member_name)

    # 2. Suggest payment plan options
    options = []

    # Standard options
    options.extend([
        {
            "name": "3 Month Plan",
            "installments": 3,
            "amount_per_installment": outstanding_amount / 3,
            "fee": 0,
            "description": "Pay off balance in 3 monthly installments"
        },
        {
            "name": "6 Month Plan",
            "installments": 6,
            "amount_per_installment": outstanding_amount / 6,
            "fee": 0,
            "description": "Pay off balance in 6 monthly installments"
        }
    ])

    # Custom option based on history
    if payment_analysis.average_payment_amount > 0:
        suggested_installments = ceil(outstanding_amount / payment_analysis.average_payment_amount)
        options.append({
            "name": "Custom Plan",
            "installments": suggested_installments,
            "amount_per_installment": payment_analysis.average_payment_amount,
            "fee": 0,
            "description": f"Based on your typical payment amount of €{payment_analysis.average_payment_amount}"
        })

    return options

def implement_payment_plan(member_name, plan_details):
    """
    Create payment plan with multiple dues schedules
    """

    # 1. Pause main schedule
    main_schedule = get_active_dues_schedule(member_name)
    main_schedule.pause_schedule("Payment plan active")

    # 2. Create payment plan record
    plan = frappe.new_doc("Member Payment Plan")
    plan.member = member_name
    plan.total_amount = plan_details.total_amount
    plan.installments = plan_details.installments
    plan.start_date = plan_details.start_date or today()
    plan.notes = plan_details.notes
    plan.insert()

    # 3. Create installment schedules
    installment_amount = plan.total_amount / plan.installments

    for i in range(plan.installments):
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.member = member_name
        schedule.membership = main_schedule.membership
        schedule.billing_frequency = "Custom"
        schedule.amount = installment_amount
        schedule.next_invoice_date = add_months(plan.start_date, i)
        schedule.grace_period_days = 14  # Shorter grace for payment plans
        schedule.auto_generate = 1
        schedule.original_schedule = main_schedule.name
        schedule.payment_plan_reference = plan.name
        schedule.notes = f"Payment plan installment {i+1} of {plan.installments}"
        schedule.insert()

    # 4. Send confirmation
    send_payment_plan_confirmation(member_name, plan)

    return plan
```

---

## 4. Technical Implementation Details

### 4.1 Database Optimizations

**Indexes for Performance:**

```sql
-- For finding schedules due for processing
CREATE INDEX idx_dues_schedule_processing
ON `tabMembership Dues Schedule` (status, auto_generate, next_invoice_date);

-- For payment status queries
CREATE INDEX idx_sales_invoice_member_status
ON `tabSales Invoice` (customer, outstanding_amount, due_date, docstatus);

-- For notification tracking
CREATE INDEX idx_notification_log_lookup
ON `tabNotification Log` (reference_doctype, reference_name, template, sent_date);
```

### 4.2 Caching Strategy

```python
# Cache payment status for dashboard performance
def get_cached_payment_status(member_name):
    cache_key = f"payment_status:{member_name}"

    # Try cache first
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    # Calculate fresh
    status = calculate_member_payment_status(member_name)

    # Cache for 1 hour
    frappe.cache().set_value(cache_key, status, expires_in_sec=3600)

    return status

# Invalidate on payment events
def invalidate_payment_cache(doc, method):
    if doc.doctype == "Payment Entry" and doc.party_type == "Customer":
        cache_key = f"payment_status:{doc.party}"
        frappe.cache().delete_value(cache_key)
```

### 4.3 Error Handling & Recovery

```python
class DuesProcessingError(Exception):
    """Custom exception for dues processing errors"""
    pass

def safe_invoice_generation(schedule_name):
    """
    Generate invoice with comprehensive error handling
    """
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

            # Pre-flight checks
            if not schedule.can_generate_invoice():
                return {
                    "success": False,
                    "reason": "Invoice generation criteria not met"
                }

            # Begin transaction
            frappe.db.begin()

            # Generate invoice
            invoice = schedule.generate_invoice()

            # Post-generation validation
            validate_generated_invoice(invoice)

            # Commit transaction
            frappe.db.commit()

            return {
                "success": True,
                "invoice": invoice,
                "schedule": schedule_name
            }

        except frappe.ValidationError as e:
            frappe.db.rollback()
            # Don't retry validation errors
            return {
                "success": False,
                "error": str(e),
                "error_type": "validation"
            }

        except Exception as e:
            frappe.db.rollback()
            retry_count += 1

            if retry_count >= max_retries:
                # Log critical error
                frappe.log_error(
                    f"Failed to generate invoice after {max_retries} attempts",
                    f"Schedule: {schedule_name}"
                )

                # Notify admins
                notify_critical_error(
                    "Invoice Generation Failed",
                    f"Schedule {schedule_name} failed after {max_retries} attempts: {str(e)}"
                )

                return {
                    "success": False,
                    "error": str(e),
                    "error_type": "critical",
                    "retries": retry_count
                }

            # Wait before retry
            time.sleep(2 ** retry_count)  # Exponential backoff
```

### 4.4 Monitoring & Alerting

```python
# Health check endpoint
@frappe.whitelist(allow_guest=True)
def dues_system_health_check():
    """
    Comprehensive health check for monitoring
    """

    health = {
        "status": "healthy",
        "timestamp": now_datetime(),
        "checks": {}
    }

    # Check 1: Recent invoice generation
    last_generation = frappe.db.sql("""
        SELECT MAX(creation) as last_run
        FROM `tabSales Invoice`
        WHERE remarks LIKE '%Dues Schedule%'
        AND creation > DATE_SUB(NOW(), INTERVAL 1 DAY)
    """)[0][0]

    if not last_generation:
        health["status"] = "warning"
        health["checks"]["invoice_generation"] = "No invoices in last 24 hours"
    else:
        health["checks"]["invoice_generation"] = "OK"

    # Check 2: Stuck schedules
    stuck_schedules = frappe.db.count("Membership Dues Schedule", {
        "status": "Active",
        "next_invoice_date": ["<", add_days(today(), -7)]
    })

    if stuck_schedules > 0:
        health["status"] = "critical"
        health["checks"]["stuck_schedules"] = f"{stuck_schedules} schedules overdue"
    else:
        health["checks"]["stuck_schedules"] = "OK"

    # Check 3: Notification queue
    pending_notifications = frappe.db.count("Email Queue", {
        "status": "Not Sent",
        "creation": ["<", add_hours(now_datetime(), -2)]
    })

    if pending_notifications > 100:
        health["status"] = "warning"
        health["checks"]["notification_queue"] = f"{pending_notifications} stuck emails"
    else:
        health["checks"]["notification_queue"] = "OK"

    return health
```

---

## 5. User Experience Flows

### 5.1 Member Portal Experience

#### Enhanced Contribution Fee Selection

```html
<!-- Enhanced Membership Fee Selection Form -->
<div class="contribution-selection-card">
    <h3>Choose Your Annual Contribution</h3>

    <div class="fee-structure-info">
        <p>Our minimum annual membership fee is €{{ membership_type.minimum_annual_fee }},
        but many members choose to contribute more to support our mission.</p>
    </div>

    <!-- Suggested Contribution Tiers -->
    <div class="contribution-tiers">
        {% for tier in membership_type.suggested_contribution_tiers %}
        <div class="tier-option" data-amount="{{ tier.annual_amount }}">
            <div class="tier-header">
                <h4>{{ tier.tier_name }}</h4>
                <span class="tier-amount">€{{ tier.annual_amount }}/year</span>
            </div>
            <p class="tier-description">{{ tier.description }}</p>
            <button class="btn btn-outline-primary select-tier"
                    onclick="selectTier({{ tier.annual_amount }})">
                Select This Amount
            </button>
        </div>
        {% endfor %}
    </div>

    <!-- Custom Amount Selection -->
    <div class="custom-amount-section">
        <h4>Choose Your Own Amount</h4>
        <div class="custom-amount-input">
            <label>Annual Contribution (minimum €{{ membership_type.minimum_annual_fee }})</label>
            <div class="input-group">
                <span class="input-group-text">€</span>
                <input type="number"
                       id="custom_amount"
                       class="form-control"
                       min="{{ membership_type.minimum_annual_fee }}"
                       step="1"
                       placeholder="{{ membership_type.standard_annual_fee }}">
                <span class="input-group-text">/year</span>
            </div>
            <small class="form-text text-muted">
                You can adjust this amount at any time through your member portal.
            </small>
        </div>
    </div>

    <!-- Special Circumstances -->
    <div class="special-circumstances">
        <h4>Special Circumstances</h4>

        <div class="circumstances-options">
            <div class="form-check">
                <input class="form-check-input" type="checkbox" id="student_rate">
                <label class="form-check-label" for="student_rate">
                    I am a student ({{ membership_type.student_discount_percentage }}% discount available)
                </label>
            </div>

            <div class="form-check">
                <input class="form-check-input" type="checkbox" id="hardship_rate">
                <label class="form-check-label" for="hardship_rate">
                    I am experiencing financial hardship
                </label>
            </div>
        </div>

        <div id="hardship_explanation" style="display: none;">
            <p class="text-info">
                <i class="fa fa-info-circle"></i>
                If you're experiencing financial difficulties, we offer reduced rates starting at
                €{{ membership_type.hardship_minimum_amount }}. Your request will be reviewed confidentially.
            </p>
            <textarea class="form-control"
                      id="hardship_reason"
                      placeholder="Please briefly explain your circumstances (optional - this information is kept confidential)"></textarea>
        </div>
    </div>

    <!-- Final Selection Display -->
    <div class="selected-amount-display">
        <h4>Selected Annual Contribution: €<span id="final_amount">{{ membership_type.standard_annual_fee }}</span></h4>
        <p id="amount_breakdown"></p>
    </div>
</div>

<script>
function selectTier(amount) {
    document.getElementById('custom_amount').value = amount;
    updateFinalAmount(amount);
    document.querySelectorAll('.tier-option').forEach(t => t.classList.remove('selected'));
    event.target.closest('.tier-option').classList.add('selected');
}

function updateFinalAmount(amount) {
    document.getElementById('final_amount').textContent = amount;

    let breakdown = '';
    if (amount > {{ membership_type.standard_annual_fee }}) {
        breakdown = `Thank you for your generous support! Your extra contribution of €${amount - {{ membership_type.standard_annual_fee }}} helps fund our programs.`;
    } else if (amount == {{ membership_type.minimum_annual_fee }}) {
        breakdown = 'Minimum membership fee selected.';
    } else {
        breakdown = 'Standard membership contribution selected.';
    }

    document.getElementById('amount_breakdown').textContent = breakdown;
}

// Handle special circumstances
document.getElementById('hardship_rate').addEventListener('change', function() {
    document.getElementById('hardship_explanation').style.display =
        this.checked ? 'block' : 'none';

    if (this.checked) {
        document.getElementById('custom_amount').value = {{ membership_type.hardship_minimum_amount }};
        updateFinalAmount({{ membership_type.hardship_minimum_amount }});
    }
});

document.getElementById('student_rate').addEventListener('change', function() {
    if (this.checked) {
        const studentAmount = Math.max(
            {{ membership_type.minimum_annual_fee }},
            {{ membership_type.standard_annual_fee }} * (1 - {{ membership_type.student_discount_percentage }}/100)
        );
        document.getElementById('custom_amount').value = studentAmount;
        updateFinalAmount(studentAmount);
    }
});

// Real-time validation
document.getElementById('custom_amount').addEventListener('input', function() {
    const amount = parseFloat(this.value);
    const minimum = {{ membership_type.minimum_annual_fee }};

    if (amount < minimum) {
        this.setCustomValidity(`Minimum amount is €${minimum}`);
        this.classList.add('is-invalid');
    } else {
        this.setCustomValidity('');
        this.classList.remove('is-invalid');
        updateFinalAmount(amount);
    }
});
</script>
```

### 5.1 Member Portal Experience

**Dashboard View:**

```html
<!-- Member Payment Dashboard -->
<div class="payment-status-card">
    <div class="status-indicator {{ status_class }}">
        <i class="fa fa-{{ status_icon }}"></i>
        <span>{{ status_text }}</span>
    </div>

    {% if status == "Current" %}
    <div class="next-due-info">
        <p>Your next payment of €{{ next_amount }} is due on {{ next_date|date:"F d, Y" }}</p>
        <button class="btn btn-sm btn-primary">Enable Auto-Pay</button>
    </div>
    {% endif %}

    {% if outstanding_amount > 0 %}
    <div class="outstanding-alert">
        <p>You have an outstanding balance of €{{ outstanding_amount }}</p>
        <div class="action-buttons">
            <button class="btn btn-primary" onclick="payNow()">Pay Now</button>
            <button class="btn btn-secondary" onclick="requestPaymentPlan()">Payment Plan</button>
            <button class="btn btn-link" onclick="contactUs()">Need Help?</button>
        </div>
    </div>
    {% endif %}

    <div class="payment-history-summary">
        <h4>Recent Payments</h4>
        {% for payment in recent_payments %}
        <div class="payment-row">
            <span>{{ payment.date|date:"M d" }}</span>
            <span>€{{ payment.amount }}</span>
            <span class="status-badge {{ payment.status|lower }}">{{ payment.status }}</span>
        </div>
        {% endfor %}
        <a href="/payment-history">View Full History →</a>
    </div>
</div>
```

**Self-Service Actions:**

```python
@frappe.whitelist()
def member_request_payment_plan():
    """
    Member-initiated payment plan request
    """
    member = get_current_member()

    # Check eligibility
    eligibility = check_payment_plan_eligibility(member)

    if not eligibility.eligible:
        return {
            "success": False,
            "reason": eligibility.reason,
            "next_eligible_date": eligibility.next_eligible_date
        }

    # Get outstanding amount
    outstanding = get_total_outstanding(member.name)

    # Generate options
    options = generate_payment_plan_options(member.name, outstanding)

    return {
        "success": True,
        "outstanding_amount": outstanding,
        "options": options,
        "terms": get_payment_plan_terms()
    }

@frappe.whitelist()
def member_update_payment_method():
    """
    Update payment method with validation
    """
    member = get_current_member()
    data = frappe.form_dict

    if data.payment_method == "sepa_direct_debit":
        # Validate IBAN
        iban_validation = validate_iban(data.iban)
        if not iban_validation.valid:
            return {"success": False, "error": iban_validation.error}

        # Create/update SEPA mandate
        mandate = create_or_update_sepa_mandate(
            member.name,
            data.iban,
            data.account_holder_name
        )

        # Update dues schedules
        update_member_payment_method(member.name, "SEPA Direct Debit")

        return {
            "success": True,
            "mandate_reference": mandate.name,
            "next_debit_date": get_next_debit_date()
        }

    elif data.payment_method == "bank_transfer":
        # Just update preference
        update_member_payment_method(member.name, "Bank Transfer")

        return {
            "success": True,
            "bank_details": get_organization_bank_details()
        }
```

### 5.2 Staff Administration Interface

**Enhanced Overdue Payments Report:**

```javascript
// Add action buttons to report
frappe.query_reports["Overdue Member Payments"] = {
    onload: function(report) {
        // Add custom buttons
        report.page.add_inner_button(__("Send Bulk Reminders"), function() {
            handle_bulk_reminders(report);
        });

        report.page.add_inner_button(__("Create Payment Plans"), function() {
            handle_bulk_payment_plans(report);
        });

        report.page.add_inner_button(__("Export for Mail Merge"), function() {
            export_for_mail_merge(report);
        });
    },

    formatter: function(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);

        // Add action buttons to each row
        if (column.fieldname == "member_name" && data) {
            value += `
                <div class="row-actions" style="float: right;">
                    <button class="btn btn-xs btn-default"
                        onclick="send_reminder('${data.member_name}')">
                        <i class="fa fa-envelope"></i>
                    </button>
                    <button class="btn btn-xs btn-default"
                        onclick="create_payment_plan('${data.member_name}')">
                        <i class="fa fa-calendar"></i>
                    </button>
                    <button class="btn btn-xs btn-default"
                        onclick="view_history('${data.member_name}')">
                        <i class="fa fa-history"></i>
                    </button>
                </div>
            `;
        }

        return value;
    }
};

function handle_bulk_reminders(report) {
    // Get selected members or all if none selected
    let members = report.get_checked_items() || report.data;

    frappe.prompt([
        {
            fieldname: 'template',
            label: 'Reminder Template',
            fieldtype: 'Select',
            options: [
                'Gentle Reminder',
                'Overdue Notice',
                'Final Notice',
                'Custom'
            ],
            default: 'Gentle Reminder'
        },
        {
            fieldname: 'custom_message',
            label: 'Additional Message',
            fieldtype: 'Text',
            depends_on: 'eval:doc.template=="Custom"'
        },
        {
            fieldname: 'skip_recent',
            label: 'Skip if contacted in last X days',
            fieldtype: 'Int',
            default: 7
        }
    ],
    function(values) {
        frappe.call({
            method: 'verenigingen.api.send_bulk_payment_reminders',
            args: {
                members: members.map(m => m.member_name),
                template: values.template,
                custom_message: values.custom_message,
                skip_recent_days: values.skip_recent
            },
            callback: function(r) {
                frappe.msgprint(`Sent ${r.message.sent} reminders, skipped ${r.message.skipped}`);
                report.refresh();
            }
        });
    },
    'Send Bulk Reminders',
    'Send'
    );
}
```

**Quick Action Dialogs:**

```javascript
function create_payment_plan(member_name) {
    frappe.call({
        method: 'verenigingen.api.get_member_outstanding_details',
        args: { member: member_name },
        callback: function(r) {
            let outstanding = r.message.outstanding_amount;
            let options = r.message.suggested_plans;

            let dialog = new frappe.ui.Dialog({
                title: `Create Payment Plan for ${member_name}`,
                fields: [
                    {
                        fieldname: 'outstanding_display',
                        fieldtype: 'HTML',
                        options: `<h4>Outstanding Amount: €${outstanding}</h4>`
                    },
                    {
                        fieldname: 'plan_type',
                        label: 'Payment Plan Type',
                        fieldtype: 'Select',
                        options: options.map(o => o.name).join('\n'),
                        default: options[0].name,
                        onchange: function() {
                            update_plan_preview(dialog, options);
                        }
                    },
                    {
                        fieldname: 'start_date',
                        label: 'Start Date',
                        fieldtype: 'Date',
                        default: frappe.datetime.get_today()
                    },
                    {
                        fieldname: 'preview',
                        fieldtype: 'HTML',
                        label: 'Payment Schedule Preview'
                    },
                    {
                        fieldname: 'notes',
                        label: 'Notes',
                        fieldtype: 'Text'
                    },
                    {
                        fieldname: 'send_confirmation',
                        label: 'Send Confirmation Email',
                        fieldtype: 'Check',
                        default: 1
                    }
                ],
                primary_action_label: 'Create Plan',
                primary_action(values) {
                    frappe.call({
                        method: 'verenigingen.api.create_payment_plan',
                        args: {
                            member: member_name,
                            plan_type: values.plan_type,
                            start_date: values.start_date,
                            notes: values.notes,
                            send_confirmation: values.send_confirmation
                        },
                        callback: function(r) {
                            dialog.hide();
                            frappe.show_alert({
                                message: 'Payment plan created successfully',
                                indicator: 'green'
                            });
                            frappe.set_route('Form', 'Member Payment Plan', r.message);
                        }
                    });
                }
            });

            dialog.show();
            update_plan_preview(dialog, options);
        }
    });
}
```

---

## 6. Integration Points

### 6.1 SEPA Direct Debit Integration

```python
def process_dues_with_sepa():
    """
    Monthly SEPA batch generation for dues
    """

    # Find members with active SEPA mandates and due invoices
    eligible_members = frappe.db.sql("""
        SELECT DISTINCT
            m.name as member,
            sm.name as mandate,
            sm.iban,
            sm.bic,
            SUM(si.outstanding_amount) as amount
        FROM `tabMember` m
        INNER JOIN `tabSEPA Mandate` sm ON sm.party = m.name
        INNER JOIN `tabSales Invoice` si ON si.customer = m.name
        WHERE sm.status = 'Active'
        AND si.outstanding_amount > 0
        AND si.due_date <= CURDATE()
        AND m.name IN (
            SELECT member
            FROM `tabMembership Dues Schedule`
            WHERE status = 'Active'
        )
        GROUP BY m.name, sm.name
    """, as_dict=True)

    if not eligible_members:
        return

    # Create SEPA batch
    batch = frappe.new_doc("Direct Debit Batch")
    batch.batch_type = "Membership Dues"
    batch.execution_date = add_days(today(), 3)  # SEPA requires 3 days notice

    for member_data in eligible_members:
        batch.append("transactions", {
            "party_type": "Customer",
            "party": member_data.member,
            "mandate": member_data.mandate,
            "amount": member_data.amount,
            "currency": "EUR",
            "description": f"Membership dues {today().strftime('%B %Y')}"
        })

    batch.insert()

    # Notify members about upcoming debit
    for member_data in eligible_members:
        send_sepa_pre_notification(
            member_data.member,
            member_data.amount,
            batch.execution_date
        )

    return batch
```

### 6.2 Accounting Integration

```python
def setup_dues_accounting():
    """
    Setup chart of accounts for dues system
    """

    accounts_to_create = [
        {
            "account_name": "Membership Dues Receivable",
            "parent_account": "Accounts Receivable",
            "account_type": "Receivable",
            "account_currency": "EUR"
        },
        {
            "account_name": "Membership Dues Income",
            "parent_account": "Direct Income",
            "account_type": "Income Account",
            "account_currency": "EUR"
        },
        {
            "account_name": "Membership Dues Discounts",
            "parent_account": "Direct Expenses",
            "account_type": "Expense Account",
            "account_currency": "EUR"
        },
        {
            "account_name": "Membership Dues Write-offs",
            "parent_account": "Indirect Expenses",
            "account_type": "Expense Account",
            "account_currency": "EUR"
        }
    ]

    for account_data in accounts_to_create:
        if not frappe.db.exists("Account", account_data["account_name"]):
            account = frappe.new_doc("Account")
            account.update(account_data)
            account.insert()

def get_dues_item_accounting_details():
    """
    Get accounting configuration for dues items
    """
    return {
        "income_account": "Membership Dues Income",
        "receivable_account": "Membership Dues Receivable",
        "cost_center": get_membership_cost_center(),
        "tax_template": get_membership_tax_template()  # Usually tax-exempt
    }
```

### 6.3 Credit Notes and Refunds System

```python
class DuesRefundManager:
    """
    Comprehensive refund and credit management for membership dues
    """

    def __init__(self):
        self.refund_reasons = [
            "Overpayment", "Duplicate Payment", "Membership Cancellation",
            "Downgrade Adjustment", "System Error", "Goodwill Gesture",
            "Membership Termination", "Pro-rata Refund"
        ]

    def process_refund_request(self, member_name, amount, reason, effective_date=None):
        """
        Process a refund request with proper workflow
        """
        effective_date = effective_date or today()

        # Validate refund eligibility
        eligibility = self.check_refund_eligibility(member_name, amount, reason)
        if not eligibility["eligible"]:
            frappe.throw(eligibility["reason"])

        # Determine refund method
        refund_method = self.determine_refund_method(member_name, amount)

        if refund_method == "credit_note":
            return self.create_credit_note(member_name, amount, reason, effective_date)
        elif refund_method == "bank_transfer":
            return self.process_bank_refund(member_name, amount, reason, effective_date)
        elif refund_method == "sepa_refund":
            return self.process_sepa_refund(member_name, amount, reason, effective_date)

    def create_credit_note(self, member_name, amount, reason, effective_date):
        """
        Create ERPNext credit note for dues refund
        """
        # Get original invoice for reference
        original_invoice = self.find_refund_source_invoice(member_name, amount)

        # Create credit note
        credit_note = frappe.new_doc("Sales Invoice")
        credit_note.customer = member_name
        credit_note.is_return = 1
        credit_note.return_against = original_invoice.name if original_invoice else None
        credit_note.posting_date = effective_date
        credit_note.due_date = effective_date

        # Add credit note item
        credit_note.append("items", {
            "item_code": get_membership_dues_item(),
            "qty": -1,  # Negative quantity for credit
            "rate": amount,
            "amount": -amount,
            "description": f"Membership dues refund - {reason}"
        })

        # Set accounting details
        accounting_details = get_dues_item_accounting_details()
        credit_note.items[0].income_account = accounting_details["income_account"]
        credit_note.items[0].cost_center = accounting_details["cost_center"]

        # Add custom fields for tracking
        credit_note.refund_reason = reason
        credit_note.refund_type = "Membership Dues"
        credit_note.remarks = f"Credit note for membership dues refund - {reason}"

        credit_note.insert()
        credit_note.submit()

        # Update member payment history
        self.update_payment_history_for_refund(member_name, credit_note, amount, reason)

        # Send notification
        self.send_refund_notification(member_name, credit_note, "credit_note")

        return credit_note

    def process_bank_refund(self, member_name, amount, reason, effective_date):
        """
        Process bank transfer refund
        """
        member = frappe.get_doc("Member", member_name)

        # Get member's bank details
        bank_details = self.get_member_bank_details(member_name)
        if not bank_details:
            frappe.throw("Member bank details required for refund")

        # Create payment entry for refund
        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.payment_type = "Pay"
        payment_entry.party_type = "Customer"
        payment_entry.party = member_name
        payment_entry.paid_from = get_default_bank_account()
        payment_entry.paid_to = get_accounts_receivable_account()
        payment_entry.paid_amount = amount
        payment_entry.received_amount = amount
        payment_entry.reference_no = f"REF-{member_name}-{random_string(6)}"
        payment_entry.reference_date = effective_date
        payment_entry.posting_date = effective_date

        # Add refund details
        payment_entry.refund_reason = reason
        payment_entry.remarks = f"Membership dues refund - {reason}"

        payment_entry.insert()
        payment_entry.submit()

        # Create refund instruction for accounting team
        self.create_refund_instruction(member_name, payment_entry, bank_details, reason)

        # Update payment history
        self.update_payment_history_for_refund(member_name, payment_entry, amount, reason)

        # Send notification
        self.send_refund_notification(member_name, payment_entry, "bank_transfer")

        return payment_entry

    def check_refund_eligibility(self, member_name, amount, reason):
        """
        Check if refund is eligible based on business rules
        """
        # Get member's payment history
        payment_history = get_member_payment_history(member_name, months=24)

        # Rule 1: Can't refund more than paid in last 24 months
        total_paid = sum(p.amount for p in payment_history if p.payment_status == "Paid")
        if amount > total_paid:
            return {
                "eligible": False,
                "reason": f"Refund amount €{amount} exceeds total payments €{total_paid} in last 24 months"
            }

        # Rule 2: Check for existing pending refunds
        pending_refunds = frappe.db.count("Payment Entry", {
            "party": member_name,
            "payment_type": "Pay",
            "docstatus": 1,
            "refund_reason": ["!=", ""],
            "creation": [">", add_months(now_datetime(), -6)]
        })

        if pending_refunds > 2:
            return {
                "eligible": False,
                "reason": "Member has multiple recent refunds - manual review required"
            }

        # Rule 3: Membership status check for certain reasons
        if reason in ["Membership Cancellation", "Membership Termination"]:
            member = frappe.get_doc("Member", member_name)
            if member.status == "Active":
                return {
                    "eligible": False,
                    "reason": "Cannot process cancellation refund for active member"
                }

        return {"eligible": True, "reason": "Eligible for refund"}

    def calculate_prorata_refund(self, member_name, termination_date):
        """
        Calculate pro-rata refund for membership termination
        """
        # Get active dues schedule
        schedule = get_active_dues_schedule(member_name)
        if not schedule:
            return {"amount": 0, "reason": "No active dues schedule"}

        # Find last payment and coverage period
        last_payment = frappe.db.sql("""
            SELECT si.posting_date, si.paid_amount, si.outstanding_amount
            FROM `tabSales Invoice` si
            LEFT JOIN `tabMember Payment History` mph
                ON mph.invoice = si.name AND mph.parent = %(member)s
            WHERE si.customer = %(member)s
            AND si.paid_amount > 0
            AND si.docstatus = 1
            ORDER BY si.posting_date DESC
            LIMIT 1
        """, {"member": member_name}, as_dict=True)

        if not last_payment:
            return {"amount": 0, "reason": "No payments found"}

        # Calculate coverage period based on billing frequency
        payment_date = getdate(last_payment[0].posting_date)

        if schedule.billing_frequency == "Annual":
            coverage_end = add_months(payment_date, 12)
        elif schedule.billing_frequency == "Semi-Annual":
            coverage_end = add_months(payment_date, 6)
        elif schedule.billing_frequency == "Quarterly":
            coverage_end = add_months(payment_date, 3)
        elif schedule.billing_frequency == "Monthly":
            coverage_end = add_months(payment_date, 1)

        # Calculate unused period
        termination_date = getdate(termination_date)
        if termination_date >= coverage_end:
            return {"amount": 0, "reason": "Termination after coverage period ends"}

        total_days = (coverage_end - payment_date).days
        unused_days = (coverage_end - termination_date).days

        if unused_days <= 0:
            return {"amount": 0, "reason": "No unused coverage period"}

        refund_amount = (last_payment[0].paid_amount * unused_days) / total_days

        return {
            "amount": round(refund_amount, 2),
            "reason": f"Pro-rata refund for {unused_days} unused days out of {total_days}",
            "coverage_start": payment_date,
            "coverage_end": coverage_end,
            "termination_date": termination_date
        }

def get_member_bank_details(member_name):
    """Get member's bank details for refund processing"""
    # Check for active SEPA mandate first
    sepa_mandate = frappe.db.get_value("SEPA Mandate",
        {"party": member_name, "status": "Active"},
        ["iban", "account_holder_name"], as_dict=True)

    if sepa_mandate:
        return {
            "method": "SEPA",
            "iban": sepa_mandate.iban,
            "account_holder": sepa_mandate.account_holder_name
        }

    # Check member profile for bank details
    member = frappe.get_doc("Member", member_name)
    if hasattr(member, 'bank_account_iban') and member.bank_account_iban:
        return {
            "method": "Bank Transfer",
            "iban": member.bank_account_iban,
            "account_holder": f"{member.first_name} {member.last_name}"
        }

    return None
```

### 6.4 Payment Gateway Integration

```python
class PaymentGatewayIntegration:
    """
    Comprehensive payment gateway integration for online dues payments
    """

    def __init__(self):
        self.supported_gateways = ["stripe", "mollie", "paypal", "adyen"]
        self.supported_methods = ["card", "ideal", "sofort", "bancontact", "paypal"]

    def create_payment_intent(self, member_name, amount, payment_method="card"):
        """
        Create payment intent for member dues payment
        """
        member = frappe.get_doc("Member", member_name)

        # Get active dues schedule for context
        schedule = get_active_dues_schedule(member_name)
        outstanding = get_total_outstanding(member_name)

        # Determine payment gateway based on settings
        gateway = self.get_preferred_gateway(member.country)

        # Create payment metadata
        metadata = {
            "member_id": member_name,
            "member_email": member.email,
            "purpose": "membership_dues",
            "outstanding_amount": outstanding,
            "billing_frequency": schedule.billing_frequency if schedule else "Annual"
        }

        if gateway == "stripe":
            return self.create_stripe_payment_intent(amount, metadata, payment_method)
        elif gateway == "mollie":
            return self.create_mollie_payment(amount, metadata, payment_method)
        elif gateway == "paypal":
            return self.create_paypal_payment(amount, metadata)
        elif gateway == "adyen":
            return self.create_adyen_payment(amount, metadata, payment_method)

    def create_stripe_payment_intent(self, amount, metadata, payment_method):
        """Create Stripe payment intent"""
        import stripe

        stripe.api_key = get_stripe_secret_key()

        intent = stripe.PaymentIntent.create(
            amount=int(amount * 100),  # Stripe uses cents
            currency='eur',
            payment_method_types=[payment_method] if payment_method != "card" else ["card", "sepa_debit", "ideal"],
            metadata=metadata,
            description=f"Membership dues payment - {metadata['member_email']}",
            receipt_email=metadata['member_email'],
            setup_future_usage="off_session" if metadata.get('save_payment_method') else None
        )

        return {
            "gateway": "stripe",
            "payment_id": intent.id,
            "client_secret": intent.client_secret,
            "amount": amount,
            "currency": "EUR",
            "status": intent.status
        }

    def create_mollie_payment(self, amount, metadata, payment_method):
        """Create Mollie payment"""
        from mollie.api.client import Client

        mollie_client = Client()
        mollie_client.set_api_key(get_mollie_api_key())

        payment = mollie_client.payments.create({
            "amount": {
                "currency": "EUR",
                "value": f"{amount:.2f}"
            },
            "description": f"Membership dues - {metadata['member_email']}",
            "redirectUrl": get_payment_success_url(),
            "webhookUrl": get_mollie_webhook_url(),
            "method": payment_method,
            "metadata": metadata
        })

        return {
            "gateway": "mollie",
            "payment_id": payment.id,
            "checkout_url": payment.checkout_url,
            "amount": amount,
            "currency": "EUR",
            "status": payment.status
        }

    def handle_payment_webhook(self, gateway, payload):
        """Handle payment gateway webhooks"""
        if gateway == "stripe":
            return self.handle_stripe_webhook(payload)
        elif gateway == "mollie":
            return self.handle_mollie_webhook(payload)
        # Add other gateways...

    def handle_successful_payment(self, payment_data):
        """Process successful payment from any gateway"""
        member_name = payment_data["metadata"]["member_id"]
        amount = payment_data["amount"]
        gateway_transaction_id = payment_data["payment_id"]

        # Create ERPNext payment entry
        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.payment_type = "Receive"
        payment_entry.party_type = "Customer"
        payment_entry.party = member_name
        payment_entry.paid_from = get_default_bank_account()
        payment_entry.paid_to = get_accounts_receivable_account()
        payment_entry.paid_amount = amount
        payment_entry.received_amount = amount
        payment_entry.reference_no = gateway_transaction_id
        payment_entry.reference_date = today()
        payment_entry.posting_date = today()
        payment_entry.mode_of_payment = payment_data.get("payment_method", "Online Payment")

        # Link to outstanding invoices
        outstanding_invoices = get_outstanding_invoices(member_name)
        for invoice in outstanding_invoices:
            if payment_entry.paid_amount <= 0:
                break

            allocated_amount = min(payment_entry.paid_amount, invoice.outstanding_amount)

            payment_entry.append("references", {
                "reference_doctype": "Sales Invoice",
                "reference_name": invoice.name,
                "allocated_amount": allocated_amount
            })

            payment_entry.paid_amount -= allocated_amount

        payment_entry.insert()
        payment_entry.submit()

        # Update member payment history
        update_member_payment_history(member_name, payment_entry)

        # Send confirmation email
        send_payment_confirmation_email(member_name, payment_entry, payment_data)

        return payment_entry

@frappe.whitelist(allow_guest=True)
def create_payment_session(member_email, amount=None):
    """
    Public API endpoint for creating payment sessions
    Used by member portal "Pay Now" button
    """
    # Validate member
    member = frappe.db.get_value("Member", {"email": member_email}, "name")
    if not member:
        frappe.throw("Member not found")

    # Calculate amount if not provided
    if not amount:
        outstanding = get_total_outstanding(member)
        if outstanding <= 0:
            frappe.throw("No outstanding balance")
        amount = outstanding

    # Create payment session
    gateway_integration = PaymentGatewayIntegration()
    payment_session = gateway_integration.create_payment_intent(member, amount)

    return payment_session

@frappe.whitelist(allow_guest=True, methods=["POST"])
def payment_webhook_handler(gateway):
    """
    Handle payment gateway webhooks
    Called by payment providers on payment events
    """
    payload = frappe.request.data

    gateway_integration = PaymentGatewayIntegration()
    result = gateway_integration.handle_payment_webhook(gateway, payload)

    return {"status": "success", "processed": result}
```

### 6.5 Communication Integration

```python
def setup_communication_templates():
    """
    Create all required email templates
    """

    templates = [
        {
            "name": "Membership Dues - Upcoming Reminder",
            "subject": "Your membership dues will be due soon",
            "use_html": 1,
            "response_html": """
                <p>Dear {{ first_name }},</p>

                <p>This is a friendly reminder that your annual membership dues
                of €{{ amount }} will be due on {{ due_date }}.</p>

                <p>You can pay online through your member portal or set up
                automatic payments to avoid future reminders.</p>

                <p><a href="{{ portal_link }}" class="btn btn-primary">
                View Account</a></p>

                <p>Thank you for your continued support!</p>
            """
        },
        {
            "name": "Membership Dues - Payment Plan Confirmation",
            "subject": "Your payment plan has been approved",
            "use_html": 1,
            "response_html": """
                <p>Dear {{ first_name }},</p>

                <p>We've set up your payment plan as requested. Here are the details:</p>

                <ul>
                    <li>Total Amount: €{{ total_amount }}</li>
                    <li>Number of Installments: {{ installments }}</li>
                    <li>Amount per Installment: €{{ installment_amount }}</li>
                    <li>First Payment Due: {{ first_payment_date }}</li>
                </ul>

                <p>You'll receive an invoice before each installment is due.</p>

                <p>Thank you for working with us to keep your membership active.</p>
            """
        }
    ]

    for template_data in templates:
        if not frappe.db.exists("Email Template", template_data["name"]):
            template = frappe.new_doc("Email Template")
            template.update(template_data)
            template.insert()
```

---

## 7. Migration Strategy

### 7.1 Pre-Migration Analysis

```python
def analyze_migration_readiness():
    """
    Comprehensive analysis before migration
    """

    analysis = {
        "timestamp": now_datetime(),
        "statistics": {},
        "issues": [],
        "recommendations": []
    }

    # 1. Count active subscriptions
    active_subs = frappe.db.count("Subscription", {"status": "Active"})
    analysis["statistics"]["active_subscriptions"] = active_subs

    # 2. Find problematic subscriptions
    problematic = frappe.db.sql("""
        SELECT name, party, status, current_invoice_start
        FROM `tabSubscription`
        WHERE status = 'Active'
        AND (
            current_invoice_start > CURDATE()
            OR current_invoice_start < DATE_SUB(CURDATE(), INTERVAL 2 YEAR)
            OR party NOT IN (SELECT name FROM `tabMember`)
        )
    """, as_dict=True)

    if problematic:
        analysis["issues"].append({
            "type": "problematic_subscriptions",
            "count": len(problematic),
            "details": problematic
        })

    # 3. Check data integrity
    orphaned_subs = frappe.db.sql("""
        SELECT s.name, s.party
        FROM `tabSubscription` s
        LEFT JOIN `tabMembership` m ON m.member = s.party
        WHERE s.status = 'Active'
        AND m.name IS NULL
    """, as_dict=True)

    if orphaned_subs:
        analysis["issues"].append({
            "type": "orphaned_subscriptions",
            "count": len(orphaned_subs),
            "details": orphaned_subs
        })

    # 4. Payment method analysis
    payment_methods = frappe.db.sql("""
        SELECT
            COUNT(*) as count,
            CASE
                WHEN sm.name IS NOT NULL THEN 'SEPA'
                ELSE 'Manual'
            END as method
        FROM `tabMember` m
        LEFT JOIN `tabSEPA Mandate` sm ON sm.party = m.name AND sm.status = 'Active'
        WHERE m.status = 'Active'
        GROUP BY method
    """, as_dict=True)

    analysis["statistics"]["payment_methods"] = payment_methods

    # 5. Generate recommendations
    if active_subs > 1000:
        analysis["recommendations"].append(
            "Consider phased migration due to large number of subscriptions"
        )

    if len(analysis["issues"]) > 0:
        analysis["recommendations"].append(
            "Resolve data issues before migration"
        )

    return analysis
```

### 7.2 Migration Execution

```python
def migrate_subscriptions_to_dues_schedules(test_mode=True, limit=None):
    """
    Main migration function with safety controls
    """

    migration_log = {
        "start_time": now_datetime(),
        "test_mode": test_mode,
        "processed": 0,
        "success": 0,
        "errors": [],
        "mappings": []
    }

    # Get subscriptions to migrate
    filters = {"status": "Active", "docstatus": 1}
    if limit:
        subscriptions = frappe.get_all("Subscription",
            filters=filters,
            limit=limit,
            order_by="creation")
    else:
        subscriptions = frappe.get_all("Subscription", filters=filters)

    for sub_data in subscriptions:
        try:
            result = migrate_single_subscription_safe(
                sub_data.name,
                test_mode=test_mode
            )

            migration_log["processed"] += 1

            if result["success"]:
                migration_log["success"] += 1
                migration_log["mappings"].append({
                    "subscription": sub_data.name,
                    "dues_schedule": result.get("schedule_name"),
                    "member": result.get("member")
                })
            else:
                migration_log["errors"].append({
                    "subscription": sub_data.name,
                    "error": result.get("error")
                })

        except Exception as e:
            migration_log["errors"].append({
                "subscription": sub_data.name,
                "error": str(e),
                "traceback": frappe.get_traceback()
            })

    migration_log["end_time"] = now_datetime()
    migration_log["duration"] = (
        migration_log["end_time"] - migration_log["start_time"]
    ).total_seconds()

    # Save migration log
    if not test_mode:
        save_migration_log(migration_log)

    return migration_log

def migrate_single_subscription_safe(subscription_name, test_mode=True):
    """
    Safely migrate a single subscription with validation
    """

    try:
        sub = frappe.get_doc("Subscription", subscription_name)

        # Validate subscription
        validation = validate_subscription_for_migration(sub)
        if not validation["valid"]:
            return {
                "success": False,
                "error": validation["reason"]
            }

        # Find associated membership
        membership = find_membership_for_subscription(sub)
        if not membership:
            return {
                "success": False,
                "error": "No associated membership found"
            }

        # Calculate migration parameters
        params = calculate_migration_parameters(sub, membership)

        if test_mode:
            return {
                "success": True,
                "test_mode": True,
                "would_create": params
            }

        # Create dues schedule
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.update(params)
        schedule.insert()

        # Link old subscription
        sub.add_comment("Info",
            f"Migrated to Dues Schedule: {schedule.name}")

        # Cancel subscription (optional - can run parallel first)
        # sub.cancel()

        return {
            "success": True,
            "schedule_name": schedule.name,
            "member": schedule.member
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
```

### 7.3 Post-Migration Validation

```python
def validate_migration_completeness():
    """
    Ensure migration was successful
    """

    validation_report = {
        "timestamp": now_datetime(),
        "checks": [],
        "issues": [],
        "summary": "PASS"
    }

    # Check 1: All active members have dues schedules
    members_without_schedules = frappe.db.sql("""
        SELECT m.name, m.full_name
        FROM `tabMember` m
        LEFT JOIN `tabMembership Dues Schedule` mds ON mds.member = m.name
        WHERE m.status = 'Active'
        AND mds.name IS NULL
    """, as_dict=True)

    validation_report["checks"].append({
        "name": "Members with dues schedules",
        "result": len(members_without_schedules) == 0,
        "details": f"{len(members_without_schedules)} members without schedules"
    })

    # Check 2: No duplicate schedules
    duplicate_schedules = frappe.db.sql("""
        SELECT member, COUNT(*) as count
        FROM `tabMembership Dues Schedule`
        WHERE status = 'Active'
        GROUP BY member
        HAVING count > 1
    """, as_dict=True)

    validation_report["checks"].append({
        "name": "No duplicate schedules",
        "result": len(duplicate_schedules) == 0,
        "details": f"{len(duplicate_schedules)} members with duplicates"
    })

    # Check 3: Invoice generation working
    recent_invoices = frappe.db.count("Sales Invoice", {
        "creation": [">", add_days(now_datetime(), -1)],
        "remarks": ["like", "%Dues Schedule%"]
    })

    validation_report["checks"].append({
        "name": "Invoice generation active",
        "result": recent_invoices > 0,
        "details": f"{recent_invoices} invoices in last 24 hours"
    })

    # Determine overall status
    if any(not check["result"] for check in validation_report["checks"]):
        validation_report["summary"] = "FAIL"

    return validation_report
```

---

## 8. Operational Procedures

### 8.1 Daily Operations Checklist

```markdown
# Daily Dues Management Checklist

## Morning (9 AM)
- [ ] Review overnight invoice generation report
- [ ] Check for failed invoice generations
- [ ] Review critical overdue accounts (>60 days)
- [ ] Process any pending payment plan requests

## Afternoon (2 PM)
- [ ] Review payment notifications queue
- [ ] Handle member inquiries about dues
- [ ] Process manual adjustments/corrections
- [ ] Update payment plans as needed

## End of Day (5 PM)
- [ ] Verify tomorrow's invoice generation queue
- [ ] Review suspension candidates
- [ ] Check system health dashboard
- [ ] Note any issues for next day
```

### 8.2 Month-End Procedures

```python
def month_end_dues_reconciliation():
    """
    Monthly reconciliation and reporting
    """

    report_date = today()
    report_month = report_date.replace(day=1)

    report = {
        "month": report_month.strftime("%B %Y"),
        "invoices_generated": 0,
        "amount_invoiced": 0,
        "amount_collected": 0,
        "collection_rate": 0,
        "aging_analysis": {},
        "payment_plans": {
            "created": 0,
            "completed": 0,
            "defaulted": 0
        }
    }

    # Calculate metrics
    report["invoices_generated"] = frappe.db.count("Sales Invoice", {
        "posting_date": ["between", [report_month, report_date]],
        "remarks": ["like", "%Dues Schedule%"]
    })

    # ... (additional calculations)

    # Generate PDF report
    return generate_month_end_report(report)
```

### 8.3 Exception Handling Procedures

```markdown
# Exception Handling Guide

## Member Claims Non-Receipt of Invoice
1. Check Email Queue for delivery status
2. Verify email address on file
3. Check spam folder instructions
4. Resend invoice with delivery confirmation
5. Update communication preferences if needed

## Payment Plan Default
1. Check if payment was attempted
2. Review bank rejection reasons
3. Contact member within 48 hours
4. Offer modified plan or alternatives
5. Document all communications

## System Errors
1. Check error logs for details
2. Verify schedule configuration
3. Run manual invoice generation if needed
4. Notify IT if systematic issue
5. Update affected members on resolution

## Disputed Charges
1. Review membership history
2. Verify invoice accuracy
3. Check for system errors
4. Involve supervisor if needed
5. Document resolution
```

---

## Summary

This comprehensive plan provides:

1. **Clean Architecture**: Separates membership from billing cleanly
2. **Robust Operations**: Handles all edge cases and exceptions
3. **Member-Friendly**: Multiple payment options and clear communication
4. **Staff-Efficient**: Automation with human oversight where needed
5. **Migration-Safe**: Careful transition from existing system
6. **Future-Proof**: Extensible for new requirements

The system respects the reality that association memberships are relationships, not subscriptions, while leveraging ERPNext's strengths in accounting and document management.

## 10. Data Retention and Archiving Policies

### 10.1 Data Lifecycle Management

```python
class DuesDataRetentionManager:
    """
    Comprehensive data retention and archiving for dues system
    """

    def __init__(self):
        self.retention_policies = {
            "active_member_data": {"years": None},  # Keep indefinitely while active
            "terminated_member_financial": {"years": 7},  # Legal requirement
            "payment_history": {"years": 7},  # Tax and audit requirements
            "dues_schedules_cancelled": {"years": 5},  # Historical reference
            "notification_logs": {"years": 2},  # Communication history
            "audit_trails": {"years": 10},  # Compliance and investigation
            "refund_records": {"years": 7},  # Financial audit requirements
            "payment_plan_history": {"years": 5},  # Member service history
            "invoice_data": {"years": 7},  # Legal requirement
            "webhook_logs": {"years": 1},  # Technical debugging only
        }

    def archive_terminated_member_data(self, member_name, termination_date):
        """
        Archive data for terminated members based on retention policies
        """
        termination_date = getdate(termination_date)
        retention_deadline = add_years(termination_date, 7)

        if getdate() < retention_deadline:
            # Still within retention period
            return self.soft_archive_member_data(member_name, termination_date)
        else:
            # Beyond retention period - can be purged
            return self.hard_archive_member_data(member_name, termination_date)

    def soft_archive_member_data(self, member_name, termination_date):
        """
        Soft archive: Mark as archived but keep data accessible
        """
        archive_log = {
            "member": member_name,
            "archive_date": today(),
            "termination_date": termination_date,
            "archive_type": "soft",
            "data_preserved": []
        }

        # Mark dues schedules as archived
        dues_schedules = frappe.get_all("Membership Dues Schedule",
            filters={"member": member_name})

        for schedule in dues_schedules:
            schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule.name)
            schedule_doc.archived = 1
            schedule_doc.archive_date = today()
            schedule_doc.archive_reason = "Member termination - soft archive"
            schedule_doc.save()
            archive_log["data_preserved"].append(f"Dues Schedule: {schedule.name}")

        # Archive payment history (keep but mark)
        payment_entries = frappe.get_all("Payment Entry",
            filters={"party": member_name, "party_type": "Customer"})

        for payment in payment_entries:
            payment_doc = frappe.get_doc("Payment Entry", payment.name)
            payment_doc.archived = 1
            payment_doc.archive_date = today()
            payment_doc.save()
            archive_log["data_preserved"].append(f"Payment: {payment.name}")

        # Create archive record
        archive_record = frappe.new_doc("Member Data Archive")
        archive_record.update(archive_log)
        archive_record.insert()

        return archive_record

    def hard_archive_member_data(self, member_name, termination_date):
        """
        Hard archive: Move data to archive tables and remove from active system
        """
        # First create comprehensive export
        export_data = self.export_member_financial_data(member_name)

        # Store in archive table
        archive_record = frappe.new_doc("Member Financial Archive")
        archive_record.member_name = member_name
        archive_record.termination_date = termination_date
        archive_record.archive_date = today()
        archive_record.archive_type = "hard"
        archive_record.data_export = json.dumps(export_data)
        archive_record.insert()

        # Remove from active tables (after export confirmed)
        self.purge_member_active_data(member_name, preserve_legal_minimum=True)

        return archive_record

    def export_member_financial_data(self, member_name):
        """
        Create comprehensive export of member financial data
        """
        export_data = {
            "member": member_name,
            "export_date": today(),
            "dues_schedules": [],
            "invoices": [],
            "payments": [],
            "refunds": [],
            "payment_plans": [],
            "audit_trail": []
        }

        # Export dues schedules
        schedules = frappe.get_all("Membership Dues Schedule",
            filters={"member": member_name},
            fields=["*"])
        export_data["dues_schedules"] = schedules

        # Export invoices
        invoices = frappe.get_all("Sales Invoice",
            filters={"customer": member_name},
            fields=["*"])
        export_data["invoices"] = invoices

        # Export payment entries
        payments = frappe.get_all("Payment Entry",
            filters={"party": member_name, "party_type": "Customer"},
            fields=["*"])
        export_data["payments"] = payments

        # Export payment plans
        payment_plans = frappe.get_all("Member Payment Plan",
            filters={"member": member_name},
            fields=["*"])
        export_data["payment_plans"] = payment_plans

        return export_data

def cleanup_old_notification_logs():
    """
    Scheduled job to clean up old notification logs
    Run monthly
    """
    cutoff_date = add_years(today(), -2)

    old_logs = frappe.get_all("Email Queue",
        filters={"creation": ["<", cutoff_date]},
        fields=["name"])

    for log in old_logs:
        frappe.delete_doc("Email Queue", log.name, ignore_permissions=True)

    return f"Cleaned up {len(old_logs)} old notification logs"

def cleanup_old_webhook_logs():
    """
    Scheduled job to clean up old webhook logs
    Run weekly
    """
    cutoff_date = add_years(today(), -1)

    # Clean up old payment gateway logs
    old_webhooks = frappe.get_all("Payment Gateway Log",
        filters={"creation": ["<", cutoff_date]},
        fields=["name"])

    for webhook in old_webhooks:
        frappe.delete_doc("Payment Gateway Log", webhook.name, ignore_permissions=True)

    return f"Cleaned up {len(old_webhooks)} old webhook logs"
```

### 10.2 Legal Compliance and GDPR

```python
def handle_gdpr_data_request(member_name, request_type):
    """
    Handle GDPR data requests for member financial data
    """
    if request_type == "export":
        return export_gdpr_financial_data(member_name)
    elif request_type == "delete":
        return process_gdpr_deletion_request(member_name)
    elif request_type == "rectification":
        return generate_gdpr_rectification_form(member_name)

def export_gdpr_financial_data(member_name):
    """
    Export all financial data for GDPR compliance
    """
    retention_manager = DuesDataRetentionManager()
    financial_data = retention_manager.export_member_financial_data(member_name)

    # Add GDPR-specific metadata
    gdpr_export = {
        "gdpr_request_date": today(),
        "member_name": member_name,
        "data_controller": "Verenigingen Organization",
        "financial_data": financial_data,
        "retention_policy": retention_manager.retention_policies,
        "legal_basis": "Membership contract and legitimate business interest"
    }

    return gdpr_export

def process_gdpr_deletion_request(member_name):
    """
    Process right to be forgotten request (with legal constraints)
    """
    # Check if member has legal retention requirements
    member = frappe.get_doc("Member", member_name)

    if member.status == "Active":
        return {
            "status": "denied",
            "reason": "Cannot delete data for active member"
        }

    # Check retention requirements
    termination_date = member.termination_date
    if termination_date and getdate() < add_years(getdate(termination_date), 7):
        return {
            "status": "partial",
            "reason": "Financial data must be retained for 7 years per legal requirements",
            "actions_taken": "Personal data anonymized, financial data retained"
        }

    # Can proceed with full deletion
    retention_manager = DuesDataRetentionManager()
    result = retention_manager.hard_archive_member_data(member_name, termination_date)

    return {
        "status": "completed",
        "archive_record": result.name,
        "deletion_date": today()
    }
```

## 11. Deceased Member Handling

### 11.1 Deceased Member Detection and Processing

```python
class DeceasedMemberProcessor:
    """
    Handle deceased member detection and appropriate actions
    """

    def mark_member_deceased(self, member_name, date_of_death, source="Manual"):
        """
        Mark member as deceased and trigger appropriate workflows
        """
        member = frappe.get_doc("Member", member_name)

        # Validate date of death
        date_of_death = getdate(date_of_death)
        if date_of_death > today():
            frappe.throw("Date of death cannot be in the future")

        if member.birth_date and date_of_death < getdate(member.birth_date):
            frappe.throw("Date of death cannot be before birth date")

        # Update member record
        member.status = "Deceased"
        member.date_of_death = date_of_death
        member.deceased_notification_source = source
        member.deceased_processed_date = today()

        # Add to modification history
        member.append("status_history", {
            "date": today(),
            "previous_status": member.status,
            "new_status": "Deceased",
            "reason": f"Member deceased on {date_of_death}",
            "source": source
        })

        member.save()

        # Trigger deceased member workflow
        self.process_deceased_member_workflow(member_name, date_of_death)

        return member

    def process_deceased_member_workflow(self, member_name, date_of_death):
        """
        Execute complete deceased member workflow
        """
        workflow_log = {
            "member": member_name,
            "date_of_death": date_of_death,
            "processing_date": today(),
            "actions_taken": []
        }

        # 1. Cancel all active dues schedules
        self.cancel_dues_schedules(member_name, date_of_death, workflow_log)

        # 2. Handle outstanding invoices
        self.handle_outstanding_invoices(member_name, date_of_death, workflow_log)

        # 3. Cancel SEPA mandates
        self.cancel_sepa_mandates(member_name, workflow_log)

        # 4. Cancel volunteer assignments
        self.handle_volunteer_assignments(member_name, workflow_log)

        # 5. Notify relevant staff
        self.notify_staff_deceased_member(member_name, workflow_log)

        # 6. Archive communications
        self.archive_member_communications(member_name, workflow_log)

        # Create workflow record
        workflow_record = frappe.new_doc("Deceased Member Workflow")
        workflow_record.update(workflow_log)
        workflow_record.insert()

        return workflow_record

    def cancel_dues_schedules(self, member_name, date_of_death, workflow_log):
        """
        Cancel all active dues schedules for deceased member
        """
        active_schedules = frappe.get_all("Membership Dues Schedule",
            filters={"member": member_name, "status": "Active"})

        for schedule in active_schedules:
            schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule.name)
            schedule_doc.status = "Cancelled"
            schedule_doc.cancellation_date = today()
            schedule_doc.cancellation_reason = f"Member deceased on {date_of_death}"
            schedule_doc.auto_generate = 0  # Stop automatic invoice generation

            # Add to modification history
            schedule_doc.append("modification_history", {
                "date": now_datetime(),
                "user": frappe.session.user,
                "change_type": "Cancelled - Deceased",
                "old_value": "Active",
                "new_value": "Cancelled",
                "reason": f"Member deceased on {date_of_death}"
            })

            schedule_doc.save()
            workflow_log["actions_taken"].append(f"Cancelled dues schedule: {schedule.name}")

def is_member_deceased(member_name):
    """
    Check if member is marked as deceased
    Used in scheduled jobs to prevent actions
    """
    member_status = frappe.db.get_value("Member", member_name, "status")
    return member_status == "Deceased"
```

## 12. Enhanced Testing Framework

### 12.1 Updated EnhancedTestCase for Dues System

```python
# Addition to verenigingen/tests/fixtures/enhanced_test_factory.py

class EnhancedDuesTestFactory(EnhancedTestDataFactory):
    """
    Extended test factory specifically for dues system testing
    """

    def __init__(self, seed: int = 12345, use_faker: bool = True):
        super().__init__(seed, use_faker)
        self.dues_scenarios = {
            "standard": {"amount": 50.0, "frequency": "Annual"},
            "student": {"amount": 25.0, "frequency": "Annual"},
            "hardship": {"amount": 15.0, "frequency": "Annual"},
            "supporter": {"amount": 100.0, "frequency": "Annual"},
            "patron": {"amount": 250.0, "frequency": "Annual"},
            "monthly": {"amount": 5.0, "frequency": "Monthly"},
            "quarterly": {"amount": 15.0, "frequency": "Quarterly"}
        }

def create_comprehensive_test_data(num_members: int = 500):
    """
    Create comprehensive test dataset with varied dues scenarios
    """
    factory = EnhancedDuesTestFactory(seed=42, use_faker=True)

    # Create membership types
    membership_types = []
    for type_name in ["Standard", "Student", "Senior", "International"]:
        mt = factory.create_membership_type_with_tiers(
            f"Test {type_name} Membership",
            minimum_annual_fee=20.0 if type_name == "Student" else 30.0,
            standard_annual_fee=40.0 if type_name == "Student" else 60.0
        )
        membership_types.append(mt)

    # Create members with varied scenarios
    created_members = []
    scenarios = ["standard", "student", "hardship", "supporter", "patron", "monthly", "quarterly"]

    for i in range(num_members):
        # Vary member characteristics
        age_days = random.randint(6570, 25550)  # 18-70 years
        birth_date = add_days(today(), -age_days)

        # Select scenario based on member characteristics
        if age_days < 9125:  # Under 25 - more likely student
            scenario = random.choices(
                ["student", "hardship", "standard"],
                weights=[0.6, 0.2, 0.2]
            )[0]
        elif age_days > 20075:  # Over 55 - more likely supporter
            scenario = random.choices(
                ["standard", "supporter", "patron"],
                weights=[0.5, 0.3, 0.2]
            )[0]
        else:  # Middle age - varied
            scenario = random.choice(scenarios)

        # Create member
        member = factory.create_member(
            first_name=f"Test{i+1:03d}",
            last_name=f"Member",
            birth_date=birth_date,
            email=f"test{i+1:03d}@example.com"
        )

        # Create dues schedule
        schedule = factory.create_dues_schedule(member.name, scenario)

        created_members.append({
            "member": member,
            "schedule": schedule,
            "scenario": scenario
        })

    return {
        "members": created_members,
        "membership_types": membership_types,
        "total_created": num_members,
        "scenarios_used": scenarios
    }

class DuesSystemTestCase(EnhancedTestCase):
    """
    Enhanced test case specifically for dues system testing
    """

    def setUp(self):
        super().setUp()
        self.dues_factory = EnhancedDuesTestFactory(seed=12345, use_faker=True)

    def create_test_member_with_dues(self, scenario="standard", **member_kwargs):
        """Create member with dues schedule in one call"""
        member = self.dues_factory.create_member(**member_kwargs)
        schedule = self.dues_factory.create_dues_schedule(member.name, scenario)

        return {
            "member": member,
            "schedule": schedule,
            "membership": self.dues_factory.get_or_create_membership(member.name)
        }

    def assertDuesScheduleValid(self, schedule):
        """Assert dues schedule meets business rules"""
        self.assertIsNotNone(schedule.member)
        self.assertIsNotNone(schedule.amount)
        self.assertGreater(schedule.amount, 0)
        self.assertIn(schedule.billing_frequency,
                     ["Annual", "Semi-Annual", "Quarterly", "Monthly", "Custom"])
```

## 13. Internationalization and Localization

### 13.1 Multi-Language Support

```python
def get_localized_dues_templates(language="en"):
    """
    Get localized email templates for dues notifications
    """
    templates = {
        "en": {
            "upcoming_dues": {
                "subject": "Your membership dues will be due soon",
                "greeting": "Dear {first_name}",
                "body": "Your annual membership dues of €{amount} will be due on {due_date}."
            },
            "payment_confirmation": {
                "subject": "Payment confirmation - Thank you",
                "greeting": "Dear {first_name}",
                "body": "We have received your payment of €{amount}. Thank you for your continued support!"
            }
        },
        "nl": {
            "upcoming_dues": {
                "subject": "Uw lidmaatschapsbijdrage vervalt binnenkort",
                "greeting": "Beste {first_name}",
                "body": "Uw jaarlijkse lidmaatschapsbijdrage van €{amount} vervalt op {due_date}."
            },
            "payment_confirmation": {
                "subject": "Betalingsbevestiging - Dank u wel",
                "greeting": "Beste {first_name}",
                "body": "Wij hebben uw betaling van €{amount} ontvangen. Dank u voor uw voortdurende steun!"
            }
        }
    }

    return templates.get(language, templates["en"])

def get_localized_currency_format(amount, country="NL"):
    """
    Format currency amounts based on locale
    """
    currency_formats = {
        "NL": {"symbol": "€", "position": "before", "separator": ",", "thousands": "."},
        "DE": {"symbol": "€", "position": "after", "separator": ",", "thousands": "."},
        "FR": {"symbol": "€", "position": "after", "separator": ",", "thousands": " "},
        "US": {"symbol": "$", "position": "before", "separator": ".", "thousands": ","}
    }

    fmt = currency_formats.get(country, currency_formats["NL"])

    if fmt["position"] == "before":
        return f"{fmt['symbol']}{amount:,.2f}".replace(",", fmt["thousands"]).replace(".", fmt["separator"])
    else:
        return f"{amount:,.2f}{fmt['symbol']}".replace(",", fmt["thousands"]).replace(".", fmt["separator"])
```

---

## 9. Access Control & Permissions

### 9.1 Role-Based Financial Access

The system implements comprehensive role-based access control for financial information, ensuring appropriate visibility while maintaining member privacy.

#### Hierarchical Access Structure

```
┌─────────────────────────────────────────────────────────────┐
│                    System Manager                            │
│              (Full access to all financial data)             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────┐
│              Verenigingen Manager/Administrator              │
│              (Full access to all financial data)             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────┐
│                   National Board Members                     │
│            (Access to all members' financial data)           │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────┐
│              Chapter Board Members (Finance)                 │
│        (Access to their chapter members' data only)          │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────┐
│              Chapter Board Members (Non-Finance)             │
│          (Limited/summary access to chapter data)            │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────┐
│                    Regular Members                           │
│              (Access to own financial data only)             │
└─────────────────────────────────────────────────────────────┘
```

### 9.2 Permission Implementation

#### Core Permission Model

```python
def get_financial_access_level(user, member_name=None):
    """
    Determine user's access level for financial data
    Returns: 'full', 'chapter', 'limited', 'own', 'none'
    """

    # System-wide access roles
    admin_roles = [
        "System Manager",
        "Verenigingen Administrator",
        "Verenigingen Manager"
    ]

    if any(role in frappe.get_roles(user) for role in admin_roles):
        return 'full'

    # Get user's member record
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not user_member:
        return 'none'

    # Check national board membership
    if is_national_board_member(user_member):
        return 'full'

    # Check chapter board membership
    board_access = get_chapter_board_access(user_member)

    if board_access.get('has_finance_access'):
        # Can see financial data for their chapters
        return 'chapter'
    elif board_access.get('is_board_member'):
        # Board member without finance access - limited view
        return 'limited'
    elif member_name and member_name == user_member:
        # Member viewing own data
        return 'own'
    else:
        return 'none'

def get_chapter_board_access(member_name):
    """
    Get chapter board access details for a member
    """
    access_info = {
        'is_board_member': False,
        'has_finance_access': False,
        'chapters': [],
        'permissions_level': None
    }

    # Get volunteer record
    volunteer = frappe.db.get_value(
        "Volunteer",
        {"member": member_name},
        "name"
    )

    if not volunteer:
        return access_info

    # Get active board positions
    board_positions = frappe.get_all(
        "Chapter Board Member",
        filters={
            "volunteer": volunteer,
            "is_active": 1
        },
        fields=["parent", "chapter_role"]
    )

    for position in board_positions:
        access_info['is_board_member'] = True
        access_info['chapters'].append(position.parent)

        # Check role permissions
        role_doc = frappe.get_doc("Chapter Role", position.chapter_role)

        if role_doc.permissions_level in ["Admin", "Finance"]:
            access_info['has_finance_access'] = True
            access_info['permissions_level'] = role_doc.permissions_level

    return access_info

def is_national_board_member(member_name):
    """
    Check if member is on national board with appropriate access
    """
    settings = frappe.get_single("Verenigingen Settings")

    if not hasattr(settings, "national_chapter") or not settings.national_chapter:
        return False

    volunteer = frappe.db.get_value(
        "Volunteer",
        {"member": member_name},
        "name"
    )

    if not volunteer:
        return False

    # Check for national board position with appropriate permissions
    national_positions = frappe.get_all(
        "Chapter Board Member",
        filters={
            "parent": settings.national_chapter,
            "volunteer": volunteer,
            "is_active": 1
        },
        fields=["chapter_role"]
    )

    for position in national_positions:
        role_doc = frappe.get_doc("Chapter Role", position.chapter_role)
        if role_doc.permissions_level in ["Admin", "Finance", "Membership"]:
            return True

    return False
```

### 9.3 Financial Data Views by Role

#### Full Access View (Admin/National Board)

```python
@frappe.whitelist()
def get_member_financial_details_admin(member_name):
    """
    Complete financial view for administrators
    """
    access_level = get_financial_access_level(frappe.session.user)

    if access_level != 'full':
        frappe.throw(_("Insufficient permissions"))

    return {
        # Complete financial history
        "payment_history": get_complete_payment_history(member_name),

        # All dues schedules (including paused/cancelled)
        "dues_schedules": get_all_dues_schedules(member_name),

        # Outstanding amounts with aging
        "outstanding_analysis": get_detailed_outstanding_analysis(member_name),

        # Payment methods and mandates
        "payment_methods": get_all_payment_methods(member_name),

        # Communication history
        "reminder_history": get_reminder_history(member_name),

        # Special arrangements
        "payment_plans": get_payment_plan_history(member_name),
        "exemptions": get_exemption_history(member_name),

        # Actions available
        "available_actions": [
            "create_payment_plan",
            "adjust_dues_amount",
            "grant_exemption",
            "write_off_debt",
            "suspend_membership",
            "send_custom_reminder"
        ]
    }
```

#### Chapter Board View (Finance Access)

```python
@frappe.whitelist()
def get_member_financial_details_chapter(member_name):
    """
    Financial view for chapter board members with finance access
    """
    access_info = get_chapter_board_access(get_current_member())

    if not access_info.get('has_finance_access'):
        frappe.throw(_("Insufficient permissions"))

    # Verify member belongs to accessible chapter
    member_chapters = get_member_chapters(member_name)
    if not any(ch in access_info['chapters'] for ch in member_chapters):
        frappe.throw(_("Member not in your chapter"))

    return {
        # Current status and recent history
        "payment_status": get_payment_status_summary(member_name),
        "recent_payments": get_recent_payments(member_name, months=6),

        # Active dues schedule only
        "active_schedule": get_active_dues_schedule(member_name),

        # Outstanding summary (not detailed aging)
        "outstanding_amount": get_total_outstanding(member_name),

        # Active payment plans
        "active_payment_plan": get_active_payment_plan(member_name),

        # Limited actions
        "available_actions": [
            "send_reminder",
            "view_payment_history",
            "recommend_payment_plan",
            "add_note"
        ]
    }
```

#### Chapter Board View (Non-Finance)

```python
@frappe.whitelist()
def get_member_financial_summary_chapter(member_name):
    """
    Limited financial view for chapter board members without finance access
    """
    access_info = get_chapter_board_access(get_current_member())

    if not access_info.get('is_board_member'):
        frappe.throw(_("Insufficient permissions"))

    # Verify member belongs to accessible chapter
    member_chapters = get_member_chapters(member_name)
    if not any(ch in access_info['chapters'] for ch in member_chapters):
        frappe.throw(_("Member not in your chapter"))

    return {
        # High-level status only
        "membership_status": get_membership_status(member_name),
        "payment_status_category": get_payment_status_category(member_name),

        # Aggregated statistics (no amounts)
        "payments_this_year": count_payments_this_year(member_name),
        "is_current": is_member_current(member_name),

        # No financial amounts or details
        "available_actions": [
            "view_member_profile",
            "send_message"
        ]
    }
```

#### Member Self-Service View

```python
@frappe.whitelist()
def get_my_financial_details():
    """
    Member viewing their own financial information
    """
    member = get_current_member()

    if not member:
        frappe.throw(_("Member record not found"))

    return {
        # Complete own payment history
        "payment_history": get_complete_payment_history(member.name),

        # Own dues schedule
        "dues_schedule": get_active_dues_schedule(member.name),

        # Outstanding with payment options
        "outstanding_amount": get_total_outstanding(member.name),
        "payment_options": get_available_payment_options(member.name),

        # Own payment plans
        "payment_plans": get_payment_plan_history(member.name),

        # Self-service actions
        "available_actions": [
            "make_payment",
            "request_payment_plan",
            "update_payment_method",
            "download_invoices",
            "contact_support"
        ]
    }
```

### 9.4 Report Access Control

#### Enhanced Report Permissions

```python
def get_report_query_conditions(report_name, user):
    """
    Generate SQL WHERE conditions based on user permissions
    Apply filtering at database level for performance
    """
    access_level = get_financial_access_level(user)

    if report_name == "Overdue Member Payments":
        if access_level == 'full':
            # No filtering needed
            return ""

        elif access_level == 'chapter':
            # Get accessible chapters
            access_info = get_chapter_board_access(get_current_member())
            if not access_info['chapters']:
                return " AND 1=0"  # No access

            chapter_list = "', '".join(access_info['chapters'])
            return f"""
                AND si.customer IN (
                    SELECT DISTINCT m.name
                    FROM `tabMember` m
                    INNER JOIN `tabChapter Member` cm ON cm.member = m.name
                    WHERE cm.parent IN ('{chapter_list}')
                    AND cm.parenttype = 'Chapter'
                )
            """

        elif access_level == 'limited':
            # Limited access - same chapter filter but will remove amounts in formatter
            access_info = get_chapter_board_access(get_current_member())
            if not access_info['chapters']:
                return " AND 1=0"  # No access

            chapter_list = "', '".join(access_info['chapters'])
            return f"""
                AND si.customer IN (
                    SELECT DISTINCT m.name
                    FROM `tabMember` m
                    INNER JOIN `tabChapter Member` cm ON cm.member = m.name
                    WHERE cm.parent IN ('{chapter_list}')
                    AND cm.parenttype = 'Chapter'
                )
            """
        else:
            # No access
            return " AND 1=0"

    return ""

def apply_report_permissions(report_name, data, user):
    """
    Post-process report data for permissions (now only used for amount masking)
    Main filtering moved to database level for performance
    """
    access_level = get_financial_access_level(user)

    if report_name == "Overdue Member Payments":
        if access_level == 'full' or access_level == 'chapter':
            # Data already filtered at query level, no post-processing needed
            return data

        elif access_level == 'limited':
            # Remove financial amounts for limited access
            filtered_data = []

            for row in data:
                summary_row = {
                    'member_name': row['member_name'],
                    'member_full_name': row['member_full_name'],
                    'chapter': row['chapter'],
                    'status_indicator': row['status_indicator'],
                    'days_overdue': row['days_overdue']
                    # Exclude financial amounts
                }
                filtered_data.append(summary_row)

            return filtered_data

        elif access_level == 'limited':
            # Summary data only - remove amounts
            filtered_data = []

            for row in data:
                summary_row = {
                    'member_name': row['member_name'],
                    'member_full_name': row['member_full_name'],
                    'chapter': row['chapter'],
                    'status_indicator': row['status_indicator'],
                    'days_overdue': row['days_overdue']
                    # Exclude financial amounts
                }
                filtered_data.append(summary_row)

            return filtered_data
        else:
            # No access
            return []
```

#### Report Column Visibility

```javascript
// Dynamic column visibility based on permissions
frappe.query_reports["Overdue Member Payments"] = {
    onload: function(report) {
        frappe.call({
            method: 'verenigingen.api.get_user_financial_access_level',
            callback: function(r) {
                const access_level = r.message;

                // Hide financial columns for limited access
                if (access_level === 'limited') {
                    report.columns = report.columns.filter(col =>
                        !['total_overdue', 'outstanding_amount'].includes(col.fieldname)
                    );
                    report.refresh();
                }

                // Add appropriate action buttons
                if (access_level === 'full' || access_level === 'chapter') {
                    report.page.add_inner_button(__("Financial Actions"), function() {
                        show_financial_actions_menu(report, access_level);
                    });
                }
            }
        });
    }
};
```

### 9.5 Dashboard Access Control

#### Payment Health Dashboard Permissions

```python
@frappe.whitelist()
def get_payment_health_dashboard_data():
    """
    Return dashboard data based on user permissions
    """
    access_level = get_financial_access_level(frappe.session.user)

    if access_level == 'none':
        frappe.throw(_("Insufficient permissions"))

    dashboard_data = {}

    if access_level == 'full':
        # Complete organizational view
        dashboard_data = {
            "total_members": get_total_active_members(),
            "payment_status_breakdown": get_payment_status_breakdown(),
            "outstanding_by_chapter": get_outstanding_by_chapter(),
            "collection_trends": get_collection_trends(months=12),
            "at_risk_members": get_at_risk_members(),
            "payment_method_distribution": get_payment_method_stats()
        }

    elif access_level == 'chapter':
        # Chapter-specific view
        access_info = get_chapter_board_access(get_current_member())
        dashboard_data = {
            "chapter_members": get_chapter_member_count(access_info['chapters']),
            "chapter_payment_status": get_chapter_payment_status(access_info['chapters']),
            "chapter_outstanding": get_chapter_outstanding_total(access_info['chapters']),
            "chapter_collection_rate": get_chapter_collection_rate(access_info['chapters']),
            "chapter_at_risk": get_chapter_at_risk_members(access_info['chapters'])
        }

    elif access_level == 'limited':
        # High-level statistics only
        access_info = get_chapter_board_access(get_current_member())
        dashboard_data = {
            "chapter_members": get_chapter_member_count(access_info['chapters']),
            "members_current": count_current_members(access_info['chapters']),
            "members_overdue": count_overdue_members(access_info['chapters'])
            # No financial amounts
        }

    return dashboard_data
```

### 9.6 Audit Trail for Financial Access

```python
def log_financial_access(user, action, target_member, details=None):
    """
    Create audit trail for financial data access
    """
    audit_log = frappe.new_doc("Financial Access Log")
    audit_log.user = user
    audit_log.timestamp = now_datetime()
    audit_log.action = action
    audit_log.target_member = target_member
    audit_log.access_level = get_financial_access_level(user)
    audit_log.ip_address = frappe.local.request_ip
    audit_log.details = details or {}

    # Add user context
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if user_member:
        board_access = get_chapter_board_access(user_member)
        audit_log.user_chapters = board_access.get('chapters', [])
        audit_log.user_role = board_access.get('permissions_level')

    audit_log.insert(ignore_permissions=True)

    # Alert on suspicious access patterns
    check_access_patterns(user, target_member)

def check_access_patterns(user, target_member):
    """
    Detect suspicious access patterns
    """
    # Check for excessive access
    recent_access_count = frappe.db.count("Financial Access Log", {
        "user": user,
        "timestamp": [">", add_hours(now_datetime(), -1)]
    })

    if recent_access_count > 50:
        notify_security_alert(
            f"Excessive financial data access by {user}",
            f"User accessed {recent_access_count} records in past hour"
        )
```

### 9.7 Permission Configuration UI

```python
# Chapter Role Enhancement
class ChapterRole(Document):
    def validate(self):
        """Enhanced validation for finance permissions"""

        # Define permission capabilities by level
        permission_capabilities = {
            "Admin": ["view_all", "edit_all", "financial_full"],
            "Finance": ["view_financial", "edit_financial", "send_reminders"],
            "Membership": ["view_summary", "send_communications"],
            "General": ["view_limited"]
        }

        # Set capabilities based on level
        if self.permissions_level in permission_capabilities:
            self.capabilities = json.dumps(
                permission_capabilities[self.permissions_level]
            )
```

### 9.8 Security Best Practices

```markdown
## Financial Data Security Guidelines

1. **Principle of Least Privilege**
   - Users only see data necessary for their role
   - Financial amounts hidden from non-finance roles
   - Sensitive actions require additional confirmation

2. **Data Masking**
   - Bank account numbers partially hidden
   - IBAN shown as NL**TEST****6789
   - Full details only for authorized users

3. **Access Logging**
   - All financial data access is logged
   - Audit trail includes user, time, and action
   - Suspicious patterns trigger alerts

4. **Session Security**
   - Financial sessions timeout after 15 minutes
   - Re-authentication required for sensitive actions
   - IP-based access restrictions available

5. **Regular Access Reviews**
   - Monthly review of board member permissions
   - Automatic deactivation of inactive board members
   - Annual audit of access logs
```

---

## Summary

The access control system ensures that:
- **National board members** and **administrators** have full visibility for organizational oversight
- **Chapter board members with finance access** can effectively manage their chapter's financial health
- **Chapter board members without finance access** can see member status without sensitive financial details
- **Regular members** have full transparency into their own financial situation
- All access is **logged and auditable** for security and compliance
