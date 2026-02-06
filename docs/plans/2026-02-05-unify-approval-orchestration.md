# Unify Approval Orchestration — Implementation Plan — COMPLETED

> **Status:** COMPLETED (2026-02-06). All 7 tasks executed. ~353 LOC deleted, canonical path unified through `MembershipCreationService`.

**Goal:** Eliminate the three competing approval orchestrators, making `approve_membership_application()` in the review API a thin HTTP layer that delegates ALL business logic through a single canonical path.

**Architecture:** The review API (`membership_application_review.py`) becomes a thin HTTP endpoint: input validation, permission checks, response formatting. All business logic flows through `MembershipCreationService` (which already handles membership creation, dues schedules, invoices, and consolidated member saves). The lifecycle service keeps its row-locking and status-setting role. The approval service's `create_membership_and_invoice()` and `process_member_approval()` are deleted — their logic already exists in better form elsewhere.

**Tech Stack:** Python 3.11, Frappe Framework v15, MariaDB

---

## Current State Summary

Three approval paths exist:

| Path | Entry Point | What It Does |
|------|-------------|-------------|
| **Path 1** (lifecycle) | `MemberLifecycleService.approve_application()` | Row lock, validate, set status fields, save, post-approval setup (user, customer, chapter) |
| **Path 2** (approval service) | `process_member_approval()` | Load member, resolve type, IBAN history, `create_membership_and_invoice()` (service copy), `finalize_member_approval()` |
| **Path 3** (review API) | `approve_membership_application()` | Input validation, permissions, calls `member.create_membership_on_approval()` (→ `MembershipCreationService`), volunteer activation, user account creation, notifications |

**The actual production flow (Path 3) currently:**
1. Review API validates inputs, checks permissions
2. Calls `assign_member_to_chapter()`
3. Calls `create_member_iban_history()` (from approval service)
4. Builds `approval_fields` dict
5. Calls `member.create_membership_on_approval(approval_fields=...)` → `MembershipCreationService`
   - MembershipCreationService creates membership, dues schedule, invoice
   - Sets approval_fields on member, saves member with rollback protection
6. Activates volunteer record
7. Creates user account
8. Sends approval notification
9. Queues payment history update

**Key finding:** Path 3 does NOT call `member.approve_application()` (Path 1) or `process_member_approval()` (Path 2). The review API's local `create_membership_and_invoice()` at line 68 is only called from `background_approval_api.py`.

## What Gets Deleted

| Function | File | Lines | Reason |
|----------|------|-------|--------|
| `create_membership_and_invoice()` | `membership_application_review.py:68-123` | 56 | Duplicate of approval service version, only called from background API |
| `create_membership_and_invoice()` | `member_approval_service.py:183-310` | 128 | Superceded by `MembershipCreationService` |
| `finalize_member_approval()` | `member_approval_service.py:313-393` | 81 | Status fields now set via `approval_fields` in `MembershipCreationService` |
| `process_member_approval()` | `member_approval_service.py:395-454` | 60 | Zero callers found — completely unused |
| `validate_member_fields()` | `member_approval_service.py:27-54` | 28 | Only called by `finalize_member_approval()` |

**Total deleted: ~353 LOC**

## What Gets Modified

| Function | File | Change |
|----------|------|--------|
| `approve_membership_application_background()` | `background_approval_api.py:30-294` | Stop importing review API's local `create_membership_and_invoice()`. Use `member.create_membership_on_approval()` instead. |
| `Member.approve_application()` | `member.py:378-391` | Remove — only called from tests, not from production approval flow |
| `MemberLifecycleService.approve_application()` | `member_lifecycle_service.py:96-179` | Keep for now (used by `Member.approve_application()` which is called by some tests) — mark deprecated |

## What Stays Unchanged

