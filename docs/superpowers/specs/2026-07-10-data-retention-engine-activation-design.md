# Data Retention Engine Activation — Design

_Date: 2026-07-10 · Branch: `feat/data-retention-engine-activation` · Base: `develop`_
_Rev 2 — incorporates SWE review (blocking items 1–3 + guardrails 4–14)._

## Context

`verenigingen/verenigingen_payments/core/compliance/data_retention_policy.py`
defines `DataRetentionPolicy` — a GDPR/compliance engine that can purge or
anonymize aged data by category (`Payment Entry`, `Member`, `SEPA Mandate`,
`Sales Invoice`, `Mollie Audit Log`, `Journal Entry`, plus categories with no
mapping yet). As of task #3 (PR #136) `SEPA Mandate` was added to the category
mapping, but the class remains **orphaned**: not registered in any
`scheduler_events` hook, exposed by any whitelisted API, nor instantiated by
production code. Retention *periods* are code-level placeholders and several
categories have no processing logic.

This project activates the engine **safely**: it runs on a schedule but does
nothing destructive until an administrator deliberately opts in — and even then,
only for categories whose live path has been individually verified. It becomes
configurable through a dedicated settings page linked from Verenigingen
Settings.

### Confirmed decisions (from brainstorming)
1. **Execution mode:** dry-run report only, gated. The scheduled job skips
   unless explicitly enabled; when enabled it defaults to `dry_run=True`.
2. **Settings scope:** a full settings page — global enable/dry-run gate **plus**
   a per-category child table (period, action, per-category live-enable) that
   feeds `_load_custom_policies()`.
3. **Defaulted calls (approved):** scheduler frequency fixed at **weekly** in
   code (not admin-configurable); legal-hold persistence **out of scope**;
   missing per-category *processing* branches stay **no-ops**.

### Added after SWE review (this rev)
4. **Live execution is allow-listed, not just flag-gated.** A category is
   purged for real only if it is in an engine-level `LIVE_CAPABLE_CATEGORIES`
   allowlist AND its row's `live_enabled` is on AND global `dry_run_only` is off.
   Initial allowlist = **`{TEMPORARY_DATA}`** only (a clean, testable
   `DELETE` of aged `webhook_validation` Mollie Audit Log rows). Every other
   category is forced to dry-run regardless of settings, because its live path
   is unverified or known-broken (see "Known pre-existing bugs" below). This is
   what makes "flip a checkbox to go live" safe: the dangerous paths
   (`payment_data` anonymize-on-submitted-doc, `personal_data` Member delete,
   `audit_logs` archive-to-missing-field) are simply not reachable yet.
5. `settings.validate()` **rejects** `live_enabled=1` on any non-allowlisted
   category, with a message pointing at the follow-up work.

## Goals / Non-goals

**Goals**
- Register the engine in `scheduler_events` (weekly), gated behind `enabled`.
- Add `Data Retention Settings` (Single) + `Data Retention Category Policy`
  (child) DocTypes, with explicit permissions.
- Make `_load_custom_policies()` read those settings (periods, actions,
  per-category live flags), robust to pre-migrate / missing-singleton / unknown
  category strings.
- Enforce the layered live-execution gate (§decision 4).
- Link the settings page from Verenigingen Settings via a custom button.
- Record `last_run` / `last_run_summary` for durable visibility; flush the
  audit-trail buffer so the compliance log is actually written.

**Non-goals**
- Persisting legal holds (remains in-memory; unused by the scheduled path).
- Implementing/repairing the missing or broken per-category processing branches
  (tracked as backlog, below).
- Admin-configurable run frequency.
- Making `payment_data` / `personal_data` / `audit_logs` live-capable (deferred
  to per-category verification follow-ups).

## Architecture

```
scheduler (weekly)
  └─ run_scheduled_retention_policies()          # new module-level entrypoint
       ├─ settings = frappe.get_single("Data Retention Settings")
       ├─ if not settings.enabled: return skipped   # last_run untouched
       ├─ policy = DataRetentionPolicy()          # __init__ -> _load_custom_policies()
       │     └─ _load_custom_policies() (guarded) reads settings:
       │           retention_periods / retention_actions / live flags <- child table
       ├─ results = policy.apply_retention_policies(dry_run = settings.dry_run_only)
       │     └─ _process_category():
       │           effective_dry_run = dry_run or not (
       │               live_flags.get(cat) and cat in LIVE_CAPABLE_CATEGORIES)
       ├─ frappe.db.set_value(... last_run, last_run_summary ...)   # not doc.save()
       ├─ get_audit_trail()._flush_buffer()       # make the audit log durable
       └─ frappe.db.commit()

Verenigingen Settings form
  └─ custom button "Data Retention" (Compliance group) -> Data Retention Settings form
```

