#!/usr/bin/env python3
"""
Mollie Data Backfill Utility

Administrative utility for backfilling missing Mollie IDs in donation records.
Fetches missing customer/mandate/subscription IDs from the Mollie API and
updates existing donation records for proper integration.

Usage:
    bench --site dev.veganisme.net execute "verenigingen.api.mollie_data_backfill_utility.backfill_missing_mollie_ids"
"""

import frappe
import mollie.api.client
from frappe.utils import flt


def backfill_missing_mollie_ids(dry_run=True, limit=50):
    """
    Backfill missing Mollie IDs for existing donation records

    Args:
        dry_run: If True, only logs what would be updated without making changes
        limit: Maximum number of donations to process in one run
    """
    try:
        # Get Mollie client
        settings = frappe.get_doc("Mollie Settings")
        client = mollie.api.client.Client()
        client.set_api_key(settings.get_active_api_key())

        # Find donations with payment_id but missing Mollie fields
        donations = frappe.db.sql(
            """
            SELECT name, payment_id, mollie_customer_id, mollie_mandate_id, mollie_subscription_id
            FROM `tabDonation`
            WHERE payment_id IS NOT NULL
            AND payment_id != ""
            AND payment_id LIKE "tr_%"
            AND (mollie_customer_id IS NULL OR mollie_customer_id = ""
                 OR mollie_mandate_id IS NULL OR mollie_mandate_id = ""
                 OR mollie_subscription_id IS NULL OR mollie_subscription_id = "")
            ORDER BY creation DESC
            LIMIT %s
        """,
            (limit,),
            as_dict=True,
        )

        frappe.logger().info(f"🔍 Found {len(donations)} donations with missing Mollie IDs")

        updated_count = 0

        for donation_data in donations:
            payment_id = donation_data.payment_id

            try:
                # Fetch payment from Mollie API
                payment = client.payments.get(payment_id)

                # Extract IDs
                customer_id = None
                mandate_id = None
                subscription_id = None

                if hasattr(payment, "_data") and isinstance(payment._data, dict):
                    customer_id = payment._data.get("customerId")
                    mandate_id = payment._data.get("mandateId")
                    subscription_id = payment._data.get("subscriptionId")
                elif hasattr(payment, "customer_id"):
                    customer_id = payment.customer_id

                # Check if we have new data to update
                needs_update = False
                update_data = {}

                if customer_id and not donation_data.mollie_customer_id:
                    update_data["mollie_customer_id"] = customer_id
                    needs_update = True

                if mandate_id and not donation_data.mollie_mandate_id:
                    update_data["mollie_mandate_id"] = mandate_id
                    needs_update = True

                if subscription_id and not donation_data.mollie_subscription_id:
                    update_data["mollie_subscription_id"] = subscription_id
                    needs_update = True

                if needs_update:
                    if dry_run:
                        frappe.logger().info(
                            f"[DRY RUN] Would update {donation_data.name} with: {update_data}"
                        )
                    else:
                        # Update the donation record
                        frappe.db.set_value("Donation", donation_data.name, update_data)
                        frappe.logger().info(
                            f"✅ Updated {donation_data.name} with Mollie IDs: {update_data}"
                        )
                        updated_count += 1
                else:
                    frappe.logger().info(
                        f"⏭️ No new Mollie data for {donation_data.name} (payment: {payment_id})"
                    )

            except Exception as e:
                frappe.logger().error(
                    f"❌ Failed to process payment {payment_id} for donation {donation_data.name}: {str(e)}"
                )
                continue

        if not dry_run:
            frappe.db.commit()

        summary = f"{'[DRY RUN] ' if dry_run else ''}Processed {len(donations)} donations, updated {updated_count} records"
        frappe.logger().info(f"🏁 {summary}")

        return {
            "status": "success",
            "processed": len(donations),
            "updated": updated_count,
            "dry_run": dry_run,
            "summary": summary,
        }

    except Exception as e:
        error_msg = f"Backfill failed: {str(e)}"
        frappe.log_error(error_msg, "Mollie ID Backfill Error")
        frappe.logger().error(f"❌ {error_msg}")
        return {"status": "error", "message": error_msg}


def run_backfill_live(limit=10):
    """Run backfill with actual updates (not dry run)"""
    return backfill_missing_mollie_ids(dry_run=False, limit=limit)


if __name__ == "__main__":
    # Test run
    result = backfill_missing_mollie_ids(dry_run=True, limit=5)
    print(result)
