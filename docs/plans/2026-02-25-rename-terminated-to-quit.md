# Rename Member Status "Terminated" → "Quit" Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the member status value "Terminated" with "Quit" across the entire Verenigingen codebase and database.

**Architecture:** This is a mechanical rename touching 4 layers: (1) DocType schema JSON files, (2) Python constants/types/business logic/SQL, (3) JavaScript UI/form/test code, (4) HTML templates. A database migration patch updates existing records. The constant `STATUS_TERMINATED` stays named the same but its VALUE changes to `"Quit"`.

**Tech Stack:** Frappe/Python/MariaDB, JavaScript, JSON DocType schemas, Cypress E2E tests

---

## Scope Summary

| Layer | Files | Occurrences |
|-------|-------|-------------|
| Python (.py) | ~74 files | ~254 (231 double-quoted + 23 single-quoted) |
| JavaScript (.js, .spec.js) | ~19 files | ~59 |
| JSON (.json) | ~5 files | ~10 |
| HTML (.html) | 3 files | 3 |
| **Total** | **~101 files** | **~326** |

**NOT renamed:** The word "termination" (noun) in DocType names, field names, method names, function names, file names, comments — these describe the *process*, not the *status value*. Only the literal status string `"Terminated"` changes to `"Quit"`.

---

### Task 1: Create the database migration patch

This MUST run first so that existing data in the database is updated before the new code expects `"Quit"`.

**Files:**
- Create: `verenigingen/patches/v2_1/rename_terminated_status_to_quit.py`
- Modify: `verenigingen/patches.txt` (append new patch)

**Step 1: Write the migration patch**

```python
"""Rename member status 'Terminated' to 'Quit' across all relevant tables."""
import frappe


def execute():
    """Update all database records that store 'Terminated' status to 'Quit'."""
    # 1. Member.status
    frappe.db.sql("""
        UPDATE `tabMember`
        SET status = 'Quit'
        WHERE status = 'Terminated'
    """)

    # 2. Chapter Membership History.status
    frappe.db.sql("""
        UPDATE `tabChapter Membership History`
        SET status = 'Quit'
        WHERE status = 'Terminated'
    """)

    # 3. Any Communication/Comment that references the status in structured data
    # (comments with "Terminated" in free text are left as-is — they're historical records)

    frappe.db.commit()
```

**Step 2: Register the patch in patches.txt**

Append to `[post_model_sync]` section of `verenigingen/patches.txt`:
```
verenigingen.patches.v2_1.rename_terminated_status_to_quit
```

**Step 3: Commit**

```bash
git add verenigingen/patches/v2_1/rename_terminated_status_to_quit.py verenigingen/patches.txt
git commit -m "feat: add migration patch to rename 'Terminated' status to 'Quit'"
```

---

### Task 2: Update DocType JSON schemas

These define the valid option values for Select fields. The patch in Task 1 updates data; this task updates the schema so the UI shows the new value.

**Files:**
- Modify: `verenigingen/verenigingen/doctype/member/member.json` (2 locations)
- Modify: `verenigingen/verenigingen/doctype/chapter_membership_history/chapter_membership_history.json` (1 location)

**Step 1: Update member.json status field options**

Line 509 — change the options string:
```
Old: "options": "Pending\nActive\nRejected\nExpired\nSuspended\nBanned\nDeceased\nTerminated"
New: "options": "Pending\nActive\nRejected\nExpired\nSuspended\nBanned\nDeceased\nQuit"
```

Line 1131 — change the status indicator title:
```
Old: "title": "Terminated"
New: "title": "Quit"
```

**Step 2: Update chapter_membership_history.json status field options**

Line 62:
```
Old: "options": "Active\nPending\nCompleted\nInactive\nTerminated"
New: "options": "Active\nPending\nCompleted\nInactive\nQuit"
```

**Step 3: Commit**

