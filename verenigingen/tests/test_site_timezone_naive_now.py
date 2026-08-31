"""Regression tests for #637: the OTHER spellings of the naive-process-clock bug.

#628 fixed ``datetime.date.today()``. That was one spelling. The same defect
written as ``datetime.now().date()`` / ``.year`` / ``.month``, as
``datetime.now().strftime("%Y%m%d")``, and as a bare ``datetime.now()`` compared
against a value Frappe wrote on the SITE clock, was never searched for -- the
last shape contains no ``today`` at all, which is why a name-based grep left the
class open.

Two kinds of test live here, and the split is deliberate.

**Behavioural tests** use the levers from ``test_site_timezone_today`` to force
the site and process clocks onto different calendar days, then assert on a
boundary that moves with them. Each is red at any hour of any day with its fix
reverted, and each is paired with a control so a trivially-passing assertion
cannot masquerade as a guard.

**The ratchet** (``TestNoNaiveProcessClockCalendarReads``) exists because a
behavioural test cannot cover the year/month sites. ``datetime.now().year``
disagrees with ``getdate().year`` only across a New Year boundary -- roughly one
day in 365 -- so a behavioural assertion on it is vacuous on 364 days and would
be a guard in name only. Pinning the *shape* is the only honest instrument for
those, and it covers every site this class touches rather than the handful that
happen to be reachable as pure functions.

Mutation control, measured 2026-08-31 on test_site_2, ONE fix reverted at a
time (not all at once -- a simultaneous revert cannot say which test guards
which fix):

    reverted                     red
    batch_validation_service     test_a_date_inside_the_minimum_notice_is_rejected
    mollie_debug_service         test_today_is_not_at_least_tomorrow
    sepa_mandate_manager         both TestMandateReferenceUsesSiteToday tests
    membership_analytics:37      the ratchet, naming that exact line

The paired control stayed green in every case, so none of these is a test that
merely reacts to any edit.
"""

import ast
import datetime
import os
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from verenigingen.services.mollie_debug_service import MollieDebugService
from verenigingen.services.payment.sepa_mandate_manager import SEPAMandateManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.test_site_timezone_today import (
    site_a_day_ahead_of_process,
    site_timezone_diverging_from_process,
)
from verenigingen.verenigingen.doctype.member.member_utils import generate_mandate_reference
from verenigingen.verenigingen_payments.services.batch_validation_service import BatchValidationService


class TestBatchCollectionDateUsesSiteToday(FrappeTestCase):
    """batch_validation_service:185 -- DATE_TOO_EARLY is an ERROR, so it blocks a batch.

    The notice-day window is measured from "today". With the site a day AHEAD of
    the process, an unfixed ``datetime.now().date()`` puts the earliest allowed
    collection date one day too early, so a date the SEPA rulebook forbids is
    waved through.
    """

    def _errors_for(self, collection_date):
        result = BatchValidationService()._validate_collection_date(collection_date.isoformat())
        return [e for e in result.errors if e.get("code") == "DATE_TOO_EARLY"]

    def _minimum_notice_days(self):
        return BatchValidationService().config_service.get_collection_date_settings()[
            "minimum_notice_days"
        ]

    def test_a_date_inside_the_minimum_notice_is_rejected(self):
        """Red unfixed: the process day is behind, so this date looks far enough out."""
        with site_a_day_ahead_of_process():
            too_early = getdate() + datetime.timedelta(days=self._minimum_notice_days() - 1)
            self.assertTrue(
                self._errors_for(too_early),
                "a collection date inside the SEPA minimum notice must be rejected, "
                "and the notice is counted from the SITE's today",
            )

    def test_a_date_at_the_minimum_notice_is_accepted(self):
        """Control: the guard must not reject everything, or the test above is empty."""
        with site_a_day_ahead_of_process():
            just_far_enough = getdate() + datetime.timedelta(days=self._minimum_notice_days())
            self.assertEqual(self._errors_for(just_far_enough), [])


