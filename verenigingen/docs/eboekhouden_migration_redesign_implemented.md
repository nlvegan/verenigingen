# E-Boekhouden Migration Status Redesign - Implementation

## Changes Implemented

### 1. JavaScript UI Logic (e_boekhouden_migration.js)

#### Button Display Logic
- **Core Migration Buttons**: Always shown when docstatus = 0 and not in progress
  - Test Connection
  - Preview Migration
  - Start Migration
  - Full Migration

- **Post-Migration Buttons**: Now shown based on capabilities rather than status
  ```javascript
  if (has_migrations || frm.doc.migration_status === 'Completed') {
      // Show Post-Migration tools
  }
  ```
  - Map Account Types
  - Fix Receivables/Payables
  - View Migration History

#### Status Help Text
Updated to be more informative and context-aware:
- Shows different messages based on migration history
- Guides users on available actions
- Explains Post-Migration tools when available

### 2. Utility Module (eboekhouden_migration_status.py)

Created new module with helper functions:

#### get_migration_capabilities()
Returns capability flags:
- `can_migrate`: Whether new migrations can be started
- `can_post_process`: Whether post-migration tools should be shown
- `has_history`: Whether migration history exists
- `is_running`: Whether a migration is currently in progress
- `can_reset`: Whether the migration can be reset to draft

#### check_running_migrations()
Checks for any migrations currently in progress across the system

#### update_migration_status()
Handles status transitions with validation

#### get_migration_summary_stats()
Provides overall migration statistics

### 3. Benefits of New Design

1. **Logical Flow**: Post-migration tools appear when they're needed (after migration)
2. **No Dead Ends**: Users can always perform valid actions
3. **Clear Guidance**: Help text adapts to current state
4. **Better UX**: Users understand what they can do at each stage
5. **Flexibility**: Can run multiple migrations without resetting

## How It Works Now

### Initial State (No Migrations)
- Shows all migration options
- Help text explains the process
- No Post-Migration tools shown

### After First Migration
- Migration options remain available
- Post-Migration tools become visible
- Help text explains new capabilities
- Can run additional migrations without resetting

### Failed Migration
- Shows reset button
- Explains the failure
- Allows retry after reset

### In Progress
- Shows progress indicator
- Auto-refreshes every 5 seconds
- Prevents concurrent operations

## Testing the New Design

1. **Test Initial State**:
   ```bash
   # Create new migration document
   # Verify only core buttons appear
   ```

2. **Test Post-Migration State**:
   ```bash
   # Run a migration
   # Verify Post-Migration buttons appear
   # Verify can still run new migrations
   ```

3. **Test Capability Detection**:
   ```python
   from verenigingen.utils.eboekhouden_migration_status import get_migration_capabilities
   caps = get_migration_capabilities("EBMIG-2025-00001")
   print(caps)
   ```

## Future Enhancements

1. **Migration History Table**: Track each migration run as a child table
2. **Batch Operations**: Run multiple date ranges in sequence
3. **Scheduled Migrations**: Allow scheduled periodic imports
4. **Migration Templates**: Save common migration configurations

## Migration Path for Existing Data

Existing migrations will automatically work with the new UI:
- Records with `imported_records > 0` will show Post-Migration tools
- Status field remains but doesn't restrict functionality
- No data migration required
