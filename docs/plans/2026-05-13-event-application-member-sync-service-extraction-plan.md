# Event Application — Member Sync Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract member-sync concerns (`_find_existing_member_or_conflict`, `_apply_new_member`, `_apply_changed_member`) from `event_application_service.py` (currently 2,345 LOC god-class) into a new `MijnRoodMemberSyncService` under `mijnrood_sync/services/event_application/`. This is Phase 1, PR #2 of the Tier C refactor.

**Architecture:** New `member_sync_service.py` module housing the `MijnRoodMemberSyncService` class (3 methods) and a `get_member_sync_service()` singleton accessor. The god-class loses ~160 LOC and gains delegation seams via the singleton. The extracted methods accept the calling event-application orchestrator as an explicit parameter so they can call cross-cutting helpers (`_create_related_records`, `_process_member_roles`, `_check_and_handle_termination`, `_try_promote_application`, `_handle_division_field_change`) that have not yet been extracted. This parameter is removed in later PRs as those helpers move to their own services.

**Tech Stack:** Frappe Framework, Python 3.12+, pytest via `bench run-tests`, `EnhancedTestCase` for real-DB integration tests.

**Reference spec:** `docs/plans/2026-05-12-event-application-service-refactor-design.md`

**Note on `_apply_deleted_member`:** The spec lists it as in scope for this PR. The current code only has a generic table-agnostic `_apply_deleted` (lines 1100-1108) that returns a fixed "manual review required" message — there is no per-table dispatch for deletes. Treat this as a no-op: leave `_apply_deleted` in the god-class; PR #7 (dispatcher) will deal with it.

---

## File Structure

**Create:**
- `verenigingen/mijnrood_sync/services/event_application/member_sync_service.py` — `MijnRoodMemberSyncService` + `get_member_sync_service`
- `verenigingen/tests/services/event_application/test_member_sync_service.py` — real-DB integration tests

**Modify:**
- `verenigingen/mijnrood_sync/services/event_application_service.py` — delete the three extracted methods; replace their call sites with delegations to `get_member_sync_service()`

**Do not touch:**
- `verenigingen/tests/services/test_event_application_service.py` — existing mocked tests must keep passing
- `verenigingen/mijnrood_sync/services/event_application/mapping_service.py` — PR #1, already shipped
- `verenigingen/mijnrood_sync/services/event_application/__init__.py` — already scaffolded
- `_set_application_fields`, `_promote_application_member`, `_try_promote_application`, `_check_and_handle_termination`, `_handle_division_field_change`, `_create_related_records`, `_process_member_roles` — these are cross-cutting helpers owned by later PRs (or unassigned). They stay in the god-class for now.

---

## Task 1: Write failing tests for `find_existing_member_or_conflict`

**Files:**
- Create: `verenigingen/tests/services/event_application/test_member_sync_service.py`

- [ ] **Step 1: Write the failing test file**

Write `verenigingen/tests/services/event_application/test_member_sync_service.py`:

