"""Regression tests for #628: "today" must be the SITE's calendar day.

``datetime.date.today()`` is the *server/process* date. ``frappe.utils.getdate()``
is the *site-timezone* date (``System Settings.time_zone``). Whenever the two name
different calendar days, code that reaches for ``date.today()`` judges "is this in
the past/future", "how old is this person", or "what date do I stamp on this row"
against the wrong day.

This is invisible most of the time, which is why the class kept escaping review:
a CI runner on UTC against a site on ``Asia/Kolkata`` (+5:30) only diverges between
18:30 and 24:00 UTC. Every green ``develop`` run before PR #620 happened to fall
outside that window.

These tests do not wait for that window. ``_site_tz_that_differs()`` picks a real
IANA timezone whose *current* calendar day differs from the process's, and installs
it as the site timezone for the duration of the assertion. ``Pacific/Kiritimati``
(+14) and ``Pacific/Midway`` (-11) are 25 hours apart, so at every instant at least
one of them is on a different date from the process -- the condition is forced
deterministically at any hour of any day, on any runner.

Mutation control, measured 2026-08-28 with all 11 production fixes reverted, run at
three process timezones:

    process TZ            failing
    UTC                   6 of 17
    Pacific/Midway        8 of 17
    Pacific/Kiritimati    6 of 17

9 distinct tests move across the three. The total varies with the ambient process
timezone because ``site_timezone_diverging_from_process`` installs whichever
candidate differs by calendar day, and both the DIRECTION of that difference and its
SIZE depend on the hour -- the size matters because the
``TestSepaRulebookMandateAgeUsesSiteToday`` pair only moves across a month boundary.

Do NOT use "the process on UTC" as a recipe for a direction. Measured at ~06:00 UTC
it selects ``Pacific/Midway`` and puts the site a day BEHIND -- the opposite of what
an earlier version of this docstring asserted. Assertions that only break in one
direction use ``site_a_day_ahead_of_process`` instead, which pins both clocks and is
therefore independent of the hour and of the runner's timezone.

Of the tests that never move: two are harness self-checks, four are deliberate
controls asserting the guards still fire, and one pins the injectable-``today``
contract.
"""

import datetime
import os
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager

import frappe
from dateutil.relativedelta import relativedelta
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_system_timezone, getdate, now_datetime

from verenigingen.services.member.utils.member_age_service import calculate_member_age
from verenigingen.utils.csv.procurios_mandate_validator import ProcuriosMandateValidator
from verenigingen.utils.csv.procurios_membership_validator import ProcuriosMembershipValidator
from verenigingen.verenigingen_payments.mollie.utils.validators import BusinessRuleValidator
from verenigingen.verenigingen_payments.ponto.core.ponto_models import PontoTransaction
from verenigingen.verenigingen_payments.utils.sepa_rulebook_validator import (
    SEPARulebookValidator,
    ValidationSeverity,
)
from verenigingen.verenigingen_payments.utils.sepa_xml_enhanced_generator import (
    EnhancedSEPAXMLGenerator,
    SEPACreditor,
    SEPALocalInstrument,
    SEPAMandate,
    SEPAPaymentInfo,
    SEPASequenceType,
)

# 25 hours apart, so their calendar dates can never both equal the process date.
_CANDIDATE_TIMEZONES = ("Pacific/Kiritimati", "Pacific/Midway")


def _site_tz_that_differs() -> str:
    """Return an IANA timezone whose current date differs from the process date."""
    process_date = datetime.datetime.now().date()
    for tz in _CANDIDATE_TIMEZONES:
        if datetime.datetime.now(datetime.timezone.utc).astimezone(_zoneinfo(tz)).date() != process_date:
            return tz
    raise AssertionError(
        f"neither {_CANDIDATE_TIMEZONES} differs from the process date {process_date}; "
        "they are 25 hours apart, so this is impossible unless tzdata is broken"
    )


def _zoneinfo(name):
    from zoneinfo import ZoneInfo

    return ZoneInfo(name)


