from frappe import _


def get_data():
    # "Direct Debit Batch" (and "SEPA Payment Retry", "Sales Invoice") are
    # deliberately absent from `transactions` (#1261): none of the three has a
    # `sepa_mandate` field (the default `fieldname` below), and Frappe's dashboard
    # always filters on this document's `name` -- but the only mandate-referencing
    # field in this data model, `Direct Debit Batch Invoice.mandate_reference`,
    # stores the mandate's `mandate_id`, never its `name`
    # (see direct_debit_batch.py::validate_sequence_types). Mapping it via
    # non_standard_fieldnames would therefore filter on the wrong value and always
    # return zero -- not a real connection, just a silent one instead of a crashing
    # one. There is no field anywhere that holds a SEPA Mandate's docname on any of
    # these three doctypes, so the items are dropped rather than "fixed" with a
    # mapping that could never match.
    return {
        "fieldname": "sepa_mandate",
        "non_standard_fieldnames": {"Payment Entry": "remarks"},
        "transactions": [
            {"label": _("Payments"), "items": ["Payment Entry"]},
        ],
        "reports": [
            {
                "label": "Mandate Usage Report",
                "route": "query-report/Mandate Usage Report",
                "filters": {"sepa_mandate": "{name}"},
            }
        ],
    }