```python
"""Real-DB integration tests for MijnRoodMemberSyncService.

find_existing_member_or_conflict is a pure DB lookup — exercised against
real Member rows created via the factory. apply_new_member and
apply_changed_member integrate against MijnRood Sync Event +
MemberImportService and use a stub orchestrator for the not-yet-extracted
cross-cutting helpers (create_related_records, process_member_roles,
try_promote_application, check_and_handle_termination,
handle_division_field_change).
"""

import frappe

from verenigingen.mijnrood_sync.services.event_application.member_sync_service import (
    get_member_sync_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFindExistingMemberOrConflict(EnhancedTestCase):
    """Lookup-by-member_id-then-email-then-conflict logic."""

    def test_returns_none_when_no_member_matches(self):
        result_name, result_dict = get_member_sync_service().find_existing_member_or_conflict(
            mijnrood_id="999999999", email="ghost-does-not-exist@example.org"
        )
        self.assertIsNone(result_name)
        self.assertIsNone(result_dict)

    def test_matches_by_member_id_first(self):
        member = self.factory.create_member(
            first_name="Bob",
            last_name="Example",
            email="bob-mid@example.org",
            member_id="MR-12345",
        )

        name, result = get_member_sync_service().find_existing_member_or_conflict(
            mijnrood_id="MR-12345", email="completely-different@example.org"
        )

        self.assertEqual(name, member.name)
        self.assertTrue(result["success"])
        self.assertIn("MR-12345", result["message"])

    def test_matches_by_email_when_member_id_absent(self):
        member = self.factory.create_member(
            first_name="Carol",
            last_name="Example",
            email="carol-email@example.org",
        )

        name, result = get_member_sync_service().find_existing_member_or_conflict(
            mijnrood_id=None, email="carol-email@example.org"
        )

        self.assertEqual(name, member.name)
        self.assertTrue(result["success"])

    def test_email_match_with_conflicting_member_id_returns_conflict(self):
        self.factory.create_member(
            first_name="Dan",
            last_name="Example",
            email="dan-conflict@example.org",
            member_id="MR-AAA",
        )

        name, result = get_member_sync_service().find_existing_member_or_conflict(
            mijnrood_id="MR-BBB", email="dan-conflict@example.org"
        )

        self.assertIsNone(name)
        self.assertFalse(result["success"])
        self.assertIn("MR-AAA", result["message"])
        self.assertIn("MR-BBB", result["message"])
```

- [ ] **Step 2: Run the tests to verify they fail with import error**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_member_sync_service
```
Expected: `ModuleNotFoundError` / `ImportError` on `verenigingen.mijnrood_sync.services.event_application.member_sync_service`.

---

## Task 2: Implement `find_existing_member_or_conflict` + service skeleton

**Files:**
- Create: `verenigingen/mijnrood_sync/services/event_application/member_sync_service.py`

- [ ] **Step 1: Write the minimal module**

Write `verenigingen/mijnrood_sync/services/event_application/member_sync_service.py`:

```python
"""MijnRoodMemberSyncService — applies MijnRood member events to Member rows.

Extracted from event_application_service.py as Phase 1, PR #2 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service owns the New-Member and Changed-Member event paths plus the
existing-member-or-conflict lookup. It delegates back to the calling
event-application orchestrator for cross-cutting helpers
(create_related_records, process_member_roles, try_promote_application,
check_and_handle_termination, handle_division_field_change) that have
not yet been extracted into their own services. The `orchestrator`
parameter on the public methods will be removed once all of those are
moved to their own services in later PRs.
"""

import logging
from typing import Optional

import frappe
from frappe import _

logger = logging.getLogger("verenigingen.mijnrood_sync.event_application.member_sync")


class MijnRoodMemberSyncService:
    """Applies MijnRood member events to Member rows.

    Stateful only insofar as it is a singleton — no per-instance state.
    """

    def find_existing_member_or_conflict(
        self, mijnrood_id, email
    ) -> tuple[Optional[str], Optional[dict]]:
        """Look up existing member by member_id (authoritative) then email.

        Returns:
            (member_name, result_dict) — found or conflict
            (None, None) — no match
        """
        if mijnrood_id:
            existing = frappe.db.get_value("Member", {"member_id": str(mijnrood_id)}, "name")
            if existing:
                return existing, {
                    "success": True,
                    "message": _("Member {0} already exists (member_id={1})").format(
                        existing, mijnrood_id
                    ),
                }
        if email:
            match = frappe.db.get_value(
                "Member", {"email": email}, ["name", "member_id"], as_dict=True
            )
            if match:
                if match.member_id and mijnrood_id and str(match.member_id) != str(mijnrood_id):
                    return None, {
                        "success": False,
                        "message": _(
                            "Email {0} already used by {1} (member_id={2}), "
                            "conflicts with MijnRood ID {3}"
                        ).format(email, match.name, match.member_id, mijnrood_id),
                    }
                return match.name, {
                    "success": True,
                    "message": _("Member {0} already exists (email={1})").format(
                        match.name, email
                    ),
                }
        return None, None


