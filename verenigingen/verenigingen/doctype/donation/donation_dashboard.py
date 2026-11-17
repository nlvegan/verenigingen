from frappe import _


def get_data():
    return {
        "fieldname": "donation",
        "non_standard_fieldnames": {"Payment Entry": "custom_donation"},
        "transactions": [{"label": _("Payment"), "items": ["Payment Entry"]}],
    }
