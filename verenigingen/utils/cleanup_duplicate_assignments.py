"""
Cleanup script for duplicate volunteer assignment history entries

This script identifies and removes duplicate assignment history entries
that were created due to the idempotency bug in assignment_history_manager.py
"""

from collections import defaultdict

import frappe


def find_duplicate_assignments(volunteer_id=None):
    """
    Find volunteers with duplicate assignment history entries

    Args:
        volunteer_id: Optional specific volunteer to check

    Returns:
        Dict mapping volunteer_id to list of duplicate sets
    """
    if volunteer_id:
        volunteers = [volunteer_id]
    else:
        # Get all volunteers with assignment history
        volunteers = frappe.get_all("Volunteer", filters={"assignment_history": ["is", "set"]}, pluck="name")

    duplicates = {}

    for vol_id in volunteers:
        volunteer = frappe.get_doc("Volunteer", vol_id)

        # Group assignments by unique key
        assignment_groups = defaultdict(list)

        for idx, assignment in enumerate(volunteer.assignment_history or []):
            # Create unique key based on assignment characteristics
            key = (
                assignment.reference_doctype,
                assignment.reference_name,
                assignment.role,
                str(assignment.start_date),
                assignment.status,
                str(assignment.end_date) if assignment.end_date else "None",
            )
            assignment_groups[key].append((idx, assignment))

        # Find groups with duplicates
        vol_duplicates = []
        for key, assignments in assignment_groups.items():
            if len(assignments) > 1:
                vol_duplicates.append(
                    {
                        "key": key,
                        "count": len(assignments),
                        "indices": [a[0] for a in assignments],
                        "assignments": [a[1] for a in assignments],
                    }
                )

        if vol_duplicates:
            duplicates[vol_id] = vol_duplicates

    return duplicates


def clean_duplicate_assignments(volunteer_id, dry_run=True):
    """
    Remove duplicate assignment history entries for a volunteer

    Keeps the first occurrence of each duplicate set and removes the rest.

    Args:
        volunteer_id: Volunteer to clean
        dry_run: If True, only reports what would be done without making changes

    Returns:
        Dict with cleanup statistics
    """
    volunteer = frappe.get_doc("Volunteer", volunteer_id)

    duplicates = find_duplicate_assignments(volunteer_id)
    if volunteer_id not in duplicates:
        print(f"No duplicates found for volunteer {volunteer_id}")
        return {"removed": 0, "kept": 0}

    stats = {"removed": 0, "kept": 0}
    indices_to_remove = set()

    for dup_set in duplicates[volunteer_id]:
        # Keep the first one, mark rest for removal
        keep_idx = dup_set["indices"][0]
        remove_indices = dup_set["indices"][1:]

        stats["kept"] += 1
        stats["removed"] += len(remove_indices)
        indices_to_remove.update(remove_indices)

        print(f"\nDuplicate set for {volunteer_id}:")
        print(f"  Reference: {dup_set['key'][0]} - {dup_set['key'][1]}")
        print(f"  Role: {dup_set['key'][2]}")
        print(f"  Start: {dup_set['key'][3]}, End: {dup_set['key'][5]}, Status: {dup_set['key'][4]}")
        print(f"  Count: {dup_set['count']}")
        print(f"  Keeping index {keep_idx}, removing indices: {remove_indices}")

    if not dry_run and indices_to_remove:
        # Remove duplicates in reverse order to preserve indices
        new_history = []
        for idx, assignment in enumerate(volunteer.assignment_history):
            if idx not in indices_to_remove:
                new_history.append(assignment)

        # Clear and rebuild assignment history
        volunteer.assignment_history = []
        for assignment in new_history:
            volunteer.append("assignment_history", assignment.as_dict())

        # Save without triggering assignment history updates
        # Security: Admin CLI utility (bench execute) - requires direct server access
        volunteer._updating_assignment_history = True
        try:
            volunteer.save(ignore_permissions=True)
            frappe.db.commit()
            print(f"\n✓ Removed {stats['removed']} duplicate entries from {volunteer_id}")
        finally:
            volunteer._updating_assignment_history = False
    elif dry_run:
        print(f"\n[DRY RUN] Would remove {stats['removed']} duplicate entries from {volunteer_id}")

    return stats


def cleanup_all_duplicates(dry_run=True):
    """
    Clean duplicate assignments for all volunteers

    Args:
        dry_run: If True, only reports what would be done

    Returns:
        Dict with overall statistics
    """
    duplicates = find_duplicate_assignments()

    if not duplicates:
        print("No duplicate assignments found in the system!")
        return {"volunteers_processed": 0, "total_removed": 0, "total_kept": 0}

    print(f"Found {len(duplicates)} volunteers with duplicate assignments\n")

    overall_stats = {"volunteers_processed": 0, "total_removed": 0, "total_kept": 0}

    for volunteer_id in duplicates.keys():
        stats = clean_duplicate_assignments(volunteer_id, dry_run=dry_run)
        overall_stats["volunteers_processed"] += 1
        overall_stats["total_removed"] += stats["removed"]
        overall_stats["total_kept"] += stats["kept"]

    print(f"\n{'=' * 60}")
    print("Summary:")
    print(f"  Volunteers processed: {overall_stats['volunteers_processed']}")
    print(f"  Total duplicates removed: {overall_stats['total_removed']}")
    print(f"  Total assignments kept: {overall_stats['total_kept']}")

    if dry_run:
        print("\nThis was a DRY RUN. No changes were made.")
        print("Run with dry_run=False to actually remove duplicates.")

    return overall_stats


def run_cleanup_for_volunteer(volunteer_id, dry_run=True):
    """Convenience function for running cleanup on a specific volunteer"""
    return clean_duplicate_assignments(volunteer_id, dry_run=dry_run)


def run_full_cleanup(dry_run=True):
    """Convenience function for running full cleanup"""
    return cleanup_all_duplicates(dry_run=dry_run)


if __name__ == "__main__":
    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    # Run cleanup in dry-run mode first
    print("Running duplicate assignment cleanup (DRY RUN)...\n")
    cleanup_all_duplicates(dry_run=True)

    frappe.destroy()