```bash
git add verenigingen/verenigingen/doctype/member/member.json \
       verenigingen/verenigingen/doctype/chapter_membership_history/chapter_membership_history.json
git commit -m "feat: update DocType schemas to use 'Quit' status instead of 'Terminated'"
```

---

### Task 3: Update Python constants and type definitions

These are the single source of truth that much of the codebase imports.

**Files:**
- Modify: `verenigingen/utils/constants.py:159`
- Modify: `verenigingen/custom_types.py:19`

**Step 1: Update constants.py**

```python
# Old (line 159):
STATUS_TERMINATED = "Terminated"

# New:
STATUS_TERMINATED = "Quit"
```

Note: The constant NAME `STATUS_TERMINATED` is kept — renaming it to `STATUS_QUIT` would be a separate refactor and risks introducing bugs in places that import it. The important thing is the VALUE changes.

**Step 2: Update custom_types.py**

```python
# Old (line 19):
MemberStatus = Literal["Pending", "Active", "Inactive", "Suspended", "Terminated"]

# New:
MemberStatus = Literal["Pending", "Active", "Inactive", "Suspended", "Quit"]
```

**Step 3: Commit**

```bash
git add verenigingen/utils/constants.py verenigingen/custom_types.py
git commit -m "feat: update STATUS_TERMINATED value and MemberStatus type to 'Quit'"
```

---

### Task 4: Update all Python business logic files (non-test)

Bulk find-and-replace of the string `"Terminated"` with `"Quit"` across all non-test Python files. This covers:
- Status comparisons (`== "Terminated"`, `!= "Terminated"`)
- Status assignments (`status = "Terminated"`)
- List membership checks (`in ["Terminated", ...]`)
- SQL queries (`WHERE status = 'Terminated'`, `NOT IN ('Terminated', ...)`)
- Log/comment messages (`"Updated member status to Terminated"`)
- UI label strings (`_("Terminated")`, `_("Membership Terminated")`)

**Files (non-test, ~30 files):** Use the following commands to find and replace. The agent should process each file, verifying context to ensure only status-value strings are changed (not the word "termination" in other contexts).

**Key files with SQL (single-quoted `'Terminated'`):**
- `verenigingen/verenigingen/report/member_end_date_reconstruction/member_end_date_reconstruction.py` — `'Terminated'` in SQL
- `vereinigingen/utils/termination_integration.py` — `'Terminated'` in SQL
- `verenigingen/verenigingen/report/account_creation_status/account_creation_status.py` — `'Terminated'` in SQL
- `verenigingen/permissions.py` — `'Terminated'` in SQL/filter lists
- `verenigingen/verenigingen/report/members_without_active_memberships/members_without_active_memberships.py` — `'Terminated'` in SQL
- `verenigingen/verenigingen/page/membership_analytics/membership_analytics.py` — `'Terminated'` in SQL
- `verenigingen/services/csv_import/member_import_service.py` — `'Terminated'` in SQL/filter
- `verenigingen/services/mollie_debug_service.py` — `'Terminated'` in filter
- `verenigingen/verenigingen_payments/api/dd_batch_optimizer.py` — `'Terminated'` in SQL

