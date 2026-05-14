# Event Application — Termination Sync Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the single `_check_and_handle_termination` method (~130 LOC) from `event_application_service.py` (now 1,437 LOC after PR #4) into a new `MijnRoodTerminationSyncService`. This is Phase 1, PR #5 of the Tier C refactor — the smallest PR in the sequence.

**Architecture:** New `termination_sync_service.py` housing a single class method. The god-class loses ~130 LOC and keeps a one-line shim. No `orchestrator` parameter needed — the method has no cross-cutting deps (`TerminationExecutionService` is its own service).

**Reference spec:** `docs/plans/2026-05-12-event-application-service-refactor-design.md`

---

## Carry-forward lessons (CRITICAL — propagate from PR #2-4)

1. `EnhancedTestDataFactory.create_member` uniquifies BOTH `email` AND `last_name`. Use stored values.
2. `MemberImportService.create_or_update_member()` commits + Member.after_save creates a Customer. Use `_cleanup_member_and_customer(member_name)` with `frappe.db.commit()` at the end.
3. `test-quality-enforcer` whitelist: `_create_*` and `_cleanup_*` method prefixes pass; other prefixes get flagged for inline `ignore_permissions=True`.
4. `permission-bypass-validator` requires `# Security: …` comments above `ignore_permissions=True` in PRODUCTION code (not test fixtures). The `_check_and_handle_termination` body has one such comment — preserve verbatim.
5. Pre-commit may reformat — re-stage and re-commit. No `--no-verify`.
6. Pyright "could not be resolved" / "not accessed" warnings on new module paths — stale-index, ignore.
7. Mock usage in tests: add `# Mock justified: …` comment above `with patch(...)` blocks.

**New for PR #5:**

8. `_check_and_handle_termination` requires `get_terminated_status_ids()` and `get_active_status_ids()` from MijnRood Sync Settings — tests must seed `status_mapping` with at least one Active and one Terminated status to exercise the routing.
9. `TerminationExecutionService().execute(termination_doc)` does real work (sets member.status, terminates membership, etc.). Tests can either:
   - Let it run end-to-end (verify member.status becomes "Quit" etc.) — full integration
   - Mock the service with `# Mock justified: Infrastructure - TerminationExecutionService covered by its own tests`
   Prefer mocking for unit isolation; the integration is exercised elsewhere.

---

## File Structure

**Create:**
- `verenigingen/mijnrood_sync/services/event_application/termination_sync_service.py` — `MijnRoodTerminationSyncService` + `get_termination_sync_service`
- `verenigingen/tests/services/event_application/test_termination_sync_service.py` — real-DB integration tests

**Modify:**
- `verenigingen/mijnrood_sync/services/event_application_service.py` — replace `_check_and_handle_termination` body with one-line delegation shim; drop orphaned imports

---

## Task 1: Scaffold + tests + implementation + wire (single-task PR)

Because PR #5 extracts only one method, all work fits in a single task. Steps follow the standard TDD pattern: failing tests → implementation → wiring → verify → commit → push.

**Files:**
- Create: `verenigingen/mijnrood_sync/services/event_application/termination_sync_service.py`
- Create: `verenigingen/tests/services/event_application/test_termination_sync_service.py`
- Modify: `verenigingen/mijnrood_sync/services/event_application_service.py`

### Step 1: Write the failing tests

Create `verenigingen/tests/services/event_application/test_termination_sync_service.py`:

