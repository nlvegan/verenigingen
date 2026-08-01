# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Service User Helper

Provides a reusable pattern for getting configured service users with
validation and audit logging when fallback is used.
"""

import frappe
from frappe import _


def get_service_user(
    settings_doctype: str,
    user_field: str,
    service_name: str,
    fallback_user: str = "Administrator",
) -> str:
    """
    Get configured service user with validation and audit logging.

    This helper provides a consistent pattern for:
    - Reading a user from a settings DocType
    - Validating the user exists and is enabled
    - Falling back to a default user with audit logging
    - Raising an error if no valid user is available

    Args:
        settings_doctype: DocType to read settings from (e.g., "Verenigingen Payments Settings")
        user_field: Field name containing the user (e.g., "webhook_user")
        service_name: Human-readable service name for logging (e.g., "Ponto Webhook")
        fallback_user: User to fall back to if configured user is invalid (default: "Administrator")

    Returns:
        str: Valid username

    Raises:
        ValueError: If no valid user is available

    Example - set the identity INSIDE the job, never via an enqueue kwarg:

        def my_job(some_arg):
            frappe.set_user(get_service_user(
                settings_doctype="Verenigingen Payments Settings",
                user_field="webhook_user",
                service_name="Ponto Webhook",
            ))
            ...

        frappe.enqueue("path.to.my_job", some_arg=x, queue="short")

    `frappe.enqueue(..., user=user)` does NOT work and is not a no-op: enqueue has no
    `user` parameter (frappe/utils/background_jobs.py:76-93), so it lands in **kwargs
    and execute_job passes it to the job function (`retval = method(**kwargs)`) - a
    TypeError in the worker, where the enqueuing request cannot see it. The worker's
    identity comes from `queue_args["user"] = frappe.session.user`, i.e. whoever
    enqueued, which for an allow_guest webhook is Guest. This example previously showed
    the broken form and it was copied to three call sites.
    """
    configured_user = None

    try:
        settings = frappe.get_single(settings_doctype)
        configured_user = getattr(settings, user_field, None)

        if configured_user:
            # Validate user exists and is enabled
            user_enabled = frappe.db.get_value("User", configured_user, "enabled")
            if user_enabled:
                return configured_user

            frappe.logger().warning(
                f"{service_name}: Configured user '{configured_user}' is disabled. "
                f"Falling back to {fallback_user}."
            )
    except Exception as e:
        frappe.logger().error(f"{service_name}: Could not get {user_field} from {settings_doctype}: {e}")

    # Validate fallback user exists
    if not frappe.db.exists("User", fallback_user):
        raise ValueError(
            f"{service_name}: No valid user configured and {fallback_user} not available. "
            f"Configure {user_field} in {settings_doctype}."
        )

    # Audit log when fallback is used (once per request per service)
    fallback_flag = f"_service_user_fallback_logged_{service_name.replace(' ', '_').lower()}"
    if not getattr(frappe.local, fallback_flag, False):
        frappe.log_error(
            title=f"{service_name} Using {fallback_user} Fallback",
            message=(
                f"No valid {user_field} configured in {settings_doctype}. "
                f"{service_name} operations are running as {fallback_user}. "
                f"For security, configure a dedicated service user with minimal permissions."
            ),
        )
        setattr(frappe.local, fallback_flag, True)

    frappe.logger().warning(f"{service_name}: No valid user configured. Using {fallback_user} as fallback.")
    return fallback_user