| Function | File | Why |
|----------|------|-----|
| `resolve_membership_type()` | `member_approval_service.py:57-111` | Used by review API and background API — still valuable |
| `create_member_iban_history()` | `member_approval_service.py:114-180` | Used by review API — still valuable |
| `validate_approval_prerequisites()` | `member_approval_service.py:457-510` | Standalone validation utility |
| `MembershipCreationService` | `membership_creation_service.py` | Already the canonical path — no changes needed |
| `approve_membership_application()` | `membership_application_review.py:126-518` | Stays as the canonical API endpoint — only its local helper gets deleted |

---

## Task 1: Write tests verifying current approval behavior

Before changing anything, capture the current behavior in tests so we can verify nothing breaks.

**Files:**
- Create: `verenigingen/tests/backend/unit/services/test_approval_unification.py`

**Step 1: Write the test file**

```python
"""
Tests to verify approval orchestration unification.

These tests capture the CURRENT behavior of the approval flow so we can
verify that the refactoring preserves it exactly.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch, MagicMock


class TestApprovalOrchestrationCurrent(FrappeTestCase):
    """Tests that document the current approval behavior before refactoring."""

    def setUp(self):
        """Create a test member in Pending state."""
        # Find or create required membership type with dues schedule template
        if not frappe.db.exists("Membership Type", "Test Annual"):
            mt = frappe.get_doc({
                "doctype": "Membership Type",
                "name1": "Test Annual",
                "minimum_amount": 25,
            })
            mt.insert(ignore_permissions=True)

        # Create test member
        self.member = frappe.get_doc({
            "doctype": "Member",
            "first_name": "Test",
            "last_name": "Approval",
            "email": f"test-approval-{frappe.generate_hash(length=6)}@example.com",
            "application_status": "Pending",
            "status": "Pending",
            "application_id": "TEST-APP-001",
            "selected_membership_type": "Test Annual",
        })
        self.member.insert(ignore_permissions=True)

    def tearDown(self):
        """Clean up test data."""
        frappe.set_user("Administrator")
        if frappe.db.exists("Member", self.member.name):
            frappe.delete_doc("Member", self.member.name, force=True)

    def test_review_api_local_create_membership_and_invoice_exists(self):
        """Verify the review API's local create_membership_and_invoice exists (will be deleted)."""
        from verenigingen.api.membership_application_review import create_membership_and_invoice
        self.assertTrue(callable(create_membership_and_invoice))

    def test_approval_service_create_membership_and_invoice_exists(self):
        """Verify the approval service's create_membership_and_invoice exists (will be deleted)."""
        from verenigingen.services.member.approval.member_approval_service import (
            create_membership_and_invoice,
        )
        self.assertTrue(callable(create_membership_and_invoice))

    def test_process_member_approval_exists(self):
        """Verify process_member_approval exists (will be deleted)."""
        from verenigingen.services.member.approval.member_approval_service import (
            process_member_approval,
        )
        self.assertTrue(callable(process_member_approval))

    def test_finalize_member_approval_exists(self):
        """Verify finalize_member_approval exists (will be deleted)."""
        from vereinigingen.services.member.approval.member_approval_service import (
            finalize_member_approval,
        )
        self.assertTrue(callable(finalize_member_approval))

    def test_resolve_membership_type_still_importable(self):
        """resolve_membership_type must remain importable after refactoring."""
        from verenigingen.services.member.approval.member_approval_service import (
            resolve_membership_type,
        )
        self.assertTrue(callable(resolve_membership_type))

    def test_create_member_iban_history_still_importable(self):
        """create_member_iban_history must remain importable after refactoring."""
        from vereinigingen.services.member.approval.member_approval_service import (
            create_member_iban_history,
        )
        self.assertTrue(callable(create_member_iban_history))

    def test_background_api_imports_from_review_api(self):
        """Background API currently imports create_membership_and_invoice from review API."""
        # This import must work before refactoring
        from vereinigingen.api.membership_application_review import create_membership_and_invoice
        self.assertTrue(callable(create_membership_and_invoice))
```

