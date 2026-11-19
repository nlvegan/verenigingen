"""Daily job that ends Chapter Board Member seats whose ``to_date`` has passed (#2875).

A seat with ``is_active=1`` and a past ``to_date`` is real data: nothing flips ``is_active``
when a fixed-term seat lapses, and a Desk save of the board table accepts that combination
(``BoardMemberValidator`` only warns). The many readers that test ``is_active`` alone keep
treating it as a live seat, so the seat is ENDED here rather than each reader learning
``to_date`` (maintainer ruling, 2026-11-19). Access lingers at most until the next run.

The seat is ended through its parent Chapter save, the same route as termination's
``end_board_positions_safe`` and ``ChapterAssignmentService._cleanup_board_memberships``
(#738): a standalone row write never runs ``Chapter.validate()``, so the volunteer's
assignment history would stay Active. The save also defers and flushes the role/profile
recalculation, which withdraws the board role.
"""

import frappe
from frappe.utils import today

from verenigingen.utils.transaction_errors import (
    NON_RESUMABLE_DB_ERRORS,
    release_savepoint_if_present,
    rollback_to_savepoint,
)

ENDED_NOTE = "Ended automatically: the seat's end date has passed."


def end_lapsed_board_seats() -> int:
    """Set ``is_active=0`` on every live-flagged seat whose ``to_date`` is before today.

    Returns the number of seats ended. The seat keeps its own ``to_date``. Idempotent: an
    ended seat no longer matches. One Chapter that cannot be saved is logged and skipped;
    its seats are retried by the next run. No commit here: the scheduler commits after the job.
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

    return sum(_end_seats_of_chapter(chapter, rows) for chapter, rows in rows_by_chapter.items())


def _end_seats_of_chapter(chapter_name, row_names) -> int:
    """End ``row_names`` with one Chapter save; a failed save leaves none of them half-ended."""
    savepoint = f"end_lapsed_seats_{frappe.generate_hash(length=10)}"
    frappe.db.savepoint(savepoint)
    ended = 0
    try:
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        for row in chapter_doc.board_members:
            if row.name in row_names:
                row.is_active = 0
                row.notes = f"{row.notes}\n{ENDED_NOTE}" if row.notes else ENDED_NOTE
                ended += 1
        chapter_doc.save()
        release_savepoint_if_present(savepoint)
    except NON_RESUMABLE_DB_ERRORS:
        # A deadlock or lock timeout has already destroyed the savepoint.
        raise
    except Exception as e:  # swallow-ok: best-effort (per-chapter isolation; Error Log row, retried next run)
        ended = 0
        rollback_to_savepoint(savepoint)
        frappe.log_error(
            title=f"Board seat expiry failed: {chapter_name}",
            message=f"Lapsed seat(s) {', '.join(row_names)} of {chapter_name} were not ended: {e}\n\n"
            f"{frappe.get_traceback()}",
        )
    return ended
