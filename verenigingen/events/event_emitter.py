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
        delay: Unused. Retained for signature compatibility with existing
            callers (e.g. approval_events.py passes delay=2); dispatch
            timing is now handled by enqueue_after_commit=True below,
            which defers the job until the enclosing transaction commits.
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

    # Test affordance: subscribers are normally enqueued after commit, so they do NOT run
    # inline even under frappe.in_test (which only short-circuits is_async=False jobs).
    # Integration tests that need to assert on a subscriber's side effects can set
    # frappe.flags.run_events_synchronously to execute the real subscriber code inline.
    run_sync = frappe.in_test and getattr(frappe.flags, "run_events_synchronously", False)

    for subscriber in subscribers:
        if run_sync:
            frappe.call(
                subscriber,
                event_name=event_name,
                event_data=event_data,
                **extra_kwargs,
            )
            continue
        frappe.enqueue(
            method=subscriber,
            queue="short",
            job_id=f"{job_prefix}_{event_name}_{entity_name}_{subscriber}",
            deduplicate=True,
            enqueue_after_commit=True,
            timeout=300,
            **extra_kwargs,
            **{"event_name": event_name, "event_data": event_data},
        )
