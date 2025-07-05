import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate


@frappe.whitelist()
def fix_subscription_dates(subscription_name=None):
    """Fix subscription date update issues"""

    if not subscription_name:
        subscription_name = "ACC-SUB-2025-00001"

    # Check permissions
    if not frappe.has_permission("Subscription", "write"):
        frappe.throw(_("You don't have permission to modify subscriptions"))

    try:
        # Get subscription
        sub = frappe.get_doc("Subscription", subscription_name)

        # Check if already fixed
        if sub.current_invoice_start and getdate(sub.current_invoice_start) >= getdate(nowdate()):
            return {"success": True, "message": f"Subscription {subscription_name} dates are already current"}

        # Calculate next period
        if sub.plans:
            plan = frappe.get_doc("Subscription Plan", sub.plans[0].plan)
            interval = plan.interval
            interval_count = plan.interval_count or 1
        else:
            interval = "Day"
            interval_count = 1

        # Calculate next dates
        if sub.current_invoice_end:
            next_start = add_days(sub.current_invoice_end, 1)
        else:
            next_start = nowdate()

        # Calculate end date
        if interval == "Day":
            next_end = add_days(next_start, interval_count - 1)
        elif interval == "Week":
            next_end = add_days(next_start, (7 * interval_count) - 1)
        elif interval == "Month":
            from dateutil.relativedelta import relativedelta

            next_end = add_days(next_start + relativedelta(months=interval_count), -1)
        elif interval == "Year":
            from dateutil.relativedelta import relativedelta

            next_end = add_days(next_start + relativedelta(years=interval_count), -1)
        else:
            next_end = next_start

        # Update using db.set_value to bypass validation
        frappe.db.set_value(
            "Subscription",
            subscription_name,
            {"current_invoice_start": next_start, "current_invoice_end": next_end},
            update_modified=True,
        )

        frappe.db.commit()

        return {
            "success": True,
            "message": f"Updated subscription {subscription_name} dates to {next_start} - {next_end}",
        }

    except Exception as e:
        frappe.log_error(f"Error fixing subscription {subscription_name}: {str(e)}", "Subscription Fix Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_all_subscription_dates():
    """Fix all subscriptions with date issues"""

    # Check permissions
    if not frappe.has_permission("Subscription", "write"):
        frappe.throw(_("You don't have permission to modify subscriptions"))

    # Find problematic subscriptions
    stuck_subs = frappe.db.sql(
        """
        SELECT name
        FROM `tabSubscription`
        WHERE
            status = 'Active'
            AND docstatus = 1
            AND (
                current_invoice_start < CURDATE()
                OR current_invoice_end < CURDATE()
            )
    """,
        pluck="name",
    )

    results = []

    for sub_name in stuck_subs:
        result = fix_subscription_dates(sub_name)
        results.append({"subscription": sub_name, "result": result})

    fixed = sum(1 for r in results if r["result"]["success"])
    failed = len(results) - fixed

    return {"success": True, "fixed": fixed, "failed": failed, "details": results}
