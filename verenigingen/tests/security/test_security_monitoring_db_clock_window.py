"""Regression tests for #668 (read side of #453): SecurityMonitor's business-rule
detectors build their "last hour"/"last day" window with MariaDB's own
``DATE_SUB(NOW(), INTERVAL ...)`` -- the DATABASE SERVER's clock -- while every
row's ``creation``/``modified`` is stamped by ``frappe.utils.now()``, the SITE
clock. Nothing keeps those two in step (measured 3h30m skew on ``test_site_4``,
2026-08-31).

``check_unusual_member_operations`` (this same file, fixed for #637) already
demonstrates the correct shape: compute the boundary in Python with
``now_datetime()`` and bind it as a query PARAMETER. The other five detectors
in this module did not follow that pattern; this file exercises the sharpest
of them -- ``check_sepa_operation_anomalies``, #668's own "sharpest single
site" example, and the one with the SHORTEST window (1 hour), so the smallest
DB-clock skew is enough to make it silently stop firing.

THE LEVER
---------
The real skew is between the MariaDB *server* clock and the site's configured
timezone, and neither can be moved from inside a test. What CAN be moved,
without touching the server or the site, is the current DB SESSION's
``time_zone`` setting -- and MariaDB's ``NOW()`` is computed in the SESSION
timezone (unlike a plain ``DATETIME`` column, which carries no zone and is
never converted). ``_mariadb_forward_skew`` MEASURES the SITE's own current
UTC offset first (``frappe.utils.get_system_timezone()``, converted with
``zoneinfo`` -- never assumed, since this bench's sites default to
``Asia/Kolkata`` while the DB server itself commonly runs a different zone),
then requests a DB session offset comfortably past it, so ``NOW()`` reads
AHEAD of the SITE clock that wrote every row's ``creation``/``modified``
regardless of what zone the database server itself happens to sit in. The
achieved skew relative to the site clock is measured again (never assumed)
and handed to the caller.

A boundary computed with ``frappe.utils.now_datetime()`` and bound as a query
parameter is sent as a literal value; nothing about the DB session's timezone
setting touches it. A boundary computed by asking the database to evaluate
``NOW()`` is exactly as skewed, relative to the site clock, as the session's
configured offset is. That is the entire difference under test.
"""

import datetime
from contextlib import contextmanager
from zoneinfo import ZoneInfo

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_system_timezone, now_datetime, today

from verenigingen.utils.security.security_monitoring import SecurityMonitor
from verenigingen.utils.validation.iban_validator import generate_test_iban

#: How far past the SITE's own UTC offset the DB session clock is pushed.
#: Comfortably exceeds the 1-hour window under test; the MariaDB offset
#: ceiling (13:00) still leaves this much margin for every real site
#: timezone up to and including Kiritimati/Tonga's +13:00 -- and this app's
#: test sites run Asia/Kolkata (+05:30), nowhere near that ceiling.
_MARGIN_HOURS = 2


@contextmanager
def _mariadb_forward_skew(margin_hours=_MARGIN_HOURS):
    """Push this session's ``NOW()`` at least `margin_hours` ahead of the
    SITE's own clock (never the DB server's ambient zone, which is a
    different, irrelevant quantity -- see the module docstring). Yields the
    measured skew (a ``timedelta``) between the shifted ``NOW()`` and
    ``frappe.utils.now_datetime()``, sampled together.
    """
    site_offset_hours = (
        datetime.datetime.now(ZoneInfo(get_system_timezone())).utcoffset().total_seconds() / 3600
    )
    target_hours = min(site_offset_hours + margin_hours, 13)  # MariaDB's offset ceiling
    sign = "+" if target_hours >= 0 else "-"
    whole = int(abs(target_hours))
    minutes = int(round((abs(target_hours) - whole) * 60))
    offset_str = f"{sign}{whole:02d}:{minutes:02d}"

    frappe.db.sql("SET time_zone = %s", (offset_str,))
    try:
        db_now = frappe.db.sql("SELECT NOW()")[0][0]
        site_now = now_datetime()
        yield db_now - site_now
    finally:
        frappe.db.sql("SET time_zone = 'SYSTEM'")


