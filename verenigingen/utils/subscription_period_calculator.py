"""
Utility functions for calculating subscription periods to ensure proper alignment
between application invoices and regular subscription invoices.
"""

from datetime import timedelta

import frappe
from frappe.utils import add_days, add_months, getdate


def calculate_subscription_period_dates(start_date, membership_type):
    """
    Calculate proper subscription period start and end dates based on membership type.

    Args:
        start_date: The membership start date
        membership_type: MembershipType document or name

    Returns:
        dict: {
            'period_start': start date of the subscription period,
            'period_end': end date of the subscription period,
            'billing_interval': billing interval (Month, Quarter, Year),
            'billing_interval_count': number of intervals,
            'next_period_start': start date of the next billing period
        }
    """

    if isinstance(membership_type, str):
        membership_type = frappe.get_doc("Membership Type", membership_type)

    start_date = getdate(start_date)

    # Map subscription periods to billing intervals and counts
    period_mapping = {
        "Daily": {"interval": "Day", "count": 1, "days": 1},
        "Monthly": {"interval": "Month", "count": 1},
        "Quarterly": {"interval": "Month", "count": 3},
        "Biannual": {"interval": "Month", "count": 6},
        "Annual": {"interval": "Month", "count": 12},
        "Lifetime": {"interval": "Month", "count": 12},  # Treat as annual for billing
        "Custom": {"interval": "Month", "count": membership_type.subscription_period_in_months or 1},
    }

    period_config = period_mapping.get(membership_type.subscription_period, {"interval": "Month", "count": 1})

    # Calculate period end date
    if period_config["interval"] == "Month":
        period_end = add_months(start_date, period_config["count"]) - timedelta(days=1)
        next_period_start = add_months(start_date, period_config["count"])
    elif period_config["interval"] == "Day":
        # For daily intervals
        days_to_add = period_config.get("days", 1) * period_config["count"]
        period_end = add_days(start_date, days_to_add - 1)
        next_period_start = add_days(start_date, days_to_add)
    else:
        # Fallback for other intervals
        period_end = add_days(start_date, 30 * period_config["count"]) - timedelta(days=1)
        next_period_start = add_days(start_date, 30 * period_config["count"])

    return {
        "period_start": start_date,
        "period_end": period_end,
        "billing_interval": period_config["interval"],
        "billing_interval_count": period_config["count"],
        "next_period_start": next_period_start,
        "subscription_period": membership_type.subscription_period,
    }


def get_aligned_subscription_dates(membership_start_date, membership_type, has_application_invoice=True):
    """
    Get properly aligned subscription dates for both application invoice and regular subscriptions.

    Args:
        membership_start_date: Date when membership starts
        membership_type: MembershipType document or name
        has_application_invoice: Whether an application invoice will be created

    Returns:
        dict: {
            'application_invoice_period': {start, end} for first invoice,
            'subscription_start_date': when regular subscription should start,
            'billing_info': billing interval information
        }
    """

    period_info = calculate_subscription_period_dates(membership_start_date, membership_type)

    if has_application_invoice:
        # Application invoice covers the first billing period
        return {
            "application_invoice_period": {
                "start": period_info["period_start"],
                "end": period_info["period_end"],
            },
            "subscription_start_date": period_info["next_period_start"],
            "billing_info": {
                "interval": period_info["billing_interval"],
                "interval_count": period_info["billing_interval_count"],
                "subscription_period": period_info["subscription_period"],
            },
        }
    else:
        # No application invoice, subscription starts immediately
        return {
            "application_invoice_period": None,
            "subscription_start_date": period_info["period_start"],
            "billing_info": {
                "interval": period_info["billing_interval"],
                "interval_count": period_info["billing_interval_count"],
                "subscription_period": period_info["subscription_period"],
            },
        }


def format_subscription_period_description(period_start, period_end, subscription_period):
    """
    Format a user-friendly description of the subscription period.

    Args:
        period_start: Start date of the period
        period_end: End date of the period
        subscription_period: Type of subscription (Monthly, Annual, etc.)

    Returns:
        str: Formatted description
    """

    start_str = period_start.strftime("%d %B %Y")
    end_str = period_end.strftime("%d %B %Y")

    if subscription_period == "Daily":
        return f"Daily membership ({start_str} - {end_str})"
    elif subscription_period == "Monthly":
        return f"Monthly membership ({start_str} - {end_str})"
    elif subscription_period == "Quarterly":
        return f"Quarterly membership ({start_str} - {end_str})"
    elif subscription_period == "Annual":
        return f"Annual membership ({start_str} - {end_str})"
    elif subscription_period == "Biannual":
        return f"Bi-annual membership ({start_str} - {end_str})"
    elif subscription_period == "Lifetime":
        return f"Lifetime membership (starting {start_str})"
    else:
        return f"Membership period ({start_str} - {end_str})"


@frappe.whitelist()
def test_subscription_period_calculation():
    """Test function to verify subscription period calculations"""

    from frappe.utils import today

    # Get available membership types
    membership_types = frappe.get_all("Membership Type", fields=["name", "subscription_period"])

    test_results = []
    test_start_date = today()

    for mt in membership_types:
        try:
            period_info = calculate_subscription_period_dates(test_start_date, mt.name)
            aligned_dates = get_aligned_subscription_dates(test_start_date, mt.name, True)

            test_results.append(
                {
                    "membership_type": mt.name,
                    "subscription_period": mt.subscription_period,
                    "calculated_period": {
                        "start": str(period_info["period_start"]),
                        "end": str(period_info["period_end"]),
                        "next_start": str(period_info["next_period_start"]),
                    },
                    "application_invoice_period": {
                        "start": str(aligned_dates["application_invoice_period"]["start"]),
                        "end": str(aligned_dates["application_invoice_period"]["end"]),
                    },
                    "subscription_start": str(aligned_dates["subscription_start_date"]),
                    "billing_info": aligned_dates["billing_info"],
                }
            )

        except Exception as e:
            test_results.append({"membership_type": mt.name, "error": str(e)})

    return {"success": True, "test_date": test_start_date, "results": test_results}
