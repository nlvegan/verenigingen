import frappe


@frappe.whitelist()
def debug_schedule_generation():
    """Debug why schedules aren't generating invoices"""

    # Get one of the schedules that should generate an invoice
    schedule_name = "Amendment AMEND-2025-02460 - VSoWlQ"

    try:
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

        result = {
            "schedule_name": schedule_name,
            "status": schedule.status,
            "auto_generate": schedule.auto_generate,
            "is_template": schedule.is_template,
            "test_mode": getattr(schedule, "test_mode", False),
            "next_invoice_date": schedule.next_invoice_date,
            "last_invoice_date": schedule.last_invoice_date,
            "member": schedule.member,
            "member_name": schedule.member_name,
        }

        # Check can_generate_invoice
        can_generate, reason = schedule.can_generate_invoice()
        result["can_generate"] = can_generate
        result["reason"] = reason

        # If we can generate, try to actually generate
        if can_generate:
            try:
                invoice = schedule.generate_invoice()
                result["invoice_generated"] = bool(invoice)
                result["invoice_name"] = invoice if invoice else None
            except Exception as e:
                result["invoice_error"] = str(e)

        return result

    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    frappe.init()
    frappe.connect()
    result = debug_schedule_generation()

    print("=== Debug Schedule Generation ===")
    for key, value in result.items():
        print(f"{key}: {value}")
