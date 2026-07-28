"""
Reconciliation math tests for the Mollie ReconciliationEngine.

Scope
-----
``verenigingen/verenigingen_payments/workflows/reconciliation_engine.py`` is the
engine behind the daily Mollie reconciliation run and is consumed live by
``FinancialDashboard``. These tests exercise the money-handling decisions the
engine makes:

* which settlement discrepancies are silently "corrected" versus escalated,
* the exact EUR/non-EUR aggregation rules for balances,
* how errors versus warnings map onto the run's overall status,
* the persistence contract of the reconciliation log, and
* the bulk-import consistency checks (skip ratio, success rate).

Mocking policy
--------------
Only the four Mollie API *clients* are replaced - they are the external HTTP
boundary. Every arithmetic decision, threshold comparison, status derivation and
database write below runs the real production code. The client stand-ins return
real ``Balance`` / ``Settlement`` / ``Invoice`` model objects built from Mollie's
documented JSON shape, so the model layer runs for real too.
"""

import json
import unittest
from decimal import Decimal
from unittest.mock import Mock

import frappe
from frappe.utils import add_days, getdate

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.models.balance import Balance
from verenigingen.verenigingen_payments.core.models.invoice import Invoice
from verenigingen.verenigingen_payments.core.models.settlement import Settlement
from verenigingen.verenigingen_payments.workflows.reconciliation_engine import (
    ReconciliationEngine,
    ReconciliationStatus,
)


def setup_mollie_backend_api():
    """Enable the Mollie backend API so the API clients will construct.

    ``BalancesClient`` & friends refuse to build unless ``enable_backend_api`` is
    set and an organization access token is present. The token is a dummy: every
    client is replaced with a stand-in before any request could be made.
    """
    settings = frappe.get_single("Mollie Settings")
    settings.enable_backend_api = 1
    settings.organization_access_token = "test_dummy_org_token"
    settings.flags.ignore_mandatory = True
    settings.flags.ignore_validate = True
    settings.save(ignore_permissions=True)

    from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

    get_mollie_config().clear_cache()


def build_balance(currency="EUR", available="0.00", pending="0.00", balance_id="bal_test"):
    """Build a real Balance model from Mollie's documented JSON shape."""
    return Balance(
        {
            "resource": "balance",
            "id": balance_id,
            "currency": currency,
            "status": "active",
            "availableAmount": {"currency": currency, "value": available},
            "pendingAmount": {"currency": currency, "value": pending},
        }
    )


def build_settlement(settlement_id="stl_test", reference="1234567.2504.03", status="paidout"):
    """Build a real Settlement model from Mollie's documented JSON shape."""
    return Settlement(
        {
            "resource": "settlement",
            "id": settlement_id,
            "reference": reference,
            "status": status,
            "amount": {"currency": "EUR", "value": "100.00"},
        }
    )


def build_invoice(invoice_id="inv_test", reference="2024.10000", status="paid", gross="121.00"):
    """Build a real Invoice model from Mollie's documented JSON shape."""
    return Invoice(
        {
            "resource": "invoice",
            "id": invoice_id,
            "reference": reference,
            "status": status,
            "grossAmount": {"currency": "EUR", "value": gross},
        }
    )


def settlement_reconciliation(actual, calculated, settlement_id="stl_test"):
    """Build the reconciliation dict shape SettlementsClient.reconcile_settlement returns.

    ``discrepancy = actual - calculated`` and ``reconciled`` uses the client's own
    one-cent tolerance, so the fixture cannot drift from the real contract.
    """
    actual = Decimal(str(actual))
    calculated = Decimal(str(calculated))
    discrepancy = actual - calculated
    return {
        "settlement_id": settlement_id,
        "components": {
            "payments": {"count": 3, "total": float(calculated)},
            "refunds": {"count": 0, "total": 0.0},
            "chargebacks": {"count": 0, "total": 0.0},
            "captures": {"count": 0, "total": 0.0},
        },
        "calculated_total": float(calculated),
        "actual_amount": float(actual),
        "discrepancy": float(discrepancy),
        "reconciled": abs(discrepancy) < Decimal("0.01"),
    }