```python
"""Real-DB integration tests for MijnRoodTerminationSyncService.

The service routes terminated-status transitions to a Membership
Termination Request + TerminationExecutionService. Tests cover the
short-circuit paths (no status change, non-terminated transitions,
missing member, already-terminal member) and the happy-path execution.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.mijnrood_sync.services.event_application.termination_sync_service import (
    get_termination_sync_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCheckAndHandleTermination(EnhancedTestCase):
    """Routes terminated-status transitions to MTR + TerminationExecutionService."""

    ACTIVE_STATUS_ID = 9101
    TERMINATED_STATUS_ID = 9102

    def setUp(self):
        super().setUp()
        # Seed status mappings: one Active, one Terminated
        settings = frappe.get_single("MijnRood Sync Settings")
        self._original_status_mapping = list(settings.status_mapping or [])
        membership_type = self.factory.ensure_membership_type("Termination Test Type")
        settings.append("status_mapping", {
            "mijnrood_status_id": self.ACTIVE_STATUS_ID,
            "label": "Active (term test)",
            "membership_type_string": "test",
            "is_active": 1,
            "verenigingen_membership_type": membership_type.name,
        })
        settings.append("status_mapping", {
            "mijnrood_status_id": self.TERMINATED_STATUS_ID,
            "label": "Terminated (term test)",
            "membership_type_string": "test",
            "is_active": 0,  # Not active → terminated
            "verenigingen_membership_type": membership_type.name,
        })
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache().delete_value("mijnrood_status_mapping")
        self.addCleanup(self._cleanup_status_mapping)

    def _cleanup_status_mapping(self):
        s = frappe.get_single("MijnRood Sync Settings")
        s.status_mapping = self._original_status_mapping
        s.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache().delete_value("mijnrood_status_mapping")

    def _cleanup_member_and_customer(self, member_name):
        for cust in frappe.get_all("Customer", filters={"member": member_name}, pluck="name"):
            try:
                frappe.db.set_value("Customer", cust, "member", None, update_modified=False)
                frappe.delete_doc("Customer", cust, ignore_permissions=True, force=True)
            except Exception:
                pass
        try:
            if frappe.db.exists("Member", member_name):
                frappe.delete_doc("Member", member_name, ignore_permissions=True, force=True)
        except Exception:
            pass
        frappe.db.commit()

    def _cleanup_termination_request(self, termination_name):
        try:
            if frappe.db.exists("Membership Termination Request", termination_name):
                frappe.delete_doc(
                    "Membership Termination Request",
                    termination_name,
                    ignore_permissions=True,
                    force=True,
                )
                frappe.db.commit()
        except Exception:
            pass

    def _make_event_mock(self, name="TEST-EVT-001", linked_member=None):
        event = MagicMock()
        event.name = name
        event.linked_member = linked_member
        return event

    def test_returns_none_when_no_status_change(self):
        event = self._make_event_mock()
        result = get_termination_sync_service()._check_and_handle_termination(
            event,
            old_data={},
            new_data={"id": "MR-NO-CHG"},
            changed_fields=[{"field": "first_name", "old": "A", "new": "B"}],
        )
        self.assertIsNone(result)

    def test_returns_none_when_new_status_not_terminated(self):
        event = self._make_event_mock()
        result = get_termination_sync_service()._check_and_handle_termination(
            event,
            old_data={"current_membership_status_id": self.ACTIVE_STATUS_ID},
            new_data={"id": "MR-STILL-ACTIVE", "current_membership_status_id": self.ACTIVE_STATUS_ID},
            changed_fields=[{
                "field": "current_membership_status_id",
                "old": self.ACTIVE_STATUS_ID,
                "new": self.ACTIVE_STATUS_ID,
            }],
        )
        self.assertIsNone(result)

    def test_returns_none_when_old_status_was_already_non_active(self):
        event = self._make_event_mock()
        result = get_termination_sync_service()._check_and_handle_termination(
            event,
            old_data={},
            new_data={"id": "MR-WAS-NON-ACTIVE"},
            changed_fields=[{
                "field": "current_membership_status_id",
                "old": 99999,  # Not in active list
                "new": self.TERMINATED_STATUS_ID,
            }],
        )
        self.assertIsNone(result)

    def test_returns_failure_when_no_linked_member_found(self):
        event = self._make_event_mock()
        result = get_termination_sync_service()._check_and_handle_termination(
            event,
            old_data={"email": "ghost-not-in-db@example.org"},
            new_data={"id": "MR-NO-MEMBER", "email": "ghost-not-in-db@example.org"},
            changed_fields=[{
                "field": "current_membership_status_id",
                "old": self.ACTIVE_STATUS_ID,
                "new": self.TERMINATED_STATUS_ID,
            }],
        )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("no linked member", result["message"].lower())

    def test_skips_when_member_already_terminal(self):
        member = self.factory.create_member(
            first_name="Already",
            last_name="Quit",
            email="already-quit@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)
        frappe.db.set_value("Member", member.name, "status", "Quit", update_modified=False)
        frappe.db.commit()

        event = self._make_event_mock(linked_member=member.name)
        result = get_termination_sync_service()._check_and_handle_termination(
            event,
            old_data={},
            new_data={"id": "MR-ALREADY-QUIT"},
            changed_fields=[{
                "field": "current_membership_status_id",
                "old": self.ACTIVE_STATUS_ID,
                "new": self.TERMINATED_STATUS_ID,
            }],
        )
        self.assertTrue(result["success"])
        self.assertIn("already has status Quit", result["message"])

    def test_happy_path_creates_and_executes_termination(self):
        member = self.factory.create_member(
            first_name="Term",
            last_name="Test",
            email="term-test@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)
        frappe.db.set_value("Member", member.name, "status", "Active", update_modified=False)
        frappe.db.commit()

        event = self._make_event_mock(linked_member=member.name)

        # Mock justified: Infrastructure - TerminationExecutionService is
        # covered by its own tests; we verify the service is called with
        # the right MTR doc, not what it does internally.
        with patch(
            "verenigingen.services.termination.TerminationExecutionService"
        ) as mock_term_svc:
            mock_term_svc.return_value.execute = MagicMock()
            result = get_termination_sync_service()._check_and_handle_termination(
                event,
                old_data={},
                new_data={"id": "MR-TERM-HAPPY"},
                changed_fields=[{
                    "field": "current_membership_status_id",
                    "old": self.ACTIVE_STATUS_ID,
                    "new": self.TERMINATED_STATUS_ID,
                }],
            )

        self.assertTrue(result["success"])
        # An MTR was created — find it via the member link
        mtrs = frappe.get_all(
            "Membership Termination Request",
            filters={"member": member.name},
            pluck="name",
        )
        self.assertEqual(len(mtrs), 1)
        self.addCleanup(self._cleanup_termination_request, mtrs[0])

        # Service was called with the MTR doc
        mock_term_svc.return_value.execute.assert_called_once()

        # Verify the MTR fields are set correctly
        mtr = frappe.get_doc("Membership Termination Request", mtrs[0])
        self.assertEqual(mtr.member, member.name)
        self.assertEqual(mtr.status, "Approved")
```

