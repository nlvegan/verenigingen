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
Uses raw SQL to avoid ORM filtering issues with invalid Select values.
"""

import frappe


def execute():
    """Migrate contribution_mode values to new schema."""
    if not frappe.db.table_exists("tabMembership Dues Schedule"):
        return

    meta = frappe.get_meta("Membership Dues Schedule")
    if not meta.has_field("contribution_mode"):
        return

    # Use raw SQL — frappe.get_all may silently filter out records whose
    # contribution_mode is not in the current Select options list.
    migrations = [
        ("Tier", "Fixed", None),
        ("Calculator", "Income-Based", "Percentage"),
        ("Custom", "Flexible", None),
        ("Progressive", "Income-Based", "Progressive"),
    ]

    total = 0
    for old_value, new_value, income_calc_type in migrations:
        if income_calc_type:
            frappe.db.sql(
                """UPDATE `tabMembership Dues Schedule`
                   SET contribution_mode = %s, income_calculation_type = %s
                   WHERE contribution_mode = %s""",
                (new_value, income_calc_type, old_value),
            )
        else:
            frappe.db.sql(
                """UPDATE `tabMembership Dues Schedule`
                   SET contribution_mode = %s
                   WHERE contribution_mode = %s""",
                (new_value, old_value),
            )

        affected = frappe.db.sql("SELECT ROW_COUNT() as cnt")[0][0]
        if affected:
            frappe.logger().info(
                f"Migrated {affected} Membership Dues Schedule records: "
                f"contribution_mode '{old_value}' → '{new_value}'"
            )
            total += affected

    # Also fix NULL values — set to DocType default
    frappe.db.sql(
        """UPDATE `tabMembership Dues Schedule`
           SET contribution_mode = 'Fixed'
           WHERE contribution_mode IS NULL"""
    )
    null_fixed = frappe.db.sql("SELECT ROW_COUNT() as cnt")[0][0]
    if null_fixed:
        frappe.logger().info(f"Set {null_fixed} NULL contribution_mode records to 'Fixed'")
        total += null_fixed

    if total:
        frappe.db.commit()
        frappe.logger().info(f"Contribution mode migration complete: {total} records updated")