### Components

**DocType: `Data Retention Settings` (Single, module `Verenigingen`)**
Placed in the main `Verenigingen` module (next to Verenigingen Settings) for
discoverability, even though the engine code lives under `verenigingen_payments`
— the controller imports the engine cross-module (normal in this app).

| field | type | default | notes |
|-------|------|---------|-------|
| `enabled` | Check | 0 | master switch; scheduler skips if off |
| `dry_run_only` | Check | 1 | global safety gate |
| `category_policies` | Table (`Data Retention Category Policy`) | — | seeded once on insert; "Reset to defaults" button |
| `last_run` | Datetime | — | read-only, set by scheduler via `db.set_value` |
| `last_run_summary` | Small Text | — | read-only; per-category counts + dry-run flag |

Permissions: mirror `Verenigingen Settings` — **write** for `System Manager` +
`Verenigingen Administrator`; no broad write. (A page that can eventually
trigger deletion must be at least as restricted as general settings.)

**DocType: `Data Retention Category Policy` (child table, module `Verenigingen`, `istable=1`)**
| field | type | default | notes |
|-------|------|---------|-------|
| `category` | Select (the 9 `DataCategory` values) | — | e.g. `payment_data`, `mandate_data`, … |
| `retention_days` | Int | (seeded) | overrides code default; validated `>= 30` |
| `action` | Select: `delete`/`anonymize`/`archive`/`review` | (seeded) | overrides code default |
| `live_enabled` | Check | 0 | per-category opt-in; rejected unless category is live-capable |

**Seeding (idempotent, not on every save):** the parent controller seeds
`category_policies` from `DataRetentionPolicy.DEFAULT_RETENTION_PERIODS` /
`DEFAULT_RETENTION_ACTIONS` **only when the doc is new** (`self.is_new()` /
`after_insert`), plus an explicit **"Reset to defaults"** button/whitelisted
method. Never re-seed "when empty" — an admin who deletes rows to fall back to
code defaults must not have them silently re-added.

**Parent `validate()` guards:**
- Reject duplicate `category` rows (ambiguous override; last-wins is unsafe).
- Reject `retention_days < 30` (a `0`/blank makes `cutoff = now`, expiring
  every record in that category on the next live run).
- Reject `live_enabled = 1` where `category` ∉ `LIVE_CAPABLE_CATEGORIES`.

**Engine changes (`data_retention_policy.py`)**
- Add module/class constant
  `LIVE_CAPABLE_CATEGORIES = {DataCategory.TEMPORARY_DATA}` with a comment
  listing why the others are excluded (unverified / known-broken paths).
