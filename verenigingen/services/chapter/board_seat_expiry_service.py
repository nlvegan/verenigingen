"""Daily job that ends Chapter Board Member seats whose ``to_date`` has passed (#2875).

A seat with ``is_active=1`` and a past ``to_date`` is real data: nothing flips ``is_active``
when a fixed-term seat lapses, and a Desk save of the board table accepts that combination
(``BoardMemberValidator`` only warns). The many readers that test ``is_active`` alone keep
treating it as a live seat, so the seat is ENDED here rather than each reader learning
``to_date`` (maintainer ruling, 2026-11-19). Access lingers at most until the next run, or,
for a chapter that cannot be saved, until staff fix it: such a chapter is reported to staff.

The seat is ended through its parent Chapter save, the same route as termination's
``end_board_positions_safe`` and ``ChapterAssignmentService._cleanup_board_memberships``
(#738): a standalone row write never runs ``Chapter.validate()``, so the volunteer's
assignment history would stay Active. The save also defers and flushes the role/profile
recalculation, which withdraws the board role. A seat whose Chapter no longer exists is ended by
saving the row itself (#2941, maintainer ruling 2026-11-24); see ``_end_orphan_seats``.

A Desk edit that sets ``is_active`` back to 1 without moving ``to_date`` is ended again at
the next run; that is intended.
"""

import hashlib

import frappe
from frappe.utils import escape_html, today

from verenigingen.services.member.application.door_alerts import _was_delivered
from verenigingen.utils.notification_helpers import notify_administrators
from verenigingen.utils.transaction_errors import (
    NON_RESUMABLE_DB_ERRORS,
    release_savepoint_if_present,
    rollback_to_savepoint,
)

ENDED_NOTE = "Ended automatically: the seat's end date has passed."
NOTIFICATION_KEY = "board_seat_expiry_failed"
# A stuck chapter stays stuck until staff act, so the reminder is weekly, not daily.
REALERT_SECONDS = 7 * 24 * 3600


def end_lapsed_board_seats() -> tuple:
    """Set ``is_active=0`` on every live-flagged seat whose ``to_date`` is before today.

    Returns ``(ended, failed)``: the number of seats ended, and one ``(chapter, rows, reason)``
    per chapter whose seats could NOT be ended (its save failed). The seat
    keeps its own ``to_date``. Idempotent: an ended seat no longer matches. A failed chapter does
    not stop the others and is NOT re-raised (the scheduler would roll back the chapters that
    succeeded); staff are alerted instead. No commit here: the scheduler commits after the job.
    """
    # "to_date < today" alone also matches an open-ended seat: Frappe compares a Date filter as
    # ifnull(to_date, '0001-01-01'), so the unset case needs its own "is set" condition.
    lapsed = frappe.db.get_all(
        "Chapter Board Member",
        filters=[
            ["is_active", "=", 1],
            ["to_date", "is", "set"],
            ["to_date", "<", today()],
        ],
        fields=["name", "parent"],
    )
    rows_by_chapter = {}
    for seat in lapsed:
        rows_by_chapter.setdefault(seat.parent, []).append(seat.name)

    ended, failed = 0, []
    for chapter_name, row_names in rows_by_chapter.items():
        count, reason = _end_seats_of_chapter(chapter_name, row_names)
        ended += count
        if reason:
            failed.append((chapter_name, row_names, reason))
    try:
        _alert_staff(failed)
    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception:
        # Alert trouble must never undo the work: an exception here reaches the scheduler, which
        # rolls back every chapter this run ended.
        frappe.log_error(title="Board seat expiry alert failed", message=frappe.get_traceback())
    return ended, failed


