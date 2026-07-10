# Data Retention Engine Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate the orphaned `DataRetentionPolicy` engine as a weekly, gated, dry-run-by-default scheduled job, configurable via a new `Data Retention Settings` page, with live purging allow-listed to one verified category.

**Architecture:** A new `DataRetentionPolicy.LIVE_CAPABLE_CATEGORIES` allowlist plus a layered `effective_dry_run` gate make live execution reachable only for verified categories. Two new DocTypes (`Data Retention Settings` Single + `Data Retention Category Policy` child) feed the engine's `_load_custom_policies()`. A new module-level `run_scheduled_retention_policies()` entrypoint is registered in the weekly scheduler bucket, and Verenigingen Settings gains a button linking to the settings page.

**Tech Stack:** Frappe/ERPNext (Python controllers, DocType JSON, `scheduler_events` hooks, client-script JS), `VereningingenTestCase` test factory.

## Global Constraints

- Branch `feat/data-retention-engine-activation`, base `develop`. Repo convention: **merge commits** (not squash); GitHub blocks force-push to `develop`.
- **Test sites: `test_site_2`** (site_1 has a Payment-Session-Log fixture baseline crash). Run: `bench --site test_site_2 run-tests --app verenigingen --module <dotted.module>`.
- **DocType / scheduler / JS changes require** `bench --site test_site_2 clear-cache` (and `bench --site test_site_2 migrate` for new DocTypes) before tests/manual checks see them.
- All tests: `VereningingenTestCase` (`from verenigingen.tests.utils.base import VereningingenTestCase`), real docs, **no mocking of frappe primitives**. Each behavioral assertion must be mutation-verified.
- Pre-push hooks ≈ 2 min; run `black`, `ruff check`, and (for test files) `python scripts/validation/test_quality_enforcer.py <files>` before committing. `SKIP=whitelist-type-safety` if it has pre-existing failures.
- Engine module path: `verenigingen/verenigingen_payments/core/compliance/data_retention_policy.py`. Import as `from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import DataRetentionPolicy, DataCategory, RetentionAction, LIVE_CAPABLE_CATEGORIES, run_scheduled_retention_policies`.
- `DataCategory` values (category strings) and code defaults (period days / action):
  `payment_data` 2555/anonymize · `mandate_data` 2555/anonymize · `personal_data` 1095/delete · `transaction_data` 2555/archive · `audit_logs` 2555/archive · `security_events` 365/delete · `financial_records` 2555/archive · `consent_records` 1095/archive · `temporary_data` 30/delete.
- **`LIVE_CAPABLE_CATEGORIES = {DataCategory.TEMPORARY_DATA}`** — the ONLY live-capable category this project ships. Do not add others.

---

### Task 1: Engine — live-capable allowlist, guarded custom-policy load, layered dry-run gate

**Files:**
- Modify: `verenigingen/verenigingen_payments/core/compliance/data_retention_policy.py`
- Test: `verenigingen/verenigingen_payments/tests/test_data_retention_engine_gate.py` (create)

**Interfaces:**
- Produces: module constant `LIVE_CAPABLE_CATEGORIES: set[DataCategory]`; `DataRetentionPolicy.category_live_flags: Dict[DataCategory, bool]` (instance attr, defaults `{}`); modified `_load_custom_policies()` (reads `Data Retention Settings` when it exists, else no-op); modified `_process_category()` using `effective_dry_run`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

Create `verenigingen/verenigingen_payments/tests/test_data_retention_engine_gate.py`:

```python
"""Engine-level live-execution gate + guarded custom-policy load.

The layered gate makes live purging reachable ONLY when the global dry_run flag
is off AND the category's live flag is on AND the category is in the code-level
LIVE_CAPABLE_CATEGORIES allowlist. Every assertion is mutation-sensitive.
"""

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    DataCategory,
    DataRetentionPolicy,
    LIVE_CAPABLE_CATEGORIES,
)


class TestDataRetentionEngineGate(VereningingenTestCase):
    def test_only_temporary_data_is_live_capable(self):
        self.assertEqual(LIVE_CAPABLE_CATEGORIES, {DataCategory.TEMPORARY_DATA})

    def test_load_custom_policies_is_noop_without_rows(self):
        # With no configured settings rows, code defaults survive and no live flags set.
        policy = DataRetentionPolicy()
        self.assertEqual(policy.retention_periods[DataCategory.PAYMENT_DATA], 2555)
        self.assertEqual(policy.category_live_flags, {})

    def test_effective_dry_run_gate_blocks_non_capable_even_when_flagged(self):
        # personal_data is NOT live-capable; even fully "live" it must stay dry-run.
        policy = DataRetentionPolicy()
        policy.category_live_flags = {DataCategory.PERSONAL_DATA: True}
        result = policy._process_category(DataCategory.PERSONAL_DATA, dry_run=False)
        # dry-run means it only counts; no member is deleted. Assert via effective flag.
        self.assertTrue(
            policy._effective_dry_run(DataCategory.PERSONAL_DATA, dry_run=False)
        )

    def test_effective_dry_run_gate_allows_capable_when_flagged(self):
        policy = DataRetentionPolicy()
        policy.category_live_flags = {DataCategory.TEMPORARY_DATA: True}
        self.assertFalse(
            policy._effective_dry_run(DataCategory.TEMPORARY_DATA, dry_run=False)
        )

    def test_global_dry_run_always_wins(self):
        policy = DataRetentionPolicy()
        policy.category_live_flags = {DataCategory.TEMPORARY_DATA: True}
        self.assertTrue(
            policy._effective_dry_run(DataCategory.TEMPORARY_DATA, dry_run=True)
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_2 run-tests --app verenigingen --module verenigingen.verenigingen_payments.tests.test_data_retention_engine_gate`
Expected: FAIL — `ImportError` on `LIVE_CAPABLE_CATEGORIES` / `AttributeError` on `_effective_dry_run` / `category_live_flags`.