### Step 2: Run tests — expect `ModuleNotFoundError`

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_termination_sync_service
```

### Step 3: Create the service module

Create `verenigingen/mijnrood_sync/services/event_application/termination_sync_service.py`:

```python
"""MijnRoodTerminationSyncService — routes terminated-status transitions.

Extracted from event_application_service.py as Phase 1, PR #5 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service owns one method: _check_and_handle_termination. When a
MijnRood admin_member row transitions from an active to a terminated
status, it creates a Membership Termination Request and delegates
execution to TerminationExecutionService.
"""

import logging
from typing import Optional

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.mijnrood_sync.field_mapping import (
    get_active_status_ids,
    get_terminated_status_ids,
    get_termination_type_map,
)
from verenigingen.mijnrood_sync.utils import safe_int

logger = logging.getLogger("verenigingen.mijnrood_sync.event_application.termination_sync")


class MijnRoodTerminationSyncService:
    """Routes terminated-status transitions to MTR + TerminationExecutionService."""

    def __init__(self):
        self.logger = logger

    def _check_and_handle_termination(
        self,
        event,
        old_data: dict,
        new_data: dict,
        changed_fields: list,
    ) -> Optional[dict]:
        """Check if this change involves a status transition to terminated.

        If so, creates a Membership Termination Request using the existing
        workflow instead of directly setting the member status.

        Returns:
            Result dict if termination was handled, None otherwise
        """
        # Find the status field change
        status_change = None
        for change in changed_fields:
            if change.get("field") == "current_membership_status_id":
                status_change = change
                break

        if not status_change:
            return None

        old_status_id = safe_int(status_change.get("old"))
        new_status_id = safe_int(status_change.get("new"))

        # Only handle transitions FROM active TO terminated
        if new_status_id not in get_terminated_status_ids():
            return None
        if old_status_id not in get_active_status_ids():
            # Already in a non-active state, just update the status field
            return None

        # Find the linked member
        member_name = event.linked_member
        if not member_name:
            member_name = frappe.db.get_value("Member", {"member_id": new_data.get("id")}, "name")
        if not member_name:
            old_email = (old_data or {}).get("email")
            if old_email:
                member_name = frappe.db.get_value("Member", {"email": old_email}, "name")

        if not member_name:
            return {
                "success": False,
                "message": _(
                    "Cannot create termination request: no linked member for MijnRood ID {0}"
                ).format(new_data.get("id")),
            }

        member_doc = frappe.get_doc("Member", member_name)

        # Skip if member is already in a terminal state
        if member_doc.status in ("Quit", "Banned", "Deceased"):
            return {
                "success": True,
                "message": _("Member {0} already has status {1}, skipping termination").format(
                    member_name, member_doc.status
                ),
            }

        # Create Membership Termination Request
        termination_type = get_termination_type_map().get(new_status_id, "Administrative")

        termination_doc = frappe.new_doc("Membership Termination Request")
        termination_doc.member = member_name
        termination_doc.termination_type = termination_type
        termination_doc.termination_reason = (
            f"Detected via MijnRood sync (event {event.name}): " f"status changed to {new_status_id}"
        )
        termination_doc.request_date = today()
        termination_doc.termination_date = today()
        termination_doc.notes = (
            f"Auto-created from MijnRood sync event {event.name}. "
            f"MijnRood status changed from {old_status_id} to {new_status_id}."
        )

        # For Voluntary and Deceased, set member_request_date
        if termination_type in ("Voluntary", "Deceased"):
            termination_doc.member_request_date = today()

        # Pre-approve since this is a sync from the authoritative system
        termination_doc.status = "Approved"
        termination_doc._csv_import = True  # Bypass workflow validation
        termination_doc.flags.skip_termination_validation = (
            True  # System-initiated, skip commitment/doc checks
        )

        # Security: System-initiated termination from authoritative MijnRood data
        termination_doc.insert(ignore_permissions=True)
        self.logger.info(
            "Created termination request %s for member %s (type=%s)",
            termination_doc.name,
            member_name,
            termination_type,
        )

        # Auto-execute: MijnRood is authoritative, termination already happened there
        from verenigingen.services.termination import TerminationExecutionService

        try:
            TerminationExecutionService().execute(termination_doc)
            self.logger.info(
                "Executed termination %s for member %s",
                termination_doc.name,
                member_name,
            )
        except Exception as e:
            self.logger.error(
                "Termination request %s created but execution failed: %s",
                termination_doc.name,
                e,
            )
            frappe.log_error(
                frappe.get_traceback(),
                f"MijnRood Termination Execution Failed: {termination_doc.name}",
            )
            return {
                "success": False,
                "message": _("Termination request {0} created but execution failed: {1}").format(
                    termination_doc.name, str(e)
                ),
            }

        return {
            "success": True,
            "message": _("Termination request {0} executed for member {1} (type: {2})").format(
                termination_doc.name, member_name, termination_type
            ),
        }


