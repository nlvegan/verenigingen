"""
Reconciliation and revenue math tests for the Mollie FinancialDashboard.

Scope
-----
``verenigingen/verenigingen_payments/dashboards/financial_dashboard.py`` is the
live consumer of ``ReconciliationEngine`` and backs the ``/financial_dashboard``
portal page and the Mollie Balance report. These tests exercise the numbers it
puts in front of a treasurer:

* the payment reconciliation rate (which statuses count as reconciled),
* revenue aggregation from payments and from settlement periods,
* settlement metrics (totals, averages, period attribution),
* the cost rate and net income arithmetic of the financial report.

Mocking policy
--------------
Only the Mollie API clients are replaced - they are the external HTTP boundary.
Payment/settlement payloads are the raw dicts the real clients hand back, so the
dashboard's own parsing, filtering and Decimal arithmetic all run for real. Two
tests deliberately use a *real* ``BalancesClient`` instance to show what happens
against the actual client API surface.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

from verenigingen.tests.payment.test_mollie_reconciliation_engine import setup_mollie_backend_api
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.models.settlement import Settlement
from verenigingen.verenigingen_payments.dashboards.financial_dashboard import FinancialDashboard


def payment(payment_id, status, value, created_at, currency="EUR"):
    """Raw Mollie Payments API item, as PaymentsClient.get() returns it."""
    return {
        "resource": "payment",
        "id": payment_id,
        "status": status,
        "amount": {"currency": currency, "value": value},
        "createdAt": created_at.isoformat().replace("+00:00", "Z"),
    }


def settlement_json(
    settlement_id,
    amount,
    status="paidout",
    created_at=None,
    settled_at=None,
    period_key=None,
    revenue_net=None,
    costs_net=None,
):
    """Raw Mollie Settlements API item, as SettlementsClient.get() returns it."""
    data = {
        "resource": "settlement",
        "id": settlement_id,
        "reference": f"REF-{settlement_id}",
        "status": status,
        "amount": {"currency": "EUR", "value": amount},
    }
    if created_at:
        data["createdAt"] = created_at.isoformat().replace("+00:00", "Z")
    if settled_at:
        data["settledAt"] = settled_at.isoformat().replace("+00:00", "Z")
    if period_key:
        period = {"revenue": [], "costs": []}
        if revenue_net is not None:
            period["revenue"].append(
                {"description": "iDEAL", "amountNet": {"currency": "EUR", "value": revenue_net}}
            )
        if costs_net is not None:
            period["costs"].append(
                {"description": "Transaction fees", "amountNet": {"currency": "EUR", "value": costs_net}}
            )
        data["periods"] = {period_key: period}
    return data


class FinancialDashboardTestBase(VereningingenTestCase):
    """Dashboard with inert Mollie clients and pre-seeded response caches."""

    def setUp(self):
        super().setUp()
        setup_mollie_backend_api(self)

        self.dashboard = FinancialDashboard()
        self.dashboard.balances_client = Mock()
        self.dashboard.settlements_client = Mock()
        self.dashboard.invoices_client = Mock()
        self.dashboard.chargebacks_client = Mock()
        self.dashboard.payments_client = Mock()

        self.dashboard.settlements_client.get.return_value = []
        self.dashboard.settlements_client.get_next_settlement.return_value = None
        self.dashboard.settlements_client.get_open_settlement.return_value = None
        self.dashboard.payments_client.get.return_value = []

        self.now = datetime.now(timezone.utc)

    def given_payments(self, payments):
        self.dashboard._payments_cache = payments

    def given_settlements(self, settlements):
        self.dashboard._settlements_cache = settlements


class TestPaymentReconciliationRate(FinancialDashboardTestBase):
    """``_get_reconciliation_status`` is the "% reconciled" figure on the portal
    page. It must count only money that actually arrived."""

    def test_only_paid_and_authorized_payments_count_as_reconciled(self):
        self.given_payments(
            [
                payment("tr_1", "paid", "10.00", self.now - timedelta(days=1)),
                payment("tr_2", "authorized", "10.00", self.now - timedelta(days=2)),
                payment("tr_3", "pending", "10.00", self.now - timedelta(days=3)),
                payment("tr_4", "failed", "10.00", self.now - timedelta(days=4)),
                payment("tr_5", "expired", "10.00", self.now - timedelta(days=5)),
                payment("tr_6", "canceled", "10.00", self.now - timedelta(days=6)),
            ]
        )

        status = self.dashboard._get_reconciliation_status()

        self.assertEqual(status["total_payments"], 6)
        self.assertEqual(status["reconciled_payments"], 2)
        self.assertEqual(status["success_rate_30d"], 33.3)

    def test_rate_is_rounded_to_one_decimal_not_truncated(self):
        self.given_payments(
            [payment(f"tr_{i}", "paid", "1.00", self.now - timedelta(days=1)) for i in range(2)]
            + [payment("tr_x", "failed", "1.00", self.now - timedelta(days=1))]
        )

        status = self.dashboard._get_reconciliation_status()

        self.assertEqual(status["success_rate_30d"], 66.7)

    def test_payments_older_than_thirty_days_are_excluded_from_both_sides(self):
        """A payment that failed 60 days ago must not keep dragging today's
        reconciliation rate down, and an old success must not prop it up."""
        self.given_payments(
            [
                payment("tr_recent_ok", "paid", "10.00", self.now - timedelta(days=5)),
                payment("tr_old_ok", "paid", "10.00", self.now - timedelta(days=60)),
                payment("tr_old_bad", "failed", "10.00", self.now - timedelta(days=90)),
            ]
        )

        status = self.dashboard._get_reconciliation_status()

        self.assertEqual(status["total_payments"], 1)
        self.assertEqual(status["reconciled_payments"], 1)
        self.assertEqual(status["success_rate_30d"], 100)

    def test_no_payments_reports_a_neutral_hundred_percent_with_a_zero_denominator(self):
        """100% with total 0 is deliberate ("nothing to reconcile"). The zero
        denominator is what stops it being read as a real success rate."""
        self.given_payments([])

        status = self.dashboard._get_reconciliation_status()

        self.assertEqual(status["success_rate_30d"], 100)
        self.assertEqual(status["total_payments"], 0)
        self.assertEqual(status["reconciled_payments"], 0)

    def test_unavailable_payments_client_reports_zero_percent_not_a_fake_hundred(self):
        """When the client failed to construct, the dashboard must not claim a
        clean reconciliation - it has no data at all."""
        self.dashboard.payments_client = None

        status = self.dashboard._get_reconciliation_status()

        self.assertEqual(status["success_rate_30d"], 0)
        self.assertEqual(status["total_payments"], 0)
        self.assertIn("PaymentsClient not available", status["error"])


class TestRevenueFromPayments(FinancialDashboardTestBase):
    """``_calculate_revenue_from_payments`` converts raw payments into a revenue
    figure. Currency and status filtering here decide whether the number is real."""

    def _range(self, days=30):
        return self.now - timedelta(days=days), self.now

    def test_foreign_currency_payments_are_excluded_rather_than_added_at_one_to_one(self):
        """A USD payment added straight into a EUR total is a silent FX error."""
        self.given_payments([])
        start, end = self._range()
        payments = [
            payment("tr_eur", "paid", "100.00", self.now - timedelta(days=1)),
            payment("tr_usd", "paid", "999.00", self.now - timedelta(days=1), currency="USD"),
        ]

        revenue = self.dashboard._calculate_revenue_from_payments(payments, start, end)

        self.assertEqual(revenue, Decimal("100.00"))

    def test_pending_and_authorized_money_is_included_in_revenue(self):
        """Deliberate: the dashboard reports money committed, not only captured.
        If this changes, the portal figure changes meaning."""
        start, end = self._range()
        payments = [
            payment("tr_paid", "paid", "10.00", self.now - timedelta(days=1)),
            payment("tr_pending", "pending", "20.00", self.now - timedelta(days=1)),
            payment("tr_auth", "authorized", "30.00", self.now - timedelta(days=1)),
        ]

        revenue = self.dashboard._calculate_revenue_from_payments(payments, start, end)

        self.assertEqual(revenue, Decimal("60.00"))

    def test_failed_expired_and_refunded_payments_are_excluded(self):
        start, end = self._range()
        payments = [
            payment("tr_ok", "paid", "10.00", self.now - timedelta(days=1)),
            payment("tr_failed", "failed", "500.00", self.now - timedelta(days=1)),
            payment("tr_expired", "expired", "500.00", self.now - timedelta(days=1)),
            payment("tr_canceled", "canceled", "500.00", self.now - timedelta(days=1)),
        ]

        revenue = self.dashboard._calculate_revenue_from_payments(payments, start, end)

        self.assertEqual(revenue, Decimal("10.00"))

    def test_revenue_accumulates_in_decimal_without_binary_float_drift(self):
        """0.10 + 0.20 + 0.30 is 0.6000000000000001 as floats."""
        start, end = self._range()
        payments = [
            payment("tr_1", "paid", "0.10", self.now - timedelta(days=1)),
            payment("tr_2", "paid", "0.20", self.now - timedelta(days=1)),
            payment("tr_3", "paid", "0.30", self.now - timedelta(days=1)),
        ]

        revenue = self.dashboard._calculate_revenue_from_payments(payments, start, end)

        self.assertEqual(revenue, Decimal("0.60"))

    def test_payments_outside_the_window_are_not_counted(self):
        start = self.now - timedelta(days=10)
        end = self.now - timedelta(days=5)
        payments = [
            payment("tr_before", "paid", "100.00", self.now - timedelta(days=11)),
            payment("tr_inside", "paid", "7.00", self.now - timedelta(days=7)),
            payment("tr_after", "paid", "100.00", self.now - timedelta(days=1)),
        ]

        revenue = self.dashboard._calculate_revenue_from_payments(payments, start, end)

        self.assertEqual(revenue, Decimal("7.00"))


class TestSettlementPeriodRevenue(FinancialDashboardTestBase):
    """``_calculate_revenue_by_settlement_periods`` is meant to prefer Mollie's
    own settled net revenue over summing raw payments."""

    MARCH_START = datetime(2025, 3, 1, tzinfo=timezone.utc)
    MARCH_END = datetime(2025, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

    def _march_settlement(self, revenue_net="500.00"):
        return settlement_json(
            "stl_march",
            "500.00",
            settled_at=datetime(2025, 4, 3, tzinfo=timezone.utc),
            created_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
            period_key="2025-03",
            revenue_net=revenue_net,
        )

    def test_settled_revenue_from_raw_api_dicts_is_never_counted(self):
        """DOCUMENTS A PRODUCTION BUG (financial_dashboard.py:150).

        ``_get_settlements_data()`` returns raw API *dicts* (``settlements_client
        .get(...)``), but this method probes them with
        ``hasattr(settlement, "settled_at_datetime")`` - an attribute only the
        parsed ``Settlement`` model has. The condition is therefore always False,
        the entire settled-revenue branch is dead, and every reported figure falls
        through to the raw-payments fallback. Consequence: the dashboard reports
        gross payment volume (including pending/authorized) instead of Mollie's
        settled net revenue.

        The companion test below feeds identical data as ``Settlement`` objects
        and shows the branch works - so this is a type mismatch, not dead intent.
        """
        self.given_settlements([self._march_settlement()])
        self.given_payments([payment("tr_1", "paid", "12.00", datetime(2025, 3, 10, tzinfo=timezone.utc))])

        revenue = self.dashboard._calculate_revenue_by_settlement_periods(self.MARCH_START, self.MARCH_END)

        # Only the raw payment - the €500.00 of settled net revenue is ignored.
        self.assertEqual(revenue, Decimal("12.00"))

    def test_settled_revenue_is_counted_when_settlements_are_parsed_models(self):
        self.given_settlements([Settlement(self._march_settlement())])
        self.given_payments([payment("tr_1", "paid", "12.00", datetime(2025, 3, 10, tzinfo=timezone.utc))])

        revenue = self.dashboard._calculate_revenue_by_settlement_periods(self.MARCH_START, self.MARCH_END)

        # Fully covered period: settled net revenue only, no payment double-count.
        self.assertEqual(revenue, Decimal("500.00"))

    def test_partial_period_overlap_is_prorated_by_days(self):
        """Half a settled month must contribute roughly half its net revenue,
        otherwise a quarter boundary double-counts a month of income."""
        self.given_settlements([Settlement(self._march_settlement(revenue_net="310.00"))])
        self.given_payments([])

        revenue = self.dashboard._calculate_revenue_by_settlement_periods(
            self.MARCH_START, datetime(2025, 3, 15, 12, 0, tzinfo=timezone.utc)
        )

        # March period spans 31 days; the overlap covers 15 of them.
        self.assertEqual(revenue, Decimal("310.00") * Decimal(15) / Decimal(31))

    def test_uncovered_days_fall_back_to_individual_payments(self):
        """A settled February plus an unsettled March must add up, not overwrite."""
        february = settlement_json(
            "stl_feb",
            "100.00",
            settled_at=datetime(2025, 3, 3, tzinfo=timezone.utc),
            period_key="2025-02",
            revenue_net="100.00",
        )
        self.given_settlements([Settlement(february)])
        self.given_payments(
            [
                payment("tr_march", "paid", "40.00", datetime(2025, 3, 10, tzinfo=timezone.utc)),
                payment("tr_feb", "paid", "999.00", datetime(2025, 2, 10, tzinfo=timezone.utc)),
            ]
        )

        revenue = self.dashboard._calculate_revenue_by_settlement_periods(
            datetime(2025, 2, 1, tzinfo=timezone.utc), self.MARCH_END
        )

        # February from the settlement, March from payments - the already-settled
        # February payment must not be counted twice.
        self.assertEqual(revenue, Decimal("140.00"))


class TestSettlementMetrics(FinancialDashboardTestBase):
    """Settlement totals and averages shown on the dashboard."""

    def test_current_month_total_and_average_are_exact(self):
        # The production boundary is ``now.replace(day=1)`` - see the following
        # test - so anchor the fixtures just after it to stay month-independent.
        month_boundary = self.now.replace(day=1)
        self.given_settlements(
            [
                settlement_json("stl_1", "100.00", settled_at=month_boundary + timedelta(minutes=1)),
                settlement_json("stl_2", "50.50", settled_at=month_boundary + timedelta(minutes=2)),
            ]
        )

        metrics = self.dashboard._get_settlement_metrics()

        self.assertNotIn("error", metrics)
        self.assertEqual(metrics["current_month"]["count"], 2)
        self.assertEqual(metrics["current_month"]["total_amount"], 150.50)
        self.assertEqual(metrics["current_month"]["average_amount"], 75.25)
        self.assertEqual(metrics["current_month"]["by_status"], {"paidout": 2})

    def test_settlement_early_on_the_first_of_the_month_is_dropped_from_current_month(self):
        """DOCUMENTS A PRODUCTION BUG (financial_dashboard.py:367).

        The current-month test is ``settlement_date >= now.replace(day=1)``.
        ``replace(day=1)`` keeps the current *time of day*, so the boundary is
        "the 1st at 14:37" rather than "the 1st at 00:00". Every settlement paid
        out earlier in the day on the 1st is silently excluded from the month's
        totals - and it is not counted anywhere else either, so the money simply
        vanishes from the monthly figures. The fix is
        ``now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)``.
        """
        if self.now.hour == 0 and self.now.minute < 5:
            self.skipTest("boundary bug is not observable in the first minutes of a day")

        midnight_on_the_first = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        self.given_settlements([settlement_json("stl_first", "42.00", settled_at=midnight_on_the_first)])

        metrics = self.dashboard._get_settlement_metrics()

        self.assertEqual(metrics["current_month"]["count"], 0)
        self.assertEqual(metrics["current_month"]["total_amount"], 0.0)

    def test_settlements_are_attributed_by_settled_date_not_created_date(self):
        """A settlement created last quarter but paid out today belongs to this
        month's cash figures."""
        self.given_settlements(
            [
                settlement_json(
                    "stl_late",
                    "80.00",
                    created_at=self.now - timedelta(days=120),
                    settled_at=self.now - timedelta(days=1),
                )
            ]
        )

        metrics = self.dashboard._get_settlement_metrics()

        self.assertEqual(metrics["last_30_days"]["count"], 1)
        self.assertEqual(metrics["last_30_days"]["total_amount"], 80.00)
        self.assertEqual(
            metrics["recent_settlements"][0]["date"], (self.now - timedelta(days=1)).strftime("%Y-%m-%d")
        )

    def test_settlement_without_settled_date_falls_back_to_created_date(self):
        self.given_settlements(
            [settlement_json("stl_open", "25.00", status="open", created_at=self.now - timedelta(days=2))]
        )

        metrics = self.dashboard._get_settlement_metrics()

        self.assertEqual(metrics["last_30_days"]["count"], 1)
        self.assertEqual(metrics["recent_settlements"][0]["status"], "open")

    def test_settlement_with_no_usable_date_is_skipped_not_counted_as_zero(self):
        self.given_settlements(
            [
                settlement_json("stl_dateless", "500.00"),
                settlement_json("stl_dated", "10.00", settled_at=self.now - timedelta(days=1)),
            ]
        )

        metrics = self.dashboard._get_settlement_metrics()

        self.assertEqual(metrics["last_30_days"]["count"], 1)
        self.assertEqual(metrics["last_30_days"]["total_amount"], 10.00)

    def test_older_settlements_are_excluded_from_the_thirty_day_window(self):
        self.given_settlements(
            [
                settlement_json("stl_old", "900.00", settled_at=self.now - timedelta(days=45)),
                settlement_json("stl_new", "10.00", settled_at=self.now - timedelta(days=2)),
            ]
        )

        metrics = self.dashboard._get_settlement_metrics()

        self.assertEqual(metrics["last_30_days"]["count"], 1)
        self.assertEqual(metrics["last_30_days"]["total_amount"], 10.00)

    def test_recent_settlements_list_is_capped_at_five_entries(self):
        self.given_settlements(
            [
                settlement_json(f"stl_{i}", "10.00", settled_at=self.now - timedelta(days=i + 1))
                for i in range(8)
            ]
        )

        metrics = self.dashboard._get_settlement_metrics()

        self.assertEqual(len(metrics["recent_settlements"]), 5)
        self.assertEqual(metrics["last_30_days"]["count"], 8)


