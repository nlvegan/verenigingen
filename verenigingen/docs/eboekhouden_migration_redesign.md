# E-Boekhouden Migration Status Redesign

## Current Issues

1. **Post-Migration buttons only appear in Draft status** - illogical since they should be used after migration
2. **Must reset to Draft to do anything** - creates unnecessary steps
3. **Status doesn't reflect actual capabilities** - you can run migrations multiple times regardless of status
4. **Completed status is a dead-end** - can only view summary, must reset to Draft for any action

## Proposed Redesign

### Option 1: Remove Status Field (Simplest)

Remove the `migration_status` field entirely and show buttons based on what has been done:

```javascript
// Always show these buttons
- Test Connection
- Full Migration
- Migration by Date Range

// Show after any successful migration
- View Last Migration Summary
- Map Account Types (Post-Migration)
- Fix Receivable/Payable Accounts
- Export Migration Report

// Show if migration is running (check background job)
- View Progress
- Cancel Migration
```

### Option 2: Activity-Based Status (Recommended)

Keep status but make it reflect what has been done, not restrict what can be done:

#### Status Values:
- **New** - Nothing migrated yet
- **Migrated** - At least one successful migration completed
- **Migration Running** - Currently processing (temporary state)

#### Button Display Logic:

**Always Available:**
```javascript
// Core Actions (always visible)
- Test Connection
- Full Migration
- Custom Migration (date range)

// Post-Migration Tools (visible if status === 'Migrated')
- Map Account Types
- Fix Receivable/Payable Accounts
- Clean Duplicate Data
- View Migration History
```

**Context-Sensitive:**
```javascript
// If migration running
- View Progress
- Cancel Migration

// If has migration history
- View Last Summary
- Export All Results
```

### Option 3: Workflow States

Use a proper workflow with meaningful states:

1. **Configuration** - Setting up connection
2. **Ready** - Connection tested, ready to migrate
3. **Processing** - Migration in progress
4. **Review** - Migration complete, review results
5. **Finalized** - Post-migration tasks complete

But this might be overkill for a migration tool.

## Recommended Implementation

### 1. Update Status Field Logic

```javascript
// In e_boekhouden_migration.js
refresh: function(frm) {
    // Always show core buttons
    show_core_buttons(frm);

    // Show post-migration tools if any migration completed
    if (has_migration_history(frm)) {
        show_post_migration_buttons(frm);
    }

    // Show progress if migration running
    if (is_migration_running(frm)) {
        show_progress_ui(frm);
    }
}

function show_core_buttons(frm) {
    // Test Connection - always available
    frm.add_custom_button(__('Test Connection'), ...);

    // Migration options - always available
    frm.add_custom_button(__('Full Migration'), ..., __('Migration'));
    frm.add_custom_button(__('Custom Date Range'), ..., __('Migration'));
}

function show_post_migration_buttons(frm) {
    // Post-migration tools
    frm.add_custom_button(__('Map Account Types'), ..., __('Post-Migration'));
    frm.add_custom_button(__('Fix Receivables/Payables'), ..., __('Post-Migration'));
    frm.add_custom_button(__('View History'), ..., __('Post-Migration'));
}
```

### 2. Add Migration History

Track each migration run:
```javascript
// Add child table: migration_runs
{
    "fieldname": "migration_runs",
    "fieldtype": "Table",
    "label": "Migration History",
    "options": "E-Boekhouden Migration Run"
}

// Child doctype fields:
- run_date
- date_from
- date_to
- records_created
- records_skipped
- records_failed
- run_type (Full/Custom)
- summary
```

### 3. Simplify Status

```python
def update_status(self):
    """Update status based on migration history"""
    if self.is_migration_running():
        self.migration_status = "Processing"
    elif self.has_successful_migrations():
        self.migration_status = "Migrated"
    else:
        self.migration_status = "New"
```

## Benefits

1. **Logical flow** - Post-migration tools appear after migration
2. **No dead ends** - Can always perform any valid action
3. **Clear history** - See all migration attempts
4. **Better UX** - Users understand what they can do and when
5. **Idempotent** - Can run migrations multiple times safely

## Migration Path

1. Add new fields while keeping old status field
2. Update JS to use new logic
3. Migrate existing records
4. Remove old status field in next version
