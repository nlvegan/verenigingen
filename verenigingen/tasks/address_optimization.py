"""
Scheduled tasks for address optimization and maintenance.

This module contains background tasks that maintain the computed address fields
for optimal performance of the 'other members at address' functionality.
"""

import frappe
from frappe.utils import now


def update_all_member_address_fingerprints():
    """
    Nightly task to update computed address fields for all members.

    This task ensures that:
    1. All members have computed address fingerprints for fast matching
    2. Any members with missing computed fields get updated
    3. Performance optimization is maintained across the system

    Scheduled to run daily at 2:00 AM to minimize system impact.
    """
    try:
        frappe.logger().info("Starting nightly address fingerprint update task")

        # Get all members with primary addresses but missing computed fields
        members_needing_update = frappe.db.sql(
            """
            SELECT name, primary_address
            FROM `tabMember`
            WHERE primary_address IS NOT NULL
            AND primary_address != ''
            AND (
                address_fingerprint IS NULL
                OR address_fingerprint = ''
                OR normalized_address_line IS NULL
                OR normalized_address_line = ''
            )
            ORDER BY modified DESC
        """,
            as_dict=True,
        )

        if not members_needing_update:
            frappe.logger().info("No members need address fingerprint updates")
            return {"status": "success", "updated_count": 0}

        frappe.logger().info(f"Found {len(members_needing_update)} members needing address updates")

        updated_count = 0
        error_count = 0

        # Process members in batches to avoid memory issues
        batch_size = 50
        for i in range(0, len(members_needing_update), batch_size):
            batch = members_needing_update[i : i + batch_size]

            for member_data in batch:
                try:
                    # Load the member document
                    member = frappe.get_doc("Member", member_data["name"])

                    if member.primary_address:
                        # Trigger the computed field update
                        member._update_computed_address_fields()

                        # Save to database without triggering full validation
                        frappe.db.set_value(
                            "Member",
                            member.name,
                            {
                                "address_fingerprint": member.address_fingerprint,
                                "normalized_address_line": member.normalized_address_line,
                                "normalized_city": member.normalized_city,
                                "address_last_updated": member.address_last_updated,
                            },
                        )

                        updated_count += 1

                        if updated_count % 10 == 0:
                            frappe.logger().info(f"Updated {updated_count} members so far...")

                except Exception as e:
                    error_count += 1
                    frappe.log_error(
                        f"Error updating address fields for member {member_data['name']}: {str(e)}",
                        "Address Fingerprint Update",
                    )

            # Commit batch changes
            frappe.db.commit()

        result = {
            "status": "success",
            "updated_count": updated_count,
            "error_count": error_count,
            "total_processed": len(members_needing_update),
            "completion_time": now(),
        }

        frappe.logger().info(f"Address fingerprint update completed: {result}")
        return result

    except Exception as e:
        frappe.log_error(f"Fatal error in address fingerprint update task: {str(e)}", "Address Update Task")
        return {"status": "error", "error": str(e)}


