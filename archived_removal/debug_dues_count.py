#!/usr/bin/env python3
"""
Debug API to check dues invoice generation counts
"""

from collections import defaultdict

import frappe
from frappe.utils import add_days, today


@frappe.whitelist()
def check_dues_schedules_today():
    """Check how many schedules should generate invoices today"""

    today_date = today()
    results = {
        "today": today_date,
        "today_schedules": [],
        "future_schedules_by_date": {},
        "total_due_within_30_days": 0,
        "problem_schedules": [],
    }

    # Check schedules with next_invoice_date = today
    today_schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"status": "Active", "auto_generate": 1, "is_template": 0, "next_invoice_date": today_date},
        fields=[
            "name",
            "member_name",
            "next_invoice_date",
            "dues_rate",
            "billing_frequency",
            "membership_type",
        ],
        order_by="member_name",
    )

    results["today_schedules"] = today_schedules

    # Check schedules due within the next 30 days (current generation window)
    future_schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={
            "status": "Active",
            "auto_generate": 1,
            "is_template": 0,
            "next_invoice_date": ["<=", add_days(today_date, 30)],
        },
        fields=["name", "member_name", "next_invoice_date", "dues_rate", "billing_frequency"],
        order_by="next_invoice_date",
    )

    results["total_due_within_30_days"] = len(future_schedules)

    # Group by next invoice date
    by_date = defaultdict(list)
    for s in future_schedules:
        by_date[str(s.next_invoice_date)].append(
            {
                "name": s.name,
                "member_name": s.member_name,
                "dues_rate": s.dues_rate,
                "billing_frequency": s.billing_frequency,
            }
        )

    results["future_schedules_by_date"] = dict(by_date)

    # Check for potential validation problems
    try:
        problem_schedules = frappe.db.sql(
            """
            SELECT mds.name, mds.member_name, mds.dues_rate, mds.membership_type,
                   mds.next_invoice_date,
                   COALESCE(template.minimum_amount, 0) as template_min
            FROM `tabMembership Dues Schedule` mds
            LEFT JOIN `tabMembership Type` mt ON mds.membership_type = mt.name
            LEFT JOIN `tabMembership Dues Schedule` template ON mt.dues_schedule_template = template.name
            WHERE mds.status = 'Active'
            AND mds.auto_generate = 1
            AND mds.is_template = 0
            AND mds.next_invoice_date <= %s
            AND mds.dues_rate < COALESCE(template.minimum_amount, 0)
            ORDER BY mds.next_invoice_date, mds.member_name
        """,
            [add_days(today_date, 30)],
            as_dict=True,
        )

        results["problem_schedules"] = problem_schedules

    except Exception as e:
        results["problem_schedules_error"] = str(e)

    return results


@frappe.whitelist()
def check_schedule_generation_eligibility():
    """Check which schedules can actually generate invoices"""

    today_date = today()
    results = {"today": today_date, "eligible_schedules": [], "blocked_schedules": [], "summary": {}}

    # Get all schedules due today or within generation window
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={
            "status": "Active",
            "auto_generate": 1,
            "is_template": 0,
            "next_invoice_date": ["<=", add_days(today_date, 30)],
        },
        fields=["name"],
        order_by="next_invoice_date",
    )

    eligible_count = 0
    blocked_count = 0

    for schedule_data in schedules[:20]:  # Check first 20 to avoid timeout
        try:
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_data.name)
            can_generate, reason = schedule.can_generate_invoice()

            schedule_info = {
                "name": schedule.name,
                "member_name": getattr(schedule, "member_name", "Unknown"),
                "next_invoice_date": str(schedule.next_invoice_date),
                "dues_rate": schedule.dues_rate,
                "billing_frequency": schedule.billing_frequency,
                "can_generate": can_generate,
                "reason": reason,
            }

            if can_generate:
                results["eligible_schedules"].append(schedule_info)
                eligible_count += 1
            else:
                results["blocked_schedules"].append(schedule_info)
                blocked_count += 1

        except Exception as e:
            blocked_count += 1
            results["blocked_schedules"].append(
                {"name": schedule_data.name, "error": str(e), "can_generate": False}
            )

    results["summary"] = {
        "total_checked": len(schedules[:20]),
        "eligible": eligible_count,
        "blocked": blocked_count,
        "total_schedules_in_window": len(schedules),
    }

    return results