class TestFinancialReport(FinancialDashboardTestBase):
    """``get_financial_report`` is the period report behind the Mollie Balance
    report and the dashboard's export."""

    def test_net_income_is_settled_revenue_minus_settled_costs(self):
        self.given_settlements(
            [
                settlement_json(
                    "stl_1", "90.00", period_key="2025-03", revenue_net="100.00", costs_net="10.00"
                ),
                settlement_json(
                    "stl_2", "45.00", period_key="2025-04", revenue_net="50.00", costs_net="5.00"
                ),
            ]
        )

        report = self.dashboard.get_financial_report("month")

        self.assertNotIn("error", report)
        self.assertEqual(report["summary"]["settlement_count"], 2)
        self.assertEqual(report["summary"]["total_revenue"], 150.00)
        self.assertEqual(report["summary"]["total_costs"], 15.00)
        self.assertEqual(report["summary"]["net_income"], 135.00)

    def test_report_totals_ignore_the_requested_period(self):
        """DOCUMENTS A PRODUCTION BUG (financial_dashboard.py:771).

        The report declares a ``period.start``/``period.end`` and then sums
        *every* cached settlement without filtering by that range. A "week" report
        and a "year" report therefore return byte-identical totals, including
        settlements from years outside the stated period. Anyone reading the
        report as a periodic statement is reading lifetime totals.
        """
        self.given_settlements(
            [
                settlement_json(
                    "stl_ancient",
                    "1000.00",
                    settled_at=datetime(2019, 1, 5, tzinfo=timezone.utc),
                    period_key="2018-12",
                    revenue_net="1000.00",
                    costs_net="20.00",
                )
            ]
        )

        week = self.dashboard.get_financial_report("week")
        year = self.dashboard.get_financial_report("year")

        self.assertNotEqual(week["period"]["start"], year["period"]["start"])
        self.assertEqual(week["summary"]["total_revenue"], 1000.00)
        self.assertEqual(week["summary"], year["summary"])

    def test_unknown_period_escapes_the_reports_error_handling(self):
        """``get_period_date_range`` is called *before* the try block, so an
        unrecognised period propagates instead of returning the report's usual
        ``{"error": ...}`` payload. ``period`` reaches this from the whitelisted
        ``get_financial_report`` endpoint, i.e. from user input, so the caller
        gets a raw 500 rather than a handled error."""
        with self.assertRaises(ValueError) as ctx:
            self.dashboard.get_financial_report("fortnight")

        self.assertIn("fortnight", str(ctx.exception))


