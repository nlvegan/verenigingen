# VIP Import Robustness & Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 9 robustness issues in VIP Import and consolidate shared logic with MijnRood CSV Import.

**Architecture:** Three-phase approach: (1) Critical fixes to VIP Import for immediate safety, (2) Extract shared services for member lookup and volunteer creation, (3) Create base class for common CSV import patterns.

**Tech Stack:** Python 3.11, Frappe Framework, MariaDB savepoints, RQ background jobs

---

## Phase 1: Critical Fixes (VIP Import Safety)

### Task 1: Add Savepoint Transactions to Row Processing

**Files:**
- Modify: `verenigingen/verenigingen/doctype/vip_import/vip_import.py:496-568`
- Test: `verenigingen/verenigingen/doctype/vip_import/test_vip_import.py`

**Step 1: Write the failing test**

Add to `test_vip_import.py`:

```python
class TestVIPImportRobustness(FrappeTestCase):
    """Test robustness features of VIP Import."""

    def test_savepoint_rollback_on_volunteer_link_failure(self):
        """Test that volunteer creation is rolled back if member link update fails."""
        # Create a member
        member = frappe.get_doc({
            "doctype": "Member",
            "first_name": "Savepoint",
            "last_name": "Test",
            "email": "savepoint-test@example.com",
            "status": "Active",
        })
        member.insert(ignore_permissions=True)
        frappe.db.commit()

        row = {
            "row_number": 1,
            "vip_user_id": "savepoint-test-123",
            "first_name": "Savepoint",
            "last_name": "Test",
            "organization_email": "savepoint-test@example.com",
            "volunteer_status": "Active",
        }

        # Mock db.set_value to fail after volunteer insert
        original_set_value = frappe.db.set_value
        call_count = [0]

        def failing_set_value(*args, **kwargs):
            call_count[0] += 1
            # Fail on the volunteer_record update (2nd set_value call)
            if call_count[0] == 2 and args[2] == "volunteer_record":
                raise Exception("Simulated DB failure")
            return original_set_value(*args, **kwargs)

        import_doc = frappe.new_doc("VIP Import")
        import_doc.name = "TEST-VIP-SAVEPOINT"
        stats = {
            "volunteers_created": 0,
            "volunteers_updated": 0,
            "volunteers_skipped": 0,
            "members_not_found": 0,
            "members_created": 0,
        }

        with patch.object(frappe.db, "set_value", failing_set_value):
            from verenigingen.verenigingen.doctype.vip_import.vip_import import (
                _process_single_row,
            )
            result = _process_single_row(row, import_doc, stats)

        # Should return error status
        self.assertEqual(result["status"], "error")

        # Volunteer should NOT exist (rolled back)
        volunteer_exists = frappe.db.exists("Volunteer", {"vip_user_id": "savepoint-test-123"})
        self.assertFalse(volunteer_exists, "Volunteer should be rolled back on failure")

        # Cleanup
        member.delete(ignore_permissions=True)
        frappe.db.commit()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.verenigingen.doctype.vip_import.test_vip_import --test TestVIPImportRobustness.test_savepoint_rollback_on_volunteer_link_failure`

Expected: FAIL - Volunteer exists despite the simulated failure (no rollback)

**Step 3: Implement savepoint in _process_single_row**

Modify `vip_import.py` at line 496:

```python
def _process_single_row(row: Dict, import_doc: Document, stats: Dict) -> Dict[str, Any]:
    """
    Process a single row from the VIP import.

    Uses savepoints to ensure atomic row processing - if any part fails,
    all changes for this row are rolled back.

    Args:
        row: Mapped row data from validator
        import_doc: VIP Import document
        stats: Statistics dictionary to update

    Returns:
        Result dictionary with status and details
    """
    import time

    row_num = row.get("row_number", "?")
    savepoint_name = f"vip_row_{row_num}_{int(time.time() * 1000)}"

    try:
        # Create savepoint before any modifications
        frappe.db.sql(f"SAVEPOINT {savepoint_name}")

        # Find existing Member
        member = _find_member(row)

        if not member:
            if import_doc.create_members_if_missing:
                member = _create_member(row)
                stats["members_created"] += 1
            else:
                # No rollback needed - no changes made
                stats["members_not_found"] += 1
                return {
                    "status": "skipped",
                    "reason": "member_not_found",
                    "row": row_num,
                    "identifier": row.get("member_id") or row.get("organization_email"),
                }

        # Find existing Volunteer
        volunteer = _find_volunteer(row, member)

        if volunteer:
            # Handle based on duplicate_handling setting
            if import_doc.duplicate_handling == "Skip existing":
                stats["volunteers_skipped"] += 1
                return {
                    "status": "skipped",
                    "reason": "volunteer_exists",
                    "row": row_num,
                    "volunteer": volunteer.name,
                }
            else:
                # Update existing with import batch tracking
                _update_volunteer(volunteer, row, member, import_batch_name=import_doc.name)
                stats["volunteers_updated"] += 1
                return {
                    "status": "updated",
                    "row": row_num,
                    "volunteer": volunteer.name,
                }
        else:
            # Create new Volunteer with import batch tracking
            volunteer = _create_volunteer(row, member, import_batch_name=import_doc.name)
            stats["volunteers_created"] += 1
            return {
                "status": "created",
                "row": row_num,
                "volunteer": volunteer.name,
            }

    except Exception as e:
        # Rollback to savepoint on any error
        try:
            frappe.db.sql(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
        except Exception:
            pass  # Savepoint may already be released

        frappe.log_error(
            title=f"VIP Import Row {row_num} Error",
            message=f"Error: {str(e)}\nRow data: {json.dumps(row, default=str)}",
        )
        return {
            "status": "error",
            "row": row_num,
            "error": str(e),
        }
```

