"""
Shared event emission helper for background job enqueueing.

Consolidates the repeated _emit_*_event() pattern across member_events,
chapter_events and team_events.
"""

import frappe
from rq.exceptions import InvalidJobOperation


def enqueue_deduplicated(*args, **enqueue_kwargs):
    """``frappe.enqueue(..., deduplicate=True)`` that a dedupe race cannot turn into a failed save (#2505).

    With ``deduplicate=True`` frappe fetches the job by id and, when it is not queued or
    started, deletes it. ``Job.delete`` re-reads the job's status, and when a concurrent
    enqueue or worker removed the hash in between, rq raises ``InvalidJobOperation``. Called
    from a document hook, that aborted the business save.

    The race means the job hash is gone, so the enqueue is retried ONCE: ``get_job`` then
    returns None and the job is queued. The race is logged. If the retry also raises
    ``InvalidJobOperation`` that is logged too and the call returns None, so the save
    survives but this job was NOT queued. Any other exception, on either attempt, propagates:
    a lock or deadlock error must still reach the caller.

    A caller that cannot tolerate a silently lost job passes ``on_not_queued``: it is called
    (no arguments) after the retry also raised, and is NOT forwarded to ``frappe.enqueue``.
    ``None`` from this function cannot say that, because frappe also returns ``None`` for a
    legitimate dedupe hit and for any ``enqueue_after_commit`` call (#3186).

    Other arguments are forwarded unchanged, so callers keep their positional/keyword shape.
    """
    on_not_queued = enqueue_kwargs.pop("on_not_queued", None)
    try:
        return frappe.enqueue(*args, deduplicate=True, **enqueue_kwargs)
    except InvalidJobOperation as e:
        _log_dedupe_race(args, enqueue_kwargs, e, "retrying once")
    try:
        return frappe.enqueue(*args, deduplicate=True, **enqueue_kwargs)
    except InvalidJobOperation as e:
        _log_dedupe_race(args, enqueue_kwargs, e, "retry failed too, job NOT queued")
        if on_not_queued:
            on_not_queued()


def _log_dedupe_race(args, enqueue_kwargs, error, outcome):
    frappe.log_error(
        title="Event dedupe enqueue race (InvalidJobOperation)",
        message=(
            f"{outcome}: job_id={enqueue_kwargs.get('job_id')} "
            f"method={args[0] if args else enqueue_kwargs.get('method')}: {error}"
        ),
    )


def emit_event(
    event_name: str,
    event_data: dict,
    subscribers: list,
    *,
    entity_key: str,
    job_prefix: str,
    bulk_flag: str | None = None,
    after_commit: bool = False,
    job_id_keys: tuple = (),
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
        after_commit: Hold the jobs back until the surrounding transaction commits
            (a full rollback then drops them). Opt-in per event: the generic
            default stays immediate, see the NOTE below and #168. A rollback to a
            SAVEPOINT does not drop them: those subscribers must re-check state (#2137).
            Member, team and chapter-membership events opt in.
        job_id_keys: event_data keys appended to the job_id, for events that fire once
            per row within one save (e.g. several volunteers added to one Team). Without
            them those jobs share an id and, deferred to commit, the last overwrites the
            others (#2144).
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
        # NOTE: enqueue_after_commit is deliberately NOT the default here (opt in via
        # after_commit; member, team and chapter membership events do, because their subscribers mail and
        # grant roles for a state a rollback can undo, #2137). It is correct for a
        # single-purpose emitter (see invoice_events.py), but this generic emitter fans
        # out from many document hooks, and deferring dispatch to commit-time triggers a
        # reproducible order-dependence lock-timeout in the shared-process test shard
        # (verified with scripts/testing/order_dependence_detector.py against the
        # bulk-account-creation suite). The read-stale race it would guard against is
        # low-frequency and already handled by idempotent, retrying subscribers. See #168.
        enqueue_deduplicated(
            method=subscriber,
            queue="short",
            job_id="_".join(
                [f"{job_prefix}_{event_name}_{entity_name}"]
                + [str(event_data.get(k)) for k in job_id_keys]
                + [subscriber]
            ),
            enqueue_after_commit=after_commit,
            timeout=300,
            **extra_kwargs,
            **{"event_name": event_name, "event_data": event_data},
        )
