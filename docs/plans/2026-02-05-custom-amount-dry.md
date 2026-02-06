# Custom Amount DRY Extraction Plan — COMPLETED

> **Status:** COMPLETED (2026-02-06). All 5 tasks executed. Commits: `07b9e7fb`, `79e38750`, `f3a5bc1b`, `136fa13c`, `3dd341a0`.

**Goal:** Extract ~120 LOC of duplicated logic from `create_member_from_application()` and `update_member_from_reapplication()` into 3 shared helpers.

**Architecture:** Three private helper functions (`_sanitize_application_names`, `_apply_custom_contribution_fee`, `_append_chapter_notes`) extracted into the same file (`application_helpers.py`), placed directly above the two consumer functions. Both functions then call the helpers instead of duplicating logic.

**Tech Stack:** Python, Frappe Framework, FrappeTestCase

**Audit Item:** 3.2 from `docs/audits/membership-application-audit-2026-02-05.md`

---

### Task 1: Write characterization tests for `update_member_from_reapplication()`

Currently has ZERO direct tests. Need a safety net before refactoring.

**Files:**
- Create: `vereinigingen/tests/backend/unit/utils/test_application_helpers_reapplication.py`
- Reference: `vereinigingen/utils/application_helpers.py:685-824`

**Step 1: Write characterization tests**

Create test file at `vereinigingen/tests/backend/unit/utils/test_application_helpers_reapplication.py`:

```python
# -*- coding: utf-8 -*-
"""
Characterization tests for update_member_from_reapplication().

These capture current behavior as a safety net for refactoring.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, now_datetime

from verenigingen.utils.application_helpers import (
    create_member_from_application,
    update_member_from_reapplication,
)


def _create_test_member(data=None, application_id=None):
    """Helper: create a member via the real function for test setup."""
    if data is None:
        data = {
            "first_name": "Original",
            "last_name": "Member",
            "email": f"test-reapp-{frappe.generate_hash(length=8)}@example.com",
            "birth_date": "1990-01-01",
            "selected_membership_type": frappe.get_all("Membership Type", limit=1)[0]["name"],
        }
    if application_id is None:
        application_id = f"APP-TEST-{frappe.generate_hash(length=8)}"
    return create_member_from_application(data, application_id)


class TestUpdateMemberFromReapplication(FrappeTestCase):
    """Characterize update_member_from_reapplication() behavior."""

    def setUp(self):
        self.member = _create_test_member()
        self.member_name = self.member.name

    def test_basic_field_update(self):
        """Core fields are updated from reapplication data."""
        data = {
            "first_name": "Updated",
            "last_name": "Name",
            "email": "updated@example.com",
            "birth_date": "1985-06-15",
            "contact_number": "+31612345678",
            "pronouns": "they/them",
        }
        app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
        result = update_member_from_reapplication(self.member_name, data, app_id)

        self.assertEqual(result.first_name, "Updated")
        self.assertEqual(result.last_name, "Name")
        self.assertEqual(result.status, "Pending")
        self.assertEqual(result.application_id, app_id)

    def test_name_sanitization(self):
        """Names with leading/trailing spaces are sanitized."""
        data = {"first_name": "  Jan  ", "last_name": "  de Vries  "}
        app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
        result = update_member_from_reapplication(self.member_name, data, app_id)

        self.assertEqual(result.first_name, "Jan")
        self.assertEqual(result.last_name, "de Vries")

    def test_custom_contribution_fee_applied(self):
        """Custom amount sets fee override fields."""
        mt = frappe.get_all("Membership Type", limit=1)
        if not mt:
            self.skipTest("No Membership Type exists")

        data = {
            "first_name": "Fee",
            "last_name": "Test",
            "custom_contribution_fee": "25.50",
            "uses_custom_amount": True,
            "selected_membership_type": mt[0]["name"],
        }
        app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
        result = update_member_from_reapplication(self.member_name, data, app_id)

        self.assertEqual(result.dues_rate, 25.50)
        self.assertIn("reapplication", result.fee_override_reason)
        self.assertEqual(result.fee_override_date, today())
        self.assertEqual(result.application_custom_fee, 25.50)

    def test_chapter_info_in_notes(self):
        """Selected chapter is appended to notes."""
        chapters = frappe.get_all("Chapter", limit=1)
        if not chapters:
            self.skipTest("No Chapter exists")

        data = {
            "first_name": "Chapter",
            "last_name": "Test",
            "selected_chapter": chapters[0]["name"],
        }
        app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
        result = update_member_from_reapplication(self.member_name, data, app_id)

        self.assertIn("Selected Chapter (Reapplication)", result.notes)

    def test_reapplication_timestamp_in_notes(self):
        """Reapplication timestamp note is always added."""
        data = {"first_name": "Time", "last_name": "Test"}
        app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
        result = update_member_from_reapplication(self.member_name, data, app_id)

        self.assertIn("Reapplication submitted:", result.notes)

    def test_zero_custom_amount_not_applied(self):
        """Custom fee of 0 does not set override fields."""
        data = {
            "first_name": "Zero",
            "last_name": "Fee",
            "custom_contribution_fee": "0",
            "uses_custom_amount": True,
        }
        app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
        result = update_member_from_reapplication(self.member_name, data, app_id)

        # dues_rate should not be set to 0 (it stays at whatever default was)
        self.assertFalse(result.fee_override_reason)

    def test_volunteer_skills_transferred(self):
        """Volunteer skills from data are set on member."""
        data = {
            "first_name": "Vol",
            "last_name": "Test",
            "volunteer_skills": ["cooking", "driving"],
        }
        app_id = f"APP-REAPP-{frappe.generate_hash(length=8)}"
        result = update_member_from_reapplication(self.member_name, data, app_id)

        self.assertEqual(result.volunteer_skills, ["cooking", "driving"])
```

