"""Helpers for asserting that a row's ``modified`` was written by the framework.

Background (#453)
-----------------
Frappe writes ``modified`` from ``frappe.utils.now()`` -- the **site** clock, with
microseconds -- into ``datetime(6)`` columns. Raw SQL that hand-writes
``modified = NOW()`` gets neither of those:

* ``NOW()`` is the **database server's** wall clock. Measured on ``test_site_4``
  2026-08-31: ``SELECT NOW()`` returned ``00:03:08`` while ``frappe.utils.now()``
  returned ``03:33:08`` -- 3h30m apart, because the site's ``time_zone`` is
  ``Asia/Kolkata`` and the server's is not. The size of that gap is
  environment-specific (it can be zero); its existence is not something a caller
  gets to assume.
* ``NOW()`` is **second** precision (``NOW(6)`` is the microsecond form), so the
  stored stamp is up to one second *earlier* than the write that produced it.

The second-precision half has a consequence that is easy to miss: Frappe's
optimistic lock (``Document.check_if_latest``) compares ``modified`` as a
**string**. Two writes inside the same second therefore produce the same stamp,
``check_if_latest`` sees no change, and a stale in-memory copy silently
overwrites the concurrent write instead of raising ``TimestampMismatchError``.
Measured on ``test_site_4``: two raw ``NOW()`` writes -> save succeeded; the same
sequence with ``NOW(6)`` and with ``frappe.db.set_value`` -> both raised.
"""

import time
from datetime import datetime

import frappe

# How close to the start of a second `wait_for_second_boundary` insists on being.
_BOUNDARY_TOLERANCE_US = 20_000


def raw_modified(doctype: str, name: str) -> datetime:
    """Read ``modified`` straight out of the table.

    Deliberately raw SQL rather than ``frappe.db.get_value``: the assertions here
    are about the exact value on disk, and any cached or re-serialised copy would
    hide the thing under test.
    """
    rows = frappe.db.sql(
        f"SELECT `modified` FROM `tab{doctype}` WHERE name = %s",  # nosec B608 - doctype is a literal at every call site
        (name,),
    )
    if not rows:
        raise AssertionError(f"{doctype} {name} has no row")
    return rows[0][0]


def wait_for_second_boundary() -> datetime:
    """Block until the site clock has just crossed into a new second.

    The defect this guards against is *second*-precision truncation, so a test
    that happens to start at ``.998`` would see the truncated stamp land in the
    following second and pass for the wrong reason. Starting just after a
    boundary gives the operation under test the best part of a second of
    headroom, which makes the red result deterministic instead of a coin flip on
    where in the second the test landed.

    Returns the moment it settled on, to be used as ``started_at``. It is
    guaranteed to carry a **non-zero** microsecond: at exactly ``.000000`` a
    truncated stamp compares equal to it and the lower bound in
    ``assert_site_clock_modified`` stops discriminating. Sampling here rather
    than asserting in the caller keeps that from being a rare red run.
    """
    while True:
        sampled = frappe.utils.now_datetime()
        if 0 < sampled.microsecond <= _BOUNDARY_TOLERANCE_US:
            return sampled
        time.sleep(0.002)


def assert_site_clock_modified(case, doctype: str, name: str, started_at: datetime) -> datetime:
    """Assert ``modified`` was written from the site clock during the operation.

    ``started_at`` must be the value ``wait_for_second_boundary()`` returned,
    sampled immediately before the operation. Both bounds matter: a
    database-clock stamp fails the lower bound in either direction of skew, and a
    second-truncated stamp falls below ``started_at`` because ``started_at``
    carries microseconds.

    Returns the stored value so callers can make further assertions on it.
    """
    # Contract check for a caller that sampled its own `started_at` instead of using the
    # one wait_for_second_boundary() returns: at exactly `.000000` a truncated stamp
    # compares equal and the lower bound below stops discriminating. It cannot fire for
    # a caller that uses the returned value.
    case.assertGreater(
        started_at.microsecond,
        0,
        msg=(
            "instrument not armed: started_at is exactly on a second boundary, so a "
            "second-truncated `modified` would compare equal to it. Use the value "
            "wait_for_second_boundary() returns."
        ),
    )
    stored = raw_modified(doctype, name)
    finished_at = frappe.utils.now_datetime()
    case.assertGreaterEqual(
        stored,
        started_at,
        msg=(
            f"{doctype} {name}: modified={stored} predates the start of the operation "
            f"({started_at}). A `modified` written by MariaDB's NOW() is on the database "
            f"server's clock and truncated to the second; Frappe writes the site clock "
            f"with microseconds. See #453."
        ),
    )
    case.assertLessEqual(
        stored,
        finished_at,
        msg=(
            f"{doctype} {name}: modified={stored} is in the future relative to the site "
            f"clock ({finished_at}). See #453."
        ),
    )
    return stored
