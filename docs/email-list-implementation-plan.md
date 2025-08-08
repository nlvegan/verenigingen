# Email List System Implementation Plan
## Hierarchical Auto-Populated Email Groups for Verenigingen

### Executive Summary
This document outlines the implementation plan for integrating Frappe's Email Group and Newsletter modules with the Verenigingen member management system. The goal is to create a hierarchical, auto-populated email list system that enables targeted communication at organizational, regional, and chapter levels.

## 1. System Architecture

### 1.1 High-Level Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                     Newsletter Module                         │
│                  (Frappe Core Component)                      │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│              Email Group Management Layer                     │
│         (Custom Integration - verenigingen.email)             │
├──────────────────────────────────────────────────────────────┤
│  • Sync Manager        • Hierarchy Manager                   │
│  • Preference Handler  • Template Integration                 │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│                    Data Sources                               │
├─────────────┬──────────────┬──────────────┬─────────────────┤
│   Member    │   Chapter    │   Volunteer  │     Region      │
│   DocType   │   DocType    │   DocType    │    DocType      │
└─────────────┴──────────────┴──────────────┴─────────────────┘
```

### 1.2 Email Group Hierarchy Structure
```
verenigingen-all-members [Master Group]
├── verenigingen-all-active
├── verenigingen-all-volunteers
├── verenigingen-all-board
└── verenigingen-regions
    └── region-[region_name]
        ├── region-[region_name]-members
        └── region-[region_name]-chapters
            └── chapter-[chapter_name]
                ├── chapter-[chapter_name]-members
                ├── chapter-[chapter_name]-board
                └── chapter-[chapter_name]-volunteers
```

### 1.3 Component Responsibilities

#### Email Group Sync Manager (`email_group_sync_manager.py`)
- Maintains synchronization between Member/Chapter data and Email Groups
- Handles member status changes (active, inactive, terminated)
- Manages unsubscribe preferences
- Provides sync status reporting

#### Hierarchy Manager (`email_hierarchy_manager.py`)
- Creates and maintains hierarchical Email Group structure
- Handles parent-child relationships between groups
- Manages group creation on Chapter/Region creation
- Handles group archival on Chapter/Region deletion

#### Preference Handler (`email_preference_handler.py`)
- Manages member communication preferences
- Handles opt-in/opt-out at different hierarchy levels
- Integrates with unsubscribe mechanism
- Provides preference UI components

#### Template Integration (`newsletter_template_manager.py`)
- Bridges existing email templates with Newsletter module
- Provides template conversion utilities
- Maintains template versioning
- Handles dynamic content injection

## 2. Data Model Changes

### 2.1 Member DocType Extensions
```python
# New fields for Member DocType
{
    "fieldname": "email_preferences_section",
    "fieldtype": "Section Break",
    "label": "Email Preferences"
},
{
    "fieldname": "newsletter_opt_in",
    "fieldtype": "Check",
    "label": "Subscribe to Newsletters",
    "default": 1,
    "description": "Receive organizational newsletters and updates"
},
{
    "fieldname": "chapter_communications",
    "fieldtype": "Check",
    "label": "Chapter Communications",
    "default": 1,
    "description": "Receive chapter-specific communications"
},
{
    "fieldname": "volunteer_communications",
    "fieldtype": "Check",
    "label": "Volunteer Communications",
    "default": 1,
    "description": "Receive volunteer-related communications (if applicable)"
},
{
    "fieldname": "communication_frequency",
    "fieldtype": "Select",
    "label": "Preferred Frequency",
    "options": "Immediate\nDaily Digest\nWeekly Digest\nMonthly",
    "default": "Immediate"
},
{
    "fieldname": "email_group_memberships",
    "fieldtype": "Table",
    "label": "Email Group Memberships",
    "options": "Member Email Group",
    "read_only": 1,
    "description": "Automatically managed email group memberships"
}
```

### 2.2 New Child DocType: Member Email Group
```python
# Child table to track member's email group memberships
{
    "doctype": "DocType",
    "name": "Member Email Group",
    "module": "Verenigingen",
    "istable": 1,
    "fields": [
        {
            "fieldname": "email_group",
            "fieldtype": "Link",
            "label": "Email Group",
            "options": "Email Group",
            "in_list_view": 1,
            "reqd": 1
        },
        {
            "fieldname": "subscription_date",
            "fieldtype": "Datetime",
            "label": "Subscribed On",
            "in_list_view": 1
        },
        {
            "fieldname": "subscription_type",
            "fieldtype": "Select",
            "label": "Type",
            "options": "Automatic\nManual\nImported",
            "default": "Automatic",
            "in_list_view": 1
        },
        {
            "fieldname": "is_active",
            "fieldtype": "Check",
            "label": "Active",
            "default": 1,
            "in_list_view": 1
        }
    ]
}
```

### 2.3 Custom Fields for Email Group
```python
# Extend Email Group DocType with custom fields
{
    "fieldname": "verenigingen_section",
    "fieldtype": "Section Break",
    "label": "Verenigingen Settings",
    "insert_after": "total_subscribers"
},
{
    "fieldname": "group_type",
    "fieldtype": "Select",
    "label": "Group Type",
    "options": "\nOrganization\nRegion\nChapter\nRole-Based\nCustom",
    "insert_after": "verenigingen_section"
},
{
    "fieldname": "auto_populate",
    "fieldtype": "Check",
    "label": "Auto-Populate",
    "default": 0,
    "insert_after": "group_type",
    "description": "Automatically manage membership based on rules"
},
{
    "fieldname": "sync_rules",
    "fieldtype": "JSON",
    "label": "Sync Rules",
    "insert_after": "auto_populate",
    "depends_on": "eval:doc.auto_populate==1",
    "description": "JSON configuration for auto-population rules"
},
{
    "fieldname": "parent_group",
    "fieldtype": "Link",
    "label": "Parent Group",
    "options": "Email Group",
    "insert_after": "sync_rules"
},
{
    "fieldname": "last_sync",
    "fieldtype": "Datetime",
    "label": "Last Synchronized",
    "read_only": 1,
    "insert_after": "parent_group"
}
```

## 3. Implementation Modules

### 3.1 Core Sync Engine
```python
# verenigingen/email/email_group_sync_manager.py