**Step 4: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.verenigingen.doctype.vip_import.test_vip_import --test TestVIPImportRobustness.test_savepoint_rollback_on_volunteer_link_failure`

Expected: PASS

**Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/vip_import/vip_import.py verenigingen/verenigingen/doctype/vip_import/test_vip_import.py
git commit -m "$(cat <<'EOF'
fix(vip-import): add savepoint transactions for atomic row processing

Wraps each row's processing in a MySQL savepoint so that if volunteer
creation succeeds but the member link update fails, both operations
are rolled back together. Prevents orphaned volunteers.
EOF
)"
```

---

### Task 2: Fix TOCTOU Race Condition in Volunteer Creation

**Files:**
- Modify: `verenigingen/verenigingen/doctype/vip_import/vip_import.py:331-404`
- Test: `verenigingen/verenigingen/doctype/vip_import/test_vip_import.py`

**Step 1: Write the failing test**

Add to `test_vip_import.py`:

```python
def test_duplicate_volunteer_handling_race_condition(self):
    """Test that concurrent volunteer creation is handled gracefully."""
    # Create a member
    member = frappe.get_doc({
        "doctype": "Member",
        "first_name": "Race",
        "last_name": "Test",
        "email": "race-test@example.com",
        "status": "Active",
    })
    member.insert(ignore_permissions=True)

    # Pre-create a volunteer to simulate race condition
    volunteer = frappe.get_doc({
        "doctype": "Volunteer",
        "volunteer_name": "Race Test",
        "member": member.name,
        "status": "Active",
        "start_date": today(),
    })
    volunteer.insert(ignore_permissions=True)
    frappe.db.commit()

    row = {
        "row_number": 1,
        "vip_user_id": "race-test-456",
        "first_name": "Race",
        "last_name": "Test",
        "organization_email": "race-test@example.com",
        "volunteer_status": "Active",
    }

    from verenigingen.verenigingen.doctype.vip_import.vip_import import (
        _create_volunteer,
    )

    # This should NOT raise an error - should detect existing and return it
    result = _create_volunteer(row, member, import_batch_name="TEST-RACE")

    # Should return the existing volunteer, not create a duplicate
    self.assertEqual(result.name, volunteer.name)

    # Cleanup
    volunteer.delete(ignore_permissions=True)
    member.delete(ignore_permissions=True)
    frappe.db.commit()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.verenigingen.doctype.vip_import.test_vip_import --test TestVIPImportRobustness.test_duplicate_volunteer_handling_race_condition`

Expected: FAIL - DuplicateEntryError or creates duplicate

**Step 3: Implement FOR UPDATE lock in _create_volunteer**

Modify `vip_import.py` function `_create_volunteer` (lines 331-404):

