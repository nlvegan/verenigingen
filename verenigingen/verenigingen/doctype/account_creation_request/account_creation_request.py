"""
Account Creation Request DocType Controller

This module handles secure account creation requests for the Verenigingen system.
It provides proper audit trails, permission validation, and status tracking
for all user account creation operations.

Key Features:
- Proper permission validation (no ignore_permissions bypasses)
- Complete audit trail for security compliance
- Status tracking with detailed failure reporting
- Integration with background job processing
- Retry capability for failed requests

Security Model:
- Only authorized users can create account requests
- All operations follow proper Frappe permission patterns
- Complete logging for security audit purposes
- No permission bypasses or security shortcuts

Author: Verenigingen Development Team
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, now

from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api


def safe_log_error(message, title=None):
    """Helper to log errors with length protection"""
    # Truncate message to prevent log title validation errors
    safe_message = message[:100] + "..." if len(message) > 100 else message
    frappe.log_error(safe_message, title)


class AccountCreationRequest(Document):
    def validate(self):
        """Validate account creation request"""
        self.validate_permissions()
        self.validate_email_uniqueness()
        self.validate_source_record()
        self.set_defaults()

    def before_insert(self):
        """Set audit fields before insertion"""
        self.requested_by = frappe.session.user
        if not self.status:
            self.status = "Requested"

    def on_update(self):
        """Handle status changes and trigger notifications"""
        # Check if status just changed to Completed
        if self.has_value_changed("status") and self.status == "Completed":
            self.handle_completion()

    def handle_completion(self):
        """Handle actions when account creation is completed"""
        try:
            # Check if this is a member application approval
            if self.request_type == "Member":
                member = frappe.get_doc("Member", self.source_record)

                # Only send approval email if this member has an approved application
                if member.application_status == "Approved":
                    self.send_member_approval_email(member)
        except Exception as e:
            frappe.log_error(
                f"Error handling account creation completion for {self.name}: {str(e)}",
                "Account Creation Completion Error",
            )

    def send_member_approval_email(self, member):
        """Send approval email with login credentials when account is ready"""
        try:
            from verenigingen.utils.application_notifications import send_approval_email

            # Get the application invoice
            invoice = self.get_application_invoice(member)

            if invoice:
                send_approval_email(member, invoice)
                frappe.logger().info(f"Sent approval email for member {member.name} after account creation")
            else:
                frappe.logger().warning(
                    f"No application invoice found for member {member.name}, skipping approval email"
                )
        except Exception as e:
            frappe.log_error(
                f"Error sending approval email for member {member.name}: {str(e)}", "Approval Email Error"
            )

    def get_application_invoice(self, member):
        """Get the application invoice for a member"""
        try:
            # Get application invoice from payment history
            payment_history = getattr(member, "payment_history", None) or []

            for payment in payment_history:
                payment_description = getattr(payment, "description", None) or ""
                invoice_type = getattr(payment, "invoice_type", None)
                if invoice_type == "Application" or "application" in payment_description.lower():
                    invoice_name = getattr(payment, "invoice", None)
                    if invoice_name:
                        return frappe.get_doc("Sales Invoice", invoice_name)

            return None
        except Exception as e:
            frappe.log_error(f"Error getting application invoice: {str(e)}")
            return None

    def autoname(self):
        """Generate naming for account creation requests"""
        self.name = f"ACR-{self.request_type}-{frappe.utils.now()[:10]}-{frappe.generate_hash()[:8]}"

    def validate_permissions(self):
        """Validate that current user can create account requests"""
        # Check if user has permission to create user accounts
        if not frappe.has_permission("User", "create"):
            frappe.throw(_("Insufficient permissions to create user account requests"))

        # Additional validation for role assignments
        if self.requested_roles:
            for role_row in self.requested_roles:
                if not self.can_request_role(role_row.role):
                    frappe.throw(_("Insufficient permissions to request role: {0}").format(role_row.role))

    def validate_email_uniqueness(self):
        """Validate that email doesn't already have a user account"""
        if frappe.db.exists("User", self.email):
            # Check if this is a retry of existing request using standardized existence validation
            from verenigingen.utils.validation_utilities import DocumentExistenceValidator

            if not self.name or not DocumentExistenceValidator.validate_document_exists(
                "Account Creation Request", self.name, throw_on_error=False
            ):
                # Instead of throwing error, mark request as completed with existing user
                existing_user = frappe.get_doc("User", self.email)
                self.status = "Completed"
                self.created_user = existing_user.name
                self.completion_date = frappe.utils.now_datetime()
                self.processing_notes = (
                    f"User account already exists for {self.email}. Linked existing account."
                )
                frappe.logger().info(f"Account creation request linked to existing user: {self.email}")
                # Don't throw error - allow the request to be saved as completed

    def validate_source_record(self):
        """Validate that source record exists and is valid"""
        # Only validate source record on creation - status updates shouldn't re-validate
        # This prevents validation errors when source records are rolled back during error handling
        if not self.is_new():
            return

        if not frappe.db.exists(self.request_type, self.source_record):
            frappe.throw(_("{0} {1} does not exist").format(self.request_type, self.source_record))

    def set_defaults(self):
        """Set default values for the request"""
        if not self.priority:
            self.priority = "Normal"
        if not self.pipeline_stage:
            self.pipeline_stage = "Validation"

    def can_request_role(self, role_name):
        """Check if current user can request assignment of this role"""
        # System managers can assign any role
        if "System Manager" in frappe.get_roles():
            return True

        # Verenigingen administrators can assign verenigingen roles
        if "Verenigingen Administrator" in frappe.get_roles():
            verenigingen_roles = [
                "Verenigingen Member",
                "Verenigingen Volunteer",
                "Verenigingen Chapter Board Member",
                "Employee",
                "Employee Self Service",
            ]
            return role_name in verenigingen_roles

        # Default deny
        return False

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def queue_processing(self):
        """Queue this request for background processing"""
        if self.status not in ["Requested", "Failed"]:
            frappe.throw(_("Request cannot be queued in current status: {0}").format(self.status))

        # Update status
        self.status = "Queued"
        self.processing_started_at = now()
        self.save()

        # Queue background job
        frappe.enqueue(
            "verenigingen.utils.account_creation_manager.process_account_creation_request",
            request_name=self.name,
            queue="long",
            timeout=600,
            job_name=f"account_creation_{self.name}",
        )

        frappe.logger().info(f"Queued account creation request: {self.name}")
        return {"success": True, "message": _("Account creation request queued for processing")}

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def retry_processing(self):
        """Retry a failed account creation request"""
        if self.status != "Failed":
            frappe.throw(_("Only failed requests can be retried"))

        # Validate retry limits
        try:
            max_retries = (
                frappe.db.get_single_value("Verenigingen Settings", "max_account_creation_retries") or 3
            )
        except frappe.ValidationError:
            # Fallback if field doesn't exist yet
            max_retries = 3
        if self.retry_count >= max_retries:
            frappe.throw(_("Maximum retry attempts exceeded ({0})").format(max_retries))

        # Reset for retry
        self.status = "Requested"
        self.failure_reason = None
        self.last_retry_at = now()
        self.retry_count = (self.retry_count or 0) + 1
        self.save()

        # Queue for processing
        return self.queue_processing()

    def mark_processing(self, stage=None):
        """Mark request as processing and update stage"""
        # Use db_set to avoid validation and timestamp issues
        try:
            updates = {
                "status": "Processing",
                "processed_by": frappe.session.user,
            }
            if stage:
                updates["pipeline_stage"] = stage
            if not self.processing_started_at:
                updates["processing_started_at"] = now()

            # Update database directly to avoid validation race conditions
            for field, value in updates.items():
                frappe.db.set_value(self.doctype, self.name, field, value, update_modified=True)

            # Reload to get updated values
            self.reload()

            frappe.logger().info(
                f"Account creation request marked as processing: {self.name} (stage: {stage or 'unknown'})"
            )

        except Exception as e:
            frappe.logger().error(f"Failed to mark request as processing: {str(e)}")
            frappe.throw(_("Failed to mark request as processing: {0}").format(str(e)))

    def mark_completed(self, user=None, employee=None):
        """Mark request as completed successfully"""
        # Use db_set to avoid validation and timestamp issues during completion
        # This is safe because we're only updating status fields, not business logic
        try:
            updates = {
                "status": "Completed",
                "pipeline_stage": "Completed",
                "completed_at": now(),
            }
            if user:
                updates["created_user"] = user
            if employee:
                updates["created_employee"] = employee

            # Update database directly to avoid validation race conditions
            for field, value in updates.items():
                frappe.db.set_value(self.doctype, self.name, field, value, update_modified=True)

            # Reload to get updated values
            self.reload()

            frappe.logger().info(f"Account creation request completed: {self.name}")

        except Exception as e:
            frappe.logger().error(f"Failed to mark request as completed: {str(e)}")
            frappe.throw(_("Failed to mark request as completed: {0}").format(str(e)))

    def mark_failed(self, error_message, stage=None):
        """Mark request as failed with error details"""
        # Use db_set to avoid validation and timestamp issues during failure marking
        # This is critical for error handling - we must succeed even if source record is gone
        try:
            updates = {
                "status": "Failed",
                "failure_reason": str(error_message)[:1000],  # Truncate to avoid DB field limits
            }
            if stage:
                updates["pipeline_stage"] = stage

            # Update database directly to avoid validation race conditions
            for field, value in updates.items():
                frappe.db.set_value(self.doctype, self.name, field, value, update_modified=True)

            # Reload to get updated values
            self.reload()

            frappe.logger().error(f"Account creation request failed: {self.name} - {error_message}")

        except Exception as e:
            # Critical: If we can't even mark as failed, log to error log
            frappe.logger().critical(
                f"CRITICAL: Failed to mark request {self.name} as failed: {str(e)}. "
                f"Original error: {error_message}"
            )
            frappe.log_error(
                f"Failed to mark ACR as failed: {str(e)}\nOriginal error: {error_message}",
                "Critical ACR Failure Marking Error",
            )

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def cancel_request(self, reason=None):
        """Cancel an account creation request"""
        if self.status in ["Completed"]:
            frappe.throw(_("Cannot cancel completed request"))

        self.status = "Cancelled"
        if reason:
            self.failure_reason = f"Cancelled: {reason}"
        self.save()

        frappe.logger().info(f"Account creation request cancelled: {self.name}")


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_pending_requests():
    """Get pending account creation requests for admin dashboard"""
    if not frappe.has_permission("Account Creation Request", "read"):
        frappe.throw(_("Insufficient permissions"))

    return frappe.get_all(
        "Account Creation Request",
        filters={"status": ["in", ["Requested", "Failed"]]},
        fields=[
            "name",
            "request_type",
            "email",
            "full_name",
            "status",
            "failure_reason",
            "retry_count",
            "creation",
            "priority",
        ],
        order_by="priority desc, creation desc",
    )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def bulk_queue_requests(request_names):
    """Queue multiple account creation requests for processing"""
    import html
    import json

    if not frappe.has_permission("Account Creation Request", "write"):
        frappe.throw(_("Insufficient permissions"))

    # Handle HTML entity encoding from frontend
    if isinstance(request_names, str):
        unescaped = html.unescape(request_names)
        try:
            request_names = json.loads(unescaped)
        except json.JSONDecodeError:
            # Try stripping outer quotes if double-encoded
            cleaned = unescaped.strip('"').strip("'")
            try:
                request_names = json.loads(cleaned)
            except json.JSONDecodeError:
                frappe.throw(_("Invalid request_names format"))

    queued_count = 0
    errors = []

    for name in request_names:
        try:
            doc = frappe.get_doc("Account Creation Request", name)

            # Validate status
            if doc.status != "Requested":
                errors.append(f"{name}: Cannot queue (status: {doc.status})")
                continue

            doc.queue_processing()
            queued_count += 1
        except Exception as e:
            errors.append(f"{name}: {str(e)}")

    return {
        "success": len(errors) == 0,
        "queued_count": queued_count,
        "total_requested": len(request_names),
        "error_count": len(errors),
        "errors": errors[:20] if errors else [],
    }


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_request_statistics():
    """Get statistics for account creation requests dashboard"""
    if not frappe.has_permission("Account Creation Request", "read"):
        frappe.throw(_("Insufficient permissions"))

    stats = frappe.db.sql(
        """
        SELECT
            status,
            COUNT(*) as count
        FROM `tabAccount Creation Request`
        WHERE creation >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        GROUP BY status
    """,
        as_dict=True,
    )

    return stats
