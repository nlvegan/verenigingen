"""
Cleanup duplicate Membership Dues Schedule templates created by different systems.

This patch addresses the issue where multiple systems were creating dues schedule templates:
1. Fixtures: "[Type] Membership Template" (preferred)
2. Legacy patch: "[Type] Template"
3. MembershipType: "Dues Schedule Template for [Type]"

This resulted in 6 templates instead of 3. We standardize on fixture-based templates
and remove duplicates.
"""

import frappe


def execute():
    """Remove duplicate dues schedule templates and standardize naming"""

    if frappe.flags.in_migrate:
        print("=== Cleaning up duplicate Membership Dues Schedule templates ===")

        # Define the standard templates we want to keep (from fixtures)
        standard_templates = [
            "Monthly Membership Template",
            "Quarterly Membership Template",
            "Annual Membership Template",
        ]

        # Find all templates that might be duplicates
        all_templates = frappe.get_all(
            "Membership Dues Schedule",
            filters={"is_template": 1},
            fields=["name", "membership_type", "schedule_name"],
        )

        duplicates_to_remove = []
        templates_to_update = {}

        for template in all_templates:
            template_name = template.name

            # Skip if this is one of our standard templates
            if template_name in standard_templates:
                continue

            # Check for duplicate patterns
            membership_type = template.membership_type

            # Pattern 1: "Dues Schedule Template for [Type]"
            if template_name.startswith("Dues Schedule Template for"):
                # Find corresponding standard template
                if membership_type == "Monthly Membership":
                    standard = "Monthly Membership Template"
                elif membership_type == "Quarterly Membership":
                    standard = "Quarterly Membership Template"
                elif membership_type == "Annual Membership":
                    standard = "Annual Membership Template"
                else:
                    continue

                if standard in [t.name for t in all_templates]:
                    duplicates_to_remove.append(template_name)
                    templates_to_update[template_name] = standard

            # Pattern 2: Just "[Type] Template" (from legacy patch)
            elif template_name.endswith(" Template") and not template_name.endswith(" Membership Template"):
                # Find corresponding standard template
                for standard in standard_templates:
                    if membership_type in standard:
                        duplicates_to_remove.append(template_name)
                        templates_to_update[template_name] = standard
                        break

        print(f"Found {len(duplicates_to_remove)} duplicate templates to remove")

        # Update any membership types that reference duplicate templates
        for old_template, new_template in templates_to_update.items():
            membership_types_using_old = frappe.get_all(
                "Membership Type", filters={"dues_schedule_template": old_template}, fields=["name"]
            )

            for mt in membership_types_using_old:
                frappe.db.set_value("Membership Type", mt.name, "dues_schedule_template", new_template)
                print(f"Updated {mt.name} to use {new_template} instead of {old_template}")

        # Remove duplicate templates
        for template_name in duplicates_to_remove:
            try:
                # Check if template is in use by any active schedules
                active_schedules = frappe.get_all(
                    "Membership Dues Schedule",
                    filters={"template_reference": template_name, "is_template": 0},
                )

                if active_schedules:
                    print(
                        f"Skipping {template_name} - still referenced by {len(active_schedules)} active schedules"
                    )
                    continue

                # Safe to delete
                frappe.delete_doc("Membership Dues Schedule", template_name)
                print(f"Removed duplicate template: {template_name}")

            except Exception as e:
                print(f"Warning: Could not remove {template_name}: {str(e)}")

        # Ensure all standard membership types are linked to correct templates
        standard_mappings = {
            "Monthly Membership": "Monthly Membership Template",
            "Quarterly Membership": "Quarterly Membership Template",
            "Annual Membership": "Annual Membership Template",
        }

        for membership_type, template in standard_mappings.items():
            if frappe.db.exists("Membership Type", membership_type):
                current_template = frappe.db.get_value(
                    "Membership Type", membership_type, "dues_schedule_template"
                )

                if current_template != template:
                    frappe.db.set_value(
                        "Membership Type", membership_type, "dues_schedule_template", template
                    )
                    print(f"Standardized {membership_type} to use {template}")

        # Commit the changes
        frappe.db.commit()
        print("=== Duplicate template cleanup completed ===")