**Step 2: Run tests to verify they pass**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.unit.utils.test_application_helpers_reapplication`

Expected: All 7 tests PASS (characterizing current behavior)

**Step 3: Commit**

```bash
git add vereinigingen/tests/backend/unit/utils/test_application_helpers_reapplication.py
git commit -m "test: add characterization tests for update_member_from_reapplication"
```

---

### Task 2: Extract `_sanitize_application_names()` helper

**Files:**
- Modify: `vereinigingen/utils/application_helpers.py`

**Step 1: Add the helper function**

Insert before `create_member_from_application()` (before line 484):

```python
def _sanitize_application_names(data):
    """
    Validate and sanitize name fields from application data.

    Returns tuple: (first_name, middle_name, tussenvoegsel, last_name)
    """
    from verenigingen.utils.validation.application_validators import validate_name

    names = {}
    for field, label in [
        ("first_name", "First Name"),
        ("middle_name", "Middle Name"),
        ("tussenvoegsel", "Tussenvoegsel"),
        ("last_name", "Last Name"),
    ]:
        value = data.get(field, "")
        if value:
            validation_result = validate_name(value, label)
            if validation_result.get("valid") and validation_result.get("sanitized"):
                value = validation_result["sanitized"]
        names[field] = value

    return names["first_name"], names["middle_name"], names["tussenvoegsel"], names["last_name"]
```

**Step 2: Replace duplicate blocks in both functions**

In `create_member_from_application()`, replace lines 487-515 (the import + sanitization block) with:

```python
    from verenigingen.utils.secure_operations import get_system_user_for_operation

    # Sanitize names before creating member record
    first_name, middle_name, tussenvoegsel, last_name = _sanitize_application_names(data)
```

In `update_member_from_reapplication()`, replace lines 694-725 (the import + sanitization block) with:

```python
    from vereinigingen.utils.secure_operations import get_system_user_for_operation, secure_user_context

    # Sanitize names before updating
    first_name, middle_name, tussenvoegsel, last_name = _sanitize_application_names(data)
