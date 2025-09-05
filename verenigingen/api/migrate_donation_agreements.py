import json

import frappe
from frappe.utils import cint, flt, today


@frappe.whitelist(allow_guest=True)
def migrate_all_donation_agreements(dry_run=True):
    """
    Migrate all Donation Agreement records to consolidated Donation model

    Args:
        dry_run (bool): If True, only simulate migration without saving
    """

    # Switch to Administrator context for permissions
    frappe.set_user("Administrator")

    try:
        # Get all Donation Agreements
        agreements = frappe.get_all(
            "Donation Agreement", fields=["name", "donor", "amount", "status"], order_by="creation"
        )

        if not agreements:
            return {
                "success": True,
                "message": "No Donation Agreement records found to migrate",
                "stats": {"total": 0, "migrated": 0, "errors": 0},
            }

        results = {
            "success": True,
            "dry_run": cint(dry_run),
            "total_agreements": len(agreements),
            "migrated": [],
            "errors": [],
            "stats": {"total": len(agreements), "migrated": 0, "errors": 0},
        }

        frappe.db.begin()  # Start transaction

        for i, agreement_data in enumerate(agreements):
            try:
                # Get full agreement document
                agreement = frappe.get_doc("Donation Agreement", agreement_data.name)

                # Create new Donation record
                new_donation = frappe.new_doc("Donation")

                # Map fields from agreement to donation
                field_mapping = {
                    "donor": agreement.donor,
                    "donation_date": today(),
                    "amount": flt(agreement.amount or 25.0),
                    "donation_type": "Herhalend",  # All agreements are recurring
                    "is_recurring": 1,
                    "recurring_frequency": "Monthly",
                    "company": frappe.defaults.get_global_default("company") or "Test Company",
                    "donation_notes": f"Migrated from Donation Agreement {agreement.name} on {today()}",
                    "payment_status": "Completed" if agreement.status == "Active" else "Pending",
                    # Preserve Mollie fields if they exist
                    "mollie_customer_id": getattr(agreement, "mollie_customer_id", None),
                    "mollie_subscription_id": getattr(agreement, "mollie_subscription_id", None),
                    "subscription_status": agreement.status or "Active",
                    "mode_of_payment": "Mollie",  # Agreements typically use Mollie
                }

                # Apply mapped fields
                for field, value in field_mapping.items():
                    if value is not None:
                        new_donation.set(field, value)

                if not dry_run:
                    # Save the new donation
                    new_donation.insert()

                    # Mark original agreement as migrated by adding a note
                    agreement.add_comment("Comment", f"Migrated to Donation {new_donation.name} on {today()}")

                # Track success
                migration_record = {
                    "agreement": agreement.name,
                    "new_donation": new_donation.name if not dry_run else f"WOULD_CREATE_{i + 1}",
                    "donor": agreement.donor,
                    "amount": field_mapping["amount"],
                    "status": "SUCCESS",
                }

                results["migrated"].append(migration_record)
                results["stats"]["migrated"] += 1

                # Progress logging
                if (i + 1) % 50 == 0:
                    frappe.logger().info(f"Migration progress: {i + 1}/{len(agreements)} processed")

            except Exception as e:
                # Track individual errors
                error_record = {"agreement": agreement_data.name, "error": str(e), "status": "ERROR"}
                results["errors"].append(error_record)
                results["stats"]["errors"] += 1

                frappe.logger().error(f"Error migrating {agreement_data.name}: {str(e)}")

                # Continue with other records
                continue

        if dry_run:
            frappe.db.rollback()  # Don't save anything in dry run
            results[
                "message"
            ] = f"DRY RUN: Would migrate {results['stats']['migrated']} of {results['stats']['total']} agreements"
        else:
            if results["stats"]["errors"] == 0:
                frappe.db.commit()  # Commit if no errors
                results[
                    "message"
                ] = f"SUCCESS: Migrated {results['stats']['migrated']} of {results['stats']['total']} agreements"
            else:
                frappe.db.rollback()  # Rollback if there were errors
                results["success"] = False
                results["message"] = f"FAILED: {results['stats']['errors']} errors occurred, no changes saved"

        return results

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Migration Script Error")
        return {
            "success": False,
            "message": f"Migration script error: {str(e)}",
            "traceback": frappe.get_traceback(),
        }


@frappe.whitelist(allow_guest=True)
def cleanup_migrated_agreements():
    """
    After successful migration, optionally disable/archive Donation Agreements
    This should only be run after verifying migration success
    """

    try:
        # Get all agreements that have migration comments
        agreements_with_comments = frappe.db.sql(
            """
            SELECT DISTINCT reference_name
            FROM `tabComment`
            WHERE reference_doctype = 'Donation Agreement'
            AND content LIKE '%Migrated to Donation%'
        """,
            as_dict=True,
        )

        if not agreements_with_comments:
            return {"success": False, "message": "No migrated agreements found to clean up"}

        results = {"success": True, "total_processed": len(agreements_with_comments), "archived": []}

        for agreement_ref in agreements_with_comments:
            agreement_name = agreement_ref.reference_name

            # Add an archived flag or disable the agreement
            agreement = frappe.get_doc("Donation Agreement", agreement_name)

            # Mark as archived (if such field exists) or add comment
            agreement.add_comment(
                "Comment",
                f"Archived after migration on {today()} - Original data preserved in new Donation record",
            )

            results["archived"].append(agreement_name)

        results["message"] = f"Archived {len(results['archived'])} migrated agreements"
        return results

    except Exception as e:
        return {"success": False, "message": f"Cleanup error: {str(e)}"}