class TestMollieDueDateWindowUsesSiteToday(FrappeTestCase):
    """mollie_debug_service:2088,2089 -- "due date must be at least tomorrow".

    ``create_test_payment`` validates the due date before it touches the Mollie
    client, so the object is built with ``__new__``: reaching the validation
    needs no credentials, and anything past it fails on the missing client with
    an AttributeError, which is distinguishable from the ValueError under test.
    """

    #: Returned when the call reached PAST the due-date guard. Distinguishing this
    #: from "no exception" is load-bearing: `_reject_reason` used to return None for
    #: both, so `assertNotIn(x, None or "")` was `assertNotIn(x, "")` -- trivially
    #: true, and unable to tell "the guard accepted" from "something blew up".
    PASSED_GUARD = "PASSED_DATE_GUARD"

    def _reject_reason(self, due_date):
        service = MollieDebugService.__new__(MollieDebugService)
        try:
            service.create_test_payment(1.0, "tz probe", due_date=due_date.isoformat())
        except ValueError as exc:
            return str(exc)
        except Exception as exc:
            return f"{self.PASSED_GUARD}:{type(exc).__name__}"
        return self.PASSED_GUARD

    def test_today_is_not_at_least_tomorrow(self):
        """Red unfixed: with the process a day behind, site-today looks like tomorrow."""
        with site_a_day_ahead_of_process():
            self.assertIn("at least tomorrow", self._reject_reason(getdate()) or "")

    def test_tomorrow_is_accepted(self):
        """Control: the guard must let a genuinely future due date through.

        Asserts the call REACHED past the date guard, not merely that it did not
        say "at least tomorrow" -- an assertion the old version satisfied by
        swallowing an unrelated AttributeError.
        """
        with site_a_day_ahead_of_process():
            reason = self._reject_reason(getdate() + datetime.timedelta(days=1))
            self.assertTrue(
                reason.startswith(self.PASSED_GUARD),
                f"a due date one site-day out must clear the guard; got {reason!r}",
            )

    def test_a_date_beyond_the_hundred_day_ceiling_is_still_rejected(self):
        """Control for the upper bound, which moves with the same clock."""
        with site_a_day_ahead_of_process():
            reason = self._reject_reason(getdate() + datetime.timedelta(days=200))
            self.assertIn("100 days", reason or "")


class TestMandateReferenceUsesSiteToday(EnhancedTestCase):
    """member_utils:748 and sepa_mandate_manager:495 -- a `unique: 1` field.

    Both stamp ``M-{member_id}-{YYYYMMDD}-{seq}`` into ``SEPA Mandate.mandate_id``,
    which `sepa_mandate.json` declares ``unique: 1``. `member_utils` is the half with
    the REACHABLE defect: it takes the date string from one clock and bounds its
    same-day sequence lookup with ``creation >= <midnight>`` from the other, and
    ``creation`` is site-written. Where the site is behind the process, a mandate
    created minutes ago falls outside that window, the sequence resets to 001, and the
    suggested reference duplicates one that already exists.

    The manager's own lookup is keyed ONLY on the date string inside `mandate_id`, with
    no ``creation`` filter, so a wrong clock there mislabels the day but cannot by
    itself collide. Both are fixed; the asymmetry is why `member_utils` gets the
    fixture-backed test rather than only the cheap one.

    The lever guarantees the two clocks name different calendar days, so every
    assertion below is red with its fix reverted, in either direction, at any hour.
    """

    def setUp(self):
        super().setUp()
        # Built OUTSIDE the lever on purpose: `create_test_member` runs production
        # code that may `frappe.clear_cache()`, and that deletes
        # `frappe.local.system_settings` -- silently dropping the timezone override
        # the levers install. The lever's own docstring names this hazard.
        self.member = self.create_test_member(
            first_name="Tz",
            last_name="Probe637",
            birth_date="1990-01-01",
            email=f"tz.probe637.{frappe.generate_hash(length=8)}@example.com",
        )

    @staticmethod
    def _day_of(reference):
        """`M-{member_id}-{YYYYMMDD}-{seq}` -> the YYYYMMDD field."""
        return reference.split("-")[2]

    def test_the_manager_stamps_the_site_day(self):
        manager = SEPAMandateManager()
        with site_timezone_diverging_from_process() as site_today:
            reference = manager.generate_mandate_reference(self.member.name, member_id="TZ637")
            self.assertEqual(
                self._day_of(reference),
                site_today.strftime("%Y%m%d"),
                "the day inside mandate_id must be the day the row's own creation and "
                "sign_date name, and those are site-tz",
            )

    def test_member_utils_stamps_the_site_day(self):
        """The half with the reachable collision. Untested until #637's review.

        Calls the real whitelisted endpoint against a real Member, so the
        `creation >= <midnight>` filter beside the date stamp is exercised too.
        """
        with site_timezone_diverging_from_process() as site_today:
            suggested = generate_mandate_reference(self.member.name)["mandate_reference"]
            self.assertEqual(
                self._day_of(suggested),
                site_today.strftime("%Y%m%d"),
                "the suggested reference's day must be the SITE's -- it is compared "
                "against SEPA Mandate.creation, which Frappe writes on the site clock",
            )

    def test_the_two_generators_agree_on_the_day(self):
        """They write the same `unique: 1` column, so they must name the same day.

        This calls BOTH functions. An earlier version called only the manager and
        compared it to `getdate()`, which made it a rename of the test above rather
        than a second guard.
        """
        manager = SEPAMandateManager()
        with site_timezone_diverging_from_process() as site_today:
            suggested = generate_mandate_reference(self.member.name)["mandate_reference"]
            allocated = manager.generate_mandate_reference(self.member.name, member_id="TZ637")
            self.assertEqual(
                self._day_of(suggested),
                self._day_of(allocated),
                "the suggesting and allocating generators must stamp the same day",
            )
            self.assertEqual(self._day_of(suggested), site_today.strftime("%Y%m%d"))


