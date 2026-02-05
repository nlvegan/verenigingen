"""
Migrate Membership Dues Schedule contribution_mode values from old to new schema.

Old values: Tier, Calculator, Custom, Progressive
New values: Fixed, Income-Based, Flexible

Mapping:
- Tier → Fixed (tiers are fixed amounts per tier)
- Calculator → Income-Based (percentage-based calculation)
- Custom → Flexible (allows custom amounts with suggestions)
- Progressive → Income-Based with income_calculation_type = "Progressive"

This patch is idempotent and can be run multiple times safely.
"""

import frappe
from frappe import _


def execute():
    """Migrate contribution_mode values to new schema."""
    # Check if Membership Dues Schedule doctype exists
    if not frappe.db.table_exists("tabMembership Dues Schedule"):
        return

    # Check if the field exists (may have been added in this same migration)
    meta = frappe.get_meta("Membership Dues Schedule")
    if not meta.has_field("contribution_mode"):
        return

    # Define the migration mapping
    migrations = [
        {
            "old_value": "Tier",
            "new_value": "Fixed",
            "additional_updates": {},
        },
        {
            "old_value": "Calculator",
            "new_value": "Income-Based",
            "additional_updates": {
                "income_calculation_type": "Percentage",
            },
        },
        {
            "old_value": "Custom",
            "new_value": "Flexible",
            "additional_updates": {},
        },
        {
            "old_value": "Progressive",
            "new_value": "Income-Based",
            "additional_updates": {
                "income_calculation_type": "Progressive",
            },
        },
    ]

    migrated_count = 0
    errors = []

    for mapping in migrations:
        old_value = mapping["old_value"]
        new_value = mapping["new_value"]
        additional = mapping["additional_updates"]

        # Find records with old value
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"contribution_mode": old_value},
            fields=["name"],
        )

        if not schedules:
            continue

        frappe.logger().info(
            f"Migrating {len(schedules)} Membership Dues Schedule records "
            f"from contribution_mode='{old_value}' to '{new_value}'"
        )

        for schedule in schedules:
            try:
                # Build update dict
                update_values = {"contribution_mode": new_value}
                update_values.update(additional)

                # Update directly via SQL for efficiency
                frappe.db.set_value(
                    "Membership Dues Schedule",
                    schedule.name,
                    update_values,
                    update_modified=False,  # Don't change modified timestamp
                )

                migrated_count += 1

            except Exception as e:
                errors.append(f"{schedule.name}: {str(e)}")
                frappe.log_error(
                    f"Error migrating contribution_mode for {schedule.name}: {str(e)}",
                    "Contribution Mode Migration Error",
                )

    # Commit changes
    if migrated_count > 0:
        frappe.db.commit()
        frappe.logger().info(f"Successfully migrated {migrated_count} Membership Dues Schedule records")

    if errors:
        frappe.logger().error(f"Errors during contribution_mode migration: {errors}")

    # Log summary
    if migrated_count > 0 or errors:
        frappe.logger().info(
            f"Contribution mode migration complete. " f"Migrated: {migrated_count}, Errors: {len(errors)}"
        )