_service_instance: Optional[MijnRoodMemberSyncService] = None


def get_member_sync_service() -> MijnRoodMemberSyncService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodMemberSyncService()
    return _service_instance
```

- [ ] **Step 2: Run the tests to verify they pass**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_member_sync_service
```
Expected: 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/member_sync_service.py \
        verenigingen/tests/services/event_application/test_member_sync_service.py
git commit -m "feat(mijnrood-sync): scaffold MijnRoodMemberSyncService with find_existing_member_or_conflict"
```

---

## Task 3: Write failing tests for `apply_new_member`

**Files:**
- Modify: `verenigingen/tests/services/event_application/test_member_sync_service.py`

The service method takes an `orchestrator` parameter that exposes the not-yet-extracted helpers. For these tests use a `_FakeOrchestrator` stub that records calls and returns sane defaults — this isolates the test from the rest of the god-class.

- [ ] **Step 1: Append the fake orchestrator + happy-path tests**

Add to `verenigingen/tests/services/event_application/test_member_sync_service.py`:

```python
import json
from unittest.mock import MagicMock


class _FakeOrchestrator:
    """Stand-in for MijnRoodEventApplicationService.

    Records calls to the cross-cutting helpers that haven't been
    extracted yet (related records, role processing, promotion fallback,
    termination handling, chapter reassignment). Each helper returns a
    safe default unless overridden per-test.
    """

    def __init__(self):
        self._create_related_records = MagicMock(return_value=[])
        self._process_member_roles = MagicMock(return_value=[])
        self._try_promote_application = MagicMock(return_value=None)
        self._check_and_handle_termination = MagicMock(return_value=None)
        self._handle_division_field_change = MagicMock(return_value=None)


def _make_event(
    *,
    table: str = "admin_member",
    event_type: str = "New",
    new_data: dict | None = None,
    old_data: dict | None = None,
    changed_fields: list | None = None,
) -> "frappe.Document":
    """Insert a MijnRood Sync Event doc and return it."""
    doc = frappe.get_doc({
        "doctype": "MijnRood Sync Event",
        "mijnrood_table": table,
        "mijnrood_event_type": event_type,
        "status": "Approved",
        "new_data": json.dumps(new_data or {}),
        "old_data": json.dumps(old_data or {}),
        "changed_fields": json.dumps(changed_fields or []),
    }).insert(ignore_permissions=True)
    return doc