@contextmanager
def site_timezone_diverging_from_process():
    """Run the block with the site timezone on a different calendar day than the process.

    Yields the site's date. ``frappe.local.system_settings`` is the first thing
    ``frappe.get_system_settings`` consults, so overriding it there really does
    change what ``getdate()`` returns -- nothing is stubbed out. Restored on exit.

    Hazard for future reuse: ``frappe.clear_cache()`` does ``del
    frappe.local.system_settings``, so calling it inside the block -- directly, or via
    a production path that does -- silently drops the override and reverts to the real
    site timezone. The entry guards cannot catch that; they run on entry. None of the
    current bodies call it.
    """
    original = getattr(frappe.local, "system_settings", None)
    try:
        settings = frappe.get_doc("System Settings")
        settings.time_zone = _site_tz_that_differs()
        frappe.local.system_settings = settings
        # Real raises, not asserts: `assert` is stripped under `python -O`, and a lever
        # that cannot report its own failure would make every test below silently
        # vacuous rather than red.
        if get_system_timezone() != settings.time_zone:
            raise RuntimeError(
                f"site timezone override did not take: asked for {settings.time_zone}, "
                f"get_system_timezone() still returns {get_system_timezone()}"
            )
        if getdate() == datetime.date.today():
            raise RuntimeError(
                f"no divergence installed: site and process are both on {getdate()}; "
                "the tests below would prove nothing"
            )
        yield getdate()
    finally:
        frappe.local.system_settings = original


@contextmanager
def site_a_day_ahead_of_process():
    """Run the block with the site exactly one calendar day ahead of the process.

    ``site_timezone_diverging_from_process`` is not enough for the assertions that
    only break in ONE direction -- "a date stamped today must not read as future".
    It guarantees a different calendar day and is satisfied just as happily by the
    candidate BEHIND the process, under which such a date is in the past and the
    guard passes whether or not it is fixed. Measured: wrapping the invoice-generator
    sign-date test in that lever left it green with the fix reverted.

    Forcing the direction cannot be done by choosing a site timezone alone. A site
    can only be a day ahead of a process at offset X when the process's local hour
    is at least ``10 + X``, because UTC+14 is the largest offset there is -- so for
    part of every day no site timezone is a day ahead, whatever we pick. This lever
    therefore pins BOTH clocks: the process to ``Pacific/Midway`` (UTC-11) via
    ``TZ`` + ``time.tzset()``, and the site to ``Pacific/Kiritimati`` (UTC+14). Those
    are 25 hours apart, so the site clock is always strictly AHEAD of the process
    clock -- which is the property the assertions actually rest on, since they
    compare instants.

    The guard checks exactly that, and deliberately NOT "exactly one calendar day
    ahead". 25 > 24 makes the site *at least* a day ahead, not exactly one: while
    Midway is at 23:00-23:59 (10:00-10:59 UTC) Kiritimati is already two calendar
    days later. A one-day guard therefore raised for one hour of every day, on every
    runner -- 6 of 144 ten-minute samples -- which made these two tests a scheduled
    red hour in CI rather than a flake. Reproduced live at 10:26 UTC.

    Both clocks are restored in ``finally``, and every mutation is made INSIDE the
    try so a failure between them cannot leave the process on UTC-11 for the rest of
    the shard. ``time.tzset()`` is process-global and POSIX-only; that is acceptable
    here because Frappe's test runner is single-threaded and CI is Linux.
    """
    original_settings = getattr(frappe.local, "system_settings", None)
    original_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Pacific/Midway"
        time.tzset()
        settings = frappe.get_doc("System Settings")
        settings.time_zone = "Pacific/Kiritimati"
        frappe.local.system_settings = settings
        if now_datetime() <= datetime.datetime.now():
            raise RuntimeError(
                "lever did not install a site clock ahead of the process: site is on "
                f"{now_datetime()}, process on {datetime.datetime.now()}"
            )
        yield getdate()
    finally:
        frappe.local.system_settings = original_settings
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()


class TestSiteTimezoneTodayHarness(FrappeTestCase):
    """The forcing lever itself must work, or every test below is vacuous."""

    def test_the_lever_actually_diverges_and_restores(self):
        tz_before, date_before = get_system_timezone(), getdate()
        with site_timezone_diverging_from_process() as site_today:
            self.assertNotEqual(tz_before, get_system_timezone())
            self.assertNotEqual(site_today, datetime.date.today())
            self.assertEqual(site_today, getdate())
        self.assertEqual(get_system_timezone(), tz_before)
        self.assertEqual(getdate(), date_before)

    def test_the_timezone_is_restored_even_when_the_block_raises(self):
        class _Sentinel(Exception):
            """Distinct from the RuntimeError the lever itself raises on failure."""

        tz_before = get_system_timezone()
        with self.assertRaises(_Sentinel):
            with site_timezone_diverging_from_process():
                raise _Sentinel("boom")
        self.assertEqual(get_system_timezone(), tz_before)