- `_load_custom_policies()` (currently `pass`): guard correctly for a **Single**
  — `if not frappe.db.exists("DocType", "Data Retention Settings"): return`
  (NOT `table_exists`; a Single never has its own table), then wrap
  `frappe.get_single(...)` and the `.category_policies` read in try/except
  (the *child* table `tabData Retention Category Policy` can raise 1146
  pre-migrate). For each row, map the `category` string back to `DataCategory`
  (skip + log unknown strings), override `self.retention_periods[cat]` /
  `self.retention_actions[cat]`, and populate
  `self.category_live_flags[cat] = bool(row.live_enabled)`. When settings are
  absent, `category_live_flags` stays empty → all-dry-run (preserves any direct
  caller's current behavior).
- `_process_category()`: compute
  `effective_dry_run = dry_run or not (self.category_live_flags.get(category, False) and category in LIVE_CAPABLE_CATEGORIES)`
  and pass it to the `_process_*` helpers. Monotonic: can only ever make a run
  *more* conservative than today.

**Scheduler entrypoint (`run_scheduled_retention_policies()` in `data_retention_policy.py`)**
- Reads the singleton; if `not enabled`, returns a skipped marker and does not
  touch `last_run`. Otherwise runs
  `apply_retention_policies(dry_run=settings.dry_run_only)`, writes `last_run` +
  `last_run_summary` via `frappe.db.set_value("Data Retention Settings",
  "Data Retention Settings", {...})` (avoids re-triggering `validate()`/seed),
  calls `get_audit_trail()._flush_buffer()`, then `frappe.db.commit()`.
- Wrapped so any failure logs an Error Log and records the error into
  `last_run_summary` instead of crashing the scheduler tick.
- Registered in `verenigingen/hooks/scheduler.py` under `"weekly"`, with a
  grouping `#` comment matching the file's style.

**Verenigingen Settings link (`verenigingen_settings.js`)**
- Add a `setup_compliance_buttons(frm)` trigger:
  `frm.add_custom_button(__('Data Retention'), () => frappe.set_route('Form', 'Data Retention Settings'), __('Compliance'))`.

## Safety invariants
1. **Off by default:** `enabled = 0` → scheduler no-op.
2. **Dry-run by default:** `enabled = 1, dry_run_only = 1` → reports only.
3. **Layered live gate:** live purge requires `dry_run_only = 0` AND row
   `live_enabled = 1` AND `category ∈ LIVE_CAPABLE_CATEGORIES`. The first two are
   admin-settable; the third is code-controlled and currently `{TEMPORARY_DATA}`.
4. **`validate()` refuses** to save `live_enabled=1` on a non-live-capable
   category, so the unsafe combination can't even be persisted.
5. **No-op / excluded categories** report their dry-run counts but purge nothing.

## Error handling
- Scheduler entrypoint: try/except → Error Log + `last_run_summary` error text;
  never raises out of the tick.
- `_load_custom_policies()` tolerates missing DocType, missing singleton, empty
  table, pre-migrate child-table 1146, and unknown category strings.
- Per-category exceptions remain captured into `results["errors"]` by
  `apply_retention_policies` (unchanged).

## Testing (real docs, mutation-verified, `test_site_2`)
1. **Auto-seed on insert:** a freshly-created `Data Retention Settings` has 9
   `category_policies` rows matching code defaults; a subsequent save with a row
   deleted does NOT re-add it (proves seed-once, not seed-if-empty).
2. **Custom-policy override:** editing a row's `retention_days` → a fresh
   `DataRetentionPolicy()` reflects it in `retention_periods` (proves
   `_load_custom_policies` reads the table). Mutation: neutralize the read →
   default returns → red.
3. **Layered `effective_dry_run` truth table** on the one live-capable category
   (`temporary_data`) using real seeded aged `Mollie Audit Log`
   `webhook_validation` rows:
   - `dry_run_only=1, live_enabled=1` → no delete.
   - `dry_run_only=0, live_enabled=0` → no delete.
   - `dry_run_only=0, live_enabled=1, category live-capable` → aged rows deleted,
     non-aged rows untouched (the one real live-path integration test).
4. **Non-capable live rejection:** setting `live_enabled=1` on `payment_data`
   (or `personal_data`/`audit_logs`) raises `ValidationError` on save.
5. **Guard tests:** duplicate `category` rejected; `retention_days=10` rejected.
6. **Enum/Select drift:** a test imports `DataCategory`, parses the child
   DocType JSON `category` options, and asserts the two sets are identical
   (prevents silent breakage of the string→enum mapping).
7. **Scheduler gate:** `run_scheduled_retention_policies()` with `enabled=0`
   returns skipped and leaves `last_run` untouched; with `enabled=1,
   dry_run_only=1` it sets `last_run`, writes a summary, flushes the audit
   buffer, and purges nothing.
8. All new tests use `VereningingenTestCase` + real factory docs, no mocking of
   frappe primitives; each assertion mutation-verified.

## Known pre-existing bugs surfaced (backlogged, NOT fixed here)
These live in the engine's untested processing branches. Activation makes them
*reachable*, so the allowlist (§decision 4) keeps them unreachable until fixed.
Record in `docs/testing/test-remediation/backlog-*.md`:
- **`_archive_audit_log` writes a non-existent field** (`data_retention_policy.py`
  ~L373: `set_value("Mollie Audit Log", …, "archived", 1)` — no `archived` field
  on that DocType). `audit_logs`' default action is `ARCHIVE`, and the dry-run
  branch short-circuits before this line, so dry-run cannot surface it. Blocks
  `audit_logs` from the live allowlist.
- **`_anonymize_payment` mutates a submitted Payment Entry** via `db.set_value`
  (`party`/`reference_no`), bypassing controller validation and risking GL/
  eBoekhouden reconciliation desync. Blocks `payment_data` from the allowlist.
- **`_process_payment_data` / `_process_personal_data` age by `creation`, not
  business/posting date** — misleading for eBoekhouden-migrated historical rows.
  Dry-run counts should be sanity-checked against business dates before any of
  these categories is ever considered for the allowlist.

## Rollout / migration
- New DocTypes sync automatically on `bench migrate` from their checked-in
  JSON/py (this is doctype schema-sync, **not** `hooks.py` `fixtures` — no data
  export needed).
- `enabled = 0` default → zero runtime effect until an admin opts in; safe to
  merge and deploy.
- `bench --site <site> clear-cache` after adding the scheduler entry / JS.

## Resolved implementation choices
- `run_scheduled_retention_policies()` lives in the engine module
  (`data_retention_policy.py`).
- `last_run_summary` is `Small Text` (per-category counts + dry-run flag); full
  machine detail already goes to the (now-flushed) audit trail.
- Initial `LIVE_CAPABLE_CATEGORIES = {TEMPORARY_DATA}`; expanding it is a
  deliberate, per-category, test-backed follow-up.
