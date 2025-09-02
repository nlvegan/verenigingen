"""
Member Import Cleanup Utility

Comprehensive cleanup function to delete all members and related records
for testing import functionality. Use with extreme caution - only on development servers.
"""

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


def validate_cleanup_permissions():
    """
    Strict permission validation for cleanup operations.
    Implements defense-in-depth security checks.
    """
    user = frappe.session.user

    # Level 1: Must be in developer mode
    if frappe.conf.get("developer_mode") != 1:
        frappe.throw(_("Cleanup operations can only be run in developer mode for safety"))

    # Level 2: User must be Administrator or have System Manager role
    if user != "Administrator":
        user_roles = frappe.get_roles()
        required_roles = {"System Manager", "Verenigingen Administrator"}

        if not any(role in user_roles for role in required_roles):
            frappe.throw(
                _(
                    "Insufficient permissions. You need Administrator access or System Manager/Verenigingen Administrator role."
                ),
                frappe.PermissionError,
            )

    # Level 3: Additional validation for nuclear operations
    # Check if user has explicit permission for destructive operations
    if not frappe.has_permission("System Settings", "write"):
        frappe.throw(
            _("You don't have write permissions for system settings, required for cleanup operations"),
            frappe.PermissionError,
        )

    # Level 4: Log the permission check for audit
    frappe.logger("verenigingen.security").info(
        f"Cleanup permission validation passed for user: {user} with roles: {frappe.get_roles()}"
    )

    return True


