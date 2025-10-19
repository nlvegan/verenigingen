# Background Job Testing Guide

## Quick Reference

**Testing background jobs? Follow these 5 steps:**

1. **Create document**: `doc.insert(); frappe.db.commit()`
2. **Reload**: `doc = frappe.get_doc(doctype, name)`
3. **Update**: `doc.save()` (triggers `on_update()` → background jobs)
4. **Check errors**: `frappe.get_all("Error Log", filters={...})`
5. **Verify effects**: `child_doc.reload()` and assert changes

**Handler signature must be**: `def handler(event_name, event_data, **kwargs):`

**See complete guide below...**

---

## Overview

This document explains how to properly test background job functionality in the Verenigingen codebase, particularly for event-driven workflows that use `frappe.enqueue()`.

## The Problem: Test Coverage Gap

### What Happened

A critical bug was discovered where team member assignment history wasn't being updated in production:

```python
# User action: Assigned member to Team IT
team.append("team_members", {...})
team.save()  # Should update volunteer assignment history

# Expected: Volunteer's assignment_history child table updated
# Actual: Nothing happened - assignment history not created
```

**Root Cause**: Background job handler functions were missing the `**kwargs` parameter.

### Why Tests Didn't Catch It

The codebase has **two separate execution paths** for team member changes:

#### Path 1: Synchronous (New Teams) - What Tests Exercise
```python
# team.py - after_insert()
def after_insert(self):
    self.handle_team_member_changes()  # ✅ Direct synchronous call
```

**Characteristics:**
- Runs immediately in the same transaction
- Never uses `frappe.enqueue()`
- Never calls background job handlers
- **All existing tests use this path**

#### Path 2: Asynchronous (Existing Teams) - What Production Uses
```python
# team.py - on_update()
def on_update(self):
    self._emit_team_change_events(...)  # Emits background events
    self._handle_immediate_team_changes()  # Empty - does nothing!
```

**Characteristics:**
- Uses `frappe.enqueue()` to queue background jobs
- Passes `dedupe=True`, `delay=1`, `timeout=300`, etc. as kwargs
- Requires handlers to accept `**kwargs`
- **Tests never exercise this path**

### The Bug

Background job handlers looked like this:

```python
# ❌ BROKEN - Missing **kwargs
def handle_role_profile_assignments(event_name, event_data):
    # ...
```

When `frappe.enqueue()` called this function:

```python
frappe.enqueue(
    method=handle_role_profile_assignments,
    dedupe=True,  # ← These kwargs need to be accepted!
    delay=1,
    timeout=300,
    **{"event_name": event_name, "event_data": event_data}
)
```

**Result**: `TypeError: handle_role_profile_assignments() got an unexpected keyword argument 'dedupe'`

### The Fix

All background job handlers must accept `**kwargs`:

```python
# ✅ CORRECT - Accepts all kwargs
def handle_role_profile_assignments(event_name, event_data, **kwargs):
    """
    Args:
        event_name: Name of the event
        event_data: Dict containing event data
        **kwargs: Additional parameters from frappe.enqueue()
                  (dedupe, delay, timeout, etc.)
    """
    # ...
```

## How to Test Background Jobs

### 1. Create Existing Documents

Background jobs typically fire on `on_update()`, not `after_insert()`. Your test must:

```python
def test_background_job_workflow(self):
    # Create and commit to make it "existing"
    team = frappe.get_doc({
        "doctype": "Team",
        "team_name": "Test Team",
        # ...
    })
    team.insert()
    frappe.db.commit()  # ← Critical!

    # Reload to simulate existing document
    team = frappe.get_doc("Team", team.name)

    # NOW update it - this triggers on_update() → background jobs
    team.append("team_members", {...})
    team.save()  # ← This emits events and queues background jobs
```

### 2. Process Background Jobs in Tests

Background jobs don't run automatically in tests. You need to process them:

```python
import time

# Save triggers background job queueing
team.save()
frappe.db.commit()

# Try to flush pending jobs (if method exists)
if hasattr(frappe.enqueue, 'flush'):
    frappe.enqueue.flush()

# Wait for processing (in development/test mode)
time.sleep(2)
```

### 3. Verify No Background Job Errors

Check that background jobs completed without errors:

```python
# Check error logs for background job failures
recent_errors = frappe.get_all(
    "Error Log",
    filters={
        "creation": [">=", frappe.utils.add_to_date(frappe.utils.now(), hours=-1)],
        "error": ["like", "%team_subscribers%"]
    },
    fields=["name", "error"]
)

# Look for **kwargs parameter errors
kwargs_errors = [
    e for e in recent_errors
    if "unexpected keyword argument" in e.error
]

self.assertEqual(len(kwargs_errors), 0,
    "Background job handlers must accept **kwargs parameters")
```

