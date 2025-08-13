from frappe import _


def get_data():
    return {
        "fieldname": "sepa_mandate",
        "non_standard_fieldnames": {"Direct Debit Invoice": "mandate_reference", "Payment Entry": "remarks"},
        "transactions": [
            {"label": _("Direct Debit"), "items": ["Direct Debit Batch", "SEPA Payment Retry"]},
            {"label": _("Payments"), "items": ["Payment Entry", "Sales Invoice"]},
        ],
        "reports": [
            {
                "label": "Mandate Usage Report",
                "route": "query-report/Mandate Usage Report",
                "filters": {"sepa_mandate": "{name}"},
            }
        ],
    }
