"""
Migrate billing and contribution settings from Membership Type to Membership Dues Schedule

This patch migrates ALL billing and contribution configuration from Membership Type
to Membership Dues Schedule templates, then removes the duplicate fields from Membership Type.

Fields migrated:
- billing_frequency
- invoice_days_before
- contribution_mode
- minimum_contribution → minimum_amount
- suggested_contribution → suggested_amount
- maximum_contribution → maximum_amount
- enable_income_calculator
- income_percentage_rate
- calculator_description
- predefined_tiers
- currency
- custom_amount_requires_approval
- fee_slider_max_multiplier
- allow_custom_amounts → uses_custom_amount

The allow_auto_renewal field is removed entirely as requested.
"""

import frappe
from frappe.utils import flt


def execute():
    """Migrate billing and contribution settings from Membership Type to Dues Schedule"""
    frappe.reload_doctype("Membership Type")
    frappe.reload_doctype("Membership Dues Schedule")

    print("Starting migration of billing settings to dues schedules...")

    membership_types = frappe.get_all("Membership Type", fields=["name"])

    for mt in membership_types:
        try:
            membership_type = frappe.get_doc("Membership Type", mt.name)

            # Check if template already exists
            existing_template = frappe.db.get_value(
                "Membership Dues Schedule",
                {"membership_type": membership_type.name, "is_template": 1},
                "name",
            )

            if existing_template:
                # Update existing template
                template = frappe.get_doc("Membership Dues Schedule", existing_template)
                print(f"Updating existing template for {membership_type.name}")
            else:
                # Create new template
                template = frappe.new_doc("Membership Dues Schedule")
                template.is_template = 1
                template.schedule_name = f"Template-{membership_type.name}"
                template.membership_type = membership_type.name
                template.status = "Active"
                print(f"Creating new template for {membership_type.name}")

            # Migrate billing frequency (if field exists)
            if hasattr(membership_type, "billing_frequency"):
                template.billing_frequency = membership_type.billing_frequency
            else:
                template.billing_frequency = "Annual"

            # Migrate contribution settings (if fields exist)
            if hasattr(membership_type, "contribution_mode"):
                # Map old values to new if needed
                contribution_mode = membership_type.contribution_mode
                if contribution_mode == "Tiers":
                    contribution_mode = "Tier"
                elif contribution_mode == "Both":
                    contribution_mode = "Calculator"  # Default to calculator for "Both"
                template.contribution_mode = contribution_mode
            else:
                template.contribution_mode = "Calculator"

            # Migrate amounts (if fields exist)
            template.minimum_amount = flt(getattr(membership_type, "minimum_contribution", 5.0))
            template.suggested_amount = flt(
                getattr(membership_type, "suggested_contribution", getattr(membership_type, "amount", 15.0))
            )
            template.maximum_amount = flt(getattr(membership_type, "maximum_contribution", 0))

            # Migrate invoice settings (if fields exist)
            template.invoice_days_before = getattr(membership_type, "invoice_days_before", 30)

            # Migrate calculator settings (if fields exist)
            if hasattr(membership_type, "enable_income_calculator"):
                template.enable_income_calculator = membership_type.enable_income_calculator
                template.income_percentage_rate = flt(
                    getattr(membership_type, "income_percentage_rate", 0.75)
                )
                template.calculator_description = getattr(membership_type, "calculator_description", "")

            # Migrate fee slider multiplier
            if hasattr(membership_type, "fee_slider_max_multiplier"):
                template.fee_slider_max_multiplier = flt(membership_type.fee_slider_max_multiplier) or 10.0

            # Migrate custom amount settings
            if hasattr(membership_type, "allow_custom_amounts") and membership_type.allow_custom_amounts:
                template.uses_custom_amount = 1

            if hasattr(membership_type, "custom_amount_requires_approval"):
                template.custom_amount_approved = not membership_type.custom_amount_requires_approval

            # Migrate tiers if present
            if hasattr(membership_type, "predefined_tiers") and membership_type.predefined_tiers:
                # Clear existing tiers
                template.predefined_tiers = []

                # Copy tiers
                for tier in membership_type.predefined_tiers:
                    template.append(
                        "predefined_tiers",
                        {
                            "tier_name": tier.tier_name,
                            "display_name": getattr(tier, "display_name", tier.tier_name),
                            "amount": flt(tier.amount),
                            "description": getattr(tier, "description", ""),
                            "requires_verification": getattr(tier, "requires_verification", 0),
                            "is_default": getattr(tier, "is_default", 0),
                            "display_order": getattr(tier, "display_order", 0),
                        },
                    )

            # Migrate currency if it exists in membership type
            if hasattr(membership_type, "currency"):
                template.currency = membership_type.currency
            else:
                template.currency = "EUR"  # Default

            # Set other required fields
            template.auto_generate = 1
            template.amount = template.suggested_amount

            # Save template
            if existing_template:
                template.save(ignore_permissions=True)
            else:
                template.insert(ignore_permissions=True)

                # Link template back to membership type
                membership_type.dues_schedule_template = template.name
                membership_type.save(ignore_permissions=True)

            print(f"✓ Migrated settings for {membership_type.name}")

        except Exception as e:
            print(f"✗ Error migrating {mt.name}: {str(e)}")
            frappe.log_error(f"Migration error for {mt.name}: {str(e)}", "Membership Type Migration")

    # Update all existing non-template dues schedules from their membership type
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"is_template": 0},
        fields=["name", "membership_type", "billing_frequency", "invoice_days_before", "minimum_amount"],
    )

    for schedule in schedules:
        if schedule.membership_type:
            try:
                mt = frappe.get_doc("Membership Type", schedule.membership_type)
                doc = frappe.get_doc("Membership Dues Schedule", schedule.name)
                updated = False

                # Update billing settings if not set
                if not doc.billing_frequency and hasattr(mt, "billing_frequency"):
                    doc.billing_frequency = mt.billing_frequency
                    updated = True

                if not doc.invoice_days_before and hasattr(mt, "invoice_days_before"):
                    doc.invoice_days_before = mt.invoice_days_before
                    updated = True

                # Update amounts if not set
                if not doc.minimum_amount and hasattr(mt, "minimum_contribution"):
                    doc.minimum_amount = flt(mt.minimum_contribution)
                    updated = True

                if not doc.suggested_amount and hasattr(mt, "suggested_contribution"):
                    doc.suggested_amount = flt(mt.suggested_contribution)
                    updated = True

                if updated:
                    doc.save(ignore_permissions=True)

            except Exception as e:
                frappe.log_error(f"Error updating dues schedule {schedule.name}: {str(e)}")
                continue

    print("Migration completed!")
    frappe.db.commit()
