# MijnRood Application → Member Approval Correlation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the `admin_membership_application` Deleted + `admin_member` New event pair, emitted by MijnRood when an applicant is approved, into a single `Approved` sync event — and fix the missing `member.status = "Active"` flip that prevents Membership + Dues Schedule creation on promotion.

**Architecture:** A new in-run correlator runs after all tables poll; it pairs matching events by Mollie ID (primary) or email + last-name (fallback), emits one synthesized `Approved` event, and marks the two raw events `Ignored`. A new `_apply_approved` handler promotes the existing Pending Member and drives all downstream side effects through a shared `_promote_application_member` helper. The existing `_try_promote_application` stays as a cross-run safety net.

**Tech Stack:** Frappe Framework (Python), existing `verenigingen/mijnrood_sync` services, existing `MijnRood Sync Event` DocType.

**Design doc:** `docs/plans/2026-04-18-mijnrood-application-approval-correlation-design.md`

---

## File Structure

**New files:**
- `verenigingen/mijnrood_sync/services/application_approval_correlator.py` — correlation logic (single responsibility: pair + collapse events within a sync run)
- `verenigingen/tests/services/test_application_approval_correlator.py` — unit tests for the correlator

**Modified files:**
- `verenigingen/mijnrood_sync/doctype/mijnrood_sync_event/mijnrood_sync_event.json` — add `Approved` to `event_type` Select options
- `verenigingen/mijnrood_sync/services/polling_service.py` — extend `compute_change_tags`, call correlator from `run_sync`
- `verenigingen/mijnrood_sync/services/event_application_service.py` — add `_apply_approved`, extract `_promote_application_member`, route `_try_promote_application` through it, update `apply_event` dispatch
- `verenigingen/tests/services/test_event_application_service.py` — add tests for `_apply_approved` + `_promote_application_member`
- `verenigingen/tests/services/test_polling_service.py` — add test for `compute_change_tags` and `run_sync` correlator wiring

Each file has one clear responsibility. The correlator is a pure function operating on already-persisted sync events — it can be tested in isolation.

---

## Task 1: Add `Approved` to event_type options

**Files:**
- Modify: `verenigingen/mijnrood_sync/doctype/mijnrood_sync_event/mijnrood_sync_event.json`

- [ ] **Step 1: Extend the event_type Select options**

Find the `event_type` field block (around line 44-51) and change its `options` value.

Current:
```json
    {
      "fieldname": "event_type",
      "fieldtype": "Select",
      "in_list_view": 1,
      "in_standard_filter": 1,
      "label": "Event Type",
      "options": "New\nChanged\nDeleted",
      "reqd": 1
    },
```

New:
```json
    {
      "fieldname": "event_type",
      "fieldtype": "Select",
      "in_list_view": 1,
      "in_standard_filter": 1,
      "label": "Event Type",
      "options": "New\nChanged\nDeleted\nApproved",
      "reqd": 1
    },
```

- [ ] **Step 2: Bump the `modified` timestamp**

Near the end of the JSON, update the `modified` field to today's date (format `YYYY-MM-DD HH:MM:SS`) — Frappe uses this to detect schema drift. Example: `"modified": "2026-04-18 10:00:00",`.

- [ ] **Step 3: Reload the DocType and clear cache**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org reload-doctype "MijnRood Sync Event" && bench --site veg11.veganisme.org clear-cache
```

Expected: `MijnRood Sync Event reloaded` and cache cleared, no errors.

- [ ] **Step 4: Verify new option is accepted**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org console <<'PY'
import frappe
meta = frappe.get_meta("MijnRood Sync Event")
opts = [f for f in meta.fields if f.fieldname == "event_type"][0].options
assert "Approved" in opts, f"Expected Approved in options, got: {opts}"
print("OK:", opts)
PY
```

Expected output contains `New`, `Changed`, `Deleted`, `Approved`.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/mijnrood_sync/doctype/mijnrood_sync_event/mijnrood_sync_event.json
git commit -m "feat(mijnrood_sync): add Approved event_type to MijnRood Sync Event"
```

---

## Task 2: Extend `compute_change_tags` for Approved events

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/polling_service.py` (lines 58-85)
- Test: `verenigingen/tests/services/test_polling_service.py`

- [ ] **Step 1: Write the failing test**

Append this to `verenigingen/tests/services/test_polling_service.py`:

```python
from verenigingen.mijnrood_sync.services.polling_service import compute_change_tags


class TestComputeChangeTags(EnhancedTestCase):
    """Tests for compute_change_tags()."""

    def test_approved_event_returns_approved_tag(self):
        """Approved events produce an 'Approved' tag regardless of table or fields."""
        self.assertEqual(
            compute_change_tags("Approved", "admin_member", None),
            "Approved",
        )

    def test_approved_event_ignores_changed_fields(self):
        """Changed fields (which shouldn't normally exist on Approved) don't leak into the tag."""
        self.assertEqual(
            compute_change_tags("Approved", "admin_member", [{"field": "email"}]),
            "Approved",
        )
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_polling_service
```

Expected: `TestComputeChangeTags` fails with output showing `Approved` is not recognized (returns `"Other"` or empty).

- [ ] **Step 3: Implement the tag logic**

In `verenigingen/mijnrood_sync/services/polling_service.py`, modify `compute_change_tags` (currently lines 65-85). After the existing `if event_type == "New":` / `if event_type == "Deleted":` branches, add:

Current function (abridged):
```python
def compute_change_tags(event_type: str, table: str, changed_fields: list | None) -> str:
    if event_type == "New":
        return _NEW_TABLE_LABELS.get(table, "New")
    if event_type == "Deleted":
        return "Deleted"
    # Changed
    if not changed_fields:
        return ""
    ...
```

New:
```python
def compute_change_tags(event_type: str, table: str, changed_fields: list | None) -> str:
    if event_type == "New":
        return _NEW_TABLE_LABELS.get(table, "New")
    if event_type == "Deleted":
        return "Deleted"
    if event_type == "Approved":
        return "Approved"
    # Changed
    if not changed_fields:
        return ""
    ...
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_polling_service
```

Expected: All tests in `TestComputeChangeTags` pass; no regressions in the existing tests.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/mijnrood_sync/services/polling_service.py verenigingen/tests/services/test_polling_service.py
git commit -m "feat(mijnrood_sync): tag Approved events for change-tag rendering"
```

---

## Task 3: Correlator module — skeleton + Mollie-ID pairing (Pass 1)

**Files:**
- Create: `verenigingen/mijnrood_sync/services/application_approval_correlator.py`
- Create: `verenigingen/tests/services/test_application_approval_correlator.py`

- [ ] **Step 1: Write the failing tests**

Create `verenigingen/tests/services/test_application_approval_correlator.py`:

```python
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for ApplicationApprovalCorrelator.

