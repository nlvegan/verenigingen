"""#2192: a Mollie UTC timestamp is dated by the SITE-LOCAL day, never the UTC day.

Sibling of #2162. Covers the Bank Transaction dates and their duplicate check, the
date-window filters and the per-day buckets. Test sites run Asia/Kolkata and CI runs
UTC, so every test pins ``System Settings.time_zone`` and derives the expected day
with pytz from the same zone; nothing here depends on the zone of the machine.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
import pytz
from frappe.utils import add_days, getdate, today

from verenigingen.tests.payment.test_bulk_transaction_importer_sweep import (
    _BulkImporterSweepBase,
    _payment,
    _StubPaymentsClient,
)
from verenigingen.tests.payment.test_mollie_bulk_run_fetch import _FakePage, _mk_payment
from verenigingen.tests.support.system_timezone import system_timezone
from verenigingen.tests.test_site_timezone_today import site_a_day_ahead_of_process
from verenigingen.verenigingen_payments.monitoring.balance_monitor import BalanceMonitor
from verenigingen.verenigingen_payments.services import mollie_bulk_run_service as svc

# (zone, UTC instant). In each the local day differs from the UTC day, in opposite directions.
EAST = ("Europe/Amsterdam", "2026-03-03T23:30:00.000Z")  # local 00:30 on the 4th
WEST = ("Pacific/Honolulu", "2026-03-04T05:00:00.000Z")  # local 19:00 on the 3rd
CASES = (EAST, WEST)


def local_day(zone, stamp):
    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return moment.astimezone(pytz.timezone(zone)).date()


def utc_day(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc).date()


class TestFixturesDiffer(_BulkImporterSweepBase):
    def test_control_local_day_differs_from_utc_day_in_both_cases(self):
        """If a case stopped differing, every test below would pass on the buggy code too."""
        for zone, stamp in CASES:
            self.assertNotEqual(local_day(zone, stamp), utc_day(stamp), zone)
        self.assertGreater(local_day(*EAST), utc_day(EAST[1]))
        self.assertLess(local_day(*WEST), utc_day(WEST[1]))


class TestBankTransactionLocalDay(_BulkImporterSweepBase):
    def _payment_bt_date(self, zone, stamp):
        pid = f"tr_local_{self.uid}"
        payment = _payment(pid, createdAt=stamp)
        with system_timezone(zone):
            result = self.imp._process_payment_for_import(payment, self.company, self.bank_account)
        self.assertTrue(result.get("imported"), result)
        return frappe.db.get_value("Bank Transaction", result["transaction"], "date")

    def test_payment_bank_transaction_is_dated_by_the_local_day(self):
        for zone, stamp in CASES:
            with self.subTest(zone=zone):
                frappe.db.delete("Bank Transaction", {"custom_mollie_payment_id": f"tr_local_{self.uid}"})
                self.assertEqual(self._payment_bt_date(zone, stamp), local_day(zone, stamp))

    def test_settlement_bank_transaction_is_dated_by_the_local_day(self):
        for zone, stamp in CASES:
            with self.subTest(zone=zone):
                sid = f"stl_local_{self.uid}_{zone[:3]}"
                settlement = {
                    "id": sid,
                    "reference": sid,
                    "settledAt": stamp,
                    "amount": {"value": "40.00", "currency": "EUR"},
                }
                with system_timezone(zone):
                    result = self.imp._process_settlement_for_import(
                        settlement, self.company, self.bank_account
                    )
                self.assertEqual(result.get("imported"), 1, result)
                self.assertEqual(
                    frappe.db.get_value("Bank Transaction", result["transaction"], "date"),
                    local_day(zone, stamp),
                )


class TestDuplicateCheckFollowsTheStoredDate(_BulkImporterSweepBase):
    def _import(self, payment, zone):
        self.imp.payments_client = _StubPaymentsClient([payment])
        with system_timezone(zone):
            return self.imp._import_payment_data(
                datetime(2026, 3, 1), datetime(2026, 3, 31), self.company, self.bank_account
            )

    def test_reimport_after_this_change_is_skipped(self):
        zone, stamp = EAST
        payment = _payment(f"tr_again_{self.uid}", createdAt=stamp)
        self.assertEqual(self._import(payment, zone)["imported"], 1)
        again = self._import(payment, zone)
        self.assertEqual((again["imported"], again["duplicates_skipped"]), (0, 1))

    def _seed_row_stored_with_the_utc_day(self, payment_id, stamp, with_payment_id, day=None):
        """A row as the pre-#2192 importer stored it: UTC day, no local-day shift."""
        bt = frappe.new_doc("Bank Transaction")
        bt.date = day or utc_day(stamp)
        bt.bank_account = self.bank_account
        bt.company = self.company
        bt.currency = "EUR"
        bt.deposit = 25.0
        bt.reference_number = payment_id
        if with_payment_id:
            bt.custom_mollie_payment_id = payment_id
        bt.insert(ignore_permissions=True)
        self.created_records.append(("Bank Transaction", bt.name))

    def test_row_imported_before_this_change_still_matches_when_it_carries_the_id(self):
        zone, stamp = EAST
        pid = f"tr_old_id_{self.uid}"
        self._seed_row_stored_with_the_utc_day(pid, stamp, with_payment_id=True)
        out = self._import(_payment(pid, createdAt=stamp, value="25.00"), zone)
        self.assertEqual((out["imported"], out["duplicates_skipped"]), (0, 1))

    def test_row_imported_before_this_change_matches_on_the_utc_day_without_the_id(self):
        """Amount + date + reference is the only key such a row has; it was stored on the UTC day."""
        zone, stamp = EAST
        pid = f"tr_old_noid_{self.uid}"
        self._seed_row_stored_with_the_utc_day(pid, stamp, with_payment_id=False)
        out = self._import(_payment(pid, createdAt=stamp, value="25.00"), zone)
        self.assertEqual((out["imported"], out["duplicates_skipped"]), (0, 1))

    def test_row_on_the_local_day_matches_on_amount_date_and_reference(self):
        """The duplicate-check date moved with the stored date: it is the local day too."""
        zone, stamp = EAST
        pid = f"tr_new_noid_{self.uid}"
        self._seed_row_stored_with_the_utc_day(pid, stamp, with_payment_id=False, day=local_day(zone, stamp))
        out = self._import(_payment(pid, createdAt=stamp, value="25.00"), zone)
        self.assertEqual((out["imported"], out["duplicates_skipped"]), (0, 1))

    def test_control_a_different_amount_on_the_utc_day_is_not_a_duplicate(self):
        zone, stamp = EAST
        pid = f"tr_old_other_{self.uid}"
        self._seed_row_stored_with_the_utc_day(pid, stamp, with_payment_id=False)
        out = self._import(_payment(pid, createdAt=stamp, value="26.00"), zone)
        self.assertEqual((out["imported"], out["duplicates_skipped"]), (1, 0))