class EmailGroupSyncManager:
    """Manages synchronization between member data and email groups"""

    def __init__(self):
        self.sync_log = []
        self.error_count = 0

    def sync_all_groups(self) -> Dict:
        """Main sync orchestrator"""
        # 1. Sync organizational groups
        # 2. Sync regional groups
        # 3. Sync chapter groups
        # 4. Sync role-based groups
        # 5. Handle removals/unsubscribes
        # 6. Generate sync report
        pass

    def sync_chapter_members(self, chapter_name: str) -> Dict:
        """Sync members of a specific chapter"""
        pass

    def sync_volunteer_groups(self) -> Dict:
        """Sync all volunteer email groups"""
        pass

    def handle_member_status_change(self, member_name: str, old_status: str, new_status: str):
        """React to member status changes"""
        pass

    def handle_unsubscribe(self, email: str, group_name: str):
        """Process unsubscribe requests"""
        pass

    def get_sync_status(self) -> Dict:
        """Return current sync status and statistics"""
        pass
```

### 3.2 Hierarchy Management
```python
# verenigingen/email/email_hierarchy_manager.py

class EmailHierarchyManager:
    """Manages hierarchical email group structure"""

    def create_chapter_groups(self, chapter_name: str, region: str) -> List[str]:
        """Create all email groups for a new chapter"""
        groups_created = []

        # Create base chapter groups
        base_group = self.create_email_group(
            name=f"chapter-{chapter_name}",
            title=f"{chapter_name} Chapter - All",
            group_type="Chapter"
        )

        # Create sub-groups
        self.create_email_group(
            name=f"chapter-{chapter_name}-members",
            title=f"{chapter_name} Chapter - Members",
            parent_group=base_group
        )

        self.create_email_group(
            name=f"chapter-{chapter_name}-board",
            title=f"{chapter_name} Chapter - Board",
            parent_group=base_group
        )

        # Link to regional hierarchy
        self.link_to_region(base_group, region)

        return groups_created

    def archive_chapter_groups(self, chapter_name: str):
        """Archive groups when chapter is deactivated"""
        pass

    def get_hierarchy_tree(self) -> Dict:
        """Return complete hierarchy structure"""
        pass
