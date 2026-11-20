"""Selling price list for production-built Sales Invoices (#2810).

`frappe.new_doc("Sales Invoice")` fills the site's global default selling price
list. When that list's currency differs from the company currency, erpnext's
`set_price_list_currency` fetches a live exchange rate, which it refuses unless
the session user is a System User (webhook and guest flows are not).
Builders therefore pin a list in the company currency with this helper.
"""

import frappe


def get_selling_price_list_for_currency(currency, customer=None):
    """Return an enabled selling Price List name in `currency`.

    Order (maintainer ruling on #2810): (1) the customer's `default_price_list`
    when it is an enabled selling list in `currency`; (2) the first enabled
    selling list in `currency` by name; (3) a created "Standard Selling <currency>".
    """
    if customer:
        default = frappe.db.get_value("Customer", customer, "default_price_list")
        if default and _is_usable_selling_list(default, currency):
            return default

    existing = frappe.db.get_value(
        "Price List",
        {"currency": currency, "selling": 1, "enabled": 1},
        "name",
        order_by="name asc",
    )
    return existing or _create_selling_price_list(currency)


def get_selling_price_list_for_company(company, customer=None):
    return get_selling_price_list_for_currency(
        frappe.get_cached_value("Company", company, "default_currency"), customer
    )


def _is_usable_selling_list(name, currency):
    return bool(
        frappe.db.exists("Price List", {"name": name, "currency": currency, "selling": 1, "enabled": 1})
    )


def _create_selling_price_list(currency):
    name = f"Standard Selling {currency}"
    if not frappe.db.exists("Price List", name):
        # Security: the caller may be a webhook/guest user; this is shared master data the
        # invoice builder needs in order to price in the company currency.
        frappe.get_doc(
            {
                "doctype": "Price List",
                "price_list_name": name,
                "currency": currency,
                "selling": 1,
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
    return name