class TestBulkRunWindowLocalDay(_BulkImporterSweepBase):
    def _window(self, zone, stamp, day):
        payment = _mk_payment("tr_win", stamp, paid_at=stamp)
        pages = [_FakePage(batch=[payment])]
        with patch("verenigingen.verenigingen_payments.mollie.core.client.MollieClient") as mc, patch(
            "verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher.get_member_payment_matcher"
        ) as mm, system_timezone(zone):
            fake = MagicMock()
            fake.payments.list.side_effect = lambda **kw: pages[0]
            mc.return_value.sdk_client = fake
            mm.return_value.find_member_for_payment.return_value = None
            return [p["id"] for p in svc._list_mollie_payments(str(day), str(day))]

    def test_window_uses_the_local_day_of_paid_at(self):
        for zone, stamp in CASES:
            with self.subTest(zone=zone):
                self.assertEqual(self._window(zone, stamp, local_day(zone, stamp)), ["tr_win"])
                self.assertEqual(self._window(zone, stamp, utc_day(stamp)), [])


class TestAdminWindowLocalDay(_BulkImporterSweepBase):
    def test_cutoff_is_compared_with_the_local_day_of_created_at(self):
        from verenigingen.verenigingen_payments.mollie.services import bulk_payment_admin_service as admin

        zone = "Europe/Amsterdam"
        days_back = 5
        with system_timezone(zone):
            cutoff = getdate(add_days(today(), -days_back))
        # 00:30 local on the cutoff day: in window locally, the previous day in UTC.
        local_midnight = pytz.timezone(zone).localize(datetime(cutoff.year, cutoff.month, cutoff.day, 0, 30))
        stamp = local_midnight.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        self.assertLess(utc_day(stamp), cutoff)
        payment = SimpleNamespace(
            id="tr_admin_win",
            created_at=stamp,
            paid_at=stamp,
            status="paid",
            amount={"currency": "EUR", "value": "10.00"},
        )
        with patch("verenigingen.verenigingen_payments.mollie.core.client.MollieClient") as mc, patch(
            "verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher.get_member_payment_matcher"
        ), system_timezone(zone):
            page = _FakePage(batch=[payment])
            mc.return_value.sdk_client.payments.list.side_effect = lambda **kw: page
            out = admin._retrieve_global_payments_with_orphans(days_back, 10, "all")
        self.assertEqual(out["total_filtered_by_date"], 0, out.get("error"))
        self.assertEqual(out["total_payments_after_filtering"], 1)


