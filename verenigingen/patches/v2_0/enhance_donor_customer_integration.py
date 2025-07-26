"""
Patch to enhance Donor-Customer integration with automatic sync capabilities

This patch:
1. Adds new customer integration fields to existing Donor records
2. Performs initial sync of existing donors with customers
3. Sets up proper sync status tracking
"""

import frappe
from frappe.utils import now


def execute():
    """Execute the donor-customer integration enhancement patch"""

    frappe.logger().info("Starting Donor-Customer integration enhancement patch...")

    try:
        # Step 1: Create Donors customer group if it doesn't exist
        ensure_donor_customer_group()

        # Step 2: Initialize sync status for existing donors
        initialize_sync_status()

        # Step 3: Link existing customers to donors where possible
        link_existing_customers_to_donors()

        # Step 4: Create customers for donors that need them
        create_customers_for_donors()

        frappe.logger().info("✅ Donor-Customer integration enhancement completed successfully")

    except Exception as e:
        frappe.log_error(f"Error in donor-customer integration patch: {str(e)}")
        raise


def ensure_donor_customer_group():
    """Ensure 'Donors' customer group exists"""
    if not frappe.db.exists("Customer Group", "Donors"):
        frappe.logger().info("Creating 'Donors' customer group...")

        donor_group = frappe.new_doc("Customer Group")
        donor_group.customer_group_name = "Donors"
        donor_group.parent_customer_group = "All Customer Groups"
        donor_group.is_group = 0
        donor_group.flags.ignore_permissions = True
        donor_group.insert()

        frappe.logger().info("✅ Created 'Donors' customer group")


def initialize_sync_status():
    """Initialize sync status fields for existing donors"""
    frappe.logger().info("Initializing sync status for existing donors...")

    # Get all donors
    donors = frappe.get_all("Donor", fields=["name", "customer"])

    updated_count = 0
    for donor in donors:
        sync_status = "Synced" if donor.customer else "Pending"
        last_sync = now() if donor.customer else None

        frappe.db.set_value(
            "Donor", donor.name, {"customer_sync_status": sync_status, "last_customer_sync": last_sync}
        )
        updated_count += 1

    frappe.logger().info(f"✅ Initialized sync status for {updated_count} donors")


def link_existing_customers_to_donors():
    """Link existing customers to donors where possible"""
    frappe.logger().info("Linking existing customers to donors...")

    # Find customers that have donor references but donors don't have customer links
    unlinked_pairs = frappe.db.sql(
        """
        SELECT
            c.name as customer_name,
            c.custom_donor_reference as donor_name
        FROM `tabCustomer` c
        LEFT JOIN `tabDonor` d ON d.name = c.custom_donor_reference
        WHERE c.custom_donor_reference IS NOT NULL
        AND c.custom_donor_reference != ''
        AND (d.customer IS NULL OR d.customer = '')
    """,
        as_dict=True,
    )

    linked_count = 0
    for pair in unlinked_pairs:
        try:
            # Update donor to link to customer
            frappe.db.set_value(
                "Donor",
                pair.donor_name,
                {
                    "customer": pair.customer_name,
                    "customer_sync_status": "Synced",
                    "last_customer_sync": now(),
                },
            )
            linked_count += 1

        except Exception as e:
            frappe.logger().error(
                f"Failed to link donor {pair.donor_name} to customer {pair.customer_name}: {str(e)}"
            )

    frappe.logger().info(f"✅ Linked {linked_count} existing customer-donor pairs")


def create_customers_for_donors():
    """Create customers for donors that have donations but no customer"""
    frappe.logger().info("Creating customers for donors with donations...")

    # Find donors who have donations but no customer
    donors_needing_customers = frappe.db.sql(
        """
        SELECT DISTINCT
            d.name,
            d.donor_name,
            d.donor_email,
            d.phone,
            d.donor_type
        FROM `tabDonor` d
        INNER JOIN `tabDonation` don ON don.donor = d.name
        WHERE (d.customer IS NULL OR d.customer = '')
        AND don.docstatus = 1
    """,
        as_dict=True,
    )

    created_count = 0
    for donor_data in donors_needing_customers:
        try:
            # Get donor document to use its create_customer method
            donor_doc = frappe.get_doc("Donor", donor_data.name)
            customer_name = donor_doc.create_customer_from_donor()

            if customer_name:
                # Update donor with customer link
                frappe.db.set_value(
                    "Donor",
                    donor_data.name,
                    {
                        "customer": customer_name,
                        "customer_sync_status": "Synced",
                        "last_customer_sync": now(),
                    },
                )
                created_count += 1

        except Exception as e:
            frappe.logger().error(f"Failed to create customer for donor {donor_data.name}: {str(e)}")

    frappe.logger().info(f"✅ Created {created_count} customers for donors with donations")


def get_patch_summary():
    """Get summary of what the patch accomplished"""
    try:
        # Count donors with customers
        donor_customer_stats = frappe.db.sql(
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

        # Count sync statuses
        sync_stats = frappe.db.sql(
            """
            SELECT
                customer_sync_status,
                COUNT(*) as count
            FROM `tabDonor`
            GROUP BY customer_sync_status
        """,
            as_dict=True,
        )

        frappe.logger().info("📊 Patch Summary:")
        frappe.logger().info(f"Customer Links: {donor_customer_stats}")
        frappe.logger().info(f"Sync Status: {sync_stats}")

    except Exception as e:
        frappe.logger().error(f"Error getting patch summary: {str(e)}")


# Call summary at the end
frappe.db.commit()
get_patch_summary()