Tests cover:
- Mollie-ID pairing (Pass 1) — strongest signal, tolerates email/name drift
- Email + last-name pairing (Pass 2) — fallback when Mollie missing
- Mollie mismatch vetoes an email-based pair
- Last-name mismatch blocks email-based pair
- Date-of-birth mismatch blocks email-based pair
- Ambiguity (>1 candidate) blocks pairing
- Zero matches (likely rejection) leaves the Deletion untouched
- Idempotent re-run — events already Ignored are skipped
- Raw events are marked Ignored with a cross-reference note
- The synthesized Approved event carries old+new payloads
"""

import json
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.mijnrood_sync.services.application_approval_correlator import (
    ApplicationApprovalCorrelator,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _app_deletion(email, last_name, mollie=None, dob=None, app_id=42, name="EVT-DEL-1"):
    """Build a dict that looks like a MijnRood Sync Event row for an
    admin_membership_application Deleted event (keys match frappe.get_all fields)."""
    old = {"id": app_id, "email": email, "last_name": last_name}
    if mollie:
        old["mollie_customer_id"] = mollie
    if dob:
        old["date_of_birth"] = dob
    return {
        "name": name,
        "event_type": "Deleted",
        "mijnrood_table": "admin_membership_application",
        "mijnrood_row_id": app_id,
        "status": "Pending",
        "linked_member": None,
        "old_data": json.dumps(old),
        "new_data": None,
    }


def _member_creation(email, last_name, mollie=None, dob=None, member_id=1234, name="EVT-NEW-1"):
    """Build a dict that looks like a MijnRood Sync Event row for an
    admin_member New event."""
    new = {"id": member_id, "email": email, "last_name": last_name, "current_membership_status_id": 1}
    if mollie:
        new["mollie_customer_id"] = mollie
    if dob:
        new["date_of_birth"] = dob
    return {
        "name": name,
        "event_type": "New",
        "mijnrood_table": "admin_member",
        "mijnrood_row_id": member_id,
        "status": "Pending",
        "linked_member": None,
        "old_data": None,
        "new_data": json.dumps(new),
    }


class TestCorrelateMollieMatch(EnhancedTestCase):
    """Pass 1: match by mollie_customer_id."""

    def setUp(self):
        super().setUp()
        self.correlator = ApplicationApprovalCorrelator()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_mollie_match_pairs_events(self, mock_load, mock_mark, mock_emit):
        """Deletion and Creation with identical mollie_customer_id are paired."""
        mock_load.return_value = (
            [_app_deletion("old@example.com", "Doe", mollie="cust_ABC", name="EVT-DEL-1")],
            [_member_creation("new@example.com", "Doe", mollie="cust_ABC", name="EVT-NEW-1")],
        )
        mock_emit.return_value = "MR-SYNC-APPROVED-1"

        count = self.correlator.correlate("run-001")

        self.assertEqual(count, 1)
        mock_emit.assert_called_once()
        # _mark_ignored called twice, once per raw event
        self.assertEqual(mock_mark.call_count, 2)
        ignored_names = {c.args[0] for c in mock_mark.call_args_list}
        self.assertEqual(ignored_names, {"EVT-DEL-1", "EVT-NEW-1"})
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_application_approval_correlator
```

Expected: `ModuleNotFoundError: No module named 'verenigingen.mijnrood_sync.services.application_approval_correlator'`.

- [ ] **Step 3: Create the correlator module with Pass 1 logic**

Create `verenigingen/mijnrood_sync/services/application_approval_correlator.py`:

```python
"""
MijnRood Application Approval Correlator

When MijnRood approves a membership applicant it deletes the source row from
admin_membership_application and creates a new row in admin_member with a
different primary key. The polling service sees these as two independent
events ("Deleted" on the application table, "New" on the member table).

This correlator runs after all tables have been polled in a single sync run
and collapses confident pairs into a single "Approved" event. The two raw
events are marked Ignored with a cross-reference note.

Pairing strategy (in order):
  1. mollie_customer_id match — strongest signal, tolerates field drift
  2. Email match — requires last-name agreement, vetoed by Mollie mismatch

