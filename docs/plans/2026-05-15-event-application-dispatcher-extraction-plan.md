# Event Application — Dispatcher Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the `MijnRoodEventApplicationService` class + module-level helpers from `event_application_service.py` (962 LOC after PR #6) into a new `dispatcher.py` under `mijnrood_sync/services/event_application/`. The original `event_application_service.py` becomes a thin re-export shim. This is Phase 1, PR #7 of the Tier C refactor — the final extraction.

**Architecture:** Mechanical relocation. The class stays structurally identical (all shim methods preserved, `_acr_queued_members` state preserved, `_sync_division_to_chapter` preserved, dispatch logic preserved). Only the file location changes. `event_application_service.py` shrinks to ~15 LOC of `from … import …` statements re-exporting the public surface (`MijnRoodEventApplicationService`, `get_event_application_service`, `batch_approve`, `batch_approve_and_apply`, `batch_apply`).

**Reference spec:** `docs/plans/2026-05-12-event-application-service-refactor-design.md`

---

## Why this is a separate PR

The shim-heavy class is doing exactly its job — preserving caller/test compatibility through Phase 2 (deleting mocked tests) and Phase 3 (result-idiom unification). Restructuring `apply_event` to bypass the shim methods would risk breaking external callers (`mijnrood_sync_event.py` DocType controller, batch_approve worker, mocked test suite) all at once. PR #7 ships ONLY the file relocation; structural simplification of the dispatcher's internals can happen as part of Phase 2/3 cleanup.

---

## File Structure

**Create:**
- `verenigingen/mijnrood_sync/services/event_application/dispatcher.py` — Full `MijnRoodEventApplicationService` class + `get_event_application_service` accessor + `batch_approve` / `batch_approve_and_apply` / `batch_apply` whitelist endpoints + internal `_batch_*_worker` functions + `_TABLE_PRIORITY` constant

**Modify:**
- `verenigingen/mijnrood_sync/services/event_application_service.py` — Replace entire content with re-export shim

**Do not touch:**
- All extracted services (PRs 1-6) — they import `event_application_service_*.py` paths only implicitly (none directly)
- Tests — `test_event_application_service.py` imports `from verenigingen.mijnrood_sync.services.event_application_service import (MijnRoodEventApplicationService, ...)`. The re-export shim preserves this import path verbatim.

---

## Task 1: Move god-class + module-level helpers to dispatcher.py

**Files:**
- Create: `verenigingen/mijnrood_sync/services/event_application/dispatcher.py`
- Modify: `verenigingen/mijnrood_sync/services/event_application_service.py`

- [ ] **Step 1: Inspect current `event_application_service.py` to confirm scope**

Run:
```bash
wc -l /home/frappeuser/frappe-bench/apps/verenigingen/verenigingen/mijnrood_sync/services/event_application_service.py
grep -n "^def\|^class\|^[A-Z_]*\s*=" /home/frappeuser/frappe-bench/apps/verenigingen/verenigingen/mijnrood_sync/services/event_application_service.py
```

Expected: ~962 LOC, single class + 4 module-level functions (`get_event_application_service`, `batch_approve`, `batch_approve_and_apply`, `batch_apply`, `_batch_event_worker`, `_batch_approve_and_apply_worker`, `_batch_apply_worker`) + 2 module-level constants (`_service_instance`, `_TABLE_PRIORITY`).

- [ ] **Step 2: Read the entire `event_application_service.py` file**

You need to know exactly what's in there before moving it. Read top to bottom.

- [ ] **Step 3: Create `dispatcher.py`**

Copy the ENTIRE content of `event_application_service.py` into a new file at `verenigingen/mijnrood_sync/services/event_application/dispatcher.py`. Do NOT change anything inside the class or the module-level functions. The only adjustments:

- Update the module docstring to reflect the new home:
  ```python
  """
  MijnRood Event Application Service — Dispatcher

  Phase 1, PR #7 of the Tier C decomposition: the dispatcher module
  housing MijnRoodEventApplicationService, its singleton accessor, and
  the batch_approve/batch_apply whitelist endpoints. All per-concern
  logic has been extracted into the sibling service modules
  (mapping_service, member_sync_service, application_sync_service,
  volunteer_sync_service, termination_sync_service,
  related_records_orchestrator). The 30+ shim methods on this class
  exist to preserve caller/test compatibility through Phase 2-3.

  Originally defined in event_application_service.py — that module is
  now a re-export shim importing from this file.
  """
  ```

- The imports stay verbatim from `event_application_service.py`. Verify each import still resolves.

- The class definition stays verbatim. Method bodies are already 1-line shims to the extracted services (from PRs 2-6).

- `_sync_division_to_chapter` stays verbatim (it's a ~100-LOC chapter-sync method that was never extracted; it lives here).

- Module-level `_service_instance`, `get_event_application_service`, `_TABLE_PRIORITY`, `batch_approve`, `batch_approve_and_apply`, `batch_apply`, `_batch_event_worker`, `_batch_approve_and_apply_worker`, `_batch_apply_worker` all stay verbatim.

- [ ] **Step 4: Reduce `event_application_service.py` to a re-export shim**

Replace the entire content of `verenigingen/mijnrood_sync/services/event_application_service.py` with:

```python
"""MijnRood Event Application Service — re-export shim.

This module's content has been moved to
verenigingen/mijnrood_sync/services/event_application/dispatcher.py
as Phase 1, PR #7 of the Tier C refactor (see
docs/plans/2026-05-12-event-application-service-refactor-design.md).

Existing callers (DocType controller, test suite, whitelist endpoint
references) import from this path; the re-exports below preserve those
import paths verbatim so no caller needs to change.
"""

from verenigingen.mijnrood_sync.services.event_application.dispatcher import (  # noqa: F401
    MijnRoodEventApplicationService,
    batch_apply,
    batch_approve,
    batch_approve_and_apply,
    get_event_application_service,
)
```

The `# noqa: F401` suppresses the "imported but unused" warning since these symbols ARE used — by external callers via this re-export path.

- [ ] **Step 5: Verify file parses**

```bash
cd ~/frappe-bench && env/bin/python -c "import ast; ast.parse(open('apps/verenigingen/verenigingen/mijnrood_sync/services/event_application_service.py').read()); print('OK')"
cd ~/frappe-bench && env/bin/python -c "import ast; ast.parse(open('apps/verenigingen/verenigingen/mijnrood_sync/services/event_application/dispatcher.py').read()); print('OK')"
```

Both expected: `OK`.

- [ ] **Step 6: Verify imports resolve**

```bash
cd ~/frappe-bench && env/bin/python -c "
from verenigingen.mijnrood_sync.services.event_application_service import (
    MijnRoodEventApplicationService,
    get_event_application_service,
    batch_approve,
    batch_approve_and_apply,
    batch_apply,
)
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 7: Run the full event_application test surface**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_related_records_orchestrator

cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_termination_sync_service

cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_volunteer_sync_service

cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_application_sync_service

cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_member_sync_service

cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_mapping_service
```

Expected per-PR: 27, 6, 44, 22, 10, 16 pass.

- [ ] **Step 8: Run the existing mocked test suite**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.test_event_application_service
```

Expected: 140/150 pass (same baseline as PR #6). The test file imports
`MijnRoodEventApplicationService` from `event_application_service` — the
re-export preserves this path, so no changes should be needed. If new
failures appear, they likely involve `patch("event_application_service.X")`
strings where `X` is no longer importable directly because it lives in
`dispatcher.py` now (re-exports satisfy `from … import X` but NOT
`patch("…event_application_service.X")` for module-attribute patches).

Common patches that may break:
- `patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")` → still works because `event_application_service` is a real module (just a shim).
- `patch.object(MijnRoodEventApplicationService, "_xxx")` → works (object-level patch follows the class regardless of module).
- `patch("verenigingen.mijnrood_sync.services.event_application_service._sync_division_to_chapter")` → likely BREAKS if anything patches module-level free functions. None expected — all bodies are class methods.

If retargeting is needed, replace `event_application_service.X` → `event_application.dispatcher.X` for the specific broken patches.

- [ ] **Step 9: Run the mijnrood_sync DocType controller test (if any)**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --doctype "MijnRood Sync Event"
```

Verify the controller method `apply_event` (which calls `get_event_application_service()`) still resolves.

- [ ] **Step 10: Smoke test the whitelist endpoints via console**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org console <<'EOF'
from verenigingen.mijnrood_sync.services.event_application_service import (
    batch_approve, batch_approve_and_apply, batch_apply, get_event_application_service,
)
print(batch_approve, batch_approve_and_apply, batch_apply, get_event_application_service)
service = get_event_application_service()
print(type(service).__name__, "loaded")
EOF
```

Expected output: function references printed + `MijnRoodEventApplicationService loaded`.

- [ ] **Step 11: Pre-commit checks**

```bash
cd ~/frappe-bench/apps/verenigingen && pre-commit run --files \
  verenigingen/mijnrood_sync/services/event_application_service.py \
  verenigingen/mijnrood_sync/services/event_application/dispatcher.py
```

Expected: all hooks pass. The `whitelist-type-safety` hook may warn on
`batch_approve()` if that pre-existing warning is still present — that
is unchanged from PR #6 and acceptable.

- [ ] **Step 12: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application_service.py \
        verenigingen/mijnrood_sync/services/event_application/dispatcher.py
# Include retargeted mocked tests if step 8 required them
# git add verenigingen/tests/services/test_event_application_service.py
git commit -m "$(cat <<'EOF'
refactor(mijnrood-sync): move dispatcher to dispatcher.py; event_application_service becomes re-export shim

Phase 1, PR #7 (final extraction) of the Tier C decomposition. The
MijnRoodEventApplicationService class and its module-level helpers
(get_event_application_service, batch_approve, batch_approve_and_apply,
batch_apply, plus internal worker functions) move from
event_application_service.py to a new dispatcher.py under
event_application/.

event_application_service.py shrinks from ~962 LOC to a ~15-LOC
re-export shim. All public symbols stay importable from the original
path (preserving the DocType controller import in
mijnrood_sync_event.py and the test suite's import in
test_event_application_service.py — no caller changes needed).

The class itself is preserved verbatim: 30+ shim methods, the per-event
_acr_queued_members dedup state, the _sync_division_to_chapter chapter
helper, and the apply_event dispatch logic all stay as-is. Structural
simplification of the dispatcher's internals (collapsing the 13 _apply_*
shims into apply_event's switch) is deferred to Phase 2-3 cleanup.

Spec: docs/plans/2026-05-12-event-application-service-refactor-design.md
EOF
)"
```

- [ ] **Step 13: Push**

```bash
SKIP=jest-testing,javascript-doctype-validator git push
```

---

## Success Criteria

1. `verenigingen/mijnrood_sync/services/event_application/dispatcher.py` exists and contains the full `MijnRoodEventApplicationService` class + module-level helpers verbatim from the original location.
2. `verenigingen/mijnrood_sync/services/event_application_service.py` is ≤ 20 LOC and contains only re-exports (no class body, no function bodies).
3. All PR #1-6 service tests still pass.
4. `test_event_application_service.py` baseline (140/150) preserved; retargeting only as needed for module-attribute patches.
5. `mijnrood_sync_event.py` DocType controller still imports `get_event_application_service` from the old path successfully.
6. `batch_approve`, `batch_approve_and_apply`, `batch_apply` whitelist endpoints still resolve from the old path.
7. Pre-commit hooks pass on every touched file.
8. God-class LOC count drops from 962 to ~15.

---

## Phase 1 completion check

After PR #7, Phase 1 is **complete**:
- 6 of 7 services extracted (mapping, member_sync, application_sync, volunteer_sync, termination_sync, related_records_orchestrator)
- 7th "service" is the dispatcher itself, now in dispatcher.py
- Original `event_application_service.py` is a ≤20-LOC re-export shim
- Cumulative LOC reduction: 2,433 → ~15 = **-2,418 LOC** from the original god-class

Phase 2 (PR #8) and Phase 3 (PR #9) follow per the master spec.