def _end_seats_of_chapter(chapter_name, row_names) -> tuple:
    """End ``row_names`` with one Chapter save: ``(ended, None)`` or ``(0, reason)``.

    A failed save is rolled back, so none of the chapter's rows is left half-ended.
    """
    orphan = not frappe.db.exists("Chapter", chapter_name)
    savepoint = f"end_lapsed_seats_{frappe.generate_hash(length=10)}"
    frappe.db.savepoint(savepoint)
    try:
        if orphan:
            ended = _end_orphan_seats(row_names)
        else:
            chapter_doc = frappe.get_doc("Chapter", chapter_name)
            ended = 0
            for row in chapter_doc.board_members:
                if row.name in row_names:
                    _mark_ended(row)
                    ended += 1
            chapter_doc.save()
        release_savepoint_if_present(savepoint)
        return ended, None
    except NON_RESUMABLE_DB_ERRORS:
        # A deadlock or lock timeout has already destroyed the savepoint.
        raise
    except Exception as e:
        rollback_to_savepoint(savepoint)
        frappe.log_error(
            title=f"Board seat expiry failed: {chapter_name}",
            message=f"Lapsed seat(s) {', '.join(row_names)} of {chapter_name} were not ended: {e}\n\n"
            f"{frappe.get_traceback()}",
        )
        error = str(e) or type(e).__name__
        return 0, error


def _mark_ended(row):
    row.is_active = 0
    row.notes = f"{row.notes}\n{ENDED_NOTE}" if row.notes else ENDED_NOTE


def _end_orphan_seats(row_names) -> int:
    """End seats whose Chapter is gone by saving each row on its own (#2941).

    There is no Chapter to save, but the row is a document in its own right: its ``on_update``
    completes the volunteer's assignment history through the orphan route (#2607) and withdraws
    the holder's board role and profile without needing a Chapter (#1953), the same hooks a REST
    PUT of the row runs. The history hangs off the Volunteer (its Dynamic Link names the missing
    Chapter), so it is kept and closed, not lost.
    """
    for name in row_names:
        row = frappe.get_doc("Chapter Board Member", name)
        _mark_ended(row)
        row.save()
    return len(row_names)


def _alert_staff(failed):
    """One staff alert for the chapters whose seats stayed live (each at most once a week).

    Deduplicated like ``door_alerts``: a Redis SETNX claim per (chapter, reason) with an expiry, not
    the key's per-recipient cooldown (0 in the registry), which would swallow a second chapter's alert.
    The window is a week rather than the door alert's day, as the daily job would otherwise repeat it.
    """
    claims = [(item, _claim(item)) for item in failed]
    fresh = [(item, key) for item, key in claims if key]
    if not fresh:
        return
    items = [item for item, _key in fresh]
    try:
        result = notify_administrators(
            subject=f"Board seats past their end date could not be ended ({len(items)} chapter(s))",
            message=_alert_message(items),
            notification_key=NOTIFICATION_KEY,  # literal: key discovery greps for it
            event_reference=NOTIFICATION_KEY,
            # staff alerts never go to Administrator (the delivery layer also excludes it)
            exclude_users=["Administrator"],
            staff_alert=True,
        )
    except Exception:
        result = None
        frappe.log_error(title="Board seat expiry alert failed", message=frappe.get_traceback())
    if not _was_delivered(result):
        for _item, key in fresh:
            frappe.cache.delete(key)  # nobody was told: do not hold the alert back for a week


def _claim(item):
    """The Redis key if this is the first alert for (chapter, reason) within the window, else None."""
    chapter_name, _rows, reason = item
    digest = hashlib.sha256(f"{chapter_name}:{reason}".encode()).hexdigest()[:16]
    key = frappe.cache.make_key(f"{NOTIFICATION_KEY}:{digest}")
    try:
        return key if frappe.cache.set(key, "1", ex=REALERT_SECONDS, nx=True) else None
    except Exception:
        try:
            frappe.log_error(title="Board seat expiry alert not deduplicated", message=frappe.get_traceback())
        except Exception:
            pass  # the cache is down and so, it seems, is logging: still fail open
        return key  # fail open: a repeat alert beats a missed one


def _alert_message(items):
    lines = "".join(
        f"<li><b>{escape_html(chapter)}</b>: seat row(s) {escape_html(', '.join(rows))} "
        f"- {escape_html(reason)}</li>"
        for chapter, rows, reason in items
    )
    return (
        "<p>The daily job could not end these lapsed Chapter Board Member seats, so their holders keep "
        "board access until the cause is fixed. Each chapter is reported again after a week.</p>"
        f"<ul>{lines}</ul>"
    )