class ReconciliationEngineTestBase(VereningingenTestCase):
    """Builds an engine whose four Mollie clients are inert stand-ins."""

    def setUp(self):
        super().setUp()
        setup_mollie_backend_api()

        self.engine = ReconciliationEngine()

        # Replace the external HTTP boundary only. Defaults are "nothing to do"
        # so each test opts into exactly the data it reasons about.
        self.engine.balances_client = Mock()
        self.engine.settlements_client = Mock()
        self.engine.invoices_client = Mock()
        self.engine.chargebacks_client = Mock()

        self.engine.balances_client.list_balances.return_value = []
        self.engine.balances_client.check_balance_health.return_value = {"status": "healthy", "issues": []}
        self.engine.settlements_client.list_settlements.return_value = []
        self.engine.invoices_client.list_invoices.return_value = []
        self.engine.invoices_client.calculate_vat_summary.return_value = {"total_vat": 0}
        self.engine.chargebacks_client.list_all_chargebacks.return_value = []
        self.engine.chargebacks_client.calculate_financial_impact.return_value = {"net_loss": 0}
        self.engine.chargebacks_client.analyze_chargeback_trends.return_value = {}

        # The engine writes an Error Log on every run because it cannot persist
        # its own log record (see test_engine_status_values_are_valid_log_options).
        self.expectErrorLog("Reconciliation Engine")

    def given_settlements(self, *pairs):
        """Register settlements as (settlement_id, actual_amount, calculated_total)."""
        settlements = [build_settlement(settlement_id=sid) for sid, _, _ in pairs]
        reconciliations = {
            sid: settlement_reconciliation(actual, calculated, sid) for sid, actual, calculated in pairs
        }
        self.engine.settlements_client.list_settlements.return_value = settlements
        self.engine.settlements_client.reconcile_settlement.side_effect = lambda sid: reconciliations[sid]


class TestSettlementDiscrepancyHandling(ReconciliationEngineTestBase):
    """The €10 auto-correction threshold decides whether a money difference is
    silently queued for adjustment or escalated to a human. Getting this boundary
    wrong either buries real losses or floods operators with noise."""

    def test_small_discrepancy_is_queued_for_correction_and_not_warned(self):
        self.given_settlements(("stl_small", "104.75", "100.00"))

        result = self.engine._reconcile_settlements()

        self.assertEqual(
            self.engine.corrections,
            [{"type": "settlement_adjustment", "settlement_id": "stl_small", "amount": 4.75}],
        )
        self.assertEqual(self.engine.warnings, [])
        self.assertEqual(len(result["discrepancies"]), 1)
        self.assertEqual(result["discrepancies"][0]["settlement_id"], "stl_small")
        self.assertAlmostEqual(result["discrepancies"][0]["amount"], 4.75, places=2)
        # The component breakdown must travel with the discrepancy - it is the
        # only trail an operator has for locating the missing money.
        self.assertEqual(result["discrepancies"][0]["components"]["payments"]["total"], 100.00)

    def test_discrepancy_at_ten_euro_boundary_escalates_instead_of_auto_correcting(self):
        """9.99 auto-corrects, 10.00 must not: the threshold is strict ``< 10``."""
        self.given_settlements(
            ("stl_under", "109.99", "100.00"),
            ("stl_at_limit", "110.00", "100.00"),
        )

        self.engine._reconcile_settlements()

        corrected_ids = [c["settlement_id"] for c in self.engine.corrections]
        self.assertEqual(corrected_ids, ["stl_under"])
        self.assertEqual(len(self.engine.warnings), 1)
        self.assertIn("stl_at_limit", self.engine.warnings[0])
        self.assertNotIn("stl_under", self.engine.warnings[0])

    def test_negative_discrepancy_uses_absolute_threshold_and_keeps_its_sign(self):
        """A shortfall (Mollie settled less than the components add up to) is the
        dangerous direction. It must be measured on absolute value but recorded
        signed, or an adjustment would be booked the wrong way round."""
        self.given_settlements(
            ("stl_short_small", "91.00", "100.00"),
            ("stl_short_large", "75.00", "100.00"),
        )

        self.engine._reconcile_settlements()

        self.assertEqual(len(self.engine.corrections), 1)
        self.assertEqual(self.engine.corrections[0]["settlement_id"], "stl_short_small")
        self.assertAlmostEqual(self.engine.corrections[0]["amount"], -9.00, places=2)
        self.assertEqual(len(self.engine.warnings), 1)
        self.assertIn("stl_short_large", self.engine.warnings[0])

    def test_reconciled_settlement_produces_no_discrepancy_or_correction(self):
        self.given_settlements(("stl_clean", "250.00", "250.00"))

        result = self.engine._reconcile_settlements()

        self.assertEqual(result["discrepancies"], [])
        self.assertEqual(self.engine.corrections, [])
        self.assertEqual(self.engine.warnings, [])
        self.assertTrue(result["settlements"][0]["reconciled"])

    def test_settlement_total_sums_actual_settled_amounts_not_calculated_totals(self):
        """The run's headline total must be what Mollie actually paid out. Summing
        ``calculated_total`` instead would hide precisely the money that went
        missing."""
        self.given_settlements(
            ("stl_a", "100.00", "90.00"),
            ("stl_b", "200.00", "500.00"),
        )

        result = self.engine._reconcile_settlements()

        self.assertEqual(result["total_amount"], Decimal("300.00"))
        self.assertEqual([s["amount"] for s in result["settlements"]], [100.00, 200.00])

    def test_settlement_total_accumulates_without_binary_float_drift(self):
        """0.1 + 0.2 + 0.3 is 0.6000000000000001 in binary floating point. The
        engine accumulates through Decimal; this test fails the moment someone
        "simplifies" that to a float sum."""
        self.given_settlements(
            ("stl_1", "0.10", "0.10"),
            ("stl_2", "0.20", "0.20"),
            ("stl_3", "0.30", "0.30"),
        )

        result = self.engine._reconcile_settlements()

        self.assertEqual(result["total_amount"], Decimal("0.60"))

    def test_settlement_client_failure_is_recorded_as_error_not_silently_zeroed(self):
        self.engine.settlements_client.list_settlements.side_effect = Exception("502 Bad Gateway")

        result = self.engine._reconcile_settlements()

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["settlements"], [])
        self.assertEqual(len(self.engine.errors), 1)
        self.assertIn("Settlement reconciliation error", self.engine.errors[0])
        self.assertIn("502 Bad Gateway", self.engine.errors[0])


