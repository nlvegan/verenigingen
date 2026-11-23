"""
Shared @unittest.skip reasons for the post-PR-#96 deferral cluster.

Consolidates near-clone reason strings that were previously inlined in each
file. See `docs/plans/2026-05-27-test-failure-triage-plan.md` for the rubric.
"""


VOLUNTEER_EXPENSE_ARCHIVED = (
    "Volunteer Expense DocType was archived in commit 1a8e5fa2; "
    "patches/v2_2/drop_volunteer_expense_archived_doctype.py drops the table. "
    "The base factory helper create_test_volunteer_expense now raises NotImplementedError. "
    "Rewrite against the HRMS Expense Claim flow "
    "(verenigingen.services.volunteer.volunteer_expense_setup + "
    "verenigingen.templates.pages.volunteer.expenses.submit_expense) to re-enable. "
    "Group C deferral - see docs/plans/2026-05-27-test-failure-triage-plan.md."
)