class TestCostRate(FinancialDashboardTestBase):
    """The cost rate is fee spend as a percentage of revenue."""

    def test_cost_rate_is_costs_over_revenue_as_a_percentage(self):
        month_start = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_key = self.now.strftime("%Y-%m")
        self.given_settlements(
            [
                settlement_json(
                    "stl_1",
                    "950.00",
                    settled_at=month_start + timedelta(hours=1),
                    period_key=period_key,
                    revenue_net="1000.00",
                    costs_net="25.00",
                )
            ]
        )
        # Revenue comes from the payments fallback (see the settlement-period bug).
        self.given_payments([payment("tr_1", "paid", "1000.00", month_start + timedelta(hours=2))])

        breakdown = self.dashboard._get_cost_breakdown()

        self.assertNotIn("error", breakdown)
        self.assertEqual(breakdown["current_month"]["total_costs"], 25.00)
        self.assertEqual(breakdown["cost_rate"], 2.5)

    def test_zero_revenue_leaves_the_cost_rate_at_zero_instead_of_dividing_by_zero(self):
        self.given_settlements([settlement_json("stl_1", "0.00", period_key="2025-03", costs_net="12.00")])
        self.given_payments([])

        breakdown = self.dashboard._get_cost_breakdown()

        self.assertNotIn("error", breakdown)
        self.assertEqual(breakdown["current_month"]["total_costs"], 12.00)
        self.assertEqual(breakdown["cost_rate"], 0)


