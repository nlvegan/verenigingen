# Volunteer Management System

## Overview

The Volunteer Management System provides coordination of volunteer activities within the association, integrating with the member lifecycle and team organization systems. This system handles volunteer onboarding, skill tracking, team assignments, expense management, and performance tracking while maintaining integration with ERPNext HR capabilities.

## Core Architecture

### Volunteer Services (`services/volunteer/`)

The volunteer service layer contains 15 specialized modules:

**Core Volunteer Operations:**

- `volunteer_activation_service.py` -- Activates volunteer profiles, manages status transitions
- `bulk_volunteer_creation_service.py` -- Creates volunteer records in bulk
- `volunteer_statistics.py` -- Volunteer program statistics and metrics
- `volunteer_role_profile_hooks.py` -- Role profile management on volunteer status changes

**Assignment Management:**

- `assignment_service.py` -- Volunteer assignment creation, modification, and tracking
- `assignment_query_builder.py` -- Optimized queries for assignment data retrieval
- `activity_service.py` -- Volunteer activity logging and tracking

**Expense Management:**

- `expense_approver_service.py` -- Manages expense claim approver assignments
- `expense_handlers.py` -- Doc event handlers for Expense Claim (on_submit, on_cancel notifications)
- `expense_history_batch_processor.py` -- Batch processing for expense history updates (daily, weekly, monthly scheduled tasks)
- `expense_history_entry_builder.py` -- Builds individual expense history entries
- `expense_submission_service.py` -- Handles expense claim submission workflow
- `native_expense_helpers.py` -- Updates employee approvers, daily scheduled refresh
- `volunteer_expense_setup.py` -- Initial expense infrastructure setup for volunteers
- `volunteer_expense_portal_utils.py` -- Portal-facing expense utilities

**Department Integration:**

- `department_approver_sync.py` -- Syncs department approvers daily

### Volunteer DocType (`Verenigingen Volunteer`)

Central volunteer entity with profile management:

**Key Characteristics:**

- 1:1 relationship with Member DocType
- Employee integration for expense management
- Skills and development goal tracking

**Core Fields:**

- **Identity**: volunteer_name, member (link), user (system account)
- **Contact**: email (organization), personal_email (from member), preferred_pronouns
- **Profile**: status, start_date, employee_id, image
- **Preferences**: commitment_level, experience_level, preferred_work_style
- **Skills**: skills_and_qualifications (table), desired_skill_development (table)
- **Activities**: interests (multi-select), assignment_history (table)

**Status Lifecycle:**

1. **New**: Initial volunteer registration
2. **Onboarding**: Training and orientation phase
3. **Active**: Regular volunteer activities
4. **Inactive**: Temporary suspension of activities
5. **Retired**: Formal end of volunteer service

### Team Organization Architecture

#### Team Management (`Team`)

Flexible team structure supporting various organizational needs:

**Team Types:** Committee, Working Group, Task Force, Project Team, Operational Team, Other

**Doc Event Hooks (from `hooks/doc_events.py`):**

- `on_update`: Team lead change handler, team members change handler, profile cache invalidation
- Note: Team Member is a child table -- child table doc_events never fire when rows are managed via parent save

#### Role Profile Automation

Managed by `utils/team_role_profile_manager.py` and `utils/team_role_profile_hooks.py`.

### Expense Management Integration

#### ERPNext Employee Integration

- `volunteer_activation_service.py` creates Employee DocType records for volunteers
- `volunteer_expense_setup.py` configures expense claim infrastructure
- `native_expense_helpers.py` manages employee-approver relationships

#### Expense Event Handling

From `hooks/doc_events.py`:

**Expense Claim:**
- `validate`: Account group validation
- `on_submit`: Update member expense history, notify expense approvers
- `on_update_after_submit`: Schedule member expense history update
- `on_cancel`: Schedule expense history removal, handle cancellation

#### Scheduled Expense Operations

From `hooks/scheduler.py`:

- **Daily**: Refresh all expense approvers, sync department approvers, process pending expense history
- **Weekly**: Validate expense history integrity
- **Monthly**: Cleanup orphaned expense history

### Document Event Hooks

From `hooks/doc_events.py`:

**Verenigingen Volunteer `on_update`:**
- Update employee approver (`native_expense_helpers`)
- Chapter role events (`chapter_role_events.on_volunteer_on_update`)
- Performance event handlers
- Volunteer role profile hooks (`on_volunteer_status_change`)

### Permission and Access Control

From `hooks/permissions.py`:

- **Volunteer**: `get_volunteer_permission_query` + `has_volunteer_permission`
- **Expense Claim**: `get_expense_claim_permission_query` + `has_expense_claim_permission`
- **Employee**: `get_employee_permission_query`
- **Project**: `get_project_permission_query_conditions` + `has_project_permission_via_team`

### Architecture Documentation

The volunteer services directory includes `ARCHITECTURE.md` documenting the service layer design decisions.

### Skills and Development Framework

The Volunteer DocType supports comprehensive skill tracking:

**Skill Categories:**

- `skills_and_qualifications` child table tracks current skills with proficiency levels
- `desired_skill_development` child table tracks development goals
- `interests` multi-select field for activity preferences
- `experience_level` and `commitment_level` fields for matching

**Interest Area Matching:**

Skills and interests are used by the assignment system to match volunteers to appropriate teams and activities.

### Bulk Operations

`bulk_volunteer_creation_service.py` supports creating volunteer records in batch, typically used during initial system setup or when onboarding groups of new volunteers.

`volunteer_statistics.py` provides aggregate volunteer program metrics.

### Data Model Relationships

```
Member (1) <-> (0..1) Volunteer
Volunteer (1) <-> (0..1) Employee
Volunteer (1) <-> (n) Volunteer Assignment
Team (1) <-> (n) Team Member
Team (1) <-> (0..1) Chapter
User (1) <-> (0..1) Volunteer
```

## Key File Locations

- **Volunteer DocType**: `verenigingen/doctype/verenigingen_volunteer/`
- **Team DocType**: `verenigingen/doctype/team/`
- **Volunteer services**: `services/volunteer/` (15 modules)
- **Team role profile**: `utils/team_role_profile_manager.py`, `utils/team_role_profile_hooks.py`
- **Hooks**: `hooks/doc_events.py` (Verenigingen Volunteer, Team, Expense Claim sections)
- **Permissions**: `hooks/permissions.py` (Volunteer, Employee, Expense Claim, Project)
