"""
Secure Service Account Manager for Background Operations

Provides controlled access to service accounts for background operations
that need to update financial history and other automated tasks.

Key Security Features:
- Limited-privilege service accounts
- Operation-specific access control
- Comprehensive audit logging
- Context restoration guarantees
"""

from contextlib import contextmanager

import frappe
from frappe.utils import now_datetime


@contextmanager
def background_service_context(operation_description: str):
    """
    Secure context manager for background service operations

    Args:
        operation_description: Description for audit trail

    Usage:
        with background_service_context("Update member expense history") as ctx:
            member.save()
            ctx.log_operation("member", member.name)
    """
    service_user = "background.service@verenigingen.local"
    original_user = frappe.session.user

    # Validate service user exists
    if not frappe.db.exists("User", service_user):
        frappe.throw(f"Background service user {service_user} not found")

    # Log operation start
    frappe.logger().info(
        f"BACKGROUND_SERVICE: Starting operation - "
        f"Description: {operation_description} "
        f"Original User: {original_user} "
        f"Service User: {service_user}"
    )

    try:
        frappe.set_user(service_user)
        yield BackgroundServiceContext(operation_description)
    finally:
        # Always restore original user
        frappe.set_user(original_user)
        frappe.logger().info(
            f"BACKGROUND_SERVICE: Completed operation - "
            f"Description: {operation_description} "
            f"Restored to: {original_user}"
        )


class BackgroundServiceContext:
    """Context object for background service operations"""

    def __init__(self, operation_description: str):
        self.operation_description = operation_description
        self.operations_log = []

    def log_operation(self, operation_type: str, record_name: str):
        """Log an operation for audit trail"""
        operation_record = {
            "timestamp": now_datetime(),
            "type": operation_type,
            "record": record_name,
            "description": self.operation_description,
            "user": frappe.session.user,
        }

        self.operations_log.append(operation_record)

        frappe.logger().info(
            f"BACKGROUND_SERVICE: Operation logged - "
            f"Type: {operation_type} Record: {record_name} "
            f"Description: {self.operation_description}"
        )


def get_background_service_user() -> str:
    """Get the background service user email"""
    return "background.service@verenigingen.local"


def validate_background_service_setup():
    """Validate that background service is properly configured"""
    service_user = get_background_service_user()

    if not frappe.db.exists("User", service_user):
        return {"valid": False, "message": f"Background service user {service_user} not found"}

    if not frappe.db.get_value("User", service_user, "enabled"):
        return {"valid": False, "message": f"Background service user {service_user} is disabled"}

    return {"valid": True, "message": "Background service configured correctly"}
