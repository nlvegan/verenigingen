# Design — Restore `volunteer_expenses` history tracking on Member

**Date:** 2026-06-22
**Status:** Approved (design); pending implementation plan
**Author:** brainstorming session (Foppe + Claude)

## Problem

The Member-side volunteer-expense history is wired end-to-end in code but is a
**guarded no-op**: every layer short-circuits on `hasattr(member,
"volunteer_expenses")`, which is `False` because the child table field and its
child doctype were removed.

History of the removal:

1. Commit `1a8e5fa2` *"refactor: archive Volunteer Expense DocType, wire
   department approver sync"* archived the `Volunteer Expense` DocType **and**
   the `Member Volunteer Expenses` child table, and removed the
   `volunteer_expenses` Table field from the Member DocType. Stated intent:
   "The system now uses native ERPNext Expense Claim via Employee linkage."
2. Patch `verenigingen/patches/v2_2/drop_volunteer_expense_archived_doctype.py`
   later **dropped** both orphaned doctypes and their data tables
   (`tabVolunteer Expense`, `tabMember Volunteer Expenses`) to stop
   `ModuleNotFoundError` on CI.

Net effect today: native HRMS `Expense Claim` is the source of truth, but the
member never gets a denormalized history snapshot — the feature is dead.

## Goal

Re-enable the chain so that submitting / updating / cancelling an HRMS Expense
Claim records (or removes) a denormalized snapshot on the linked member's
`volunteer_expenses` child table. **Going-forward only** — no backfill of
historical claims.

## Key finding (why this is low-churn)

The entire processing chain is intact and self-consistent:

```
hooks/doc_events.py ("Expense Claim": on_submit / on_update_after_submit)
  → services/volunteer/expense_handlers.py (queue_expense_update / _removal)
  → events/delayed_expense_hooks.py, events/subscribers/expense_history_subscriber.py
  → utils/financial_history_batch_processor.py (batched, 30s)
  → utils/member_financial_history_manager.py
        get_expense_history_manager(member) -> MemberFinancialHistoryManager(member, "volunteer_expenses", max_entries=30)
  → services/volunteer/expense_history_entry_builder.py
        ExpenseHistoryEntryBuilder.build_from_expense_doc(expense_doc, member_name)
```

- The **manager already targets** the `volunteer_expenses` field
  (`member_financial_history_manager.py:346`) — "repoint the manager" is already
  done.
- The **builder already emits** a dict whose keys map 1:1 to the archived
  `Member Volunteer Expenses` schema. No builder change is needed.
- The `hasattr(..., "volunteer_expenses")` guards in `ExpenseMixin`
  (`member/mixins/expense_mixin.py`) and the batch processor
  (`financial_history_batch_processor.py:208`) auto-pass once the field exists.

So restoration = restore the doctype + the Member field + stop dropping it.
Source of truth stays native HRMS Expense Claim; the child table is a
denormalized history view.

## Scope of changes

### 1. Restore the child doctype (verbatim)

Recreate `verenigingen/verenigingen/doctype/member_volunteer_expenses/` from git
`1a8e5fa2~1`:

- `member_volunteer_expenses.json` — `istable=1`, `editable_grid=1`, module
  `Verenigingen`, engine InnoDB. Fields (verbatim):
  `expense_section` (Section Break), `expense_claim` (Link → Expense Claim),
  `volunteer` (Link → Volunteer), `posting_date` (Date),
  `column_break_e1`, `total_claimed_amount` (Currency),
  `total_sanctioned_amount` (Currency), `status` (Data),
  `payment_section` (Section Break), `payment_status` (Select:
  Pending/Paid/Rejected), `payment_date` (Date), `column_break_p1`,
  `payment_entry` (Link → Payment Entry), `payment_method` (Data),
  `column_break_p2`, `paid_amount` (Currency).
- `member_volunteer_expenses.py` — trivial controller
  `class MemberVolunteerExpenses(Document): pass`.
- `__init__.py`.

### 2. Re-add the Member field (original placement)

In `verenigingen/verenigingen/doctype/member/member.json`:

- Add `volunteer_expenses_section` (Section Break) and `volunteer_expenses`
  field:
  ```json
  {
    "fieldname": "volunteer_expenses",
    "fieldtype": "Table",
    "label": "Volunteer Expenses",
    "options": "Member Volunteer Expenses",
    "read_only": 1
  }
  ```
- Restore both to their original `field_order` position: immediately after
  `payment_history` (i.e. after the `payment_history_section` /
  `payment_history` pair) and before `chapter_data_tab`.

### 3. Delete the obsolete drop patch

- Remove the line
  `verenigingen.patches.v2_2.drop_volunteer_expense_archived_doctype` from
  `verenigingen/patches.txt` (it is under `[post_model_sync]`).
- **Delete** the file
  `verenigingen/patches/v2_2/drop_volunteer_expense_archived_doctype.py`.

Rationale: the patch runs post-model-sync, so on a **fresh** migrate / CI it
would drop the freshly-synced `tabMember Volunteer Expenses` table right after
model sync. Existing sites already logged the patch (it will not re-run), so
deleting it is safe and only affects fresh sites/CI.

The sibling patch `v2_2/drop_orphan_volunteer_doctype_rows.py` targets
`Verenigingen Volunteer` / `Volunteer Team` (unrelated) and is left untouched.

### 4. No live-code changes

Manager, builder, handlers, subscribers, and the `hasattr` guards are already
correct and need no edits.

### 5. Migration

- Local: `bench --site veg11.veganisme.org migrate` (or `reload-doctype
  "Member"` + `reload-doctype "Member Volunteer Expenses"`) to create
  `tabMember Volunteer Expenses`.
- CI: created automatically via model sync (now that the drop patch is gone).

## Testing (TDD)

Real-DB integration tests (no business-logic mocks, per repo conventions),
using the existing test base classes and the Error-Log guard:

1. **Populate path:** create Member + Volunteer with a linked Employee, submit
   an Expense Claim, flush the batch processor (force-process the queue), and
   assert exactly one entry in `member.volunteer_expenses` with the expected
   `expense_claim`, amounts, and `status`. Wrap in `assertNoErrorLog()`.
2. **Remove path:** cancel the Expense Claim → assert the entry is removed.
3. **(Optional) cap regression:** confirm the `max_entries=30` trim still holds.

Tests must fail before the restore (field absent → no entry) and pass after.

## Risk / blast radius

Low. The schema restore is additive and the live code already references the
field everywhere. The only non-additive edit is deleting the obsolete drop
patch, which is required for correctness on fresh sites.

## Out of scope

- Backfilling historical Expense Claims into the restored table (explicitly
  deferred — going-forward only).
- Any change to native HRMS Expense Claim handling or the department-approver
  sync added in `1a8e5fa2`.
- Re-introducing the archived `Volunteer Expense` DocType (it stays archived;
  native Expense Claim remains the source of truth).
