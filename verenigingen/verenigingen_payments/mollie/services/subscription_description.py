"""
Canonical Mollie subscription description for members.

The template lives on Verenigingen Payments Settings
(`mollie_subscription_description_template`, placeholders MEMBER_ID and
MEMBER_NAME) - the same field the payment dashboard's manual-transfer
reference renders, and the format live subscriptions were created with.
Creation and PATCH paths must build descriptions through this helper so
they cannot drift apart again.
"""

import frappe

DEFAULT_TEMPLATE = "Contribution payment for member MEMBER_ID"


def get_member_subscription_description(member) -> str:
    """Render the canonical subscription description for a Member document."""
    template = (
        frappe.db.get_single_value(
            "Verenigingen Payments Settings", "mollie_subscription_description_template"
        )
        or DEFAULT_TEMPLATE
    )
    return template.replace("MEMBER_NAME", member.full_name or "").replace(
        "MEMBER_ID", str(member.member_id or member.name)
    )
