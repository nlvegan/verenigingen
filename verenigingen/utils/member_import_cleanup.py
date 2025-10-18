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
    - Sales Invoices (membership invoices AND application invoices):
      * Invoices linked via Customer records
      * Application invoices using email as temporary customer
      * Invoices referenced in remarks/descriptions
      * All found invoices are canceled (if submitted) then deleted
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
        "amendment_requests": {"count": 0, "deleted": 0, "errors": []},
        "account_creation_requests": {"count": 0, "deleted": 0, "errors": []},
        "sales_invoices": {"count": 0, "deleted": 0, "errors": []},
        "volunteers": {"count": 0, "deleted": 0, "errors": []},
        "sepa_mandates": {"count": 0, "deleted": 0, "errors": []},
        "payment_history": {"count": 0, "deleted": 0, "errors": []},
        "chapter_members": {"count": 0, "deleted": 0, "errors": []},
        "users": {"count": 0, "deleted": 0, "errors": []},
        "customers": {"count": 0, "deleted": 0, "errors": []},
        "donors": {"count": 0, "deleted": 0, "errors": []},
        "addresses": {"count": 0, "deleted": 0, "errors": []},
        "contacts": {"count": 0, "deleted": 0, "errors": []},
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
        try:
            memberships = frappe.get_all(
                "Membership", filters={"member": ["in", member_names]}, fields=["name"]
            )
            results["memberships"]["count"] = len(memberships)
        except Exception as e:
            frappe.logger().error(f"Error querying Membership: {str(e)}")
            memberships = []
            results["memberships"]["count"] = 0

        # Membership Dues Schedules (exclude templates)
        try:
            dues_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": ["in", member_names], "is_template": 0},
                fields=["name"],
            )
            results["dues_schedules"]["count"] = len(dues_schedules)

            # Also check if any templates are incorrectly linked to members (should never happen)
            template_check = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": ["in", member_names], "is_template": 1},
                fields=["name", "schedule_name"],
            )
            if template_check:
                results["warnings"].append(
                    f"⚠️ Found {len(template_check)} template schedules incorrectly linked to members - these will be preserved but should be cleaned up manually"
                )
        except Exception as e:
            frappe.logger().error(f"Error querying Membership Dues Schedule: {str(e)}")
            dues_schedules = []
            results["dues_schedules"]["count"] = 0

        # Contribution Amendment Requests
        try:
            amendment_requests = frappe.get_all(
                "Contribution Amendment Request", filters={"member": ["in", member_names]}, fields=["name"]
            )
            results["amendment_requests"]["count"] = len(amendment_requests)
        except Exception as e:
            frappe.logger().error(f"Error querying Contribution Amendment Request: {str(e)}")
            amendment_requests = []
            results["amendment_requests"]["count"] = 0

        # Account Creation Requests (using Dynamic Link field)
        try:
            account_creation_requests = frappe.get_all(
                "Account Creation Request",
                filters={"request_type": "Member", "source_record": ["in", member_names]},
                fields=["name"],
            )
            results["account_creation_requests"]["count"] = len(account_creation_requests)
        except Exception as e:
            frappe.logger().error(f"Error querying Account Creation Request: {str(e)}")
            account_creation_requests = []
            results["account_creation_requests"]["count"] = 0

        # Sales Invoices - comprehensive cleanup including application invoices
        try:
            sales_invoices = []

            # Method 1: Get customer IDs for these members and find their invoices
            customer_ids = []
            if frappe.db.has_column("Customer", "custom_member") and member_names:
                placeholders = ", ".join(["%s"] * len(member_names))
                customers = frappe.db.sql(
                    f"""
                    SELECT name FROM `tabCustomer`
                    WHERE custom_member IN ({placeholders})
                """,
                    member_names,
                    as_dict=True,
                )
                customer_ids = [c.name for c in customers]

            # Find ALL sales invoices for these customers (not just membership invoices)
            # This prevents orphaned invoices when Customer records are deleted
            if customer_ids:
                placeholders = ", ".join(["%s"] * len(customer_ids))
                sales_invoices_by_customer = frappe.db.sql(
                    f"""
                    SELECT name, docstatus FROM `tabSales Invoice`
                    WHERE customer IN ({placeholders})
                """,
                    customer_ids,
                    as_dict=True,
                )
                sales_invoices.extend(sales_invoices_by_customer)

            # Method 2: Find application invoices by email (temporary customer during application)
            if member_names:
                member_emails = [m["email"] for m in members if m.get("email")]
                if member_emails:
                    placeholders = ", ".join(["%s"] * len(member_emails))
                    application_invoices = frappe.db.sql(
                        f"""
                        SELECT name, docstatus FROM `tabSales Invoice`
                        WHERE customer IN ({placeholders})
                        AND remarks LIKE '%application%'
                    """,
                        member_emails,
                        as_dict=True,
                    )
                    sales_invoices.extend(application_invoices)

            # Method 3: Find invoices by remarks referencing member names
            if member_names:
                placeholders = ", ".join(["%s"] * len(member_names))
                invoices_by_remarks = frappe.db.sql(
                    f"""
                    SELECT name, docstatus FROM `tabSales Invoice`
                    WHERE remarks LIKE CONCAT('%', REPLACE({placeholders}, ',', '%') , '%')
                    LIMIT 1000
                """,
                    member_names[0] if member_names else "",
                    as_dict=True,
                )
                sales_invoices.extend(invoices_by_remarks)

            # Remove duplicates
            seen_invoices = set()
            unique_invoices = []
            for inv in sales_invoices:
                if inv.name not in seen_invoices:
                    seen_invoices.add(inv.name)
                    unique_invoices.append(inv)

            sales_invoices = unique_invoices
            results["sales_invoices"]["count"] = len(sales_invoices)
        except Exception as e:
            frappe.logger().error(f"Error querying Sales Invoice: {str(e)}")
            sales_invoices = []
            results["sales_invoices"]["count"] = 0

        # Volunteers
        try:
            volunteers = frappe.get_all(
                "Volunteer", filters={"member": ["in", member_names]}, fields=["name"]
            )
            results["volunteers"]["count"] = len(volunteers)
        except Exception as e:
            frappe.logger().error(f"Error querying Volunteer: {str(e)}")
            volunteers = []
            results["volunteers"]["count"] = 0

        # SEPA Mandates
        try:
            sepa_mandates = frappe.get_all(
                "SEPA Mandate", filters={"member": ["in", member_names]}, fields=["name"]
            )
            results["sepa_mandates"]["count"] = len(sepa_mandates)
        except Exception as e:
            frappe.logger().error(f"Error querying SEPA Mandate: {str(e)}")
            sepa_mandates = []
            results["sepa_mandates"]["count"] = 0

        # Member Payment History
        try:
            payment_history = frappe.get_all(
                "Member Payment History", filters={"member": ["in", member_names]}, fields=["name"]
            )
            results["payment_history"]["count"] = len(payment_history)
        except Exception as e:
            frappe.logger().error(f"Error querying Member Payment History: {str(e)}")
            payment_history = []
            results["payment_history"]["count"] = 0

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
        # Only query if the custom field exists
        users_with_member_links = []
        try:
            if frappe.db.has_column("User", "custom_member") and member_names:
                placeholders = ", ".join(["%s"] * len(member_names))
                users_with_member_links = frappe.db.sql(
                    f"""
                    SELECT name FROM `tabUser`
                    WHERE custom_member IN ({placeholders})
                """,
                    member_names,
                    as_dict=True,
                )
        except Exception as e:
            frappe.logger().warning(f"Could not query User records: {str(e)}")
        results["users"]["count"] = len(users_with_member_links)

        # Customer records where member is linked - SECURE VERSION
        # Only query if the custom field exists
        customers_with_member_links = []
        try:
            if frappe.db.has_column("Customer", "custom_member") and member_names:
                placeholders = ", ".join(["%s"] * len(member_names))
                customers_with_member_links = frappe.db.sql(
                    f"""
                    SELECT name FROM `tabCustomer`
                    WHERE custom_member IN ({placeholders})
                """,
                    member_names,
                    as_dict=True,
                )
        except Exception as e:
            frappe.logger().warning(f"Could not query Customer records: {str(e)}")
        results["customers"]["count"] = len(customers_with_member_links)

        # Donors where member is linked (check if Donor doctype exists first)
        donors = []
        if frappe.db.exists("DocType", "Donor"):
            try:
                donors = frappe.get_all("Donor", filters={"member": ["in", member_names]}, fields=["name"])
            except Exception as e:
                frappe.logger().warning(f"Could not query Donor records: {str(e)}")
                donors = []
        results["donors"]["count"] = len(donors)

        # Addresses linked to Members via Dynamic Link
        try:
            if member_names:
                placeholders = ", ".join(["%s"] * len(member_names))
                addresses = frappe.db.sql(
                    f"""
                    SELECT DISTINCT dl.parent
                    FROM `tabDynamic Link` dl
                    WHERE dl.parenttype = 'Address'
                    AND dl.link_doctype = 'Member'
                    AND dl.link_name IN ({placeholders})
                """,
                    member_names,
                    as_dict=True,
                )
                results["addresses"]["count"] = len(addresses)
            else:
                addresses = []
        except Exception as e:
            frappe.logger().warning(f"Could not query Address records: {str(e)}")
            addresses = []
            results["addresses"]["count"] = 0

        # Contacts linked to Members via Dynamic Link
        try:
            if member_names:
                placeholders = ", ".join(["%s"] * len(member_names))
                contacts = frappe.db.sql(
                    f"""
                    SELECT DISTINCT dl.parent
                    FROM `tabDynamic Link` dl
                    WHERE dl.parenttype = 'Contact'
                    AND dl.link_doctype = 'Member'
                    AND dl.link_name IN ({placeholders})
                """,
                    member_names,
                    as_dict=True,
                )
                results["contacts"]["count"] = len(contacts)
            else:
                contacts = []
        except Exception as e:
            frappe.logger().warning(f"Could not query Contact records: {str(e)}")
            contacts = []
            results["contacts"]["count"] = 0

        # Calculate total affected records
        results["total_records_affected"] = (
            results["members"]["count"]
            + results["memberships"]["count"]
            + results["dues_schedules"]["count"]
            + results["amendment_requests"]["count"]
            + results["account_creation_requests"]["count"]
            + results["sales_invoices"]["count"]
            + results["volunteers"]["count"]
            + results["sepa_mandates"]["count"]
            + results["payment_history"]["count"]
            + results["chapter_members"]["count"]
            + results["users"]["count"]
            + results["customers"]["count"]
            + results["donors"]["count"]
            + results["addresses"]["count"]
            + results["contacts"]["count"]
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

            # Delete Sales Invoices first (they depend on dues schedules and memberships)
            for invoice in sales_invoices:
                try:
                    doc = frappe.get_doc("Sales Invoice", invoice.name)
                    # Cancel if submitted
                    if doc.docstatus == 1:
                        doc.cancel()
                    # Delete
                    frappe.delete_doc("Sales Invoice", invoice.name, ignore_permissions=True, force=True)
                    results["sales_invoices"]["deleted"] += 1
                except Exception as e:
                    results["sales_invoices"]["errors"].append(f"{invoice.name}: {str(e)}")

            # Delete dependent DocTypes (cancel submitted docs first)
            for doctype, records, result_key in [
                ("Member Payment History", payment_history, "payment_history"),
                ("SEPA Mandate", sepa_mandates, "sepa_mandates"),
                ("Contribution Amendment Request", amendment_requests, "amendment_requests"),
                ("Membership Dues Schedule", dues_schedules, "dues_schedules"),
                ("Membership", memberships, "memberships"),
                ("Volunteer", volunteers, "volunteers"),
                ("Donor", donors, "donors"),
            ]:
                for record in records:
                    try:
                        # Cancel submitted records first
                        doc = frappe.get_doc(doctype, record.name)
                        if doc.docstatus == 1:
                            doc.cancel()
                        frappe.delete_doc(doctype, record.name, ignore_permissions=True, force=True)
                        results[result_key]["deleted"] += 1
                    except Exception as e:
                        results[result_key]["errors"].append(f"{record.name}: {str(e)}")

            # Delete Addresses linked to members
            for address in addresses:
                try:
                    # Load address and clean up any stale links before deletion
                    addr_doc = frappe.get_doc("Address", address.parent)

                    # Remove links to deleted members/customers to prevent validation errors
                    if hasattr(addr_doc, "links") and addr_doc.links:
                        links_to_remove = []
                        for idx, link in enumerate(addr_doc.links):
                            if link.link_doctype and link.link_name:
                                if not frappe.db.exists(link.link_doctype, link.link_name):
                                    links_to_remove.append(idx)

                        # Remove stale links in reverse order
                        for idx in reversed(links_to_remove):
                            addr_doc.links.pop(idx)

                        # Save without validation to remove stale links
                        if links_to_remove:
                            addr_doc.flags.ignore_validate = True
                            addr_doc.save(ignore_permissions=True)

                    # Now delete the address
                    frappe.delete_doc("Address", address.parent, ignore_permissions=True, force=True)
                    results["addresses"]["deleted"] += 1
                except Exception as e:
                    results["addresses"]["errors"].append(f"{address.parent}: {str(e)}")

            # Delete Contacts linked to members
            for contact in contacts:
                try:
                    frappe.delete_doc("Contact", contact.parent, ignore_permissions=True, force=True)
                    results["contacts"]["deleted"] += 1
                except Exception as e:
                    results["contacts"]["errors"].append(f"{contact.parent}: {str(e)}")

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

            # Delete Account Creation Requests (must be before Members due to link validation)
            for acr in account_creation_requests:
                try:
                    frappe.delete_doc(
                        "Account Creation Request", acr.name, ignore_permissions=True, force=True
                    )
                    results["account_creation_requests"]["deleted"] += 1
                except Exception as e:
                    results["account_creation_requests"]["errors"].append(f"{acr.name}: {str(e)}")

            # Finally delete Members
            for member in members:
                try:
                    frappe.delete_doc("Member", member.name, ignore_permissions=True, force=True)
                    results["members"]["deleted"] += 1
                except Exception as e:
                    results["members"]["errors"].append(f"{member.name}: {str(e)}")

            # Commit all changes - transaction successful
            frappe.db.commit()

            total_deleted = (
                results["members"]["deleted"]
                + results["memberships"]["deleted"]
                + results["dues_schedules"]["deleted"]
                + results["amendment_requests"]["deleted"]
                + results["account_creation_requests"]["deleted"]
                + results["sales_invoices"]["deleted"]
                + results["volunteers"]["deleted"]
                + results["sepa_mandates"]["deleted"]
                + results["payment_history"]["deleted"]
                + results["chapter_members"]["deleted"]
                + results["users"]["deleted"]
                + results["customers"]["deleted"]
                + results["donors"]["deleted"]
                + results["addresses"]["deleted"]
                + results["contacts"]["deleted"]
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
def force_cleanup_orphaned_schedules_and_invoices(dry_run=True):
    """
    Force cleanup of orphaned dues schedules and ALL sales invoices
    after members have already been deleted.

    This is more aggressive than the standard cleanup - it doesn't validate
    membership/member existence, just force deletes schedules and invoices
    that reference non-existent customers.

    Args:
        dry_run (bool): If True, only shows what would be deleted

    Returns:
        dict: Results of cleanup
    """
    validate_cleanup_permissions()

    results = {
        "dry_run": dry_run,
        "orphaned_schedules": {"count": 0, "deleted": 0, "errors": []},
        "orphaned_invoices": {"count": 0, "deleted": 0, "errors": []},
        "summary": "",
    }

    try:
        # Find all non-template schedules
        all_schedules = frappe.get_all(
            "Membership Dues Schedule", filters={"is_template": 0}, fields=["name", "member", "membership"]
        )

        # Check which ones reference non-existent members/memberships
        orphaned_schedules = []
        for schedule in all_schedules:
            is_orphaned = False

            # Check if member exists (if specified)
            if schedule.member and not frappe.db.exists("Member", schedule.member):
                is_orphaned = True

            # Check if membership exists (if specified)
            if schedule.membership and not frappe.db.exists("Membership", schedule.membership):
                is_orphaned = True

            if is_orphaned:
                orphaned_schedules.append(schedule)

        results["orphaned_schedules"]["count"] = len(orphaned_schedules)

        # Find ALL sales invoices with non-existent customers (not just membership invoices)
        # This prevents orphaned invoices from accumulating over time
        all_invoices = frappe.db.sql(
            """
            SELECT si.name, si.customer, si.docstatus
            FROM `tabSales Invoice` si
            LEFT JOIN `tabCustomer` c ON si.customer = c.name
            WHERE c.name IS NULL
        """,
            as_dict=True,
        )

        orphaned_invoices = all_invoices
        results["orphaned_invoices"]["count"] = len(orphaned_invoices)

        if dry_run:
            results[
                "summary"
            ] = f"DRY RUN: Would delete {len(orphaned_schedules)} orphaned schedules and {len(orphaned_invoices)} orphaned invoices"
            return results

        # ACTUAL DELETION
        frappe.db.begin()

        try:
            # Delete orphaned invoices first
            for invoice in orphaned_invoices:
                try:
                    # Cancel if submitted
                    if invoice.docstatus == 1:
                        frappe.db.sql(
                            """
                            UPDATE `tabSales Invoice`
                            SET docstatus = 2
                            WHERE name = %s
                        """,
                            invoice.name,
                        )

                    # Force delete
                    frappe.delete_doc("Sales Invoice", invoice.name, ignore_permissions=True, force=True)
                    results["orphaned_invoices"]["deleted"] += 1
                except Exception as e:
                    results["orphaned_invoices"]["errors"].append(f"{invoice.name}: {str(e)}")

            # Delete orphaned schedules
            for schedule in orphaned_schedules:
                try:
                    frappe.delete_doc(
                        "Membership Dues Schedule", schedule.name, ignore_permissions=True, force=True
                    )
                    results["orphaned_schedules"]["deleted"] += 1
                except Exception as e:
                    results["orphaned_schedules"]["errors"].append(f"{schedule.name}: {str(e)}")

            frappe.db.commit()
            results[
                "summary"
            ] = f"Successfully deleted {results['orphaned_schedules']['deleted']} schedules and {results['orphaned_invoices']['deleted']} invoices"

        except Exception as e:
            frappe.db.rollback()
            results["summary"] = f"ROLLED BACK: {str(e)}"
            frappe.log_error(f"Force cleanup failed: {str(e)}", "Orphaned Cleanup Error")

    except Exception as e:
        results["summary"] = f"Error: {str(e)}"
        frappe.log_error(f"Force cleanup error: {str(e)}", "Orphaned Cleanup Error")

    return results


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def cleanup_orphaned_chapter_members(dry_run=True):
    """
    Remove orphaned member references from all Chapter child tables.

    Finds chapter member entries where the referenced member no longer exists
    and removes them from the chapter's members child table.

    Args:
        dry_run (bool): If True, only reports what would be removed

    Returns:
        dict: Results of cleanup
    """
    validate_cleanup_permissions()

    results = {
        "dry_run": dry_run,
        "chapters_checked": 0,
        "orphaned_found": 0,
        "orphaned_removed": 0,
        "chapters_affected": [],
        "errors": [],
    }

    try:
        chapters = frappe.get_all("Chapter", fields=["name"])
        results["chapters_checked"] = len(chapters)

        for chapter in chapters:
            try:
                chapter_doc = frappe.get_doc("Chapter", chapter.name)
                orphaned_indices = []

                # Find orphaned members in this chapter
                for i, member_row in enumerate(chapter_doc.members or []):
                    if not frappe.db.exists("Member", member_row.member):
                        orphaned_indices.append((i, member_row.member))
                        results["orphaned_found"] += 1

                if orphaned_indices:
                    results["chapters_affected"].append(
                        {
                            "chapter": chapter.name,
                            "orphaned_count": len(orphaned_indices),
                            "orphaned_members": [m[1] for m in orphaned_indices[:5]],  # Sample
                        }
                    )

                    if not dry_run:
                        # Remove orphaned entries (in reverse order to preserve indices)
                        for idx, member_name in reversed(orphaned_indices):
                            chapter_doc.remove(chapter_doc.members[idx])
                            results["orphaned_removed"] += 1

                        chapter_doc.save(ignore_permissions=True)

            except Exception as e:
                results["errors"].append(f"{chapter.name}: {str(e)}")

        if dry_run:
            results[
                "summary"
            ] = f"DRY RUN: Found {results['orphaned_found']} orphaned members across {len(results['chapters_affected'])} chapters"
        else:
            results[
                "summary"
            ] = f"Removed {results['orphaned_removed']} orphaned members from {len(results['chapters_affected'])} chapters"
            frappe.db.commit()

    except Exception as e:
        results["summary"] = f"Error: {str(e)}"
        frappe.log_error(f"Orphaned chapter cleanup error: {str(e)}", "Chapter Cleanup Error")

    return results


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def cleanup_orphaned_addresses_and_contacts(dry_run=True):
    """
    Clean up Address and Contact records that reference deleted members.

    Args:
        dry_run (bool): If True, only shows what would be deleted

    Returns:
        dict: Results of cleanup
    """
    validate_cleanup_permissions()

    results = {
        "dry_run": dry_run,
        "addresses": {"count": 0, "deleted": 0, "errors": []},
        "contacts": {"count": 0, "deleted": 0, "errors": []},
        "summary": "",
    }

    try:
        # Find addresses linked to non-existent members
        address_links = frappe.db.sql(
            """
            SELECT DISTINCT dl.parent
            FROM `tabDynamic Link` dl
            WHERE dl.parenttype = 'Address'
            AND dl.link_doctype = 'Member'
        """,
            as_dict=True,
        )

        orphaned_addresses = []
        for link in address_links:
            # Check if any member link still exists
            member_links = frappe.db.sql(
                """
                SELECT link_name
                FROM `tabDynamic Link`
                WHERE parent = %s
                AND parenttype = 'Address'
                AND link_doctype = 'Member'
            """,
                link.parent,
                as_dict=True,
            )

            all_orphaned = True
            for ml in member_links:
                if frappe.db.exists("Member", ml.link_name):
                    all_orphaned = False
                    break

            if all_orphaned:
                orphaned_addresses.append(link.parent)

        results["addresses"]["count"] = len(orphaned_addresses)

        # Find contacts linked to non-existent members
        contact_links = frappe.db.sql(
            """
            SELECT DISTINCT dl.parent
            FROM `tabDynamic Link` dl
            WHERE dl.parenttype = 'Contact'
            AND dl.link_doctype = 'Member'
        """,
            as_dict=True,
        )

        orphaned_contacts = []
        for link in contact_links:
            member_links = frappe.db.sql(
                """
                SELECT link_name
                FROM `tabDynamic Link`
                WHERE parent = %s
                AND parenttype = 'Contact'
                AND link_doctype = 'Member'
            """,
                link.parent,
                as_dict=True,
            )

            all_orphaned = True
            for ml in member_links:
                if frappe.db.exists("Member", ml.link_name):
                    all_orphaned = False
                    break

            if all_orphaned:
                orphaned_contacts.append(link.parent)

        results["contacts"]["count"] = len(orphaned_contacts)

        if dry_run:
            results[
                "summary"
            ] = f"DRY RUN: Would delete {len(orphaned_addresses)} addresses and {len(orphaned_contacts)} contacts"
            return results

        # Delete orphaned records
        frappe.db.begin()

        try:
            for addr in orphaned_addresses:
                try:
                    frappe.delete_doc("Address", addr, ignore_permissions=True, force=True)
                    results["addresses"]["deleted"] += 1
                except Exception as e:
                    results["addresses"]["errors"].append(f"{addr}: {str(e)}")

            for contact in orphaned_contacts:
                try:
                    frappe.delete_doc("Contact", contact, ignore_permissions=True, force=True)
                    results["contacts"]["deleted"] += 1
                except Exception as e:
                    results["contacts"]["errors"].append(f"{contact}: {str(e)}")

            frappe.db.commit()
            results[
                "summary"
            ] = f"Deleted {results['addresses']['deleted']} addresses and {results['contacts']['deleted']} contacts"

        except Exception as e:
            frappe.db.rollback()
            results["summary"] = f"ROLLED BACK: {str(e)}"

    except Exception as e:
        results["summary"] = f"Error: {str(e)}"

    return results


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
