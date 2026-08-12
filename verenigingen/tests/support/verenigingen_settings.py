"""Own the `Verenigingen Settings` company for the duration of a test class.

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
Fixing the restore is what exposed it — five tests across three CI shards.

Both singles, not one
---------------------
`invoice_generator._get_income_account` returns `dues_income_account` if the
Account merely *exists*; it never checks whose company it belongs to. So
pinning `company` alone reproduces the second error quoted above on any site
whose `dues_income_account` belongs to someone else. The pair moves together
or not at all.

Why class scope, and why that matters
-------------------------------------
This pins in `setUpClass` and restores in `addClassCleanup`, NOT per test.

`VereningingenTestCase` extends the compat `FrappeTestCase`
(`frappe/deprecation_dumpster.py`), which defines no `setUp`/`tearDown` and
whose only rollback is a single `addClassCleanup(_rollback_db)`. Writing the
pin per test therefore meant a `frappe.db.commit()` in `setUp` and another in
the cleanup, neither preceded by a rollback — which would make every row a test
created without tracking it **durable** instead of discarded at class cleanup.
That is a worse isolation guarantee than doing nothing at all, in a base class
the whole suite inherits.

`FrappeTestCase.setUpClass` already commits at exactly this point, so pinning
here adds no new commit boundary.

Reproducing the bug this fixes
------------------------------
All test sites already carry the leaked value (`company = _Test Company`), so
the pin is a no-op there and its absence proves nothing. To see it work, point
the single somewhere else first::

    bench --site test_site_2 console
    >>> frappe.db.set_value("Verenigingen Settings", None, "company", "_Test Company 2")
    >>> frappe.db.commit()

then run e.g. `verenigingen.tests.backend.components.test_enhanced_sepa_processing`:
red on develop, green here.
"""

import frappe

SETTINGS = "Verenigingen Settings"
PAYMENT_SETTINGS = "Verenigingen Payments Settings"


def own_settings_company(test_class, company: str | None = None) -> str | None:
    """Pin the settings company for `test_class`, restoring what was there after.

    Args:
        test_class: the test CLASS (called from `setUpClass`); its
            `addClassCleanup` is used for the restore.
        company: company to pin. Defaults to the harness-owned company, which
            is what `EnhancedTestCase` pins and therefore what the previously
            leaked value was.

    Returns the pinned company, or None if no harness company exists — a site
    without one has bigger problems, and this helper is not where they should
    be reported.
    """
    company = company or _harness_company()
    if not company:
        return None

    previous = (
        frappe.db.get_value(SETTINGS, None, "company"),
        frappe.db.get_value(PAYMENT_SETTINGS, None, "dues_income_account"),
    )
    # Registered even when the values already match, so that a test body which
    # changes them still gets them put back. Skipping the cleanup when the
    # current value happens to be right is order-dependent behaviour in a helper
    # written to remove order dependence.
    test_class.addClassCleanup(_write, *previous)

    _write(company, _income_account_for(company) or previous[1])
    return company


def _write(company: str | None, dues_income_account: str | None) -> None:
    frappe.db.set_value(SETTINGS, None, "company", company, update_modified=False)
    frappe.db.set_value(
        PAYMENT_SETTINGS, None, "dues_income_account", dues_income_account, update_modified=False
    )
    # Commit: production code reads these through a fresh single load, and the
    # restore has to outlive the class-level rollback.
    frappe.db.commit()


def _income_account_for(company: str) -> str | None:
    """A leaf income account belonging to `company`.

    Matched on `root_type`, not `account_type`: income accounts carry
    `root_type = "Income"` and leave `account_type` empty.
    """
    return frappe.db.get_value(
        "Account", {"company": company, "root_type": "Income", "is_group": 0}, "name"
    )


def _harness_company() -> str | None:
    """The harness-owned company, per `HARNESS_OWNED_COMPANIES`.

    Imported lazily so `tests/utils/base` does not pull in the whole Enhanced
    harness at module scope, and imported rather than copied because a copy of
    that list drifts silently — the first draft of this file hardcoded a guess
    and got two of the three names wrong, which would have pinned a company the
    harness does not own.

    Note this is NOT identical to `EnhancedTestCase._get_test_company()`: that
    also honours `frappe.local.test_company_name` and ensures the company has a
    usable chart of accounts. Nothing else writes that attribute today, but the
    chart-of-accounts guarantee is genuinely absent here.
    """
    from verenigingen.tests.fixtures.enhanced_test_factory import HARNESS_OWNED_COMPANIES

    for candidate in HARNESS_OWNED_COMPANIES:
        if frappe.db.exists("Company", candidate):
            return candidate
    return None
