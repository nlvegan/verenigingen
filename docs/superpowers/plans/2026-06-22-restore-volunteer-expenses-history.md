# Restore `volunteer_expenses` History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-enable the dead-but-wired Member volunteer-expense history so an HRMS Expense Claim records a denormalized snapshot on the linked member's `volunteer_expenses` child table.

**Architecture:** Native HRMS `Expense Claim` stays the source of truth. The live chain (hooks → `expense_handlers` → `financial_history_batch_processor` → `MemberFinancialHistoryManager(member, "volunteer_expenses")` → `ExpenseHistoryEntryBuilder`) is already intact and references `volunteer_expenses`. Restoration = recreate the `Member Volunteer Expenses` child doctype + the Member `volunteer_expenses` Table field, and delete the obsolete post-model-sync patch that drops it. No live-code changes; the `hasattr(..., "volunteer_expenses")` guards auto-pass once the field exists. Going-forward only — no backfill.

**Tech Stack:** Frappe/ERPNext DocTypes (JSON metadata + Python controllers), HRMS Expense Claim, Frappe `bench migrate`, `EnhancedTestCase` real-DB integration tests.

**Reference spec:** `docs/superpowers/specs/2026-06-22-restore-volunteer-expenses-history-design.md`

**Branch:** `feat/restore-volunteer-expenses-history` (already created; spec committed at `76dd0bc3`).

---

## File Structure

- **Create:** `verenigingen/verenigingen/doctype/member_volunteer_expenses/__init__.py` — empty package marker.
- **Create:** `verenigingen/verenigingen/doctype/member_volunteer_expenses/member_volunteer_expenses.json` — child doctype schema (istable=1), verbatim restore.
- **Create:** `verenigingen/verenigingen/doctype/member_volunteer_expenses/member_volunteer_expenses.py` — trivial `Document` subclass.
- **Modify:** `verenigingen/verenigingen/doctype/member/member.json` — add `volunteer_expenses_section` + `volunteer_expenses` Table field to `fields` and `field_order` (after `payment_history`, before `chapter_data_tab`).
- **Modify:** `verenigingen/patches.txt` — remove the `drop_volunteer_expense_archived_doctype` line.
- **Delete:** `verenigingen/patches/v2_2/drop_volunteer_expense_archived_doctype.py`.
- **Create:** `verenigingen/tests/events/test_volunteer_expenses_history_restore.py` — new real-DB integration tests (populate + remove paths).
- **Modify:** `verenigingen/tests/events/test_expense_events_coverage.py` — update the now-stale "NOTE (characterized bug)" docstring at lines 22–26.

No changes to: `expense_mixin.py`, `financial_history_batch_processor.py`, `member_financial_history_manager.py`, `expense_history_entry_builder.py`, `hooks/doc_events.py`, or any subscriber/handler — they are already correct.

---

## Task 1: Write the failing populate-path test

**Files:**
- Test: `verenigingen/tests/events/test_volunteer_expenses_history_restore.py`

- [ ] **Step 1: Write the failing test**

Create `verenigingen/tests/events/test_volunteer_expenses_history_restore.py`:

```python
"""
Integration coverage for the restored Member ``volunteer_expenses`` history.

Real Member / Volunteer / Employee / Expense Claim documents are built (no
business-logic mocking). Exercises the live persistence path that was dead
while the child table was archived:

    queue_expense_update / queue_expense_removal
      -> FinancialHistoryBatchProcessor.force_process_all
        -> MemberFinancialHistoryManager(member, "volunteer_expenses")
          -> ExpenseHistoryEntryBuilder.build_from_expense_doc

The hook wiring itself (Expense Claim doc_events -> expense_handlers) is
covered by test_expense_events_coverage.py; here we assert the denormalized
snapshot actually lands on Member.volunteer_expenses.
"""

import frappe
from frappe.utils import today

from verenigingen.utils.financial_history_batch_processor import (
    FinancialHistoryBatchProcessor,
    queue_expense_removal,
    queue_expense_update,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerExpensesHistoryRestore(EnhancedTestCase):
    """Real integration coverage for the restored volunteer_expenses child table."""

    def setUp(self):
        super().setUp()
        # The batch queues are class-level; flush any cross-test residue so a
        # prior test's queued op cannot leak into this member's batch.
        FinancialHistoryBatchProcessor.force_process_all()

    # ------------------------------------------------------------------ helpers
    def _company(self):
        return (
            "_Test Company"
            if frappe.db.exists("Company", "_Test Company")
            else (frappe.get_all("Company", limit=1, pluck="name") or [None])[0]
        )

    def _accounts(self, company):
        expense = frappe.db.get_value(
            "Account", {"account_type": "Expense Account", "company": company, "is_group": 0}, "name"
        )
        payable = frappe.db.get_value(
            "Account", {"account_type": "Payable", "company": company, "is_group": 0}, "name"
        )
        return expense, payable

    def _make_employee(self, company):
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"VeR{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": company,
            }
        ).insert(ignore_permissions=True)
        self._track_test_document("Employee", emp.name, priority=2)
        return emp

    def _make_volunteer_member_employee(self):
        company = self._company()
        if not company:
            self.skipTest("No Company available")
        member = self.create_test_member(first_name="VExp", last_name="Member", birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        emp = self._make_employee(company)
        volunteer.db_set("employee_id", emp.name, update_modified=False)
        volunteer.reload()
        return member, volunteer, emp, company

    def _make_expense_claim(self, employee, company):
        expense_acct, payable = self._accounts(company)
        if not expense_acct or not payable:
            self.skipTest("No expense/payable accounts available")
        ec = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": employee.name,
                "company": company,
                "custom_organization_type": "National",
                "posting_date": today(),
                "currency": "EUR",
                "exchange_rate": 1,
                "payable_account": payable,
                "expenses": [
                    {
                        "expense_type": "Food",
                        "amount": 12.5,
                        "sanctioned_amount": 12.5,
                        "expense_date": today(),
                        "default_account": expense_acct,
                    }
                ],
            }
        )
        ec.insert(ignore_permissions=True)
        self._track_test_document("Expense Claim", ec.name, priority=1)
        return ec

    # ------------------------------------------------------------------ tests
    def test_queue_expense_update_persists_history_entry(self):
        """A queued expense update lands a real row on Member.volunteer_expenses."""
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_expense_claim(emp, company)

        with self.assertNoErrorLog():
            queue_expense_update(member.name, ec.name)
            FinancialHistoryBatchProcessor.force_process_all()

        member.reload()
        entries = member.get("volunteer_expenses") or []
        self.assertEqual(len(entries), 1, "expected exactly one volunteer_expenses entry")
        row = entries[0]
        self.assertEqual(row.expense_claim, ec.name)
        self.assertEqual(row.volunteer, volunteer.name)
        self.assertEqual(row.total_claimed_amount, 12.5)
        self.assertEqual(row.total_sanctioned_amount, 12.5)
```

- [ ] **Step 2: Run test to verify it fails (RED)**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.events.test_volunteer_expenses_history_restore \
  --test test_queue_expense_update_persists_history_entry
```
Expected: FAIL — `volunteer_expenses` field does not exist yet, so `member.get("volunteer_expenses")` is empty → `0 != 1` (AssertionError "expected exactly one volunteer_expenses entry").

- [ ] **Step 3: Commit the failing test**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/tests/events/test_volunteer_expenses_history_restore.py
git commit -m "test(volunteer-expenses): failing test for restored volunteer_expenses history"
```

---

## Task 2: Restore the `Member Volunteer Expenses` child doctype

**Files:**
- Create: `verenigingen/verenigingen/doctype/member_volunteer_expenses/__init__.py`
- Create: `verenigingen/verenigingen/doctype/member_volunteer_expenses/member_volunteer_expenses.py`
- Create: `verenigingen/verenigingen/doctype/member_volunteer_expenses/member_volunteer_expenses.json`

- [ ] **Step 1: Create the package marker**

Create `verenigingen/verenigingen/doctype/member_volunteer_expenses/__init__.py` as an empty file (zero bytes).

- [ ] **Step 2: Create the controller**

Create `verenigingen/verenigingen/doctype/member_volunteer_expenses/member_volunteer_expenses.py`:

```python
# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MemberVolunteerExpenses(Document):
    # this is a child table doctype, it has no separate code
    pass
```

- [ ] **Step 3: Create the doctype JSON (verbatim restore)**

Create `verenigingen/verenigingen/doctype/member_volunteer_expenses/member_volunteer_expenses.json`:

```json
{
  "actions": [],
  "allow_rename": 1,
  "app": "verenigingen",
  "creation": "2025-07-24 12:00:00.000000",
  "doctype": "DocType",
  "editable_grid": 1,
  "engine": "InnoDB",
  "field_order": [
    "expense_section",
    "expense_claim",
    "volunteer",
    "posting_date",
    "column_break_e1",
    "total_claimed_amount",
    "total_sanctioned_amount",
    "status",
    "payment_section",
    "payment_status",
    "payment_date",
    "column_break_p1",
    "payment_entry",
    "payment_method",
    "column_break_p2",
    "paid_amount"
  ],
  "fields": [
    {
      "fieldname": "expense_section",
      "fieldtype": "Section Break",
      "label": "Expense Information"
    },
    {
      "fieldname": "expense_claim",
      "fieldtype": "Link",
      "in_list_view": 1,
      "label": "Expense Claim",
      "options": "Expense Claim",
      "read_only": 1
    },
    {
      "fieldname": "volunteer",
      "fieldtype": "Link",
      "in_list_view": 1,
      "label": "Volunteer",
      "options": "Volunteer",
      "read_only": 1
    },
    {
      "fieldname": "posting_date",
      "fieldtype": "Date",
      "in_list_view": 1,
      "label": "Claim Date",
      "read_only": 1
    },
    {
      "fieldname": "column_break_e1",
      "fieldtype": "Column Break"
    },
    {
      "fieldname": "total_claimed_amount",
      "fieldtype": "Currency",
      "label": "Claimed Amount",
      "options": "Company:company:default_currency",
      "read_only": 1
    },
    {
      "fieldname": "total_sanctioned_amount",
      "fieldtype": "Currency",
      "in_list_view": 1,
      "label": "Approved Amount",
      "options": "Company:company:default_currency",
      "read_only": 1
    },
    {
      "fieldname": "status",
      "fieldtype": "Data",
      "label": "Status",
      "read_only": 1
    },
    {
      "fieldname": "payment_section",
      "fieldtype": "Section Break",
      "label": "Payment Information"
    },
    {
      "fieldname": "payment_status",
      "fieldtype": "Select",
      "in_list_view": 1,
      "label": "Payment Status",
      "options": "Pending\nPaid\nRejected",
      "read_only": 1
    },
    {
      "fieldname": "payment_date",
      "fieldtype": "Date",
      "in_list_view": 1,
      "label": "Payment Date",
      "read_only": 1
    },
    {
      "fieldname": "column_break_p1",
      "fieldtype": "Column Break"
    },
    {
      "fieldname": "payment_entry",
      "fieldtype": "Link",
      "label": "Payment Entry",
      "options": "Payment Entry",
      "read_only": 1
    },
    {
      "fieldname": "payment_method",
      "fieldtype": "Data",
      "label": "Payment Method",
      "read_only": 1
    },
    {
      "fieldname": "column_break_p2",
      "fieldtype": "Column Break"
    },
    {
      "fieldname": "paid_amount",
      "fieldtype": "Currency",
      "label": "Paid Amount",
      "options": "Company:company:default_currency",
      "read_only": 1
    }
  ],
  "istable": 1,
  "links": [],
  "modified": "2026-06-22 12:00:00.000000",
  "modified_by": "Administrator",
  "module": "Verenigingen",
  "name": "Member Volunteer Expenses",
  "owner": "Administrator",
  "permissions": [],
  "sort_field": "modified",
  "sort_order": "DESC",
  "states": []
}
```

- [ ] **Step 4: Commit the restored doctype**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/verenigingen/doctype/member_volunteer_expenses/
git commit -m "feat(volunteer-expenses): restore Member Volunteer Expenses child doctype"
```

---

## Task 3: Add the `volunteer_expenses` field to the Member doctype

**Files:**
- Modify: `verenigingen/verenigingen/doctype/member/member.json`

The current `field_order` contains the consecutive entries `... "payment_history_section", "payment_history", "chapter_data_tab" ...`. Insert the two new fieldnames between `payment_history` and `chapter_data_tab`.

- [ ] **Step 1: Update `field_order`**

In `member.json`, find this fragment of the `field_order` array:

```json
  "payment_history_section",
  "payment_history",
  "chapter_data_tab",
```

Replace with:

```json
  "payment_history_section",
  "payment_history",
  "volunteer_expenses_section",
  "volunteer_expenses",
  "chapter_data_tab",
```

- [ ] **Step 2: Add the two field definitions**

In `member.json`, locate the field definition object whose `"fieldname": "payment_history"` (a Table field). Immediately after that object's closing `},`, insert these two field objects:

```json
    {
      "fieldname": "volunteer_expenses_section",
      "fieldtype": "Section Break",
      "label": "Volunteer Expenses"
    },
    {
      "fieldname": "volunteer_expenses",
      "fieldtype": "Table",
      "label": "Volunteer Expenses",
      "options": "Member Volunteer Expenses",
      "read_only": 1
    },
