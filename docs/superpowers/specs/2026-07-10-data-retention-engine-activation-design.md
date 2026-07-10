# Data Retention Engine Activation — Design

_Date: 2026-07-10 · Branch: `feat/data-retention-engine-activation` · Base: `develop`_

## Context

`verenigingen/verenigingen_payments/core/compliance/data_retention_policy.py`
defines `DataRetentionPolicy` — a GDPR/compliance engine that can purge or
anonymize aged data by category (`Payment Entry`, `Member`, `SEPA Mandate`,
`Sales Invoice`, `Mollie Audit Log`, `Journal Entry`, plus categories with no
mapping yet). As of task #3 (PR #136) `SEPA Mandate` was added to the category
mapping, but the class remains **orphaned**: it is not registered in any
`scheduler_events` hook, exposed by any whitelisted API, nor instantiated by
production code. Retention *periods* are code-level placeholders and several
categories have no processing logic.

This project activates the engine **safely**: it runs on a schedule but does
nothing destructive until an administrator deliberately opts in, and it becomes
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
   missing per-category *processing* branches stay **no-ops** (the dry-run
   report counts them but purges nothing — consistent with task #3's deferral).

## Goals / Non-goals

**Goals**
- Register the engine in `scheduler_events` (weekly), gated behind an enable flag.
- Add `Data Retention Settings` (Single) + `Data Retention Category Policy`
  (child) DocTypes.
- Make `_load_custom_policies()` read those settings (periods, actions,
  per-category live flags).
- Enforce per-category live semantics: a category purges for real only when
  the global `dry_run_only` is OFF **and** that category's `live_enabled` is ON.
- Link the settings page from Verenigingen Settings via a custom button.
- Record `last_run` / `last_run_summary` for visibility; keep the existing
  audit-trail logging.

**Non-goals**
- Persisting legal holds (remains in-memory; unused by the scheduled path).
- Implementing the missing per-category processing branches (SEPA Mandate and
  four others stay no-ops).
- Admin-configurable run frequency.
- Any change to what data is actually deleted/anonymized by the existing
  processing branches.

## Architecture

```
scheduler (weekly)
  └─ run_scheduled_retention_policies()          # new module-level entrypoint
       ├─ read Data Retention Settings singleton
       ├─ if not enabled: return (no-op)
       ├─ policy = DataRetentionPolicy()          # __init__ -> _load_custom_policies()
       │     └─ _load_custom_policies() reads settings:
       │           retention_periods / retention_actions / live flags  <- child table
       ├─ results = policy.apply_retention_policies(dry_run = settings.dry_run_only)
       │     └─ _process_category(): effective_dry_run = dry_run or not live_flags[cat]
       └─ persist last_run + last_run_summary; audit-trail entry (existing)

Verenigingen Settings form
  └─ custom button "Data Retention" (Compliance group) -> Data Retention Settings form
```

### Components

**DocType: `Data Retention Settings` (Single, module `Verenigingen`)**
| field | type | default | notes |
|-------|------|---------|-------|
| `enabled` | Check | 0 | master switch; scheduler skips if off |
| `dry_run_only` | Check | 1 | global safety gate |
| `category_policies` | Table (`Data Retention Category Policy`) | — | auto-seeded on first save |
| `last_run` | Datetime | — | read-only, set by scheduler |
| `last_run_summary` | Small Text / Code | — | read-only, human-readable run summary |

**DocType: `Data Retention Category Policy` (child table, module `Verenigingen`)**
| field | type | default | notes |
|-------|------|---------|-------|
| `category` | Select (9 `DataCategory` values) | — | e.g. `payment_data`, `mandate_data`, … |
| `retention_days` | Int | (seeded) | overrides code default |
| `action` | Select: `delete`/`anonymize`/`archive`/`review` | (seeded) | overrides code default |
| `live_enabled` | Check | 0 | per-category opt-in to real purge |

Seeding: the `Data Retention Settings` controller (`validate` / a helper)
populates `category_policies` from `DataRetentionPolicy.DEFAULT_RETENTION_PERIODS`
and `DEFAULT_RETENTION_ACTIONS` when the table is empty, so all 9 categories are
visible with their code-default period/action and `live_enabled = 0`.

**Engine changes (`data_retention_policy.py`)**
- `_load_custom_policies()`: if `Data Retention Settings` exists and has rows,
  override `self.retention_periods[cat]` / `self.retention_actions[cat]` per
  row (mapping the `category` string back to the `DataCategory` enum), and build
  `self.category_live_flags: Dict[DataCategory, bool]`. Robust to unknown/legacy
  category strings (skip with a log). Default `category_live_flags` to all-False
  when settings absent (preserves current behavior for any direct caller).
- `_process_category()`: compute
  `effective_dry_run = dry_run or not self.category_live_flags.get(category, False)`
  and pass `effective_dry_run` to the `_process_*` helpers instead of the raw
  `dry_run`. This is the only behavioral change to the engine, and it can only
  make a run *more* conservative than before.

**Scheduler entrypoint (`run_scheduled_retention_policies()`)**
- New module-level function in `data_retention_policy.py` (kept in the engine
  module for cohesion).
- Reads the singleton via `frappe.get_single`. If `not enabled`, returns a
  skipped marker (and does not touch `last_run`). Otherwise runs
  `apply_retention_policies(dry_run=settings.dry_run_only)`, writes `last_run` +
  `last_run_summary`, and lets the existing `_log_retention_execution` audit
  hook fire.
- Registered in `verenigingen/hooks/scheduler.py` under `"weekly"`.

**Verenigingen Settings link (`verenigingen_settings.js`)**
- Add a `setup_compliance_buttons(frm)` trigger adding
  `frm.add_custom_button(__('Data Retention'), () => frappe.set_route('Form', 'Data Retention Settings'), __('Compliance'))`.

## Data flow / safety invariants

1. **Off by default:** fresh install → `enabled = 0` → scheduler is a no-op.
2. **Dry-run by default:** `enabled = 1, dry_run_only = 1` → reports only,
   deletes nothing, regardless of per-category `live_enabled`.
3. **Per-category opt-in:** live purge for a category requires BOTH
   `dry_run_only = 0` AND that row's `live_enabled = 1`.
4. **No-op processing categories:** categories without a `_process_*` branch
   (incl. `mandate_data`) report 0 affected and purge nothing even when live —
   documented, not a regression.

## Error handling
- Scheduler entrypoint wraps the run so a failure logs an Error Log and does not
  crash the scheduler tick; `last_run_summary` records the error.
- `_load_custom_policies()` tolerates a missing DocType (pre-migrate), missing
  singleton, empty table, and unknown category strings without raising.
- Per-category exceptions are already captured into `results["errors"]` by
  `apply_retention_policies` (unchanged).

## Testing (real docs, mutation-verified, `test_site_2`)
1. **Auto-seed:** saving an empty `Data Retention Settings` yields 9
   `category_policies` rows matching the code defaults.
2. **Custom-policy override:** editing a row's `retention_days` → a fresh
   `DataRetentionPolicy()` reflects the override in `retention_periods` (proves
   `_load_custom_policies` reads the table). Mutation: revert the read → default
   returns → test reds.
3. **`effective_dry_run` truth table** (`_process_category` behavior):
   - `dry_run_only=1` + `live_enabled=1` → effective dry-run (no purge).
   - `dry_run_only=0` + `live_enabled=0` → effective dry-run (no purge).
   - `dry_run_only=0` + `live_enabled=1` → live for that category.
   Verified against a category that HAS a processing branch (e.g. a seeded
   old `Mollie Audit Log` temporary_data / audit_logs row) so "live" is
   observable, using real seeded rows.
4. **Scheduler gate:** `run_scheduled_retention_policies()` with `enabled=0`
   returns skipped and leaves `last_run` untouched; with `enabled=1,
   dry_run_only=1` it sets `last_run`, writes a summary, and purges nothing.
5. All new tests use `VereningingenTestCase` + real factory docs, no mocking of
   frappe primitives; each rewrite/assertion mutation-verified.

## Rollout / migration
- New DocTypes ship via fixtures/migration; `bench migrate` creates them.
- `enabled=0` default means activation has zero runtime effect until an admin
  turns it on — safe to merge and deploy.
- `bench --site <site> clear-cache` after adding the scheduler entry / JS.

## Resolved implementation choices
- `run_scheduled_retention_policies()` lives in the engine module
  (`data_retention_policy.py`).
- `last_run_summary` is a `Small Text` human-readable summary (record counts per
  category + dry-run flag); full machine detail already goes to the audit trail.