```python
def _create_volunteer(row: Dict, member: Document, import_batch_name: Optional[str] = None) -> Document:
    """
    Create a new Volunteer record.

    Uses FOR UPDATE lock on member row to prevent race conditions where
    multiple concurrent processes could create duplicate volunteers.

    Args:
        row: Mapped row data from validator
        member: Member document to link
        import_batch_name: Name of the VIP Import document for batch tracking

    Returns:
        Created (or existing) Volunteer document

    Raises:
        frappe.ValidationError: If member doesn't meet age requirement
    """
    # Lock member row to prevent concurrent volunteer creation
    frappe.db.sql(
        "SELECT name FROM `tabMember` WHERE name = %s FOR UPDATE",
        member.name
    )

    # Re-check if volunteer already exists (after acquiring lock)
    existing_volunteer_name = frappe.db.get_value(
        "Volunteer", {"member": member.name}, "name"
    )
    if existing_volunteer_name:
        # Return existing volunteer - another process created it first
        existing_volunteer = frappe.get_doc("Volunteer", existing_volunteer_name)
        # Update with VIP data if needed
        if row.get("vip_user_id") and not existing_volunteer.vip_user_id:
            existing_volunteer.vip_user_id = str(row["vip_user_id"])
            existing_volunteer.flags.bulk_member_operations = True
            existing_volunteer.save(ignore_permissions=True)
        return existing_volunteer

    # Validate volunteer age requirement
    age_error = _validate_volunteer_age(member)
    if age_error:
        frappe.throw(_(age_error))

    volunteer = frappe.new_doc("Volunteer")

    # Set name from member
    volunteer.volunteer_name = member.full_name or f"{member.first_name} {member.last_name}"
    volunteer.member = member.name

    # Organization email (from VIP)
    if row.get("organization_email"):
        volunteer.email = row["organization_email"]

    # VIP IDs
    if row.get("vip_user_id"):
        volunteer.vip_user_id = str(row["vip_user_id"])

    if row.get("google_workspace_id"):
        volunteer.google_workspace_id = row["google_workspace_id"]

    # Import batch tracking
    if import_batch_name:
        volunteer.vip_import_batch = import_batch_name

    # Status
    volunteer.status = row.get("volunteer_status", "Active")

    # Start date
    if row.get("start_date"):
        volunteer.start_date = row["start_date"]
    else:
        volunteer.start_date = today()

    # Notes
    notes_parts = []
    if row.get("notes"):
        notes_parts.append(row["notes"])
    if row.get("status_notes"):
        notes_parts.append(f"[Status Notes]: {row['status_notes']}")
    if notes_parts:
        volunteer.note = "\n\n".join(notes_parts)

    # Skip account creation during bulk import
    volunteer.flags.bulk_member_operations = True
    volunteer.flags.skip_volunteer_account_creation = True

    # Bulk import operation - permissions validated at API level via @critical_api decorator
    volunteer.insert(ignore_permissions=True)

    # Update member's volunteer_record link (safe - we hold the lock)
    frappe.db.set_value(
        "Member", member.name, "volunteer_record", volunteer.name, update_modified=False
    )

    return volunteer
```

**Step 4: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.verenigingen.doctype.vip_import.test_vip_import --test TestVIPImportRobustness.test_duplicate_volunteer_handling_race_condition`

Expected: PASS

**Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/vip_import/vip_import.py verenigingen/verenigingen/doctype/vip_import/test_vip_import.py
git commit -m "$(cat <<'EOF'
fix(vip-import): prevent TOCTOU race condition in volunteer creation

Uses FOR UPDATE lock on member row before creating volunteer.
After acquiring lock, re-checks if volunteer exists (another process
may have created it while waiting for lock). Returns existing volunteer
instead of creating duplicate.
EOF
)"
```

---

### Task 3: Add Queue Capacity Check Before Enqueue

**Files:**
- Modify: `verenigingen/verenigingen/doctype/vip_import/vip_import.py:143-167`
- Test: `verenigingen/verenigingen/doctype/vip_import/test_vip_import.py`

**Step 1: Write the failing test**

Add to `test_vip_import.py`:

```python
def test_queue_capacity_check_on_submit(self):
    """Test that queue capacity is checked before enqueueing import job."""
    from unittest.mock import patch, MagicMock

    # Create minimal VIP Import document
    import_doc = frappe.get_doc({
        "doctype": "VIP Import",
        "import_date": today(),
        "import_status": "Ready for Import",
    })

    # Mock queue capacity check to return False (queue full)
    with patch(
        "verenigingen.verenigingen.doctype.vip_import.vip_import.has_queue_capacity",
        return_value=False
    ) as mock_capacity:
        with patch(
            "verenigingen.verenigingen.doctype.vip_import.vip_import.wait_for_queue_capacity",
            return_value=False
        ) as mock_wait:
            # Attempt to submit should throw
            with self.assertRaises(frappe.ValidationError) as context:
                import_doc.on_submit()

            self.assertIn("queue", str(context.exception).lower())
            mock_capacity.assert_called_once()
            mock_wait.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.verenigingen.doctype.vip_import.test_vip_import --test TestVIPImportRobustness.test_queue_capacity_check_on_submit`

Expected: FAIL - no queue check exists, enqueue proceeds

**Step 3: Implement queue capacity check**

Modify `vip_import.py` - add imports and modify `on_submit`:

```python
# Add to imports at top of file (around line 23)
from verenigingen.utils.queue_management import has_queue_capacity, wait_for_queue_capacity
```

```python
def on_submit(self):
    """Queue background import job when document is submitted."""
    if self.import_status not in ["Ready for Import", "Pending"]:
        frappe.throw(
            _(
                "Import status must be 'Ready for Import' or 'Pending' to process. Current status: {0}"
            ).format(self.import_status)
        )

    # Check queue capacity before enqueueing
    if not has_queue_capacity(queue_name="long", required_capacity=1):
        frappe.msgprint(
            _("Background job queue is near capacity. Waiting for space..."),
            indicator="orange",
        )
        if not wait_for_queue_capacity(
            queue_name="long",
            timeout=60,  # Wait up to 60 seconds
            log_prefix=f"[VIP Import {self.name}] ",
        ):
            frappe.throw(
                _(
                    "Background job queue is full. Please wait a few minutes and try again. "
                    "The queue processes jobs continuously and should have capacity soon."
                ),
                exc=frappe.ValidationError,
            )

    # Queue background job
    self.db_set("import_status", "Queued")
    frappe.db.commit()

    frappe.enqueue(
        "verenigingen.verenigingen.doctype.vip_import.vip_import.process_import_background",
        queue="long",
        timeout=BACKGROUND_JOB_TIMEOUT,
        import_doc_name=self.name,
        test_mode=bool(self.test_mode),
    )

    frappe.msgprint(
        _("VIP Import has been queued for processing. You can monitor progress on this page."),
        indicator="blue",
    )
```