- [ ] **Step 3: Write minimal implementation**

In `data_retention_policy.py`, after the `RetentionAction` enum (before `class DataRetentionPolicy`), add:

```python
# Categories whose LIVE (destructive) processing path has been individually
# verified safe and is allowed to run. Everything else is forced to dry-run
# regardless of settings. Kept intentionally minimal:
#   - temporary_data: a clean DELETE of aged webhook_validation Mollie Audit Log
#     rows; verified + integration-tested.
# Excluded (see backlog): audit_logs (archive writes a non-existent field),
# payment_data (anonymizes a submitted Payment Entry -> GL desync risk),
# personal_data (Member delete) — all unverified/known-broken.
LIVE_CAPABLE_CATEGORIES = {DataCategory.TEMPORARY_DATA}
```

In `__init__`, add `self.category_live_flags` BEFORE the `_load_custom_policies()` call:

```python
    def __init__(self):
        """Initialize data retention policy manager"""
        self.retention_periods = self.DEFAULT_RETENTION_PERIODS.copy()
        self.retention_actions = self.DEFAULT_RETENTION_ACTIONS.copy()
        self.category_live_flags: Dict[DataCategory, bool] = {}
        self.legal_holds = {}
        self._load_custom_policies()
```

Replace `_load_custom_policies()` body:

```python
    def _load_custom_policies(self):
        """Load custom retention policies from the Data Retention Settings singleton.

        Robust to pre-migrate / absent DocType / empty table / unknown category
        strings — any of which leaves the code defaults in place.
        """
        # A Single DocType has no table of its own (stored in tabSingles), so
        # check for the DocType's METADATA, not a table.
        if not frappe.db.exists("DocType", "Data Retention Settings"):
            return
        try:
            settings = frappe.get_single("Data Retention Settings")
            rows = settings.get("category_policies") or []
        except Exception:
            # Child table tabData Retention Category Policy may not exist yet
            # (pre-migrate) -> keep code defaults.
            return

        by_value = {c.value: c for c in DataCategory}
        for row in rows:
            category = by_value.get(row.category)
            if category is None:
                frappe.logger("retention").warning(
                    f"Unknown retention category '{row.category}' in settings; skipping"
                )
                continue
            if row.retention_days:
                self.retention_periods[category] = int(row.retention_days)
            if row.action:
                try:
                    self.retention_actions[category] = RetentionAction(row.action)
                except ValueError:
                    frappe.logger("retention").warning(
                        f"Unknown retention action '{row.action}' for {row.category}; skipping"
                    )
            self.category_live_flags[category] = bool(row.live_enabled)
```

Add the `_effective_dry_run` helper (place directly above `_process_category`):

```python
    def _effective_dry_run(self, category: "DataCategory", dry_run: bool) -> bool:
        """Layered live-execution gate.

        A category runs LIVE only when the global dry_run is off AND the
        category is flagged live in settings AND it is in the code-level
        LIVE_CAPABLE_CATEGORIES allowlist. Monotonic: can only ever be MORE
        conservative than the raw dry_run.
        """
        is_live = (
            not dry_run
            and self.category_live_flags.get(category, False)
            and category in LIVE_CAPABLE_CATEGORIES
        )
        return not is_live
```

In `_process_category`, replace the four `_process_*` calls' `dry_run` argument with an `effective_dry_run` computed once. Change the top of the method:

```python
        retention_days = self.retention_periods[category]
        retention_action = self.retention_actions[category]
        cutoff_date = add_days(now_datetime(), -retention_days)
        effective_dry_run = self._effective_dry_run(category, dry_run)
```

and change each of the four branches to pass `effective_dry_run` instead of `dry_run`, e.g.:

```python
        if category == DataCategory.PAYMENT_DATA:
            result["records_affected"] = self._process_payment_data(cutoff_date, retention_action, effective_dry_run)

        elif category == DataCategory.PERSONAL_DATA:
            result["records_affected"] = self._process_personal_data(cutoff_date, retention_action, effective_dry_run)

        elif category == DataCategory.AUDIT_LOGS:
            result["records_affected"] = self._process_audit_logs(cutoff_date, retention_action, effective_dry_run)

        elif category == DataCategory.TEMPORARY_DATA:
            result["records_affected"] = self._process_temporary_data(cutoff_date, retention_action, effective_dry_run)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bench --site test_site_2 run-tests --app verenigingen --module verenigingen.verenigingen_payments.tests.test_data_retention_engine_gate`
