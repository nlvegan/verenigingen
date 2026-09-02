# Chapter Organization System

## Overview

The Chapter Organization System provides geographic and administrative structure for association management, enabling local chapter operations while maintaining central coordination. This system supports multi-level governance, regional management, and permission structures that align with Dutch association governance practices.

## Core Architecture

### Chapter Services (`services/chapter/`)

The chapter service layer contains 16 specialized modules:

- `chapter_assignment_service.py` -- Assigns members to chapters based on postal code
- `chapter_board_service.py` -- Board member management, appointment, and removal
- `chapter_board_permissions.py` -- Permission logic for board-level operations
- `chapter_event_service.py` -- Chapter event handling
- `chapter_finance_service.py` -- Cost center creation and financial tracking
- `chapter_matching_service.py` -- Matches postal codes to chapters
- `chapter_membership_manager.py` -- Chapter member add/remove/status operations
- `chapter_permission_service.py` -- Chapter-level permission enforcement
- `chapter_provisioning_service.py` -- New chapter setup and provisioning
- `chapter_query_service.py` -- Optimized queries for chapter data
- `chapter_reference_manager.py` -- Manages cross-references between chapters and related records
- `chapter_role_events.py` -- Doc event handlers for member/volunteer/chapter role changes
- `chapter_role_profile_hooks.py` -- Cache invalidation for chapter role profiles
- `chapter_role_profile_manager.py` -- Assigns/removes role profiles for board members
- `chapter_security.py` -- Security enforcement for chapter operations
- `chapter_utils.py` -- Shared chapter utility functions
- `chapter_validation_service.py` -- Chapter data validation with `ValidationResult.merge()` pattern
- `department_sync_service.py` -- Syncs chapter structure with ERPNext Department
- `optimized_chapter_lookup.py` -- Cached chapter lookup with cache invalidation on chapter save

### Chapter DocType (`Chapter`)

Geographic organizational units with governance and membership management:

**Key Characteristics:**

- User-defined naming for flexibility
- Web view integration for public chapter pages
- Guest access for public information
- Permission levels for sensitive governance data

**Core Fields:**

- **Identity**: chapter_head, status (Active/Inactive/Dissolved), region
- **Geography**: postal_codes (pattern-based area definition), address
- **Governance**: board_members (table), board role profile configuration
- **Finance**: cost_center (financial tracking integration)
- **Web Presence**: introduction, meetup_embed_html, route, published
- **Membership**: members (Chapter Member table)

### Geographic Management

#### Regional Structure (`Region`)

Higher-level geographic organization above individual chapters.

#### Postal Code-Based Assignment

Sophisticated geographic assignment using Dutch postal code patterns:

**Pattern Support:**

- **Range Patterns**: `1000-1099` (covers postal codes 1000 through 1099)
- **Exact Matches**: `2500` (covers only postal code 2500)
- **Wildcard Patterns**: `3*` (covers all postal codes starting with 3)
- **Multiple Patterns**: Comma-separated list for complex geographic areas

**Automatic Assignment:**

- `chapter_matching_service.py` matches member postal codes to chapter patterns
- `chapter_assignment_service.py` handles the actual assignment logic
- Manual override capability for special cases

### Member-Chapter Relationships

#### Chapter Membership (`Chapter Member`)

Many-to-many relationship managed by `chapter_membership_manager.py`:

- **Multi-Chapter Membership**: Members can belong to multiple chapters
- **Status Tracking**: Pending, Active, Inactive status per chapter
- **Join Date Tracking**: Historical membership timeline
- Cache invalidation via doc_events on `after_save` and `on_trash`

### Governance and Board Management

#### Chapter Board Structure

Managed by `chapter_board_service.py`:

- Chapter Head (automatic leadership role)
- Board Members with specific roles (Treasurer, Secretary, etc.)
- Board role profile automation via `chapter_role_profile_manager.py`

**Important implementation note:** Role assignment and role profile sync for board members is handled explicitly by `BoardManager.handle_board_member_additions/changes/deletions` (called from `Chapter.before_save`). Child table doc_events never fire for rows managed via parent save, so those hooks were intentionally removed.

#### Role Profile Automation

Managed by `chapter_role_profile_manager.py` and `chapter_role_profile_hooks.py`:

**Configuration Modes:**

1. **Default Profile**: Single role profile for all board members
2. **Role-Specific Profiles**: Different profiles based on board position
3. **Hybrid Approach**: Default with role-specific overrides

### Permission and Security Architecture

#### Permission Queries (from `hooks/permissions.py`)

- **Chapter**: `get_chapter_permission_query_conditions` + `has_chapter_permission`
- **Chapter Member**: `get_chapter_member_permission_query`
- **Team**: `get_team_permission_query_conditions`

#### Chapter Security Services

- `chapter_permission_service.py` -- Enforces chapter-level permission rules
- `chapter_board_permissions.py` -- Board-specific permission logic
- `chapter_security.py` -- Security enforcement for chapter operations

### Document Event Hooks

From `hooks/doc_events.py`:

**Chapter:**
- `after_save`: Invalidate chapter lookup cache (`optimized_chapter_lookup`)
- `on_update`: Invalidate chapter profile cache

**Chapter Member:**
- `after_save`: Performance cache update
- `on_trash`: Performance cache update

**Chapter Role:**
- `on_update`: Chapter role event handler

**Member `on_update`:** Triggers `chapter_role_events.on_member_on_update`

There is no Volunteer-side board-role handler. `on_volunteer_on_update` was removed in
#688: it had been registered under the non-existent doctype `Verenigingen Volunteer` and
never fired, and `BoardManager.handle_board_member_additions/changes/deletions` owns board
role assignment and withdrawal.

### Web Presence and Public Interface

- Public chapter information pages with route management
- Meetup.com embed integration via `meetup_embed_html` field
- Published/unpublished toggle for public visibility
- Guest access configuration for public chapter information

### Chapter Provisioning

`chapter_provisioning_service.py` handles new chapter setup:

- Creates chapter with initial configuration
- Sets up cost center via `chapter_finance_service.py`
- Configures board role profiles
- Syncs with ERPNext Department via `department_sync_service.py`

### Financial Integration

#### Cost Center Alignment

Managed by `chapter_finance_service.py`:

- Dedicated cost center per chapter (created via `create_chapter_cost_center()`)
- Uses `db_set()` to persist cost_center -- callers must `reload()` to see updated value

#### Department Sync

`department_sync_service.py` synchronizes chapter structure with ERPNext Department hierarchy.

### Data Model Relationships

```
Region (1) <-> (n) Chapter
Chapter (1) <-> (n) Chapter Member
Member (1) <-> (n) Chapter Member
Chapter (1) <-> (n) Chapter Board Member
Chapter (1) <-> (1) Cost Center
User (1) <-> (n) Chapter Board Member
```

## Key File Locations

- **Chapter DocType**: `verenigingen/doctype/chapter/`
- **Chapter services**: `services/chapter/` (16+ modules)
- **Member chapter service**: `services/member/chapter/chapter_management_service.py`
- **Hooks**: `hooks/doc_events.py` (Chapter, Chapter Member, Chapter Role sections)
- **Permissions**: `hooks/permissions.py` (Chapter, Chapter Member, Team)
