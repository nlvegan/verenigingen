# Volunteer Management

Verenigingen provides a volunteer coordination system for tracking volunteer registrations, assignments, skills, activities, and expense reimbursements. Volunteers are typically association members who contribute their time.

## Core Concepts

### Volunteer Record

The Volunteer DocType (`/app/volunteer`) is the central record for each volunteer. Key fields:

- **Volunteer name** (inherited from linked Member if applicable)
- **Member link** (connects the volunteer to their Member record)
- **Email and contact details** (inherited from the linked member's address/contact)
- **Status** (Active, Inactive)
- **Start date** and availability information
- **Skills and interests** (tracked via child tables)
- **Assignment history** (all past and current assignments)

Volunteers must be at least 16 years old. The system validates age requirements during registration.

### Volunteer Activities

Volunteer Activities (`/app/volunteer-activity`) track specific work a volunteer performs. Each activity records:

- **Volunteer** reference
- **Activity type** and role
- **Date range** (start and end dates)
- **Status** (Active, Completed, Cancelled)
- **Reference** to the related document (project, event, chapter, etc.)

When an activity's status changes, the volunteer's assignment history is automatically updated.

### Volunteer Assignments

Volunteer Assignments (`/app/volunteer-assignment`) provide a detailed audit trail of where and when a volunteer has served. Each assignment includes:

- **Assignment type** (Chapter, Project, Team, etc.)
- **Role** performed
- **Reference** to the organizational unit
- **Date range**
- **Status**

Assignments are automatically created when volunteers are added to chapters, projects, or teams.

## Skills and Interests

### Skill Tracking

Volunteer Skills (`/app/volunteer-skill`) record what each volunteer can do. Skills are organized by:

- **Skill Category** (`/app/volunteer-skill-category`) - broad groupings like "Communication", "Technical", "Administrative"
- **Skill name** - specific abilities within each category

Administrators can define skill categories at `/app/volunteer-skill-category` and then assign skills to individual volunteer records.

### Interest Areas

Volunteer Interest Areas (`/app/volunteer-interest-area`) track what volunteers want to do. Interest areas are organized by:

- **Interest Category** (`/app/volunteer-interest-category`) - broad themes like "Events", "Advocacy", "Education"
- **Interest name** - specific topics within each category

This helps match volunteers to suitable activities and chapter needs.

### Development Goals

Volunteer Development Goals (`/app/volunteer-development-goal`) track growth objectives for each volunteer, supporting personal development within the association.

## Volunteer Lifecycle

### 1. Registration

Volunteers can register through:

- **Membership application** - Applicants can indicate volunteer interest during membership signup
- **Volunteer application form** - Existing members can apply to volunteer
- **Administrative creation** - Staff can create volunteer records at `/app/volunteer/new`

The system checks for existing volunteer records by member link and email to prevent duplicates.

### 2. Activation

When a membership application with volunteer interest is approved, the volunteer record is automatically activated. The activation process:

1. Finds or creates the Volunteer record
2. Links it to the Member record
3. Sets the status to Active
4. Upgrades the user account with volunteer permissions (role profiles)
5. Sends a notification

### 3. Assignment

Active volunteers can be assigned to:

- **Chapters** - Local branch activities (managed through the Chapter's board/volunteer system)
- **Teams** - Cross-chapter working groups
- **Projects** - Specific time-bound initiatives
- **Activities** - Individual tasks or events

Assignments can be made through the relevant organizational unit (chapter, team, project) or directly on the Volunteer record.

### 4. Expense Reimbursement

Volunteers can submit expense claims for costs incurred during association activities.

**Submitting an expense claim:**

1. Navigate to the volunteer expense portal
2. Enter the expense details:
   - Description and amount
   - Expense date and category
   - Organization type (Chapter, Team, or National)
   - Which chapter or team the expense is for
   - Receipt attachment (photo or scan)
3. Submit for approval

**Expense approval workflow:**

- Expense claims are routed to the appropriate approver based on the organization type
- Chapter expenses go to the chapter board for approval
- National expenses go to the national finance team
- Approved claims are processed through ERPNext's standard Expense Claim system

The system automatically creates an ERPNext Employee record for the volunteer (required by the Expense Claim DocType) if one does not already exist.

### 5. Deactivation

When a volunteer steps down or their membership ends:

- Their Volunteer status is set to Inactive
- Active assignments are closed with an end date
- The volunteer's user account permissions are adjusted
- Historical records are preserved for reporting

## Bulk Operations

### Bulk Volunteer Creation

Administrators can create multiple volunteer records at once using the bulk creation service. This is useful when onboarding a group of new volunteers (e.g., after a recruitment drive).

## Integration with Chapters

Volunteers are tightly integrated with the Chapter system:

- The **VolunteerIntegrationManager** on the Chapter DocType coordinates volunteer assignments within each chapter
- Chapter board members are tracked as volunteer assignments
- Chapter-level volunteer statistics are available on the chapter record

See [Chapter Management](chapter-management.md) for details on chapter-volunteer coordination.

## Integration with Members

When a Volunteer is linked to a Member:

- Address and contact information is inherited from the Member record
- The volunteer portal shows member-relevant information
- Financial records (expenses) are connected to the member's profile

## Key Configuration

### Expense Types

Navigate to `/app/expense-claim-type` to configure the categories available for volunteer expense claims (e.g., Travel, Materials, Catering).

### Skill and Interest Categories

- `/app/volunteer-skill-category` - Define skill groupings
- `/app/volunteer-interest-category` - Define interest groupings

### Department Approver Sync

The system can synchronize chapter-based expense approvers with ERPNext's Department structure, ensuring that expense claims are routed correctly.

## Common Tasks

| Task | Where |
|------|-------|
| View all volunteers | `/app/volunteer` |
| Create a new volunteer | `/app/volunteer/new` |
| Assign a volunteer to a chapter | Edit the Chapter record, add to board/volunteer list |
| View volunteer activities | `/app/volunteer-activity?volunteer=VOL-NAME` |
| Review expense claims | `/app/expense-claim?approval_status=Open` |
| Manage skill categories | `/app/volunteer-skill-category` |
| Manage interest categories | `/app/volunteer-interest-category` |
| View volunteer statistics | Chapter record or volunteer dashboard |