class TestMariadbForwardSkewLever(FrappeTestCase):
    """Control: the lever itself must actually move ``NOW()`` past the SITE
    clock by at least the requested margin, or every test below that relies
    on it would pass for the wrong reason."""

    def test_the_lever_measurably_leads_the_site_clock(self):
        with _mariadb_forward_skew() as skew:
            self.assertGreaterEqual(
                skew.total_seconds(),
                (_MARGIN_HOURS - 1) * 3600,  # allow a little clock jitter / rounding
                f"expected DB NOW() to read at least ~{_MARGIN_HOURS}h ahead of the "
                f"SITE clock; measured a skew of only {skew}. This bench's site "
                "timezone must already be unusually close to the MariaDB offset "
                "ceiling for the clamp to have eaten the requested margin.",
            )

    def test_now_reverts_after_the_lever_exits(self):
        before = frappe.db.sql("SELECT NOW()")[0][0]
        with _mariadb_forward_skew():
            pass
        after = frappe.db.sql("SELECT NOW()")[0][0]
        self.assertLess(abs((after - before).total_seconds()), 5)


class TestCheckSepaOperationAnomaliesUsesSiteClock(FrappeTestCase):
    """``check_sepa_operation_anomalies`` --
    ``creation > DATE_SUB(NOW(), INTERVAL 1 HOUR)``, grouped by owner
    ``HAVING count > 5``. #668 names this exact line as "the sharpest single
    site" of the 94 it found: the shortest window among the five detectors in
    this module, so the smallest DB-clock skew already breaks it.

    ``member`` is optional on SEPA Mandate ("leave blank for non-member
    donors"), which keeps this fixture free of any Member/Company dependency.
    """

    def setUp(self):
        super().setUp()
        self.monitor = SecurityMonitor()
        self.tag = frappe.generate_hash(length=8)
        self.mandate_names = []
        for i in range(6):  # HAVING count > 5 needs at least 6 for one owner
            mandate = frappe.get_doc(
                {
                    "doctype": "SEPA Mandate",
                    "mandate_id": f"TZ668-{self.tag}-{i}",
                    "iban": generate_test_iban("TEST"),
                    "account_holder_name": f"TZ668 Probe {i}",
                    "sign_date": today(),
                    "status": "Active",
                    "scheme": "SEPA",
                    "mandate_type": "RCUR",
                }
            ).insert(ignore_permissions=True)
            self.mandate_names.append(mandate.name)
        self.addCleanup(self._delete_mandates)

    def _delete_mandates(self):
        for name in self.mandate_names:
            frappe.delete_doc("SEPA Mandate", name, force=True, ignore_permissions=True)

    def _backdate_mandates(self, when):
        for name in self.mandate_names:
            frappe.db.set_value("SEPA Mandate", name, "creation", when, update_modified=False)
        frappe.db.commit()

    def _alert_fired_for_current_user(self):
        alerts = self.monitor.check_sepa_operation_anomalies()
        return any(a["user"] == frappe.session.user for a in alerts)

    def test_six_mandates_created_moments_ago_are_not_hidden_by_a_forward_db_clock(self):
        """RED unfixed: a forward DB-session skew pushes the cutoff PAST the
        mandates' real (site-clock) creation timestamps, so a rapid-creation
        burst that happened moments ago silently drops out of the alert --
        the "empty window" failure mode #668 names as the more dangerous
        direction for a security monitor.
        """
        self.assertTrue(
            self._alert_fired_for_current_user(),
            "sanity: 6 mandates just created by this user must trip the >5-in-1h alert "
            "with the session clock untouched",
        )
        with _mariadb_forward_skew():
            self.assertTrue(
                self._alert_fired_for_current_user(),
                "6 SEPA Mandates created moments ago must still trip the rapid-creation "
                "alert even when the DATABASE session clock has drifted forward of the "
                "SITE clock that wrote `creation`",
            )

    def test_mandates_created_two_hours_ago_are_still_excluded(self):
        """Control: the fix must not turn the detector into "everything always
        alerts" -- a burst that genuinely happened outside the 1-hour window
        stays excluded even under the same forward DB-session skew.
        """
        self._backdate_mandates(add_to_date(now_datetime(), hours=-2))
        with _mariadb_forward_skew():
            self.assertFalse(
                self._alert_fired_for_current_user(),
                "6 SEPA Mandates created 2 hours ago must NOT trip a last-1h alert; the "
                "fix must still respect the window's outer edge",
            )
