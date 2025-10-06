"""
Bulk Chapter Assignment Utility

Efficient batch processing for assigning members to chapters during CSV imports.
Optimized for handling 500-6000 member records with minimal database overhead.
"""

from typing import Any, Dict, List, Set

import frappe
from frappe import _

# Resource protection limits
MAX_BATCH_SIZE = 500
MAX_TOTAL_MEMBERS = 10000


def bulk_assign_members_to_chapters(
    member_postal_codes: Dict[str, str], batch_size: int = 200
) -> Dict[str, Any]:
    """
    Assign members to chapters in bulk based on postal codes.

    Args:
        member_postal_codes: Dict mapping member names to their postal codes
        batch_size: Number of members to process in each batch (default 200)

    Returns:
        dict: Results with counts and errors
    """
    if not member_postal_codes:
        return {"success": True, "assigned": 0, "skipped": 0, "errors": []}

    # Validate batch size limits
    if batch_size > MAX_BATCH_SIZE:
        frappe.throw(_(f"Batch size cannot exceed {MAX_BATCH_SIZE} for resource protection"))

    if len(member_postal_codes) > MAX_TOTAL_MEMBERS:
        frappe.throw(_(f"Cannot process more than {MAX_TOTAL_MEMBERS} members in single operation"))

    results = {
        "success": True,
        "assigned": 0,
        "skipped": 0,
        "errors": [],
        "total_members": len(member_postal_codes),
        "chapters_updated": set(),
    }

    frappe.logger().info(f"Starting bulk chapter assignment for {len(member_postal_codes)} members")

    # Load chapter lookup once for all batches
    from verenigingen.utils.optimized_chapter_lookup import get_lookup_instance

    lookup = get_lookup_instance()

    # Group members by their target chapter to minimize chapter doc updates
    chapter_member_map = {}  # {chapter_name: [member_names]}

    for member_name, postal_code in member_postal_codes.items():
        if not postal_code:
            results["skipped"] += 1
            continue

        # Find best chapter for this postal code
        best_chapter = lookup.find_best_chapter_for_postal_code(postal_code)

        if not best_chapter:
            results["skipped"] += 1
            results["errors"].append(f"Member {member_name}: No chapter found for postal code {postal_code}")
            continue

        if best_chapter not in chapter_member_map:
            chapter_member_map[best_chapter] = []

        chapter_member_map[best_chapter].append(member_name)

    # Process each chapter's members in batch
    for chapter_name, member_names in chapter_member_map.items():
        # Retry with exponential backoff for deadlock errors
        max_retries = 3
        retry_delay = 0.1  # Start with 100ms

        for attempt in range(max_retries):
            try:
                batch_results = _assign_members_to_chapter_batch(chapter_name, member_names)
                results["assigned"] += batch_results["assigned"]
                results["skipped"] += batch_results["skipped"]
                results["errors"].extend(batch_results["errors"])

                if batch_results["assigned"] > 0:
                    results["chapters_updated"].add(chapter_name)

                # Commit after each chapter to avoid long transactions
                frappe.db.commit()

                frappe.logger().info(
                    f"Assigned {batch_results['assigned']} members to chapter {chapter_name}"
                )
                break  # Success - exit retry loop

            except Exception as e:
                error_str = str(e)
                # Check if it's a deadlock error (MySQL error 1213)
                is_deadlock = "1213" in error_str or "Deadlock" in error_str

                if is_deadlock and attempt < max_retries - 1:
                    # Rollback and retry with exponential backoff
                    frappe.db.rollback()
                    import time

                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    frappe.logger().warning(
                        f"Deadlock detected for chapter {chapter_name}, retrying (attempt {attempt + 2}/{max_retries})..."
                    )
                else:
                    # Final attempt failed or non-deadlock error
                    frappe.db.rollback()
                    error_msg = f"Chapter {chapter_name}: Failed to assign members after {attempt + 1} attempts - {error_str}"
                    results["errors"].append(error_msg)
                    frappe.logger().error(error_msg)
                    break  # Exit retry loop

    # Convert set to list for JSON serialization
    results["chapters_updated"] = list(results["chapters_updated"])

    if results["errors"]:
        results["success"] = False

    frappe.logger().info(
        f"Bulk chapter assignment completed: {results['assigned']} assigned, "
        f"{results['skipped']} skipped, {len(results['errors'])} errors, "
        f"{len(results['chapters_updated'])} chapters updated"
    )

    return results