**Step 2: Run test to verify it passes**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.unit.services.test_approval_unification -v`
Expected: All tests PASS (documenting current state)

**Step 3: Commit**

```bash
git add vereinigingen/tests/backend/unit/services/test_approval_unification.py
git commit -m "test: add approval orchestration baseline tests before unification"
```

---

## Task 2: Delete unused `process_member_approval()` and `finalize_member_approval()`

These have zero production callers. `process_member_approval()` is imported by the review API but never called. `finalize_member_approval()` is only called by `process_member_approval()`. `validate_member_fields()` is only called by `finalize_member_approval()`.

**Files:**
- Modify: `verenigingen/services/member/approval/member_approval_service.py`
- Modify: `verenigingen/api/membership_application_review.py` (remove unused imports)

**Step 1: Write failing test**

Update `test_approval_unification.py`:

```python
def test_process_member_approval_removed(self):
    """process_member_approval should no longer exist after cleanup."""
    with self.assertRaises(ImportError):
        from vereinigingen.services.member.approval.member_approval_service import (
            process_member_approval,
        )

def test_finalize_member_approval_removed(self):
    """finalize_member_approval should no longer exist after cleanup."""
    with self.assertRaises(ImportError):
        from vereinigingen.services.member.approval.member_approval_service import (
            finalize_member_approval,
        )
```

**Step 2: Run test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.unit.services.test_approval_unification::TestApprovalOrchestrationCurrent::test_process_member_approval_removed -v`
Expected: FAIL (functions still exist)

**Step 3: Delete the functions from `member_approval_service.py`**

Delete these functions (preserving `resolve_membership_type`, `create_member_iban_history`, `validate_approval_prerequisites`):

- `validate_member_fields()` (lines 27-54)
- `finalize_member_approval()` (lines 313-393)
- `process_member_approval()` (lines 395-454)

**Step 4: Remove unused imports from `membership_application_review.py`**

Change line 13-18 from:
```python
from verenigingen.services.member.approval.member_approval_service import (
    create_member_iban_history,
    finalize_member_approval,
    process_member_approval,
    resolve_membership_type,
    validate_approval_prerequisites,
)
```

To:
```python
from verenigingen.services.member.approval.member_approval_service import (
    create_member_iban_history,
    resolve_membership_type,
    validate_approval_prerequisites,
)
```

**Step 5: Run tests to verify they pass**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.unit.services.test_approval_unification -v`
Expected: New tests PASS, baseline tests for removed functions now also need updating (remove the "exists" tests, keep the "removed" tests)

**Step 6: Run full approval test suite to verify no breakage**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.components.test_membership_application -v`
Expected: All existing tests PASS (these functions had zero callers)

**Step 7: Commit**

```bash
git add vereinigingen/services/member/approval/member_approval_service.py
git add verenigingen/api/membership_application_review.py
git add vereinigingen/tests/backend/unit/services/test_approval_unification.py
git commit -m "refactor: remove unused process_member_approval and finalize_member_approval

These functions had zero production callers. The review API's
approve_membership_application() already handles approval through
MembershipCreationService, making these orchestrators redundant.

Preserved: resolve_membership_type, create_member_iban_history,
validate_approval_prerequisites (still have active callers)."
```

---

## Task 3: Delete approval service's `create_membership_and_invoice()`

The approval service's version (Location B) is only called from `process_member_approval()` which we just deleted.

**Files:**
- Modify: `vereinigingen/services/member/approval/member_approval_service.py`

**Step 1: Write failing test**

```python
def test_approval_service_create_membership_and_invoice_removed(self):
    """Approval service's create_membership_and_invoice should be removed."""
    with self.assertRaises(ImportError):
        from vereinigingen.services.member.approval.member_approval_service import (
            create_membership_and_invoice,
        )
```

**Step 2: Run test to verify it fails**

Expected: FAIL (function still exists)

**Step 3: Delete `create_membership_and_invoice()` from `member_approval_service.py`**

Delete lines 183-310 (the entire function).

**Step 4: Run tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.unit.services.test_approval_unification -v`
Expected: PASS

Run full suite: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.components.test_membership_application -v`
Expected: PASS (no callers of this function)

**Step 5: Commit**

