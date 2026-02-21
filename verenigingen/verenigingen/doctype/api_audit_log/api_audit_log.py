"""
API Audit Log DocType for tracking general API and security events
"""

import frappe
from frappe.model.document import Document

from verenigingen.utils.constants import Roles
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


class APIAuditLog(Document):
    """
    API Audit Log document for general API security events

    This doctype stores audit events for:
    - General API calls (success/failure)
    - Security events (CSRF failures, rate limiting, unauthorized access)
    - Authentication events (login/logout)
    - Data access events
    - Configuration changes
    - System errors and performance alerts
    """

    def before_insert(self):
        """Validate event data before insertion"""
        # Ensure event_id is unique
        if not self.event_id:
            import time

            self.event_id = f"api_audit_{int(time.time() * 1000)}_{hash(f'{self.user}{self.event_type}{time.time()}') % 100000:05d}"

        # Set timestamp if not provided
        if not self.timestamp:
            self.timestamp = frappe.utils.now()

        # Set user if not provided
        if not self.user:
            self.user = getattr(frappe.session, "user", "System")

    def validate(self):
        """Validate audit log entry"""
        # Validate required fields
        if not self.event_id:
            frappe.throw("Event ID is required")
        if not self.timestamp:
            frappe.throw("Timestamp is required")
        if not self.event_type:
            frappe.throw("Event Type is required")
        if not self.severity:
            frappe.throw("Severity is required")

    def on_update(self):
        """Handle post-update actions"""
        # API Audit Log entries should be immutable after creation
        # Skip immutability check if this is being called from ignore_permissions context (system operations)
        # or if the document has never been committed to database
        if (
            frappe.flags.ignore_permissions
            or getattr(frappe.local, "ignore_permissions", False)
            or self.is_new()
            or not self.creation
        ):
            return

        # Check if this is an actual user-initiated update by looking at the call stack
        import inspect

        frame_info = inspect.stack()

        # Skip immutability check if called from audit logging system itself
        for frame in frame_info:
            filename = frame.filename
            if (
                "audit_logging.py" in filename
                or "api_security_framework.py" in filename
                or "insert" in frame.function.lower()
            ):
                return

        # This appears to be a user-initiated update - enforce immutability
        frappe.throw("API Audit Log entries cannot be modified after creation")

    @staticmethod
    def create_audit_entry(event_data):
        """
        Create an API audit log entry

        Args:
            event_data: Dictionary containing audit event data

        Returns:
            API Audit Log document name
        """
        try:
            audit_doc = frappe.new_doc("API Audit Log")
            audit_doc.update(event_data)
            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            insert_result = secure_document_operation(
                operation="insert",
                doc=audit_doc,
                justification="Create API audit log entry for security compliance",
                required_permissions=["API Audit Log:create"],
                allow_system_user=True,
            )

            if not insert_result.success:
                frappe.log_error("Could not create API audit entry: Permission denied", "API Audit Error")
                return None
            frappe.db.commit()
            return audit_doc.name
        except Exception as e:
            frappe.log_error(f"Failed to create API audit entry: {str(e)}", "API Audit Error")
            return None

    @staticmethod
    def cleanup_old_entries(retention_days=90):
        """
        Clean up old API audit log entries

        Args:
            retention_days: Number of days to retain entries
        """
        try:
            cutoff_date = frappe.utils.add_days(frappe.utils.today(), -retention_days)

            old_entries = frappe.get_all(
                "API Audit Log", filters={"timestamp": ["<", cutoff_date]}, pluck="name"
            )

            for entry_name in old_entries:
                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                delete_result = secure_document_operation(
                    operation="delete",
                    doc=frappe.get_doc("API Audit Log", entry_name),
                    justification=f"Cleanup old API audit entry older than {retention_days} days",
                    required_permissions=["API Audit Log:delete"],
                    allow_system_user=True,
                )

                if not delete_result.success:
                    frappe.log_error(
                        f"Could not delete old audit entry {entry_name}: Permission denied",
                        "API Audit Cleanup Error",
                    )

            if old_entries:
                frappe.db.commit()
                frappe.logger().info(f"Cleaned up {len(old_entries)} old API audit log entries")

        except Exception as e:
            frappe.log_error(f"Failed to cleanup old API audit entries: {str(e)}", "API Audit Cleanup Error")


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def clear_all_audit_logs():
    """
    Clear all API Audit Log entries using efficient bulk deletion.

    This function is restricted to users with the 'Verenigingen Administrator' role.
    It deletes ALL audit log entries from the system using direct SQL for performance.

    Returns:
        dict: Result with success status and deleted count
    """
    # Check if user has Verenigingen Administrator role
    if not frappe.has_permission("API Audit Log", "delete"):
        return {
            "success": False,
            "message": "Insufficient permissions. Verenigingen Administrator role required.",
            "deleted_count": 0,
        }

    # Additional check for Verenigingen Administrator role
    user_roles = frappe.get_roles()
    if Roles.VERENIGINGEN_ADMIN not in user_roles and frappe.session.user != "Administrator":
        return {
            "success": False,
            "message": "This operation requires Verenigingen Administrator role.",
            "deleted_count": 0,
        }

    try:
        # Get count before deletion for reporting
        count_before = frappe.db.count("API Audit Log")

        # CRITICAL: Create permanent audit trail BEFORE truncation
        # This creates an immutable record in Error Log that survives TRUNCATE
        frappe.log_error(
            f"""CRITICAL SECURITY EVENT: API Audit Log Cleared

User: {frappe.session.user}
IP Address: {frappe.local.request_ip if hasattr(frappe.local, 'request_ip') else 'Unknown'}
Timestamp: {frappe.utils.now()}
Records Deleted: {count_before}
User Roles: {', '.join(frappe.get_roles())}
Justification: System maintenance - audit log hygiene

This operation deleted ALL audit log entries. This permanent record
ensures compliance and forensic traceability of the clearing operation.
""",
            "API Audit Log Cleared",
        )

        # Begin transaction
        frappe.db.begin()

        try:
            # Use TRUNCATE TABLE for maximum performance
            # TRUNCATE is faster than DELETE as it doesn't generate undo logs
            # and doesn't fire triggers (which is fine for audit log cleanup)
            frappe.db.sql("TRUNCATE TABLE `tabAPI Audit Log`")

            # Commit transaction
            frappe.db.commit()

            # Log the clearing action (in addition to Error Log above)
            frappe.logger().warning(
                f"API Audit Logs cleared by {frappe.session.user}: {count_before} entries deleted"
            )

            return {
                "success": True,
                "message": f"Successfully deleted {count_before} audit log entries",
                "deleted_count": count_before,
            }

        except Exception as e:
            # Rollback on error
            frappe.db.rollback()
            frappe.log_error(
                f"Failed to clear audit logs (rolled back): {str(e)}", "API Audit Log Clear Error"
            )
            return {"success": False, "message": f"Failed to clear audit logs: {str(e)}", "deleted_count": 0}

    except Exception as e:
        frappe.log_error(f"Error in clear_all_audit_logs: {str(e)}", "API Audit Log Clear Error")
        return {"success": False, "message": f"Error: {str(e)}", "deleted_count": 0}