class TestBalanceAggregation(ReconciliationEngineTestBase):
    """Balance totals are reported as EUR figures; anything that quietly folds a
    foreign-currency balance into them overstates the association's cash."""

    def _given_balances(self, balances, reconciliations):
        self.engine.balances_client.list_balances.return_value = balances
        self.engine.balances_client.reconcile_balance.side_effect = lambda bid: reconciliations[bid]

    def test_only_eur_balances_are_added_to_the_eur_totals(self):
        self._given_balances(
            [
                build_balance("EUR", "1500.50", "200.25", "bal_eur"),
                build_balance("USD", "999.99", "111.11", "bal_usd"),
            ],
            {
                "bal_eur": {"reconciled": True, "discrepancy": 0},
                "bal_usd": {"reconciled": True, "discrepancy": 0},
            },
        )

        result = self.engine._reconcile_balances()

        self.assertEqual(result["total_available"], Decimal("1500.50"))
        self.assertEqual(result["total_pending"], Decimal("200.25"))
        # The USD balance is still reported individually - excluded from the
        # total, not dropped from the report.
        self.assertEqual([b["currency"] for b in result["balances"]], ["EUR", "USD"])
        self.assertEqual(result["balances"][1]["available"], 999.99)

    def test_multiple_eur_balances_accumulate_exactly(self):
        self._given_balances(
            [
                build_balance("EUR", "0.10", "0.00", "bal_1"),
                build_balance("EUR", "0.20", "0.00", "bal_2"),
            ],
            {
                "bal_1": {"reconciled": True, "discrepancy": 0},
                "bal_2": {"reconciled": True, "discrepancy": 0},
            },
        )

        result = self.engine._reconcile_balances()

        self.assertEqual(result["total_available"], Decimal("0.30"))

    def test_unreconciled_balance_reports_currency_and_absolute_discrepancy(self):
        self._given_balances(
            [build_balance("EUR", "1000.00", "0.00", "bal_eur")],
            {"bal_eur": {"reconciled": False, "discrepancy": -12.34}},
        )

        result = self.engine._reconcile_balances()

        self.assertEqual(len(result["issues"]), 1)
        issue = result["issues"][0]
        self.assertIn("EUR", issue)
        self.assertIn("12.34", issue)
        self.assertNotIn("-12.34", issue)
        # The issue is mirrored onto the run so it can drive the overall status.
        self.assertEqual(self.engine.warnings, [issue])
        self.assertEqual(result["balances"][0]["discrepancy"], -12.34)

    def test_missing_amount_objects_default_to_zero_rather_than_crashing(self):
        """Mollie omits ``pendingAmount`` on some balances. A None-deref here would
        abort the whole balance component."""
        balance = Balance({"resource": "balance", "id": "bal_bare", "currency": "EUR", "status": "active"})
        self._given_balances([balance], {"bal_bare": {"reconciled": True, "discrepancy": 0}})

        result = self.engine._reconcile_balances()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["balances"][0]["available"], 0)
        self.assertEqual(result["balances"][0]["pending"], 0)
        self.assertEqual(result["total_available"], Decimal("0"))

    def test_unhealthy_balance_health_issues_become_run_warnings(self):
        self._given_balances(
            [build_balance("EUR", "5.00", "0.00", "bal_eur")],
            {"bal_eur": {"reconciled": True, "discrepancy": 0}},
        )
        self.engine.balances_client.check_balance_health.return_value = {
            "status": "unhealthy",
            "issues": ["EUR balance below minimum threshold"],
        }

        result = self.engine._reconcile_balances()

        self.assertEqual(result["health_issues"], ["EUR balance below minimum threshold"])
        self.assertIn("EUR balance below minimum threshold", self.engine.warnings)