Unmatched Deletions are left alone (likely rejections). Ambiguous matches
(>1 candidate on either side) are also left alone.
"""

import json
from typing import Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.mijnrood_sync.services.polling_service import compute_change_tags
from verenigingen.services.infrastructure.base_service import StatefulService


class ApplicationApprovalCorrelator(StatefulService):
    """Collapses admin_membership_application Deleted + admin_member New event
    pairs created in the same sync run into a single Approved event."""

    def __init__(self):
        super().__init__(service_name="ApplicationApprovalCorrelator")

    def correlate(self, sync_run_id: str) -> int:
        """Entry point. Returns the number of pairs collapsed."""
        deletions, creations = self._load_candidates(sync_run_id)
        if not deletions or not creations:
            return 0

        pairs_collapsed = 0

        # Pass 1 — Mollie-ID match
        mollie_index = {}
        for c in creations:
            c_mollie = self._field(c["new_data"], "mollie_customer_id")
            if c_mollie:
                mollie_index.setdefault(c_mollie, []).append(c)

        remaining_deletions = []
        paired_creation_names = set()
        for d in deletions:
            d_mollie = self._field(d["old_data"], "mollie_customer_id")
            if not d_mollie:
                remaining_deletions.append(d)
                continue
            candidates = [
                c for c in mollie_index.get(d_mollie, [])
                if c["name"] not in paired_creation_names
            ]
            if len(candidates) == 1:
                c = candidates[0]
                self._collapse_pair(d, c, sync_run_id)
                paired_creation_names.add(c["name"])
                pairs_collapsed += 1
            else:
                # 0 or >1 — leave for Pass 2 (0) or skip (>1 logged)
                if len(candidates) > 1:
                    self.logger.warning(
                        "Ambiguous Mollie match for deletion %s (id=%s): %d candidates",
                        d["name"],
                        d_mollie,
                        len(candidates),
                    )
                else:
                    remaining_deletions.append(d)

        # Pass 2 comes in Task 4 — for now, unmatched remain unmatched
        return pairs_collapsed

    # ─── Candidate loading ────────────────────────────────────────────

    def _load_candidates(self, sync_run_id: str) -> tuple[list[dict], list[dict]]:
        """Load Pending Deleted admin_membership_application events and
        Pending New admin_member events for this sync run."""
        fields = [
            "name",
            "event_type",
            "mijnrood_table",
            "mijnrood_row_id",
            "status",
            "linked_member",
            "old_data",
            "new_data",
        ]
        deletions = frappe.get_all(
            "MijnRood Sync Event",
            filters={
                "sync_run_id": sync_run_id,
                "event_type": "Deleted",
                "mijnrood_table": "admin_membership_application",
                "status": "Pending",
            },
            fields=fields,
        )
        creations = frappe.get_all(
            "MijnRood Sync Event",
            filters={
                "sync_run_id": sync_run_id,
                "event_type": "New",
                "mijnrood_table": "admin_member",
                "status": "Pending",
            },
            fields=fields,
        )
        return deletions, creations

    # ─── Pair collapsing ──────────────────────────────────────────────

    def _collapse_pair(self, deletion: dict, creation: dict, sync_run_id: str) -> None:
        """Emit the Approved event and mark both raw events Ignored."""
        approved_name = self._emit_approved_event(deletion, creation, sync_run_id)
        note = _("Superseded by {0}").format(approved_name)
        self._mark_ignored(deletion["name"], note)
        self._mark_ignored(creation["name"], note)

    def _emit_approved_event(self, deletion: dict, creation: dict, sync_run_id: str) -> str:
        """Create and insert the synthesized Approved event. Returns its name."""
        old_data = json.loads(deletion["old_data"]) if deletion["old_data"] else {}
        new_data = json.loads(creation["new_data"]) if creation["new_data"] else {}

        summary = self._build_summary(old_data, new_data)

        event = frappe.new_doc("MijnRood Sync Event")
        event.event_type = "Approved"
        event.mijnrood_table = "admin_member"
        event.mijnrood_row_id = creation["mijnrood_row_id"]
        event.status = "Pending"
        event.linked_member = creation.get("linked_member") or deletion.get("linked_member")
        event.old_data = json.dumps(old_data)
        event.new_data = json.dumps(new_data)
        event.change_summary = summary
        event.change_tags = compute_change_tags("Approved", "admin_member", None)
        event.detected_at = now_datetime()
        event.sync_run_id = sync_run_id
        event.insert(ignore_permissions=True)
        return event.name

    def _mark_ignored(self, event_name: str, note: str) -> None:
        """Mark a raw event as Ignored with a cross-reference note."""
        frappe.db.set_value(
            "MijnRood Sync Event",
            event_name,
            {"status": "Ignored", "review_notes": note},
            update_modified=False,
        )

    def _build_summary(self, old_data: dict, new_data: dict) -> str:
        """Human-readable summary for the synthesized Approved event."""
        name_parts = [
            (new_data.get(k) or old_data.get(k) or "").strip()
            for k in ("first_name", "middle_name", "last_name")
        ]
        full_name = " ".join(p for p in name_parts if p) or "unknown"
        return _("Application approved: {0} (app #{1} → member #{2})").format(
            full_name,
            old_data.get("id", "?"),
            new_data.get("id", "?"),
        )

    @staticmethod
    def _field(raw_json: Optional[str], key: str) -> Optional[str]:
        """Safely extract a field from a JSON string column."""
        if not raw_json:
            return None
        try:
            data = json.loads(raw_json)
        except (TypeError, ValueError):
            return None
        val = data.get(key)
        if val is None or val == "":
            return None
        return str(val).strip()


# Module-level singleton
_correlator_instance: Optional[ApplicationApprovalCorrelator] = None


def get_correlator() -> ApplicationApprovalCorrelator:
    """Singleton accessor for the correlator."""
    global _correlator_instance
    if _correlator_instance is None:
        _correlator_instance = ApplicationApprovalCorrelator()
    return _correlator_instance
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_application_approval_correlator
```

Expected: `TestCorrelateMollieMatch` passes.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/mijnrood_sync/services/application_approval_correlator.py verenigingen/tests/services/test_application_approval_correlator.py
git commit -m "feat(mijnrood_sync): correlator module with Mollie-ID pairing (Pass 1)"
```

---

## Task 4: Correlator — email + last-name pairing (Pass 2) and veto rules

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/application_approval_correlator.py`
- Modify: `verenigingen/tests/services/test_application_approval_correlator.py`

- [ ] **Step 1: Add failing tests for Pass 2 and veto behavior**

Append to `verenigingen/tests/services/test_application_approval_correlator.py`:

```python
class TestCorrelateEmailFallback(EnhancedTestCase):
    """Pass 2: match by email + last name, with Mollie-mismatch veto."""

    def setUp(self):
        super().setUp()
        self.correlator = ApplicationApprovalCorrelator()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_email_match_with_last_name_pairs(self, mock_load, mock_mark, mock_emit):
        """Same email + last name pairs when no Mollie ID on either side."""
        mock_load.return_value = (
            [_app_deletion("jane@example.com", "Doe", name="EVT-DEL-2")],
            [_member_creation("jane@example.com", "Doe", name="EVT-NEW-2")],
        )
        mock_emit.return_value = "MR-SYNC-APPROVED-2"

        count = self.correlator.correlate("run-002")

        self.assertEqual(count, 1)
        mock_emit.assert_called_once()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_email_match_with_mollie_mismatch_vetoes(self, mock_load, mock_mark, mock_emit):
        """Email matches but Mollie IDs disagree → no pair."""
        mock_load.return_value = (
            [_app_deletion("jane@example.com", "Doe", mollie="cust_AAA", name="EVT-DEL-3")],
            [_member_creation("jane@example.com", "Doe", mollie="cust_BBB", name="EVT-NEW-3")],
        )

        count = self.correlator.correlate("run-003")

        self.assertEqual(count, 0)
        mock_emit.assert_not_called()
        mock_mark.assert_not_called()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_last_name_mismatch_blocks_email_pair(self, mock_load, mock_mark, mock_emit):
        """Same email but different last names → no pair."""
        mock_load.return_value = (
            [_app_deletion("family@example.com", "Doe", name="EVT-DEL-4")],
            [_member_creation("family@example.com", "Smith", name="EVT-NEW-4")],
        )

        count = self.correlator.correlate("run-004")

        self.assertEqual(count, 0)
        mock_emit.assert_not_called()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_dob_mismatch_blocks_email_pair(self, mock_load, mock_mark, mock_emit):
        """Both sides have DOB, DOBs differ → no pair."""
        mock_load.return_value = (
            [_app_deletion("jane@example.com", "Doe", dob="1990-01-01", name="EVT-DEL-5")],
            [_member_creation("jane@example.com", "Doe", dob="1985-05-15", name="EVT-NEW-5")],
        )

        count = self.correlator.correlate("run-005")

        self.assertEqual(count, 0)

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_multiple_candidates_blocks_pairing(self, mock_load, mock_mark, mock_emit):
        """More than one Creation with the same email → no pair."""
        mock_load.return_value = (
            [_app_deletion("shared@example.com", "Doe", name="EVT-DEL-6")],
            [
                _member_creation("shared@example.com", "Doe", member_id=1, name="EVT-NEW-6a"),
                _member_creation("shared@example.com", "Doe", member_id=2, name="EVT-NEW-6b"),
            ],
        )

        count = self.correlator.correlate("run-006")

        self.assertEqual(count, 0)
        mock_emit.assert_not_called()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_no_candidates_is_noop(self, mock_load, mock_mark, mock_emit):
        """Empty candidate sets return 0."""
        mock_load.return_value = ([], [])

        count = self.correlator.correlate("run-007")

        self.assertEqual(count, 0)
        mock_emit.assert_not_called()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_deletion_with_no_match_is_untouched(self, mock_load, mock_mark, mock_emit):
        """Deletion with no matching Creation (rejection case) stays untouched."""
        mock_load.return_value = (
            [_app_deletion("lonely@example.com", "Doe", name="EVT-DEL-8")],
            [_member_creation("other@example.com", "Smith", name="EVT-NEW-8")],
        )

        count = self.correlator.correlate("run-008")

        self.assertEqual(count, 0)
        mock_emit.assert_not_called()
        mock_mark.assert_not_called()
```

- [ ] **Step 2: Run the tests — confirm they fail**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_application_approval_correlator
```

Expected: the new `TestCorrelateEmailFallback` tests fail — Pass 2 is not implemented yet, email matches all pass through unmatched.

- [ ] **Step 3: Implement Pass 2 and the veto rules**

In `verenigingen/mijnrood_sync/services/application_approval_correlator.py`, extend `correlate()` to run a second pass over `remaining_deletions` after Pass 1. Replace the `# Pass 2 comes in Task 4 — for now, unmatched remain unmatched` placeholder and the `return pairs_collapsed` at the bottom of `correlate()` with the following block:

```python
        # Pass 2 — Email + last-name match (fallback)
        email_index = {}
        for c in creations:
            if c["name"] in paired_creation_names:
                continue
            c_email = self._field(c["new_data"], "email")
            if c_email:
                email_index.setdefault(c_email.lower(), []).append(c)

        for d in remaining_deletions:
            d_email = self._field(d["old_data"], "email")
            if not d_email:
                continue
            candidates = [
                c for c in email_index.get(d_email.lower(), [])
                if c["name"] not in paired_creation_names
            ]
            if len(candidates) != 1:
                if len(candidates) > 1:
                    self.logger.warning(
                        "Ambiguous email match for deletion %s (email=%s): %d candidates",
                        d["name"],
                        d_email,
                        len(candidates),
                    )
                continue

            c = candidates[0]
            if not self._passes_confidence_check(d, c):
                continue

            self._collapse_pair(d, c, sync_run_id)
            paired_creation_names.add(c["name"])
            pairs_collapsed += 1

        return pairs_collapsed
```

Then add the confidence-check helper to the class:

```python
    def _passes_confidence_check(self, deletion: dict, creation: dict) -> bool:
        """Confirm an email-based pair via last-name agreement and veto rules."""
        d_last = (self._field(deletion["old_data"], "last_name") or "").lower()
        c_last = (self._field(creation["new_data"], "last_name") or "").lower()
        if d_last != c_last:
            self.logger.info(
                "Last-name mismatch blocks pair %s ↔ %s: %r vs %r",
                deletion["name"], creation["name"], d_last, c_last,
            )
            return False

        d_mollie = self._field(deletion["old_data"], "mollie_customer_id")
        c_mollie = self._field(creation["new_data"], "mollie_customer_id")
        if d_mollie and c_mollie and d_mollie != c_mollie:
            self.logger.info(
                "Mollie-ID mismatch vetoes pair %s ↔ %s: %s vs %s",
                deletion["name"], creation["name"], d_mollie, c_mollie,
            )
            return False

        d_dob = self._field(deletion["old_data"], "date_of_birth")
        c_dob = self._field(creation["new_data"], "date_of_birth")
        if d_dob and c_dob and d_dob != c_dob:
            self.logger.info(
                "DOB mismatch blocks pair %s ↔ %s: %s vs %s",
                deletion["name"], creation["name"], d_dob, c_dob,
            )
            return False

        return True
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_application_approval_correlator
```

Expected: all tests in `TestCorrelateMollieMatch` and `TestCorrelateEmailFallback` pass.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/mijnrood_sync/services/application_approval_correlator.py verenigingen/tests/services/test_application_approval_correlator.py
git commit -m "feat(mijnrood_sync): email + last-name pairing with Mollie/DOB veto"
```

---

## Task 5: Wire correlator into `run_sync` + surface count in sync log

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/polling_service.py` (lines 94-206)
- Modify: `verenigingen/tests/services/test_polling_service.py`

- [ ] **Step 1: Write a failing test**

Append to `verenigingen/tests/services/test_polling_service.py`:

```python
class TestRunSyncCallsCorrelator(EnhancedTestCase):
    """Verify run_sync invokes the application-approval correlator after polling."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodPollingService()

    @patch("verenigingen.mijnrood_sync.services.polling_service.ApplicationApprovalCorrelator")
    @patch.object(MijnRoodPollingService, "_poll_division_contacts", return_value=0)
    @patch.object(MijnRoodPollingService, "_poll_table")
    @patch("verenigingen.mijnrood_sync.services.polling_service.MijnRoodDatabaseClient")
    @patch("verenigingen.mijnrood_sync.services.polling_service.frappe")
    def test_run_sync_invokes_correlator_with_sync_run_id(
        self, mock_frappe, mock_client_cls, mock_poll_table, mock_poll_dc, mock_correlator_cls
    ):
        """run_sync calls correlator.correlate(sync_run_id) once all tables are polled,
        and the returned count is reflected in totals."""
        # Arrange settings
        settings = MagicMock()
        settings.tables_to_sync = '["admin_member"]'
        mock_frappe.get_single.return_value = settings
        mock_frappe.db.count.return_value = 0

        # Log + client stubs
        log_doc = MagicMock()
        mock_frappe.new_doc.return_value = log_doc
        mock_client_cls.return_value.__enter__.return_value = mock_client_cls.return_value

        mock_poll_table.return_value = {
            "new": 1, "changed": 0, "deleted": 1, "unchanged": 0, "rows_scanned": 1,
        }
        mock_correlator = MagicMock()
        mock_correlator.correlate.return_value = 1
        mock_correlator_cls.return_value = mock_correlator

        # Act
        totals = self.service.run_sync()

        # Assert
        mock_correlator.correlate.assert_called_once()
        # sync_run_id is a positional str argument
        call_args = mock_correlator.correlate.call_args
        self.assertEqual(len(call_args.args[0]), 12)  # uuid4().hex[:12]
        self.assertEqual(totals.get("approved"), 1)
