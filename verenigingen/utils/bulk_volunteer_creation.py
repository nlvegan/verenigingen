"""
Bulk Volunteer Creation Utility

Efficient batch processing for creating volunteer records during CSV imports.
Optimized for handling 500-6000 member records.
"""

from typing import Any, Dict, List

import frappe
from frappe import _
from frappe.utils import today

# Resource protection limits
MAX_BATCH_SIZE = 500
MAX_TOTAL_MEMBERS = 10000


def bulk_create_volunteers_for_members(member_names: List[str], batch_size: int = 100) -> Dict[str, Any]:
    """
    Create volunteer records in bulk for a list of members.

    Args:
        member_names: List of member document names
        batch_size: Number of volunteers to process in each batch (default 100)

    Returns:
        dict: Results with counts and errors
    """
    if not member_names:
        return {"success": True, "created": 0, "skipped": 0, "errors": []}

    # Validate batch size limits
    if batch_size > MAX_BATCH_SIZE:
        frappe.throw(_(f"Batch size cannot exceed {MAX_BATCH_SIZE} for resource protection"))

    if len(member_names) > MAX_TOTAL_MEMBERS:
        frappe.throw(_(f"Cannot process more than {MAX_TOTAL_MEMBERS} members in single operation"))

    results = {"success": True, "created": 0, "skipped": 0, "errors": [], "total_members": len(member_names)}

    frappe.logger().info(f"Starting bulk volunteer creation for {len(member_names)} members")

    # Process in batches to avoid memory issues
    for i in range(0, len(member_names), batch_size):
        batch = member_names[i : i + batch_size]
        batch_results = _process_volunteer_batch(batch)

        results["created"] += batch_results["created"]
        results["skipped"] += batch_results["skipped"]
        results["errors"].extend(batch_results["errors"])

        # Commit after each batch to avoid long transactions
        frappe.db.commit()

        frappe.logger().info(
            f"Processed volunteer batch {i // batch_size + 1}: "
            f"{batch_results['created']} created, {batch_results['skipped']} skipped"
        )

    if results["errors"]:
        results["success"] = False

    frappe.logger().info(
        f"Bulk volunteer creation completed: {results['created']} created, "
        f"{results['skipped']} skipped, {len(results['errors'])} errors"
    )

    return results


def _process_volunteer_batch(member_names: List[str]) -> Dict[str, Any]:
    """Process a single batch of volunteer creations"""
    batch_results = {"created": 0, "skipped": 0, "errors": []}

    # Fetch all members in batch with required fields
    members = frappe.get_all(
        "Member",
        filters={"name": ["in", member_names]},
        fields=["name", "full_name", "first_name", "last_name", "email", "birth_date", "status"],
    )

    # Check for existing volunteers in batch
    existing_volunteers = set()
    if members:
        existing_check = frappe.get_all(
            "Volunteer", filters={"member": ["in", [m.name for m in members]]}, pluck="member"
        )
        existing_volunteers = set(existing_check)

    for member_data in members:
        try:
            # Skip if volunteer already exists
            if member_data.name in existing_volunteers:
                batch_results["skipped"] += 1
                continue

            # Skip if member is not active
            if member_data.status not in ["Active", "Approved"]:
                batch_results["skipped"] += 1
                continue

            # Validate age requirement (must be 16+)
            if member_data.birth_date:
                from dateutil.relativedelta import relativedelta
                from frappe.utils import getdate

                age = relativedelta(getdate(today()), getdate(member_data.birth_date)).years
                if age < 16:
                    batch_results["skipped"] += 1
                    batch_results["errors"].append(
                        f"Member {member_data.name}: Too young for volunteer (age {age})"
                    )
                    continue

            # Create volunteer record
            volunteer_name = (
                member_data.full_name or f"{member_data.first_name} {member_data.last_name}".strip()
            )
            if not volunteer_name:
                volunteer_name = member_data.email

            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": volunteer_name,
                    "member": member_data.name,
                    "email": member_data.email,
                    "status": "New",
                    "start_date": today(),
                }
            )

            # Set workflow flag only (no permission bypass)
            volunteer.flags.ignore_workflow = True

            volunteer.insert()
            batch_results["created"] += 1

        except Exception as e:
            batch_results["errors"].append(f"Member {member_data.name}: {str(e)}")
            frappe.logger().error(f"Failed to create volunteer for {member_data.name}: {str(e)}")

    return batch_results


@frappe.whitelist()
def create_volunteers_for_import_with_members(member_names: List[str]) -> Dict[str, Any]:
    """
    Create volunteers for a specific list of members.

    Note: This is a direct API method. The CSV import flow calls
    bulk_create_volunteers_for_members() directly with the processed_members list.

    Args:
        member_names: List of member names to create volunteers for

    Returns:
        dict: Results of volunteer creation
    """
    # Permission check - requires admin access for bulk operations
    if not frappe.has_permission("Volunteer", "create"):
        frappe.throw(_("Insufficient permissions to create volunteer records"))

    if not member_names:
        return {"success": True, "message": "No members provided"}

    try:
        results = bulk_create_volunteers_for_members(member_names)
        return results

    except Exception as e:
        frappe.log_error(f"Failed to create volunteers: {str(e)}")
        return {"success": False, "error": str(e)}