**Step 4: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.verenigingen.doctype.vip_import.test_vip_import --test TestVIPImportRobustness.test_queue_capacity_check_on_submit`

Expected: PASS

**Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/vip_import/vip_import.py verenigingen/verenigingen/doctype/vip_import/test_vip_import.py
git commit -m "$(cat <<'EOF'
fix(vip-import): add queue capacity check before enqueueing

Checks RQ queue capacity before submitting import job. If queue is
near capacity, waits up to 60 seconds for space. Prevents queue
overload during high-volume import periods.

Uses existing queue_management utilities for consistency with
MijnRood CSV import.
EOF
)"
```

---

### Task 4: Add Import Status Warning for ACR Failures

**Files:**
- Modify: `verenigingen/verenigingen/doctype/vip_import/vip_import.py:909-927`
- Test: `verenigingen/verenigingen/doctype/vip_import/test_vip_import.py`

**Step 1: Write the failing test**

Add to `test_vip_import.py`:

```python
def test_import_status_reflects_acr_failures(self):
    """Test that import status shows warning when ACR queuing fails."""
    from unittest.mock import patch

    # Mock ACR result with error
    acr_result = {
        "error": "Redis connection failed",
        "acrs_created": 0,
        "active_volunteers_queued": 5,
    }

    import_doc = frappe.get_doc({
        "doctype": "VIP Import",
        "import_date": today(),
    })
    import_doc.insert(ignore_permissions=True)

    # Simulate setting final status with ACR error
    with patch(
        "verenigingen.verenigingen.doctype.vip_import.vip_import._process_account_creation",
        return_value=acr_result
    ):
        # We need to call the status update logic
        from verenigingen.verenigingen.doctype.vip_import.vip_import import (
            _set_final_import_status,
        )
        _set_final_import_status(import_doc, stats={}, acr_result=acr_result)

    import_doc.reload()
    self.assertEqual(import_doc.import_status, "Completed with Warnings")
    self.assertIn("Redis connection failed", import_doc.acr_error or "")

    # Cleanup
    import_doc.delete(ignore_permissions=True)
    frappe.db.commit()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.verenigingen.doctype.vip_import.test_vip_import --test TestVIPImportRobustness.test_import_status_reflects_acr_failures`

Expected: FAIL - function `_set_final_import_status` doesn't exist

**Step 3: Extract and implement status update logic**

Add new function and modify `process_import_background` in `vip_import.py`:

