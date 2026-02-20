"""
Shared event emission helper for background job enqueueing.

Consolidates the repeated _emit_*_event() pattern across member_events,
chapter_events, approval_events, and team_events.
"""

import frappe


def emit_event(
    event_name: str,
    event_data: dict,
    subscribers: list,
    *,
    entity_key: str,
    job_prefix: str,
    delay: int = 1,
    bulk_flag: str | None = None,
):
    """Enqueue background jobs for each subscriber of an event.

    Args:
        event_name: The event identifier (e.g. "member_status_changed").
        event_data: Payload dict passed to each subscriber.
        subscribers: List of dotted-path method strings to enqueue.
        entity_key: Key in event_data used for the job_name suffix
            (e.g. "member", "chapter", "team").
        job_prefix: Prefix for the job_name (e.g. "member", "approval").
        delay: Seconds to delay the enqueue (default 1).
        bulk_flag: Optional frappe.flags attribute name that, together with
            ``in_bulk_import``, is forwarded as ``is_bulk_import`` kwarg
            to subscribers so they can skip heavy work during bulk ops.
    """
    entity_name = event_data.get(entity_key)

    extra_kwargs: dict = {}
    if bulk_flag is not None:
        is_bulk_import = getattr(frappe.flags, "in_bulk_import", False) or getattr(
            frappe.flags, bulk_flag, False
        )
        extra_kwargs["is_bulk_import"] = is_bulk_import

    for subscriber in subscribers:
        frappe.enqueue(
            method=subscriber,
            queue="short",
            job_name=f"{job_prefix}_{event_name}_{entity_name}",
            dedupe=True,
            timeout=300,
            delay=delay,
            **extra_kwargs,
            **{"event_name": event_name, "event_data": event_data},
        )