```

- [ ] **Step 2: Run test — confirm failure**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_polling_service
```

Expected: `TestRunSyncCallsCorrelator` fails — either `ApplicationApprovalCorrelator` isn't imported in polling_service.py yet, or `approved` isn't in `totals`.

- [ ] **Step 3: Wire the correlator into `run_sync`**

In `verenigingen/mijnrood_sync/services/polling_service.py`:

(a) Add the import near the top (after the existing `from verenigingen.services.infrastructure.base_service import StatefulService`):

```python
from verenigingen.mijnrood_sync.services.application_approval_correlator import (
    ApplicationApprovalCorrelator,
)
```

(b) Extend the `totals` dict initialization in `run_sync()` (currently lines 119-125) to include `approved`:

```python
        totals = {
            "new": 0,
            "changed": 0,
            "deleted": 0,
            "approved": 0,
            "unchanged": 0,
            "rows_scanned": 0,
        }
```

(c) Immediately after the `dc_events = self._poll_division_contacts(...)` line and its `totals["changed"] += dc_events` (currently around line 140), before the `# Update sync log` block, add:

```python
                # Correlate application→member approvals emitted in this run
                approvals = ApplicationApprovalCorrelator().correlate(sync_run_id)
                totals["approved"] += approvals
```

(d) Update the `last_sync_message` string to include the new count. Replace the current line 160-162:

```python
            msg = _("Synced {0} tables: {1} new, {2} changed, {3} deleted").format(
                len(tables), totals["new"], totals["changed"], totals["deleted"]
            )
```

with:

```python
            msg = _(
                "Synced {0} tables: {1} new, {2} changed, {3} deleted, {4} approved"
            ).format(
                len(tables),
                totals["new"],
                totals["changed"],
                totals["deleted"],
                totals["approved"],
            )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_polling_service
```

Expected: all polling service tests pass.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/mijnrood_sync/services/polling_service.py verenigingen/tests/services/test_polling_service.py
git commit -m "feat(mijnrood_sync): wire approval correlator into run_sync, expose count"
```

---

## Task 6: Extract `_promote_application_member` helper (with `member.status` fix)

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application_service.py` (around lines 766-843)
- Modify: `verenigingen/tests/services/test_event_application_service.py`

- [ ] **Step 1: Add a failing test for the helper**

Append to `verenigingen/tests/services/test_event_application_service.py`:

```python
class TestPromoteApplicationMember(EnhancedTestCase):
    """Tests for the shared _promote_application_member() helper.

    This helper centralizes the promotion logic so both the correlator-driven
    _apply_approved path and the apply-time _try_promote_application safety net
    set member.status = "Active" (previously an omission in _try_promote_application).
    """

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodEventApplicationService, "_create_related_records", return_value=[])
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_sets_member_status_active_for_active_mijnrood_status(self, mock_frappe, mock_related):
        """When new_data.current_membership_status_id is an active id, member.status → Active."""
        mock_frappe._ = frappe._
        event = MagicMock()
        event.name = "EVT-PROMOTE-1"

        with patch(
            "verenigingen.services.csv_import.member_import_service.get_member_import_service"
        ) as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.create_or_update_member.return_value = ("updated", "MEM-001")
            mock_get_svc.return_value = mock_svc

            old_data = {"id": 42, "email": "jane@example.com"}
            new_data = {"id": 1234, "email": "jane@example.com", "current_membership_status_id": 1}
            row_data = {"member_id": "1234", "email": "jane@example.com"}

            result = self.service._promote_application_member(
                "MEM-001", old_data, new_data, row_data, event
            )

        self.assertTrue(result["success"])
        # Verify set_value updated BOTH application_status AND status
        # (one call with a dict containing both keys)
        updates = None
        for call in mock_frappe.db.set_value.call_args_list:
            if call.args[0] == "Member" and isinstance(call.args[2], dict):
                updates = call.args[2]
                break
        self.assertIsNotNone(updates, "Expected a dict-update set_value call on Member")
        self.assertEqual(updates.get("application_status"), "Approved")
        self.assertEqual(updates.get("status"), "Active")

    @patch.object(MijnRoodEventApplicationService, "_create_related_records", return_value=[])
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_logs_warning_for_unexpected_mijnrood_status(self, mock_frappe, mock_related):
        """An unexpected status_id (e.g. terminated during promotion) logs and does
        NOT overwrite member.status — only application_status flips."""
        mock_frappe._ = frappe._
        event = MagicMock()
        event.name = "EVT-PROMOTE-2"

        with patch(
            "verenigingen.services.csv_import.member_import_service.get_member_import_service"
        ) as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.create_or_update_member.return_value = ("updated", "MEM-001")
            mock_get_svc.return_value = mock_svc

            old_data = {"id": 42, "email": "jane@example.com"}
            # status_id=3 is "opgezegd" (terminated) — unexpected on a promotion
            new_data = {"id": 1234, "email": "jane@example.com", "current_membership_status_id": 3}
            row_data = {"member_id": "1234", "email": "jane@example.com"}

            self.service._promote_application_member(
                "MEM-001", old_data, new_data, row_data, event
            )

        # The single set_value call should carry application_status but NOT status
        updates = None
        for call in mock_frappe.db.set_value.call_args_list:
            if call.args[0] == "Member" and isinstance(call.args[2], dict):
                updates = call.args[2]
                break
        self.assertIsNotNone(updates)
        self.assertEqual(updates.get("application_status"), "Approved")
        self.assertNotIn("status", updates)
```