```python
def _set_final_import_status(
    import_doc: Document,
    stats: Dict[str, int],
    acr_result: Dict[str, Any],
    errors: List[str] = None,
    skipped_rows: List[Dict] = None,
    skipped_reasons: List[str] = None,
) -> None:
    """
    Set final import status and summary fields.

    Sets status to "Completed with Warnings" if ACR queuing failed,
    otherwise "Completed".

    Args:
        import_doc: VIP Import document
        stats: Processing statistics dictionary
        acr_result: Account creation result dictionary
        errors: List of error messages
        skipped_rows: List of skipped row info dicts
        skipped_reasons: List of delegated account skip reasons
    """
    errors = errors or []
    skipped_rows = skipped_rows or []
    skipped_reasons = skipped_reasons or []

    # Determine final status
    if acr_result.get("error"):
        import_doc.db_set("import_status", "Completed with Warnings")
        import_doc.db_set("acr_error", acr_result["error"][:500])
    else:
        import_doc.db_set("import_status", "Completed")

    # Set statistics
    import_doc.db_set("volunteers_created", stats.get("volunteers_created", 0))
    import_doc.db_set("volunteers_updated", stats.get("volunteers_updated", 0))
    import_doc.db_set("volunteers_skipped", stats.get("volunteers_skipped", 0))
    import_doc.db_set("members_not_found", stats.get("members_not_found", 0))
    import_doc.db_set("members_created", stats.get("members_created", 0))

    # Set account creation tracking fields
    import_doc.db_set("acrs_created", acr_result.get("acrs_created", 0))
    import_doc.db_set("acrs_queued_for_active", acr_result.get("active_volunteers_queued", 0))
    import_doc.db_set("users_upgraded", acr_result.get("users_linked", 0))
    if acr_result.get("tracker_name"):
        import_doc.db_set("bulk_operation_tracker", acr_result["tracker_name"])

    # Set skipped rows log
    if skipped_rows:
        skipped_rows_log = _generate_skipped_rows_log(skipped_rows)
        import_doc.db_set("skipped_rows_log", skipped_rows_log)

    # Build summary
    summary_parts = [
        f"Import completed at {now_datetime()}",
        f"Volunteers created: {stats.get('volunteers_created', 0)}",
        f"Volunteers updated: {stats.get('volunteers_updated', 0)}",
        f"Volunteers skipped: {stats.get('volunteers_skipped', 0)}",
    ]
    if stats.get("members_created", 0) > 0:
        summary_parts.append(f"Members created: {stats['members_created']}")
    if stats.get("members_not_found", 0) > 0:
        summary_parts.append(f"Members not found: {stats['members_not_found']}")

    # Add account creation summary
    if acr_result.get("active_volunteers_queued", 0) > 0:
        summary_parts.extend([
            "",
            "--- Account Creation ---",
            f"Active volunteers queued: {acr_result['active_volunteers_queued']}",
        ])
        if acr_result.get("inactive_skipped", 0) > 0:
            summary_parts.append(f"Inactive/Retired skipped: {acr_result['inactive_skipped']}")
        if acr_result.get("acrs_created", 0) > 0:
            summary_parts.append(f"Account creation requests: {acr_result['acrs_created']}")
        if acr_result.get("users_linked", 0) > 0:
            summary_parts.append(f"Users linked (already had accounts): {acr_result['users_linked']}")
        if acr_result.get("tracker_name"):
            summary_parts.append(f"Progress tracker: {acr_result['tracker_name']}")
    elif acr_result.get("inactive_skipped", 0) > 0:
        summary_parts.extend([
            "",
            "--- Account Creation ---",
            f"All {acr_result['inactive_skipped']} volunteers have Inactive/Retired status - no account upgrades needed",
        ])

    if acr_result.get("error"):
        summary_parts.append(f"\n⚠️ Account creation error: {acr_result['error']}")

    import_doc.db_set("import_summary", "\n".join(summary_parts))

    # Set errors (sanitize PII from error messages)
    if errors:
        sanitized_errors = [_sanitize_error_message(e) for e in errors[:MAX_ERRORS_TO_LOG]]
        import_doc.db_set("error_log", "\n".join(sanitized_errors))
        import_doc.db_set("top_errors_summary", f"{len(errors)} errors encountered during import")

    # Include skipped delegated accounts in error log if any
    if skipped_reasons:
        current_log = import_doc.error_log or ""
        sanitized_skipped = [_sanitize_error_message(r) for r in skipped_reasons[:MAX_SKIPPED_TO_LOG]]
        delegated_section = "\n\n--- Delegated Accounts Skipped ---\n" + "\n".join(sanitized_skipped)
        import_doc.db_set("error_log", current_log + delegated_section)
```

Then update `process_import_background` to use this function (replace lines 912-982):

```python
        # Process account creation for Active volunteers
        acr_result = _process_account_creation(import_doc_name, processed_volunteers)

        # Finalize
        import_doc.reload()
        _set_final_import_status(
            import_doc=import_doc,
            stats=stats,
            acr_result=acr_result,
            errors=errors,
            skipped_rows=skipped_rows,
            skipped_reasons=skipped_reasons,
        )
        frappe.db.commit()
```

**Step 4: Add acr_error field to DocType**

Modify `verenigingen/verenigingen/doctype/vip_import/vip_import.json` - add field:

```json
{
    "fieldname": "acr_error",
    "fieldtype": "Small Text",
    "label": "Account Creation Error",
    "read_only": 1,
    "depends_on": "eval:doc.acr_error"
}
```

**Step 5: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.verenigingen.doctype.vip_import.test_vip_import --test TestVIPImportRobustness.test_import_status_reflects_acr_failures`

Expected: PASS

**Step 6: Commit**

```bash
git add verenigingen/verenigingen/doctype/vip_import/vip_import.py verenigingen/verenigingen/doctype/vip_import/vip_import.json verenigingen/verenigingen/doctype/vip_import/test_vip_import.py
git commit -m "$(cat <<'EOF'
fix(vip-import): show warning status when account creation fails

Extracts status update logic into _set_final_import_status function.
Sets import status to "Completed with Warnings" when ACR queuing fails,
with error details stored in new acr_error field.

