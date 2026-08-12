"""Own `Verenigingen Settings.company` for the duration of a test.

Why this exists
---------------
A lot of production code resolves "which company" from the
`Verenigingen Settings` single rather than from its arguments —
`sepa_config_manager.get_company_sepa_config()`, `chapter_finance_service`,
`invoice_generator`, `department_sync_service`, `user_role_profile_calculator`
and others. A test whose fixtures live under the harness company therefore
fails unless that single agrees with them:

    Cost Center: Test Amsterdam 32a9 - Chapter - _TC2 does not belong to the
        Company: _Test Company
    Row 1: The Income Account Test Sales Income - _TC does not belong to the
        company _Test Company 2
    Party Account Debtors - _TC2 currency (EUR) and document currency (INR)
        should be same

`EnhancedTestCase` sets that single in `setUp` (via `_ensure_master_data`).
`VereningingenTestCase` never did — so its tests passed only when an
`EnhancedTestCase` test had run earlier **in the same shard** and left the
value behind, because the restore that was supposed to undo it was addressing
the wrong object and never ran (#312).

That is the #308 anti-pattern in its purest form: a test resolving a shared
fixture by reading what another test happened to leave, rather than owning it.
Fixing the restore is what exposed it — five tests across three CI shards, and
more locally, since which tests break depends on shard composition.

So each test now pins the value it needs and puts back what it found. The value
pinned is the harness-owned company, which is what the leak had been supplying
all along — the difference is that it is now deterministic and does not depend
on what ran first.

Why `addCleanup` and not `tearDown`
-----------------------------------
`VereningingenTestCase.tearDown` rolls back *before* each tracked delete and
commits *after*, so a restore written into `tearDown` is discarded while a pin
written in `setUp` becomes durable — the worst of both. `addCleanup` callbacks
run before that machinery, and the explicit commit here makes the restore
survive it.
"""

import frappe

SETTINGS = "Verenigingen Settings"


def own_settings_company(test_case, company: str | None = None) -> str | None:
    """Pin `Verenigingen Settings.company` for this test, restoring it after.

    Args:
        test_case: the running test; its `addCleanup` is used for the restore.
        company: company to pin. Defaults to the harness-owned company, which
            is what `EnhancedTestCase` pins and therefore what the previously
            leaked value was.

    Returns the pinned company, or None if no harness company exists (in which
    case nothing is changed — a site without one has bigger problems, and this
    helper is not the place to report them).
    """
    company = company or _harness_company()
    if not company:
        return None

    previous = frappe.db.get_value(SETTINGS, None, "company")
    if previous == company:
        return company

    _set_company(company)
    test_case.addCleanup(_set_company, previous)
    return company


def _set_company(company: str | None) -> None:
    frappe.db.set_value(SETTINGS, None, "company", company, update_modified=False)
    # Commit: the pin has to be visible to production code that reads the single
    # through a fresh document load, and the restore has to survive the rollback
    # in the base tearDown.
    frappe.db.commit()


def _harness_company() -> str | None:
    """The same company `EnhancedTestCase._get_test_company()` would choose.

    Imported here rather than at module scope so `tests/utils/base` does not
    pull in the whole Enhanced harness just to read a tuple of names — and
    imported rather than copied because a copy of this list drifts silently.
    The first draft of this file hardcoded a guess and got two of three names
    wrong, which would have selected a company the harness does not own.
    """
    from verenigingen.tests.fixtures.enhanced_test_factory import HARNESS_OWNED_COMPANIES

    for candidate in HARNESS_OWNED_COMPANIES:
        if frappe.db.exists("Company", candidate):
            return candidate
    return None
