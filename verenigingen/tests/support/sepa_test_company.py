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
Sales Invoice save. ``TEST-Payment-Integration-Company`` is the app's own EUR
test company and is the sole company scoped to the current ``FY-2026`` fiscal
year; the ERPNext ``_Test Company 2`` is EUR but has no current Fiscal Year.
"""

import frappe
from frappe.utils import getdate, today

# The app's EUR test company, scoped to the current fiscal year. Preferred.
_PREFERRED_EUR_COMPANY = "TEST-Payment-Integration-Company"


def get_eur_test_company() -> str:
    """Return a EUR company that also has an active Fiscal Year for today.

    Prefers ``TEST-Payment-Integration-Company`` (EUR + current FY); otherwise
    falls back to the first EUR company whose Fiscal Year covers today --
    EXCLUDING erpnext's volatile ``_Test Company*`` defaults (see the loop comment);
    otherwise CREATES the preferred company (get-or-create). The company used to be created
    only as a side effect of one e_boekhouden test, so SEPA tests raised
    RuntimeError on any shard/order where that test had not run first. Creating it
    on demand here makes SEPA tests self-sufficient regardless of suite ordering.
    """
    if _company_is_eur_with_current_fy(_PREFERRED_EUR_COMPANY):
        return _PREFERRED_EUR_COMPANY

    for company in frappe.get_all("Company", filters={"default_currency": "EUR"}, pluck="name"):
        # Never borrow erpnext's own default companies (_Test Company /
        # _Test Company 2). They share the current calendar-year Fiscal Year, and
        # erpnext's lazy make_test_records rewrites that FY's company restrictions
        # on the FIRST dated Sales Invoice of a shard -- re-scoping it to
        # _Test Company and excluding the others. A shard that resolves to
        # _Test Company 2 here BEFORE that rewrite then fails mid-submit with
        # "Date <today> is not in any active Fiscal Year for _Test Company 2": an
        # order-dependent flake that passes in isolation but fails on some shard
        # orderings. _create_eur_test_company() builds
        # TEST-Payment-Integration-Company with its OWN dedicated FY that erpnext
        # never touches, so it resolves deterministically regardless of suite order.
        if company.startswith("_Test Company"):
            continue
        if _company_is_eur_with_current_fy(company):
            return company

    return _create_eur_test_company()


def _create_eur_test_company() -> str:
    """Get-or-create the EUR test company with a Fiscal Year covering today.

    Mirrors the company that test_e_boekhouden_migration_integration builds, but
    makes it available to any SEPA test. ERPNext creates a default Chart of
    Accounts on company insert, so the standard Receivable/Payable/Income accounts
    exist afterwards.
    """
    company_name = _PREFERRED_EUR_COMPANY

    if not frappe.db.exists("Company", company_name):
        company = frappe.new_doc("Company")
        company.company_name = company_name
        company.abbr = "TPIC"
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
    return company_name


def _ensure_current_fiscal_year(company_name: str) -> None:
    """Ensure a Fiscal Year covering today exists, scoped to ``company_name`` alone.

    The app's EUR test company gets its OWN dedicated, single-company Fiscal Year
    (``FY-<abbr>-<year>``) rather than sharing the generic ``FY-<year>``. Two
    reasons make the dedicated, scoped FY the correct design rather than a shared
    or unrestricted one:

    1. **Scoping is mandatory, not optional.** ``FY-<year>`` overlaps erpnext's
       default ``<year>`` Fiscal Year on dates. erpnext's overlap guard rejects two
       overlapping Fiscal Years unless each is restricted to specific companies, so
       an unrestricted (empty ``companies``) FY cannot coexist with the default one.

    2. **Sharing one FY across tests is the root of the flake.** Other tests (e.g.
       ``test_erpnext_integration_comprehensive``) append THEIR companies to the
       shared ``FY-<year>`` and leave dangling ``companies`` rows when those
       companies roll back; re-saving the shared FY later then fails
       ``_validate_links`` with an order-dependent ``LinkValidationError``. A
       Fiscal Year that only this company ever touches sidesteps the whole class.

    While erpnext's default ``<year>`` FY stays unrestricted it covers every company
    (so ``get_fiscal_year(company)`` resolves to it); once erpnext's lazy
    ``make_test_records`` re-scopes ``<year>`` to ``_Test Company`` on a shard's
    first dated invoice, ``get_fiscal_year`` falls back to this dedicated FY.
    """
    year = getdate().year
    abbr = frappe.db.get_value("Company", company_name, "abbr") or company_name
    fy_name = f"FY-{abbr}-{year}"

    if frappe.db.exists("Fiscal Year", fy_name):
        return

    fy = frappe.new_doc("Fiscal Year")
    fy.year = fy_name
    fy.year_start_date = f"{year}-01-01"
    fy.year_end_date = f"{year}-12-31"
    fy.append("companies", {"company": company_name})
    fy.insert(ignore_permissions=True)


def _company_is_eur_with_current_fy(company: str) -> bool:
    if frappe.db.get_value("Company", company, "default_currency") != "EUR":
        return False
    from erpnext.accounts.utils import get_fiscal_year

    try:
        get_fiscal_year(date=today(), company=company, as_dict=True)
        return True
    except Exception:
        return False


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