Provides visibility into account creation issues instead of silently
marking import as successful.
EOF
)"
```

---

## Phase 2: Service Extraction (Consolidation)

### Task 5: VIP Import Adopts BulkVolunteerCreationService

**Files:**
- Modify: `verenigingen/verenigingen/doctype/vip_import/vip_import.py`
- Modify: `verenigingen/services/volunteer/bulk_volunteer_creation_service.py`
- Test: `verenigingen/verenigingen/doctype/vip_import/test_vip_import.py`

**Step 1: Write the failing test**

Add to `test_vip_import.py`:

```python
def test_volunteer_creation_uses_bulk_service(self):
    """Test that VIP Import uses BulkVolunteerCreationService for volunteer creation."""
    from unittest.mock import patch, MagicMock
    from verenigingen.services.volunteer.bulk_volunteer_creation_service import (
        BulkVolunteerCreationService,
        BulkVolunteerCreationSummary,
    )

    # Create test member
    member = frappe.get_doc({
        "doctype": "Member",
        "first_name": "Bulk",
        "last_name": "ServiceTest",
        "email": "bulk-service-test@example.com",
        "status": "Active",
    })
    member.insert(ignore_permissions=True)
    frappe.db.commit()

    # Mock the service
    mock_summary = BulkVolunteerCreationSummary(
        total_attempted=1,
        created=1,
    )

    with patch.object(
        BulkVolunteerCreationService,
        "create_volunteers_for_members",
        return_value=mock_summary
    ) as mock_create:
        from verenigingen.verenigingen.doctype.vip_import.vip_import import (
            _create_volunteers_batch,
        )
        result = _create_volunteers_batch([member.name], import_batch_name="TEST-BULK")

        mock_create.assert_called_once()
        self.assertEqual(result.created, 1)

    # Cleanup
    member.delete(ignore_permissions=True)
    frappe.db.commit()
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.verenigingen.doctype.vip_import.test_vip_import --test TestVIPImportRobustness.test_volunteer_creation_uses_bulk_service`

Expected: FAIL - `_create_volunteers_batch` doesn't exist

**Step 3: Add vip_data parameter support to BulkVolunteerCreationService**

Modify `bulk_volunteer_creation_service.py` - add VIP data support to `create_volunteers_for_members`:

```python
def create_volunteers_for_members(
    self,
    member_names: List[str],
    batch_size: int = 50,
    commit_per_batch: bool = True,
    vip_data: Optional[Dict[str, Dict[str, Any]]] = None,
    import_batch_name: Optional[str] = None,
) -> BulkVolunteerCreationSummary:
    """
    Create volunteer records for a list of members with full tracking.

    Args:
        member_names: List of member document names
        batch_size: Number of members to process before committing
        commit_per_batch: Whether to commit after each batch
        vip_data: Optional dict mapping member_name to VIP row data
        import_batch_name: Optional import batch name for tracking

    Returns:
        BulkVolunteerCreationSummary with detailed results
    """
    # ... existing implementation with vip_data passed to _create_volunteer_for_member
```

**Step 4: Create wrapper function in vip_import.py**

Add to `vip_import.py`:

```python
def _create_volunteers_batch(
    member_names: List[str],
    vip_data: Dict[str, Dict[str, Any]] = None,
    import_batch_name: str = None,
) -> "BulkVolunteerCreationSummary":
    """
    Create volunteers for members using BulkVolunteerCreationService.

    Provides consistent volunteer creation with proper error tracking
    and savepoint transactions.

    Args:
        member_names: List of member document names
        vip_data: Optional mapping of member_name to VIP CSV row data
        import_batch_name: Import batch name for tracking

    Returns:
        BulkVolunteerCreationSummary with creation results
    """
    from verenigingen.services.volunteer.bulk_volunteer_creation_service import (
        get_bulk_volunteer_creation_service,
    )

    service = get_bulk_volunteer_creation_service()
    return service.create_volunteers_for_members(
        member_names=member_names,
        vip_data=vip_data,
        import_batch_name=import_batch_name,
    )
```

**Step 5: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.verenigingen.doctype.vip_import.test_vip_import --test TestVIPImportRobustness.test_volunteer_creation_uses_bulk_service`

Expected: PASS

**Step 6: Commit**

```bash
git add verenigingen/verenigingen/doctype/vip_import/vip_import.py verenigingen/services/volunteer/bulk_volunteer_creation_service.py verenigingen/verenigingen/doctype/vip_import/test_vip_import.py
git commit -m "$(cat <<'EOF'
refactor(vip-import): adopt BulkVolunteerCreationService for volunteer creation

VIP Import now uses the same robust volunteer creation service as
MijnRood CSV Import. Provides consistent error handling, savepoint
transactions, and detailed outcome tracking.

Adds vip_data parameter support to BulkVolunteerCreationService for
VIP-specific fields (vip_user_id, google_workspace_id, etc).
EOF
)"
```

---

### Task 6: Extract MemberLookupService for Cascade Matching

**Files:**
- Create: `verenigingen/services/member/member_lookup_service.py`
- Create: `verenigingen/services/member/test_member_lookup_service.py`
- Modify: `verenigingen/verenigingen/doctype/vip_import/vip_import.py`

**Step 1: Write the failing test**

Create `test_member_lookup_service.py`:

```python
"""
Tests for MemberLookupService - cascade member matching.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.member.member_lookup_service import (
    MemberLookupService,
    LookupStrategy,
)


class TestMemberLookupService(FrappeTestCase):
    """Test cases for MemberLookupService."""

    def setUp(self):
        """Set up test fixtures."""
        self.service = MemberLookupService()

        # Create test member
        self.test_member = frappe.get_doc({
            "doctype": "Member",
            "first_name": "Lookup",
            "last_name": "Test",
            "email": "lookup-test@example.com",
            "member_id": "LOOKUP-123",
            "status": "Active",
        })
        self.test_member.insert(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        """Clean up test fixtures."""
        if frappe.db.exists("Member", self.test_member.name):
            self.test_member.delete(ignore_permissions=True)
            frappe.db.commit()

    def test_find_by_member_id(self):
        """Test finding member by member_id."""
        result = self.service.find_member(
            {"member_id": "LOOKUP-123"},
            strategies=[LookupStrategy.MEMBER_ID],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_find_by_email_fallback(self):
        """Test finding member by email when member_id not found."""
        result = self.service.find_member(
            {"member_id": "NONEXISTENT", "email": "lookup-test@example.com"},
            strategies=[LookupStrategy.MEMBER_ID, LookupStrategy.EMAIL],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, self.test_member.name)

    def test_cascade_stops_on_first_match(self):
        """Test that cascade matching stops on first successful match."""
        call_log = []

        original_find = self.service._find_by_member_id
        def tracking_find(*args, **kwargs):
            call_log.append("member_id")
            return original_find(*args, **kwargs)

        self.service._find_by_member_id = tracking_find

        result = self.service.find_member(
            {"member_id": "LOOKUP-123", "email": "lookup-test@example.com"},
            strategies=[LookupStrategy.MEMBER_ID, LookupStrategy.EMAIL],
        )

        # Should find by member_id and not try email
        self.assertEqual(len(call_log), 1)
        self.assertIsNotNone(result)
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.services.member.test_member_lookup_service`

Expected: FAIL - module not found

**Step 3: Implement MemberLookupService**

Create `member_lookup_service.py`:

```python
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberLookupService - Cascade member matching for imports.

Provides configurable cascade matching strategies to find existing
members during bulk import operations.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

import frappe
from frappe.model.document import Document

from verenigingen.services.infrastructure.base_service import StatelessService


class LookupStrategy(Enum):
    """Available member lookup strategies."""

    MEMBER_ID = "member_id"
    PROCURIOS_ID = "procurios_id"
    EMAIL = "email"
    PERSONAL_EMAIL = "personal_email"
    ORGANIZATION_EMAIL = "organization_email"


class MemberLookupService(StatelessService):
    """
    Service for finding existing members using cascade matching.

    Tries multiple lookup strategies in order until a match is found.
    Supports different strategy sets for different import sources.
    """

    # Default strategies for VIP Import (4-step cascade)
    VIP_STRATEGIES = [
        LookupStrategy.MEMBER_ID,
        LookupStrategy.PROCURIOS_ID,
        LookupStrategy.PERSONAL_EMAIL,
        LookupStrategy.ORGANIZATION_EMAIL,
    ]

    # Default strategies for MijnRood Import (2-step cascade)
    MIJNROOD_STRATEGIES = [
        LookupStrategy.MEMBER_ID,
        LookupStrategy.EMAIL,
    ]

    def __init__(self):
        super().__init__(service_name="MemberLookupService")

    def find_member(
        self,
        row_data: Dict[str, Any],
        strategies: List[LookupStrategy] = None,
    ) -> Optional[Document]:
        """
        Find existing member using cascade matching.

        Args:
            row_data: Dictionary with lookup field values
            strategies: Ordered list of strategies to try

        Returns:
            Member document or None if not found
        """
        if strategies is None:
            strategies = self.VIP_STRATEGIES

        for strategy in strategies:
            member = self._find_by_strategy(strategy, row_data)
            if member:
                self.logger.debug(
                    f"Found member {member.name} via {strategy.value}"
                )
                return member

        return None

    def _find_by_strategy(
        self,
        strategy: LookupStrategy,
        row_data: Dict[str, Any],
    ) -> Optional[Document]:
        """Find member using a specific strategy."""
        if strategy == LookupStrategy.MEMBER_ID:
            return self._find_by_member_id(row_data.get("member_id"))
        elif strategy == LookupStrategy.PROCURIOS_ID:
            return self._find_by_member_id(row_data.get("procurios_id"))
        elif strategy == LookupStrategy.EMAIL:
            return self._find_by_email(row_data.get("email"))
        elif strategy == LookupStrategy.PERSONAL_EMAIL:
            return self._find_by_email(row_data.get("personal_email"))
        elif strategy == LookupStrategy.ORGANIZATION_EMAIL:
            return self._find_by_email(row_data.get("organization_email"))
        return None

    def _find_by_member_id(self, member_id: Optional[str]) -> Optional[Document]:
        """Find member by member_id field."""
        if not member_id:
            return None
        member_name = frappe.db.get_value("Member", {"member_id": member_id}, "name")
        if member_name:
            return frappe.get_doc("Member", member_name)
        return None

    def _find_by_email(self, email: Optional[str]) -> Optional[Document]:
        """Find member by email field."""
        if not email:
            return None
        member_name = frappe.db.get_value("Member", {"email": email}, "name")
        if member_name:
            return frappe.get_doc("Member", member_name)
        return None


# Module-level singleton accessor
_service_instance = None


def get_member_lookup_service() -> MemberLookupService:
    """Get singleton instance of MemberLookupService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MemberLookupService()
    return _service_instance
```