class TestBalancesClientContract(VereningingenTestCase):
    """Both the engine and the dashboard call BalancesClient methods that do not
    exist on the class. These tests use a real client instance - the only mock is
    the one HTTP-backed call that would otherwise reach Mollie."""

    def setUp(self):
        super().setUp()
        setup_mollie_backend_api(self)

    def _real_balances_client(self):
        from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient
        from verenigingen.verenigingen_payments.core.models.balance import Balance

        client = BalancesClient()
        client.list_balances = lambda **kwargs: [
            Balance(
                {
                    "resource": "balance",
                    "id": "bal_real",
                    "currency": "EUR",
                    "status": "active",
                    "availableAmount": {"currency": "EUR", "value": "1000.00"},
                    "pendingAmount": {"currency": "EUR", "value": "0.00"},
                }
            )
        ]
        return client

    def test_engine_balance_reconciliation_fails_against_the_real_client(self):
        """DOCUMENTS A PRODUCTION BUG (reconciliation_engine.py:166 and :192).

        ``_reconcile_balances`` calls ``balances_client.reconcile_balance(id)``
        and ``balances_client.check_balance_health()``. Neither exists on
        ``BalancesClient`` - the real method is
        ``reconcile_balance_transactions(balance_id, start_date, end_date)``, and
        there is no health check at all. So with any balance present the component
        raises AttributeError on the first iteration, no balance is ever
        reconciled, and the daily run reports FAILED every single day.
        """
        from verenigingen.verenigingen_payments.workflows.reconciliation_engine import ReconciliationEngine

        engine = ReconciliationEngine()
        engine.balances_client = self._real_balances_client()

        result = engine._reconcile_balances()

        self.assertEqual(result["status"], "failed")
        self.assertIn("reconcile_balance", result["error"])
        self.assertEqual(result["balances"], [])
        self.assertEqual(len(engine.errors), 1)
        self.assertIn("Balance reconciliation error", engine.errors[0])

    def test_dashboard_alerts_are_swallowed_by_the_same_missing_health_check(self):
        """DOCUMENTS A PRODUCTION BUG (financial_dashboard.py:682).

        ``_get_active_alerts`` calls the same non-existent
        ``check_balance_health()`` as its *first* step, inside one broad
        try/except that wraps every other check. The AttributeError therefore
        collapses the whole alerts panel into a single generic "system" alert -
        overdue invoices and chargeback risk are never evaluated, no matter how
        bad they are.
        """
        from verenigingen.verenigingen_payments.core.models.invoice import Invoice

        dashboard = FinancialDashboard()
        dashboard.balances_client = self._real_balances_client()
        dashboard.invoices_client = Mock()
        dashboard.invoices_client.get_overdue_invoices.return_value = [
            Invoice({"resource": "invoice", "id": "inv_late", "reference": "2024.1", "status": "overdue"})
        ]
        dashboard.chargebacks_client = Mock()
        dashboard.chargebacks_client.get_chargeback_prevention_insights.return_value = {"risk_level": "high"}

        alerts = dashboard._get_active_alerts()

        self.assertEqual([a["type"] for a in alerts], ["system"])
        self.assertIn("check_balance_health", alerts[0]["message"])
        # The overdue invoice and the high chargeback risk never reach the user.
        dashboard.invoices_client.get_overdue_invoices.assert_not_called()