```

### 3.3 Preference Management
```python
# verenigingen/email/email_preference_handler.py

class EmailPreferenceHandler:
    """Manages member email preferences"""

    def get_member_preferences(self, member_name: str) -> Dict:
        """Get all email preferences for a member"""
        pass

    def update_preferences(self, member_name: str, preferences: Dict) -> bool:
        """Update member preferences"""
        pass

    def get_eligible_recipients(self, group_name: str, respect_preferences: bool = True) -> List[str]:
        """Get list of eligible recipients for a group"""
        pass

    def apply_frequency_filter(self, recipients: List[str], communication_type: str) -> List[str]:
        """Filter recipients based on frequency preferences"""
        pass
```

## 4. Integration Points

### 4.1 Hooks Configuration
```python
# hooks.py additions
doc_events = {
    "Member": {
        "after_insert": "verenigingen.email.hooks.after_insert_member",
        "on_update": "verenigingen.email.hooks.on_update_member",
        "on_trash": "verenigingen.email.hooks.on_trash_member"
    },
    "Chapter": {
        "after_insert": "verenigingen.email.hooks.after_insert_chapter",
        "on_trash": "verenigingen.email.hooks.on_trash_chapter"
    },
    "Volunteer": {
        "after_insert": "verenigingen.email.hooks.after_insert_volunteer",
        "on_update": "verenigingen.email.hooks.on_update_volunteer"
    },
    "Chapter Board Member": {
        "after_insert": "verenigingen.email.hooks.sync_board_member_groups",
        "on_trash": "verenigingen.email.hooks.sync_board_member_groups"
    }
}

scheduler_events = {
    "daily": [
        "verenigingen.email.tasks.daily_email_group_sync"
    ],
    "hourly": [
        "verenigingen.email.tasks.process_pending_syncs"
    ]
}
```

### 4.2 API Endpoints
```python
# New whitelisted API functions

@frappe.whitelist()
def get_chapter_email_groups(chapter_name: str) -> List[Dict]:
    """Get all email groups for a chapter"""
    pass

@frappe.whitelist()
def trigger_manual_sync(group_name: str = None) -> Dict:
    """Manually trigger email group sync"""
    pass

@frappe.whitelist()
def get_member_email_preferences(member_name: str = None) -> Dict:
    """Get email preferences for current user or specified member"""
    pass

@frappe.whitelist()
def update_email_preferences(preferences: Dict) -> bool:
    """Update email preferences for current user"""
    pass

@frappe.whitelist()
def preview_newsletter_recipients(newsletter_name: str) -> Dict:
    """Preview recipients for a newsletter"""
    pass
```

### 4.3 UI Components
```javascript
// Client-side integration for Chapter form
frappe.ui.form.on('Chapter', {
    refresh: function(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__('View Email Groups'), function() {
                frappe.verenigingen.email.show_chapter_groups(frm.doc.name);
            }, __('Email'));

            frm.add_custom_button(__('Sync Email Groups'), function() {
                frappe.verenigingen.email.sync_chapter_groups(frm.doc.name);
            }, __('Email'));
        }
    }
});