class TestRunStatusDerivation(ReconciliationEngineTestBase):
    """The run status is what an operator acts on. Errors must dominate warnings,
    and a clean run must never be reported as degraded (or vice versa)."""

    def test_clean_run_is_completed(self):
        results = self.engine.run_daily_reconciliation()

        self.assertEqual(results["status"], ReconciliationStatus.COMPLETED)
        self.assertEqual(results["errors"], [])
        self.assertEqual(results["warnings"], [])

    def test_overdue_invoice_alone_degrades_the_run_to_partial(self):
        self.engine.invoices_client.list_invoices.return_value = [
            build_invoice("inv_ok", "2024.10001", status="paid"),
            build_invoice("inv_late", "2024.10002", status="overdue", gross="242.00"),
        ]

        results = self.engine.run_daily_reconciliation()

        self.assertEqual(results["status"], ReconciliationStatus.PARTIAL)
        self.assertEqual(results["errors"], [])
        self.assertEqual(results["warnings"], ["Overdue invoice: 2024.10002"])

        invoices = results["components"]["invoices"]
        self.assertEqual([i["id"] for i in invoices["overdue"]], ["inv_late"])
        self.assertEqual(invoices["overdue"][0]["amount"], 242.00)
        self.assertFalse(invoices["invoices"][1]["is_paid"])

    def test_component_error_marks_the_run_failed_and_does_not_abort_other_components(self):
        self.engine.balances_client.list_balances.side_effect = Exception("Mollie 503")
        self.engine.invoices_client.list_invoices.return_value = [
            build_invoice("inv_late", "2024.10002", status="overdue")
        ]

        results = self.engine.run_daily_reconciliation()

        self.assertEqual(results["status"], ReconciliationStatus.FAILED)
        self.assertIn("Balance reconciliation error", results["errors"][0])
        # An error in one component must not stop the others from running -
        # otherwise one flaky endpoint blinds the whole reconciliation.
        self.assertEqual(results["components"]["balances"]["status"], "failed")
        self.assertEqual(results["components"]["invoices"]["status"], "success")
        self.assertEqual(len(results["components"]["invoices"]["overdue"]), 1)
        # Errors outrank warnings.
        self.assertTrue(results["warnings"])

    def test_each_run_gets_its_own_reconciliation_id_and_timing(self):
        first = self.engine.run_daily_reconciliation()
        second = self.engine.run_daily_reconciliation()

        self.assertNotEqual(first["reconciliation_id"], second["reconciliation_id"])
        self.assertGreaterEqual(second["duration_seconds"], 0)
        # State from the first run must not leak into the second.
        self.assertEqual(second["errors"], [])
        self.assertEqual(second["corrections"], [])

    def test_run_state_is_reset_between_runs(self):
        self.given_settlements(("stl_short_large", "50.00", "100.00"))
        first = self.engine.run_daily_reconciliation()
        self.assertEqual(first["status"], ReconciliationStatus.PARTIAL)

        # Second run over clean data must not inherit the first run's warning.
        self.engine.settlements_client.list_settlements.return_value = []
        second = self.engine.run_daily_reconciliation()

        self.assertEqual(second["status"], ReconciliationStatus.COMPLETED)
        self.assertEqual(second["warnings"], [])