_service_instance: Optional[MijnRoodTerminationSyncService] = None


def get_termination_sync_service() -> MijnRoodTerminationSyncService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodTerminationSyncService()
    return _service_instance
```

### Step 4: Run tests — expect 6 pass

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_termination_sync_service
```

### Step 5: Wire god-class

Open `verenigingen/mijnrood_sync/services/event_application_service.py`. Add to the imports near the other event_application service imports:

```python
from verenigingen.mijnrood_sync.services.event_application.termination_sync_service import (
    get_termination_sync_service,
)
```

Replace the body of `_check_and_handle_termination` (around line 756). The method has 5 parameters: `(self, event, old_data, new_data, changed_fields)`. The shim body is one line:

```python
        return get_termination_sync_service()._check_and_handle_termination(
            event, old_data, new_data, changed_fields
        )
```

Preserve the method signature and docstring.

### Step 6: Clean up orphaned imports in god-class

Run:
```bash
grep -c "get_active_status_ids\|get_terminated_status_ids\|get_termination_type_map" verenigingen/mijnrood_sync/services/event_application_service.py
```

If any of these symbols are now unused (count is 0 or only import line), drop them from the `from verenigingen.mijnrood_sync.field_mapping import (...)` block.

### Step 7: Verify file parses

```bash
cd ~/frappe-bench && env/bin/python -c "import ast; ast.parse(open('apps/verenigingen/verenigingen/mijnrood_sync/services/event_application_service.py').read()); print('OK')"
```