```

Note: Keep the `validate_name` import in the helper, remove it from both calling functions.

**Step 3: Run characterization tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.unit.utils.test_application_helpers_reapplication`

Expected: All 7 tests still PASS

**Step 4: Commit**

```bash
git add vereinigingen/utils/application_helpers.py
git commit -m "refactor: extract _sanitize_application_names helper to DRY name validation"
```

---

### Task 3: Extract `_apply_custom_contribution_fee()` helper

**Files:**
- Modify: `vereinigingen/utils/application_helpers.py`

**Step 1: Add the helper function**

Insert after `_sanitize_application_names()`:

```python
def _apply_custom_contribution_fee(member, data, context_label="application"):
    """
    Apply custom contribution fee override fields to a member.

    Args:
        member: Member document (modified in place)
        data: Application data dict with custom_contribution_fee, uses_custom_amount, custom_amount_reason
        context_label: Used in fee_override_reason (e.g. "application" or "reapplication")
    """
    if not (data.get("custom_contribution_fee") or data.get("uses_custom_amount")):
        return

    try:
        # Safely convert custom_contribution_fee to float
        custom_contribution_fee = 0
        if data.get("custom_contribution_fee"):
            try:
                custom_contribution_fee = float(data.get("custom_contribution_fee"))
            except (ValueError, TypeError) as e:
                frappe.logger().error(
                    f"Error converting custom_contribution_fee '{data.get('custom_contribution_fee')}' to float: {str(e)}"
                )
                custom_contribution_fee = 0

        if custom_contribution_fee > 0:
            member.dues_rate = custom_contribution_fee
            member.fee_override_reason = (
                f"Custom amount selected during {context_label}: "
                f"{data.get('custom_amount_reason', 'Member-specified contribution level')}"
            )
            member.fee_override_date = today()
            member.application_custom_fee = custom_contribution_fee

            # Resolve fee_override_by user with safe fallback
            override_user = None
            if frappe.session.user and frappe.session.user != "Guest":
                if frappe.db.exists("User", frappe.session.user):
                    override_user = frappe.session.user
            if not override_user and frappe.db.exists("User", "Administrator"):
                override_user = "Administrator"
            if not override_user:
                first_user = frappe.db.get_value("User", {"enabled": 1}, "name")
                if first_user:
                    override_user = first_user

            if override_user:
                member.fee_override_by = override_user
            else:
                frappe.log_error(
                    "No valid user found for fee_override_by field - custom amount preserved without approver",
                    "Fee Override User Warning",
                )

    except Exception as e:
        frappe.log_error(
            f"Error storing custom amount data: {str(e)}",
            "Custom Amount Storage Error",
        )
```

**Behavior notes:**
- `create_member_from_application()` had 3-tier user fallback (session -> Administrator -> any enabled user)
- `update_member_from_reapplication()` had only 2-tier (session -> Administrator)
- The helper uses the 3-tier fallback for both -- this is a behavior improvement (not a regression)
- The `context_label` parameter preserves different `fee_override_reason` wording
- Debug `frappe.logger().info()` calls from create path are removed (debug-only, not needed)

**Step 2: Replace duplicate blocks in both functions**

In `create_member_from_application()`, replace the entire custom amount block (lines 559-621) with:

```python
    # Handle custom membership amount using fee override fields
    _apply_custom_contribution_fee(member, data, context_label="application")
```

In `update_member_from_reapplication()`, replace the custom amount block with:

```python
    # Handle custom membership amount
    _apply_custom_contribution_fee(member, data, context_label="reapplication")
```

