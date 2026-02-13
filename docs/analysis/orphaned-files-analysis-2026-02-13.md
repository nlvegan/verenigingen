# Orphaned Files Analysis — 2026-02-13

Desloppify `show orphaned --status open` reported **822 findings**. This document records the investigation results and triage decisions.

## Triage Summary

| Category | Count | Verdict |
|----------|-------|---------|
| Frappe convention (doctype/report/page/www controllers) | ~120 | False positive — auto-loaded by framework |
| Hooks-registered files (jinja, overrides, events, scheduler) | ~10 | False positive — referenced in hooks config |
| Patches in patches.txt | ~30 | False positive — registered for migration |
| Standalone scripts (`scripts/`) | ~200 | Expected — entry points, not libraries |
| Unregistered patches (deleted) | 16 | **Deleted** — superseded, changes already applied |
| Whitelisted debug API files | ~80 | **Actionable** — unnecessary attack surface |
| Orphaned utils | ~100+ | **Actionable** — dead weight in production path |
| Orphaned payment debug utils | ~12 | **Actionable** — dead weight |
| Orphaned services | 5 | **Actionable** — abandoned implementations |
| Orphaned event handlers | 2 | **Actionable** — confirmed dead code |

## Actions Taken

### Deleted: 80 Orphaned API Files (26,834 LOC removed)

Debug/fix/check API endpoints with `@frappe.whitelist()` decorators that had zero frontend references and zero Python imports (except from other orphaned files). These exposed admin-level operations to any authenticated Frappe user.

**10 API files KEPT** because they have confirmed frontend JS/HTML references:
- `chapter_validation.py` — chapter.js (5 calls)
- `check_account_types.py` — e_boekhouden_migration.js (2 calls)
- `dashboard_charts.py` — member_age_chart.js
- `document_portal.py` — board templates (4 calls)
- `get_user_chapters.py` — chapter.html
- `mollie_payment.py` — payment_dashboard.html (2 calls)
- `overdue_application_notifications.py` — pending_membership_applications.js
- `schedule_maintenance.py` — schedule_maintenance.html (3 calls)
- `update_prepare_system_button.py` — e_boekhouden_migration.js
- `volunteer_application.py` — volunteer/apply.html

### Deleted: 16 Unregistered Patch Files

These patch files existed but were **never listed in `patches.txt`**, meaning they could never run during `bench migrate`. All changes were confirmed already applied (manually or superseded):

**Root-level patches:**
- `patches/add_chapter_board_member_permissions.py`
- `patches/add_customer_member_link_field.py`
- `patches/create_nvv_balance_sheet_template.py`
- `patches/create_nvv_profit_loss_template.py`
- `patches/migrate_donation_agreements.py`
- `patches/remove_unique_constraint_member_dues_schedule.py`
- `patches/rename_amount_to_dues_rate.py`
- `patches/post_install/create_refund_indexes.py`

**Versioned patches:**
- `patches/v1_0/add_address_matching_optimization.py` — verified columns + indexes exist in DB
- `patches/v1_0/fix_workspace_shortcuts_dict_issue.py`
- `patches/v1_0/populate_dynamic_link_doctype_fields.py`
- `patches/v2_0/enhance_donor_customer_integration.py`
- `patches/v2_1/backfill_membership_commitment_end_date.py`

**Database patches (entire directory removed):**
- `database_patches/add_performance_indexes.py`
- `database_patches/migrate_dues_schedule_field.py`
- `database_patches/rename_membership_dues_field.py`

**Note:** `patches/v1_0/add_coverage_duplicate_check_indexes.py` was NOT deleted — it is intentionally called from the `after_migrate` hook in `hooks/lifecycle.py` rather than patches.txt.

## Remaining Cleanup Targets

### Priority 1: Whitelisted Debug API Files (~80 files)

Files in `verenigingen/api/` that have `@frappe.whitelist()` decorators but exist purely for debugging, one-off fixes, or manual maintenance. They expose admin-level operations to any authenticated user via Frappe RPC.

**Patterns found:**
- `api/debug_*` — debugging endpoints
- `api/fix_*` — one-off data fixes
- `api/check_*` — diagnostic checks
- `api/validate_*` — one-time validation scripts
- `api/test_*` — test endpoints left in production
- `api/phase2_2_*` — migration-phase utilities

**Risk:** These are callable by any authenticated user. Many perform data mutations (deletions, field updates, permission changes).

