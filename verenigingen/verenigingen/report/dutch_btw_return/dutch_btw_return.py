# Create a report for BTW returns
# verenigingen/verenigingen/report/dutch_btw_return/dutch_btw_return.py

from __future__ import unicode_literals

from frappe import _
from frappe.utils import flt, getdate

from verenigingen.utils import generate_btw_report


def execute(filters=None):
    if not filters:
        filters = {}

    columns = get_columns()
    data = get_data(filters)

    return columns, data


def get_columns():
    return [
        {"fieldname": "box", "label": _("BTW Box"), "fieldtype": "Data", "width": 100},
        {"fieldname": "description", "label": _("Description"), "fieldtype": "Data", "width": 400},
        {"fieldname": "amount", "label": _("Amount (EUR)"), "fieldtype": "Currency", "width": 150},
    ]


def get_data(filters):
    start_date = getdate(filters.get("from_date"))
    end_date = getdate(filters.get("to_date"))

    report_data = generate_btw_report(start_date, end_date)

    # Format for display
    result = []

    # Box descriptions
    descriptions = {
        "1a": _("Supplies/services at standard rate"),
        "1b": _("Supplies/services at reduced rate"),
        "1c": _("Supplies/services at other rates"),
        "1d": _("Private use"),
        "1e": _("Supplies/services - Import threshold"),
        "2a": _("VAT at standard rate"),
        "2b": _("VAT at reduced rate"),
        "2c": _("VAT at other rates"),
        "2d": _("VAT on private use"),
        "2e": _("VAT Import threshold"),
        "3": _("Supplies/services to foreign countries"),
        "4a": _("Supplies to EU countries"),
        "4b": _("Supplies to non-EU countries"),
        "5a": _("Input VAT"),
        "5b": _("VAT shifted to you"),
        "5c": _("Import"),
        "5d": _("Small Business Scheme (KOR)"),
        "total": _("Total Amount"),
    }

    # Add rows for each box
    for box, amount in report_data.items():
        result.append({"box": box, "description": descriptions.get(box, ""), "amount": flt(amount, 2)})

    return result
