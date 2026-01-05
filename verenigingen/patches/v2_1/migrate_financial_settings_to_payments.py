"""
Migrate Financial & SEPA Settings from Verenigingen Settings to Verenigingen Payments Settings.

This patch moves the following field groups:
1. Financial Settings: company_account_holder, company_iban, company_bic,
   default_cash_account, mollie_bank_account, ponto_bank_account_parent
2. SEPA Batch Processing: sepa_mandate_naming_pattern, creditor_id,
   sepa_mandate_starting_counter, batch_creation_days, financial_admin_emails,
   batch_optimization_config, last_batch_creation_run, sepa_strict_period_mode,
   enable_auto_batch_creation, sepa_allowed_ips
3. Invoicing: send_email, send_invoice, email_template, membership_print_format,
   inv_print_format, default_item_group, membership_webhook_secret, contact_email,
   automate_membership_payment_entries
"""

import frappe
from frappe import _


def execute():
    """Migrate financial and SEPA settings to Verenigingen Payments Settings."""
    frappe.reload_doctype("Verenigingen Payments Settings")
    frappe.reload_doctype("Verenigingen Settings")

    # Fields to migrate
    fields_to_migrate = [
        # Financial Settings
        "company_account_holder",
        "company_iban",
        "company_bic",
        "default_cash_account",
        "mollie_bank_account",
        "ponto_bank_account_parent",
        # SEPA Batch Processing
        "sepa_mandate_naming_pattern",
        "creditor_id",
        "sepa_mandate_starting_counter",
        "batch_creation_days",
        "financial_admin_emails",
        "batch_optimization_config",
        "last_batch_creation_run",
        "sepa_strict_period_mode",
        "enable_auto_batch_creation",
        "sepa_allowed_ips",
        # Invoicing
        "send_email",
        "send_invoice",
        "email_template",
        "membership_print_format",
        "inv_print_format",
        "default_item_group",
        "membership_webhook_secret",
        "contact_email",
        "automate_membership_payment_entries",
    ]

    try:
        # Get source values using raw SQL to bypass schema validation
        # (fields may already be removed from source DocType)
        source_values = {}
        for field in fields_to_migrate:
            result = frappe.db.sql("""
                SELECT value FROM tabSingles
                WHERE doctype = 'Verenigingen Settings' AND field = %s
            """, field)
            if result and result[0][0]:
                source_values[field] = result[0][0]

        if not source_values:
            frappe.log("No financial/SEPA settings to migrate")
            return

        frappe.log(f"Migrating {len(source_values)} settings to Verenigingen Payments Settings")

        # Ensure target exists
        if not frappe.db.exists("Verenigingen Payments Settings", "Verenigingen Payments Settings"):
            payments_settings = frappe.get_doc({
                "doctype": "Verenigingen Payments Settings",
            })
            payments_settings.insert(ignore_permissions=True)

        # Migrate using direct SQL (INSERT ON DUPLICATE KEY UPDATE)
        # This bypasses ORM validation and ensures values are copied even if
        # source DocType schema no longer has these fields
        migrated_count = 0
        for field, value in source_values.items():
            # Check if target already has a value
            existing = frappe.db.sql("""
                SELECT value FROM tabSingles
                WHERE doctype = 'Verenigingen Payments Settings' AND field = %s
            """, field)

            if not existing or not existing[0][0]:
                frappe.db.sql("""
                    INSERT INTO tabSingles (doctype, field, value)
                    VALUES ('Verenigingen Payments Settings', %s, %s)
                    ON DUPLICATE KEY UPDATE value = %s
                """, (field, value, value))
                migrated_count += 1
                frappe.log(f"  Migrated {field}: {repr(value)[:50]}")

        if migrated_count > 0:
            frappe.db.commit()
            frappe.log(f"Successfully migrated {migrated_count} fields to Verenigingen Payments Settings")
        else:
            frappe.log("All fields already migrated or have values - no changes made")

    except Exception as e:
        frappe.log_error(f"Error migrating financial settings: {str(e)}")
        # Don't fail the patch - settings can be manually configured
        frappe.log(f"Warning: Could not migrate some settings. Please configure manually: {str(e)}")
