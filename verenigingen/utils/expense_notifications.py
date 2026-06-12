"""Expense-related notifications.

Backs the "Send Overdue Reminders" action on the Chapter Expense Report.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, escape_html, flt, fmt_money, formatdate, today

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api

# Mirrors the roles allowed on the Chapter Expense Report (its ref_doctype is
# Volunteer Expense, so board members run the report without direct Expense
# Claim permissions — gate on the same roles rather than Expense Claim perms to
# avoid locking those users out of the report's own action button).
_REMINDER_ROLES = (
    "System Manager",
    "Verenigingen Administrator",
    "Verenigingen Chapter Board Member",
)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def send_overdue_reminders(days_overdue: int = 7):
    """Email reminders to expense approvers about overdue pending Expense Claims.

    "Overdue" = a non-cancelled ERPNext Expense Claim still in approval_status
    "Draft" (awaiting the approver) whose posting_date is older than the cutoff.
    One email is sent per approver, summarising their outstanding claims.

    Args:
        days_overdue: Minimum age (days, by posting_date) for a pending claim to
            be considered overdue. Defaults to 7.

    Returns:
        dict: {success, claims_found, approvers_notified, unassigned, message}.
    """
    if not any(role in frappe.get_roles() for role in _REMINDER_ROLES):
        frappe.throw(_("You are not permitted to send expense reminders"))

    days_overdue = cint(days_overdue) or 7
    cutoff = add_days(today(), -days_overdue)

    claims = frappe.get_all(
        "Expense Claim",
        filters={
            "approval_status": "Draft",
            "docstatus": ["<", 2],
            "posting_date": ["<=", cutoff],
        },
        fields=[
            "name",
            "posting_date",
            "total_claimed_amount",
            "employee_name",
            "expense_approver",
        ],
        order_by="posting_date asc",
    )

    # Group overdue claims by their approver; claims without an approver can't be
    # reminded and are reported back separately.
    claims_by_approver = {}
    unassigned = 0
    for claim in claims:
        approver = claim.get("expense_approver")
        if not approver:
            unassigned += 1
            continue
        claims_by_approver.setdefault(approver, []).append(claim)

    for approver, approver_claims in claims_by_approver.items():
        _send_reminder_email(approver, approver_claims, days_overdue)

    approvers_notified = len(claims_by_approver)
    return {
        "success": True,
        "claims_found": len(claims),
        "approvers_notified": approvers_notified,
        "unassigned": unassigned,
        "message": _("Sent {0} reminder(s) covering {1} overdue expense claim(s)").format(
            approvers_notified, len(claims) - unassigned
        ),
    }


def _send_reminder_email(approver: str, claims: list, days_overdue: int) -> None:
    """Send a single approver a summary of their overdue pending claims."""
    rows = "".join(
        "<tr><td>{name}</td><td>{date}</td><td>{amount}</td><td>{claimant}</td></tr>".format(
            name=escape_html(claim["name"]),
            date=formatdate(claim["posting_date"]),
            amount=fmt_money(flt(claim.get("total_claimed_amount"))),
            claimant=escape_html(claim.get("employee_name") or ""),
        )
        for claim in claims
    )
    message = _(
        "<p>The following expense claim(s) have been awaiting your approval for" " more than {0} day(s):</p>"
    ).format(days_overdue) + (
        "<table border='1' cellpadding='6' cellspacing='0'>"
        "<tr><th>Expense Claim</th><th>Date</th><th>Amount</th><th>Claimant</th></tr>"
        f"{rows}</table>"
    )
    frappe.sendmail(
        recipients=[approver],
        subject=_("Reminder: {0} expense claim(s) awaiting your approval").format(len(claims)),
        message=message,
    )
