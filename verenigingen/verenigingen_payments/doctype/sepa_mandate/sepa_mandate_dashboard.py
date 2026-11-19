import frappe


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
    #
    # "Payment Entry" is absent for the same reason (#1318): it was mapped via
    # `remarks`, ERPNext's free-text narrative, which never holds a mandate name.
    # Payment Entry has no field that holds a SEPA Mandate; its only SEPA field,
    # `custom_sepa_batch`, links to a Direct Debit Batch, which reaches a mandate
    # only through the mandate_id on a child row.
    #
    # "Donation" is present (#2738, maintainer ruling 2026-11-19): `Donation.sepa_mandate`
    # is a real Link to SEPA Mandate holding the mandate's docname, and its name is this
    # dashboard's default `fieldname`, so no `non_standard_fieldnames` entry is needed.
    # The group is offered only to a viewer who can read Donation (maintainer ruling
    # 2026-11-19): Frappe counts connections with `frappe.get_all`, which ignores the
    # viewer's permissions, so a Staff user (may read SEPA Mandate, not Donation) would
    # otherwise see how many Donations a mandate has. This function runs per request.
    return {
        "fieldname": "sepa_mandate",
        "transactions": _donation_transactions(),
        "reports": [
            {
                "label": "Mandate Usage Report",
                "route": "query-report/Mandate Usage Report",
                "filters": {"sepa_mandate": "{name}"},
            }
        ],
    }


def _donation_transactions():
    """The Donations group, or nothing when the session user cannot read Donation.
    Fails closed: if the permission check itself errors, the group is withheld."""
    try:
        can_read_donations = frappe.has_permission("Donation", "read")
    except Exception:  # swallow-ok: best-effort (fail closed: [] withholds the group; logged below)
        frappe.log_error(
            title="SEPA Mandate dashboard: Donation permission check failed",
            message=frappe.get_traceback(),
        )
        return []
    return [{"label": "Donations", "items": ["Donation"]}] if can_read_donations else []