class TestDebugServiceWindowLocalDay(_BulkImporterSweepBase):
    """The orphan-payments retrieval in MollieDebugService carries the same created_at window."""

    class _PastTheDateFilter(Exception):
        pass

    def _passes_date_filter(self, zone, stamp, start_day):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        payment = SimpleNamespace(id="tr_dbg", created_at=stamp, status="paid")
        matcher = MagicMock()
        matcher.find_member_for_payment.return_value = {"name": "M-1"}
        creator = MagicMock()
        creator.check_already_processed.side_effect = self._PastTheDateFilter()
        result = {"total_filtered_by_date": 0, "total_filtered_by_duplicate": 0, "total_filtered_by_member": 0}
        try:
            with system_timezone(zone):
                MollieDebugService()._process_retrieved_payment(
                    payment, matcher, creator, MagicMock(), set(), str(start_day), "all", 0, {}, result
                )
        except self._PastTheDateFilter:
            return True
        self.assertEqual(result["total_filtered_by_date"], 1)
        return False

    def test_created_at_is_compared_by_its_local_day(self):
        for zone, stamp in CASES:
            with self.subTest(zone=zone):
                self.assertTrue(self._passes_date_filter(zone, stamp, local_day(zone, stamp)))
                self.assertFalse(self._passes_date_filter(zone, stamp, add_days(local_day(zone, stamp), 1)))


SITE_ZONE_UNDER_LEVER = "Pacific/Kiritimati"  # what site_a_day_ahead_of_process pins


