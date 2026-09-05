"""
Migrate payment-related fields from Verenigingen Settings to Verenigingen Payments Settings.

Fields migrated:
- mollie_subscription_description_template
- ponto_payment_description_template
- membership_payment_account
- dues_income_account
- dues_payments_receivable_account
"""
import frappe


def execute():
    """Copy payment field values from Verenigingen Settings to Payments Settings."""
    # Fields to migrate
    source_fields = [
        "mollie_subscription_description_template",
        "ponto_payment_description_template",
        "membership_payment_account",
        "dues_income_account",
        "dues_payments_receivable_account",
    ]

    # Get source values using raw SQL to bypass schema validation
    # (fields may already be removed from source DocType)
    source_values = {}
    for field in source_fields:
        result = frappe.db.sql(
            """
            SELECT value FROM tabSingles
            WHERE doctype = 'Verenigingen Settings' AND field = %s
        """,
            field,
        )
        if result and result[0][0]:
            source_values[field] = result[0][0]

    if not source_values:
        frappe.log("No payment fields to migrate - all empty in source")
        return

    frappe.log(f"Migrating {len(source_values)} payment fields to Verenigingen Payments Settings")

    # Ensure target singleton exists. frappe.db.exists(dt, dt) is
    # unconditionally truthy for a Single (#889), so check whether it has
    # actually been saved instead.
    if not frappe.db.get_singles_dict("Verenigingen Payments Settings"):
        payments_settings = frappe.get_doc(
            {
                "doctype": "Verenigingen Payments Settings",
            }
        )
        payments_settings.insert(ignore_permissions=True)

    # Migrate using direct SQL (INSERT ON DUPLICATE KEY UPDATE)
    # This bypasses ORM validation and ensures values are copied even if
    # source DocType schema no longer has these fields
    migrated_count = 0
    for field, value in source_values.items():
        # Check if target already has a value (don't overwrite existing)
        existing = frappe.db.sql(
            """
            SELECT value FROM tabSingles
            WHERE doctype = 'Verenigingen Payments Settings' AND field = %s
        """,
            field,
        )

        if not existing or not existing[0][0]:
            frappe.db.sql(
                """
                INSERT INTO tabSingles (doctype, field, value)
                VALUES ('Verenigingen Payments Settings', %s, %s)
                ON DUPLICATE KEY UPDATE value = %s
            """,
                (field, value, value),
            )
            migrated_count += 1
            frappe.log(f"  Migrated {field}: {repr(value)[:50]}")
        else:
            frappe.log(f"  Skipped {field} - already set in Payments Settings")

    if migrated_count > 0:
        frappe.db.commit()
        frappe.log(f"Successfully migrated {migrated_count} payment fields to Verenigingen Payments Settings")
    else:
        frappe.log("All payment fields already migrated or have values - no changes made")