def refresh_member_address_displays():
    """
    Weekly task to refresh the HTML display fields for member addresses.

    Optimized to only process members whose addresses have changed recently
    or who need initial address display setup. This dramatically reduces
    the number of API calls needed and avoids rate limiting issues.

    Scheduled to run weekly on Sunday at 3:00 AM.
    """
    try:
        frappe.logger().info("Starting optimized address display refresh task")

        # Get members who need address display updates:
        # 1. Members whose addresses changed in the last 7 days
        # 2. Members who don't have any address display content yet
        members_with_addresses = frappe.db.sql(
            """
            SELECT name, primary_address, full_name, address_last_updated
            FROM `tabMember`
            WHERE primary_address IS NOT NULL
            AND primary_address != ''
            AND status IN ('Active', 'Pending')
            AND (
                address_last_updated >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                OR other_members_at_address IS NULL
                OR other_members_at_address = ''
            )
            ORDER BY address_last_updated DESC, modified DESC
        """,
            as_dict=True,
        )

        if not members_with_addresses:
            frappe.logger().info("No members need address display updates")
            return {"status": "success", "refreshed_count": 0}

        frappe.logger().info(f"Found {len(members_with_addresses)} members needing address display updates")

        refreshed_count = 0
        error_count = 0
        rate_limit_count = 0

        # Process in smaller batches with rate limiting awareness
        batch_size = 15  # Reduced batch size to avoid rate limits
        for i in range(0, len(members_with_addresses), batch_size):
            batch = members_with_addresses[i : i + batch_size]

            for member_data in batch:
                try:
                    # Load the member document
                    member = frappe.get_doc("Member", member_data["name"])

                    # Update the HTML display field
                    member.update_other_members_at_address_display(save_to_db=True)

                    refreshed_count += 1

                    if refreshed_count % 10 == 0:
                        frappe.logger().info(f"Refreshed {refreshed_count} member displays so far...")

                except Exception as e:
                    error_str = str(e)

                    # Check for rate limiting errors
                    if "Rate limit exceeded" in error_str:
                        rate_limit_count += 1
                        frappe.logger().warning(
                            f"Rate limit hit for member {member_data['name']}, will retry in next run"
                        )

                        # If we hit rate limits frequently, add a delay
                        if rate_limit_count > 3:
                            frappe.logger().info("Multiple rate limits hit, adding delay between requests")
                            import time

                            time.sleep(2)  # 2 second delay
                    else:
                        error_count += 1
                        frappe.log_error(
                            f"Error refreshing address display for member {member_data['name']}: {error_str}",
                            "Address Display Refresh",
                        )

            # Add small delay between batches to respect rate limits
            if i + batch_size < len(members_with_addresses):
                import time

                time.sleep(0.5)  # Half second delay between batches

        result = {
            "status": "success",
            "refreshed_count": refreshed_count,
            "error_count": error_count,
            "rate_limit_count": rate_limit_count,
            "total_processed": len(members_with_addresses),
            "optimization_note": f"Processed only changed addresses (last 7 days) or missing displays instead of all {frappe.db.count('Member', {'primary_address': ['!=', ''], 'status': ['in', ['Active', 'Pending']]})} members",
            "completion_time": now(),
        }

        frappe.logger().info(f"Address display refresh completed: {result}")
        return result

    except Exception as e:
        frappe.log_error(f"Fatal error in address display refresh task: {str(e)}", "Address Refresh Task")
        return {"status": "error", "error": str(e)}


def cleanup_orphaned_address_data():
    """
    Monthly task to clean up computed address fields for members without addresses.

    This maintenance task ensures that members who no longer have primary addresses
    get their computed fields cleared to maintain data consistency.

    Scheduled to run monthly on the 1st at 4:00 AM.
    """
    try:
        frappe.logger().info("Starting monthly address data cleanup task")

        # Find members with computed fields but no primary address
        orphaned_members = frappe.db.sql(
            """
            SELECT name, full_name
            FROM `tabMember`
            WHERE (primary_address IS NULL OR primary_address = '')
            AND (
                address_fingerprint IS NOT NULL
                OR normalized_address_line IS NOT NULL
                OR normalized_city IS NOT NULL
                OR address_last_updated IS NOT NULL
            )
        """,
            as_dict=True,
        )

        if not orphaned_members:
            frappe.logger().info("No orphaned address data found")
            return {"status": "success", "cleaned_count": 0}

        frappe.logger().info(f"Cleaning orphaned address data for {len(orphaned_members)} members")

        cleaned_count = 0

        for member_data in orphaned_members:
            try:
                # Clear computed fields
                frappe.db.set_value(
                    "Member",
                    member_data["name"],
                    {
                        "address_fingerprint": None,
                        "normalized_address_line": None,
                        "normalized_city": None,
                        "address_last_updated": None,
                        "other_members_at_address": "",
                    },
                )

                cleaned_count += 1

            except Exception as e:
                frappe.log_error(
                    f"Error cleaning address data for member {member_data['name']}: {str(e)}",
                    "Address Cleanup",
                )

        frappe.db.commit()

        result = {
            "status": "success",
            "cleaned_count": cleaned_count,
            "total_processed": len(orphaned_members),
            "completion_time": now(),
        }

        frappe.logger().info(f"Address data cleanup completed: {result}")
        return result

    except Exception as e:
        frappe.log_error(f"Fatal error in address cleanup task: {str(e)}", "Address Cleanup Task")
        return {"status": "error", "error": str(e)}