```bash
git add vereinigingen/services/member/approval/member_approval_service.py
git add vereinigingen/tests/backend/unit/services/test_approval_unification.py
git commit -m "refactor: remove approval service's create_membership_and_invoice

This was only called by process_member_approval() which was removed
in the previous commit. MembershipCreationService is the canonical
path for membership creation during approval."
```

---

## Task 4: Delete review API's local `create_membership_and_invoice()` and fix background API

The review API's local copy (Location A, lines 68-123) is NOT called by the review API itself — `approve_membership_application()` uses `member.create_membership_on_approval()`. It IS called from `background_approval_api.py:187-191`.

**Files:**
- Modify: `vereinigingen/api/membership_application_review.py` (delete local function)
- Modify: `vereinigingen/api/background_approval_api.py` (use `member.create_membership_on_approval()` instead)

**Step 1: Write failing test for background API**

```python
class TestBackgroundApprovalRefactored(FrappeTestCase):
    """Tests that background API uses MembershipCreationService."""

    def test_review_api_no_longer_exports_create_membership_and_invoice(self):
        """Review API should no longer have create_membership_and_invoice."""
        import vereinigingen.api.membership_application_review as review_api
        self.assertFalse(
            hasattr(review_api, 'create_membership_and_invoice'),
            "create_membership_and_invoice should be removed from review API"
        )

    def test_background_api_does_not_import_create_membership_and_invoice(self):
        """Background API should not import create_membership_and_invoice from review API."""
        import ast
        import inspect
        import vereinigingen.api.background_approval_api as bg_api
        source = inspect.getsource(bg_api)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and 'membership_application_review' in node.module:
                    imported_names = [alias.name for alias in node.names]
                    self.assertNotIn(
                        'create_membership_and_invoice',
                        imported_names,
                        "background API should not import create_membership_and_invoice from review API"
                    )
```

**Step 2: Run test to verify it fails**

Expected: FAIL (function still exists in review API)

**Step 3: Delete `create_membership_and_invoice()` from review API**

Delete lines 68-123 from `membership_application_review.py`.

**Step 4: Refactor background API to use `member.create_membership_on_approval()`**

In `background_approval_api.py`, replace lines 183-210:

```python
# OLD CODE (lines 183-210):
# 2. Create invoice (synchronous for immediate user feedback)
invoice = None
if create_invoice:
    try:
        from vereinigingen.api.membership_application_review import create_membership_and_invoice
        membership, membership_type_doc, billing_amount = create_membership_and_invoice(
            member, membership_type
        )
        # ... customer creation, invoice creation ...
    except Exception as e:
        # ...
```

Replace with:

```python
# 2. Create membership and invoice via canonical MembershipCreationService path
invoice = None
membership = None
if create_invoice:
    try:
        # Build approval_fields same as review API does
        approval_fields = {
            "application_status": "Approved",
            "status": "Active",
            "member_since": today(),
            "reviewed_by": frappe.session.user,
            "review_date": now_datetime(),
            "selected_membership_type": membership_type,
        }
        if notes:
            approval_fields["review_notes"] = notes

        # If member has custom dues rate, set fee_override_reason
        if hasattr(member, "dues_rate") and member.dues_rate:
            if not getattr(member, "fee_override_reason", None):
                approval_fields["fee_override_reason"] = "Application approval"

        membership = member.create_membership_on_approval(
            create_invoice=True,
            approval_fields=approval_fields,
        )

        # Get invoice from member after create_membership_on_approval sets it
        member.reload()
        if hasattr(member, "application_invoice") and member.application_invoice:
            invoice = frappe.get_doc("Sales Invoice", member.application_invoice)

    except Exception as e:
        frappe.log_error(
            f"Membership/invoice creation failed during background approval for {member_name}: {str(e)}",
            "Background Approval Error",
        )
        invoice = None
```

Also remove the duplicate status-setting code (lines 120-181) since `approval_fields` in `create_membership_on_approval()` now handles this. The background API's manual retry loop for member.save() is no longer needed.

**Step 5: Run tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.unit.services.test_approval_unification -v`
Expected: PASS

Run full suite: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.components.test_membership_application -v`
Expected: PASS

**Step 6: Commit**