class TestApplyNewMember(EnhancedTestCase):
    """Happy path, idempotent re-apply, and promotion fallback."""

    def setUp(self):
        super().setUp()
        # Status mapping needed so map_member_fields doesn't raise
        settings = frappe.get_single("MijnRood Sync Settings")
        self._original_status_mapping = list(settings.status_mapping or [])
        membership_type = self.factory.ensure_membership_type("Member Sync Test Type")
        settings.append("status_mapping", {
            "mijnrood_status_id": 7001,
            "label": "Member Sync Test",
            "membership_type_string": "test",
            "is_active": 1,
            "verenigingen_membership_type": membership_type.name,
        })
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache().delete_value("mijnrood_status_mapping")

        def _restore():
            s = frappe.get_single("MijnRood Sync Settings")
            s.status_mapping = self._original_status_mapping
            s.save(ignore_permissions=True)
            frappe.db.commit()
            frappe.cache().delete_value("mijnrood_status_mapping")

        self.addCleanup(_restore)

    def test_creates_new_member_when_none_exists(self):
        event = _make_event(new_data={
            "id": "MR-NEW-1",
            "first_name": "Eve",
            "last_name": "NewMember",
            "email": "eve-new@example.org",
            "current_membership_status_id": 7001,
        })
        self.addCleanup(lambda: frappe.delete_doc(
            "MijnRood Sync Event", event.name, ignore_permissions=True, force=True
        ))

        orchestrator = _FakeOrchestrator()
        result = get_member_sync_service().apply_new_member(event, orchestrator)

        self.assertTrue(result["success"])
        self.assertTrue(event.linked_member)
        # Verify the Member row was created
        member = frappe.db.get_value(
            "Member", {"member_id": "MR-NEW-1"}, ["first_name", "last_name", "email"], as_dict=True
        )
        self.assertEqual(member.first_name, "Eve")
        self.assertEqual(member.email, "eve-new@example.org")
        # Cross-cutting helpers were called
        orchestrator._create_related_records.assert_called_once()
        orchestrator._process_member_roles.assert_called_once()

    def test_idempotent_when_member_already_exists_by_member_id(self):
        existing = self.factory.create_member(
            first_name="Frank",
            last_name="Existing",
            email="frank-existing@example.org",
            member_id="MR-EXIST-1",
        )

        event = _make_event(new_data={
            "id": "MR-EXIST-1",
            "first_name": "Frank",
            "last_name": "Existing",
            "email": "frank-existing@example.org",
            "current_membership_status_id": 7001,
        })
        self.addCleanup(lambda: frappe.delete_doc(
            "MijnRood Sync Event", event.name, ignore_permissions=True, force=True
        ))

        orchestrator = _FakeOrchestrator()
        result = get_member_sync_service().apply_new_member(event, orchestrator)

        self.assertTrue(result["success"])
        self.assertIn("already exists", result["message"])
        self.assertEqual(event.linked_member, existing.name)
        # No new member was created; cross-cutting helpers were NOT called
        orchestrator._create_related_records.assert_not_called()
        orchestrator._process_member_roles.assert_not_called()

    def test_email_conflict_invokes_promotion_fallback(self):
        # Pre-existing member with a different MijnRood id but same email
        # — simulates an application that was promoted on the MijnRood side
        # but never correlated on our end.
        self.factory.create_member(
            first_name="Grace",
            last_name="Promotable",
            email="grace-promo@example.org",
            member_id="MR-OLD-9",
        )

        event = _make_event(new_data={
            "id": "MR-NEW-9",
            "first_name": "Grace",
            "last_name": "Promotable",
            "email": "grace-promo@example.org",
            "current_membership_status_id": 7001,
        })
        self.addCleanup(lambda: frappe.delete_doc(
            "MijnRood Sync Event", event.name, ignore_permissions=True, force=True
        ))

        orchestrator = _FakeOrchestrator()
        orchestrator._try_promote_application = MagicMock(
            return_value={"success": True, "message": "Promoted via test stub"}
        )

        result = get_member_sync_service().apply_new_member(event, orchestrator)

        self.assertTrue(result["success"])
        self.assertIn("Promoted", result["message"])
        orchestrator._try_promote_application.assert_called_once()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_member_sync_service
```
Expected: `AttributeError: 'MijnRoodMemberSyncService' object has no attribute 'apply_new_member'` on the 3 new tests; the 4 lookup tests still pass.

---

## Task 4: Implement `apply_new_member`

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application/member_sync_service.py`

- [ ] **Step 1: Add the method**

Add to `verenigingen/mijnrood_sync/services/event_application/member_sync_service.py`:

- Insert this near the existing imports (after `from frappe import _`):

```python
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    get_mapping_service,
)
from verenigingen.mijnrood_sync.utils import safe_json_load
```

- Add the `apply_new_member` method to `MijnRoodMemberSyncService` (after `find_existing_member_or_conflict`):