- [ ] **Step 2: Run tests — confirm failure**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_event_application_service
```

Expected: `TestPromoteApplicationMember` fails with `AttributeError: MijnRoodEventApplicationService has no attribute _promote_application_member`.

- [ ] **Step 3: Extract the helper and update `_try_promote_application` to delegate**

In `verenigingen/mijnrood_sync/services/event_application_service.py`:

(a) Add the shared helper (place it immediately **above** `_try_promote_application`, around line 766):

```python
    def _promote_application_member(
        self,
        member_name: str,
        old_data: dict,
        new_data: dict,
        row_data: dict,
        event,
    ) -> dict:
        """Promote a local Pending Member to Approved/Active using MijnRood data.

        Shared by:
        - _apply_approved (correlator-driven path, preferred)
        - _try_promote_application (apply-time cross-run safety net)

        Handles:
        1. Field sync via MemberImportService.create_or_update_member
        2. Flipping application_status to Approved AND member.status to Active
           (the latter was missing in the original _try_promote_application and
           prevented Membership + Dues Schedule creation downstream)
        3. Running the standard related-records side effects (chapter, address,
           Mollie, Membership + Dues Schedule, user account, notes)
        """
        from verenigingen.services.csv_import.member_import_service import (
            get_member_import_service,
        )

        service = get_member_import_service()
        status, updated_name = service.create_or_update_member(
            row_data=row_data,
            import_doc_name=f"MijnRood Sync: {event.name}",
        )
        if status not in ("created", "updated"):
            return {
                "success": False,
                "message": _("Application promotion failed: {0}").format(status),
            }

        old_member_id = old_data.get("id")
        new_member_id = new_data.get("id")

        updates = {
            "application_status": "Approved",
            "review_notes": (
                f"Approved via MijnRood (event {event.name}). "
                f"Application id {old_member_id} → member_id {new_member_id}."
            ),
        }

        # Flip member.status to Active if the MijnRood status is recognized as active.
        # For unexpected status ids on a promotion (e.g. terminated), log and leave
        # member.status alone — this shouldn't happen in practice.
        status_id = safe_int(new_data.get("current_membership_status_id"))
        if status_id is not None and status_id in get_active_status_ids():
            updates["status"] = "Active"
        elif status_id is not None:
            self.logger.warning(
                "Promotion event %s carries unexpected MijnRood status id %s for member %s; "
                "leaving member.status unchanged",
                event.name,
                status_id,
                updated_name,
            )

        frappe.db.set_value("Member", updated_name, updates, update_modified=False)

        event.linked_member = updated_name

        related_msgs = self._create_related_records(updated_name, row_data, event)

        messages = [
            _("Application {0} promoted (id {1} → member_id {2})").format(
                updated_name, old_member_id, new_member_id
            )
        ]
        messages.extend(related_msgs)
        return {"success": True, "message": "; ".join(messages)}
```

(b) Replace the body of `_try_promote_application` (currently lines 766-843 — the whole method after its docstring, from `email = row_data.get("email")` through `return {"success": True, "message": "; ".join(messages)}`) with:

```python
    def _try_promote_application(self, event, row_data: dict) -> Optional[dict]:
        """Handle MijnRood application→member promotion (apply-time safety net).

        This runs when the correlator didn't pair events at poll time (rare:
        cross-run split or low-confidence match). Detection: email match where
        the existing member has application_status=Pending. Promotion itself
        is delegated to _promote_application_member.

        Returns:
            Result dict if promotion was handled, None if not a promotion.
        """
        email = row_data.get("email")
        match = frappe.db.get_value(
            "Member",
            {"email": email},
            ["name", "member_id", "application_status"],
            as_dict=True,
        )
        if not match or match.application_status != "Pending":
            return None

        old_member_id = match.member_id
        new_member_id = row_data.get("member_id")

        self.logger.info(
            "Promoting application %s (member_id %s → %s) via event %s (apply-time fallback)",
            match.name, old_member_id, new_member_id, event.name,
        )

        # Build a minimal old_data stub — the safety-net path doesn't have the
        # original application row handy. _promote_application_member only uses
        # old_data["id"] for the log message, so this is adequate.
        old_data_stub = {"id": old_member_id}
        # Build a new_data stub from row_data so the status-flip path works.
        # The apply-time path may not have current_membership_status_id —
        # default to 1 (active) which is correct for a promotion.
        new_data_stub = {
            "id": new_member_id,
            "current_membership_status_id": 1,
        }

        return self._promote_application_member(
            match.name, old_data_stub, new_data_stub, row_data, event
        )
```

Note: the `safe_int` and `get_active_status_ids` imports are already present at the top of the file — no import changes needed.

- [ ] **Step 4: Run all event_application_service tests**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_event_application_service
```

Expected: `TestPromoteApplicationMember` passes. The pre-existing `TestTryPromoteApplication` and `TestApplyNewMemberPromotionPath` tests continue to pass — they still exercise the `_try_promote_application` entry point, which now delegates through `_promote_application_member`.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application_service.py verenigingen/tests/services/test_event_application_service.py
git commit -m "refactor(mijnrood_sync): extract _promote_application_member, flip member.status on promotion"
```

---

## Task 7: Add `_apply_approved` handler and dispatch

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application_service.py` (lines 43-91 dispatch, plus new method)
- Modify: `verenigingen/tests/services/test_event_application_service.py`

- [ ] **Step 1: Add failing tests**

Append to `verenigingen/tests/services/test_event_application_service.py`:

```python
class TestApplyApproved(EnhancedTestCase):
    """Tests for _apply_approved() — correlator-driven promotion."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodEventApplicationService, "_promote_application_member")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_uses_linked_member_when_set(self, mock_frappe, mock_promote):
        """When event.linked_member is set, promote that member directly."""
        mock_frappe._ = frappe._
        mock_promote.return_value = {"success": True, "message": "promoted"}

        event = MagicMock()
        event.linked_member = "MEM-001"
        event.old_data = json.dumps({"id": 42, "email": "jane@example.com", "last_name": "Doe"})
        event.new_data = json.dumps({
            "id": 1234, "email": "jane@example.com", "last_name": "Doe",
            "current_membership_status_id": 1,
        })

        result = self.service._apply_approved(event)

        self.assertTrue(result["success"])
        mock_promote.assert_called_once()
        # First arg is member_name
        self.assertEqual(mock_promote.call_args.args[0], "MEM-001")

    @patch.object(MijnRoodEventApplicationService, "_promote_application_member")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_falls_back_to_application_id_lookup(self, mock_frappe, mock_promote):
        """Without linked_member, locate by application_id = f'MR-APP-{old_id}'."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = "MEM-002"
        mock_promote.return_value = {"success": True, "message": "promoted"}

        event = MagicMock()
        event.linked_member = None
        event.old_data = json.dumps({"id": 99, "email": "jane@example.com", "last_name": "Doe"})
        event.new_data = json.dumps({
            "id": 5678, "email": "jane@example.com", "last_name": "Doe",
            "current_membership_status_id": 1,
        })

        result = self.service._apply_approved(event)

        self.assertTrue(result["success"])
        # First get_value call should be for application_id
        first_call = mock_frappe.db.get_value.call_args_list[0]
        self.assertEqual(first_call.args[0], "Member")
        self.assertEqual(first_call.args[1], {"application_id": "MR-APP-99"})
        self.assertEqual(mock_promote.call_args.args[0], "MEM-002")

    @patch.object(MijnRoodEventApplicationService, "_apply_new_member")
    @patch.object(MijnRoodEventApplicationService, "_promote_application_member")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_falls_through_to_new_member_when_not_found(
        self, mock_frappe, mock_promote, mock_apply_new
    ):
        """If no existing member can be located, fall through to _apply_new_member."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = None
        mock_apply_new.return_value = {"success": True, "message": "created"}

        event = MagicMock()
        event.linked_member = None
        event.old_data = json.dumps({"id": 99, "email": "ghost@example.com", "last_name": "Doe"})
        event.new_data = json.dumps({
            "id": 5678, "email": "ghost@example.com", "last_name": "Doe",
            "current_membership_status_id": 1,
        })

        result = self.service._apply_approved(event)

        self.assertTrue(result["success"])
        mock_apply_new.assert_called_once_with(event)
        mock_promote.assert_not_called()


class TestApplyEventDispatchesApproved(EnhancedTestCase):
    """Verify apply_event dispatches Approved events to _apply_approved."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodEventApplicationService, "_apply_approved")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_approved_event_routes_to_apply_approved(self, mock_frappe, mock_apply_approved):
        """apply_event('...') with event_type='Approved' calls _apply_approved."""
        mock_frappe._ = frappe._
        event_doc = MagicMock()
        event_doc.status = "Approved"
        event_doc.event_type = "Approved"
        mock_frappe.get_doc.return_value = event_doc
        mock_apply_approved.return_value = {"success": True, "message": "ok"}

        result = self.service.apply_event("EVT-APPROVED-1")

        self.assertTrue(result["success"])
        mock_apply_approved.assert_called_once_with(event_doc)
```

- [ ] **Step 2: Run tests — confirm failure**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_event_application_service
```

Expected: `TestApplyApproved` fails (`AttributeError: _apply_approved`). `TestApplyEventDispatchesApproved` fails with `"Unknown event type: Approved"`.

- [ ] **Step 3: Implement `_apply_approved` and wire dispatch**

In `verenigingen/mijnrood_sync/services/event_application_service.py`:

(a) Extend `apply_event()` dispatch (currently lines 58-66). Replace:

```python
            if event.event_type == "New":
                result = self._apply_new(event)
            elif event.event_type == "Changed":
                result = self._apply_changed(event)
            elif event.event_type == "Deleted":
                result = self._apply_deleted(event)
            else:
                result = {"success": False, "message": _("Unknown event type: {0}").format(event.event_type)}
```

with:

```python
            if event.event_type == "New":
                result = self._apply_new(event)
            elif event.event_type == "Changed":
                result = self._apply_changed(event)
            elif event.event_type == "Deleted":
                result = self._apply_deleted(event)
            elif event.event_type == "Approved":
                result = self._apply_approved(event)
            else:
                result = {"success": False, "message": _("Unknown event type: {0}").format(event.event_type)}
```

(b) Add `_apply_approved` and `_locate_application_member` immediately after `_apply_deleted` (currently around line 1073). Insert:

```python
    # ─── Approved (correlator-synthesized) ─────────────────────────────

    def _apply_approved(self, event) -> dict:
        """Apply an Approved event synthesized by the approval correlator.

        The event's old_data is the deleted application row; new_data is the
        newly-created admin_member row. We locate the local Pending Member
        that was created when the application first synced, then delegate to
        _promote_application_member for the actual promotion.
        """
        new_data = safe_json_load(event.new_data)
        old_data = safe_json_load(event.old_data)
        if not new_data:
            return {"success": False, "message": _("No new data in approved event")}

        row_data = self._map_mijnrood_to_member_fields(new_data)

        member_name = self._locate_application_member(old_data or {}, new_data, event.linked_member)
        if not member_name:
            # Fall through to fresh creation — defensive, shouldn't happen in
            # practice because the application event already created a Pending
            # Member that the correlator linked to this event.
            self.logger.warning(
                "Approved event %s could not locate a Pending Member; falling "
                "through to _apply_new_member",
                event.name,
            )
            return self._apply_new_member(event)

        return self._promote_application_member(
            member_name, old_data or {}, new_data, row_data, event
        )

    def _locate_application_member(
        self, old_data: dict, new_data: dict, linked_member: Optional[str]
    ) -> Optional[str]:
        """Locate the local Pending Member for an Approved event.

        Order:
          1. event.linked_member (set by the correlator).
          2. Lookup by application_id = f'MR-APP-{old_data.id}' — matches what
             _apply_new_membership_application stamps onto the Member.
          3. Lookup by normalized email.
          4. None → caller falls through.
        """
        if linked_member:
            return linked_member

        app_id = old_data.get("id")
        if app_id is not None:
            match = frappe.db.get_value(
                "Member",
                {"application_id": f"MR-APP-{app_id}"},
                "name",
            )
            if match:
                return match

        email = (new_data.get("email") or old_data.get("email") or "").strip()
        if email:
            match = frappe.db.get_value("Member", {"email": email}, "name")
            if match:
                return match

        return None
```

- [ ] **Step 4: Run event_application_service tests**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_event_application_service
```