Expected: PASS (5 tests).

- [ ] **Step 5: Mutation-verify**

Temporarily change `LIVE_CAPABLE_CATEGORIES` to `set()` → `test_effective_dry_run_gate_allows_capable_when_flagged` must FAIL. Revert. Temporarily drop `and category in LIVE_CAPABLE_CATEGORIES` from `_effective_dry_run` → `test_effective_dry_run_gate_blocks_non_capable_even_when_flagged` must FAIL. Revert. Re-run: all pass.

- [ ] **Step 6: Commit**

```bash
git add verenigingen/verenigingen_payments/core/compliance/data_retention_policy.py \
        verenigingen/verenigingen_payments/tests/test_data_retention_engine_gate.py
git commit -m "feat(compliance): layered live-execution gate + guarded custom-policy load"
```

---

### Task 2: `Data Retention Category Policy` child DocType

**Files:**
- Create: `verenigingen/verenigingen/doctype/data_retention_category_policy/data_retention_category_policy.json`
- Create: `verenigingen/verenigingen/doctype/data_retention_category_policy/data_retention_category_policy.py`
- Create: `verenigingen/verenigingen/doctype/data_retention_category_policy/__init__.py` (empty)
- Test: `verenigingen/verenigingen/doctype/data_retention_settings/test_category_enum_sync.py` (create in Task 3's folder is fine; here create under the child folder) → use `verenigingen/verenigingen/doctype/data_retention_category_policy/test_data_retention_category_policy.py`

**Interfaces:**
- Produces: child DocType `Data Retention Category Policy` with fields `category` (Select), `retention_days` (Int), `action` (Select), `live_enabled` (Check).

- [ ] **Step 1: Write the failing test (enum/Select drift guard)**

Create `verenigingen/verenigingen/doctype/data_retention_category_policy/test_data_retention_category_policy.py`:

```python
import json
import os
import unittest

from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    DataCategory,
    RetentionAction,
)


class TestCategoryPolicyEnumSync(unittest.TestCase):
    def _load_json(self):
        here = os.path.dirname(__file__)
        with open(os.path.join(here, "data_retention_category_policy.json")) as f:
            return json.load(f)

    def _options(self, doc, fieldname):
        field = next(f for f in doc["fields"] if f["fieldname"] == fieldname)
        return set(o for o in field["options"].split("\n") if o)

    def test_category_options_match_enum(self):
        doc = self._load_json()
        self.assertEqual(self._options(doc, "category"), {c.value for c in DataCategory})

    def test_action_options_match_enum(self):
        doc = self._load_json()
        self.assertEqual(self._options(doc, "action"), {a.value for a in RetentionAction})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_2 run-tests --app verenigingen --module verenigingen.verenigingen.doctype.data_retention_category_policy.test_data_retention_category_policy`
Expected: FAIL — JSON file not found.

- [ ] **Step 3: Create the DocType files**

`__init__.py`: empty file.

`data_retention_category_policy.json`:

```json
{
  "actions": [],
  "creation": "2026-07-10 00:00:00.000000",
  "doctype": "DocType",
  "editable_grid": 1,
  "engine": "InnoDB",
  "field_order": [
    "category",
    "retention_days",
    "action",
    "live_enabled"
  ],
  "fields": [
    {
      "fieldname": "category",
      "fieldtype": "Select",
      "in_list_view": 1,
      "label": "Category",
      "options": "payment_data\nmandate_data\npersonal_data\ntransaction_data\naudit_logs\nsecurity_events\nfinancial_records\nconsent_records\ntemporary_data",
      "reqd": 1
    },
    {
      "fieldname": "retention_days",
      "fieldtype": "Int",
      "in_list_view": 1,
      "label": "Retention Days",
      "reqd": 1
    },
    {
      "fieldname": "action",
      "fieldtype": "Select",
      "in_list_view": 1,
      "label": "Action",
      "options": "delete\nanonymize\narchive\nreview",
      "reqd": 1
    },
    {
      "default": "0",
      "fieldname": "live_enabled",
      "fieldtype": "Check",
      "in_list_view": 1,
      "label": "Live Enabled"
    }
  ],
  "index_web_pages_for_search": 0,
  "istable": 1,
  "links": [],
  "modified": "2026-07-10 00:00:00.000000",
  "modified_by": "Administrator",
  "module": "Verenigingen",
  "name": "Data Retention Category Policy",
  "owner": "Administrator",
  "permissions": [],
  "sort_field": "modified",
  "sort_order": "DESC",
  "states": []
}
```

`data_retention_category_policy.py`:

```python
from frappe.model.document import Document


class DataRetentionCategoryPolicy(Document):
    pass
```

- [ ] **Step 4: Migrate + run test to verify it passes**

Run: `bench --site test_site_2 migrate && bench --site test_site_2 run-tests --app verenigingen --module verenigingen.verenigingen.doctype.data_retention_category_policy.test_data_retention_category_policy`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/data_retention_category_policy/
git commit -m "feat(compliance): add Data Retention Category Policy child DocType"
```

---

### Task 3: `Data Retention Settings` Single DocType + controller (guards, seed helper, reset)

**Files:**
- Create: `verenigingen/verenigingen/doctype/data_retention_settings/data_retention_settings.json`
- Create: `verenigingen/verenigingen/doctype/data_retention_settings/data_retention_settings.py`
- Create: `verenigingen/verenigingen/doctype/data_retention_settings/__init__.py` (empty)
- Test: `verenigingen/verenigingen/doctype/data_retention_settings/test_data_retention_settings.py` (create)

**Interfaces:**
- Consumes: Task 1's `LIVE_CAPABLE_CATEGORIES`, `DataCategory`, engine `DEFAULT_RETENTION_PERIODS`/`DEFAULT_RETENTION_ACTIONS`; Task 2's child DocType.
- Produces: Single `Data Retention Settings` with `enabled` (Check), `dry_run_only` (Check), `category_policies` (Table), `last_run` (Datetime, read-only), `last_run_summary` (Small Text, read-only). Controller methods: `default_category_rows()` (staticmethod → list of dicts), `reset_category_policies()` (whitelisted), `validate()` guards. Also proves Task 1's `_load_custom_policies` override path end-to-end.

- [ ] **Step 1: Write the failing test**

Create `verenigingen/verenigingen/doctype/data_retention_settings/test_data_retention_settings.py`:

```python
import frappe
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    DataCategory,
    DataRetentionPolicy,
)