class TestAgeCalculationUsesSiteToday(FrappeTestCase):
    """member_age_service:36 and mollie validators:385."""

    def test_member_age_increments_on_the_site_birthday(self):
        with site_timezone_diverging_from_process() as site_today:
            birth_date = site_today.replace(year=site_today.year - 30)
            self.assertEqual(
                calculate_member_age(birth_date.isoformat()),
                30,
                "a member whose birthday is today (site tz) must already be 30",
            )

    def test_membership_eligibility_accepts_someone_turning_sixteen_today(self):
        with site_timezone_diverging_from_process() as site_today:
            birth_date = site_today.replace(year=site_today.year - 16)
            errors = BusinessRuleValidator.validate_membership_eligibility(
                {"birth_date": birth_date.isoformat()}
            )
            self.assertEqual(
                [e for e in errors if "16 years old" in e],
                [],
                "someone who turns 16 today (site tz) is eligible",
            )


class TestPontoDateFallbackUsesSiteToday(FrappeTestCase):
    """ponto_models:233 and :240 -- the fallback becomes a booking date."""

    def test_missing_date_falls_back_to_site_today(self):
        with site_timezone_diverging_from_process() as site_today:
            self.assertEqual(PontoTransaction._parse_date(None), site_today)

    def test_unparseable_date_falls_back_to_site_today(self):
        with site_timezone_diverging_from_process() as site_today:
            self.assertEqual(PontoTransaction._parse_date("not-a-date"), site_today)


class TestProcuriosValidatorsDefaultToSiteToday(FrappeTestCase):
    """procurios_mandate_validator:71 and procurios_membership_validator:35."""

    def test_mandate_validator_default_today(self):
        with site_timezone_diverging_from_process() as site_today:
            self.assertEqual(ProcuriosMandateValidator()._today, site_today)

    def test_membership_validator_default_today(self):
        with site_timezone_diverging_from_process() as site_today:
            self.assertEqual(ProcuriosMembershipValidator()._today, site_today)

    def test_an_injected_today_still_wins(self):
        """The injectable parameter is the contract; only the default changed."""
        pinned = datetime.date(2020, 1, 2)
        with site_timezone_diverging_from_process():
            self.assertEqual(ProcuriosMandateValidator(today=pinned)._today, pinned)
            self.assertEqual(ProcuriosMembershipValidator(today=pinned)._today, pinned)


class TestSepaXmlValidationUsesSiteToday(FrappeTestCase):
    """sepa_xml_enhanced_generator:301 and :419."""

    def _generator(self):
        gen = EnhancedSEPAXMLGenerator.__new__(EnhancedSEPAXMLGenerator)
        gen.validation_errors = []
        gen.validation_warnings = []
        return gen

    def _payment_info_due_on(self, collection_date):
        return SEPAPaymentInfo(
            payment_info_id="PI-628",
            payment_method="DD",
            batch_booking=True,
            requested_collection_date=collection_date,
            creditor=SEPACreditor(
                name="Test Creditor",
                iban="NL39RABO0300065264",
                bic="RABONL2U",
                creditor_id="NL98ZZZ999999990000",
            ),
            local_instrument=SEPALocalInstrument.CORE,
            sequence_type=SEPASequenceType.RCUR,
            transactions=[],
        )

    def test_same_day_collection_is_not_flagged_as_past(self):
        with site_timezone_diverging_from_process() as site_today:
            gen = self._generator()
            gen._validate_payment_info(self._payment_info_due_on(site_today), 0)
            self.assertEqual(
                [w for w in gen.validation_warnings if "Collection date is in the past" in w],
                [],
                "a collection requested for today (site tz) is not in the past",
            )

    def test_collection_genuinely_in_the_past_is_still_flagged(self):
        """Control: the warning must still fire, or the test above proves nothing."""
        with site_timezone_diverging_from_process() as site_today:
            gen = self._generator()
            gen._validate_payment_info(self._payment_info_due_on(site_today - datetime.timedelta(days=2)), 0)
            self.assertTrue(
                [w for w in gen.validation_warnings if "Collection date is in the past" in w]
            )

    def test_mandate_signed_today_is_not_flagged_as_future(self):
        with site_timezone_diverging_from_process() as site_today:
            gen = self._generator()
            gen._validate_mandate(SEPAMandate(mandate_id="M-628", date_of_signature=site_today), "P")
            self.assertEqual(
                [w for w in gen.validation_warnings if "signature date is in the future" in w],
                [],
                "a mandate signed today (site tz) is not future-dated",
            )

    def test_mandate_genuinely_future_dated_is_still_flagged(self):
        """Control for the test above."""
        with site_timezone_diverging_from_process() as site_today:
            gen = self._generator()
            gen._validate_mandate(
                SEPAMandate(mandate_id="M-628", date_of_signature=site_today + datetime.timedelta(days=2)),
                "P",
            )
            self.assertTrue(
                [w for w in gen.validation_warnings if "signature date is in the future" in w]
            )


