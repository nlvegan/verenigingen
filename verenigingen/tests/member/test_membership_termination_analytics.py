"""
Real-integration tests for the termination analytics module
``verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_analytics.py``.

The module computes trends, predictions, early-warning indicators and an executive
summary over ``Membership Termination Request`` rows. It was ~10% covered.

These tests create real Members and Termination Requests (no business-logic
mocking) and assert that the analytics return well-formed structures with correct
counts. The pure helper functions (trend / efficiency / prediction maths) are
exercised directly with representative inputs, and the whitelisted aggregators
(``get_termination_trends``, ``get_early_warning_system``,
``generate_executive_summary``) are run against seeded data.
"""

import frappe
from frappe.utils import add_months, getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.membership_termination_request import (
    membership_termination_analytics as ana,
)


class TestMembershipTerminationAnalytics(VereningingenTestCase):
    """Exercise the termination analytics functions end to end."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Analytics",
            last_name="Subject",
            email=f"analytics.subject.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )

    # ------------------------------------------------------------------ helpers

    def _make_request(self, member=None, **kwargs):
        defaults = {
            "doctype": "Membership Termination Request",
            "member": member or self.member.name,
            "termination_type": "Voluntary",
            "termination_reason": "analytics seed",
            "member_request_date": today(),
        }
        defaults.update(kwargs)
        doc = frappe.get_doc(defaults)
        doc.insert()
        self.track_doc("Membership Termination Request", doc.name)
        return doc

    def _make_disciplinary(self, member=None, **kwargs):
        defaults = {
            "termination_type": "Expulsion",
            "termination_reason": "analytics disciplinary seed",
            "disciplinary_documentation": "<p>doc</p>",
            "member_request_date": None,
        }
        defaults.update(kwargs)
        return self._make_request(member=member, **defaults)

    def _fresh_member(self, label):
        return self.create_test_member(
            first_name=label,
            last_name="Analytics",
            email=f"analytics.{label.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )

    # ============================================================ get_termination_trends

    def test_get_termination_trends_shape(self):
        self._make_request()
        trends = ana.get_termination_trends(period="12_months")
        for key in (
            "period",
            "start_date",
            "end_date",
            "total_terminations",
            "monthly_breakdown",
            "type_trends",
            "chapter_analysis",
            "processing_efficiency",
            "risk_indicators",
            "predictions",
            "seasonal_patterns",
        ):
            self.assertIn(key, trends)
        self.assertEqual(trends["period"], "12_months")
        self.assertGreaterEqual(trends["total_terminations"], 1)

    def test_get_termination_trends_period_6_months(self):
        trends = ana.get_termination_trends(period="6_months")
        self.assertEqual(trends["start_date"], add_months(trends["end_date"], -6))

    def test_get_termination_trends_period_2_years(self):
        trends = ana.get_termination_trends(period="2_years")
        self.assertEqual(trends["start_date"], add_months(trends["end_date"], -24))

    # ============================================================ analyze_monthly_breakdown

    def test_analyze_monthly_breakdown_fills_months_and_counts(self):
        # get_termination_trends passes getdate() objects (date), so the missing-
        # month fill loop relies on .strftime() — mirror that real call contract.
        start = getdate(add_months(today(), -2))
        end = getdate(today())
        rows = [
            frappe._dict(request_date=today(), termination_type="Voluntary", status="Draft"),
            frappe._dict(request_date=today(), termination_type="Expulsion", status="Executed"),
        ]
        breakdown = ana.analyze_monthly_breakdown(rows, start, end)
        # Every month in range is present (zero-filled).
        self.assertGreaterEqual(len(breakdown), 3)
        this_month = getdate(today()).strftime("%Y-%m")
        self.assertEqual(breakdown[this_month]["total"], 2)
        self.assertEqual(breakdown[this_month]["voluntary"], 1)
        self.assertEqual(breakdown[this_month]["disciplinary"], 1)
        self.assertEqual(breakdown[this_month]["executed"], 1)

    # ============================================================ analyze_type_trends

    def test_analyze_type_trends_needs_three_months(self):
        # All in the same month -> only one distinct month -> excluded (needs >=3).
        rows = [
            frappe._dict(request_date=today(), termination_type="Voluntary")
            for _ in range(4)
        ]
        result = ana.analyze_type_trends(rows)
        self.assertNotIn("Voluntary", result)

    def test_analyze_type_trends_three_distinct_months(self):
        rows = [
            frappe._dict(request_date=add_months(today(), -2), termination_type="Voluntary"),
            frappe._dict(request_date=add_months(today(), -1), termination_type="Voluntary"),
            frappe._dict(request_date=today(), termination_type="Voluntary"),
        ]
        result = ana.analyze_type_trends(rows)
        self.assertIn("Voluntary", result)
        self.assertEqual(result["Voluntary"]["count"], 3)
        self.assertIn("trend", result["Voluntary"])
        self.assertIn("recent_average", result["Voluntary"])

    # ============================================================ analyze_chapter_patterns + risk

    def test_analyze_chapter_patterns_no_chapter_bucket(self):
        # Member with no enabled Chapter Member row lands in "No Chapter".
        m = self._fresh_member("NoChap")
        # Remove any chapter membership the factory may have added.
        frappe.db.delete("Chapter Member", {"member": m.name})
        rows = [
            frappe._dict(member=m.name, termination_type="Expulsion", requested_by="Administrator"),
            frappe._dict(member=m.name, termination_type="Voluntary", requested_by="Administrator"),
        ]
        result = ana.analyze_chapter_patterns(rows)
        self.assertIn("No Chapter", result)
        bucket = result["No Chapter"]
        self.assertEqual(bucket["total"], 2)
        self.assertEqual(bucket["disciplinary"], 1)
        self.assertEqual(bucket["voluntary"], 1)
        self.assertEqual(bucket["disciplinary_rate"], 50.0)
        self.assertIn("risk_score", bucket)

    def test_calculate_chapter_risk_score_high(self):
        # High disciplinary rate (>50 -> +30) + high volume (>10 -> +20) + one
        # dominant requester (>70% -> +25) = 75 (the maximum the scorer can reach).
        data = {
            "disciplinary_rate": 60,
            "total": 12,
            "by_requester": {"u1": 11, "u2": 1},
        }
        score = ana.calculate_chapter_risk_score(data)
        self.assertEqual(score, 75)

    def test_calculate_chapter_risk_score_low(self):
        data = {"disciplinary_rate": 5, "total": 2, "by_requester": {"u1": 1, "u2": 1}}
        self.assertEqual(ana.calculate_chapter_risk_score(data), 0)

    # ============================================================ processing efficiency

    def test_analyze_processing_efficiency_shape(self):
        rows = [
            frappe._dict(
                status="Executed",
                request_date="2024-01-01",
                execution_date="2024-01-11",
            ),
            frappe._dict(status="Draft", request_date="2024-01-05", execution_date=None),
        ]
        eff = ana.analyze_processing_efficiency(rows)
        self.assertIn("status_distribution", eff)
        self.assertEqual(eff["status_distribution"]["Executed"], 1)
        self.assertEqual(eff["avg_processing_time"], 10)
        self.assertEqual(eff["median_processing_time"], 10)
        self.assertIn("efficiency_score", eff)

    def test_calculate_processing_time_trend_insufficient(self):
        rows = [
            frappe._dict(request_date="2024-01-01", execution_date="2024-01-05"),
        ]
        trend = ana.calculate_processing_time_trend(rows)
        self.assertEqual(trend["trend"], 0)
        self.assertFalse(trend["improvement"])

    def test_calculate_processing_time_trend_improving(self):
        # Three months of decreasing processing times -> negative trend -> improving.
        rows = [
            frappe._dict(request_date="2024-01-01", execution_date="2024-01-21"),  # 20 days
            frappe._dict(request_date="2024-02-01", execution_date="2024-02-11"),  # 10 days
            frappe._dict(request_date="2024-03-01", execution_date="2024-03-03"),  # 2 days
        ]
        trend = ana.calculate_processing_time_trend(rows)
        self.assertLess(trend["trend"], 0)
        self.assertTrue(trend["improvement"])

    def test_calculate_efficiency_score_empty(self):
        self.assertEqual(ana.calculate_efficiency_score({}, []), 0)

    def test_calculate_efficiency_score_penalises_slow_and_pending(self):
        # All pending + slow processing -> well below 100.
        dist = {"Draft": 5, "Executed": 5}
        score = ana.calculate_efficiency_score(dist, [40, 45, 50])
        self.assertLess(score, 100)
        self.assertGreaterEqual(score, 0)

    # ============================================================ risk indicators

    def test_identify_risk_indicators_empty(self):
        result = ana.identify_risk_indicators([])
        self.assertEqual(result["risk_level"], "LOW")
        self.assertFalse(result["high_disciplinary_rate"])

    def test_identify_risk_indicators_high(self):
        # All disciplinary + all pending + single requester -> HIGH.
        rows = [
            frappe._dict(termination_type="Expulsion", status="Draft", requested_by="u1")
            for _ in range(5)
        ]
        result = ana.identify_risk_indicators(rows)
        self.assertTrue(result["high_disciplinary_rate"])
        self.assertTrue(result["processing_delays"])
        self.assertTrue(result["concentrated_requesters"])
        self.assertEqual(result["risk_level"], "HIGH")
        self.assertTrue(result["unusual_patterns"])

    # ============================================================ predictions

    def test_generate_predictions_insufficient(self):
        rows = [frappe._dict(request_date=today()) for _ in range(3)]
        result = ana.generate_predictions(rows)
        self.assertTrue(result["insufficient_data"])

    def test_generate_predictions_with_data(self):
        rows = []
        for offset in range(6):
            month_date = add_months(today(), -offset)
            for _ in range(2):
                rows.append(frappe._dict(request_date=month_date))
        result = ana.generate_predictions(rows)
        self.assertNotIn("insufficient_data", result)
        self.assertIn("next_month", result)
        self.assertIn("next_quarter", result)
        self.assertIn(result["trend"], ("increasing", "decreasing", "stable"))
        self.assertIn(result["confidence"], ("LOW", "MEDIUM", "HIGH"))

    # ============================================================ seasonal patterns

    def test_identify_seasonal_patterns_shape(self):
        rows = [
            frappe._dict(request_date="2024-01-15", termination_type="Voluntary"),
            frappe._dict(request_date="2024-01-20", termination_type="Expulsion"),
            frappe._dict(request_date="2024-07-10", termination_type="Voluntary"),
        ]
        result = ana.identify_seasonal_patterns(rows)
        self.assertIn("monthly_data", result)
        self.assertIn("January", result["monthly_data"])
        self.assertEqual(result["monthly_data"]["January"]["count"], 2)
        self.assertIn("peak_month", result)
        self.assertIn("low_month", result)
        self.assertIn("has_seasonal_pattern", result)

    # ============================================================ pure maths helpers

    def test_calculate_trend_increasing(self):
        self.assertGreater(ana.calculate_trend([1, 2, 3, 4]), 0)

    def test_calculate_trend_flat(self):
        self.assertEqual(ana.calculate_trend([5, 5, 5]), 0)

    def test_calculate_trend_single(self):
        self.assertEqual(ana.calculate_trend([5]), 0)

    def test_calculate_prediction_confidence_levels(self):
        self.assertEqual(ana.calculate_prediction_confidence([10, 10, 10]), "HIGH")
        self.assertEqual(ana.calculate_prediction_confidence([1]), "LOW")
        # Wildly varying counts -> LOW confidence.
        self.assertEqual(ana.calculate_prediction_confidence([1, 20, 2]), "LOW")

    # ============================================================ early warning system

    def test_get_early_warning_system_shape(self):
        self._make_request()
        warnings = ana.get_early_warning_system()
        for key in ("critical", "warning", "info", "last_updated"):
            self.assertIn(key, warnings)
        self.assertIsInstance(warnings["critical"], list)
        self.assertIsInstance(warnings["warning"], list)

    def test_check_system_health_shape(self):
        health = ana.check_system_health()
        self.assertIn("status", health)
        self.assertIn("issues", health)
        self.assertIn(health["status"], ("healthy", "warning", "critical"))

    def test_check_system_health_flags_missing_disciplinary_docs(self):
        # A disciplinary request without documentation cannot be inserted (validation
        # blocks it), so simulate the data-integrity case by clearing the field
        # directly in the DB and confirm the health check surfaces it.
        doc = self._make_disciplinary()
        frappe.db.set_value(
            "Membership Termination Request", doc.name, "disciplinary_documentation", ""
        )
        health = ana.check_system_health()
        types = {issue["type"] for issue in health["issues"]}
        self.assertIn("missing_documentation", types)

    # ============================================================ executive summary

    def test_generate_executive_summary_shape_and_counts(self):
        self._make_request()
        self._make_disciplinary(member=self._fresh_member("ExecDisc").name)
        summary = ana.generate_executive_summary()
        for key in (
            "period",
            "total_terminations",
            "disciplinary_terminations",
            "completed_terminations",
            "pending_terminations",
            "key_metrics",
            "recommendations",
        ):
            self.assertIn(key, summary)
        self.assertGreaterEqual(summary["total_terminations"], 2)
        self.assertGreaterEqual(summary["disciplinary_terminations"], 1)
        self.assertIsInstance(summary["recommendations"], list)

    # ============================================================ key metrics / recommendations

    def test_calculate_key_metrics(self):
        rows = [
            frappe._dict(
                termination_type="Voluntary",
                status="Executed",
                request_date="2024-01-01",
                execution_date="2024-01-11",
            ),
            frappe._dict(
                termination_type="Expulsion",
                status="Executed",
                request_date="2024-02-01",
                execution_date="2024-02-21",
            ),
        ]
        metrics = ana.calculate_key_metrics(rows, [])
        self.assertIn("avg_processing_time", metrics)
        self.assertIn("median_processing_time", metrics)
        self.assertEqual(metrics["avg_processing_time"], 15)
        self.assertEqual(metrics["disciplinary_rate"], 50.0)

    def test_generate_recommendations_slow_processing_and_high_disciplinary(self):
        rows = [
            frappe._dict(
                termination_type="Expulsion",
                status="Executed",
                request_date="2024-01-01",
                execution_date="2024-02-15",  # 45 days -> slow
            ),
            frappe._dict(
                termination_type="Expulsion",
                status="Executed",
                request_date="2024-01-01",
                execution_date="2024-02-20",  # 50 days
            ),
        ]
        recs = ana.generate_recommendations(rows, [])
        categories = {r["category"] for r in recs}
        self.assertIn("efficiency", categories)
        self.assertIn("governance", categories)

    def test_generate_recommendations_clean_data_empty(self):
        rows = [
            frappe._dict(
                termination_type="Voluntary",
                status="Executed",
                request_date="2024-01-01",
                execution_date="2024-01-05",  # 4 days -> fast, no disciplinary
            ),
        ]
        recs = ana.generate_recommendations(rows, [])
        self.assertEqual(recs, [])