class TestDataRetentionSettings(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.settings = frappe.get_single("Data Retention Settings")
        # Start from a known clean state for each test.
        self.settings.set("category_policies", [])
        self.settings.enabled = 0
        self.settings.dry_run_only = 1
        self.settings.flags.ignore_permissions = True
        self.settings.save()

    def _seed(self):
        self.settings.reset_category_policies()
        self.settings.reload()

    def test_reset_seeds_nine_rows_from_defaults(self):
        self._seed()
        rows = self.settings.category_policies
        self.assertEqual(len(rows), 9)
        payment = next(r for r in rows if r.category == "payment_data")
        self.assertEqual(payment.retention_days, 2555)
        self.assertEqual(payment.action, "anonymize")
        self.assertEqual(payment.live_enabled, 0)

    def test_save_does_not_reseed_after_row_removed(self):
        self._seed()
        self.settings.set("category_policies", self.settings.category_policies[:-1])
        self.settings.save()
        self.settings.reload()
        self.assertEqual(len(self.settings.category_policies), 8)

    def test_duplicate_category_rejected(self):
        self.settings.append("category_policies", {"category": "payment_data", "retention_days": 100, "action": "review"})
        self.settings.append("category_policies", {"category": "payment_data", "retention_days": 200, "action": "review"})
        with self.assertRaises(frappe.ValidationError):
            self.settings.save()

    def test_retention_days_below_minimum_rejected(self):
        self.settings.append("category_policies", {"category": "payment_data", "retention_days": 10, "action": "review"})
        with self.assertRaises(frappe.ValidationError):
            self.settings.save()

    def test_live_enabled_on_non_capable_category_rejected(self):
        self.settings.append("category_policies", {"category": "personal_data", "retention_days": 1095, "action": "delete", "live_enabled": 1})
        with self.assertRaises(frappe.ValidationError):
            self.settings.save()

    def test_live_enabled_on_capable_category_allowed(self):
        self.settings.append("category_policies", {"category": "temporary_data", "retention_days": 30, "action": "delete", "live_enabled": 1})
        self.settings.save()  # must not raise
        self.assertEqual(len(self.settings.category_policies), 1)

    def test_custom_period_flows_into_engine(self):
        self._seed()
        payment = next(r for r in self.settings.category_policies if r.category == "payment_data")
        payment.retention_days = 999
        self.settings.save()
        policy = DataRetentionPolicy()
        self.assertEqual(policy.retention_periods[DataCategory.PAYMENT_DATA], 999)
        # seeded defaults set live_enabled=0 everywhere -> flag loaded as False
        self.assertFalse(policy.category_live_flags[DataCategory.PAYMENT_DATA])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_2 run-tests --app verenigingen --module verenigingen.verenigingen.doctype.data_retention_settings.test_data_retention_settings`
Expected: FAIL — DocType `Data Retention Settings` not found.

- [ ] **Step 3: Create the Single DocType JSON**

`__init__.py`: empty.

`data_retention_settings.json`:

```json
{
  "actions": [],
  "creation": "2026-07-10 00:00:00.000000",
  "doctype": "DocType",
  "editable_grid": 1,
  "engine": "InnoDB",
  "field_order": [
    "enabled",
    "dry_run_only",
    "policies_section",
    "category_policies",
    "status_section",
    "last_run",
    "last_run_summary"
  ],
  "fields": [
    {
      "default": "0",
      "description": "Master switch. When off, the weekly retention job does nothing.",
      "fieldname": "enabled",
      "fieldtype": "Check",
      "label": "Retention Engine Enabled"
    },
    {
      "default": "1",
      "description": "Global safety gate. When on, the job only reports what WOULD be purged; nothing is deleted or anonymized.",
      "fieldname": "dry_run_only",
      "fieldtype": "Check",
      "label": "Dry-run Only"
    },
    {
      "fieldname": "policies_section",
      "fieldtype": "Section Break",
      "label": "Category Policies"
    },
    {
      "fieldname": "category_policies",
      "fieldtype": "Table",
      "label": "Category Policies",
      "options": "Data Retention Category Policy"
    },
    {
      "fieldname": "status_section",
      "fieldtype": "Section Break",
      "label": "Last Run"
    },
    {
      "fieldname": "last_run",
      "fieldtype": "Datetime",
      "label": "Last Run",
      "read_only": 1
    },
    {
      "fieldname": "last_run_summary",
      "fieldtype": "Small Text",
      "label": "Last Run Summary",
      "read_only": 1
    }
  ],
  "index_web_pages_for_search": 0,
  "issingle": 1,
  "links": [],
  "modified": "2026-07-10 00:00:00.000000",
  "modified_by": "Administrator",
  "module": "Verenigingen",
  "name": "Data Retention Settings",
  "owner": "Administrator",
  "permissions": [
    {"create": 1, "delete": 1, "email": 1, "print": 1, "read": 1, "role": "System Manager", "share": 1, "write": 1},
    {"create": 1, "delete": 1, "email": 1, "print": 1, "read": 1, "role": "Verenigingen Administrator", "share": 1, "write": 1}
  ],
  "sort_field": "modified",
  "sort_order": "DESC",
  "states": [],
  "track_changes": 1
}
```

- [ ] **Step 4: Create the controller**

`data_retention_settings.py`:

```python
import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    DataCategory,
    DataRetentionPolicy,
    LIVE_CAPABLE_CATEGORIES,
)