### Step 8: Run all tests

```bash
# New PR #5 tests
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_termination_sync_service

# PR #1-4 regression
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_volunteer_sync_service
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_application_sync_service
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_member_sync_service
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_mapping_service

# Existing mocked baseline
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.test_event_application_service
```

Expected: 6/6 new, 44/22/10/16 PR #4-1 regression, 140/150 mocked baseline preserved. If existing mocked tests fail (specifically `TestCheckAndHandleTermination.test_*`), retarget mocks following the established pattern:
- `patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")` → `patch("verenigingen.mijnrood_sync.services.event_application.termination_sync_service.frappe")` for tests of this method
- `patch.object(MijnRoodEventApplicationService, "_check_and_handle_termination")` keeps working (shim still exists)

### Step 9: Pre-commit + commit + push

```bash
cd ~/frappe-bench/apps/verenigingen && pre-commit run --files \
  verenigingen/mijnrood_sync/services/event_application_service.py \
  verenigingen/mijnrood_sync/services/event_application/termination_sync_service.py \
  verenigingen/tests/services/event_application/test_termination_sync_service.py

# Include retargeted mocked tests if step 8 required them
git add verenigingen/mijnrood_sync/services/event_application/termination_sync_service.py \
        verenigingen/tests/services/event_application/test_termination_sync_service.py \
        verenigingen/mijnrood_sync/services/event_application_service.py
# git add verenigingen/tests/services/test_event_application_service.py  # if retargeted
git commit -m "$(cat <<'EOF'
refactor(mijnrood-sync): extract termination sync to MijnRoodTerminationSyncService

Moves _check_and_handle_termination (~130 LOC) from the god-class to a
new MijnRoodTerminationSyncService. The god-class shrinks by ~130 LOC
and keeps a one-line shim so existing dispatcher call sites (from PR
#2's apply_changed_member via the orchestrator) continue to work.

No orchestrator parameter needed — the method has no cross-cutting deps
beyond TerminationExecutionService (already its own service).

This is Phase 1, PR #5 of the Tier C decomposition documented at
docs/plans/2026-05-12-event-application-service-refactor-design.md.
EOF
)"

SKIP=jest-testing,javascript-doctype-validator git push
```

---

## Success Criteria

1. `verenigingen/mijnrood_sync/services/event_application/termination_sync_service.py` exists with `MijnRoodTerminationSyncService` + `get_termination_sync_service`.
2. `event_application_service.py` retains a 3-line shim for `_check_and_handle_termination`.
3. 6 new termination-sync tests pass against a real DB. MagicMock used only for `TerminationExecutionService` (justified — covered by its own tests).
4. PR #1-4 regression tests still pass.
5. `test_event_application_service.py` baseline (140/150) preserved; any new failures resolved via minimal mock retargeting.
6. Pre-commit hooks pass on every touched file.
7. God-class LOC count drops by ~130 (from 1,437 to ~1,307).