**Key files with double-quoted `"Terminated"` (non-test):**
- `verenigingen/utils/chapter_membership_history_manager.py` (6 occurrences)
- `verenigingen/events/subscribers/member_subscribers.py` (3)
- `verenigingen/utils/alert_manager.py` (2)
- `verenigingen/utils/validation_utilities.py` (3)
- `verenigingen/utils/termination_integration.py` (9)
- `verenigingen/utils/csv/data_transformers.py` (2)
- `verenigingen/services/member/core/member_lifecycle_service.py` (2)
- `verenigingen/services/member/core/member_status_service.py` (4)
- `verenigingen/services/member/lifecycle/member_status_notification_service.py` (1)
- `verenigingen/services/member/account/member_user_account_service.py` (1)
- `verenigingen/services/member/display/member_volunteer_display_service.py` (1)
- `verenigingen/services/billing/bulk_invoice_generation_service.py` (1)
- `verenigingen/services/billing/billing_date_service.py` (1)
- `verenigingen/services/billing/eligibility_checker.py` (1)
- `vereinigingen/services/account/account_creation_service.py` (1)
- `verenigingen/services/csv_import/mollie_sync_service.py` (1)
- `verenigingen/services/csv_import/member_import_service.py` (4)
- `verenigingen/services/monitoring/monitoring_metrics_service.py` (1)
- `verenigingen/vereinigingen/doctype/member/mixins/termination_mixin.py` (3)
- `verenigingen/verenigingen/doctype/member/member_utils.py` (2)
- `verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.py` (2)
- `verenigingen/verenigingen/doctype/membership_goal/membership_goal.py` (1)
- `verenigingen/vereinigingen/doctype/mijnrood_csv_import/mijnrood_csv_import.py` (1)
- `verenigingen/mijnrood_sync/services/event_application_service.py` (2)
- `vereinigingen/api/membership_application.py` (1)
- `verenigingen/templates/pages/chapter_dashboard.py` (1)
- `verenigingen/verenigingen/page/membership_analytics/membership_analytics.py` (8)
- `verenigingen/utils/resource_monitor.py` (1)
- `verenigingen/utils/business_logic_monitor.py` (1)
- `verenigingen/verenigingen_payments/api/dd_batch_optimizer.py` (2)

**Step 1: Replace all `"Terminated"` → `"Quit"` in non-test Python files**

Use targeted find-and-replace. For each file:
1. Read the file
2. Replace `"Terminated"` with `"Quit"` (double-quoted instances)
3. Replace `'Terminated'` with `'Quit'` (single-quoted instances, especially in SQL)
4. Verify no false positives (the string "Terminated" as a status value vs. other uses)

**Special attention for UI strings:**
- `"Membership Terminated"` → `"Membership Quit"` — **WAIT**: This is a UI label. The user-facing label should say something natural. Consider: `"Membership Ended"` or just keep the label as-is and only change the status value. **Decision: Change the status VALUE only.** UI labels like `"Membership Terminated"` that describe the action/state in prose should be updated to `"Membership Quit"` for consistency.

**Step 2: Commit**

```bash
git add -u  # stages all modified tracked files
git commit -m "feat: rename 'Terminated' to 'Quit' in all Python business logic and SQL queries"
```

---

### Task 5: Update all JavaScript files (non-test)

**Files (~8 non-test JS files):**
- `verenigingen/verenigingen/doctype/member/member.js` (3 occurrences) — dashboard indicators, status labels
- `verenigingen/verenigingen/doctype/member/member_list.js` (1) — list view indicator
- `verenigingen/verenigingen/doctype/membership/membership_list.js` (1) — comment
- `verenigingen/public/js/member/js_modules/chapter-history-utils.js` (5) — chapter history display
- `verenigingen/public/js/member/js_modules/volunteer-utils.js` (1) — volunteer eligibility
- `verenigingen/public/js/customer_member_link.js` (1) — customer link display
- `verenigingen/verenigingen/report/members_without_active_memberships/members_without_active_memberships.js` (6) — report filters
- `verenigingen/verenigingen/report/members_without_dues_schedule/members_without_dues_schedule.js` (5) — report filters

**Step 1: Replace `"Terminated"` → `"Quit"` and `'Terminated'` → `'Quit'` in all non-test JS files**

For each file, also update UI-facing strings:
- `__('Terminated')` → `__('Quit')`
- `__('Membership Terminated')` → `__('Membership Quit')`
- `Terminated: ['red', ...]` → `Quit: ['red', ...]` (list view indicator keys)

**Step 2: Commit**

```bash
git add -u
git commit -m "feat: rename 'Terminated' to 'Quit' in JavaScript form, list, and report files"
```

---

### Task 6: Update HTML template files