// Newsletter enhancement
frappe.ui.form.on('Newsletter', {
    onload: function(frm) {
        // Add quick filters for verenigingen groups
        frm.set_query('email_group', 'email_group', function() {
            return {
                filters: {
                    'auto_populate': 1
                }
            };
        });
    }
});
```

## 5. Migration Strategy

### 5.1 Phase 1: Foundation (Week 1-2)
1. Create new DocTypes and fields
2. Implement core sync engine
3. Set up basic hierarchy manager
4. Create initial test groups

### 5.2 Phase 2: Integration (Week 3-4)
1. Implement hooks for auto-sync
2. Create scheduled jobs
3. Build preference management
4. Integrate with existing CommunicationManager

### 5.3 Phase 3: Migration (Week 5)
1. Create initial Email Groups structure
2. Import existing member emails
3. Set default preferences
4. Run initial full sync

### 5.4 Phase 4: Enhancement (Week 6)
1. Add UI components
2. Create management reports
3. Implement advanced filtering
4. Performance optimization

## 6. Testing Strategy

### 6.1 Unit Tests
```python
# Test coverage requirements
- EmailGroupSyncManager: 90% coverage
- EmailHierarchyManager: 90% coverage
- EmailPreferenceHandler: 95% coverage
- Hook functions: 85% coverage
```

### 6.2 Integration Tests
```python
class TestEmailGroupIntegration(EnhancedTestCase):
    def test_chapter_creation_creates_groups(self):
        """Test that creating a chapter creates appropriate email groups"""
        pass

    def test_member_status_change_updates_groups(self):
        """Test member status changes reflect in email groups"""
        pass

    def test_preference_changes_affect_membership(self):
        """Test preference changes update group membership"""
        pass

    def test_hierarchy_navigation(self):
        """Test traversing email group hierarchy"""
        pass
```

### 6.3 Performance Tests
- Sync 10,000 members: < 60 seconds
- Create chapter with groups: < 2 seconds
- Update preferences: < 500ms
- Get eligible recipients (1000 members): < 1 second

## 7. Security Considerations

### 7.1 Permission Model
```python
# Email Group permissions
- Newsletter Manager: Full access to all groups
- Chapter Admin: Manage chapter-specific groups
- Member: View own preferences, update own preferences
```

### 7.2 Data Protection
- PII handling in email lists
- GDPR compliance for unsubscribe
- Audit trail for preference changes
- Secure API endpoints with rate limiting

## 8. Monitoring and Maintenance

### 8.1 Monitoring Metrics
- Sync success rate
- Average sync duration
- Group membership accuracy
- Unsubscribe rate
- Delivery success rate

### 8.2 Maintenance Tasks
- Weekly sync validation
- Monthly orphaned record cleanup
- Quarterly performance review
- Annual architecture review

## 9. Rollback Plan

### 9.1 Rollback Triggers
- Sync failure rate > 10%
- Performance degradation > 50%
- Data integrity issues
- Critical security vulnerability

### 9.2 Rollback Steps
1. Disable scheduler jobs
2. Unhook doc_events
3. Restore CommunicationManager to direct mode
4. Archive Email Groups
5. Remove custom fields

## 10. Success Criteria

### 10.1 Functional Success
- ✓ All chapters have auto-populated email groups
- ✓ Member changes reflect within 24 hours
- ✓ Preferences are respected in all communications
- ✓ Newsletter module fully integrated

### 10.2 Performance Success
- ✓ Daily sync completes in < 5 minutes
- ✓ No impact on Member/Chapter operations
- ✓ Newsletter sending performance maintained
- ✓ UI remains responsive

### 10.3 User Success
- ✓ Chapter admins can easily send targeted emails
- ✓ Members can manage their preferences
- ✓ Unsubscribe rate < 5%
- ✓ Positive user feedback

## Appendix A: Sync Rules Configuration

```json
{
  "chapter-members": {
    "source": "Chapter Member",
    "filters": {
      "enabled": true,
      "member.status": "Active"
    },
    "email_field": "member.email",
    "update_frequency": "daily"
  },
  "all-volunteers": {
    "source": "Volunteer",
    "filters": {
      "status": "Active"
    },
    "email_field": "member.email",
    "update_frequency": "daily"
  }
}
```

## Appendix B: Database Schema Changes

```sql
-- Custom fields for tabMember
ALTER TABLE `tabMember` ADD COLUMN `newsletter_opt_in` INT(1) DEFAULT 1;
ALTER TABLE `tabMember` ADD COLUMN `chapter_communications` INT(1) DEFAULT 1;
ALTER TABLE `tabMember` ADD COLUMN `volunteer_communications` INT(1) DEFAULT 1;
ALTER TABLE `tabMember` ADD COLUMN `communication_frequency` VARCHAR(140);

-- Index for performance
CREATE INDEX idx_member_email_prefs ON `tabMember` (email, newsletter_opt_in, status);
CREATE INDEX idx_email_group_sync ON `tabEmail Group` (auto_populate, last_sync);
```
