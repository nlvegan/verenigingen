"""
Payment Entry Cleanup Utility

Safely deletes Payment Entry documents by first removing their references
from Member Payment History child tables to avoid LinkExistsError.

This is particularly useful for testing scenarios where you need to reimport
payment data.
"""

from typing import Any, Dict, List

import frappe
from frappe import _


@frappe.whitelist()
def bulk_delete_payment_entries(
    payment_entry_names: List[str] = None, filters: Dict = None
) -> Dict[str, Any]:
    """
    Bulk delete Payment Entry documents with proper cleanup of Member Payment History references.

    Strategy:
    1. Find all Payment Entries matching the criteria
    2. For each Payment Entry, find and remove references in Member Payment History
    3. Delete the Payment Entry documents
    4. Return detailed results

    Args:
        payment_entry_names: Optional list of specific Payment Entry names to delete
        filters: Optional dict of filters to find Payment Entries (e.g., {"docstatus": 0})

    Returns:
        Dict with deletion results including success count, errors, and details

    Examples:
        # Delete specific payment entries
        frappe.call("verenigingen.utils.payment_entry_cleanup.bulk_delete_payment_entries",
                   payment_entry_names=["ACC-PAY-2025-127456", "ACC-PAY-2025-127457"])

        # Delete all draft payment entries
        frappe.call("verenigingen.utils.payment_entry_cleanup.bulk_delete_payment_entries",
                   filters={"docstatus": 0})
    """
    # Validate input
    if not payment_entry_names and not filters:
        frappe.throw(_("Either payment_entry_names or filters must be provided"))

    # Convert string input to list if needed (for web API calls)
    if isinstance(payment_entry_names, str):
        import json

        payment_entry_names = json.loads(payment_entry_names)

    if isinstance(filters, str):
        import json

        filters = json.loads(filters)

    result = {
        "total_requested": 0,
        "member_history_cleaned": 0,
        "payment_entries_deleted": 0,
        "errors": 0,
        "details": [],
        "timestamp": frappe.utils.now(),
        "total_records_affected": 0,  # For UI formatter compatibility
        "payment_entries": {"count": 0, "deleted": 0, "errors": []},
        "member_history_records": {"count": 0, "deleted": 0, "errors": []},
    }

    try:
        # Step 1: Get list of Payment Entries to delete
        if payment_entry_names:
            pe_list = payment_entry_names
        else:
            pe_list = frappe.get_all("Payment Entry", filters=filters, pluck="name")

        result["total_requested"] = len(pe_list)
        frappe.logger().info(f"Starting cleanup of {len(pe_list)} Payment Entries")

        # Step 2: Process each Payment Entry
        for pe_name in pe_list:
            try:
                # Find all Members with this Payment Entry in their payment history
                members_with_pe = frappe.db.sql(
                    """
                    SELECT DISTINCT parent
                    FROM `tabMember Payment History`
                    WHERE payment_entry = %s
                """,
                    (pe_name,),
                    as_dict=True,
                )

                # Remove Payment Entry references from Member Payment History
                members_cleaned = []
                for member_row in members_with_pe:
                    member_name = member_row.parent
                    try:
                        member = frappe.get_doc("Member", member_name)

                        # Find and remove matching payment history rows
                        rows_to_remove = []
                        for idx, history_row in enumerate(member.payment_history):
                            if history_row.payment_entry == pe_name:
                                rows_to_remove.append(idx)

                        # Remove rows in reverse order to maintain indices
                        for idx in reversed(rows_to_remove):
                            member.payment_history.pop(idx)

                        if rows_to_remove:
                            # Save without triggering full validation
                            member.flags.ignore_validate = True
                            member.save()
                            members_cleaned.append(member_name)
                            result["member_history_cleaned"] += len(rows_to_remove)

                    except Exception as member_error:
                        frappe.log_error(
                            f"Failed to clean payment history for member {member_name}: {member_error}",
                            "Member History Cleanup Error",
                        )
                        result["details"].append(
                            {
                                "payment_entry": pe_name,
                                "member": member_name,
                                "status": "error",
                                "error": str(member_error),
                            }
                        )

                # Step 3: Delete the Payment Entry
                try:
                    frappe.delete_doc("Payment Entry", pe_name, force=True)
                    result["payment_entries_deleted"] += 1
                    result["details"].append(
                        {
                            "payment_entry": pe_name,
                            "status": "deleted",
                            "members_cleaned": members_cleaned,
                            "history_rows_removed": len(members_cleaned),
                        }
                    )
                    frappe.logger().info(
                        f"Deleted Payment Entry {pe_name} after cleaning {len(members_cleaned)} members"
                    )

                except Exception as delete_error:
                    result["errors"] += 1
                    result["details"].append(
                        {
                            "payment_entry": pe_name,
                            "status": "delete_failed",
                            "error": str(delete_error),
                            "members_cleaned": members_cleaned,
                        }
                    )
                    frappe.log_error(
                        f"Failed to delete Payment Entry {pe_name} after cleanup: {delete_error}",
                        "Payment Entry Deletion Error",
                    )

            except Exception as pe_error:
                result["errors"] += 1
                result["details"].append(
                    {"payment_entry": pe_name, "status": "error", "error": str(pe_error)}
                )
                frappe.log_error(f"Error processing Payment Entry {pe_name}: {pe_error}")

        # Commit changes
        frappe.db.commit()

        # Populate summary fields for UI formatter
        result["total_records_affected"] = (
            result["payment_entries_deleted"] + result["member_history_cleaned"]
        )
        result["payment_entries"]["count"] = result["total_requested"]
        result["payment_entries"]["deleted"] = result["payment_entries_deleted"]
        result["member_history_records"]["count"] = result["member_history_cleaned"]
        result["member_history_records"]["deleted"] = result["member_history_cleaned"]

        # Add summary message
        result["summary"] = (
            f"Deleted {result['payment_entries_deleted']} payment entries "
            f"and cleaned {result['member_history_cleaned']} member payment history records. "
            f"{result['errors']} errors encountered."
        )

        frappe.logger().info(
            f"Cleanup complete: {result['payment_entries_deleted']} deleted, "
            f"{result['member_history_cleaned']} history rows cleaned, "
            f"{result['errors']} errors"
        )

    except Exception as e:
        frappe.db.rollback()
        result["error"] = str(e)
        frappe.log_error(f"Bulk payment entry cleanup failed: {e}")

    return result


