import frappe


@frappe.whitelist()
def fix_daily_access_template():
    """Fix the Template-Daily Access to have correct minimum amount"""

    try:
        template = frappe.get_doc("Membership Dues Schedule", "Template-Daily Access")

        old_minimum = template.minimum_amount

        # Fix the minimum amount to match suggested amount
        template.minimum_amount = template.suggested_amount  # 1.0

        # Save the template
        template.save()

        return {
            "success": True,
            "template": "Template-Daily Access",
            "old_minimum": old_minimum,
            "new_minimum": template.minimum_amount,
            "suggested_amount": template.suggested_amount,
            "dues_rate": template.dues_rate,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def update_existing_schedules_from_template():
    """Update existing schedules that were created from the incorrect template"""

    # Find schedules that reference Template-Daily Access with minimum_amount > dues_rate
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"template_reference": "Template-Daily Access", "is_template": 0},
        fields=["name", "minimum_amount", "dues_rate", "suggested_amount", "member"],
    )

    updated_schedules = []
    errors = []

    for schedule_info in schedules:
        if schedule_info.minimum_amount > schedule_info.dues_rate:
            try:
                # Update the schedule
                frappe.db.set_value(
                    "Membership Dues Schedule",
                    schedule_info.name,
                    "minimum_amount",
                    schedule_info.dues_rate,  # Set minimum to match dues rate
                )

                updated_schedules.append(
                    {
                        "name": schedule_info.name,
                        "member": schedule_info.member,
                        "old_minimum": schedule_info.minimum_amount,
                        "new_minimum": schedule_info.dues_rate,
                    }
                )

            except Exception as e:
                errors.append({"name": schedule_info.name, "error": str(e)})

    if updated_schedules:
        frappe.db.commit()

    return {
        "total_schedules_found": len(schedules),
        "updated_count": len(updated_schedules),
        "error_count": len(errors),
        "updated_schedules": updated_schedules,
        "errors": errors,
    }