```python
    def apply_new_member(self, event, orchestrator) -> dict:
        """Create a new Member from MijnRood admin_member data.

        Transitional `orchestrator` parameter exposes the not-yet-extracted
        cross-cutting helpers (_try_promote_application,
        _create_related_records, _process_member_roles). This parameter
        will be removed once those helpers are extracted in later PRs.
        """
        new_data = safe_json_load(event.new_data)
        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        row_data = get_mapping_service().map_member_fields(new_data)

        # Idempotency — member_id is authoritative, email is fallback
        existing_name, existing_result = self.find_existing_member_or_conflict(
            row_data.get("member_id"), row_data.get("email")
        )
        if existing_result is not None:
            # Check for application→member promotion: MijnRood deletes the
            # application row and creates a new member row with a different ID.
            # find_existing_member_or_conflict sees this as a conflict (email
            # match, member_id mismatch). If the existing member is a pending
            # application, this is actually a promotion, not a conflict.
            if not existing_result.get("success") and row_data.get("email"):
                promotion_result = orchestrator._try_promote_application(event, row_data)
                if promotion_result:
                    return promotion_result

            if existing_name:
                event.linked_member = existing_name
            return existing_result

        # Use MemberImportService for consistent creation logic
        from verenigingen.services.csv_import.member_import_service import (
            get_member_import_service,
        )

        service = get_member_import_service()
        status, member_name = service.create_or_update_member(
            row_data=row_data,
            import_doc_name=f"MijnRood Sync: {event.name}",
        )

        if status in ("created", "updated"):
            event.linked_member = member_name

            related_msgs = orchestrator._create_related_records(member_name, row_data, event)
            role_msgs = orchestrator._process_member_roles(member_name, new_data, event=event)
            related_msgs.extend(role_msgs)

            messages = [_("Member {0} {1}").format(member_name, status)]
            messages.extend(related_msgs)
            return {"success": True, "message": "; ".join(messages)}
        else:
            return {"success": False, "message": _("Member creation {0}").format(status)}
```

- [ ] **Step 2: Run the tests to verify they pass**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_member_sync_service
```
Expected: 7 tests pass (4 lookup + 3 apply_new_member).

- [ ] **Step 3: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/member_sync_service.py \
        verenigingen/tests/services/event_application/test_member_sync_service.py
git commit -m "feat(mijnrood-sync): add apply_new_member to MijnRoodMemberSyncService"
```

---

## Task 5: Write failing tests for `apply_changed_member`

**Files:**
- Modify: `verenigingen/tests/services/event_application/test_member_sync_service.py`

- [ ] **Step 1: Append the test class**

Add to `verenigingen/tests/services/event_application/test_member_sync_service.py`:

```python
class TestApplyChangedMember(EnhancedTestCase):
    """Field update happy path, termination short-circuit, and missing-member error."""

    def setUp(self):
        super().setUp()
        settings = frappe.get_single("MijnRood Sync Settings")
        self._original_status_mapping = list(settings.status_mapping or [])
        membership_type = self.factory.ensure_membership_type("Member Sync Change Test Type")
        settings.append("status_mapping", {
            "mijnrood_status_id": 7002,
            "label": "Member Sync Change Test",
            "membership_type_string": "test",
            "is_active": 1,
            "verenigingen_membership_type": membership_type.name,
        })
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache().delete_value("mijnrood_status_mapping")

        def _restore():
            s = frappe.get_single("MijnRood Sync Settings")
            s.status_mapping = self._original_status_mapping
            s.save(ignore_permissions=True)
            frappe.db.commit()
            frappe.cache().delete_value("mijnrood_status_mapping")

        self.addCleanup(_restore)

    def test_updates_existing_member_fields(self):
        member = self.factory.create_member(
            first_name="Henry",
            last_name="OldName",
            email="henry-change@example.org",
            member_id="MR-CHG-1",
        )

        event = _make_event(
            event_type="Changed",
            new_data={
                "id": "MR-CHG-1",
                "first_name": "Henry",
                "last_name": "NewName",
                "email": "henry-change@example.org",
                "current_membership_status_id": 7002,
            },
            old_data={"id": "MR-CHG-1", "last_name": "OldName"},
            changed_fields=["last_name"],
        )
        event.linked_member = member.name
        event.save(ignore_permissions=True)
        self.addCleanup(lambda: frappe.delete_doc(
            "MijnRood Sync Event", event.name, ignore_permissions=True, force=True
        ))

        orchestrator = _FakeOrchestrator()
        result = get_member_sync_service().apply_changed_member(event, orchestrator)

        self.assertTrue(result["success"])
        updated_last = frappe.db.get_value("Member", member.name, "last_name")
        self.assertEqual(updated_last, "NewName")

    def test_termination_short_circuits_field_update(self):
        member = self.factory.create_member(
            first_name="Iris",
            last_name="Terminator",
            email="iris-term@example.org",
            member_id="MR-CHG-2",
        )

        event = _make_event(
            event_type="Changed",
            new_data={
                "id": "MR-CHG-2",
                "current_membership_status_id": 7002,
            },
            old_data={"id": "MR-CHG-2"},
            changed_fields=["current_membership_status_id"],
        )
        event.linked_member = member.name
        event.save(ignore_permissions=True)
        self.addCleanup(lambda: frappe.delete_doc(
            "MijnRood Sync Event", event.name, ignore_permissions=True, force=True
        ))

        orchestrator = _FakeOrchestrator()
        orchestrator._check_and_handle_termination = MagicMock(
            return_value={"success": True, "message": "Termination handled (stub)"}
        )

        result = get_member_sync_service().apply_changed_member(event, orchestrator)

        self.assertTrue(result["success"])
        self.assertIn("Termination handled", result["message"])
        # Other helpers should NOT have been called because termination short-circuited
        orchestrator._process_member_roles.assert_not_called()
        orchestrator._create_related_records.assert_not_called()

    def test_returns_failure_when_no_linked_member_found(self):
        event = _make_event(
            event_type="Changed",
            new_data={
                "id": "MR-CHG-MISSING",
                "current_membership_status_id": 7002,
            },
        )
        self.addCleanup(lambda: frappe.delete_doc(
            "MijnRood Sync Event", event.name, ignore_permissions=True, force=True
        ))

        orchestrator = _FakeOrchestrator()
        result = get_member_sync_service().apply_changed_member(event, orchestrator)

        self.assertFalse(result["success"])
        self.assertIn("No linked member found", result["message"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_member_sync_service
```
Expected: `AttributeError: 'MijnRoodMemberSyncService' object has no attribute 'apply_changed_member'` on the 3 new tests.

---

## Task 6: Implement `apply_changed_member`

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application/member_sync_service.py`

- [ ] **Step 1: Add the method**

Add to `verenigingen/mijnrood_sync/services/event_application/member_sync_service.py` (after `apply_new_member`):

```python
    def apply_changed_member(self, event, orchestrator) -> dict:
        """Update existing Member fields from MijnRood admin_member data.

        For status changes to terminated statuses, delegates to the
        orchestrator's _check_and_handle_termination which creates a
        Membership Termination Request rather than directly modifying
        the member.

        Transitional `orchestrator` parameter: see apply_new_member.
        """
        new_data = safe_json_load(event.new_data)
        old_data = safe_json_load(event.old_data)
        changed_fields = safe_json_load(event.changed_fields, default=[])

        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        # Check for status change to a terminated status — short-circuits the rest
        termination_result = orchestrator._check_and_handle_termination(
            event, old_data, new_data, changed_fields
        )
        if termination_result is not None:
            return termination_result

        # Resolve linked member: event link → member_id → old email
        member_name = event.linked_member
        if not member_name:
            member_name = frappe.db.get_value(
                "Member", {"member_id": new_data.get("id")}, "name"
            )
        if not member_name:
            old_email = (old_data or {}).get("email")
            if old_email:
                member_name = frappe.db.get_value(
                    "Member", {"email": old_email}, "name"
                )

        if not member_name:
            return {
                "success": False,
                "message": _("No linked member found for MijnRood ID {0}").format(
                    new_data.get("id")
                ),
            }

        # Chapter transfer if division_id changed
        chapter_result = orchestrator._handle_division_field_change(
            member_name, changed_fields, event, field_name="division_id"
        )

        row_data = get_mapping_service().map_member_fields(new_data)

        messages = []
        if chapter_result:
            messages.append(chapter_result)

        # Role-only events (e.g. synthetic division contact changes) carry only
        # managed_division_ids / roles — no mappable member fields. Skip the
        # member create/update path and go straight to role processing.
        if row_data:
            from verenigingen.services.csv_import.member_import_service import (
                get_member_import_service,
            )

            service = get_member_import_service()
            status, updated_name = service.create_or_update_member(
                row_data=row_data,
                import_doc_name=f"MijnRood Sync: {event.name}",
            )

            if status in ("created", "updated"):
                event.linked_member = updated_name
                member_name = updated_name
                messages.append(_("Member {0} updated").format(updated_name))

                messages.extend(
                    orchestrator._create_related_records(updated_name, row_data, event)
                )
            else:
                return {"success": False, "message": _("Member update {0}").format(status)}

        role_msgs = orchestrator._process_member_roles(
            member_name, new_data, old_data=old_data, event=event
        )
        messages.extend(role_msgs)

        return {
            "success": True,
            "message": "; ".join(messages) if messages else _("No changes applied"),
        }