Expected: `TestApplyApproved` and `TestApplyEventDispatchesApproved` pass; pre-existing tests continue to pass.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application_service.py verenigingen/tests/services/test_event_application_service.py
git commit -m "feat(mijnrood_sync): add _apply_approved handler for correlator events"
```

---

## Task 8: Integration test — end-to-end Membership + Dues creation on promotion

**Files:**
- Modify: `verenigingen/tests/services/test_event_application_service.py`

- [ ] **Step 1: Write the failing regression test**

Append to `verenigingen/tests/services/test_event_application_service.py`:

```python
class TestApprovedEventCreatesMembershipAndDues(EnhancedTestCase):
    """Integration regression test: an Approved event must result in a
    Membership + Dues Schedule being created (the bug that
    _try_promote_application forgot to flip member.status to Active,
    which _ensure_membership_and_dues requires).

    Uses real DB and full pipeline — no mocks on the promotion side.
    """

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    def _make_pending_member(self, email="promoted@example.com", app_mijnrood_id=99):
        """Create a Pending Member analogous to what _apply_new_membership_application creates."""
        member = frappe.new_doc("Member")
        member.first_name = "Jane"
        member.last_name = "Doe"
        member.email = email
        member.application_id = f"MR-APP-{app_mijnrood_id}"
        member.application_status = "Pending"
        member.status = "Pending"
        member.application_date = frappe.utils.today()
        member._csv_import = True
        member._system_update = True
        member.flags.ignore_workflow = True
        member.insert(ignore_permissions=True)
        frappe.db.commit()
        return member.name

    def test_approved_event_flips_status_and_creates_membership(self):
        """Applying an Approved event promotes the Pending Member to Active
        AND downstream creates a Membership + Dues Schedule."""
        email = f"promo-{frappe.generate_hash(length=8)}@example.com"
        app_id = 990001  # unlikely to collide
        new_member_id = 880001

        pending_member_name = self._make_pending_member(email=email, app_mijnrood_id=app_id)

        # Synthesize an Approved event as the correlator would
        old_data = {
            "id": app_id,
            "email": email,
            "first_name": "Jane",
            "last_name": "Doe",
        }
        new_data = {
            "id": new_member_id,
            "email": email,
            "first_name": "Jane",
            "last_name": "Doe",
            "current_membership_status_id": 1,  # active
            "contribution_per_period_in_cents": 1000,  # €10
            "contribution_period": 12,  # annual (matches existing mapping)
        }

        event = frappe.new_doc("MijnRood Sync Event")
        event.event_type = "Approved"
        event.mijnrood_table = "admin_member"
        event.mijnrood_row_id = new_member_id
        event.status = "Approved"
        event.linked_member = pending_member_name
        event.old_data = json.dumps(old_data)
        event.new_data = json.dumps(new_data)
        event.change_summary = "Test approved event"
        event.change_tags = "Approved"
        event.detected_at = frappe.utils.now_datetime()
        event.sync_run_id = "test-run-001"
        event.insert(ignore_permissions=True)
        frappe.db.commit()

        # Apply the event
        result = self.service.apply_event(event.name)
        self.assertTrue(result["success"], f"apply_event failed: {result.get('message')}")

        # Assert member state
        member = frappe.get_doc("Member", pending_member_name)
        self.assertEqual(member.application_status, "Approved")
        self.assertEqual(member.status, "Active", "Bug regression: member.status should flip to Active")
        self.assertEqual(str(member.member_id), str(new_member_id))

        # Assert downstream: Membership created (integration proof of the fix)
        membership = frappe.db.get_value(
            "Membership",
            {"member": pending_member_name, "status": "Active", "docstatus": 1},
            "name",
        )
        self.assertIsNotNone(
            membership,
            "Regression: Membership should be created on promotion now that member.status=Active",
        )

        # Assert Dues Schedule created
        dues = frappe.db.exists(
            "Membership Dues Schedule",
            {"member": pending_member_name, "is_template": 0},
        )
        self.assertTrue(dues, "Regression: Dues Schedule should be created on promotion")
```

- [ ] **Step 2: Run the test — confirm it fails or passes correctly**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_event_application_service
```

Expected: since Task 6 already delivers the status-flip fix and Task 7 delivers `_apply_approved`, the test should pass at this point. If it still fails, the failure output pinpoints a downstream issue — investigate before proceeding (likely a missing field, e.g. the dues-schedule template resolution needs a different `contribution_period` value — inspect `get_dues_schedule_template_from_payment_period` and `_map_mijnrood_to_member_fields`).

- [ ] **Step 3: Commit**

```bash
git add verenigingen/tests/services/test_event_application_service.py
git commit -m "test(mijnrood_sync): regression test — Approved event creates membership + dues"
```

---

## Task 9: Smoke-test the full flow end-to-end

**Files:** none (verification only)

- [ ] **Step 1: Run all mijnrood-related tests together**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_event_application_service
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_polling_service
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services.test_application_approval_correlator
```

Expected: all pass.

- [ ] **Step 2: Run pre-commit validation**

```bash
cd ~/frappe-bench/apps/verenigingen && pre-commit run --all-files --files \
  verenigingen/mijnrood_sync/services/polling_service.py \
  verenigingen/mijnrood_sync/services/event_application_service.py \
  verenigingen/mijnrood_sync/services/application_approval_correlator.py \
  verenigingen/mijnrood_sync/doctype/mijnrood_sync_event/mijnrood_sync_event.json \
  verenigingen/tests/services/test_polling_service.py \
  verenigingen/tests/services/test_event_application_service.py \
  verenigingen/tests/services/test_application_approval_correlator.py
```

Expected: pass. If `whitelist-type-safety` fails due to pre-existing issues in unrelated files, it's noted in CLAUDE.md — skip with `SKIP=whitelist-type-safety`.

- [ ] **Step 3: Check git log is clean**

```bash
git log --oneline develop..HEAD
```

Expected: 7 commits on top of the spec commit, each scoped and readable:

```
feat(mijnrood_sync): add Approved event_type to MijnRood Sync Event
feat(mijnrood_sync): tag Approved events for change-tag rendering
feat(mijnrood_sync): correlator module with Mollie-ID pairing (Pass 1)
feat(mijnrood_sync): email + last-name pairing with Mollie/DOB veto
feat(mijnrood_sync): wire approval correlator into run_sync, expose count
refactor(mijnrood_sync): extract _promote_application_member, flip member.status on promotion
feat(mijnrood_sync): add _apply_approved handler for correlator events
test(mijnrood_sync): regression test — Approved event creates membership + dues
```

---

## Notes for the implementer

- **Transaction handling:** The correlator writes new events + updates existing events. Frappe's implicit per-request commit covers the whole run_sync call; the correlator need not add its own `commit()`. If a caller invokes `correlate()` outside of run_sync in the future, they must manage their own transaction.
- **Idempotency:** The correlator filters on `status='Pending'` — events already collapsed are skipped on re-run. The `_apply_approved` path is idempotent via `MemberImportService.create_or_update_member` which checks for an existing member before creating.
- **Related-records pathway:** `_promote_application_member` → `_create_related_records` → `_ensure_membership_and_dues` is where the status-flip bug fix manifests. The integration test in Task 8 is the proof.
- **Existing `_try_promote_application` keeps working:** the pre-existing `TestTryPromoteApplication` tests will continue to pass because the entry point signature is unchanged — only the body was replaced to delegate.
- **No cross-run correlation in v1:** if a sync split causes the application deletion and member creation to land in different runs, the retained `_try_promote_application` catches it at apply time for the `New admin_member` event. Revisit if production traffic shows this is common.