def _site_noon_stamp(day):
    """UTC stamp for 12:00 on ``day`` in the lever's site zone (day-stable at any hour)."""
    noon = pytz.timezone(SITE_ZONE_UNDER_LEVER).localize(datetime(day.year, day.month, day.day, 12, 0))
    return noon.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class TestCutoffIsTheSiteDayNotTheProcessDay(_BulkImporterSweepBase):
    """The cutoff `add_days(today(), -days_back)` is the SITE day.

    The lever puts the site strictly ahead of the process (process Pacific/Midway, site
    Pacific/Kiritimati), so site-today > process-today at every hour. A payment on the site's
    cutoff day is kept; one on the day before is dropped. A process-clock cutoff
    (`datetime.now()`) is a day or more earlier and would keep the older payment too.
    """

    days_back = 5

    def _kept_flags(self, site_today):
        on_cutoff = add_days(site_today, -self.days_back)
        before_cutoff = add_days(site_today, -self.days_back - 1)
        process_cutoff = getdate(add_days(datetime.now().date(), -self.days_back))
        # Control: the older payment is inside a process-clock window, so only a site-day
        # cutoff can drop it.
        self.assertGreaterEqual(getdate(before_cutoff), process_cutoff)
        return _site_noon_stamp(getdate(on_cutoff)), _site_noon_stamp(getdate(before_cutoff))

    def test_admin_cutoff_uses_the_site_day(self):
        from verenigingen.verenigingen_payments.mollie.services import bulk_payment_admin_service as admin

        with site_a_day_ahead_of_process() as site_today:
            on_stamp, before_stamp = self._kept_flags(site_today)
            payments = [
                SimpleNamespace(
                    id=pid,
                    created_at=stamp,
                    paid_at=stamp,
                    status="paid",
                    amount={"currency": "EUR", "value": "10.00"},
                )
                for pid, stamp in (("tr_on", on_stamp), ("tr_before", before_stamp))
            ]
            page = _FakePage(batch=payments)
            with patch("verenigingen.verenigingen_payments.mollie.core.client.MollieClient") as mc, patch(
                "verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher.get_member_payment_matcher"
            ):
                mc.return_value.sdk_client.payments.list.side_effect = lambda **kw: page
                out = admin._retrieve_global_payments_with_orphans(self.days_back, 10, "all")
        self.assertEqual(out["total_filtered_by_date"], 1, out.get("error"))
        self.assertEqual(out["total_payments_after_filtering"], 1)

    def test_debug_service_cutoff_uses_the_site_day(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        with site_a_day_ahead_of_process() as site_today:
            on_stamp, before_stamp = self._kept_flags(site_today)
            payments = [
                SimpleNamespace(id=pid, created_at=stamp, status="paid")
                for pid, stamp in (("tr_before", before_stamp), ("tr_on", on_stamp))
            ]
            matcher = MagicMock()
            matcher.find_member_for_payment.return_value = {"name": "M-1"}
            creator = MagicMock()
            # A payment past the date filter reaches this and the run aborts (the failure is
            # swallowed by the service); the call count says which payments got that far.
            creator.check_already_processed.side_effect = RuntimeError("past the date filter")
            service = MollieDebugService.__new__(MollieDebugService)
            service.logger = MagicMock()
            service.mollie_client = MagicMock()
            service.mollie_client.is_test_mode.return_value = True
            service.mollie_client.sdk_client.payments.list.side_effect = lambda **kw: payments
            with patch(
                "verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher.get_member_payment_matcher",
                return_value=matcher,
            ), patch(
                "verenigingen.verenigingen_payments.services.bank_transaction_creator.get_bank_transaction_creator",
                return_value=creator,
            ):
                out = service.bulk_retrieve_all_member_payments(days_back=self.days_back)
        # tr_before is dropped, then tr_on is kept and reaches the creator: both were seen.
        self.assertEqual(out["total_payments_found"], 2, out)
        self.assertEqual(out["total_filtered_by_date"], 1, out)
        self.assertEqual(creator.check_already_processed.call_count, 1)


class TestBalanceMonitorDailyBuckets(_BulkImporterSweepBase):
    def _avg_daily_change(self, zone, stamps):
        monitor = BalanceMonitor.__new__(BalanceMonitor)
        monitor.config = {"thresholds": {"critical_balance_eur": 100, "low_balance_eur": 1000}}
        amount = SimpleNamespace(decimal_value="10.00", currency="EUR")
        txs = [SimpleNamespace(created_at=s, result_amount=amount) for s in stamps]
        monitor.balances_client = SimpleNamespace(list_balance_transactions=lambda *a, **kw: txs)
        balance = SimpleNamespace(id="bal_1", currency="EUR", available_amount=amount)
        with system_timezone(zone):
            out = monitor._run_predictive_analysis([balance])
        self.assertNotIn("error", out)
        return out["predictions"][0]["avg_daily_change"]

    def test_two_events_on_one_local_day_form_one_bucket(self):
        # 23:00Z on the 3rd and 05:00Z on the 4th are both the 4th in Amsterdam.
        self.assertEqual(
            self._avg_daily_change("Europe/Amsterdam", ["2026-03-03T23:00:00Z", "2026-03-04T05:00:00Z"]),
            20.0,
        )

    def test_two_events_on_one_utc_day_split_when_the_local_days_differ(self):
        # 09:00Z and 12:00Z on the 3rd are the 2nd and the 3rd in Honolulu (UTC-10).
        self.assertEqual(
            self._avg_daily_change("Pacific/Honolulu", ["2026-03-03T09:00:00Z", "2026-03-03T12:00:00Z"]),
            10.0,
        )