class TestCorrectionApplication(ReconciliationEngineTestBase):
    """Corrections are the point where the engine claims to have *fixed* money."""

    def test_auto_correction_is_reported_applied_without_creating_any_ledger_entry(self):
        """DOCUMENTS A PRODUCTION BUG (reconciliation_engine.py:408).

        ``_create_adjustment_entry`` is an empty ``pass``. A settlement that is
        €4.75 short is therefore queued as a correction, reported back with
        ``status: applied``, produces no warning, and leaves the run status at
        COMPLETED - while no journal entry, and no accounting record of any kind,
        is ever created. The discrepancy simply disappears.

        This test pins that behaviour so the gap is visible and executable. When
        ``_create_adjustment_entry`` is implemented, this test must be rewritten
        to assert the resulting ledger entry.
        """
        self.given_settlements(("stl_short", "95.25", "100.00"))
        journal_entries_before = frappe.db.count("Journal Entry")

        results = self.engine.run_daily_reconciliation()

        self.assertEqual(
            results["corrections_applied"],
            [
                {
                    "type": "settlement_adjustment",
                    "id": "stl_short",
                    "amount": -4.75,
                    "status": "applied",
                }
            ],
        )
        self.assertEqual(frappe.db.count("Journal Entry"), journal_entries_before)
        # ...and the run reports itself fully successful despite the €4.75 gap.
        self.assertEqual(results["status"], ReconciliationStatus.COMPLETED)
        self.assertEqual(results["warnings"], [])

    def test_no_corrections_key_is_emitted_when_nothing_needed_correcting(self):
        results = self.engine.run_daily_reconciliation()

        self.assertNotIn("corrections_applied", results)
        self.assertEqual(results["corrections"], [])

    def test_failure_of_one_correction_does_not_drop_the_others(self):
        self.engine.corrections = [
            {"type": "settlement_adjustment", "settlement_id": "stl_a", "amount": 1.00},
            {"type": "settlement_adjustment", "settlement_id": "stl_b", "amount": 2.00},
        ]
        original = ReconciliationEngine._create_adjustment_entry

        def failing_for_a(engine_self, correction):
            if correction["settlement_id"] == "stl_a":
                raise Exception("adjustment account missing")
            return original(engine_self, correction)

        self.engine._create_adjustment_entry = failing_for_a.__get__(self.engine, ReconciliationEngine)

        applied = self.engine._apply_corrections()

        self.assertEqual(len(applied), 2)
        self.assertEqual(applied[0]["status"], "failed")
        self.assertEqual(applied[0]["id"], "stl_a")
        self.assertIn("adjustment account missing", applied[0]["error"])
        self.assertEqual(applied[1]["status"], "applied")
        self.assertEqual(applied[1]["id"], "stl_b")