@frappe.whitelist()
def delete_payment_entries_by_date_range(
    from_date: str, to_date: str, docstatus: int = None
) -> Dict[str, Any]:
    """
    Delete Payment Entries within a date range.

    Args:
        from_date: Start date (YYYY-MM-DD)
        to_date: End date (YYYY-MM-DD)
        docstatus: Optional filter by docstatus (0=Draft, 1=Submitted, 2=Cancelled)

    Returns:
        Dict with deletion results

    Example:
        frappe.call("verenigingen.utils.payment_entry_cleanup.delete_payment_entries_by_date_range",
                   from_date="2025-01-01", to_date="2025-01-31", docstatus=0)
    """
    filters = {"posting_date": ["between", [from_date, to_date]]}

    if docstatus is not None:
        filters["docstatus"] = docstatus

    return bulk_delete_payment_entries(filters=filters)


@frappe.whitelist()
def get_payment_entry_cleanup_preview(
    payment_entry_names: List[str] = None, filters: Dict = None
) -> Dict[str, Any]:
    """
    Preview what would be deleted without actually deleting.

    Useful for checking impact before running the actual cleanup.

    Returns:
        Dict with preview information including affected members and payment entries
    """
    # Convert string input to list if needed
    if isinstance(payment_entry_names, str):
        import json

        payment_entry_names = json.loads(payment_entry_names)

    if isinstance(filters, str):
        import json

        filters = json.loads(filters)

    if not payment_entry_names and not filters:
        frappe.throw(_("Either payment_entry_names or filters must be provided"))

    # Get list of Payment Entries
    if payment_entry_names:
        pe_list = payment_entry_names
    else:
        pe_list = frappe.get_all("Payment Entry", filters=filters, pluck="name")

    preview = {
        "total_payment_entries": len(pe_list),
        "affected_members": [],
        "total_history_rows": 0,
        "payment_entries": [],
    }

    # Analyze each Payment Entry
    for pe_name in pe_list:
        members_with_pe = frappe.db.sql(
            """
            SELECT DISTINCT
                mph.parent as member,
                COUNT(*) as history_rows
            FROM `tabMember Payment History` mph
            WHERE mph.payment_entry = %s
            GROUP BY mph.parent
        """,
            (pe_name,),
            as_dict=True,
        )

        pe_info = {
            "name": pe_name,
            "affected_members": [m.member for m in members_with_pe],
            "history_rows": sum(m.history_rows for m in members_with_pe),
        }

        preview["payment_entries"].append(pe_info)
        preview["total_history_rows"] += pe_info["history_rows"]

        for m in members_with_pe:
            if m.member not in preview["affected_members"]:
                preview["affected_members"].append(m.member)

    preview["total_affected_members"] = len(preview["affected_members"])

    return preview