**Step 3: Run characterization tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.unit.utils.test_application_helpers_reapplication`

Expected: All 7 tests still PASS

Note: The `test_custom_contribution_fee_applied` test asserts `"reapplication" in result.fee_override_reason`. The new helper produces "Custom amount selected during reapplication: ..." which still contains "reapplication". Verify this.

**Step 4: Commit**

```bash
git add vereinigingen/utils/application_helpers.py
git commit -m "refactor: extract _apply_custom_contribution_fee helper to DRY fee override logic"
```

---

### Task 4: Extract `_append_chapter_notes()` helper

**Files:**
- Modify: `vereinigingen/utils/application_helpers.py`

**Step 1: Add the helper function**

Insert after `_apply_custom_contribution_fee()`:

```python
def _append_chapter_notes(member, selected_chapter, label="Selected Chapter"):
    """
    Append chapter display info to member notes.

    Args:
        member: Member document (modified in place)
        selected_chapter: Chapter name/ID from application data
        label: Prefix label (e.g. "Selected Chapter" or "Selected Chapter (Reapplication)")
    """
    if not selected_chapter:
        return

    try:
        try:
            chapter_doc = frappe.get_doc("Chapter", selected_chapter)
            chapter_display = f"{chapter_doc.region} ({selected_chapter})"
        except Exception:
            chapter_display = selected_chapter

        existing_notes = member.notes or ""
        if existing_notes:
            existing_notes += "\n\n"
        member.notes = existing_notes + f"{label}: {chapter_display}"
    except Exception as e:
        frappe.log_error(
            f"Error storing chapter information: {str(e)}",
            "Chapter Info Storage Error",
        )
```

**Step 2: Replace duplicate blocks in both functions**

In `create_member_from_application()`, replace the chapter notes block with:

```python
    # Add chapter information to notes for approver visibility
    _append_chapter_notes(member, data.get("selected_chapter"), label="Selected Chapter")
```

In `update_member_from_reapplication()`, replace the chapter notes block with:

```python
    # Add chapter information to notes for approver visibility
    _append_chapter_notes(member, data.get("selected_chapter"), label="Selected Chapter (Reapplication)")
```

**Step 3: Run characterization tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.unit.utils.test_application_helpers_reapplication`

Expected: All 7 tests still PASS

**Step 4: Commit**

```bash
git add vereinigingen/utils/application_helpers.py
git commit -m "refactor: extract _append_chapter_notes helper to DRY chapter note logic"
```

---

### Task 5: Final verification and audit update

**Step 1: Run the characterization tests**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.unit.utils.test_application_helpers_reapplication
```

Expected: All 7 PASS

**Step 2: Run existing fee logic tests**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app vereinigingen --module vereinigingen.tests.backend.components.test_fee_logic
```

Expected: All PASS

**Step 3: Smoke-test helpers via bench console**

```python
import frappe
from vereinigingen.utils.application_helpers import (
    _sanitize_application_names,
    _apply_custom_contribution_fee,
    _append_chapter_notes,
)

# Test name sanitization
names = _sanitize_application_names({"first_name": "  Jan  ", "last_name": "Bakker"})
assert names == ("Jan", "", "", "Bakker"), f"Got {names}"

print("All smoke tests passed")
```

**Step 4: Run ruff linter**

```bash
cd ~/frappe-bench/apps/verenigingen && ruff check verenigingen/utils/application_helpers.py
```

Expected: No errors

**Step 5: Update audit doc**

In `docs/audits/membership-application-audit-2026-02-05.md`, mark section 3.2 as **RESOLVED**.

**Step 6: Commit**

```bash
git add docs/audits/membership-application-audit-2026-02-05.md
git commit -m "docs: mark custom amount DRY extraction as resolved in audit"
```

---

## Behavior Changes

| Change | Impact | Risk |
|--------|--------|------|
| `update_member_from_reapplication()` gains 3-tier user fallback (was 2-tier) | If Administrator doesn't exist, falls back to any enabled user | Very low - improvement |
| Debug `frappe.logger().info()` calls removed from create path | Less noise in logs | None |
| Error messages unified between create/update | Consistent logging | None |
| Trailing `\n` on chapter note in reapplication removed | Cosmetic whitespace difference in notes field | Negligible |