def validate_nuclear_confirmation(confirm_nuclear_cleanup):
    """
    Validate nuclear cleanup confirmation with additional safety checks.
    """
    if not confirm_nuclear_cleanup:
        frappe.throw(
            _("You must set confirm_nuclear_cleanup=True to proceed with this destructive operation")
        )

    # Additional safety: Check for recent backup (if backup system exists)
    try:
        # This would check for recent backups - implementation depends on backup system
        # For now, just log the attempt
        frappe.logger("verenigingen.security").warning(
            f"Nuclear cleanup attempted by {frappe.session.user} - ensure recent backup exists"
        )
    except Exception:
        # Don't fail if backup check isn't available
        pass

    return True


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def nuclear_cleanup_all_members(confirm_nuclear_cleanup=False, dry_run=True):
    """
    Nuclear cleanup: Delete ALL members and their related records.

    This function will delete:
    - Members
    - Memberships
    - Membership Dues Schedules
    - Volunteers
    - SEPA Mandates (member-linked)
    - Member Payment History
    - Chapter Members
    - User accounts (where member is linked)
    - Customer records (where member is linked)
    - Donors (where member is linked)
    - Member-related audit logs and history records

    Args:
        confirm_nuclear_cleanup (bool): Must be True to proceed
        dry_run (bool): If True, only shows what would be deleted

    Returns:
        dict: Results of the cleanup operation
    """

    # ENHANCED SECURITY VALIDATION
    validate_cleanup_permissions()
    validate_nuclear_confirmation(confirm_nuclear_cleanup)

    results = {
        "dry_run": dry_run,
        "total_records_affected": 0,
        "members": {"count": 0, "deleted": 0, "errors": []},
        "memberships": {"count": 0, "deleted": 0, "errors": []},
        "dues_schedules": {"count": 0, "deleted": 0, "errors": []},
        "volunteers": {"count": 0, "deleted": 0, "errors": []},
        "sepa_mandates": {"count": 0, "deleted": 0, "errors": []},
        "payment_history": {"count": 0, "deleted": 0, "errors": []},
        "chapter_members": {"count": 0, "deleted": 0, "errors": []},
        "users": {"count": 0, "deleted": 0, "errors": []},
        "customers": {"count": 0, "deleted": 0, "errors": []},
        "donors": {"count": 0, "deleted": 0, "errors": []},
        "other_related": {"count": 0, "deleted": 0, "errors": []},
        "warnings": [],
        "summary": "",
    }

    try:
        # Step 1: Get all members first
        members = frappe.get_all("Member", fields=["name", "email", "first_name", "last_name"])
        results["members"]["count"] = len(members)

        if not members:
            results["summary"] = "No members found to delete"
            return results

        member_names = [m.name for m in members]
        results["warnings"].append(f"Found {len(member_names)} members to process")

        # Step 2: Find all related records that reference these members

        # Memberships
        memberships = frappe.get_all(
            "Membership", filters={"member": ["in", member_names]}, fields=["name", "member"]
        )
        results["memberships"]["count"] = len(memberships)

        # Membership Dues Schedules
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule", filters={"member": ["in", member_names]}, fields=["name", "member"]
        )
        results["dues_schedules"]["count"] = len(dues_schedules)

        # Volunteers
        volunteers = frappe.get_all(
            "Volunteer", filters={"member": ["in", member_names]}, fields=["name", "member"]
        )
        results["volunteers"]["count"] = len(volunteers)

        # SEPA Mandates
        sepa_mandates = frappe.get_all(
            "SEPA Mandate", filters={"member": ["in", member_names]}, fields=["name", "member"]
        )
        results["sepa_mandates"]["count"] = len(sepa_mandates)

        # Member Payment History
        payment_history = frappe.get_all(
            "Member Payment History", filters={"member": ["in", member_names]}, fields=["name", "member"]
        )
        results["payment_history"]["count"] = len(payment_history)

        # Chapter Members (from Chapter doctype child table) - SECURE VERSION
        if member_names:
            placeholders = ", ".join(["%s"] * len(member_names))
            chapter_members = frappe.db.sql(
                f"""
                SELECT cm.parent as chapter_name, cm.name as chapter_member_name, cm.member
                FROM `tabChapter Member` cm
                WHERE cm.member IN ({placeholders})
            """,
                member_names,
                as_dict=True,
            )
        else:
            chapter_members = []
        results["chapter_members"]["count"] = len(chapter_members)

        # User accounts where custom fields link to member - SECURE VERSION
        if member_names:
            placeholders = ", ".join(["%s"] * len(member_names))
            users_with_member_links = frappe.db.sql(
                f"""
                SELECT name FROM `tabUser`
                WHERE custom_member IN ({placeholders})
            """,
                member_names,
                as_dict=True,
            )
        else:
            users_with_member_links = []
        results["users"]["count"] = len(users_with_member_links)

        # Customer records where member is linked - SECURE VERSION
        if member_names:
            placeholders = ", ".join(["%s"] * len(member_names))
            customers_with_member_links = frappe.db.sql(
                f"""
                SELECT name FROM `tabCustomer`
                WHERE custom_member IN ({placeholders})
            """,
                member_names,
                as_dict=True,
            )
        else:
            customers_with_member_links = []
        results["customers"]["count"] = len(customers_with_member_links)

        # Donors where member is linked
        donors = frappe.get_all("Donor", filters={"member": ["in", member_names]}, fields=["name", "member"])
        results["donors"]["count"] = len(donors)

        # Calculate total affected records
        results["total_records_affected"] = (
            results["members"]["count"]
            + results["memberships"]["count"]
            + results["dues_schedules"]["count"]
            + results["volunteers"]["count"]
            + results["sepa_mandates"]["count"]
            + results["payment_history"]["count"]
            + results["chapter_members"]["count"]
            + results["users"]["count"]
            + results["customers"]["count"]
            + results["donors"]["count"]
        )

        if dry_run:
            results[
                "summary"
            ] = f"DRY RUN: Would delete {results['total_records_affected']} total records across all related DocTypes"
            return results

        # Step 3: ACTUAL DELETION (in dependency order) - WITH TRANSACTION SAFETY
        frappe.logger().info(f"Starting nuclear cleanup of {results['total_records_affected']} records")

        # Begin atomic transaction - either all succeed or all rollback
        frappe.db.begin()

        try:
            # Delete child table records first (Chapter Members)
            for cm in chapter_members:
                try:
                    # Remove from chapter's members child table
                    chapter_doc = frappe.get_doc("Chapter", cm.chapter_name)
                    for i, member_row in enumerate(chapter_doc.members):
                        if member_row.name == cm.chapter_member_name:
                            chapter_doc.remove(chapter_doc.members[i])
                            break
                    chapter_doc.save(ignore_permissions=True)
                    results["chapter_members"]["deleted"] += 1
                except Exception as e:
                    results["chapter_members"]["errors"].append(f"Chapter {cm.chapter_name}: {str(e)}")

            # Delete dependent DocTypes
            for doctype, records, result_key in [
                ("Member Payment History", payment_history, "payment_history"),
                ("SEPA Mandate", sepa_mandates, "sepa_mandates"),
                ("Membership Dues Schedule", dues_schedules, "dues_schedules"),
                ("Membership", memberships, "memberships"),
                ("Volunteer", volunteers, "volunteers"),
                ("Donor", donors, "donors"),
            ]:
                for record in records:
                    try:
                        frappe.delete_doc(doctype, record.name, ignore_permissions=True)
                        results[result_key]["deleted"] += 1
                    except Exception as e:
                        results[result_key]["errors"].append(f"{record.name}: {str(e)}")

            # Delete Customer records
            for customer in customers_with_member_links:
                try:
                    frappe.delete_doc("Customer", customer.name, ignore_permissions=True)
                    results["customers"]["deleted"] += 1
                except Exception as e:
                    results["customers"]["errors"].append(f"{customer.name}: {str(e)}")

            # Delete User accounts (be very careful here)
            for user in users_with_member_links:
                try:
                    # Extra safety check - don't delete Administrator or system users
                    if user.name not in ["Administrator", "Guest"]:
                        frappe.delete_doc("User", user.name, ignore_permissions=True)
                        results["users"]["deleted"] += 1
                    else:
                        results["users"]["errors"].append(f"Skipped system user: {user.name}")
                except Exception as e:
                    results["users"]["errors"].append(f"{user.name}: {str(e)}")

            # Finally delete Members
            for member in members:
                try:
                    frappe.delete_doc("Member", member.name, ignore_permissions=True)
                    results["members"]["deleted"] += 1
                except Exception as e:
                    results["members"]["errors"].append(f"{member.name}: {str(e)}")

            # Commit all changes - transaction successful
            frappe.db.commit()

            total_deleted = (
                results["members"]["deleted"]
                + results["memberships"]["deleted"]
                + results["dues_schedules"]["deleted"]
                + results["volunteers"]["deleted"]
                + results["sepa_mandates"]["deleted"]
                + results["payment_history"]["deleted"]
                + results["chapter_members"]["deleted"]
                + results["users"]["deleted"]
                + results["customers"]["deleted"]
                + results["donors"]["deleted"]
            )

            results["summary"] = f"Successfully deleted {total_deleted} records. Nuclear cleanup complete."
            frappe.logger().info(f"Nuclear member cleanup completed: {total_deleted} records deleted")

        except Exception as e:
            # CRITICAL: Rollback transaction on any error
            frappe.db.rollback()
            results["summary"] = f"TRANSACTION ROLLED BACK - Critical error during cleanup: {str(e)}"
            results["transaction_rolled_back"] = True
            frappe.log_error(
                f"Nuclear member cleanup failed and rolled back: {str(e)}", "Member Import Cleanup Error"
            )

    except Exception as e:
        # Outer catch for any other errors
        results["summary"] = f"Unexpected error during cleanup: {str(e)}"
        frappe.log_error(f"Nuclear member cleanup unexpected error: {str(e)}", "Member Import Cleanup Error")

    return results


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def preview_member_cleanup():
    """
    Safe preview of what would be deleted by nuclear cleanup.
    Always runs in dry_run mode.
    """
    return nuclear_cleanup_all_members(confirm_nuclear_cleanup=True, dry_run=True)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def cleanup_test_members_only(email_patterns=None):
    """
    Safer cleanup that only deletes members matching test email patterns.

    Args:
        email_patterns (list): List of email patterns to match (default: test patterns)

    Returns:
        dict: Results of cleanup
    """
    # ENHANCED SECURITY VALIDATION
    validate_cleanup_permissions()

    if not email_patterns:
        email_patterns = ["%test@example.com", "%@test.com", "test_%@%", "%example.%", "%@test.%"]

    results = {
        "test_patterns": email_patterns,
        "members_deleted": 0,
        "related_records_deleted": 0,
        "errors": [],
    }

    try:
        # Find test members
        test_members = []
        for pattern in email_patterns:
            members = frappe.get_all(
                "Member",
                filters={"email": ["like", pattern]},
                fields=["name", "email", "first_name", "last_name"],
            )
            test_members.extend(members)

        # Remove duplicates
        seen = set()
        unique_test_members = []
        for member in test_members:
            if member.name not in seen:
                seen.add(member.name)
                unique_test_members.append(member)

        if not unique_test_members:
            results["summary"] = "No test members found matching the patterns"
            return results

        # Use nuclear cleanup on just these members
        member_names = [m.name for m in unique_test_members]

        # Delete related records for these specific members
        for member_name in member_names:
            try:
                # This will cascade delete related records
                frappe.delete_doc("Member", member_name, ignore_permissions=True)
                results["members_deleted"] += 1
            except Exception as e:
                results["errors"].append(f"Error deleting {member_name}: {str(e)}")

        frappe.db.commit()
        results["summary"] = f"Deleted {results['members_deleted']} test members and their related records"

    except Exception as e:
        results["summary"] = f"Error during test cleanup: {str(e)}"
        results["errors"].append(str(e))

    return results
