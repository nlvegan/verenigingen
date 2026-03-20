# Chapter Management

Chapters are the local branches of your association. Verenigingen provides a full chapter management system covering geographic organization, board governance, member coordination, and financial tracking.

## Core Concepts

### Chapter Record

The Chapter DocType (`/app/chapter`) represents a local branch. Each chapter has:

- **Chapter name** and description
- **Region** (geographic area)
- **Status** (Active, Inactive)
- **Chapter head** (automatically set from the board chair)
- **Board members** (child table of Chapter Board Members)
- **Members** (child table of Chapter Members)
- **Cost center** (for financial tracking in ERPNext)
- **Department** (synced with ERPNext Department for expense routing)
- **Website page** (public chapter page at `/chapter/CHAPTER-NAME`)

### Chapter Roles

Chapter Roles (`/app/chapter-role`) define the positions available on a chapter board (e.g., Chair, Secretary, Treasurer). Each role can have:

- **Role name** and description
- **Role Profile mapping** - links to Frappe Role Profiles for permission management

When a member is appointed to a board position, they automatically receive the permissions defined by the role's profile mapping.

### Chapter Members vs Board Members

- **Chapter Members** are regular association members assigned to this chapter
- **Board Members** are chapter members who hold governance positions (chair, secretary, treasurer, etc.)

Board members have elevated permissions for their chapter, managed through role profile mappings.

## Chapter Operations

### Provisioning a New Chapter

The chapter provisioning service handles the setup of new chapters:

1. **Region verification** - Ensures the geographic region exists (auto-creates a Netherlands region if needed)
2. **Chapter creation** - Creates the Chapter record with required fields
3. **Cost center creation** - Sets up a dedicated ERPNext Cost Center for financial tracking
4. **Department sync** - Creates or links an ERPNext Department for expense claim routing

To create a chapter manually, navigate to `/app/chapter/new` and fill in the required fields.

### Board Member Management

Board members are managed through the Chapter record's Board Members section. The **BoardManager** handles:

- **Appointments** - Adding members to board positions with start dates
- **Role assignment** - Linking board positions to Chapter Roles with permission profiles
- **Chair tracking** - Automatically updating the chapter head field when a chair is appointed
- **Term management** - Tracking start and end dates for board positions
- **Permission updates** - Granting and revoking role profiles when board membership changes

When a board member is appointed:
1. Their Chapter Board Member record is created
2. The appropriate Role Profile is assigned to their user account
3. If they are the chair, the chapter head field is updated
4. A chapter board change event is emitted for notifications

### Member Registration

Members are assigned to chapters through the **MemberManager**:

- **Automatic assignment** during membership approval (based on postal code matching)
- **Manual assignment** by administrators
- **Join requests** from members via the Chapter Join Request (`/app/chapter-join-request`)

Chapter membership history is tracked in the **Chapter Membership History** DocType, recording when members join and leave each chapter.

### Postal Code Matching

The **ChapterMatchingService** automatically assigns new members to chapters based on their postal code. This uses the Region system to map postal codes to geographic areas and then to chapters.

### Communication

The **CommunicationManager** handles chapter-level announcements and notifications:

- Board change notifications
- Member welcome messages
- Chapter announcements to all members

## Chapter Validation

The chapter system includes comprehensive validation through the **ChapterValidator**:

- **Chapter info validation** - Required fields, date consistency
- **Board member validation** - Role assignments, duplicate checks, date overlaps
- **Postal code validation** - Format and region matching

Validators use a `ValidationResult.merge()` pattern that collects all errors before reporting, giving users a complete picture of what needs fixing.

## Financial Tracking

### Cost Centers

Each chapter can have a dedicated ERPNext Cost Center for tracking income and expenses. The **ChapterFinanceService** manages:

- Cost center creation (using existing centers if available, creating new ones if needed)
- Cost center assignment to the chapter record
- Financial reporting by chapter

### Department Sync

The **DepartmentSyncService** synchronizes chapters with ERPNext Departments:

- Creates Department records matching chapters
- Enables ERPNext's native expense approval workflows
- Routes expense claims to the correct chapter-level approvers

This integration allows volunteer expense claims to flow through ERPNext's standard approval process while keeping chapters as the primary organizational unit.

### Chapter Board Documents

The Chapter Board Document DocType (`/app/chapter-board-document`) stores governance documents:

- Meeting minutes
- Board resolutions
- Policy documents

Files are automatically organized into chapter-specific folders.

## Website Integration

Chapters have public-facing pages accessible at `/chapter/CHAPTER-NAME`. These pages display:

- Chapter description and contact information
- Board member listings
- Public chapter information

Public chapter pages are served through custom web pages (not Frappe's WebsiteGenerator), ensuring proper separation between the admin desk view and the public website.

## Permissions and Security

### Role-Based Access

Chapter permissions are managed through a layered system:

1. **Standard Frappe permissions** control who can view/edit chapter records
2. **Chapter Role Profiles** grant additional permissions to board members
3. **Chapter-specific scoping** ensures board members only manage their own chapter

The **ChapterPermissionService** handles permission checks and updates.

### Board Permission Lifecycle

When a member becomes a board member:
1. They receive the Role Profile for their board position
2. They gain write access to chapter-specific records
3. When they leave the board, the Role Profile is removed

## Key Configuration

### Regions

Navigate to `/app/region` to set up geographic regions. Regions are used for:
- Chapter assignment via postal code matching
- Geographic reporting and analytics

### Chapter Roles

Navigate to `/app/chapter-role` to define board positions. Link each role to a **Chapter Role Profile Mapping** to control permissions.

### Verenigingen Settings

Chapter-related settings in `/app/verenigingen-settings`:
- Default region for new chapters
- Chapter provisioning defaults

## Common Tasks

| Task | Where |
|------|-------|
| View all chapters | `/app/chapter` |
| Create a new chapter | `/app/chapter/new` |
| Manage board members | Open chapter record, edit Board Members table |
| Process join requests | `/app/chapter-join-request` |
| View chapter members | Open chapter record, Members section |
| View membership history | `/app/chapter-membership-history?chapter=CHAPTER` |
| Manage chapter roles | `/app/chapter-role` |
| View chapter finances | Check the chapter's linked Cost Center in ERPNext |
| Configure role permissions | `/app/chapter-role-profile-mapping` |
