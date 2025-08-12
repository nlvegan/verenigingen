import frappe


@frappe.whitelist()
def check_membership_types_missing_templates():
    """Check which membership types are missing dues_schedule_template assignments"""

    # Find membership types without template assignments
    missing_templates = frappe.db.sql(
        """
        SELECT name, membership_type_name, amount, billing_period
        FROM `tabMembership Type`
        WHERE (dues_schedule_template IS NULL OR dues_schedule_template = '')
        AND is_active = 1
    """,
        as_dict=True,
    )

    # For each missing template, suggest what template should be used
    suggestions = []

    for mt in missing_templates:
        # Look for existing templates that match this membership type
        matching_templates = frappe.get_all(
            "Membership Dues Schedule",
            filters={"is_template": 1, "membership_type": mt.name},
            fields=["name", "minimum_amount", "suggested_amount", "dues_rate"],
        )

        suggestions.append(
            {
                "membership_type": mt.name,
                "membership_type_name": mt.membership_type_name,
                "amount": mt.minimum_amount,
                "billing_period": mt.billing_period,
                "matching_templates": matching_templates,
                "recommended_action": (
                    f"Assign template '{matching_templates[0].name}'"
                    if matching_templates
                    else "Create new template"
                ),
            }
        )

    return {
        "total_missing": len(missing_templates),
        "membership_types_missing_templates": suggestions,
        "status": "VALIDATION_REQUIRED" if missing_templates else "ALL_TEMPLATES_ASSIGNED",
    }


@frappe.whitelist()
def auto_assign_templates_to_membership_types():
    """Automatically assign templates to membership types that have matching templates"""

    # Find membership types without template assignments
    missing_templates = frappe.db.sql(
        """
        SELECT name, membership_type_name
        FROM `tabMembership Type`
        WHERE (dues_schedule_template IS NULL OR dues_schedule_template = '')
        AND is_active = 1
    """,
        as_dict=True,
    )

    results = {"assigned_count": 0, "failed_count": 0, "assigned_templates": [], "failed_assignments": []}

    for mt in missing_templates:
        try:
            # Look for template that matches this membership type
            matching_template = frappe.db.get_value(
                "Membership Dues Schedule", {"is_template": 1, "membership_type": mt.name}, "name"
            )

            if matching_template:
                # Assign the template
                frappe.db.set_value("Membership Type", mt.name, "dues_schedule_template", matching_template)

                results["assigned_templates"].append(
                    {
                        "membership_type": mt.name,
                        "membership_type_name": mt.membership_type_name,
                        "assigned_template": matching_template,
                    }
                )
                results["assigned_count"] += 1
            else:
                results["failed_assignments"].append(
                    {
                        "membership_type": mt.name,
                        "membership_type_name": mt.membership_type_name,
                        "reason": "No matching template found",
                    }
                )
                results["failed_count"] += 1

        except Exception as e:
            results["failed_assignments"].append(
                {
                    "membership_type": mt.name,
                    "membership_type_name": mt.membership_type_name,
                    "reason": str(e),
                }
            )
            results["failed_count"] += 1

    if results["assigned_count"] > 0:
        frappe.db.commit()
        results["status"] = f"Assigned {results['assigned_count']} templates"
    else:
        results["status"] = "No templates could be auto-assigned"

    return results


@frappe.whitelist()
def create_missing_templates():
    """Create basic templates for membership types that don't have any"""

    # Find membership types that have no matching templates
    membership_types_without_templates = []

    all_membership_types = frappe.get_all(
        "Membership Type",
        filters={"is_active": 1},
        fields=["name", "membership_type_name", "minimum_amount", "billing_period"],
    )

    for mt in all_membership_types:
        # Check if there's any template for this membership type
        existing_template = frappe.db.exists(
            "Membership Dues Schedule", {"is_template": 1, "membership_type": mt.name}
        )

        if not existing_template:
            membership_types_without_templates.append(mt)

    results = {"created_count": 0, "failed_count": 0, "created_templates": [], "errors": []}

    for mt in membership_types_without_templates:
        try:
            # Create a basic template
            template = frappe.get_doc(
                {
                    "doctype": "Membership Dues Schedule",
                    "schedule_name": f"Template-{mt.membership_type_name}",
                    "is_template": 1,
                    "membership_type": mt.name,
                    "minimum_amount": mt.minimum_amount,
                    "suggested_amount": mt.minimum_amount,
                    "dues_rate": mt.minimum_amount,
                    "billing_frequency": (
                        "Daily"
                        if mt.billing_period == "Daily"
                        else "Monthly"
                        if mt.billing_period == "Monthly"
                        else "Quarterly"
                        if mt.billing_period == "Quarterly"
                        else "Semi-Annual"
                        if mt.billing_period == "Biannual"
                        else "Annual"  # Default for Annual, Lifetime, Custom
                    ),
                    "contribution_mode": "Calculator",
                    "base_multiplier": 1.0,
                    "status": "Active",
                    "auto_generate": 1,
                }
            )

            template.insert()

            # Assign the template to the membership type
            frappe.db.set_value("Membership Type", mt.name, "dues_schedule_template", template.name)

            results["created_templates"].append(
                {
                    "membership_type": mt.name,
                    "membership_type_name": mt.membership_type_name,
                    "template_name": template.name,
                    "amount": mt.minimum_amount,
                }
            )
            results["created_count"] += 1

        except Exception as e:
            results["errors"].append(
                {"membership_type": mt.name, "membership_type_name": mt.membership_type_name, "error": str(e)}
            )
            results["failed_count"] += 1

    if results["created_count"] > 0:
        frappe.db.commit()

    results["status"] = f"Created {results['created_count']} templates, {results['failed_count']} failed"

    return results
