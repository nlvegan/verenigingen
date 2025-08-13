"""Dashboard configuration for Verenigingen"""

from frappe import _


def get_data():
    return {
        "heatmap": True,
        "heatmap_message": _(
            "This is based on the transactions against this Member. See timeline below for details"
        ),
        "fieldname": "member",
        "transactions": [
            {"label": _("Memberships"), "items": ["Membership"]},
            {"label": _("Payments"), "items": ["Payment Entry", "SEPA Direct Debit"]},
        ],
    }


# Custom dashboard chart sources
dashboard_charts = {
    "Member Age Distribution": "verenigingen.config.dashboard_charts.get_member_age_distribution"
}
