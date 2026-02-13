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
| Whitelisted debug API files | 80 | **Deleted** — 26,834 LOC removed |
| Orphaned utils | 81 | **Deleted** — 13,683 LOC removed (87 files incl. services/events) |
| Orphaned payment debug utils | ~12 | Needs investigation — Mollie module reorganized |
| Orphaned services | 5 | **Deleted** — included in utils cleanup round |
| Orphaned event handlers | 1 | **Deleted** — included in utils cleanup round |

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

### Deleted: 87 Orphaned Utils/Services/Events (13,683 LOC removed)

One-off debug, fix, check, cleanup, and analysis utilities with zero imports anywhere in the codebase. Also includes orphaned services and event handlers.

**utils/debug/ (52 files — entire directory removed):**
Debug/diagnostic utilities for e-boekhouden imports, payment APIs, permissions, templates, SEPA, membership, and more. None imported by production code.

**utils/fix_\* (6 files):**
- `fix_overpaid_invoice.py`, `fix_eboekhouden_workspace.py`, `fix_member_ownership.py`
- `fix_sepa_database_issues.py`, `fix_missing_payment_history.py`, `fix_unique_db.py`

**utils/check_\* (3 files):**
- `check_subscription_payment.py`, `check_existing_accounts.py`, `check_coverage_mismatch.py`

**utils/cleanup_\* (5 files):**
- `cleanup_function_summary.py`, `cleanup_e_boekhouden_codebase.py`, `cleanup_direct_sql.py`
- `cleanup_orphaned_links.py`, `cleanup_duplicate_assignments.py`

**utils/analyze_\* (5 files):**
- `analyze_like_usage.py`, `analyze_mutation_ledgers.py`, `analyze_remaining_fallbacks.py`
- `analyze_missed_payments.py`, `analyze_account_mappings.py`

**Other orphaned utils (10 files):**
- `validate_team_role_migration.py` — one-off migration validator
- `chapter_role_profile_hooks.py` — zero imports
- `volunteer_role_profile_hooks.py` — zero imports
- `security/cache_invalidation.py` — zero imports (rest of security/ is active)
- `inspect_journal_entry.py` — debug utility
- `execute_workspace_reorg.py` — zero imports (one-off script)
- `workspace_reports_organizer.py` — only referenced by execute_workspace_reorg.py
- `admin_utilities/mandate_sync_utility.py` — zero imports
- `admin_utilities/payment_entry_repair_utility.py` — zero imports
- `admin_utilities/subscription_management_utility.py` — zero imports

**Orphaned services (5 files):**
- `services/customer_service.py` — explicitly marked DEPRECATED, zero imports
- `services/donation/management_service.py` — zero imports (other donation services are active)
- `services/donation/validation_service.py` — zero imports
- `services/payment_processing_service.py` — zero imports
- `services/infrastructure/integration_tests.py` — test file in wrong location

**Orphaned event handler (1 file):**
- `events/simple_expense_hooks.py` — NOT registered in doc_events.py, zero imports

**Files investigated but KEPT:**
- `utils/nuke_financial_data.py` and `nuke_financial_data_fast.py` — imported by e_boekhouden code
- `utils/admin_utilities/subscription_audit.py` — imported by 3 files (reports, www)
- `utils/admin_utilities/run_audit.py` — imported by subscription audit report
- `utils/workspace_analyzer.py`, `workspace_link_validator.py`, `workspace_content_fixer.py` — imported by `commands/workspace.py`
- `services/donation/donor_service.py`, `financial_service.py`, `reporting_service.py` — actively used by Donation DocType controller

## Remaining Cleanup Targets

All priority 1–4 items have been cleaned up. The remaining items are:

### Payment Module Debug Utils

The original analysis identified `mollie/utils/` debug files, but these paths no longer exist (the Mollie module was reorganized into `verenigingen_payments/`). The `verenigingen_payments/utils/` directory contains ~40 SEPA and payment utility files that need individual import verification before any can be removed — these are likely a mix of active and orphaned code.

### hooks/before_request.py

Listed in the analysis but file does not exist on disk — already removed or never created as a separate file (the hook is commented out inline in `hooks/lifecycle.py:69-71`).

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
