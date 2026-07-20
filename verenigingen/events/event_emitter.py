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
    bulk_flag: str | None = None,
):
    """Enqueue background jobs for each subscriber of an event.

    Args:
        event_name: The event identifier (e.g. "member_status_changed").
        event_data: Payload dict passed to each subscriber.
        subscribers: List of dotted-path method strings to enqueue.
        entity_key: Key in event_data used for the job_id suffix
            (e.g. "member", "chapter", "team").
        job_prefix: Prefix for the job_id (e.g. "member", "approval").
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

    # Test affordance: subscribers are normally enqueued to a worker, so they do NOT
    # run inline even under frappe.in_test. Integration tests that need to assert on a
    # subscriber's side effects can set frappe.flags.run_events_synchronously to execute
    # the real subscriber code inline.
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
        # job_id must be per-subscriber: a single (event, entity) key would collapse
        # every subscriber onto one job under deduplicate=True, silently dropping all
        # but one. job_name/dedupe/delay (used previously) are NOT real Frappe v16
        # enqueue params -- they leaked into **kwargs and were forwarded to the
        # subscriber -- so deduplicate=True + a per-subscriber job_id are the real dedup.
        #
        # NOTE: enqueue_after_commit is deliberately NOT set here. It is correct for a
        # single-purpose emitter (see invoice_events.py), but this generic emitter fans
        # out from many document hooks, and deferring dispatch to commit-time triggers a
        # reproducible order-dependence lock-timeout in the shared-process test shard
        # (verified with scripts/testing/order_dependence_detector.py against the
        # bulk-account-creation suite). The read-stale race it would guard against is
        # low-frequency and already handled by idempotent, retrying subscribers. See #168.
        frappe.enqueue(
            method=subscriber,
            queue="short",
            job_id=f"{job_prefix}_{event_name}_{entity_name}_{subscriber}",
            deduplicate=True,
            timeout=300,
            **extra_kwargs,
            **{"event_name": event_name, "event_data": event_data},
        )