```

(If `payment_history`'s object is the last in the `fields` array, ensure commas remain valid JSON after insertion.)

- [ ] **Step 3: Validate the JSON parses**

Run:
```bash
cd ~/frappe-bench/apps/verenigingen
python3 -c "import json; d=json.load(open('verenigingen/verenigingen/doctype/member/member.json')); assert 'volunteer_expenses' in d['field_order']; assert any(f['fieldname']=='volunteer_expenses' and f['options']=='Member Volunteer Expenses' for f in d['fields']); print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit the Member field**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/verenigingen/doctype/member/member.json
git commit -m "feat(volunteer-expenses): add read-only volunteer_expenses table to Member"
```

---

## Task 4: Delete the obsolete drop patch

**Files:**
- Modify: `verenigingen/patches.txt`
- Delete: `verenigingen/patches/v2_2/drop_volunteer_expense_archived_doctype.py`

- [ ] **Step 1: Remove the patch registration**

In `verenigingen/patches.txt`, delete the single line:

```
verenigingen.patches.v2_2.drop_volunteer_expense_archived_doctype
```

(Leave the sibling line `verenigingen.patches.v2_2.drop_orphan_volunteer_doctype_rows` untouched — it targets unrelated doctypes.)

- [ ] **Step 2: Delete the patch file**

```bash
cd ~/frappe-bench/apps/verenigingen
git rm verenigingen/patches/v2_2/drop_volunteer_expense_archived_doctype.py
```

- [ ] **Step 3: Verify it is fully unreferenced**

Run:
```bash
cd ~/frappe-bench/apps/verenigingen
grep -rn "drop_volunteer_expense_archived_doctype" verenigingen/ --include="*.py" --include="*.txt" | grep -v "drop_orphan_volunteer_doctype_rows"
```
Expected: only a comment reference inside `verenigingen/patches/v2_2/drop_orphan_volunteer_doctype_rows.py` (a docstring mention) may remain — that is harmless. No `patches.txt` line and no patch file should appear.

- [ ] **Step 4: Commit the patch removal**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/patches.txt
git commit -m "chore(volunteer-expenses): drop obsolete drop_volunteer_expense_archived_doctype patch"
```

---

## Task 5: Migrate the local site and make the populate test pass (GREEN)

**Files:** none (runtime only)

- [ ] **Step 1: Create the table via migrate**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org migrate
```
Expected: completes without error.

- [ ] **Step 2: Verify the table now exists**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org mariadb -e "SHOW TABLES LIKE 'tabMember Volunteer Expenses'"
```
Expected: one row listing `tabMember Volunteer Expenses`.

- [ ] **Step 3: Run the populate test (now GREEN)**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.events.test_volunteer_expenses_history_restore \
  --test test_queue_expense_update_persists_history_entry
```
Expected: PASS.

(No commit — no files changed in this task.)

---

## Task 6: Add the remove-path test

**Files:**
- Modify: `verenigingen/tests/events/test_volunteer_expenses_history_restore.py`

- [ ] **Step 1: Add the failing remove-path test**

Append this method to the `TestVolunteerExpensesHistoryRestore` class:

```python
    def test_queue_expense_removal_deletes_history_entry(self):
        """Queuing a removal drops the previously-recorded entry."""
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_expense_claim(emp, company)

        with self.assertNoErrorLog():
            queue_expense_update(member.name, ec.name)
            FinancialHistoryBatchProcessor.force_process_all()
        member.reload()
        self.assertEqual(len(member.get("volunteer_expenses") or []), 1)

        with self.assertNoErrorLog():
            queue_expense_removal(member.name, ec.name)
            FinancialHistoryBatchProcessor.force_process_all()

        member.reload()
        remaining = [r for r in (member.get("volunteer_expenses") or []) if r.expense_claim == ec.name]
        self.assertEqual(remaining, [], "removal should delete the entry for this claim")
```

- [ ] **Step 2: Run the remove-path test**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.events.test_volunteer_expenses_history_restore \
  --test test_queue_expense_removal_deletes_history_entry
```
Expected: PASS. (The schema already exists from Task 5, so this is green immediately — it verifies the remove branch of the chain, which was equally dead before.)

