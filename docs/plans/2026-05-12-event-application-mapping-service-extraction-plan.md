# Event Application — Mapping Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the mapping concerns (`_map_mijnrood_to_member_fields`, `_resolve_division_id`, `_extract_email`) from `event_application_service.py` (2,433 LOC god-class) into a new `MijnRoodMappingService` under `mijnrood_sync/services/event_application/`. This is Phase 1, PR #1 of the Tier C refactor.

**Architecture:** New sub-package `mijnrood_sync/services/event_application/` with `mapping_service.py` housing the `MijnRoodMappingService` class (two methods, plus the `extract_email` module function). The god-class loses ~80 LOC and gains a delegation seam via a singleton accessor `get_mapping_service()`. Real-DB integration tests live under `tests/services/event_application/test_mapping_service.py` using the existing `EnhancedTestCase`/`EnhancedTestDataFactory` infrastructure. Existing mocked tests in `tests/services/test_event_application_service.py` are left untouched (they continue to pass via the delegating call sites).

**Tech Stack:** Frappe Framework, Python 3.12+, pytest via `bench run-tests`, `EnhancedTestCase` for real-DB integration tests.

**Reference spec:** `docs/plans/2026-05-12-event-application-service-refactor-design.md`

---

## File Structure

**Create:**
- `verenigingen/mijnrood_sync/services/event_application/__init__.py` — sub-package marker + re-exports
- `verenigingen/mijnrood_sync/services/event_application/mapping_service.py` — `MijnRoodMappingService` + `extract_email` + `get_mapping_service`
- `verenigingen/tests/services/event_application/__init__.py` — sub-package marker
- `verenigingen/tests/services/event_application/test_mapping_service.py` — real-DB integration tests

**Modify:**
- `verenigingen/mijnrood_sync/services/event_application_service.py` — delete the three extracted methods; replace all 11 internal call sites with calls to the new service

**Do not touch:**
- `verenigingen/tests/services/test_event_application_service.py` — existing mocked tests must keep passing
- `verenigingen/mijnrood_sync/doctype/mijnrood_sync_event/mijnrood_sync_event.py` — DocType controller still imports the god-class accessor; no change needed
- `verenigingen/mijnrood_sync/field_mapping.py` — referenced as-is

---

## Task 1: Create the sub-package skeleton

**Files:**
- Create: `verenigingen/mijnrood_sync/services/event_application/__init__.py`
- Create: `verenigingen/tests/services/event_application/__init__.py`

- [ ] **Step 1: Create the production sub-package**

Write `verenigingen/mijnrood_sync/services/event_application/__init__.py`:

```python
"""Per-concern services extracted from event_application_service.py.

Phase 1 of the Tier C refactor (see docs/plans/2026-05-12-event-
application-service-refactor-design.md). Each service is callable in
isolation and tested against a real DB.
"""
```

- [ ] **Step 2: Create the test sub-package**

Write `verenigingen/tests/services/event_application/__init__.py`:

```python
"""Integration tests for services in mijnrood_sync.services.event_application."""
```

- [ ] **Step 3: Verify import works**

Run:
```bash
cd ~/frappe-bench && env/bin/python -c "from verenigingen.mijnrood_sync.services import event_application; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/__init__.py \
        verenigingen/tests/services/event_application/__init__.py
git commit -m "chore(mijnrood-sync): scaffold event_application sub-package"
```

---

## Task 2: Write failing tests for `extract_email`

**Files:**
- Test: `verenigingen/tests/services/event_application/test_mapping_service.py`

- [ ] **Step 1: Write the failing test file**

Write `verenigingen/tests/services/event_application/test_mapping_service.py`:

```python
"""Real-DB integration tests for MijnRoodMappingService.

extract_email() is tested as a pure helper; map_member_fields() and
resolve_division_id() require Chapter / MijnRood Sync State fixtures.
"""

import frappe

from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    extract_email,
    get_mapping_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestExtractEmail(EnhancedTestCase):
    """extract_email is a pure helper — no DB needed but kept here for cohesion."""

    def test_returns_value_for_valid_email_string(self):
        self.assertEqual(extract_email("alice@example.org"), "alice@example.org")

    def test_returns_none_for_numeric_string(self):
        # MijnRood's email_id column sometimes contains a numeric FK
        self.assertIsNone(extract_email("12345"))

    def test_returns_none_for_string_without_at_sign(self):
        self.assertIsNone(extract_email("not-an-email"))

    def test_returns_none_for_none(self):
        self.assertIsNone(extract_email(None))

    def test_returns_none_for_integer(self):
        self.assertIsNone(extract_email(12345))

    def test_returns_none_for_empty_string(self):
        self.assertIsNone(extract_email(""))
```

