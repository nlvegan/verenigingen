import frappe


@frappe.whitelist()
def clear_failed_administrator_emails():
    """Clear failed email queue items with Administrator as recipient"""
    if not frappe.has_permission("System Manager"):
        frappe.throw("Only System Managers can clear failed email queue items")

    print("=== CLEARING FAILED EMAIL QUEUE ITEMS ===")

    # Find Email Queue items with Administrator as recipient that are in Error status
    failed_emails = frappe.db.sql(
        """
        SELECT DISTINCT eq.name, eq.status, eq.error
        FROM `tabEmail Queue` eq
        JOIN `tabEmail Queue Recipient` eqr ON eq.name = eqr.parent
        WHERE eqr.recipient = 'Administrator'
        AND eq.status = 'Error'
        ORDER BY eq.creation DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    result = {"found_count": len(failed_emails), "deleted_count": 0, "errors": []}

    print(f"Found {len(failed_emails)} failed email queue items with Administrator recipient")

    for email in failed_emails:
        print(f"  {email.name}")
        print(f"    Status: {email.status}")

        # Delete the failed email queue item
        try:
            frappe.delete_doc("Email Queue", email.name, ignore_permissions=True)
            print(f"    ✓ Deleted {email.name}")
            result["deleted_count"] += 1
        except Exception as e:
            error_msg = f"Failed to delete {email.name}: {e}"
            print(f"    ❌ {error_msg}")
            result["errors"].append(error_msg)
        print()

    if result["deleted_count"] > 0:
        frappe.db.commit()

    print("\n✅ Email queue cleanup completed!")
    print("The SMTP recipients error should now be resolved.")

    return result
