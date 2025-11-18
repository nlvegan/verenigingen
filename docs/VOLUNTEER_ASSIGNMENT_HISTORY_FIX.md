# Volunteer Assignment History Idempotency Fix

## Problem Summary

The volunteer assignment history tracking system had three critical bugs that caused duplicate entries:

### 1. **Incomplete Idempotency Check**
**File:** `verenigingen/utils/assignment_history_manager.py`
**Method:** `add_assignment_history()`
**Line:** 57

The idempotency check only looked for **Active** assignments:
```python
if (assignment.status == "Active" and ...)
```

**Problem:** If an assignment was completed and then re-added (e.g., when rapidly saving a chapter document), a duplicate "Active" assignment would be created because the original was now "Completed".

### 2. **Reconstruction Logic Created Duplicates**
**File:** `verenigingen/utils/assignment_history_manager.py`
**Method:** `complete_assignment_history()`
**Lines:** 234-252

When no active assignment was found, the method would create a new "Completed" entry as a fallback. This could create duplicates if:
- The assignment was already completed
- The method was called again (e.g., multiple event triggers)
- It couldn't find an active assignment, so created a new completed one

### 3. **Multiple Event Triggers**
While the event system itself works correctly, rapid document saves or concurrent operations could trigger the sync process multiple times before the previous operation completed.

## Solution Implemented

### Fix 1: Enhanced Idempotency Check

**Changed:** The `add_assignment_history()` method now checks for **both Active and Completed** assignments with the same key:

```python
for assignment in volunteer.assignment_history or []:
    if (
        assignment.reference_doctype == reference_doctype
        and assignment.reference_name == reference_name
        and assignment.role == role
        and str(assignment.start_date) == str(start_date)
    ):
        # Assignment already exists - check status
        if assignment.status == "Active":
            # Already active - skip
            return True
        elif assignment.status == "Completed":
            # Reactivate instead of creating duplicate
            assignment.status = "Active"
            assignment.end_date = None
            # Save and return
```

**Benefit:** Prevents duplicates and properly handles the case where someone is removed and re-added to the same position.

### Fix 2: Duplicate Check Before Reconstruction

**Changed:** The `complete_assignment_history()` method now checks if a completed assignment already exists before creating a new one:

```python
# Before reconstructing, check if a completed assignment already exists
existing_completed = None
for assignment in volunteer.assignment_history or []:
    if (
        assignment.reference_doctype == reference_doctype
        and assignment.reference_name == reference_name
        and assignment.role == role
        and str(assignment.start_date) == str(start_date)
        and assignment.status == "Completed"
    ):
        existing_completed = assignment
        break

if existing_completed:
    # Already completed - just update end_date if needed or return early
    if str(existing_completed.end_date) != str(end_date):
        existing_completed.end_date = end_date
    else:
        return True  # Nothing to do
else:
    # Create new completed entry (reconstruction)
    volunteer.append("assignment_history", {...})
```

**Benefit:** Prevents duplicate completed entries from being created during reconstruction.

### Fix 3: Improved Logging

All operations now log their actions with appropriate levels:
- **Info:** Normal operations (assignment added, completed, reactivated)
- **Warning:** Unusual but handled situations (reactivating completed assignment)
- **Error:** Failures that need attention

## Cleanup Utility

A cleanup utility has been created to find and remove existing duplicate assignments:

**File:** `verenigingen/utils/cleanup_duplicate_assignments.py`

### Usage

#### Check for Duplicates
```python
from verenigingen.utils.cleanup_duplicate_assignments import find_duplicate_assignments

# Check all volunteers
duplicates = find_duplicate_assignments()

# Check specific volunteer
duplicates = find_duplicate_assignments('Assoc-Vol-2025-10-101174')
```

#### Clean Duplicates (Dry Run)
```python
from verenigingen.utils.cleanup_duplicate_assignments import clean_duplicate_assignments

# Dry run first (shows what would be done)
clean_duplicate_assignments('Assoc-Vol-2025-10-101174', dry_run=True)
```

#### Clean Duplicates (For Real)
```python
# Actually remove duplicates
clean_duplicate_assignments('Assoc-Vol-2025-10-101174', dry_run=False)
```

#### Clean All Duplicates
```python
from verenigingen.utils.cleanup_duplicate_assignments import cleanup_all_duplicates

# Dry run on all volunteers
cleanup_all_duplicates(dry_run=True)

# Actually clean all
cleanup_all_duplicates(dry_run=False)
```

### Manual Cleanup (SQL)

If you need to manually remove duplicates from the database:

```sql
-- Find duplicates for a specific volunteer
SELECT
    assignment_type,
    reference_name,
    role,
    start_date,
    end_date,
    status,
    idx,
    COUNT(*) as count
FROM `tabVolunteer Assignment`
WHERE parent = 'Assoc-Vol-2025-10-101174'
GROUP BY assignment_type, reference_name, role, start_date, end_date, status
HAVING count > 1;

-- Remove duplicate (keep idx=1, remove idx=2)
DELETE FROM `tabVolunteer Assignment`
WHERE parent = 'Assoc-Vol-2025-10-101174'
  AND idx = 2;
```