```

- [ ] **Step 2: Run the tests to verify they pass**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_member_sync_service
```
Expected: 10 tests pass (4 lookup + 3 apply_new_member + 3 apply_changed_member).

- [ ] **Step 3: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/member_sync_service.py \
        verenigingen/tests/services/event_application/test_member_sync_service.py
git commit -m "feat(mijnrood-sync): add apply_changed_member to MijnRoodMemberSyncService"
```

---

## Task 7: Wire the new service into the god-class

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application_service.py`

- [ ] **Step 1: Add the import**

Open `verenigingen/mijnrood_sync/services/event_application_service.py`. Near the existing `from verenigingen.mijnrood_sync.services.event_application.mapping_service import (...)` block, add:

```python
from verenigingen.mijnrood_sync.services.event_application.member_sync_service import (
    get_member_sync_service,
)
```

- [ ] **Step 2: Replace the body of `_apply_new_member` with a delegation shim**

Find `def _apply_new_member(self, event) -> dict:` (around line 705). Replace its entire body (lines 706-757) — i.e. everything indented under the method header — with:

```python
        return get_member_sync_service().apply_new_member(event, self)
```

The method now reads:

```python
    def _apply_new_member(self, event) -> dict:
        """Create a new Member from MijnRood admin_member data."""
        return get_member_sync_service().apply_new_member(event, self)
```

- [ ] **Step 3: Replace the body of `_apply_changed_member` with a delegation shim**

Find `def _apply_changed_member(self, event) -> dict:` (around line 949). Replace its entire body (everything indented under the method header) with:

```python
        return get_member_sync_service().apply_changed_member(event, self)
```

- [ ] **Step 4: Replace the body of `_find_existing_member_or_conflict` with a delegation shim**

Find `def _find_existing_member_or_conflict(self, mijnrood_id, email)` (around line 135). Replace its entire body with:

```python
        return get_member_sync_service().find_existing_member_or_conflict(mijnrood_id, email)
```

