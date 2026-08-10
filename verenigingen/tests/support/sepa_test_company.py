"""Helpers for SEPA tests that require a EUR-denominated company.

``InvoiceManagementUtilities.validate_invoice_for_sepa`` rejects any invoice
whose currency is not EUR. The ERPNext test fixtures default to companies with
non-EUR currencies (``_Test Company`` is INR), so a Sales Invoice created under
the default company is rejected by the Direct Debit Batch validation, surfacing
as "No valid invoices found in batch" / the F3001 "Negative batch total amount
calculated" error. SEPA tests must therefore create their invoices under a EUR
company.

Besides EUR, the company must have an active Fiscal Year covering today's date,
or ``erpnext.accounts.utils.get_fiscal_year`` raises ``FiscalYearError`` on
Sales Invoice save -- AND a usable Chart of Accounts, without which a Sales
Invoice cannot resolve an Income Account or a Debit To account at all.
``TEST-Payment-Integration-Company`` is the app's own EUR test company, built
and repaired here so it satisfies all three regardless of what any other test
has created. ``_unusable_reasons`` is the single definition of "usable".
"""

import frappe
from frappe.utils import today

# The app's EUR test company, scoped to the current fiscal year. Preferred.
_PREFERRED_EUR_COMPANY = "TEST-Payment-Integration-Company"
# Kept beside the name because the two must move together: every account this
# company owns is suffixed with the abbreviation ("Debtors - TPIC"), and Company
# rejects an abbreviation another company already holds.
_PREFERRED_EUR_COMPANY_ABBR = "TPIC"


def get_eur_test_company() -> str:
    """Return ``TEST-Payment-Integration-Company``, creating or repairing it as needed.

    This helper OWNS its company; it never borrows another test's. An earlier
    version fell back to "the first EUR company whose Fiscal Year covers today",
    which is what broke CI when the shards were rebalanced by measured runtime
    (PR #237): two e_boekhouden tests deliberately build EUR companies with an
    EMPTY Chart of Accounts under ``ignore_chart_of_accounts`` --
    ``EBH Migration Test Co`` and ``EBH Account Migration Test Co`` -- and the
    borrow accepted them, because it checked only currency and fiscal year.

    Any shard that ran one of those e_boekhouden modules before a SEPA/payment
    module handed every later caller a company with no accounts at all, producing
    101 failures across two shards: "Income Account None cannot be same as Debit To
    (Party Account) None", "no parent account found for company ...",
    "[Account, Income - EBHMT]: parent_account", and "No parent bank account group
    configured in Verenigingen Settings". The borrow also defeated the very purpose
    this helper was written for -- being independent of suite ordering.
    """
    if _company_is_usable(_PREFERRED_EUR_COMPANY):
        return _PREFERRED_EUR_COMPANY

    return _create_eur_test_company()


def _create_eur_test_company() -> str:
    """Get-or-create the EUR test company, then repair and verify it.

    ERPNext creates a default Chart of Accounts on company insert, so the standard
    Receivable/Payable/Income/Bank accounts exist afterwards.

    Also the REPAIR path for an existing-but-unusable company: the insert is
    skipped when it already exists, but ``_ensure_current_fiscal_year`` below then
    restores the one failure mode that is genuinely recoverable (a missing or
    out-of-date Fiscal Year). Anything still wrong after that is a broken Chart of
    Accounts, which this helper will not silently paper over -- see the
    post-condition at the end.

    The ``frappe.db.commit()`` is pre-existing and fires at most once per site: the
    company persists for the rest of the run, so every later call short-circuits on
    the usability check in ``get_eur_test_company``.
    """
    company_name = _PREFERRED_EUR_COMPANY

    if not frappe.db.exists("Company", company_name):
        company = frappe.new_doc("Company")
        company.company_name = company_name
        company.abbr = _PREFERRED_EUR_COMPANY_ABBR
        company.default_currency = "EUR"
        company.country = "Netherlands"
        company.insert(ignore_permissions=True)

        receivable = frappe.db.get_value(
            "Account", {"company": company_name, "account_type": "Receivable", "is_group": 0}, "name"
        )
        payable = frappe.db.get_value(
            "Account", {"company": company_name, "account_type": "Payable", "is_group": 0}, "name"
        )
        if receivable:
            company.default_receivable_account = receivable
        if payable:
            company.default_payable_account = payable
        if receivable or payable:
            company.save(ignore_permissions=True)

    _ensure_current_fiscal_year(company_name)
    frappe.db.commit()

    # Fail loudly rather than hand back a company that cannot back a Sales Invoice.
    # Returning one quietly is exactly what the old borrow did, and the resulting
    # errors surfaced hundreds of lines away in ERPNext with no mention of the
    # company that caused them.
    unusable = _unusable_reasons(company_name)
    if unusable:
        raise RuntimeError(
            f"{company_name} exists but cannot be used by SEPA/payment tests: "
            + "; ".join(unusable)
            + ". Its Chart of Accounts is missing or was wiped; delete the company "
            "and let this helper rebuild it."
        )
    return company_name


