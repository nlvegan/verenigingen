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
from frappe.utils import today

# The app's EUR test company, scoped to the current fiscal year. Preferred.
_PREFERRED_EUR_COMPANY = "TEST-Payment-Integration-Company"


def get_eur_test_company() -> str:
    """Return a EUR company that also has an active Fiscal Year for today.

    Prefers ``TEST-Payment-Integration-Company`` (EUR + current FY); otherwise
    falls back to the first EUR company whose Fiscal Year covers today.
    """
    if _company_is_eur_with_current_fy(_PREFERRED_EUR_COMPANY):
        return _PREFERRED_EUR_COMPANY

    for company in frappe.get_all("Company", filters={"default_currency": "EUR"}, pluck="name"):
        if _company_is_eur_with_current_fy(company):
            return company

    raise RuntimeError(
        "No EUR company with an active Fiscal Year for today was found for SEPA "
        "tests. SEPA invoice validation requires EUR and Sales Invoice save "
        "requires a current Fiscal Year."
    )


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
