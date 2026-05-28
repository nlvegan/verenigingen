"""
Shared @unittest.skip reasons for the post-PR-#96 deferral cluster.

Consolidates near-clone reason strings that were previously inlined in each
file. See `docs/plans/2026-05-27-test-failure-triage-plan.md` for the rubric.
"""


DUES_SCHEMA_GONE = (
    "Membership Type schema migrated in patches/v2_0/migrate_membership_type_billing_to_dues_schedule.py: "
    "predefined_tiers, contribution_mode, enable_income_calculator, income_percentage_rate, "
    "suggested_contribution moved to Membership Dues Schedule templates. On the new target doctype, "
    "contribution_mode is `Fixed|Income-Based|Flexible` - the affected tests write 'Tier', 'Tiers', "
    "'Calculator', 'Custom', 'Both' which are not valid Select options. Tests also reference the "
    "removed verenigingen.api.enhanced_membership_application module from inside their create_test_* "
    "helpers and test bodies. Re-enable after rewriting against the new template-based schema. See "
    "docs/plans/2026-05-27-test-failure-triage-plan.md (Bucket B - schema dead). G3 sweep deferral from PR #98."
)


VOLUNTEER_EXPENSE_ARCHIVED = (
    "Volunteer Expense DocType was archived in commit 1a8e5fa2; "
    "patches/v2_2/drop_volunteer_expense_archived_doctype.py drops the table. "
    "The base factory helper create_test_volunteer_expense now raises NotImplementedError. "
    "Rewrite against the HRMS Expense Claim flow "
    "(verenigingen.services.volunteer.volunteer_expense_setup + "
    "verenigingen.templates.pages.volunteer.expenses.submit_expense) to re-enable. "
    "Group C deferral - see docs/plans/2026-05-27-test-failure-triage-plan.md."
)