**Files (3 files):**
- `verenigingen/templates/pages/mollie_payment_processing.html:489` — help text
- `verenigingen/templates/pages/chapter_dashboard.html:175` — status badge
- `verenigingen/www/mollie_member_reconciliation.html:459` — status-to-color mapping

**Step 1: Replace in each file**

```
# mollie_payment_processing.html
Old: "Both include all member statuses (Active, Terminated, etc.)"
New: "Both include all member statuses (Active, Quit, etc.)"

# chapter_dashboard.html
Old: >Terminated</span>
New: >Quit</span>

# mollie_member_reconciliation.html
Old: 'Terminated': 'danger',
New: 'Quit': 'danger',
```

**Step 2: Commit**

```bash
git add -u
git commit -m "feat: rename 'Terminated' to 'Quit' in HTML templates"
```

---

### Task 7: Update test contract JSON files

**Files:**
- `verenigingen/tests/contracts/member-contracts.json` (4 occurrences)
- `vereinigingen/tests/setup/api-contract-simple.js` (4 occurrences)

**Step 1: Replace all `"Terminated"` → `"Quit"` in both files**

**Step 2: Commit**

```bash
git add -u
git commit -m "test: update API contract schemas to use 'Quit' status"
```

---

### Task 8: Update all Python test files

This is the largest batch (~40 test files, ~170+ occurrences). Mechanical replacement.

**Files (all under `verenigingen/tests/` or `verenigingen/services/csv_import/test_*`):**
- `tests/backend/components/test_member_status_transitions.py` (19)
- `tests/backend/components/test_membership_status_comprehensive.py` (20)
- `tests/backend/components/test_member_portal_integration.py` (15)
- `tests/backend/components/test_volunteer_member_integration.py` (7)
- `tests/backend/components/test_financial_reconciliation_comprehensive.py` (6)
- `tests/backend/components/test_chapter_assignment_comprehensive.py` (1)
- `tests/backend/components/test_membership_analytics_functionality.py` (1)
- `tests/backend/components/test_member_lifecycle_iban.py` (1)
- `tests/backend/workflows/test_member_lifecycle.py` (4)
- `tests/backend/workflows/test_member_lifecycle_basic.py` (2)
- `tests/backend/workflows/test_member_lifecycle_complete.py` (4)
- `tests/backend/workflows/test_suspension_system.py` (1)
- `tests/backend/comprehensive/test_termination_workflow_edge_cases.py` (2)
- `tests/backend/comprehensive/test_termination_system_comprehensive.py` (1)
- `tests/backend/unit/services/test_member_status_notification_service.py` (2)
- `tests/integration/test_chapter_membership_approval_integration.py` (7)
- `tests/integration/test_member_lifecycle_complete_real.py` (2)
- `tests/integration/services/test_eligibility_checker.py` (4)
- `tests/services/test_billing_date_service.py` (1)
- `tests/services/test_event_application_service.py` (4)
- `tests/test_member_doctype_integration_fixed.py` (2)
- `tests/test_member_permissions.py` (3)
- `tests/test_api_endpoints_comprehensive.py` (5)
- `tests/test_chapter_members_enhanced.py` (2)
- `tests/test_invoice_eligibility_validation.py` (4)
- `tests/test_member_lifecycle_comprehensive.py` (9)
- `tests/test_member_lifecycle_workflows.py` (1)
- `tests/test_dutch_business_logic_integration.py` (6)
- `tests/test_csv_data_transformers.py` (2)
- `tests/unit/test_member_lifecycle_production_issues_discovered.py` (2)
- `tests/unit/test_member_lifecycle_unit.py` (5)
- `tests/unit/test_member_payment_matcher.py` (3)
- `tests/unit/test_member_lifecycle_mock_elimination.py` (3)
- `tests/unit/test_eboekhouden_mock_elimination.py` (1)
- `tests/fixtures/test_personas.py` (2)
- `tests/fixtures/test_data_factory_extended.py` (2)
- `tests/fixtures/test_data_factory.py` (1)
- `tests/fixtures/enhanced_test_factory.py` (1)
- `tests/utils/assertions.py` (1)
- `services/csv_import/test_member_import_service.py` (2)