```bash
git add vereinigingen/api/membership_application_review.py
git add vereinigingen/api/background_approval_api.py
git add vereinigingen/tests/backend/unit/services/test_approval_unification.py
git commit -m "refactor: delete duplicate create_membership_and_invoice from review API

Removed the review API's local copy (lines 68-123) which was only used
by background_approval_api.py. Background API now uses
member.create_membership_on_approval() — the same canonical path as
the main review API approval flow.

This eliminates the divergence where the review API's copy didn't
respect application_dues_schedule (the user's payment plan selection)."
```

---

## Task 5: Deprecate `Member.approve_application()` and lifecycle service approval

`Member.approve_application()` is NOT called from the production approval flow. The review API calls `member.create_membership_on_approval()` directly. However, `Member.approve_application()` IS called from some test files, so we deprecate rather than delete.

**Files:**
- Modify: `verenigingen/vereinigingen/doctype/member/member.py`

**Step 1: Add deprecation warning to `Member.approve_application()`**

Change `member.py` lines 376-391:

```python
@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def approve_application(self) -> bool:
    """Approve this application and assign member ID.

    .. deprecated:: 2.1
        Not used in production approval flow. The canonical approval path is
        ``approve_membership_application()`` in ``api/membership_application_review.py``
        which calls ``member.create_membership_on_approval()`` directly.
        This method will be removed in a future version.
    """
    import warnings
    warnings.warn(
        "Member.approve_application() is deprecated. "
        "Use api.membership_application_review.approve_membership_application() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    # Use lifecycle service for core approval logic
    result = get_member_lifecycle_service().approve_application(self)

    if not result.success:
        if result.errors:
            frappe.throw(_(result.errors[0]))
        else:
            frappe.throw(_(result.error_message or "Application approval failed"))

    # Create membership - this should trigger the dues schedule logic
    return self.create_membership_on_approval()
```

**Step 2: Run tests to verify no breakage**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen -v`
Expected: PASS (deprecation warning doesn't break anything)

**Step 3: Commit**

```bash
git add vereinigingen/vereinigingen/doctype/member/member.py
git commit -m "refactor: deprecate Member.approve_application()

This method is not used in the production approval flow. The canonical
path is approve_membership_application() in the review API, which calls
member.create_membership_on_approval() directly.

Marked deprecated with warning; will be removed in a future version
after test files are updated."
```

---

## Task 6: Update module docstring and verify final state

**Files:**
- Modify: `vereinigingen/services/member/approval/member_approval_service.py` (update module docstring)
- Modify: `verenigingen/tests/backend/unit/services/test_approval_unification.py` (finalize tests)

**Step 1: Update module docstring**

The approval service module docstring still references deleted functions. Update it:

```python
"""
Member Approval Service - Reusable approval workflow utilities.

This module provides utility functions used during the membership approval process.
The main approval orchestration lives in:
- API layer: api/membership_application_review.py::approve_membership_application()
- Service layer: services/member/approval/membership_creation_service.py::MembershipCreationService

Functions in this module:
    - resolve_membership_type(): Validate and resolve membership type with fallbacks
    - create_member_iban_history(): Initialize IBAN history tracking on approval
    - validate_approval_prerequisites(): Check member readiness for approval
"""
```

**Step 2: Update test file — remove baseline "exists" tests, keep "removed" tests**

Remove the tests that checked functions exist (they no longer do). Keep the tests that verify they're removed. Add a final integration-style test:

```python
def test_canonical_approval_path_works(self):
    """Verify the canonical approval path (review API -> MembershipCreationService) works."""
    from vereinigingen.api.membership_application_review import approve_membership_application

    # This test verifies the function is importable and callable
    # Full integration testing is done in test_membership_application.py
    self.assertTrue(callable(approve_membership_application))

def test_membership_creation_service_is_canonical(self):
    """MembershipCreationService should be the single path for membership creation."""
    from vereinigingen.services.member.approval.membership_creation_service import (
        MembershipCreationService,
    )
    service = MembershipCreationService()
    self.assertTrue(hasattr(service, 'create_membership_on_approval'))
