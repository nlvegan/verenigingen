# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.utils.constants import Roles


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

        # Set naming timestamp for unique identification. A bare second-precision
        # timestamp collides on the primary key when several audit rows are
        # written within the same second (e.g. a SEPA bulk operation logging one
        # event per member), raising DuplicateEntryError and losing the row.
        # Append a short random suffix to keep names unique and chronological.
        self.name = "SEPA-AUDIT-{0}-{1}".format(
            frappe.utils.now().replace(" ", "-").replace(":", "-"),
            frappe.generate_hash(length=6),
        )

        # Capture additional context if not already set. get_request_header
        # touches frappe.local.request, which is unbound in non-request contexts
        # (background jobs, scheduler, CLI, tests). SEPA bulk operations commonly
        # run as background jobs, so an unguarded call raises "object is not
        # bound" and the entire audit insert fails -- dropping the row exactly
        # when the audit trail matters most.
        if not self.ip_address:
            self.ip_address = self._safe_request_header("X-Forwarded-For")

        if not self.user_agent:
            self.user_agent = self._safe_request_header("User-Agent")

    @staticmethod
    def _safe_request_header(key: str) -> str:
        """Return a request header, falling back to 'unknown' outside a request."""
        try:
            return frappe.get_request_header(key) or "unknown"
        except Exception:
            return "unknown"

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
            "role": ["in", [Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_STAFF, "Verenigingen Auditor"]],
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
            "role": ["in", [Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_STAFF, "Verenigingen Auditor"]],
        },
        "name",
    ):
        return ""

    # Default: no access to audit logs
    return "1=0"
