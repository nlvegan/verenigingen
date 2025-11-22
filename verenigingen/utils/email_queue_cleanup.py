import frappe

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def clear_failed_administrator_emails():
    """Clear failed email queue items with Administrator as recipient"""
    if "System Manager" not in frappe.get_roles():
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

        # Delete the failed email queue item using secure operations
        try:
            email_doc = frappe.get_doc("Email Queue", email.name)

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            operation_result = secure_document_operation(
                operation="delete",
                doc=email_doc,
                justification=f"Clean up failed email queue item {email.name} with Administrator recipient - system maintenance",
                required_permissions=["Email Queue:delete"],
            )

            if operation_result.success:
                print(f"    ✓ Deleted {email.name}")
                result["deleted_count"] += 1
            else:
                error_msg = f"Failed to delete {email.name}: {'; '.join(operation_result.errors)}"
                print(f"    ❌ {error_msg}")
                result["errors"].append(error_msg)
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