- [ ] **Step 3: Run the whole new test module**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.events.test_volunteer_expenses_history_restore
```
Expected: both tests PASS.

- [ ] **Step 4: Commit the remove-path test**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/tests/events/test_volunteer_expenses_history_restore.py
git commit -m "test(volunteer-expenses): cover expense-history removal path"
```

---

## Task 7: Refresh the stale docstring and run the regression sweep

**Files:**
- Modify: `verenigingen/tests/events/test_expense_events_coverage.py`

- [ ] **Step 1: Update the now-false NOTE**

In `verenigingen/tests/events/test_expense_events_coverage.py`, replace the docstring block at lines 22–26:

```
NOTE (characterized bug): the Member doctype has NO ``volunteer_expenses`` child
field on this site, so ``ExpenseMixin.add_expense_to_history`` /
``remove_expense_from_history`` early-return and write NOTHING. The expense
subscribers therefore complete "successfully" without persisting any history.
Tests below assert this observable no-op rather than a phantom history row.
```

with:

```
NOTE: the Member ``volunteer_expenses`` child table was restored
(2026-06-22). The member-expense-history persistence path is now exercised by
``test_volunteer_expenses_history_restore.py``; this module covers the event
emitters, subscribers, and doc-event scheduling around it.
```

- [ ] **Step 2: Run the related test files (regression)**

Run each and confirm no new failures introduced by the schema change:
```bash
cd ~/frappe-bench && for m in \
  verenigingen.tests.events.test_expense_events_coverage \
  verenigingen.tests.backend.unit.services.test_member_history_update_service \
  verenigingen.tests.backend.unit.api.test_chapter_dashboard_api_coverage \
  verenigingen.tests.utils.test_member_history_integrity \
  verenigingen.tests.volunteer.test_volunteer_expense_services_coverage ; do
    echo "===== $m ====="
    bench --site veg11.veganisme.org run-tests --module "$m" || echo "FAILED: $m"
  done
```
Expected: all PASS. If any fail, inspect: these reference `volunteer_expenses` either as termination-summary keys (`volunteer_expenses_cancelled`) or as `member_history_update_service` result keys whose structure is unchanged, or as `get_volunteer_expenses_count` which keys off the still-absent `Volunteer Expense` parent doctype. A genuine failure means the change touched one of those — fix the specific assertion to reflect real post-restore behavior (do not weaken to a tautology).

- [ ] **Step 3: Commit the docstring refresh**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/tests/events/test_expense_events_coverage.py
git commit -m "test(volunteer-expenses): refresh stale no-op note after history restore"
```

---

## Task 8: Final verification

**Files:** none

- [ ] **Step 1: Confirm the live chain is unchanged**

Run:
```bash
cd ~/frappe-bench/apps/verenigingen
git diff develop --stat -- verenigingen/utils/financial_history_batch_processor.py \
  verenigingen/utils/member_financial_history_manager.py \
  verenigingen/services/volunteer/expense_history_entry_builder.py \
  verenigingen/verenigingen/doctype/member/mixins/expense_mixin.py \
  verenigingen/hooks/doc_events.py
```
Expected: empty output (no diff) — the live persistence chain was not modified.

- [ ] **Step 2: Run the full changed-surface diff review**

Run:
```bash
cd ~/frappe-bench/apps/verenigingen && git diff develop --stat
```
Expected: only the doctype create, `member.json`, `patches.txt`, the deleted patch, and the two test files (plus the spec/plan docs).

- [ ] **Step 3: Request code review**

Use the `superpowers:requesting-code-review` skill (or dispatch the `skeptical-code-reviewer` agent) on the branch diff, with focus on: (a) the two new tests are meaningful (assert real persisted values, not tautologies), and (b) no fresh-site regression from deleting the drop patch.

---

## Self-Review (completed at authoring)

- **Spec coverage:** child doctype restore (Task 2), Member field (Task 3), drop-patch deletion (Task 4), migration (Task 5), no live-code changes (verified Task 8), going-forward-only/no backfill (no backfill task present — intentional), TDD populate + remove tests (Tasks 1, 6). ✅ all spec sections mapped.
- **Placeholder scan:** no TBD/TODO; every code/JSON step contains full content. ✅
- **Type/name consistency:** field names (`volunteer_expenses`, `Member Volunteer Expenses`), manager target, builder keys, and the `force_process_all` / `queue_expense_update` / `queue_expense_removal` APIs all match the inspected source. ✅