def _assign_members_to_chapter_batch(chapter_name: str, member_names: List[str]) -> Dict[str, Any]:
    """
    Assign a batch of members to a single chapter.

    This updates the chapter document once with all new members,
    rather than updating it individually for each member.
    """
    batch_results = {"assigned": 0, "skipped": 0, "errors": []}

    try:
        # Get chapter document
        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        # Get existing member assignments in this chapter
        existing_members = set()
        for cm in chapter_doc.members or []:
            existing_members.add(cm.member)

        # Add new members to chapter
        members_added = []
        for member_name in member_names:
            # Skip if already assigned
            if member_name in existing_members:
                batch_results["skipped"] += 1
                continue

            # Verify member exists
            if not frappe.db.exists("Member", member_name):
                batch_results["errors"].append(f"Member {member_name} not found")
                batch_results["skipped"] += 1
                continue

            # Add to chapter's members child table
            chapter_doc.append("members", {"member": member_name, "status": "Active"})

            members_added.append(member_name)
            batch_results["assigned"] += 1

        # Save chapter document once with all new members
        if members_added:
            # Suppress activity logging for bulk operations to avoid spam
            chapter_doc.flags.ignore_activity_log = True
            chapter_doc.save()

            frappe.logger().info(f"Added {len(members_added)} members to chapter {chapter_name}")

    except Exception as e:
        batch_results["errors"].append(f"Failed to update chapter {chapter_name}: {str(e)}")
        frappe.logger().error(f"Error assigning members to chapter {chapter_name}: {str(e)}")

    return batch_results


def bulk_assign_members_with_addresses(member_names: List[str], batch_size: int = 200) -> Dict[str, Any]:
    """
    Assign members to chapters based on their primary address postal codes.

    This is a convenience function that fetches postal codes from member addresses
    and then calls bulk_assign_members_to_chapters.

    Args:
        member_names: List of member document names
        batch_size: Number of members to process in each batch (default 200)

    Returns:
        dict: Results with counts and errors
    """
    if not member_names:
        return {"success": True, "assigned": 0, "skipped": 0, "errors": []}

    # Fetch members with their addresses in batches
    member_postal_codes = {}

    for i in range(0, len(member_names), batch_size):
        batch = member_names[i : i + batch_size]

        # Get members with primary address
        members = frappe.get_all(
            "Member", filters={"name": ["in", batch]}, fields=["name", "primary_address"]
        )

        # Fetch postal codes for members with addresses
        for member in members:
            if member.primary_address:
                try:
                    address = frappe.get_doc("Address", member.primary_address)
                    if address.pincode:
                        member_postal_codes[member.name] = address.pincode
                except Exception as e:
                    frappe.logger().warning(f"Could not fetch address for member {member.name}: {str(e)}")

    # Perform bulk assignment
    return bulk_assign_members_to_chapters(member_postal_codes, batch_size)


@frappe.whitelist()
def assign_chapters_for_members(member_names: List[str]) -> Dict[str, Any]:
    """
    Assign chapters for a specific list of members based on their addresses.

    Note: This is a direct API method. The CSV import flow calls
    bulk_assign_members_with_addresses() directly with the processed_members list.

    Args:
        member_names: List of member names to assign to chapters

    Returns:
        dict: Results of chapter assignment
    """
    # Permission check - requires admin access for bulk operations
    if not frappe.has_permission("Chapter", "write"):
        frappe.throw(_("Insufficient permissions to assign chapter members"))

    if not member_names:
        return {"success": True, "message": "No members provided"}

    try:
        results = bulk_assign_members_with_addresses(member_names)
        return results

    except Exception as e:
        frappe.log_error(f"Failed to assign chapters: {str(e)}")
        return {"success": False, "error": str(e)}