class TestReconciliationLogPersistence(ReconciliationEngineTestBase):
    """A reconciliation that is not recorded cannot be audited afterwards."""

    def test_daily_run_records_nothing_because_status_values_are_rejected(self):
        """DOCUMENTS A PRODUCTION BUG (reconciliation_engine.py:419).

        ``ReconciliationStatus`` uses lowercase values ("completed"/"partial"/
        "failed") but the ``Mollie Reconciliation Log`` Select field only accepts
        "Success", "Partial" or "Failed". Frappe's Select validation is
        case-sensitive, so every insert raises ValidationError, is swallowed by
        the try/except in ``_save_reconciliation_record`` and written to the Error
        Log instead. Result: no reconciliation is ever persisted, and
        ``get_reconciliation_history()`` is permanently empty.
        """
        results = self.engine.run_daily_reconciliation()

        self.assertEqual(results["status"], ReconciliationStatus.COMPLETED)
        self.assertEqual(
            frappe.db.count(
                "Mollie Reconciliation Log", {"reconciliation_id": self.engine.reconciliation_id}
            ),
            0,
        )

    @unittest.expectedFailure
    def test_engine_status_values_are_valid_log_options(self):
        """KNOWN FAILURE - root cause of the empty reconciliation history above.

        Marked ``expectedFailure`` deliberately: it documents the contract that
        *should* hold. Fixing the engine (or the DocType's Select options) turns
        this into an unexpected success, which unittest reports as a failure -
        the signal to drop the ``expectedFailure`` marker and delete
        ``test_daily_run_records_nothing_because_status_values_are_rejected``.
        """
        options = frappe.get_meta("Mollie Reconciliation Log").get_field("status").options.split("\n")

        for status in (
            ReconciliationStatus.COMPLETED,
            ReconciliationStatus.PARTIAL,
            ReconciliationStatus.FAILED,
        ):
            self.assertIn(status, options)

    def test_reconciliation_details_serialise_decimal_totals_without_raising(self):
        """The results dict carries Decimal balances into ``json.dumps``. If that
        ever stops round-tripping, the log record loses its entire payload."""
        self.engine.balances_client.list_balances.return_value = [
            build_balance("EUR", "1500.50", "200.25", "bal_eur")
        ]
        self.engine.balances_client.reconcile_balance.side_effect = lambda bid: {
            "reconciled": True,
            "discrepancy": 0,
        }

        results = self.engine.run_daily_reconciliation()

        encoded = json.loads(json.dumps(results, default=str))
        # Serialised as a string via ``default=str``; the value (not its scale)
        # is what has to survive - the engine routes balances through float on
        # the way in, so "1500.50" arrives as "1500.5".
        self.assertEqual(Decimal(encoded["components"]["balances"]["total_available"]), Decimal("1500.50"))
        self.assertEqual(encoded["components"]["balances"]["balances"][0]["available"], 1500.50)


class TestReconciliationHistoryAndTrends(VereningingenTestCase):
    """History drives the trend analysis operators use to spot a degrading
    integration. The arithmetic runs against real log rows."""

    def setUp(self):
        super().setUp()
        setup_mollie_backend_api()
        self.engine = ReconciliationEngine()
        # Isolate from any rows a previous run left behind; the surrounding test
        # transaction is rolled back afterwards.
        frappe.db.delete("Mollie Reconciliation Log")

    def make_log(self, days_ago, status="Failed", error_count=0, warning_count=0):
        doc = frappe.get_doc(
            {
                "doctype": "Mollie Reconciliation Log",
                "reconciliation_id": frappe.generate_hash(length=10),
                "date": add_days(getdate(), -days_ago),
                "status": status,
                "error_count": error_count,
                "warning_count": warning_count,
                "correction_count": 0,
            }
        )
        doc.insert()
        self.track_doc("Mollie Reconciliation Log", doc.name)
        return doc

    def test_history_window_excludes_records_older_than_requested_days(self):
        recent = self.make_log(days_ago=3)
        edge = self.make_log(days_ago=29)
        self.make_log(days_ago=45)

        history = self.engine.get_reconciliation_history(days=30)

        returned = {r["reconciliation_id"] for r in history}
        self.assertEqual(returned, {recent.reconciliation_id, edge.reconciliation_id})

    def test_history_is_ordered_most_recent_first(self):
        older = self.make_log(days_ago=10)
        newer = self.make_log(days_ago=1)

        history = self.engine.get_reconciliation_history(days=30)

        self.assertEqual(
            [r["reconciliation_id"] for r in history],
            [newer.reconciliation_id, older.reconciliation_id],
        )

    def test_trend_averages_are_computed_across_the_whole_window(self):
        self.make_log(days_ago=1, error_count=4, warning_count=2)
        self.make_log(days_ago=2, error_count=0, warning_count=0)

        analysis = self.engine.analyze_reconciliation_trends()

        self.assertEqual(analysis["total_reconciliations"], 2)
        self.assertEqual(analysis["average_errors"], 2.0)
        self.assertEqual(analysis["average_warnings"], 1.0)

    def test_trend_is_deteriorating_when_recent_errors_exceed_older_by_more_than_half(self):
        for day in range(1, 8):  # 7 most recent days
            self.make_log(days_ago=day, error_count=3)
        for day in range(8, 15):  # the preceding 7 days
            self.make_log(days_ago=day, error_count=1)

        analysis = self.engine.analyze_reconciliation_trends()

        self.assertEqual(analysis["trend"], "deteriorating")

    def test_trend_is_stable_exactly_at_the_1_5x_deterioration_boundary(self):
        """3.0 vs 2.0 is exactly 1.5x. The comparison is strict ``>``, so this
        must stay "stable" - a boundary slip would fire alerts on normal noise."""
        for day in range(1, 8):
            self.make_log(days_ago=day, error_count=3)
        for day in range(8, 15):
            self.make_log(days_ago=day, error_count=2)

        analysis = self.engine.analyze_reconciliation_trends()

        self.assertEqual(analysis["trend"], "stable")

    def test_trend_is_improving_when_recent_errors_drop_below_half(self):
        for day in range(1, 8):
            self.make_log(days_ago=day, error_count=1)
        for day in range(8, 15):
            self.make_log(days_ago=day, error_count=4)

        analysis = self.engine.analyze_reconciliation_trends()

        self.assertEqual(analysis["trend"], "improving")

    def test_trend_stays_stable_without_a_comparison_window(self):
        """Fewer than 8 records means there is no "older" half to compare
        against; the engine must not invent a trend from one week of data."""
        for day in range(1, 6):
            self.make_log(days_ago=day, error_count=9)

        analysis = self.engine.analyze_reconciliation_trends()

        self.assertEqual(analysis["trend"], "stable")
        self.assertEqual(analysis["total_reconciliations"], 5)

    def test_empty_history_reports_zeroed_analysis_without_dividing_by_zero(self):
        analysis = self.engine.analyze_reconciliation_trends()

        self.assertEqual(analysis["total_reconciliations"], 0)
        self.assertEqual(analysis["success_rate"], 0)
        self.assertEqual(analysis["average_errors"], 0)
        self.assertEqual(analysis["trend"], "stable")

    def test_success_rate_never_recognises_a_successful_run(self):
        """DOCUMENTS A PRODUCTION BUG (reconciliation_engine.py:514).

        ``analyze_reconciliation_trends`` counts rows whose status equals
        ``ReconciliationStatus.COMPLETED`` ("completed"), but the DocType can only
        ever store "Success". Even with a full history of clean runs the reported
        success rate is 0%, which reads as a totally broken integration. Same
        root cause as the persistence bug above.
        """
        for day in range(1, 5):
            self.make_log(days_ago=day, status="Success")

        analysis = self.engine.analyze_reconciliation_trends()

        self.assertEqual(analysis["total_reconciliations"], 4)
        self.assertEqual(analysis["success_rate"], 0)


