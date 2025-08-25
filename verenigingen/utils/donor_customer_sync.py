"""
Donor-Customer synchronization utilities

This module handles automatic synchronization between Donor and Customer records
to ensure consistent data across the nonprofit and accounting systems.
"""

import frappe
from frappe.utils import now


def sync_donor_to_customer(doc, method=None):
    """
    Sync donor data to related customer record
    Called from document hooks (after_save, on_update)

    Args:
        doc: Donor document
        method: Hook method name (not used)
    """
    # Skip if this is being called from customer sync to prevent loops
    if hasattr(doc, "flags") and doc.flags.get("from_customer_sync"):
        return

    # Skip if sync is disabled
    if hasattr(doc, "flags") and doc.flags.get("ignore_customer_sync"):
        return

    # Skip if we're in the middle of a customer save operation to prevent circular sync
    if getattr(frappe.local, "_customer_save_in_progress", False):
        if frappe.flags.get("in_test"):
            print("🔄 Skipping donor→customer sync: customer save in progress")
        return

    try:
        # The sync logic is already in the Donor document class
        # Always call sync to ensure customer data stays up to date
        # The sync_with_customer method handles its own optimization

        # Debug logging during tests
        if frappe.flags.get("in_test"):
            print(f"🔄 Hook sync_donor_to_customer called for donor {doc.name}")

        doc.sync_with_customer()

    except Exception as e:
        # Enhanced error logging with operational context
        error_context = {
            "donor_name": doc.name,
            "donor_display_name": getattr(doc, "donor_name", "Unknown"),
            "donor_email": getattr(doc, "donor_email", "No email"),
            "current_customer": getattr(doc, "customer", "No customer"),
            "sync_method": "donor_to_customer_hook",
        }

        frappe.log_error(
            f"Error in donor-customer sync hook:\n"
            f"Donor: {error_context['donor_name']} ({error_context['donor_display_name']})\n"
            f"Email: {error_context['donor_email']}\n"
            f"Current Customer: {error_context['current_customer']}\n"
            f"Error: {str(e)}",
            "Donor-Customer Sync Hook Error",
        )

        if frappe.flags.get("in_test"):
            print(f"❌ Hook error for donor {doc.name}: {str(e)}")


def sync_customer_to_donor(doc, method=None):
    """
    Sync customer data back to related donor record
    Called from Customer document hooks

    Args:
        doc: Customer document
        method: Hook method name (not used)
    """
    # Skip if this sync originated from donor
    if hasattr(doc, "flags") and doc.flags.get("from_donor_sync"):
        return

    # Debug logging during tests
    if frappe.flags.get("in_test"):
        print(f"🔄 Hook sync_customer_to_donor called for customer {doc.name}")
        print(f"   hasattr(doc, 'donor'): {hasattr(doc, 'donor')}")
        if hasattr(doc, "donor"):
            print(f"   doc.donor: {doc.donor}")
        else:
            print("   doc.donor: ATTRIBUTE_NOT_FOUND")

    # Only sync if this customer has a donor reference
    if not hasattr(doc, "donor") or not doc.donor:
        if frappe.flags.get("in_test"):
            print("❌ Customer-to-donor sync skipped: no donor reference")
        return

    try:
        donor_name = doc.donor

        # Check if donor exists
        if not frappe.db.exists("Donor", donor_name):
            return

        donor_doc = frappe.get_doc("Donor", donor_name)

        # Track if any changes were made
        changes_made = False

        # Sync basic information back to donor
        if donor_doc.donor_name != doc.customer_name:
            donor_doc.donor_name = doc.customer_name
            changes_made = True

        if doc.email_id and donor_doc.donor_email != doc.email_id:
            donor_doc.donor_email = doc.email_id
            changes_made = True

        if doc.mobile_no and (not hasattr(donor_doc, "phone") or donor_doc.phone != doc.mobile_no):
            donor_doc.phone = doc.mobile_no
            changes_made = True

        # Update customer link if needed
        if donor_doc.customer != doc.name:
            donor_doc.customer = doc.name
            changes_made = True

        # Save if changes were made
        if changes_made:
            if frappe.flags.get("in_test"):
                print("📝 Customer→Donor changes detected, saving donor")
                print(
                    f"   Changes: name={donor_doc.donor_name}, email={donor_doc.donor_email}, phone={getattr(donor_doc, 'phone', None)}"
                )

            # Set flag to prevent circular sync during donor save
            frappe.local._customer_save_in_progress = True

            try:
                donor_doc.flags.from_customer_sync = True
                donor_doc.flags.ignore_customer_sync = True
                donor_doc.customer_sync_status = "Synced"
                donor_doc.last_customer_sync = now()
                donor_doc.save()

                # Commit during tests to ensure visibility
                if frappe.flags.get("in_test"):
                    frappe.db.commit()
                    print("✅ Donor saved and committed after customer sync")
            finally:
                # Always clear the flag, even if save fails
                frappe.local._customer_save_in_progress = False

            frappe.logger().info(f"Synced customer {doc.name} data back to donor {donor_name}")
        else:
            if frappe.flags.get("in_test"):
                print("⏭️ No changes detected for customer→donor sync")

    except Exception as e:
        if frappe.flags.get("in_test"):
            print(f"❌ Customer→Donor sync error: {str(e)}")
            import traceback

            traceback.print_exc()
        # Enhanced error logging with operational context
        error_context = {
            "customer_name": doc.name,
            "customer_display_name": getattr(doc, "customer_name", "Unknown"),
            "customer_email": getattr(doc, "email_id", "No email"),
            "linked_donor": getattr(doc, "donor", "No donor"),
            "sync_method": "customer_to_donor_hook",
        }

        frappe.log_error(
            f"Error in customer-donor sync hook:\n"
            f"Customer: {error_context['customer_name']} ({error_context['customer_display_name']})\n"
            f"Email: {error_context['customer_email']}\n"
            f"Linked Donor: {error_context['linked_donor']}\n"
            f"Error: {str(e)}",
            "Customer-Donor Sync Error",
        )


