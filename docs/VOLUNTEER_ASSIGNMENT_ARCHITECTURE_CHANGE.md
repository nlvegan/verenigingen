# Volunteer Assignment History - Architecture Change

**Date:** 2025-11-18
**Change Type:** Architecture simplification
**Impact:** Removes duplicate processing, prevents race conditions

## Summary

Removed direct volunteer sync from `Chapter.after_save()` to rely exclusively on event-driven architecture. This eliminates the race condition that was causing duplicate assignment history entries.

## Problem: Dual Processing Paths

The system had **two paths** that both triggered volunteer assignment sync:

### Path 1: Direct Sync (REMOVED)
```python
# chapter.py - after_save() [Lines 173-182]
if self.has_value_changed("board_members"):
    # Direct synchronous call
    self.volunteer_integration_manager.sync_board_members_with_volunteer_system()
```

### Path 2: Event-Driven Sync (KEPT)
```python
# chapter.py - on_update() [Line 204]
self._emit_chapter_change_events(old_doc)
    ↓
# Emits events → Background jobs → Same sync function
```

## The Race Condition

When a chapter was saved:

1. **`after_save()`** runs → direct sync (synchronous)
2. **`on_update()`** runs → emits event → background job → sync again (asynchronous)

This created a race condition where:
- Both paths might read volunteer data simultaneously
- Both might create "Active" assignments
- Both assignments would later be marked "Completed"
- Result: **Duplicate entries**

The recursion guard (`_syncing_board_members`) only prevented recursive calls within the same request, not across different processes.

## Solution: Event-Driven Only

**File Changed:** `verenigingen/verenigingen/doctype/chapter/chapter.py`

**Lines 173-175:** Removed direct sync, added explanation comment

```python
def after_save(self):
    """After save hook - streamlined with safe operations"""
    # Handle cost center renaming if chapter name changed
    if self.has_value_changed("name"):
        self._safe_manager_operation(
            "cost_center_rename",
            lambda: self._update_chapter_cost_center_name(),
        )

    # NOTE: Volunteer sync removed from here (2025-11-18)
    # Now handled exclusively via event-driven architecture in on_update()
    # This prevents duplicate processing and race conditions
```

## Event-Driven Architecture Details

### Event Emission (chapter.py)

```python
def on_update(self):
    """On update hook with event emission for background processing"""
    if old_doc:
        self._emit_chapter_change_events(old_doc)

def _emit_chapter_change_events(self, old_doc):
    """Emit events for significant chapter changes"""
    self._detect_and_emit_board_changes(old_doc)  # ← Detects changes

def _detect_and_emit_board_changes(self, old_doc):
    """Detect and emit board member changes"""
    # Emits separate event for each volunteer change
    for volunteer, role in new_board - old_board:
        emit_chapter_board_changed(
            self.name,
            {
                "volunteer": volunteer,
                "action": "added",  # or "removed", "role_changed"
                "role": role,
                ...
            },
        )
```

### Event Processing (chapter_events.py)

```python
def emit_chapter_board_changed(chapter_name, board_data):
    """Emit event when chapter board composition changes"""
    event_data = {"chapter": chapter_name, **board_data}

    # Enqueue background job with deduplication
    frappe.enqueue(
        method="...handle_volunteer_sync",
        job_name=f"chapter_chapter_board_changed_{chapter_name}",
        dedupe=True,  # ← KEY: Deduplicates by chapter
        queue="short",
        ...
    )
```

### Deduplication Strategy

**Chapter-level deduplication** (not volunteer-level):

- **Job name:** `chapter_chapter_board_changed_{chapter_name}`
- **Effect:** Multiple events for same chapter → ONE job
- **Why it works:** `sync_board_members_with_volunteer_system()` syncs **ALL** board members, not just the one in the event

**Example:**
```
Save chapter with 3 board member changes:
  → Emit 3 events (volunteer A, B, C)
  → All have same job_name (chapter name only)
  → dedupe=True collapses to 1 job
  → 1 job runs, syncs ALL board members (A, B, C)
```

### Background Job Handler (chapter_subscribers.py)

```python
def handle_volunteer_sync(event_name, event_data, **kwargs):
    """Handle synchronization with volunteer system"""
    chapter_name = event_data.get("chapter")
    chapter = frappe.get_doc("Chapter", chapter_name)

    # Syncs ALL board members, not just the one in event_data
    chapter.volunteer_integration_manager.sync_board_members_with_volunteer_system()
```

### Full Sync Implementation (volunteer_integration_manager.py)