class TestSepaRulebookMandateAgeUsesSiteToday(FrappeTestCase):
    """sepa_rulebook_validator:669 -- a day's shift moves months_diff at a month boundary.

    Scope note, measured: unlike the other cases here, this pair does NOT go red when
    the fix is reverted on an ordinary day. months_diff is computed from
    today_date.month, so a one-day disagreement only changes the answer when the two
    calendar days fall in different MONTHS -- roughly one day in thirty. These are
    therefore correctness assertions for the intended behaviour, not a mutation-proof
    guard. The month-boundary case is the one that actually bites in production.
    """

    def _issues_for_sign_date(self, sign_date):
        validator = SEPARulebookValidator()
        xml = (
            f'<Document xmlns="{SEPARulebookValidator.DEFAULT_NAMESPACE}"><MndtRltdInf>'
            f"<DtOfSgntr>{sign_date.isoformat()}</DtOfSgntr></MndtRltdInf></Document>"
        )
        return validator.validate_mandate_age(validator.rules[0], ET.fromstring(xml), xml)

    def test_mandate_exactly_36_months_old_is_accepted(self):
        with site_timezone_diverging_from_process() as site_today:
            self.assertEqual(self._issues_for_sign_date(site_today - relativedelta(months=36)), [])

    def test_mandate_older_than_36_months_is_still_rejected(self):
        """Control for the test above."""
        with site_timezone_diverging_from_process() as site_today:
            self.assertTrue(self._issues_for_sign_date(site_today - relativedelta(months=40)))


class TestSepaRulebookCreationDatetimeUsesSiteToday(FrappeTestCase):
    """sepa_rulebook_validator:447 -- CreDtTm is stamped on the SITE clock.

    ``sepa_xml_generation_service`` stores ``sepa_generation_date`` as
    ``f"{nowdate()} {nowtime()}"`` -- site timezone -- and the generator emits that
    as ``GrpHdr/CreDtTm``. Comparing it against ``datetime.now()`` (the process
    clock) reports a freshly generated file as "Creation datetime cannot be in the
    future" at severity CRITICAL.

    Unlike every other case in this module this is NOT the 18:30-24:00 window: the
    rule compares two instants rather than two calendar days, so it fires on every
    validation, all day, on any host whose process clock is behind the site's.
    Hence the offset lever rather than the calendar-day one.
    """

    def _issues_for_creation_datetime(self, moment):
        validator = SEPARulebookValidator()
        rule = next(r for r in validator.rules if r.rule_id == "MSG002")
        xml = (
            f'<Document xmlns="{SEPARulebookValidator.DEFAULT_NAMESPACE}"><GrpHdr>'
            f'<CreDtTm>{moment.strftime("%Y-%m-%dT%H:%M:%S")}</CreDtTm></GrpHdr></Document>'
        )
        return validator.validate_creation_datetime(rule, ET.fromstring(xml), xml)

    def test_a_file_stamped_on_the_site_clock_is_not_flagged_as_future(self):
        with site_a_day_ahead_of_process():
            site_now = now_datetime()
            self.assertEqual(self._issues_for_creation_datetime(site_now), [])

    def test_a_genuinely_future_creation_datetime_is_still_flagged(self):
        """Control: the rule must still fire on a real future stamp."""
        with site_a_day_ahead_of_process():
            site_now = now_datetime()
            issues = self._issues_for_creation_datetime(site_now + datetime.timedelta(days=1))
            self.assertTrue(issues)
            self.assertEqual(issues[0].severity, ValidationSeverity.CRITICAL)