The method stays in the god-class because `_apply_changed_membership_application` (PR #3 territory) still calls `self._find_existing_member_or_conflict(...)`. The shim lets the existing call sites keep working.

- [ ] **Step 5: Verify the file parses**

Run:
```bash
cd ~/frappe-bench && env/bin/python -c "import ast; ast.parse(open('apps/verenigingen/verenigingen/mijnrood_sync/services/event_application_service.py').read()); print('OK')"
```
Expected: `OK`.

- [ ] **Step 6: Confirm no orphaned imports**

Run:
```bash
grep -n "from verenigingen.mijnrood_sync.utils import safe_json_load\|safe_json_load" \
  /home/frappeuser/frappe-bench/apps/verenigingen/verenigingen/mijnrood_sync/services/event_application_service.py | head -5
```

`safe_json_load` is still used by other handlers (`_apply_new_division`, `_apply_changed_membership_application`, `_apply_approved`, etc.) — leave the import alone.

---

## Task 8: Verify all tests still pass

- [ ] **Step 1: Run the new member sync service tests**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_member_sync_service
```
Expected: 10 tests pass.

- [ ] **Step 2: Run the existing mocked event_application_service tests**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.test_event_application_service
```
Expected: All existing tests pass. (If any directly mocked `service._apply_new_member`, `service._apply_changed_member`, or `service._find_existing_member_or_conflict` and asserted on internal behaviour rather than the return value, those mocks may need to be retargeted at the orchestrator-callable level.)

- [ ] **Step 3: If any existing tests failed — fix them**

For each failing test, the typical fix is to update the mock target. The shim methods on the god-class still exist with the same signatures, so any test that mocked them via `patch.object(service, "_apply_new_member")` should keep working. Tests that monkeypatched inner helpers may need:
- `service._find_existing_member_or_conflict` → patch the underlying service: `verenigingen.mijnrood_sync.services.event_application.member_sync_service.MijnRoodMemberSyncService.find_existing_member_or_conflict`

- [ ] **Step 4: Run the broader sync test surface**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.mijnrood_sync
```
Expected: All MijnRood Sync tests pass.

- [ ] **Step 5: Run the mapping service tests (PR #1 regression check)**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_mapping_service
```
Expected: 16 tests pass.

---

## Task 9: Commit the wiring + final polish

- [ ] **Step 1: Run pre-commit checks**

Run:
```bash
cd ~/frappe-bench/apps/verenigingen && pre-commit run --files \
  verenigingen/mijnrood_sync/services/event_application_service.py \
  verenigingen/mijnrood_sync/services/event_application/member_sync_service.py \
  verenigingen/tests/services/event_application/test_member_sync_service.py
```
Expected: All hooks pass.

- [ ] **Step 2: Commit the wiring**

```bash
git add verenigingen/mijnrood_sync/services/event_application_service.py
git commit -m "$(cat <<'EOF'
refactor(mijnrood-sync): delegate member sync to MijnRoodMemberSyncService

Replaces the bodies of _find_existing_member_or_conflict,
_apply_new_member, and _apply_changed_member with one-line delegations
to the new MijnRoodMemberSyncService. The god-class shrinks by ~160
LOC; the shim methods stay so existing call sites in the dispatcher
and _apply_changed_membership_application continue to work without
import-path churn.

This is Phase 1, PR #2 of the Tier C decomposition documented at
docs/plans/2026-05-12-event-application-service-refactor-design.md.
EOF
)"
```

- [ ] **Step 3: Push**

```bash
SKIP=jest-testing,javascript-doctype-validator git push
```

---

## Success Criteria (this PR)

1. `verenigingen/mijnrood_sync/services/event_application/member_sync_service.py` exists with `MijnRoodMemberSyncService` (3 methods: `find_existing_member_or_conflict`, `apply_new_member`, `apply_changed_member`) and `get_member_sync_service`.
2. `event_application_service.py` retains shim methods `_find_existing_member_or_conflict`, `_apply_new_member`, `_apply_changed_member`, each ≤ 3 lines, delegating to the service.
3. All 10 new member-sync-service tests pass against a real DB via `EnhancedTestCase` (no `MagicMock(frappe)` — only stubs for the not-yet-extracted orchestrator methods).
4. All existing mocked tests in `test_event_application_service.py` continue to pass (or are minimally edited to retarget mocks).
5. `bench run-tests --module verenigingen.mijnrood_sync` passes end-to-end.
6. PR #1 mapping-service tests still pass (16/16) — no regression in the prior extraction.
7. Pre-commit hooks pass on every touched file.
