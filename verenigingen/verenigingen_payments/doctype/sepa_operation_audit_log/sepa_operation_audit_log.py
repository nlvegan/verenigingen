# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SEPAOperationAuditLog(Document):
    """
    Audit log for SEPA operations - required for Dutch banking compliance

    This DocType maintains an immutable audit trail of all SEPA mandate operations
    to ensure regulatory compliance and security monitoring.
    """

    def validate(self):
        """Validate audit log entry before saving"""

        # Ensure timestamp is set
        if not self.timestamp:
            self.timestamp = frappe.utils.now()

        # Validate required compliance fields
        if not self.operation_type or not self.operation_status:
            frappe.throw(_("Operation type and status are required for audit compliance"))

        # Ensure user context is captured
        if not self.user:
            self.user = frappe.session.user

    def before_insert(self):
        """Set additional audit fields before insertion"""

        # Set naming timestamp for unique identification
        self.name = f"SEPA-AUDIT-{frappe.utils.now().replace(' ', '-').replace(':', '-')}"

        # Capture additional context if not already set
        if not self.ip_address:
            self.ip_address = frappe.get_request_header("X-Forwarded-For") or "unknown"

        if not self.user_agent:
            self.user_agent = frappe.get_request_header("User-Agent") or "unknown"

    def on_update(self):
        """Prevent updates to audit logs - they must be immutable for compliance"""
        # Check if this is a genuine update (not the initial insert)
        # During insert, _doc_before_save is None; during update, it exists
        if self._doc_before_save:
            frappe.throw(_("Audit log entries cannot be modified - compliance requirement"))

    def on_cancel(self):
        """Prevent cancellation of audit logs"""
        frappe.throw(_("Audit log entries cannot be cancelled - compliance requirement"))

    def on_trash(self):
        """Prevent deletion of audit logs"""
        frappe.throw(_("Audit log entries cannot be deleted - compliance requirement"))


def has_permission(doc, user=None, ptype=None):
    """Custom permission check for SEPA Operation Audit Log"""
    if not user:
        user = frappe.session.user

    # System Manager and Verenigingen Staff have full read access
    if frappe.db.get_value(
        "Has Role",
        {
            "parent": user,
            "role": ["in", ["System Manager", "Verenigingen Staff", "Verenigingen Auditor"]],
        },
        "name",
    ):
        # Audit logs are read-only for compliance
        return ptype in ["read", "print", "email", "export", "report"]

    # No other access allowed - audit logs are restricted
    return False


def get_permission_query_conditions(user=None):
    """Custom permission query conditions for SEPA Operation Audit Log"""
    if not user:
        user = frappe.session.user

    # Only managers and auditors can see audit logs
    if frappe.db.get_value(
        "Has Role",
        {
            "parent": user,
            "role": ["in", ["System Manager", "Verenigingen Staff", "Verenigingen Auditor"]],
        },
        "name",
    ):
        return ""

    # Default: no access to audit logs
    return "1=0"