def _ensure_current_fiscal_year(company_name: str = None) -> None:
    """Ensure a Fiscal Year covering today exists and applies to ``company_name``.

    Delegates to the single canonical find-or-create-by-date helper,
    ``e_boekhouden...date_utils.ensure_fiscal_year_exists`` -- the same one
    ``tests.setup.ensure_test_fiscal_year_for_all_companies`` uses -- rather than
    maintaining a parallel, company-scoped ``FY-<abbr>-<year>`` creator.

    A dedicated per-company scoped FY was previously created here, but on erpnext
    v16 a scoped current-year FY collides with any other current-year FY under the
    stricter overlap guard ("overlapping with FY-..."), so two helpers creating FYs
    for the same year fought each other and left NO usable FY. Reusing one FY by
    date sidesteps the overlap, and -- because the canonical helper only appends a
    company to a *restricted* FY (a global, empty-``companies`` FY needs no row) --
    also avoids the dangling ``Fiscal Year Company`` rows a shared, appended-to FY
    used to leave on rollback.
    """
    from verenigingen.e_boekhouden.utils.consolidated.date_utils import (
        ensure_fiscal_year_exists,
    )

    company = (
        company_name
        or frappe.defaults.get_global_default("company")
        or frappe.db.get_value("Company", {}, "name")
    )
    ensure_fiscal_year_exists(today(), company)


def _company_is_usable(company: str) -> bool:
    return not _unusable_reasons(company)


def _unusable_reasons(company: str) -> list:
    """Return the reasons ``company`` cannot back a SEPA/payment test; empty if it can.

    Checking currency and fiscal year alone is what let a company with an EMPTY
    Chart of Accounts pass (see ``get_eur_test_company``), so each check below is
    tied to a failure actually observed in CI run 31168194632.
    """
    if not frappe.db.exists("Company", company):
        return [f"company {company!r} does not exist"]

    reasons = []
    defaults = frappe.db.get_value(
        "Company",
        company,
        ["default_currency", "default_receivable_account", "default_income_account"],
        as_dict=True,
    )

    if defaults.default_currency != "EUR":
        # InvoiceManagementUtilities.validate_invoice_for_sepa rejects non-EUR.
        reasons.append(f"default_currency is {defaults.default_currency!r}, not 'EUR'")

    # Sales Invoice resolves Income Account and Debit To from these two Company
    # fields. ERPNext only stamps them when it builds a Chart of Accounts, so a
    # company created under ``ignore_chart_of_accounts`` has both NULL -- which is
    # literally the "Income Account None cannot be same as Debit To (Party Account)
    # None" failure, 41 occurrences.
    for field in ("default_receivable_account", "default_income_account"):
        value = defaults.get(field)
        if not value:
            reasons.append(f"{field} is not set")
        elif not frappe.db.exists("Account", value):
            reasons.append(f"{field} points at missing account {value!r}")

    # Needed to PARENT a new income account, which the company defaults above do
    # not guarantee: "[Account, Income - EBHMT]: parent_account", 19 occurrences.
    # Must be matched on root_type, NOT account_type -- ERPNext stamps
    # account_type="Income Account" only on LEAF income accounts, so every group
    # income account has an empty account_type.
    if not frappe.db.get_value(
        "Account", {"company": company, "root_type": "Income", "is_group": 1}, "name"
    ):
        reasons.append("no is_group Income account to parent new income accounts under")

    # Needed to parent a new bank account: "no parent account found for company ..."
    # (22) and "No parent bank account group configured in Verenigingen Settings" (4).
    if not frappe.db.get_value(
        "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
    ):
        reasons.append("no is_group Bank account to parent new bank accounts under")

    # Without this erpnext.accounts.utils.get_fiscal_year raises on Sales Invoice save.
    from erpnext.accounts.utils import get_fiscal_year

    try:
        get_fiscal_year(date=today(), company=company, as_dict=True)
    except Exception:
        reasons.append(f"no active Fiscal Year covering {today()}")

    return reasons


def ensure_sepa_payment_terms_template() -> str:
    """Get-or-create the "SEPA Direct Debit" Payment Terms Template.

    Membership Dues Schedules (and the invoices generated from them) set
    ``payment_terms_template = "SEPA Direct Debit"``; on a fresh test site this
    master does not exist, so saving the schedule/invoice raises
    ``LinkValidationError: Could not find Payment Terms Template: SEPA Direct
    Debit``. Production sites get this master from setup/fixtures.
    """
    name = "SEPA Direct Debit"
    if frappe.db.exists("Payment Terms Template", name):
        return name

    template = frappe.new_doc("Payment Terms Template")
    template.template_name = name
    template.append(
        "terms",
        {
            "due_date_based_on": "Day(s) after invoice date",
            "credit_days": 14,
            "invoice_portion": 100,
        },
    )
    template.insert(ignore_permissions=True)
    frappe.db.commit()
    return name


def ensure_membership_dues_item(billing_frequency: str = "Daily") -> str:
    """Get-or-create the "Membership Dues - <frequency>" Item.

    Membership dues Sales Invoices reference an Item named after the billing
    frequency (e.g. "Membership Dues - Daily"). Production creates it on demand
    via MembershipDuesItemManager.ensure_item_exists(); tests that build such an
    invoice directly need it pre-created or they fail with "Could not find Row #1:
    Item: Membership Dues - <frequency>".
    """
    from verenigingen.services.billing.invoice_generator import MembershipDuesItemManager

    item_name = f"Membership Dues - {billing_frequency}"
    if frappe.db.exists("Item", item_name):
        return item_name

    # ensure_item_exists needs a company for the default accounts; the EUR test
    # company has a usable chart of accounts.
    company = get_eur_test_company()
    income_account = frappe.db.get_value(
        "Account",
        {"account_type": "Income Account", "company": company, "is_group": 0},
        "name",
    )
    MembershipDuesItemManager().ensure_item_exists(
        item_name=item_name, company=company, income_account=income_account
    )
    frappe.db.commit()
    return item_name