- [ ] **Step 2: Run the tests to verify they fail with import error**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_mapping_service
```
Expected: ImportError / ModuleNotFoundError on `verenigingen.mijnrood_sync.services.event_application.mapping_service`

---

## Task 3: Implement `extract_email` and minimal scaffold

**Files:**
- Create: `verenigingen/mijnrood_sync/services/event_application/mapping_service.py`

- [ ] **Step 1: Write the minimal module**

Write `verenigingen/mijnrood_sync/services/event_application/mapping_service.py`:

```python
"""MijnRoodMappingService — translates MijnRood row dicts into Member field dicts.

Extracted from event_application_service.py as Phase 1, PR #1 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service is stateless and read-only — it performs lookups in Chapter
and MijnRood Sync State for division resolution, and consults the
Settings child tables (status / role mapping) via field_mapping.py
helpers, but writes nothing.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger("verenigingen.mijnrood_sync.event_application.mapping")


def extract_email(value: Any) -> Optional[str]:
    """Return value only if it looks like an email address.

    MijnRood's email_id column may contain a numeric FK rather than
    an actual email string. Passing a bare number to a Frappe Data
    field with options=Email causes a validation error.
    """
    if not value or not isinstance(value, str):
        return None
    if "@" not in value:
        return None
    return value


class MijnRoodMappingService:
    """Translates MijnRood DB rows to Member field dicts. Stateless."""


_service_instance: Optional[MijnRoodMappingService] = None


def get_mapping_service() -> MijnRoodMappingService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodMappingService()
    return _service_instance
```

- [ ] **Step 2: Run the tests to verify they pass**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_mapping_service
```
Expected: 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/mapping_service.py \
        verenigingen/tests/services/event_application/test_mapping_service.py
git commit -m "feat(mijnrood-sync): add MijnRoodMappingService with extract_email"
```

---

## Task 4: Write failing tests for `resolve_division_id`

**Files:**
- Modify: `verenigingen/tests/services/event_application/test_mapping_service.py`

- [ ] **Step 1: Append the test class**

Add to `verenigingen/tests/services/event_application/test_mapping_service.py`:

```python
class TestResolveDivisionId(EnhancedTestCase):
    """resolve_division_id checks Chapter.mijnrood_division_id, then
    falls back to MijnRood Sync State raw_data for chapters that predate
    the ID field.
    """

    def test_returns_chapter_name_via_direct_id_field(self):
        # Create a chapter with mijnrood_division_id set. create_chapter
        # accepts arbitrary kwargs and forwards them to the doc.
        chapter = self.factory.create_chapter(mijnrood_division_id=42)

        service = get_mapping_service()
        result = service.resolve_division_id(42)

        self.assertEqual(result, chapter.name)

    def test_falls_back_to_sync_state_when_id_field_unset(self):
        # Create a sync state row for a division that's NOT linked to a
        # Chapter via the direct field. raw_data must include "name".
        state = frappe.get_doc({
            "doctype": "MijnRood Sync State",
            "mijnrood_table": "admin_division",
            "mijnrood_row_id": 999,
            "state_key": "admin_division:999",
            "raw_data": '{"name": "Sync-State-Chapter"}',
            "row_checksum": "0" * 32,
        }).insert(ignore_permissions=True)
        self.addCleanup(lambda: frappe.delete_doc(
            "MijnRood Sync State", state.name, ignore_permissions=True, force=True
        ))

        service = get_mapping_service()
        result = service.resolve_division_id(999)

        self.assertEqual(result, "Sync-State-Chapter")

    def test_returns_none_when_neither_source_has_match(self):
        service = get_mapping_service()
        result = service.resolve_division_id(987654)  # nonexistent

        self.assertIsNone(result)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_mapping_service
```
Expected: `AttributeError: 'MijnRoodMappingService' object has no attribute 'resolve_division_id'` on the 3 new tests; the 6 extract_email tests still pass.

---

## Task 5: Implement `resolve_division_id`

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application/mapping_service.py`

- [ ] **Step 1: Add the method to `MijnRoodMappingService`**

Add to `verenigingen/mijnrood_sync/services/event_application/mapping_service.py`:

- Insert `import json` and `import frappe` near the existing imports
- Replace the empty `class MijnRoodMappingService:` body with:

```python
class MijnRoodMappingService:
    """Translates MijnRood DB rows to Member field dicts. Stateless."""

    def resolve_division_id(self, division_id: int) -> Optional[str]:
        """Resolve a MijnRood division_id to a Chapter name.

        Checks the Chapter's mijnrood_division_id field first (direct lookup),
        then falls back to Sync State for chapters that predate the ID field.
        """
        # Direct lookup via the ID field on Chapter
        chapter_name = frappe.db.get_value(
            "Chapter", {"mijnrood_division_id": division_id}, "name"
        )
        if chapter_name:
            return chapter_name

        # Fallback: resolve via stored sync state raw data
        state = frappe.db.get_value(
            "MijnRood Sync State",
            {"mijnrood_table": "admin_division", "mijnrood_row_id": division_id},
            "raw_data",
        )
        if state:
            data = json.loads(state)
            return data.get("name")
        return None
```

- [ ] **Step 2: Run the tests to verify they pass**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_mapping_service
```
Expected: 9 tests pass (6 extract_email + 3 resolve_division_id).

- [ ] **Step 3: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/mapping_service.py \
        verenigingen/tests/services/event_application/test_mapping_service.py
git commit -m "feat(mijnrood-sync): add resolve_division_id to MijnRoodMappingService"
```

---

## Task 6: Write failing tests for `map_member_fields`

**Files:**
- Modify: `verenigingen/tests/services/event_application/test_mapping_service.py`

- [ ] **Step 1: Append the test class**

Add to `verenigingen/tests/services/event_application/test_mapping_service.py`:

```python
class TestMapMemberFields(EnhancedTestCase):
    """map_member_fields translates MijnRood row dicts via the configured
    status / role / period mappings. Status_id with no mapping must raise
    ValueError (Tier A audit guarantee — event remains visible to operator).
    """

    def setUp(self):
        super().setUp()
        # Ensure a known status mapping exists. Use mijnrood_status_id=999
        # to avoid collision with seed data.
        settings = frappe.get_single("MijnRood Sync Settings")
        original = list(settings.status_mapping or [])
        # Pick a Membership Type that already exists in the test fixture
        # set, or create one if not.
        membership_type = self.factory.ensure_membership_type("Mapping Test Type")
        settings.append("status_mapping", {
            "mijnrood_status_id": 999,
            "label": "Test Status",
            "membership_type_string": "test",
            "is_active": 1,
            "verenigingen_membership_type": membership_type.name,
        })
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        def _cleanup():
            settings = frappe.get_single("MijnRood Sync Settings")
            settings.status_mapping = original
            settings.save(ignore_permissions=True)
            frappe.db.commit()
        self.addCleanup(_cleanup)
        # Force the field_mapping cache to refresh
        frappe.cache().delete_value("mijnrood_status_mapping")

    def test_maps_basic_field_translations(self):
        # MIJNROOD_TO_MEMBER_FIELD_MAP is the source of truth. Pick a few
        # well-known mappings to assert the loop runs.
        result = get_mapping_service().map_member_fields({
            "first_name": "Alice",
            "last_name": "Example",
            "current_membership_status_id": 999,
        })
        self.assertEqual(result["first_name"], "Alice")
        self.assertEqual(result["last_name"], "Example")

    def test_filters_empty_string_and_none_values(self):
        result = get_mapping_service().map_member_fields({
            "first_name": "",
            "last_name": None,
            "city": "Amsterdam",
            "current_membership_status_id": 999,
        })
        self.assertNotIn("first_name", result)
        self.assertNotIn("last_name", result)
        self.assertEqual(result["city"], "Amsterdam")

    def test_status_id_with_explicit_mapping_sets_membership_type(self):
        result = get_mapping_service().map_member_fields({
            "current_membership_status_id": 999,
        })
        self.assertIn("membership_type", result)
        self.assertEqual(result["membership_type"], "Mapping Test Type")

    def test_unmapped_status_id_raises_valueerror(self):
        # Tier A guarantee: silent skip → ValueError → event surfaces in queue
        with self.assertRaises(ValueError) as cm:
            get_mapping_service().map_member_fields({
                "id": 12345,
                "current_membership_status_id": 99999,  # not in mapping
            })
        self.assertIn("99999", str(cm.exception))
        self.assertIn("Lidmaatschapstypes", str(cm.exception))

    def test_converts_cents_to_euros(self):
        result = get_mapping_service().map_member_fields({
            "current_membership_status_id": 999,
            "contribution_per_period_in_cents": 1250,
        })
        self.assertEqual(result["dues_rate"], 12.5)

    def test_maps_known_contribution_period(self):
        result = get_mapping_service().map_member_fields({
            "current_membership_status_id": 999,
            "contribution_period": 1,  # Quarterly in MijnRood
        })
        self.assertEqual(result["payment_period"], "Per kwartaal")

    def test_unknown_contribution_period_is_logged_and_omitted(self):
        # logger.warning, key not set — should not raise
        result = get_mapping_service().map_member_fields({
            "current_membership_status_id": 999,
            "contribution_period": 99,
        })
        self.assertNotIn("payment_period", result)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_mapping_service
```
Expected: `AttributeError: 'MijnRoodMappingService' object has no attribute 'map_member_fields'` on the 7 new tests.

---

## Task 7: Implement `map_member_fields`

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application/mapping_service.py`

- [ ] **Step 1: Add the method**

Add to `verenigingen/mijnrood_sync/services/event_application/mapping_service.py`:

- Add to imports at top of file:

```python
from verenigingen.mijnrood_sync.field_mapping import (
    MIJNROOD_TO_MEMBER_FIELD_MAP,
    get_status_id_map,
    get_verenigingen_membership_type_for_status_id,
)
from verenigingen.mijnrood_sync.utils import safe_int
```

- Add the method to `MijnRoodMappingService` (after `resolve_division_id`):

```python
    def map_member_fields(self, mijnrood_data: dict) -> dict:
        """Map MijnRood database row to intermediate field names.

        These intermediate names match what MemberImportService.update_member_fields()
        expects (same names as csv_data_validator.py FIELD_MAPPING values).

        Raises ValueError when current_membership_status_id has no mapping
        configured — operator must add the mapping and re-apply the event.
        """
        row_data: dict = {}
        for mijnrood_col, member_field in MIJNROOD_TO_MEMBER_FIELD_MAP.items():
            value = mijnrood_data.get(mijnrood_col)
            if value is not None and value != "":
                row_data[member_field] = value

        # Convert status ID to membership type — prefer explicit mapping,
        # fall back to status string, then fail loudly if neither matches.
        status_id = safe_int(mijnrood_data.get("current_membership_status_id"))
        if status_id:
            explicit_type = get_verenigingen_membership_type_for_status_id(status_id)
            if explicit_type:
                row_data["membership_type"] = explicit_type
            else:
                status_id_map = get_status_id_map()
                if status_id in status_id_map:
                    row_data["membership_type"] = status_id_map[status_id]
                else:
                    # Fail the event instead of silently importing a member
                    # without a membership type. Operator fixes the mapping,
                    # then re-runs. (Tier A audit guarantee.)
                    raise ValueError(
                        f"MijnRood status ID {status_id} (member {mijnrood_data.get('id')}) "
                        f"has no mapping configured. Add it under "
                        f"MijnRood Sync Settings → Lidmaatschapstypes, then re-apply this event."
                    )

        # Convert contribution amount from cents to euros
        cents = safe_int(mijnrood_data.get("contribution_per_period_in_cents"))
        if cents:
            row_data["dues_rate"] = cents / 100.0

        # Convert contribution period integer to Dutch string for template resolution
        # MijnRood: 0=Monthly, 1=Quarterly, 2=Annually (see Member.php constants)
        period_int = safe_int(mijnrood_data.get("contribution_period"))
        period_map = {0: "Maandelijks", 1: "Per kwartaal", 2: "Jaarlijks"}
        if period_int is not None:
            if period_int in period_map:
                row_data["payment_period"] = period_map[period_int]
            else:
                logger.warning(
                    "Unknown contribution_period value %s for MijnRood ID %s",
                    period_int,
                    mijnrood_data.get("id"),
                )

        return row_data
```

- [ ] **Step 2: Run the tests to verify they pass**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_mapping_service
```
Expected: 16 tests pass (6 extract_email + 3 resolve_division_id + 7 map_member_fields).

- [ ] **Step 3: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/mapping_service.py \
        verenigingen/tests/services/event_application/test_mapping_service.py
git commit -m "feat(mijnrood-sync): add map_member_fields to MijnRoodMappingService"
```

---

## Task 8: Wire the new service into the god-class

The god-class currently has three internal helpers (`_map_mijnrood_to_member_fields`, `_resolve_division_id`, `_extract_email`) called from 11 sites. Replace the call sites with calls to the new service, then delete the old helper methods.

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application_service.py`

- [ ] **Step 1: Add the new service import at the top of `event_application_service.py`**

Open `verenigingen/mijnrood_sync/services/event_application_service.py`. Find the existing imports near the top. Add this line near the other `verenigingen.mijnrood_sync.*` imports:

```python
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    extract_email,
    get_mapping_service,
)
```

- [ ] **Step 2: Replace all 5 call sites of `_map_mijnrood_to_member_fields`**

In `verenigingen/mijnrood_sync/services/event_application_service.py`, run a find-and-replace (or do them manually at lines ~708, ~896, ~988, ~1075, ~1123 — line numbers may shift as you edit):

Replace each occurrence of:
```python
row_data = self._map_mijnrood_to_member_fields(new_data)
```

With:
```python
row_data = get_mapping_service().map_member_fields(new_data)
```

- [ ] **Step 3: Replace all 4 call sites of `_resolve_division_id`**

At lines ~642, ~1626, ~1895, ~1983, replace:
```python
chapter_name = self._resolve_division_id(division_id)
```

With:
```python
chapter_name = get_mapping_service().resolve_division_id(division_id)
```

And at the comprehension form (line ~1983):
```python
ch = self._resolve_division_id(div_id)
```

Becomes:
```python
ch = get_mapping_service().resolve_division_id(div_id)
```

- [ ] **Step 4: Replace the single call site of `_extract_email`**

At line ~2134, replace:
```python
contact_email=self._extract_email(division_data.get("email_id")),
```

With:
```python
contact_email=extract_email(division_data.get("email_id")),
```

- [ ] **Step 5: Delete the three extracted helper methods from the god-class**

In `event_application_service.py`, delete:
- `def _resolve_division_id(self, division_id: int) -> Optional[str]:` (~lines 2147-2167)
- `def _map_mijnrood_to_member_fields(self, mijnrood_data: dict) -> dict:` (~lines 2169-2225)
- `def _extract_email(value: Any) -> Optional[str]:` static method (~lines 2227-2240)

Also remove now-unused imports if any:
- `MIJNROOD_TO_MEMBER_FIELD_MAP` from the `field_mapping` import block — verify no remaining references first via:

```bash
grep -n "MIJNROOD_TO_MEMBER_FIELD_MAP" verenigingen/mijnrood_sync/services/event_application_service.py
```

If only the import line remains, drop it from the import.

- [ ] **Step 6: Verify the file parses**

Run:
```bash
cd ~/frappe-bench && env/bin/python -c "import ast; ast.parse(open('apps/verenigingen/verenigingen/mijnrood_sync/services/event_application_service.py').read()); print('OK')"
```
Expected: `OK`.

---

## Task 9: Verify all tests still pass

The existing mocked test suite in `tests/services/test_event_application_service.py` patches `frappe` wholesale. The internal call-site changes (still routed through `MijnRoodEventApplicationService`) should not break those tests — but verify before committing.

- [ ] **Step 1: Run the new mapping service tests**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_mapping_service
```
Expected: 16 tests pass.

- [ ] **Step 2: Run the existing mocked event_application_service tests**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.test_event_application_service
```
Expected: All 150 existing tests pass. (If any fail because they directly tested the deleted helpers — e.g. mocked `service._map_mijnrood_to_member_fields` — update those specific tests to mock `get_mapping_service` instead. Likely 0-3 such cases.)

- [ ] **Step 3: If any existing tests failed in step 2 — fix them**

For each failed test:
1. Read the failing assertion.
2. If it directly references `service._map_mijnrood_to_member_fields`, `service._resolve_division_id`, or `service._extract_email`: replace the mock target with the corresponding new function:
   - `service._map_mijnrood_to_member_fields` → `verenigingen.mijnrood_sync.services.event_application.mapping_service.MijnRoodMappingService.map_member_fields`
   - similarly for the other two
3. Re-run step 2 until clean.

- [ ] **Step 4: Run the broader sync test surface to catch indirect callers**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.mijnrood_sync
```
Expected: All MijnRood Sync tests pass.

---

## Task 10: Commit the wiring + final polish

- [ ] **Step 1: Confirm no stragglers**

Run:
```bash
grep -n "_map_mijnrood_to_member_fields\|_resolve_division_id\|self._extract_email" \
  verenigingen/mijnrood_sync/services/event_application_service.py
```
Expected: 0 matches. (One match is acceptable if it's in a comment — verify visually.)

- [ ] **Step 2: Run pre-commit checks locally**

Run:
```bash
cd ~/frappe-bench/apps/verenigingen && pre-commit run --files \
  verenigingen/mijnrood_sync/services/event_application_service.py \
  verenigingen/mijnrood_sync/services/event_application/__init__.py \
  verenigingen/mijnrood_sync/services/event_application/mapping_service.py \
  verenigingen/tests/services/event_application/__init__.py \
  verenigingen/tests/services/event_application/test_mapping_service.py
```
Expected: All hooks pass.

- [ ] **Step 3: Commit the wiring**

```bash
git add verenigingen/mijnrood_sync/services/event_application_service.py
git commit -m "$(cat <<'EOF'
refactor(mijnrood-sync): delegate mapping concerns to MijnRoodMappingService

Replaces 11 internal call sites of the deleted helpers
(_map_mijnrood_to_member_fields, _resolve_division_id, _extract_email)
with calls to the new MijnRoodMappingService and module-level
extract_email helper. The god-class shrinks by ~80 LOC.

This is Phase 1, PR #1 of the Tier C decomposition documented at
docs/plans/2026-05-12-event-application-service-refactor-design.md.
EOF
)"
```

- [ ] **Step 4: Push**

```bash
SKIP=jest-testing,javascript-doctype-validator git push
```

---

## Subsequent PRs (high-level outline; each will get its own detail-plan)

| # | PR scope | Extracted from god-class | Approx LOC |
|---|---|---|---|
| 2 | `member_sync_service.py` | `_apply_new_member`, `_apply_changed_member`, `_find_existing_member_or_conflict`, `_apply_deleted_member` | ~400 |
| 3 | `application_sync_service.py` | `_apply_new_membership_application`, `_promote_application_member`, `_apply_approved`, `_try_promote_application` | ~350 |
| 4 | `volunteer_sync_service.py` | `_process_member_roles`, `_handle_admin_role_change`, `_handle_division_contact_change`, `_apply_role_actions`, `_ensure_user_role`, `_parse_mijnrood_roles`, `_prune_orphan_team_members` | ~500 |
| 5 | `termination_sync_service.py` | `_check_and_handle_termination`, status-transition routing | ~250 |
| 6 | `related_records_orchestrator.py` | `_create_related_records`, address / Mollie / membership / dues coordination | ~300 |
| 7 | `dispatcher.py` | What remains: `apply_event`, `_apply_new/_changed/_deleted/_approved`, `_TABLE_HANDLERS`, error→`event.error_message`. Original `event_application_service.py` becomes ≤20-LOC re-export shim. | ~300 |
| 8 (Phase 2) | Delete `tests/services/test_event_application_service.py` (3,107 LOC of mocks) | — | -3,107 |
| 9 (Phase 3) | Unify result idioms on `OperationResult` | — | ~150 (adapter shims at boundaries) |

Each PR follows the same pattern as this one: TDD with real-DB tests, replace call sites, delete extracted code, verify, commit, push.

---

## Success Criteria (this PR)

1. `verenigingen/mijnrood_sync/services/event_application/mapping_service.py` exists with `MijnRoodMappingService`, `extract_email`, and `get_mapping_service`.
2. `event_application_service.py` no longer defines `_map_mijnrood_to_member_fields`, `_resolve_division_id`, or `_extract_email`, and contains no references to those names.
3. All 16 new mapping-service tests pass against a real DB via `EnhancedTestCase` (no `MagicMock(frappe)`). Pure mapping logic doesn't exercise permissions, so the test user role isn't load-bearing here; later PRs that touch permission-sensitive code will need non-Admin contexts per the project's `tests_run_as_admin` feedback note.
4. All 150 existing mocked tests in `test_event_application_service.py` continue to pass (or are minimally edited to retarget mocks).
5. `bench run-tests --module verenigingen.mijnrood_sync` passes end-to-end.
6. Pre-commit hooks pass on every touched file.