```python
def sync_board_members_with_volunteer_system(self) -> Dict:
    """Synchronize chapter board members with volunteer system"""

    # Process EACH board member (not just the one that changed)
    for board_member in self.chapter_doc.board_members or []:
        if board_member.is_active:
            # Ensure active assignment exists
            self.add_volunteer_assignment_history(...)
        else:
            # Ensure assignment is marked as completed
            self.update_volunteer_assignment_history(...)
```

## Benefits of Event-Driven Architecture

### 1. **No Duplicate Processing**
- ✅ Only ONE sync path exists
- ✅ No race conditions between sync and events
- ✅ Deduplication prevents redundant jobs

### 2. **Better Scalability**
- ✅ Background processing doesn't block user
- ✅ Jobs can be queued and batched
- ✅ Better resource utilization

### 3. **Separation of Concerns**
- ✅ Chapter save completes quickly
- ✅ Volunteer updates happen asynchronously
- ✅ Failures in volunteer sync don't break chapter save

### 4. **Built-in Retry**
- ✅ Background jobs can retry on failure
- ✅ Errors are logged separately
- ✅ Chapter operations not affected by volunteer system issues

## Combined with Idempotency Fixes

This architectural change works together with the idempotency fixes in `assignment_history_manager.py`:

1. **Architecture:** Prevents race conditions at the event level
2. **Idempotency:** Handles any remaining edge cases at the data level

**Defense in depth:**
- Event deduplication (first line of defense)
- Idempotency checks in `add_assignment_history()` (second line)
- Duplicate detection in `complete_assignment_history()` (third line)

## Migration Notes

### Immediate Effect
- No database changes required
- Existing assignment history unchanged
- Background jobs continue working

### Behavior Change
- **Before:** Sync happened synchronously during save
- **After:** Sync happens asynchronously via background job

### Timing
- Sync may take 1-2 seconds longer (background job delay)
- User doesn't wait for sync to complete
- Check background job queue if sync doesn't appear immediately

## Testing

### Manual Test

1. **Add board member:**
   ```python
   chapter = frappe.get_doc("Chapter", "Utrecht")
   chapter.append("board_members", {
       "volunteer": "Assoc-Vol-2025-10-101174",
       "chapter_role": "Secretary",
       "from_date": today(),
       "is_active": 1
   })
   chapter.save()
   ```

2. **Check events emitted:**
   - Should see log: `Emitting chapter_board_changed event`
   - Should NOT see direct sync log in save operation

3. **Check background jobs:**
   ```python
   frappe.get_all("RQ Job",
       filters={"job_name": ["like", "%chapter_chapter_board_changed%"]},
       limit=5
   )
   ```

4. **Wait for job to complete** (1-2 seconds)

5. **Verify assignment history:**
   ```python
   volunteer = frappe.get_doc("Volunteer", "Assoc-Vol-2025-10-101174")
   print(len(volunteer.assignment_history))  # Should have new entry
   ```

### Automated Test

See `test_event_driven_sync.py` for automated testing.

## Monitoring

### Check Background Jobs
```bash
bench --site dev.veganisme.net show-jobs
```

### Check Event Logs
```python
frappe.get_all("Error Log",
    filters={"error": ["like", "%chapter%volunteer%"]},
    order_by="creation desc",
    limit=10
)
```

### Verify Job Deduplication
```python
# Should be only one job per chapter per save
jobs = frappe.get_all("RQ Job",
    filters={
        "job_name": ["like", "%chapter_chapter_board_changed_Utrecht%"],
        "creation": [">", "2025-11-18 10:00:00"]
    }
)
print(f"Jobs created: {len(jobs)}")  # Should be minimal
```

## Rollback (If Needed)

If issues occur, restore direct sync by adding back to `after_save()`:

```python
def after_save(self):
    # ... existing code ...

    # Restore direct sync
    if self.has_value_changed("board_members"):
        self.volunteer_integration_manager.sync_board_members_with_volunteer_system()
```

However, this brings back the race condition, so also disable event-driven sync:

```python
# In on_update(), comment out:
# self._emit_chapter_change_events(old_doc)
```

## Related Changes

1. **Idempotency Fixes:** `verenigingen/utils/assignment_history_manager.py`
2. **Cleanup Utility:** `verenigingen/utils/cleanup_duplicate_assignments.py`
3. **Documentation:** `docs/VOLUNTEER_ASSIGNMENT_HISTORY_FIX.md`

## Author

**Change Date:** 2025-11-18
**Files Modified:** 1 (chapter.py)
**Lines Changed:** ~10 (removal + comment)
**Testing:** Manual verification required
**Risk Level:** Low (event system already working, just removing redundant path)
