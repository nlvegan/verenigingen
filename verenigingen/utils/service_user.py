# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Service User Helper

Resolves the configured service user (e.g. the webhook user). There is NO fallback:
a missing, unset, disabled or unreadable user means "no service user", never
Administrator (#1876).
"""

import frappe


class ServiceUserUnavailable(Exception):
    """No usable service user is configured.

    Deliberately a plain Exception, not frappe.ValidationError: ``frappe.throw`` appends
    its message to ``message_log``, which the framework serialises into the
    ``_server_messages`` of an anonymous webhook caller's response. The reason goes to
    the Error Log only.
    """


def _lookup_service_user(settings_doctype: str, user_field: str) -> tuple[str | None, str]:
    """(user, "") when usable, else (None, why). Never raises."""
    messages_before = len(frappe.local.message_log or [])
    try:
        configured = frappe.db.get_single_value(settings_doctype, user_field)
        if not configured:
            return None, f"{user_field} is not set in {settings_doctype}"
        if frappe.db.get_value("User", configured, "enabled"):
            return configured, ""
        return None, f"'{configured}' is disabled or does not exist"
    except Exception as e:
        # a failed lookup may have frappe.throw()n on the way (a missing doctype does),
        # and that message would surface in an anonymous caller's _server_messages
        del (frappe.local.message_log or [])[messages_before:]
        return None, f"reading {user_field} from {settings_doctype} raised {type(e).__name__}: {e}"


def get_service_user(
    settings_doctype: str,
    user_field: str,
    service_name: str,
    fallback_user: str | None = None,
) -> str | None:
    """
    Get the configured service user, or None when there is no usable one.

    Reads a user from a settings DocType and validates it exists and is enabled. It never
    elevates: no Administrator fallback, whatever the reason (unset, disabled, deleted,
    or a lookup that raises). Writes no Error Log row and does not raise; a caller that
    must refuse without a user uses ``require_service_user``.

    Args:
        settings_doctype: DocType to read settings from (e.g., "Verenigingen Payments Settings")
        user_field: Field name containing the user (e.g., "webhook_user")
        service_name: Human-readable service name (e.g., "Ponto Webhook"); only
            ``require_service_user`` uses it, kept so both share one call shape
        fallback_user: Kept for signature compatibility. Must be None: any other value
            (Administrator included) raises ValueError.

    Returns:
        str | None: Valid username, or None when no usable user is configured

    Raises:
        ValueError: If a fallback_user is passed

    Example - set the identity INSIDE the job, never via an enqueue kwarg:

        def my_job(some_arg):
            frappe.set_user(require_service_user(
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
    if fallback_user is not None:
        raise ValueError(f"{service_name}: get_service_user no longer supports a fallback user (#1876)")
    return _lookup_service_user(settings_doctype, user_field)[0]


def require_service_user(settings_doctype: str, user_field: str, service_name: str) -> str:
    """The service user, or fail closed.

    With no usable user this writes an Error Log row (the operator-visible signal, with
    the reason) and raises ``ServiceUserUnavailable``. The caller must not write anything
    and, for a webhook, must answer non-2xx so the gateway redelivers.
    """
    user, reason = _lookup_service_user(settings_doctype, user_field)
    if user:
        return user
    frappe.log_error(
        title=f"{service_name}: no usable service user",
        message=(
            f"{reason}. {service_name} refused to run: there is deliberately no Administrator "
            f"fallback. Set an enabled user in {settings_doctype}.{user_field} (migrate "
            f"re-creates the webhook user unless disable_webhook_user_autosetup is set)."
        ),
    )
    raise ServiceUserUnavailable(f"{service_name}: no usable {user_field}")
