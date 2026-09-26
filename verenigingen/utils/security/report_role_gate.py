"""Shared guard for a whitelisted API that wraps a Script Report's get_data()
directly.

A Report's own "Report Role" list (the `roles` child table on the Report
doctype) is what Desk checks -- via Report.is_permitted() -- before it lets a
user open that report at all. An API endpoint that imports the report
module's get_data() and calls it directly bypasses that check entirely: it is
gated only by whatever @standard_api/@high_security_api tier decorates the
endpoint, which is typically wider (e.g. the generic MEDIUM
@standard_api(REPORTING) tier, cleared by "Verenigingen Volunteer" and
"Verenigingen Chapter Board Member" alike) than the report's own, narrower
role list (#1486).

ensure_report_role_access() closes that gap by reusing the report's own role
list (via frappe.core's Report.is_permitted(), which also honours a Custom
Role override) rather than a second, possibly-diverging hardcoded list.
"""

import frappe


def ensure_report_role_access(report_name, denied_message):
    """Refuse the caller unless they hold at least one role from
    `report_name`'s own Report Role list.

    Args:
        report_name: The Report doctype record's name (e.g. "ANBI Periodic
            Agreements").
        denied_message: User-facing message for the PermissionError, already
            wrapped in frappe._() by the caller.
    """
    if not frappe.get_doc("Report", report_name).is_permitted():
        frappe.throw(denied_message, frappe.PermissionError)