MIN_RETENTION_DAYS = 30


class DataRetentionSettings(Document):
    @staticmethod
    def default_category_rows():
        """Nine rows seeded from the engine's code-level defaults."""
        rows = []
        for category in DataCategory:
            rows.append(
                {
                    "category": category.value,
                    "retention_days": DataRetentionPolicy.DEFAULT_RETENTION_PERIODS[category],
                    "action": DataRetentionPolicy.DEFAULT_RETENTION_ACTIONS[category].value,
                    "live_enabled": 0,
                }
            )
        return rows

    @frappe.whitelist()
    def reset_category_policies(self):
        """Replace the table with the code defaults (button + patch use this)."""
        self.set("category_policies", [])
        for row in self.default_category_rows():
            self.append("category_policies", row)
        self.save()

    def validate(self):
        self._validate_no_duplicate_categories()
        self._validate_retention_minimums()
        self._validate_live_capability()

    def _validate_no_duplicate_categories(self):
        seen = set()
        for row in self.category_policies:
            if row.category in seen:
                frappe.throw(_("Duplicate retention category: {0}").format(row.category))
            seen.add(row.category)

    def _validate_retention_minimums(self):
        for row in self.category_policies:
            if not row.retention_days or int(row.retention_days) < MIN_RETENTION_DAYS:
                frappe.throw(
                    _("Retention Days for {0} must be at least {1}.").format(
                        row.category, MIN_RETENTION_DAYS
                    )
                )

    def _validate_live_capability(self):
        capable = {c.value for c in LIVE_CAPABLE_CATEGORIES}
        for row in self.category_policies:
            if row.live_enabled and row.category not in capable:
                frappe.throw(
                    _(
                        "Live purging is not yet available for category '{0}'. "
                        "Only {1} is live-capable; leave Live Enabled off."
                    ).format(row.category, ", ".join(sorted(capable)))
                )
```

Note: `reset_category_policies()` calls `self.save()`, which runs `validate()`. Since defaults set `live_enabled=0` and `retention_days >= 30` for all categories, the guards pass.

- [ ] **Step 5: Migrate, clear cache, run test to verify it passes**

Run: `bench --site test_site_2 migrate && bench --site test_site_2 clear-cache && bench --site test_site_2 run-tests --app verenigingen --module verenigingen.verenigingen.doctype.data_retention_settings.test_data_retention_settings`
Expected: PASS (7 tests).

- [ ] **Step 6: Mutation-verify the guards**

Comment out the `self._validate_live_capability()` call → `test_live_enabled_on_non_capable_category_rejected` FAILS. Restore. Comment out `_validate_retention_minimums` call → `test_retention_days_below_minimum_rejected` FAILS. Restore. In `_load_custom_policies` (Task 1) neutralize the `retention_periods` override line → `test_custom_period_flows_into_engine` FAILS. Restore. Re-run: all pass.

- [ ] **Step 7: Commit**

```bash
git add verenigingen/verenigingen/doctype/data_retention_settings/
git commit -m "feat(compliance): add Data Retention Settings singleton with guards + seed"
```

---

### Task 4: Seed patch + scheduler entrypoint + weekly registration

**Files:**
- Create: `verenigingen/patches/v1_0/seed_data_retention_category_policies.py`
- Modify: `patches.txt` (repo-root: `/home/frappeuser/frappe-bench/apps/verenigingen/patches.txt`)
- Modify: `verenigingen/verenigingen_payments/core/compliance/data_retention_policy.py` (add `run_scheduled_retention_policies`)
- Modify: `verenigingen/hooks/scheduler.py` (weekly bucket)
- Test: `verenigingen/verenigingen_payments/tests/test_retention_scheduler.py` (create)

**Interfaces:**
- Consumes: Task 1 engine, Task 3 settings DocType.
- Produces: module-level `run_scheduled_retention_policies() -> dict` (returns `{"skipped": True}` when disabled, else the results dict with `last_run` written).

- [ ] **Step 1: Write the failing test**

Create `verenigingen/verenigingen_payments/tests/test_retention_scheduler.py`:

```python
import frappe
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    run_scheduled_retention_policies,
)