**Step 4: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.services.member.test_member_lookup_service`

Expected: PASS

**Step 5: Update VIP Import to use MemberLookupService**

Modify `vip_import.py` `_find_member` function:

```python
def _find_member(row: Dict) -> Optional[Document]:
    """
    Find existing Member by cascade matching.

    Uses MemberLookupService with VIP-specific 4-step cascade:
    1. member_id (nvv_relatie_nummer)
    2. procurios_id (alternate member ID source)
    3. personal_email (private_email)
    4. organization_email (email)

    Args:
        row: Mapped row data from validator

    Returns:
        Member document or None if not found
    """
    from verenigingen.services.member.member_lookup_service import (
        get_member_lookup_service,
        LookupStrategy,
    )

    service = get_member_lookup_service()
    return service.find_member(row, strategies=service.VIP_STRATEGIES)
```

**Step 6: Commit**

```bash
git add verenigingen/services/member/member_lookup_service.py verenigingen/services/member/test_member_lookup_service.py verenigingen/verenigingen/doctype/vip_import/vip_import.py
git commit -m "$(cat <<'EOF'
refactor: extract MemberLookupService for cascade member matching

Creates reusable service for finding members during imports. Supports
configurable lookup strategies for different import sources:
- VIP: member_id → procurios_id → personal_email → org_email
- MijnRood: member_id → email

VIP Import now uses this service instead of inline lookup logic.
MijnRood can adopt it in a follow-up change.
EOF
)"
```

---

### Task 7: Add PII Sanitization to MijnRood CSV Import

**Files:**
- Modify: `verenigingen/verenigingen/doctype/mijnrood_csv_import/mijnrood_csv_import.py`
- Test: `verenigingen/verenigingen/doctype/mijnrood_csv_import/test_mijnrood_csv_import.py`

**Step 1: Write the failing test**

Add to `test_mijnrood_csv_import.py`:

```python
def test_error_log_sanitizes_pii(self):
    """Test that error logs have PII sanitized."""
    from verenigingen.utils.error_handling import sanitize_error_for_audit

    # Simulate an error message with PII
    error_with_pii = "Validation failed for member john.doe@example.com: phone +31612345678 invalid"

    sanitized = sanitize_error_for_audit(error_with_pii, redact_pii=True)

    self.assertNotIn("john.doe@example.com", sanitized)
    self.assertNotIn("+31612345678", sanitized)
    self.assertIn("[EMAIL REDACTED]", sanitized)
```

**Step 2: Run test to verify behavior**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.verenigingen.doctype.mijnrood_csv_import.test_mijnrood_csv_import --test test_error_log_sanitizes_pii`

Expected: Depends on current implementation

**Step 3: Add PII sanitization to MijnRood error logging**

Add import and modify error logging in `mijnrood_csv_import.py`:

```python
# Add to imports
from verenigingen.utils.error_handling import sanitize_error_for_audit

# In _log_row_error or equivalent:
def _sanitize_error_message(message: str) -> str:
    """Sanitize PII from error messages before logging."""
    return sanitize_error_for_audit(
        message,
        max_length=1000,
        remove_stack_trace=False,
        redact_pii=True,
    ) or message
```

**Step 4: Commit**

```bash
git add verenigingen/verenigingen/doctype/mijnrood_csv_import/mijnrood_csv_import.py verenigingen/verenigingen/doctype/mijnrood_csv_import/test_mijnrood_csv_import.py
git commit -m "$(cat <<'EOF'
fix(mijnrood-import): sanitize PII in error logs

Uses sanitize_error_for_audit from error_handling utils to redact
email addresses and phone numbers from error messages before storing
in error_log field.

Adopts same PII protection that VIP Import already has.
EOF
)"
```

---

## Phase 3: Run All Tests and Final Verification

### Task 8: Run Full Test Suite

**Step 1: Run VIP Import tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.verenigingen.doctype.vip_import.test_vip_import -v`

Expected: All tests PASS

**Step 2: Run MijnRood CSV Import tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.verenigingen.doctype.mijnrood_csv_import.test_mijnrood_csv_import -v`

Expected: All tests PASS

**Step 3: Run MemberLookupService tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.services.member.test_member_lookup_service -v`

Expected: All tests PASS

**Step 4: Run pre-commit hooks**

Run: `cd ~/frappe-bench/apps/verenigingen && pre-commit run --all-files`

Expected: All hooks PASS

**Step 5: Final commit for any fixes**

```bash
git add -A
git commit -m "test: ensure all import robustness tests pass"
```

---

## Summary of Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `vip_import.py` | Modify | Savepoints, TOCTOU fix, queue check, ACR status |
| `vip_import.json` | Modify | Add `acr_error` field |
| `test_vip_import.py` | Modify | Add robustness tests |
| `bulk_volunteer_creation_service.py` | Modify | Add VIP data support |
| `member_lookup_service.py` | Create | New cascade matching service |
| `test_member_lookup_service.py` | Create | Service tests |
| `mijnrood_csv_import.py` | Modify | Add PII sanitization |

---

Plan complete and saved to `docs/plans/2026-01-29-vip-import-robustness-and-consolidation.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach?