## Testing

### Test Scenario 1: Add Board Member
1. Create a chapter board member assignment
2. Verify single "Active" assignment is created in volunteer history
3. Save chapter multiple times rapidly
4. Verify no duplicate assignments are created

### Test Scenario 2: Remove Board Member
1. Remove a board member (set `is_active = 0` or delete row)
2. Verify assignment is marked "Completed" with correct end_date
3. Trigger the operation multiple times
4. Verify no duplicate "Completed" entries are created

### Test Scenario 3: Re-add Board Member
1. Remove a board member (marks assignment "Completed")
2. Re-add the same person to the same position with same start_date
3. Verify the existing "Completed" assignment is reactivated (status changed to "Active", end_date cleared)
4. Verify no duplicate assignment is created

### Test Scenario 4: Concurrent Operations
1. Trigger multiple chapter saves in quick succession
2. Verify assignment history remains consistent
3. No duplicate entries should be created

## Event Flow

The complete flow from board member change to assignment history update:

```
1. Chapter.on_update()
   ↓
2. Chapter._emit_chapter_change_events(old_doc)
   ↓
3. Chapter._detect_and_emit_board_changes(old_doc)
   ↓
4. emit_chapter_board_changed(chapter_name, event_data)
   ↓
5. Background: handle_volunteer_sync(event_name, event_data)
   ↓
6. chapter.volunteer_integration_manager.sync_board_members_with_volunteer_system()
   ↓
7. For active: add_volunteer_assignment_history()
   For inactive: update_volunteer_assignment_history()
   ↓
8. AssignmentHistoryManager.add_assignment_history() or
   AssignmentHistoryManager.complete_assignment_history()
```

## Files Modified

1. **verenigingen/utils/assignment_history_manager.py**
   - Enhanced `add_assignment_history()` with reactivation logic (lines 50-96)
   - Enhanced `complete_assignment_history()` with duplicate check (lines 234-282)
   - Improved logging throughout

2. **verenigingen/utils/cleanup_duplicate_assignments.py** (NEW)
   - Complete cleanup utility for finding and removing duplicates
   - Supports dry-run mode
   - Batch processing for all volunteers

3. **docs/VOLUNTEER_ASSIGNMENT_HISTORY_FIX.md** (NEW)
   - This documentation

## Affected Volunteer Record

The issue was discovered in **Assoc-Vol-2025-10-101174**, which had two identical completed assignments:

**Before Fix:**
| Type | Reference | Role | Start | End | Status | idx |
|------|-----------|------|-------|-----|--------|-----|
| Board Position | Utrecht | Chair | 2025-11-02 | 2025-11-18 | Completed | 1 |
| Board Position | Utrecht | Chair | 2025-11-02 | 2025-11-18 | Completed | 2 |

**After Fix:**
| Type | Reference | Role | Start | End | Status | idx |
|------|-----------|------|-------|-----|--------|-----|
| Board Position | Utrecht | Chair | 2025-11-02 | 2025-11-18 | Completed | 1 |

## Prevention

The fixes prevent future duplicates through:

1. **Comprehensive Idempotency:** Checks both Active and Completed status
2. **Reactivation Logic:** Reuses existing assignments instead of creating duplicates
3. **Reconstruction Guards:** Checks for existing completed assignments before creating new ones
4. **Recursion Guards:** Existing `_updating_assignment_history` flag prevents infinite loops
5. **Better Logging:** Clear visibility into what operations are happening and why

## Monitoring

To monitor for future issues:

1. **Check error logs** for "Assignment History" errors:
   ```python
   frappe.get_all("Error Log",
       filters={"error": ["like", "%Assignment History%"]},
       order_by="creation desc",
       limit=20
   )
   ```

2. **Run duplicate check periodically:**
   ```python
   from verenigingen.utils.cleanup_duplicate_assignments import find_duplicate_assignments
   duplicates = find_duplicate_assignments()
   if duplicates:
       print(f"Found duplicates in {len(duplicates)} volunteers")
   ```

3. **Monitor background jobs** for volunteer sync failures:
   ```bash
   bench --site dev.veganisme.net show-jobs
   ```

## Rollback (If Needed)

If issues occur, the fix can be rolled back by:

1. Reverting changes to `assignment_history_manager.py`
2. Manually cleaning up any problematic assignments using the SQL queries above
3. The cleanup utility can remain as it's a standalone tool

## Author

Fix implemented: 2025-11-18
Files affected: 2
Lines changed: ~150
Testing status: Manual testing on dev.veganisme.net

## Related Issues

- Original issue: Duplicate assignments in Assoc-Vol-2025-10-101174
- Root cause: Incomplete idempotency protection
- Event triggering: Working as intended, but needed better duplicate protection