@frappe.whitelist()
def bulk_sync_donors_to_customers(filters=None):
    """
    Bulk synchronization of donors to customers
    Useful for initial setup or data cleanup

    Args:
        filters: Optional filters to limit which donors to sync

    Returns:
        dict: Summary of sync results
    """
    if not filters:
        filters = {}

    try:
        # Get donors to sync
        donors = frappe.get_all(
            "Donor",
            filters=filters,
            fields=["name", "donor_name", "donor_email", "customer", "customer_sync_status"],
        )

        results = {
            "total_processed": 0,
            "created_customers": 0,
            "updated_customers": 0,
            "errors": 0,
            "error_details": [],
        }

        for donor_data in donors:
            try:
                donor_doc = frappe.get_doc("Donor", donor_data.name)

                # Store original customer to detect if new one was created
                original_customer = donor_doc.customer

                # Trigger sync
                donor_doc.flags.ignore_customer_sync = False
                donor_doc.sync_with_customer()
                donor_doc.save()

                results["total_processed"] += 1

                # Check if customer was created or updated
                if not original_customer and donor_doc.customer:
                    results["created_customers"] += 1
                elif original_customer and donor_doc.customer:
                    results["updated_customers"] += 1

            except Exception as e:
                results["errors"] += 1
                results["error_details"].append({"donor": donor_data.name, "error": str(e)})

        return results

    except Exception as e:
        frappe.log_error(f"Error in bulk donor-customer sync: {str(e)}", "Bulk Sync Error")
        return {"error": str(e)}


@frappe.whitelist()
def get_sync_status_summary():
    """
    Get summary of donor-customer sync status

    Returns:
        dict: Summary statistics
    """
    try:
        # Get sync status counts
        sync_status = frappe.db.sql(
            """
            SELECT
                customer_sync_status,
                COUNT(*) as count
            FROM `tabDonor`
            GROUP BY customer_sync_status
        """,
            as_dict=True,
        )

        # Get donors with/without customers
        customer_stats = frappe.db.sql(
            """
            SELECT
                CASE
                    WHEN customer IS NOT NULL AND customer != '' THEN 'Has Customer'
                    ELSE 'No Customer'
                END as status,
                COUNT(*) as count
            FROM `tabDonor`
            GROUP BY
                CASE
                    WHEN customer IS NOT NULL AND customer != '' THEN 'Has Customer'
                    ELSE 'No Customer'
                END
        """,
            as_dict=True,
        )

        return {
            "sync_status": {item["customer_sync_status"] or "Unknown": item["count"] for item in sync_status},
            "customer_links": {item["status"]: item["count"] for item in customer_stats},
        }

    except Exception as e:
        frappe.log_error(f"Error getting sync status summary: {str(e)}", "Sync Status Error")
        return {"error": str(e)}
