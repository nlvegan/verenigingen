# Membership Management

Verenigingen provides a complete membership lifecycle system for Dutch non-profit associations, from initial application through termination. It integrates with SEPA direct debit, chapter assignment, and financial billing.

## Core Concepts

### Member Record

The Member DocType (`/app/member`) is the central record for each association member. It stores:

- Personal information (name, address, email, phone)
- Dutch name formatting (tussenvoegsel / prefix support)
- Membership status and history
- Chapter assignment
- SEPA mandate references
- Financial data (fees, payment coverage)
- Volunteer record link

Each member receives a unique Member ID, generated automatically upon approval.

### Membership Types

Membership Types (`/app/membership-type`) define the categories of membership your association offers. Each type specifies:

- **Billing period** (monthly, quarterly, yearly, or custom)
- **Minimum amount** for membership fees
- **Dues Schedule Template** linking to automatic billing configuration

Common examples: Regular Member, Student Member, Senior Member, Supporting Member.

To configure, navigate to `/app/membership-type` and create or edit types as needed.

### Membership Record

A Membership (`/app/membership`) is a submittable document linking a Member to a Membership Type for a specific period. Key fields:

- Start date and end date
- Membership type
- Renewal date (calculated automatically)
- Grace period expiry
- Status (Active, Expired, Cancelled)

When submitted, a Membership automatically creates a **Membership Dues Schedule** for recurring billing.

## Member Lifecycle

### 1. Application

New members apply through the public-facing membership application form. The application collects personal details, preferred membership type, and payment preferences.

Applications are created with status **Pending** and appear in the review queue at `/app/membership-application-review`.

### 2. Review and Approval

Administrators review applications at `/app/member` (filtered by application status). The review process includes:

- Identity verification
- Duplicate member detection (automatic matching by name, address, email)
- Age validation (configurable minimum age requirements)
- Chapter assignment (based on postal code matching or manual selection)

Approval triggers several automated steps:
- Member ID generation
- User account creation (website login)
- Membership record creation and submission
- Dues schedule setup
- Chapter membership registration
- Volunteer record activation (if applicable)
- Welcome email notification

### 3. Active Membership

Active members have access to:

- **Member portal** for viewing and updating personal information
- **Chapter participation** through their assigned local chapter
- **Volunteer activities** if registered as a volunteer
- **Expense claims** for reimbursement of association-related costs

### 4. Fee Management

Membership fees are managed through the dues schedule system:

- Fees are calculated based on the linked Membership Type
- Fee overrides can be set per member (e.g., reduced fees for financial hardship)
- Fee changes are tracked in the **Member Fee Change History** for audit purposes
- Age-based fee groups may apply (configurable per membership type)

To change a member's fee, update the fee override on their Member record. The system records who made the change and when.

### 5. Termination

Membership termination follows a structured workflow via the **Membership Termination Request** (`/app/membership-termination-request`):

- **Member-initiated**: The member requests termination; a grace period applies (configurable, default 30 days)
- **Administrative**: Staff terminates the membership immediately
- **Disciplinary**: Board-initiated termination with documentation

The termination request goes through these statuses: Draft, Submitted, Approved, Executed. Upon execution:

- The membership is cancelled
- The dues schedule is paused
- The member status is updated
- An audit trail is maintained

## SEPA Mandate Management

Members can authorize recurring payments via SEPA Direct Debit. SEPA Mandates (`/app/sepa-mandate`) track:

- **Mandate ID** (auto-generated)
- **IBAN** (validated for format correctness)
- **Status** (Draft, Active, Suspended, Cancelled, Expired)
- **Usage scope** (memberships, donations, or both)
- **Expiry date** with automatic status updates

Mandates are linked to the Member record and can be used for both membership fees and donations. The system automatically expires mandates past their expiry date.

To view a member's mandates, open their Member record and check the SEPA section, or navigate to `/app/sepa-mandate?member=MEMBER-ID`.

## Chapter Membership

Each member can belong to one chapter (local branch). Chapter assignment happens:

- **Automatically** during application approval, based on postal code matching
- **Manually** by an administrator via the Member record

Chapter membership history is tracked, recording when members join and leave chapters. See [Chapter Management](chapter-management.md) for details on chapter operations.

## Key Configuration

### Verenigingen Settings

Navigate to `/app/verenigingen-settings` to configure:

- Default grace period for termination (days)
- Membership ID format and numbering
- Age group thresholds
- Default membership type for new applications

### Membership Types

Navigate to `/app/membership-type` to manage:

- Available membership categories
- Billing periods and minimum amounts
- Linked dues schedule templates

### Regions

Navigate to `/app/region` to set up geographic regions for chapter matching and postal code assignment.

## Common Tasks

| Task | Where |
|------|-------|
| Review pending applications | `/app/member?status=Pending` |
| View active members | `/app/member?status=Active` |
| Process a termination | `/app/membership-termination-request/new` |
| Change a member's fee | Edit the member record, update fee override |
| View membership history | Open a member record, check History section |
| Manage SEPA mandates | `/app/sepa-mandate` |
| View dues schedules | `/app/membership-dues-schedule` |
| Merge duplicate members | See [Member Merge](MEMBER_MERGE.md) |
