import frappe


@frappe.whitelist()
def check_dues_schedules():
    """Check status of dues schedules"""
    from frappe.utils import add_days, today

    # Get schedules with upcoming invoice dates
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"status": "Active", "auto_generate": 1, "is_template": 0},
        fields=["name", "member_name", "next_invoice_date", "billing_frequency"],
        order_by="next_invoice_date",
        limit=10,
    )

    result = {"today": today(), "cutoff_date": add_days(today(), 30), "schedules": schedules}

    # Count schedules by next invoice date range
    result["due_now"] = frappe.db.count(
        "Membership Dues Schedule",
        {"status": "Active", "auto_generate": 1, "next_invoice_date": ["<=", today()]},
    )

    result["due_30_days"] = frappe.db.count(
        "Membership Dues Schedule",
        {"status": "Active", "auto_generate": 1, "next_invoice_date": ["<=", add_days(today(), 30)]},
    )

    # Get some that are past due if any
    past_due = frappe.get_all(
        "Membership Dues Schedule",
        filters={"status": "Active", "auto_generate": 1, "next_invoice_date": ["<", today()]},
        fields=["name", "member_name", "next_invoice_date"],
        limit=5,
    )

    result["past_due_schedules"] = past_due

    return result


if __name__ == "__main__":
    frappe.init()
    frappe.connect()
    result = check_dues_schedules()

    print(f"Today: {result['today']}")
    print(f"30 days from now: {result['cutoff_date']}")
    print(f"\nSchedules due today or earlier: {result['due_now']}")
    print(f"Schedules due within 30 days: {result['due_30_days']}")

    if result["past_due_schedules"]:
        print("\nPast due schedules:")
        for schedule in result["past_due_schedules"]:
            print(
                f"- {schedule['name']}: Member {schedule['member_name']}, Due: {schedule['next_invoice_date']}"
            )

    print("\nNext 10 schedules:")
    for schedule in result["schedules"]:
        print(
            f"- {schedule['name']}: Member {schedule['member_name']}, Next: {schedule['next_invoice_date']}, Frequency: {schedule['billing_frequency']}"
        )