class TestBulkImportValidation(ReconciliationEngineTestBase):
    """``_validate_bulk_imports`` is the engine's only check that the Mollie ->
    Bank Transaction import actually landed the data it claims to have landed.
    It runs against real MT940 Import rows."""

    def setUp(self):
        super().setUp()
        self.bank_account = self._ensure_bank_account()

    def _ensure_bank_account(self):
        bank_name = "TEST Mollie Recon Bank"
        if not frappe.db.exists("Bank", bank_name):
            bank = frappe.get_doc({"doctype": "Bank", "bank_name": bank_name})
            bank.insert()
            self.track_doc("Bank", bank.name)

        account_name = "TEST Mollie Recon Account"
        existing = frappe.db.get_value("Bank Account", {"account_name": account_name, "bank": bank_name})
        if existing:
            return existing

        account = frappe.get_doc({"doctype": "Bank Account", "account_name": account_name, "bank": bank_name})
        account.insert()
        self.track_doc("Bank Account", account.name)
        return account.name

    def make_import(self, status="Completed", created=0, skipped=0, summary="", days_ago=1):
        doc = frappe.get_doc(
            {
                "doctype": "MT940 Import",
                "import_type": "Mollie Bulk Import",
                "bank_account": self.bank_account,
                "import_date": getdate(),
                "import_status": status,
                "transactions_created": created,
                "transactions_skipped": skipped,
                "import_summary": summary,
                "mollie_from_date": add_days(getdate(), -(days_ago + 1)),
                "mollie_to_date": add_days(getdate(), -days_ago),
                "mollie_import_strategy": "hybrid",
            }
        )
        doc.insert()
        self.track_doc("MT940 Import", doc.name)
        return doc

    def test_high_skip_ratio_is_flagged_with_the_actual_ratio(self):
        """Two thirds of the statement lines skipped means duplicate detection is
        eating real transactions - money that never reaches a Bank Transaction."""
        doc = self.make_import(created=10, skipped=20)

        result = self.engine._validate_bulk_imports()

        issues = [i for i in result["validation_issues"] if i["import"] == doc.name]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "high_skip_ratio")
        self.assertIn("66.7%", issues[0]["message"])
        entry = next(i for i in result["recent_imports"] if i["name"] == doc.name)
        self.assertEqual(entry["validation_status"], "issues_found")

    def test_skip_ratio_of_exactly_half_is_not_flagged(self):
        """The threshold is a strict ``> 0.5``; 50/50 is normal for a re-import
        overlapping the previous window."""
        doc = self.make_import(created=10, skipped=10)

        result = self.engine._validate_bulk_imports()

        self.assertEqual([i for i in result["validation_issues"] if i["import"] == doc.name], [])
        entry = next(i for i in result["recent_imports"] if i["name"] == doc.name)
        self.assertEqual(entry["validation_status"], "validated")

    def test_import_that_skipped_everything_is_not_flagged_at_all(self):
        """DOCUMENTS A PRODUCTION BUG (reconciliation_engine.py:653).

        The skip-ratio check is guarded by ``transactions_created > 0``. An import
        that created 0 transactions and skipped 40 - a 100% skip ratio, the worst
        possible outcome and the exact signature of a broken duplicate check or a
        wrong date window - therefore produces no issue at all, and is reported as
        "validated". The guard should be on the denominator
        (``created + skipped > 0``), not on ``created``.
        """
        doc = self.make_import(created=0, skipped=40)

        result = self.engine._validate_bulk_imports()

        self.assertEqual([i for i in result["validation_issues"] if i["import"] == doc.name], [])
        entry = next(i for i in result["recent_imports"] if i["name"] == doc.name)
        self.assertEqual(entry["validation_status"], "validated")

    def test_failed_import_is_flagged_and_excluded_from_the_imported_transaction_count(self):
        completed = self.make_import(status="Completed", created=25)
        failed = self.make_import(status="Failed", created=7, summary="Mollie API returned 401")

        result = self.engine._validate_bulk_imports()

        stats = result["statistics"]
        self.assertEqual(stats["successful_imports"], 1)
        self.assertEqual(stats["failed_imports"], 1)
        # A failed import's partial writes must not be counted as imported.
        self.assertEqual(stats["total_transactions_imported"], 25)

        issues = [i for i in result["validation_issues"] if i["import"] == failed.name]
        self.assertEqual([i["type"] for i in issues], ["failed_import"])
        self.assertIn("Mollie API returned 401", issues[0]["message"])
        self.assertEqual([i for i in result["validation_issues"] if i["import"] == completed.name], [])

    def test_success_rate_below_eighty_percent_raises_a_run_warning(self):
        for _ in range(3):
            self.make_import(status="Completed", created=5)
        for _ in range(2):
            self.make_import(status="Failed")

        self.engine._validate_bulk_imports()

        rate_warnings = [w for w in self.engine.warnings if "success rate is low" in w]
        self.assertEqual(len(rate_warnings), 1)
        self.assertIn("60.0%", rate_warnings[0])

    def test_success_rate_of_exactly_eighty_percent_does_not_warn(self):
        """Strict ``< 80``: one failure in five is tolerated, two is not."""
        for _ in range(4):
            self.make_import(status="Completed", created=5)
        self.make_import(status="Failed")

        self.engine._validate_bulk_imports()

        self.assertEqual([w for w in self.engine.warnings if "success rate is low" in w], [])

    def test_only_mollie_bulk_imports_are_validated(self):
        """A file-based MT940 import has nothing to do with the Mollie
        reconciliation and must not drag the success rate down."""
        statement = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": f"recon-test-{frappe.generate_hash(length=6)}.sta",
                "is_private": 1,
                "content": ":20:DUMMY",
            }
        )
        statement.insert()
        self.track_doc("File", statement.name)

        file_import = frappe.get_doc(
            {
                "doctype": "MT940 Import",
                "import_type": "MT940 File Import",
                "bank_account": self.bank_account,
                "import_date": getdate(),
                "import_status": "Failed",
                "mt940_file": statement.file_url,
            }
        )
        file_import.insert()
        self.track_doc("MT940 Import", file_import.name)
        mollie_import = self.make_import(status="Completed", created=3)

        result = self.engine._validate_bulk_imports()

        names = [i["name"] for i in result["recent_imports"]]
        self.assertIn(mollie_import.name, names)
        self.assertNotIn(file_import.name, names)
        self.assertEqual([w for w in self.engine.warnings if "success rate is low" in w], [])