class TestRetentionScheduler(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.settings = frappe.get_single("Data Retention Settings")
        self.settings.flags.ignore_permissions = True
        self.settings.enabled = 0
        self.settings.dry_run_only = 1
        self.settings.db_set("last_run", None)
        self.settings.save()

    def test_disabled_engine_skips_and_leaves_last_run_untouched(self):
        result = run_scheduled_retention_policies()
        self.assertTrue(result.get("skipped"))
        self.assertIsNone(frappe.db.get_single_value("Data Retention Settings", "last_run"))

    def test_enabled_dry_run_sets_last_run_and_purges_nothing(self):
        self.settings.enabled = 1
        self.settings.dry_run_only = 1
        self.settings.save()
        # A recent Member exists (created by factory helpers); assert it survives.
        member = self.create_test_member(first_name="Retention", last_name="Survivor",
                                          email="retention.survivor@test.com")
        result = run_scheduled_retention_policies()
        self.assertFalse(result.get("skipped"))
        self.assertTrue(result["dry_run"])
        self.assertTrue(frappe.db.exists("Member", member.name))
        self.assertIsNotNone(frappe.db.get_single_value("Data Retention Settings", "last_run"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_2 run-tests --app verenigingen --module verenigingen.verenigingen_payments.tests.test_retention_scheduler`
Expected: FAIL — `ImportError: cannot import name 'run_scheduled_retention_policies'`.

- [ ] **Step 3: Add the scheduler entrypoint**

At the END of `data_retention_policy.py` (module level, after the class), add:

```python
def run_scheduled_retention_policies() -> Dict[str, Any]:
    """Weekly scheduler entrypoint: gated, dry-run-by-default retention run.

    Registered in hooks/scheduler.py under "weekly". Does nothing unless
    Data Retention Settings.enabled is on. Never raises out of the scheduler
    tick — failures are logged and recorded into last_run_summary.
    """
    settings = frappe.get_single("Data Retention Settings")
    if not settings.enabled:
        return {"skipped": True}

    dry_run = bool(settings.dry_run_only)
    try:
        policy = DataRetentionPolicy()
        results = policy.apply_retention_policies(dry_run=dry_run)
        summary = _summarize_retention_results(results)
        frappe.db.set_value(
            "Data Retention Settings",
            "Data Retention Settings",
            {"last_run": now_datetime(), "last_run_summary": summary},
            update_modified=False,
        )
        # The audit-trail logger buffers in memory; flush so the compliance
        # record is actually persisted for this low-frequency job.
        try:
            from .audit_trail import get_audit_trail

            get_audit_trail()._flush_buffer()
        except Exception:
            frappe.logger("retention").warning("audit-trail flush failed", exc_info=True)
        frappe.db.commit()
        return results
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Data retention run failed")
        frappe.db.set_value(
            "Data Retention Settings",
            "Data Retention Settings",
            {"last_run": now_datetime(), "last_run_summary": f"ERROR: {e}"},
            update_modified=False,
        )
        frappe.db.commit()
        return {"skipped": False, "error": str(e)}


def _summarize_retention_results(results: Dict[str, Any]) -> str:
    """Compact per-category summary for the settings singleton."""
    lines = [f"dry_run={results.get('dry_run')} total={results.get('total_records_affected', 0)}"]
    for cat in results.get("categories_processed", []):
        lines.append(f"{cat['category']}: {cat['records_affected']} ({cat['action']})")
    if results.get("errors"):
        lines.append(f"errors: {len(results['errors'])}")
    return "\n".join(lines)[:1000]
```

- [ ] **Step 4: Register in the weekly scheduler bucket**

In `verenigingen/hooks/scheduler.py`, inside the `"weekly": [` list, add before the closing `]`:

```python
        # Data retention (gated; dry-run unless explicitly enabled in settings)
        "verenigingen.verenigingen_payments.core.compliance.data_retention_policy.run_scheduled_retention_policies",
```

- [ ] **Step 5: Create the seed patch**

`verenigingen/patches/v1_0/seed_data_retention_category_policies.py`:

```python
import frappe


def execute():
    """Seed Data Retention Settings with the 9 default category policies (once)."""
    if not frappe.db.exists("DocType", "Data Retention Settings"):
        return
    settings = frappe.get_single("Data Retention Settings")
    if settings.get("category_policies"):
        return  # already has rows; do not clobber admin edits
    settings.reset_category_policies()
```

Add to `patches.txt` (repo root) under the most recent `[post_model_sync]` section (append as the last line of that block):

```
verenigingen.patches.v1_0.seed_data_retention_category_policies
```

(If `verenigingen/patches/v1_0/` lacks an `__init__.py`, create an empty one. Confirm the correct patches sub-package by reading the tail of `patches.txt` and matching the existing dotted paths.)

- [ ] **Step 6: Migrate, clear cache, run test**

Run: `bench --site test_site_2 migrate && bench --site test_site_2 clear-cache && bench --site test_site_2 run-tests --app verenigingen --module verenigingen.verenigingen_payments.tests.test_retention_scheduler`
Expected: PASS (2 tests).

- [ ] **Step 7: Mutation-verify**

In `run_scheduled_retention_policies`, temporarily change `if not settings.enabled:` to `if False:` → `test_disabled_engine_skips_and_leaves_last_run_untouched` FAILS (last_run gets set). Revert. Re-run: pass.

- [ ] **Step 8: Commit**

```bash
git add verenigingen/verenigingen_payments/core/compliance/data_retention_policy.py \
        verenigingen/hooks/scheduler.py \
        verenigingen/patches/v1_0/seed_data_retention_category_policies.py \
        patches.txt \
        verenigingen/verenigingen_payments/tests/test_retention_scheduler.py
git commit -m "feat(compliance): weekly gated retention scheduler + seed patch"
```

---

### Task 5: Live-path integration test for the one live-capable category

**Files:**
- Test: `verenigingen/verenigingen_payments/tests/test_retention_live_temporary_data.py` (create)

**Interfaces:**
- Consumes: Tasks 1–4. Proves the ONLY live path (`temporary_data`) actually deletes aged rows and only aged rows.

- [ ] **Step 1: Write the live-path test**

Create `verenigingen/verenigingen_payments/tests/test_retention_live_temporary_data.py`:

```python
"""The single live-capable path: temporary_data deletes aged webhook_validation
Mollie Audit Log rows (and only those) when fully enabled. This is the one
destructive path this project ships; it must be proven end-to-end."""

import frappe
from frappe.utils import add_days, now_datetime
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    DataCategory,
    DataRetentionPolicy,
)


class TestRetentionLiveTemporaryData(VereningingenTestCase):
    def _make_audit_row(self, action, age_days):
        doc = frappe.get_doc(
            {
                "doctype": "Mollie Audit Log",
                "event_type": "webhook_received",
                "event_category": "webhook",
                "severity": "info",
                "action": action,
                "status": "success",
                "description": "retention test row",
            }
        )
        doc.insert(ignore_permissions=True)
        # timestamp drives retention; force it directly.
        frappe.db.set_value("Mollie Audit Log", doc.name, "timestamp",
                            add_days(now_datetime(), -age_days))
        self.track_doc("Mollie Audit Log", doc.name)
        return doc.name

    def _policy_live_for_temporary(self):
        policy = DataRetentionPolicy()
        policy.retention_periods[DataCategory.TEMPORARY_DATA] = 30
        policy.category_live_flags = {DataCategory.TEMPORARY_DATA: True}
        return policy

    def test_dry_run_deletes_nothing(self):
        aged = self._make_audit_row("webhook_validation", age_days=60)
        policy = self._policy_live_for_temporary()
        policy.apply_retention_policies(dry_run=True)  # global dry-run wins
        self.assertTrue(frappe.db.exists("Mollie Audit Log", aged))

    def test_live_deletes_only_aged_webhook_validation_rows(self):
        aged = self._make_audit_row("webhook_validation", age_days=60)
        recent = self._make_audit_row("webhook_validation", age_days=1)
        other = self._make_audit_row("payment_created", age_days=60)
        policy = self._policy_live_for_temporary()
        policy.apply_retention_policies(dry_run=False)
        self.assertFalse(frappe.db.exists("Mollie Audit Log", aged))    # purged
        self.assertTrue(frappe.db.exists("Mollie Audit Log", recent))   # too new
        self.assertTrue(frappe.db.exists("Mollie Audit Log", other))    # wrong action
```

If `test-quality-enforcer` blocks the `insert(ignore_permissions=True)` in `_make_audit_row`, it is already inside an `_make_`-prefixed helper (allow-listed); keep it there. Add `# Security: test fixture row, no user context` on that line if `permission-bypass-validator` complains.

- [ ] **Step 2: Run test to verify it fails (or errors) before wiring is complete**

Run: `bench --site test_site_2 run-tests --app verenigingen --module verenigingen.verenigingen_payments.tests.test_retention_live_temporary_data`
Expected on a correct Task 1 build: both tests PASS. If `test_live_deletes_only_aged_webhook_validation_rows` does NOT delete `aged`, the gate/effective_dry_run wiring from Task 1 is wrong — fix Task 1, not the test.

- [ ] **Step 3: Confirm the required Mollie Audit Log fields**

Read `verenigingen/verenigingen_payments/doctype/mollie_audit_log/mollie_audit_log.json` and confirm `event_type`, `event_category`, `severity`, `action`, `status`, `timestamp` exist and which are `reqd`. Adjust `_make_audit_row`'s dict to satisfy every `reqd` field. Re-run until green.

- [ ] **Step 4: Mutation-verify**

In `_effective_dry_run` (Task 1), temporarily force `return True` → `test_live_deletes_only_aged_webhook_validation_rows` FAILS (aged row survives). Revert. Re-run: pass.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen_payments/tests/test_retention_live_temporary_data.py
git commit -m "test(compliance): live-path integration test for temporary_data retention"
```

---

### Task 6: Verenigingen Settings link button (client script)

**Files:**
- Modify: `verenigingen/verenigingen/doctype/verenigingen_settings/verenigingen_settings.js`

**Interfaces:**
- Consumes: Task 3's `Data Retention Settings` DocType (route target).

- [ ] **Step 1: Add the trigger call in `refresh`**

In `verenigingen_settings.js`, in the `refresh` handler where the other `frm.trigger(...)` calls are (right after `frm.trigger('setup_member_portal_buttons');`), add:

```javascript
		frm.trigger('setup_compliance_buttons');
```

- [ ] **Step 2: Add the trigger definition**

Add a new method to the form script object (next to `setup_member_portal_buttons`):

```javascript
	setup_compliance_buttons(frm) {
		frm.add_custom_button(
			__('Data Retention'),
			() => frappe.set_route('Form', 'Data Retention Settings'),
			__('Compliance')
		);
	},
```

- [ ] **Step 3: Lint**

Run: `npx eslint verenigingen/verenigingen/doctype/verenigingen_settings/verenigingen_settings.js`
Expected: no new errors.

- [ ] **Step 4: Build + manual verification**

Run: `bench build --app verenigingen && bench --site test_site_2 clear-cache`
Then open Verenigingen Settings in Desk → confirm a **Compliance ▸ Data Retention** button appears and routes to the Data Retention Settings form. (Client-only navigation; no automated test.)

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/verenigingen_settings/verenigingen_settings.js
git commit -m "feat(compliance): link Data Retention Settings from Verenigingen Settings"
```

---

### Task 7: Backlog the surfaced pre-existing engine bugs + memory

**Files:**
- Modify: `verenigingen/docs/testing/test-remediation/backlog-dead-code.md` (or `backlog-missing-coverage.md` — match where engine bugs are tracked)
- Modify: `~/.claude/projects/-home-frappeuser-frappe-bench-apps-verenigingen/memory/MEMORY.md` + a new topic file

- [ ] **Step 1: Record the three engine bugs**

Append to the backlog file a "Data Retention engine — live-path hazards (blocked from allowlist)" entry documenting: (a) `_archive_audit_log` writes non-existent `archived` field on Mollie Audit Log (dry-run can't surface it); (b) `_anonymize_payment` mutates a submitted Payment Entry via `db.set_value` (GL/eBoekhouden desync risk); (c) `_process_payment_data`/`_process_personal_data` age by `creation` not business date. Note each is why the corresponding category is excluded from `LIVE_CAPABLE_CATEGORIES`.

- [ ] **Step 2: Commit**

```bash
git add verenigingen/docs/testing/test-remediation/
git commit -m "docs(backlog): record retention engine live-path hazards"
```

- [ ] **Step 3: Update memory** (MEMORY.md pointer + topic file for this feature). Not committed to git (memory dir is outside the repo).

---

## Verification before PR

- [ ] `bench --site test_site_2 migrate && bench --site test_site_2 clear-cache`
- [ ] Run all new modules together:
  `bench --site test_site_2 run-tests --app verenigingen --module verenigingen.verenigingen_payments.tests.test_data_retention_policy` (existing, still green)
  and each new `test_*` module from Tasks 1–5.
- [ ] `black verenigingen/... && ruff check verenigingen/...` on all changed Python.
- [ ] Confirm the scheduler entry imports cleanly: `bench --site test_site_2 execute verenigingen.verenigingen_payments.core.compliance.data_retention_policy.run_scheduled_retention_policies` → returns `{'skipped': True}` on a fresh site (engine disabled).
- [ ] Push branch (background; pre-push hooks ≈ 2 min), open PR against `develop`, poll CI, merge on green (with approval).

## Self-review notes (author)
- Spec coverage: allowlist (T1), guarded load (T1), Single+child DocTypes (T2/T3), seed-once patch + reset (T3/T4), validate guards (T3), scheduler gate + flush + set_value (T4), live-path proof (T5), VerSettings link (T6), backlog (T7). All spec sections mapped.
- Seeding uses a **patch** (reviewer-endorsed alternative to `after_insert`, which is unreliable for Single first-insert timing) + a `reset_category_policies()` button/method; tests drive the reset method directly.
