# Member Lifecycle Management System

## Overview

The Member Lifecycle Management System is the core of the Verenigingen association management platform. It orchestrates the complete journey from initial membership application through active membership, renewals, and eventual termination. This system integrates with financial operations, volunteer management, and chapter organization to provide comprehensive member management.

## Core Architecture

### Service Layer Organization

The member service layer lives under `services/member/` with domain-specific subdirectories:

- **`account/`** -- User account creation, role profiles, role management
- **`approval/`** -- Application helpers, approval service, membership creation, application payments
- **`chapter/`** -- Chapter management service for member-chapter relationships
- **`core/`** -- Lifecycle service, membership service, address service, fee changes, ID generation, status management
- **`debug/`** -- Debug tools for member troubleshooting
- **`display/`** -- Address display, chapter display, volunteer display, onload data
- **`donor/`** -- Donor management, customer sync, auto-creation, member-donor reconciliation
- **`financial/`** -- Fee calculation, fee validation, fee override hooks, fee change recording, item service
- **`history/`** -- Fee change history, member history updates
- **`identification/`** -- Member ID service
- **`integration/`** -- Member-donor integration service
- **`lifecycle/`** -- Before-save service, cleanup service, event emission, status notifications
- **`payment/`** -- Payment coverage service, payment history service
- **`testing/`** -- Debug tools and test utilities
- **`utils/`** -- Duration service, membership duration, age service
- **`validation/`** -- Duplicate detection, member validation

### Central DocTypes

#### Member (`Member`)

The foundational entity representing an association member:

**Key Characteristics:**

- Auto-naming: `Assoc-Member-{YYYY}-{MM}-{####}`
- Complete Dutch name handling including tussenvoegsel (van, de, der, etc.)
- Lifecycle status tracking from application through termination
- Multi-tab organization: Member Details, Membership Data, Financial Information, Volunteer & Chapter Data, Administration, Miscellaneous

**Core Fields:**

- **Identity**: first_name, middle_name, tussenvoegsel, last_name, full_name, pronouns, birth_date, age
- **Contact**: email, contact_number, primary_address
- **Status Management**: status (Pending, Active, Rejected, Expired, Suspended, Banned, Deceased, Terminated)
- **Application Data**: application_id, application_status, application_date, selected_membership_type
- **Membership Tracking**: current_membership_plan, current_dues_schedule, next_invoice_date
- **Financial Integration**: customer (ERPNext Customer), payment_method, dues_rate

**Integration Points:**

- Links to Membership records for time-bounded membership periods
- Customer integration for ERPNext financial operations
- Employee integration for volunteer expense claims
- User integration for portal access
- Address optimization for household member detection

#### Membership (`Membership`)

Time-bounded membership periods with submission workflow:

**Key Characteristics:**

- Auto-naming: `MEMB-{YY}-{MM}-{####}`
- Submittable DocType with workflow states
- Grace period management for payment delays
- Cancellation handling with reason tracking

**Core Fields:**

- **Member Link**: member, member_name, email, contact_number
- **Type & Status**: membership_type, status (Draft, Active, Pending, Inactive, Expired, Cancelled)
- **Period Management**: start_date, renewal_date (minimum 1 year)
- **Grace Periods**: grace_period_status, grace_period_expiry_date, grace_period_reason
- **Cancellation**: cancellation_date, cancellation_reason, cancellation_type

### Lifecycle States and Transitions

#### Application Phase

1. **Initial Application**: Online form submission via web form
2. **Review Process**: Manual or automated approval workflow (`member_approval_service.py`)
3. **Payment Setup**: SEPA mandate creation, dues schedule generation (`membership_creation_service.py`)
4. **Activation**: Member status change to Active, integration setup (`member_lifecycle_service.py`)

#### Active Membership Phase

1. **Dues Processing**: Automated invoice generation from dues schedules
2. **Payment Collection**: SEPA direct debit batch processing
3. **Status Monitoring**: Grace period management for payment delays
4. **Renewal Processing**: Automated renewal workflows via `membership/scheduler.py`

