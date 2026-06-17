"""
Fixtures for Mollie payment-entry factory / processor integration tests.

These helpers create the master data (a "Mollie" bank GL Account, Donor, Donation,
Customer links) that the PaymentEntryFactory and payment processors need to build
real Payment Entries and Bank Transactions against REAL accounts/parties.

The ``ignore_permissions`` inserts live here (a fixtures module) so they are a
recognised setup pattern and never appear in test bodies, per the test-quality
enforcer.
"""

import frappe

from verenigingen.utils.bank_utils import get_or_create_unknown_bank


def get_test_company():
    """Resolve the company the factory will use (mirrors the production resolver)."""
    from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

    try:
        company = get_mollie_config().get_default_company()
    except Exception:
        company = None
    return company or frappe.get_list("Company", limit=1)[0].name


def ensure_mollie_bank_gl_account(company=None):
    """Ensure a GL Account named 'Mollie' (Bank type) exists for the company.

    The PaymentEntryFactory._get_accounts resolves the Mollie bank account via the
    fallback ``frappe.get_value("Account", {"company": ..., "account_name": "Mollie"})``
    when ``mollie_bank_account`` is not configured in settings. Creating it lets the
    factory create real Payment Entries end-to-end.

    Returns the Account name (e.g. ``Mollie - _TC``).
    """
    company = company or get_test_company()
    existing = frappe.db.get_value("Account", {"company": company, "account_name": "Mollie"}, "name")
    if existing:
        return existing

    # Find a Bank-type group to parent under, else any Asset group.
    parent = (
        frappe.db.get_value("Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name")
        or frappe.db.get_value(
            "Account", {"company": company, "account_name": ["like", "%Bank%"], "is_group": 1}, "name"
        )
        or frappe.db.get_value("Account", {"company": company, "root_type": "Asset", "is_group": 1}, "name")
    )
    if not parent:
        return None

    acct = frappe.get_doc(
        {
            "doctype": "Account",
            "account_name": "Mollie",
            "company": company,
            "parent_account": parent,
            "account_type": "Bank",
            "is_group": 0,
        }
    )
    acct.insert(ignore_permissions=True)
    return acct.name


def ensure_mollie_mode_of_payment():
    """Ensure the 'Mollie' Mode of Payment exists (factory checks for it)."""
    if frappe.db.exists("Mode of Payment", "Mollie"):
        return "Mollie"
    mop = frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": "Mollie", "type": "Bank"})
    mop.insert(ignore_permissions=True)
    return mop.name


def ensure_bank_account_for_company(company=None):
    """Ensure a usable Bank Account doc exists for the company (for Bank Transactions)."""
    company = company or get_test_company()
    existing = frappe.db.get_value("Bank Account", {"company": company}, "name")
    if existing:
        return existing

    gl_account = ensure_mollie_bank_gl_account(company) or frappe.db.get_value(
        "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
    )
    if not gl_account:
        return None

    ba = frappe.get_doc(
        {
            "doctype": "Bank Account",
            "account_name": f"Mollie Test {frappe.generate_hash()[:6]}",
            "bank": get_or_create_unknown_bank(),
            "account": gl_account,
            "company": company,
        }
    )
    ba.insert(ignore_permissions=True)
    return ba.name


def ensure_service_item():
    """Ensure a non-stock service Item exists for building Sales Invoices."""
    item_code = "Mollie Test Membership Dues"
    if frappe.db.exists("Item", item_code):
        return item_code
    group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or frappe.db.get_value(
        "Item Group", {}, "name"
    )
    item = frappe.get_doc(
        {
            "doctype": "Item",
            "item_code": item_code,
            "item_name": item_code,
            "item_group": group,
            "is_stock_item": 0,
            "is_sales_item": 1,
            "stock_uom": frappe.db.get_value("UOM", {"name": "Nos"}, "name")
            or frappe.db.get_value("UOM", {}, "name"),
        }
    )
    item.insert(ignore_permissions=True)
    return item.name


def customer_for_member(member_doc):
    """Return the Customer linked to a Member.

    ``Member.after_insert`` already auto-creates+links a Customer when the member
    has an email, so in tests we just read it back. If for some reason the link is
    missing, fall back to creating one.
    """
    existing = frappe.db.get_value("Member", member_doc.name, "customer")
    if existing:
        return existing

    company = get_test_company()
    customer = frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": member_doc.full_name or f"Member {member_doc.name}",
            "customer_type": "Individual",
            "company": company,
            "member": member_doc.name,
        }
    )
    customer.insert(ignore_permissions=True)
    frappe.db.set_value("Member", member_doc.name, "customer", customer.name)
    member_doc.reload()
    return customer.name