class TestNoNaiveProcessClockCalendarReads(FrappeTestCase):
    """Ratchet: the modules fixed for #637 may not read the process calendar again.

    This is the class gate, not an instance test. It walks the AST rather than
    grepping, so a comment or a docstring mentioning ``datetime.now().date()``
    cannot trip it -- and, unlike the grep in #637's own body, it sees
    ``(datetime.now() + delta).date()`` and ``datetime.now().strftime("%Y%m%d")``,
    the two spellings that hid sites from every earlier sweep. The strftime arm
    is what found ``sepa_mandate_manager:444``, the allocating twin of
    ``member_utils:729``, after a name-based sweep had already declared the file
    clean.

    ``datetime.now()`` used as a plain instant (a duration, a log timestamp, a
    value compared only against another value this same process stamped) is NOT
    a defect and is deliberately not pinned here.

    Known blind spot, measured rather than assumed: the receiver is resolved from
    the module's ``import`` statements, so a clock reached without one --
    ``__import__("datetime").datetime.now()`` -- is invisible. That spelling
    appears nowhere in this app and is not worth the false positives that
    matching any ``.now()`` would cost, but it is a gap, not an oversight.
    """

    #: The only production files allowed to reduce the process clock to a calendar
    #: day. Each is here for a stated reason, and the scan is whole-tree so a NEW
    #: module cannot escape simply by not being on a list -- which is what let
    #: `my_dues_schedule.py` sit outside the first version of this guard.
    EXEMPT = {
        # Bounds a Mollie API date range, not a site-clock DB column. #637 carves
        # "naive datetime.now() passed to the Mollie API, which wants UTC" out as a
        # DIFFERENT bug; fixing these site-tz without settling which clock that
        # boundary belongs to would be guessing.
        "templates/pages/mollie_payments_debug.py",
        "verenigingen_payments/services/balance_transaction_processor.py",
        # A log FILENAME stamp. Cosmetic -- though note the file is internally
        # inconsistent: the name uses the process day, the body six lines later
        # uses frappe.utils.now_datetime().
        "e_boekhouden/utils/migration_error_logger.py",
    }

    _NAIVE_ATTRS = {"today", "now", "utcnow"}
    _CAL_ATTRS = {"date", "year", "month", "day"}
    _TIME_DIRECTIVES = ("%H", "%M", "%S", "%f", "%I", "%p", "%X", "%c", "%Z", "%z")
    _DATE_DIRECTIVES = ("%Y", "%y", "%m", "%d", "%j", "%B", "%b", "%A", "%a")

    @classmethod
    def _app_root(cls):
        import verenigingen

        return os.path.dirname(os.path.abspath(verenigingen.__file__))

    @classmethod
    def _dotted(cls, node):
        bits = []
        while isinstance(node, ast.Attribute):
            bits.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            bits.append(node.id)
            return ".".join(reversed(bits))
        return None

    @classmethod
    def _clock_receivers(cls, tree):
        """Names in this module that denote ``datetime.datetime`` or ``datetime.date``.

        Resolving the import rather than hard-coding the receiver matters: the
        control below writes ``from datetime import datetime as dt``, and a
        detector keyed on the literal text ``datetime.`` sees nothing there.
        """
        receivers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "datetime":
                        module = alias.asname or "datetime"
                        receivers.update({module + ".datetime", module + ".date"})
            elif isinstance(node, ast.ImportFrom) and node.module == "datetime":
                for alias in node.names:
                    if alias.name in ("datetime", "date"):
                        receivers.add(alias.asname or alias.name)
        return receivers

    @classmethod
    def _naive_clock_call(cls, node, receivers):
        """The spelling if `node` reads the PROCESS clock, else None."""
        if not isinstance(node, ast.Call):
            return None
        d = cls._dotted(node.func)
        if not d or "." not in d:
            return None
        receiver, attr = d.rsplit(".", 1)
        if attr not in cls._NAIVE_ATTRS or receiver not in receivers:
            return None
        if attr == "now" and (node.args or node.keywords):
            return None  # datetime.now(tz) names its zone; not naive
        return d + "()"

    @classmethod
    def _date_only_strftime(cls, node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            return False
        if node.func.attr != "strftime" or not node.args:
            return False
        fmt = node.args[0]
        if not isinstance(fmt, ast.Constant) or not isinstance(fmt.value, str):
            return False
        if any(d in fmt.value for d in cls._TIME_DIRECTIVES):
            return False
        return any(d in fmt.value for d in cls._DATE_DIRECTIVES)

    @classmethod
    def calendar_reads(cls, path):
        """Every process-clock read in `path` that is reduced to a calendar day."""
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source)
        receivers = cls._clock_receivers(tree)
        parent = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parent[child] = node

        found = []
        for node in ast.walk(tree):
            spelling = cls._naive_clock_call(node, receivers)
            if not spelling:
                continue
            if spelling.endswith("today()"):
                found.append((node.lineno, spelling))
                continue

            # Names bound from THIS node. Scoping matters: a module-wide tainted
            # set marks a plain instant as a calendar read merely because some
            # other naive value elsewhere was strftime'd. The control below
            # catches exactly that.
            bound_here = set()
            for assign in ast.walk(tree):
                if isinstance(assign, ast.Assign) and any(
                    c is node for c in ast.walk(assign.value)
                ):
                    for target in assign.targets:
                        if isinstance(target, ast.Name):
                            bound_here.add(target.id)

            reduced = False
            cur = node
            for _ in range(3):  # `.date`, `(now + delta).date`, `.strftime(...)`
                cur = parent.get(cur)
                if cur is None:
                    break
                if isinstance(cur, ast.Attribute) and cur.attr in cls._CAL_ATTRS:
                    reduced = True
                    break
                if cls._date_only_strftime(cur):
                    reduced = True
                    break
            if not reduced and bound_here:
                # The naive value bound to a local and reduced LATER, which is the
                # `now = datetime.now()` ... `f"{now.year}-01-01"` shape. Checking only
                # strftime here was a real hole: it left three live sites invisible
                # (`my_dues_schedule`, and the year/month reads it shares with the
                # payment dashboards) while the guard above reported a clean tree.
                for use in ast.walk(tree):
                    if cls._date_only_strftime(use) and isinstance(use.func.value, ast.Name) \
                            and use.func.value.id in bound_here:
                        reduced = True
                        break
                    if isinstance(use, ast.Attribute) and use.attr in cls._CAL_ATTRS \
                            and isinstance(use.value, ast.Name) and use.value.id in bound_here:
                        reduced = True
                        break
            if reduced:
                found.append((node.lineno, spelling))
        return found

    def _production_modules(self):
        root = self._app_root()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in ("node_modules", "__pycache__", "tests", "test")]
            for fn in sorted(filenames):
                if fn.endswith(".py") and not fn.startswith("test_"):
                    path = os.path.join(dirpath, fn)
                    yield os.path.relpath(path, root), path

    def test_production_reads_no_process_calendar(self):
        offenders = []
        for rel, path in self._production_modules():
            if rel in self.EXEMPT:
                continue
            try:
                reads = self.calendar_reads(path)
            except (SyntaxError, UnicodeDecodeError):
                continue
            for lineno, spelling in reads:
                offenders.append(f"{rel}:{lineno} {spelling}")
        self.assertEqual(
            offenders,
            [],
            "these read the PROCESS calendar; use frappe.utils.getdate()/now_datetime() "
            "so the day agrees with every other date this app stores (#628, #637):\n"
            + "\n".join(offenders),
        )

    def test_every_exemption_still_names_a_real_offender(self):
        """An exemption that no longer applies is a hole nobody will notice.

        If one of these is fixed or deleted, this fails and the entry must go --
        otherwise the set silently grows into an allowlist of the kind that let
        `my_dues_schedule.py` escape the first version of this guard.
        """
        root = self._app_root()
        stale = []
        for rel in sorted(self.EXEMPT):
            path = os.path.join(root, rel)
            if not os.path.exists(path) or not self.calendar_reads(path):
                stale.append(rel)
        self.assertEqual(stale, [], f"exemptions that no longer name an offender: {stale}")

    def test_the_detector_sees_every_spelling(self):
        """Control: a detector that finds nothing must be shown able to find something.

        Without this, ``offenders == []`` above is equally consistent with "the
        code is clean" and "the walk is broken" -- the failure mode that made an
        earlier sweep in this repo report 0 for all four of its targets.
        """
        import tempfile

        sample = (
            "import datetime\n"
            "from datetime import datetime as dt\n"
            "def f(x):\n"
            "    a = datetime.date.today()\n"
            "    b = dt.now().date()\n"
            "    c = dt.now().year\n"
            "    d = (dt.now() + x).date()\n"
            "    e = dt.now()\n"
            "    g = e.strftime('%Y%m%d')\n"
            "    # a comment naming date.today() and datetime.now().month\n"
            "    h = dt.now()          # a plain instant: NOT a calendar read\n"
            "    i = dt.now().strftime('%Y-%m-%d %H:%M:%S')  # a timestamp, not a day\n"
            "    j = datetime.datetime.now().month\n"
            "    k = datetime.datetime.now()\n"
            "    m = k.year\n"
            "    return a, b, c, d, g, h, i, j, m\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write(sample)
            probe = fh.name
        try:
            lines = {lineno for lineno, _ in self.calendar_reads(probe)}
        finally:
            os.unlink(probe)
        self.assertEqual(
            lines,
            {4, 5, 6, 7, 8, 13, 14},
            "the detector must see date.today(), .date(), .year, (now+delta).date(), a "
            "date-only strftime on a bound name, `datetime.datetime.now().month` via a "
            "plain `import datetime`, and `.year` on a name bound EARLIER -- and must "
            "NOT see the comment, the plain instant, or the time-bearing strftime",
        )

class TestCrossClockFilesStayOffTheProcessClock(unittest.TestCase):
    """The XDB class -- the shape with no ``today`` in it anywhere.

    The ratchet above pins CALENDAR reads. It cannot see a bare
    ``datetime.now() - timedelta(hours=24)`` handed to a query as a bound, because
    the same expression is perfectly correct when both ends are process-local
    (``retry_policy``, ``token_manager``, ``settlement_cache`` all do it legitimately).
    Distinguishing them needs whole-program reasoning about where the OTHER operand
    came from, and a gate that guesses would either miss cases or cry wolf.

    So this pins the narrow, decidable thing instead: in these six files, which were
    audited one call at a time for #637, EVERY process-clock read was cross-clock and
    none was legitimate. A file-scoped "no ``datetime.now()`` here" is therefore exact
    -- no judgement, no false positives -- and it covers the group the ratchet above
    admits it cannot.

    This is a smaller claim than "the XDB class is guarded". It is not guarded
    globally; 80 ``datetime.now()`` call sites remain in production, most of them
    legitimately process-local. What is guarded is that these six do not regress.
    """

    CROSS_CLOCK_FILES = (
        "events/delayed_expense_hooks.py",
        "templates/pages/my_dues_schedule.py",
        "utils/auth_monitoring.py",
        "utils/security/security_monitoring.py",
        "utils/session_cleanup_enhanced.py",
        "verenigingen_payments/services/sepa_xml_adapter.py",
    )

    def test_no_process_clock_reads_remain(self):
        root = TestNoNaiveProcessClockCalendarReads._app_root()
        offenders = []
        for rel in self.CROSS_CLOCK_FILES:
            path = os.path.join(root, rel)
            self.assertTrue(os.path.exists(path), f"file has moved: {rel}")
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            receivers = TestNoNaiveProcessClockCalendarReads._clock_receivers(tree)
            for node in ast.walk(tree):
                spelling = TestNoNaiveProcessClockCalendarReads._naive_clock_call(
                    node, receivers
                )
                if spelling:
                    offenders.append(f"{rel}:{node.lineno} {spelling}")
        self.assertEqual(
            offenders,
            [],
            "every clock read in these files is compared against a value Frappe wrote "
            "on the SITE clock, so it must use frappe.utils.now_datetime() (#637):\n"
            + "\n".join(offenders),
        )