#### Termination Phase

Handled by `services/termination/`:

1. **Request Submission**: `Membership Termination Request` DocType initiation
2. **Execution**: `termination_execution_service.py` with FOR UPDATE row locks for race condition prevention
3. **Integration Cleanup**: `termination_integration.py` handles related record updates
4. **Audit**: `termination_audit_service.py` maintains compliance records
5. **Utilities**: `termination_utils.py` provides daily overdue processing and weekly reporting

## Application Management System

### Web Form Integration

- Public membership application form
- Dutch postal code validation
- IBAN validation for payment setup
- Chapter preference selection
- Volunteer interest indication

### Review Workflow

- Automated eligibility checking via `application_helpers.py`
- Manual review for edge cases
- Payment verification through `application_payments.py`
- Chapter assignment

### Data Validation

- Age requirement enforcement (16+ for volunteers)
- Dutch business logic (postal codes, IBAN format)
- Duplicate detection via `member_duplicate_detection_service.py`
- Address normalization and household detection

## Address Optimization System

### Household Member Detection

Advanced address matching system for detecting multiple members at the same address:

**Technical Implementation:**

- 8-byte hash fingerprinting for O(1) address matching
- Normalized address line and city name storage
- Background tasks: daily `update_all_member_address_fingerprints`, weekly `refresh_member_address_displays`, monthly `cleanup_orphaned_address_data` (all in `tasks/address_optimization.py`)
- Display services in `services/member/display/member_address_display_service.py`

## Document Event Hooks

Member-related doc_events registered in `hooks/doc_events.py`:

- **Member `before_save`**: Updates termination status display
- **Member `after_save`**: Email group sync, cache invalidation, performance cache update
- **Member `on_update`**: Chapter role events, field sync service
- **Membership `on_submit`/`on_cancel`/`on_update`**: Membership hooks + performance cache

## Background Processing

### Scheduled Tasks (from `hooks/scheduler.py`)

- **Daily**: Member financial history refresh, expired membership processing, renewal reminders, orphaned record notifications, SEPA mandate discrepancy checks
- **Hourly**: Payment history validation
- **Weekly**: Address display refresh, termination reports
- **Monthly**: Orphaned address data cleanup
- **High-frequency (30s)**: Financial history batch processing

## Security and Permissions

### Permission Queries (from `hooks/permissions.py`)

Row-level security is implemented for:

- **Member**: `get_member_permission_query` + `has_member_permission`
- **Membership**: `get_membership_permission_query` + `has_membership_permission`
- **Chapter Member**: `get_chapter_member_permission_query`
- **Membership Termination Request**: `get_termination_permission_query` + `has_membership_termination_request_permission`
- **Address**: `get_address_permission_query` + `has_address_permission`

### Role-Based Access Control

- **Verenigingen Member**: Own record access only
- **Verenigingen Staff**: Read-only member access
- **Verenigingen Chapter Board Member**: Chapter member management
- **Verenigingen Manager**: Full member management
- **Verenigingen Administrator**: System administration

## Data Model Relationships

```
Member (1) <-> (n) Membership
Member (1) <-> (n) Chapter Member
Member (1) <-> (1) Customer
Member (1) <-> (0..1) User
Member (1) <-> (0..1) Employee
Member (1) <-> (n) SEPA Mandate
Member (1) <-> (n) Payment History
Member (1) <-> (n) Volunteer Assignment
Member (1) <-> (0..1) Donor
```

## Key File Locations

- **DocType**: `verenigingen/doctype/member/`, `verenigingen/doctype/membership/`
- **Services**: `services/member/` (19 subdirectories)
- **Termination**: `services/termination/` (5 service files)
- **Hooks**: `hooks/doc_events.py`, `hooks/scheduler.py`, `hooks/permissions.py`
- **Schedulers**: `verenigingen/doctype/member/scheduler.py`, `verenigingen/doctype/membership/scheduler.py`