```

**Step 3: Run full test suite**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.components.test_membership_application -v`
Expected: ALL PASS

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.unit.services.test_approval_unification -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add vereinigingen/services/member/approval/member_approval_service.py
git add vereinigingen/tests/backend/unit/services/test_approval_unification.py
git commit -m "refactor: finalize approval orchestration unification

Updated module docstrings to reflect new architecture. The approval flow
is now:

  review API (HTTP layer)
    → input validation, permissions, response formatting
    → member.create_membership_on_approval()
      → MembershipCreationService (canonical business logic)

Deleted: 3 duplicate functions (~353 LOC)
Deprecated: Member.approve_application() (unused in production)
Preserved: resolve_membership_type, create_member_iban_history"
```

---

## Task 7: Run comprehensive verification

**Step 1: Run all approval-related tests**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.components.test_membership_application -v
```

**Step 2: Run integration tests**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.integration.test_membership_approval_real -v
```

**Step 3: Run workflow tests**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module verenigingen.tests.backend.workflows.test_chapter_membership_workflow -v
```

**Step 4: Run concurrency tests**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.integration.test_concurrency_safety -v
```

**Step 5: Run pre-commit validators**

```bash
cd ~/frappe-bench/apps/vereinigingen && pre-commit run --all-files
```

**Step 6: Commit any fixes from verification**

---

## Architecture After Refactoring

```
┌─────────────────────────────────────────────────────────┐
│ HTTP Layer (thin)                                        │
│                                                          │
│ approve_membership_application()                         │
│   ├── Input sanitization (APIValidator)                  │
│   ├── Idempotency check                                  │
│   ├── Permission check (chapter security)                │
│   ├── resolve_membership_type()  ← approval service      │
│   ├── validate_membership_type_for_approval()            │
│   ├── assign_member_to_chapter()                         │
│   ├── create_member_iban_history()  ← approval service   │
│   │                                                      │
│   ├── member.create_membership_on_approval()  ──────┐    │
│   │     (approval_fields passed through)            │    │
│   │                                                 ▼    │
│   │   ┌─────────────────────────────────────────────┐    │
│   │   │ MembershipCreationService (CANONICAL)       │    │
│   │   │   ├── Validate membership type              │    │
│   │   │   ├── Create/reuse membership               │    │
│   │   │   ├── Ensure dues schedule                  │    │
│   │   │   ├── Create invoice                        │    │
│   │   │   ├── Consolidate member updates            │    │
│   │   │   │   (sets approval_fields here)           │    │
│   │   │   └── Save with rollback protection         │    │
│   │   └─────────────────────────────────────────────┘    │
│   │                                                      │
│   ├── Activate volunteer record                          │
│   ├── Create user account                                │
│   ├── Send approval notification                         │
│   └── Return response                                    │
│                                                          │
│ approve_membership_application_background()              │
│   ├── Same input validation + permissions                │
│   ├── member.create_membership_on_approval()  ──────┘    │
│   │     (same canonical path)                            │
│   └── Emit events for background processing              │
└──────────────────────────────────────────────────────────┘
```

## Files Changed Summary

| File | Action | LOC Change |
|------|--------|------------|
| `services/member/approval/member_approval_service.py` | Delete 4 functions, update docstring | -269 |
| `api/membership_application_review.py` | Delete local function, remove imports | -58 |
| `api/background_approval_api.py` | Replace import + inline code with canonical path | -60, +25 |
| `verenigingen/doctype/member/member.py` | Add deprecation warning | +8 |
| `tests/backend/unit/services/test_approval_unification.py` | New test file | +80 |
| **Net** | | **~-274 LOC** |

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Existing tests import deleted functions | Medium | Task 1 baseline tests catch this; grep for imports |
| Background API behavior changes | Low | Same `MembershipCreationService` path; approval_fields pattern preserved |
| `Member.approve_application()` callers break | Low | Deprecated, not deleted; still works |
| Race conditions in background approval | Low | `MembershipCreationService._save_member_with_rollback()` handles retries |
