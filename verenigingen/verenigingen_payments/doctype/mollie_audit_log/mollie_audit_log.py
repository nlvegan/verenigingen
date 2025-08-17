"""
Mollie Audit Log DocType
Immutable audit trail for Mollie integration security events
"""

import hashlib
import json

import frappe
from frappe.model.document import Document


class MollieAuditLog(Document):
    """
    Immutable audit log for security and compliance

    Features:
    - Read-only after creation
    - Integrity hash for tamper detection
    - Comprehensive security event logging
    """

    def before_insert(self):
        """Calculate and set integrity hash before insertion"""
        if not self.integrity_hash:
            self.integrity_hash = self.calculate_integrity_hash()

    def validate(self):
        """Ensure audit log cannot be modified after creation"""
        if not self.is_new():
            # Check if document is being modified (not allowed)
            if (
                self.has_value_changed("action")
                or self.has_value_changed("status")
                or self.has_value_changed("details")
                or self.has_value_changed("timestamp")
                or self.has_value_changed("user")
            ):
                frappe.throw("Audit logs cannot be modified after creation")

            # Verify integrity hash
            if not self.verify_integrity():
                frappe.throw("Audit log integrity check failed - possible tampering detected")

    def calculate_integrity_hash(self) -> str:
        """
        Calculate SHA256 hash of critical fields

        Returns:
            str: Hexadecimal hash string
        """
        # Create hash input from critical fields
        hash_input = "|".join(
            [
                str(self.action or ""),
                str(self.status or ""),
                str(self.details or ""),
                str(self.timestamp or ""),
                str(self.user or ""),
            ]
        )

        # Calculate SHA256 hash
        return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    def verify_integrity(self) -> bool:
        """
        Verify audit log integrity

        Returns:
            bool: True if integrity is maintained
        """
        if not self.integrity_hash:
            return False

        # Recalculate hash and compare
        current_hash = self.calculate_integrity_hash()
        return current_hash == self.integrity_hash

    def on_trash(self):
        """Prevent deletion of audit logs"""
        frappe.throw("Audit logs cannot be deleted for compliance reasons")

    @staticmethod
    def create_audit_log(action: str, status: str, details: dict = None, user: str = None):
        """
        Static method to create audit log entry

        Args:
            action: Action being logged
            status: Status of action (success/failed/warning)
            details: Additional details as dictionary
            user: User performing action (defaults to current user)
        """
        try:
            audit_log = frappe.new_doc("Mollie Audit Log")
            audit_log.action = action
            audit_log.status = status
            audit_log.details = json.dumps(details) if details else None
            audit_log.user = user or frappe.session.user
            audit_log.timestamp = frappe.utils.now()

            # Get IP address if available
            if frappe.local.request:
                audit_log.ip_address = frappe.local.request.environ.get("REMOTE_ADDR")

            # Save with system permissions
            audit_log.flags.ignore_permissions = True
            audit_log.insert()

        except Exception as e:
            # Log error but don't fail the main operation
            frappe.log_error(f"Failed to create audit log: {str(e)}", "Mollie Audit Log")