**Notable dangerous endpoints:**
- `api/donation_reset.py` — resets donation data
- `api/fix_race_condition_invoices.py` — modifies invoices
- `api/cleanup_chapter_members.py` — deletes records
- `utils/nuke_financial_data_fast.py` — self-explanatory

### Priority 2: Orphaned Utils (~100+ files)

Files in `verenigingen/utils/` with zero imports anywhere in the codebase. These are one-off debug/fix/analysis utilities that were placed in `utils/` instead of `scripts/`.

**Confirmed truly orphaned (sampled):**
- `utils/chapter_role_profile_hooks.py` — not imported
- `utils/volunteer_role_profile_hooks.py` — not imported
- `utils/security/cache_invalidation.py` — not imported
- `utils/admin_utilities/mandate_sync_utility.py` — not imported
- All `utils/debug/*` files (~30+)
- All `utils/fix_*`, `utils/check_*`, `utils/cleanup_*`, `utils/analyze_*` files

**Confirmed actively used (NOT orphaned):**
- `utils/secure_operations.py` — 150+ imports
- `utils/validation_utilities.py` — 20+ imports
- `utils/account_creation_manager.py` — 19 imports
- `utils/jinja_methods.py` — registered in hooks
- `utils/error_handling.py` — 20+ imports

### Priority 3: Orphaned Services (5 files)

- `services/customer_service.py` — explicitly marked DEPRECATED (superseded by `customer_handling_service.py`)
- `services/donation/management_service.py` — abandoned, zero imports
- `services/donation/validation_service.py` — abandoned, zero imports
- `services/payment_processing_service.py` — abandoned, zero imports
- `services/infrastructure/integration_tests.py` — test file in wrong location

### Priority 4: Orphaned Event Handlers (2 files)

- `events/simple_expense_hooks.py` — NOT in doc_events.py, not imported anywhere
- `hooks/before_request.py` — explicitly commented out in `hooks/lifecycle.py:69-71`

### Priority 5: Payment Module Debug Utils (~12 files)

Mollie debug/fix utilities with zero imports:
- `mollie/utils/debug_issue.py`, `debug_payment_entry.py`
- `mollie/utils/fix_customer_data.py`, `fix_donation_status.py`
- `mollie/utils/check_donation_status.py`, `data_backfill_utility.py`
- `mollie/utils/manual_webhook_retry.py`, `payment_checker.py`, `transaction_manager.py`
- `mollie/utils/relationship_manager.py` — duplicate of active `mollie_relationship_manager.py`
- `core/compliance/regulatory_reporter.py` — abandoned compliance feature

## False Positive Details

### Frappe Convention Files (auto-loaded, no import needed)

**DocType controllers** — Frappe loads `doctype/{name}/{name}.py` automatically when the DocType is accessed. All ~47 flagged doctype controller files are legitimate.

**Report controllers** — Frappe loads `report/{name}/{name}.py` automatically for Script Reports. All ~21 flagged report files are legitimate.

**Template page controllers** — Frappe loads `templates/pages/{name}.py` when serving the corresponding HTML template. All ~40 flagged files are legitimate.

**www controllers** — Frappe loads `www/{name}.py` for www routes. All ~10 flagged files are legitimate.

### Hooks-Registered Files

| File | Registration |
|------|-------------|
| `boot.py` | `hooks/lifecycle.py:59` — `boot_session` |
| `utils/jinja_methods.py` | `hooks/__init__.py:65` — `jinja.methods` |
| `overrides/payment_entry.py` | `hooks/__init__.py:83` — `override_doctype_class` |
| `overrides/sales_invoice.py` | `hooks/doc_events.py` — validate hook |
| `events/delayed_expense_hooks.py` | `hooks/doc_events.py:179,185` — Expense Claim hooks |
| `events/subscribers/team_subscribers.py` | Imported by `events/team_events.py` |
| `mijnrood_sync/tasks.py` | `hooks/scheduler.py:128` — 15-min cron |
| `config/desktop.py`, `config/dashboard.py` | Frappe convention |

### E-boekhouden Module

Initially flagged as partially orphaned, but investigation found it's **well-integrated** with 30+ import sites across the codebase. The `e_boekhouden/hooks.py` is active. DocType controllers are Frappe convention. Only some utils are debug one-offs.

### Payment Infrastructure

Core payment infrastructure is **100% active**: Mollie integration, Ponto integration, ING Checkout, SEPA infrastructure, Direct Debit Batch API — all properly imported and referenced. Only debug/fix utilities are orphaned.
