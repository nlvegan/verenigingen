import frappe
from frappe.utils import getdate, today


@frappe.whitelist()
def fix_invalid_last_invoice_dates():
    """Fix schedules with last_invoice_date in the future"""

    today_date = getdate(today())

    # Find schedules with future last invoice dates
    invalid_schedules = frappe.db.sql(
        """
        SELECT name, member_name, last_invoice_date, next_invoice_date
        FROM `tabMembership Dues Schedule`
        WHERE last_invoice_date > %s
        AND status = 'Active'
        ORDER BY last_invoice_date DESC
    """,
        [today_date],
        as_dict=True,
    )

    if not invalid_schedules:
        return {"success": True, "message": "No schedules found with invalid future last invoice dates."}

    results = []
    fixed_count = 0

    for schedule_data in invalid_schedules:
        try:
            # Load and fix the schedule
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_data.name)

            old_date = schedule.last_invoice_date
            schedule.last_invoice_date = today_date

            # Recalculate next_invoice_date if needed
            if schedule.next_invoice_date and getdate(schedule.next_invoice_date) <= today_date:
                schedule.next_invoice_date = schedule.calculate_next_invoice_date(today_date)

            # Save with validation skip to avoid triggering validation
            schedule.flags.ignore_validate = True
            schedule.save()

            results.append(
                {
                    "schedule": schedule_data.name,
                    "member": schedule_data.member_name,
                    "old_date": str(old_date),
                    "new_date": str(schedule.last_invoice_date),
                    "status": "Fixed",
                }
            )
            fixed_count += 1

        except Exception as e:
            results.append(
                {
                    "schedule": schedule_data.name,
                    "member": schedule_data.member_name,
                    "old_date": str(schedule_data.last_invoice_date),
                    "error": str(e),
                    "status": "Error",
                }
            )

    frappe.db.commit()

    return {
        "success": True,
        "message": f"Fixed {fixed_count} out of {len(invalid_schedules)} schedules.",
        "fixed_count": fixed_count,
        "total_found": len(invalid_schedules),
        "details": results,
    }
