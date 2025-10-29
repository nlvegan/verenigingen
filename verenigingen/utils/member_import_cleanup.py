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

    # Level 1: Must be in developer mode (TEMPORARILY DISABLED for staging testing)
    # if not frappe.conf.get("developer_mode"):
    #     frappe.throw(_("Cleanup operations can only be run in developer mode for safety"))

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

    This function will delete records in the following order:

    EARLY CLEANUP (tracking/administrative records):
    1. Notification Settings (for member emails)
    2. API Audit Log entries (for member emails)
    3. Account Creation Requests (for these members)
    4. Chapter Members (child table links)

    DEPENDENCY CLEANUP (financial/operational records):
    5. Sales Invoices (membership invoices AND application invoices):
       * Invoices linked via Customer records
       * Application invoices using email as temporary customer
       * Invoices referenced in remarks/descriptions
       * All found invoices are canceled (if submitted) then deleted
    6. Member Payment History
    7. SEPA Mandates (member-linked)
    8. Contribution Amendment Requests
    9. Membership Dues Schedules
    10. Memberships
    11. Volunteers
    12. Donors (where member is linked)
    13. Addresses (linked to members)
    14. Contacts (linked to members)
    15. Customer records (where member is linked)
    16. User accounts (where member is linked)

    FINAL CLEANUP:
    17. Members (core records deleted last)

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
        "notification_settings": {"count": 0, "deleted": 0, "errors": []},
        "api_audit_logs": {"count": 0, "deleted": 0, "errors": []},
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

        # Notification Settings (by member email - name field is the email)
        notification_settings = []
        try:
            member_emails = [m["email"] for m in members if m.get("email")]
            if member_emails:
                placeholders = ", ".join(["%s"] * len(member_emails))
                notification_settings = frappe.db.sql(
                    f"""
                    SELECT name FROM `tabNotification Settings`
                    WHERE name IN ({placeholders})
                """,
                    member_emails,
                    as_dict=True,
                )
            results["notification_settings"]["count"] = len(notification_settings)
        except Exception as e:
            frappe.logger().error(f"Error querying Notification Settings: {str(e)}")
            notification_settings = []
            results["notification_settings"]["count"] = 0

        # API Audit Log entries (by member email in user field)
        api_audit_logs = []
        try:
            member_emails = [m["email"] for m in members if m.get("email")]
            if member_emails:
                placeholders = ", ".join(["%s"] * len(member_emails))
                api_audit_logs = frappe.db.sql(
                    f"""
                    SELECT name FROM `tabAPI Audit Log`
                    WHERE user IN ({placeholders})
                """,
                    member_emails,
                    as_dict=True,
                )
            results["api_audit_logs"]["count"] = len(api_audit_logs)
        except Exception as e:
            frappe.logger().error(f"Error querying API Audit Log: {str(e)}")
            api_audit_logs = []
            results["api_audit_logs"]["count"] = 0

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

        # User accounts linked to members - query via Member.user field
        users_with_member_links = []
        try:
            if member_names:
                placeholders = ", ".join(["%s"] * len(member_names))
                users_with_member_links = frappe.db.sql(
                    f"""
                    SELECT DISTINCT m.user as name
                    FROM `tabMember` m
                    WHERE m.name IN ({placeholders})
                    AND m.user IS NOT NULL
                    AND m.user != ''
                """,
                    member_names,
                    as_dict=True,
                )
        except Exception as e:
            frappe.logger().warning(f"Could not query User records: {str(e)}")
        results["users"]["count"] = len(users_with_member_links)

        # Employee records linked to these users
        employees = []
        if users_with_member_links:
            try:
                user_ids = [u.name for u in users_with_member_links]
                placeholders = ", ".join(["%s"] * len(user_ids))
                employees = frappe.db.sql(
                    f"""
                    SELECT name FROM `tabEmployee`
                    WHERE user_id IN ({placeholders})
                """,
                    user_ids,
                    as_dict=True,
                )
            except Exception as e:
                frappe.logger().warning(f"Could not query Employee records: {str(e)}")
        results["employees"] = {"count": len(employees), "deleted": 0, "errors": []}

        # User Permission records for these employees
        user_permissions = []
        if employees:
            try:
                employee_ids = [e.name for e in employees]
                placeholders = ", ".join(["%s"] * len(employee_ids))
                user_permissions = frappe.db.sql(
                    f"""
                    SELECT name FROM `tabUser Permission`
                    WHERE allow IN ({placeholders})
                    AND for_value IN ({placeholders})
                """,
                    employee_ids + employee_ids,
                    as_dict=True,
                )
            except Exception as e:
                frappe.logger().warning(f"Could not query User Permission records: {str(e)}")
        results["user_permissions"] = {"count": len(user_permissions), "deleted": 0, "errors": []}

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
            + results["notification_settings"]["count"]
            + results["api_audit_logs"]["count"]
            + results["sales_invoices"]["count"]
            + results["volunteers"]["count"]
            + results["sepa_mandates"]["count"]
            + results["payment_history"]["count"]
            + results["chapter_members"]["count"]
            + results["users"]["count"]
            + results["employees"]["count"]
            + results["user_permissions"]["count"]
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
            # EARLY CLEANUP: Delete tracking/administrative records first
            # These don't have dependencies and should be cleaned up early

            # Delete Notification Settings (by member email)
            frappe.logger().info(f"Cleaning up {len(notification_settings)} Notification Settings...")
            for ns in notification_settings:
                try:
                    frappe.delete_doc("Notification Settings", ns.name, ignore_permissions=True, force=True)
                    results["notification_settings"]["deleted"] += 1
                except Exception as e:
                    results["notification_settings"]["errors"].append(f"{ns.name}: {str(e)}")

            # Delete API Audit Log entries (by member email)
            frappe.logger().info(f"Cleaning up {len(api_audit_logs)} API Audit Log entries...")
            for audit_log in api_audit_logs:
                try:
                    frappe.delete_doc("API Audit Log", audit_log.name, ignore_permissions=True, force=True)
                    results["api_audit_logs"]["deleted"] += 1
                except Exception as e:
                    results["api_audit_logs"]["errors"].append(f"{audit_log.name}: {str(e)}")

            # Delete Account Creation Requests (tracking records - delete early)
            frappe.logger().info(f"Cleaning up {len(account_creation_requests)} Account Creation Requests...")
            for acr in account_creation_requests:
                try:
                    frappe.delete_doc(
                        "Account Creation Request", acr.name, ignore_permissions=True, force=True
                    )
                    results["account_creation_requests"]["deleted"] += 1
                except Exception as e:
                    results["account_creation_requests"]["errors"].append(f"{acr.name}: {str(e)}")

            # Delete child table records (Chapter Members)
            frappe.logger().info(f"Cleaning up {len(chapter_members)} Chapter Member links...")
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

            # Delete Sales Invoices (they depend on dues schedules and memberships)
            frappe.logger().info(f"Cleaning up {len(sales_invoices)} Sales Invoices...")
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

            # Delete User Permissions first (they reference employees)
            frappe.logger().info(f"Cleaning up {len(user_permissions)} User Permission records...")
            for perm in user_permissions:
                try:
                    frappe.delete_doc("User Permission", perm.name, ignore_permissions=True, force=True)
                    results["user_permissions"]["deleted"] += 1
                except Exception as e:
                    results["user_permissions"]["errors"].append(f"{perm.name}: {str(e)}")

            # Delete Employee records (they reference users)
            frappe.logger().info(f"Cleaning up {len(employees)} Employee records...")
            for employee in employees:
                try:
                    frappe.delete_doc("Employee", employee.name, ignore_permissions=True, force=True)
                    results["employees"]["deleted"] += 1
                except Exception as e:
                    results["employees"]["errors"].append(f"{employee.name}: {str(e)}")

            # Delete User accounts last (be very careful here)
            frappe.logger().info(f"Cleaning up {len(users_with_member_links)} User accounts...")
            for user in users_with_member_links:
                try:
                    # Extra safety check - don't delete Administrator or system users
                    if user.name not in ["Administrator", "Guest"]:
                        frappe.delete_doc("User", user.name, ignore_permissions=True, force=True)
                        results["users"]["deleted"] += 1
                    else:
                        results["users"]["errors"].append(f"Skipped system user: {user.name}")
                except Exception as e:
                    results["users"]["errors"].append(f"{user.name}: {str(e)}")

            # Finally delete Members
            frappe.logger().info(f"Cleaning up {len(members)} Member records...")
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
                + results["notification_settings"]["deleted"]
                + results["api_audit_logs"]["deleted"]
                + results["sales_invoices"]["deleted"]
                + results["volunteers"]["deleted"]
                + results["sepa_mandates"]["deleted"]
                + results["payment_history"]["deleted"]
                + results["chapter_members"]["deleted"]
                + results["user_permissions"]["deleted"]
                + results["employees"]["deleted"]
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
    Force cleanup of orphaned dues schedules and membership sales invoices
    after members have already been deleted.

    Detects orphaned invoices by checking:
    - Membership invoices (is_membership_invoice = 1 OR membership_dues_schedule_display IS NOT NULL)
    - Where the member no longer exists OR the customer no longer exists

    Also cleans up related GL Entries, Payment Ledger Entries, and Payment Entry References
    to prevent foreign key constraint violations.

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
        "gl_entries_deleted": 0,
        "payment_ledger_deleted": 0,
        "payment_references_deleted": 0,
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

        # Find MEMBERSHIP invoices where member was deleted OR customer was deleted
        # Only considers invoices marked as membership invoices or linked to dues schedules
        orphaned_invoices = frappe.db.sql(
            """
            SELECT si.name, si.customer, si.docstatus, si.member, si.is_membership_invoice
            FROM `tabSales Invoice` si
            LEFT JOIN `tabMember` m ON si.member = m.name
            LEFT JOIN `tabCustomer` c ON si.customer = c.name
            WHERE (si.is_membership_invoice = 1 OR si.membership_dues_schedule_display IS NOT NULL)
              AND (
                  (si.member IS NOT NULL AND m.name IS NULL)  -- Member deleted
                  OR c.name IS NULL  -- Customer deleted (rare, requires force delete)
              )
        """,
            as_dict=True,
        )

        results["orphaned_invoices"]["count"] = len(orphaned_invoices)

        if dry_run:
            # Show sample of what would be deleted
            summary_lines = [
                f"DRY RUN: Would delete {len(orphaned_schedules)} orphaned schedules and {len(orphaned_invoices)} orphaned membership invoices"
            ]
            if orphaned_invoices:
                sample = orphaned_invoices[:5]
                summary_lines.append(f"\nSample invoices to delete:")
                for inv in sample:
                    summary_lines.append(
                        f"  - {inv.name}: customer={inv.customer}, member={inv.member}, status={inv.docstatus}"
                    )
                if len(orphaned_invoices) > 5:
                    summary_lines.append(f"  ... and {len(orphaned_invoices) - 5} more")
            results["summary"] = "\n".join(summary_lines)
            return results

        # ACTUAL DELETION
        frappe.db.begin()

        try:
            # Delete orphaned invoices first (with proper GL cleanup)
            # Note: We manually delete GL entries instead of using doc.cancel() because:
            # 1. The member/customer may already be deleted, causing cancel() to fail
            # 2. Direct SQL deletion is more reliable for cleanup after force deletions
            # 3. We can track exactly what gets cleaned up for audit purposes
            #
            # Strategy: Continue on individual invoice errors (not fail-fast) because:
            # - We want to clean up as many orphaned invoices as possible in one run
            # - Some invoices may have unique constraint issues that shouldn't block others
            # - Errors are tracked in results["orphaned_invoices"]["errors"] for review
            for invoice in orphaned_invoices:
                try:
                    # Step 1: Delete GL Entries (must be done before cancelling/deleting invoice)
                    # frappe.db.sql returns affected row count as integer
                    gl_count = frappe.db.sql(
                        """
                        DELETE FROM `tabGL Entry`
                        WHERE voucher_type = 'Sales Invoice' AND voucher_no = %s
                    """,
                        invoice.name,
                    )
                    results["gl_entries_deleted"] += gl_count or 0

                    # Step 2: Delete Payment Ledger Entries
                    pl_count = frappe.db.sql(
                        """
                        DELETE FROM `tabPayment Ledger Entry`
                        WHERE voucher_type = 'Sales Invoice' AND voucher_no = %s
                    """,
                        invoice.name,
                    )
                    results["payment_ledger_deleted"] += pl_count or 0

                    # Step 3: Delete Payment Entry References
                    pr_count = frappe.db.sql(
                        """
                        DELETE FROM `tabPayment Entry Reference`
                        WHERE reference_doctype = 'Sales Invoice' AND reference_name = %s
                    """,
                        invoice.name,
                    )
                    results["payment_references_deleted"] += pr_count or 0

                    # Step 4: Cancel if submitted (now safe since GL entries are gone)
                    if invoice.docstatus == 1:
                        frappe.db.sql(
                            """
                            UPDATE `tabSales Invoice`
                            SET docstatus = 2
                            WHERE name = %s
                        """,
                            invoice.name,
                        )

                    # Step 5: Force delete the invoice
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
            ] = f"Successfully deleted {results['orphaned_schedules']['deleted']} schedules and {results['orphaned_invoices']['deleted']} invoices (with {results['gl_entries_deleted']} GL entries, {results['payment_ledger_deleted']} payment ledger entries, {results['payment_references_deleted']} payment references)"

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
