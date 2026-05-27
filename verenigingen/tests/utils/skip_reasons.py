"""
Shared @unittest.skip reasons for the post-PR-#96 deferral cluster.

Consolidates near-clone reason strings that were previously inlined in each
file. See `docs/plans/2026-05-27-test-failure-triage-plan.md` for the rubric.
"""


ENHANCED_MEMBERSHIP_API_GONE = (
    "verenigingen.api.enhanced_membership_application module was deleted; the "
    "process_enhanced_application / get_membership_types_for_application / "
    "validate_contribution_amount entry points no longer exist at this path. "
    "Re-enable when these are rewired (some functions migrated, e.g. "
    "validate_contribution_amount -> templates/pages/membership_application.py:125). "
    "Group G3 follow-up - see PR #96 notes."
)


LIFECYCLE_SCHEMA_GONE = (
    "Membership Type schema migrated in patches/v2_0/migrate_membership_type_billing_to_dues_schedule.py: "
    "predefined_tiers, contribution_mode, enable_income_calculator, income_percentage_rate, "
    "suggested_contribution moved to Membership Dues Schedule templates. The setUp helpers "
    "(create_tier_based_membership_type, create_calculator_based_membership_type, "
    "create_calculator_dues_schedule) write to fields that no longer exist on Membership Type. "
    "Re-enable after rewriting helpers against the new template-based schema. See "
    "docs/plans/2026-05-27-test-failure-triage-plan.md (Bucket B - schema dead)."
)


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