### 4. Verify Side Effects Occurred

Check that the background job actually did its work:

```python
# Reload to see changes made by background job
volunteer_doc.reload()

# Verify assignment history was created
found_assignment = any(
    a.reference_name == team.name and a.status == "Active"
    for a in volunteer_doc.assignment_history or []
)

self.assertTrue(found_assignment,
    "Background job should have created assignment history")
```

## Meta-Test: Validate Function Signatures

To prevent future regressions, include a meta-test that validates all background job handlers:

```python
def test_all_handlers_accept_kwargs(self):
    """Verify all background job handlers have correct signatures"""
    import inspect
    from verenigingen.events import team_events

    event_types = [
        "team_membership_changed",
        "team_settings_changed",
        "team_leadership_changed"
    ]

    for event_type in event_types:
        subscribers = team_events._get_team_event_subscribers(event_type)

        for subscriber_path in subscribers:
            # Import handler function
            module_path, function_name = subscriber_path.rsplit(".", 1)
            module = frappe.get_module(module_path)
            handler = getattr(module, function_name)

            # Check signature
            sig = inspect.signature(handler)

            # Verify **kwargs exists
            has_kwargs = any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in sig.parameters.values()
            )

            self.assertTrue(has_kwargs,
                f"{subscriber_path} MUST accept **kwargs for frappe.enqueue() parameters")
```

## Common Pitfalls

### ❌ Testing Only New Document Creation

```python
# This only tests after_insert() path!
def test_team_assignment(self):
    team = frappe.get_doc({...})
    team.insert()  # ← Uses synchronous path
    # Never tests background jobs!
```

### ✅ Test Both Insert and Update

```python
def test_team_assignment_on_new_team(self):
    """Test synchronous path (after_insert)"""
    team = frappe.get_doc({...})
    team.insert()
    # Verify immediate behavior

def test_team_assignment_on_existing_team(self):
    """Test asynchronous path (on_update)"""
    team = frappe.get_doc({...})
    team.insert()
    frappe.db.commit()

    team = frappe.get_doc("Team", team.name)  # Reload
    team.append("team_members", {...})
    team.save()  # ← Triggers background jobs
    # Verify background job behavior
```

### ❌ Forgetting frappe.db.commit()

```python
team = frappe.get_doc({...})
team.insert()
# Missing: frappe.db.commit()

team = frappe.get_doc("Team", team.name)
# Document isn't really "existing" without commit
```

### ❌ Not Checking Error Logs

```python
team.save()  # Background jobs may have failed!
# Should check Error Log for failures
```

## Example: Complete Background Job Test

See `/home/frappe/frappe-bench/apps/verenigingen/verenigingen/tests/integration/test_team_background_jobs.py` for a complete example.

Key features:
- Tests existing document updates
- Processes background jobs
- Checks error logs
- Verifies side effects
- Includes meta-test for function signatures

## When to Use Background Jobs in Tests

**Use background job tests when:**
- Testing event-driven workflows
- Testing document updates (not just creation)
- Testing integration between multiple systems
- Testing async operations like email sending, notifications, etc.

**Use synchronous tests when:**
- Testing business logic in isolation
- Testing validators
- Testing calculations
- Testing simple CRUD operations

## Debugging Background Job Issues

### 1. Check if Events are Emitted

Add logging to event emission:

```python
def emit_team_membership_changed(team_name, membership_data):
    frappe.logger("events").info(f"Emitting event for {team_name}")
    # ...
```

### 2. Check if Jobs are Queued

```bash
# View Redis queue
bench --site dev.veganisme.net show-jobs
```

### 3. Check Error Logs

```python
errors = frappe.get_all("Error Log",
    filters={"error": ["like", "%team_subscribers%"]},
    order_by="creation desc",
    limit=10
)
```

### 4. Enable Debug Logging

```python
frappe.logger("events").setLevel("DEBUG")
frappe.logger("background_jobs").setLevel("DEBUG")
```

## Summary

**Key Takeaway**: When testing event-driven background job workflows:

1. ✅ Create "existing" documents with `insert()` + `commit()` + `reload()`
2. ✅ Update documents to trigger `on_update()` path
3. ✅ Process background jobs with `flush()` or wait
4. ✅ Check error logs for failures
5. ✅ Verify side effects occurred
6. ✅ Include meta-tests for handler signatures
7. ✅ Test both synchronous and asynchronous paths

**Without these steps, your tests will pass but production will fail.**