**Step 1: Replace all `"Terminated"` → `"Quit"` and `'Terminated'` → `'Quit'` in all test Python files**

**Step 2: Commit**

```bash
git add -u
git commit -m "test: rename 'Terminated' to 'Quit' in all Python test files"
```

---

### Task 9: Update JavaScript test files

**Files (~8 JS test files):**
- `tests/unit/doctype/test_member_controller.test.js` (2)
- `tests/frontend/integration/business-workflows.test.js` (4)
- `tests/frontend/doctypes/volunteer.test.js` (2)
- `tests/frontend/doctypes/member.test.js` (4)
- `tests/frontend/unit/api-service.spec.js` (1)
- `tests/frontend/unit/workflow-transitions.spec.js` (7)
- `tests/setup/domain-test-builders.js` (1)
- `cypress/support/commands.js` (2 + function name `verifyMemberTerminated`)
- `cypress/integration/member-controller.spec.js` (3)

**Step 1: Replace all `"Terminated"` → `"Quit"` in all JS test files**

**Special case:** `cypress/support/commands.js` has a Cypress command named `verifyMemberTerminated`. Rename it to `verifyMemberQuit` and update all call sites.

**Step 2: Commit**

```bash
git add -u
git commit -m "test: rename 'Terminated' to 'Quit' in all JavaScript test files"
```

---

### Task 10: Run migration and verify

**Step 1: Run the database migration**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org migrate
```

Expected: Patch `rename_terminated_status_to_quit` executes successfully, schema syncs new option values.

**Step 2: Clear cache**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache
```

**Step 3: Verify no remaining references**

```bash
cd ~/frappe-bench/apps/verenigingen && grep -rn '"Terminated"' verenigingen/ --include="*.py" --include="*.js" --include="*.json" --include="*.html" | grep -v node_modules | grep -v '.ruff_cache' | grep -v __pycache__
cd ~/frappe-bench/apps/verenigingen && grep -rn "'Terminated'" verenigingen/ --include="*.py" --include="*.js" --include="*.json" --include="*.html" | grep -v node_modules | grep -v '.ruff_cache' | grep -v __pycache__
```

Expected: Zero matches (or only matches in documentation/comments that describe the historical rename).

**Step 4: Run tests to verify nothing broke**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen
```

**Step 5: Final commit (if any fixups needed)**

```bash
git commit -m "fix: address any remaining 'Terminated' references found during verification"
```

---

## Execution Order & Dependencies

```
Task 1 (migration patch) ─┐
Task 2 (JSON schemas)     ─┤
Task 3 (constants/types)  ─┼── All independent, can be done in parallel
Task 4 (Python logic)     ─┤    but commit in order for clean history
Task 5 (JS logic)         ─┤
Task 6 (HTML templates)   ─┤
Task 7 (test contracts)   ─┤
Task 8 (Python tests)     ─┤
Task 9 (JS tests)         ─┘
Task 10 (migrate & verify) ── depends on ALL above
```

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Database has "Terminated" records | Migration patch (Task 1) handles this |
| Missed occurrence causes runtime error | Task 10 grep verification catches stragglers |
| External systems send "Terminated" | CSV import `data_transformers.py` maps Dutch values → status; update the mapping target |
| Cypress command rename breaks tests | Rename command AND all call sites in Task 9 |
| `STATUS_TERMINATED` constant name misleading | Acceptable — renaming the constant is a separate refactor |

## Out of Scope

- Renaming the constant `STATUS_TERMINATED` → `STATUS_QUIT` (would touch every import site)
- Renaming "termination" in DocType names, field names, method names, file names
- Renaming the `Membership Termination Request` DocType
- Updating external documentation (.md files) — these describe historical/process context
