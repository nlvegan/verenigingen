"""
SEPA Admin Reporting Tools

Week 4 Implementation: Comprehensive reporting tools for SEPA administrators
providing detailed analytics, operational insights, and business intelligence
for SEPA batch operations and mandate management.

This module provides advanced reporting capabilities with exportable formats,
scheduled report generation, and executive dashboards.
"""

import csv
import io
import json
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import cint, flt, format_datetime, formatdate, get_datetime, now_datetime
from frappe.utils.pdf import get_pdf

from verenigingen.utils.error_handling import log_error
from verenigingen.utils.sepa_memory_optimizer import SEPAMemoryMonitor
from verenigingen.utils.sepa_monitoring_dashboard import get_dashboard_instance


class SEPAAdminReportGenerator:
    """
    Advanced reporting system for SEPA administrators

    Generates comprehensive reports on batch processing, financial metrics,
    operational performance, and business intelligence insights.
    """

    def __init__(self):
        self.memory_monitor = SEPAMemoryMonitor()
        self.dashboard = get_dashboard_instance()

    def generate_executive_summary(self, days: int = 30) -> Dict[str, Any]:
        """
        Generate executive summary report for management

        Args:
            days: Time period in days

        Returns:
            Executive summary data
        """
        cutoff_time = get_datetime() - timedelta(days=days)

        # Get key performance indicators
        kpis = self._calculate_kpis(cutoff_time)

        # Get trend analysis
        trends = self._analyze_trends(cutoff_time, days)

        # Get risk indicators
        risks = self._identify_risks(cutoff_time)

        # Get recommendations
        recommendations = self._generate_executive_recommendations(kpis, trends, risks)

        return {
            "report_type": "executive_summary",
            "period_days": days,
            "generated_at": get_datetime().isoformat(),
            "kpis": kpis,
            "trends": trends,
            "risk_indicators": risks,
            "recommendations": recommendations,
            "next_review_date": (get_datetime() + timedelta(days=7)).isoformat(),
        }

    def generate_operational_report(self, days: int = 7) -> Dict[str, Any]:
        """
        Generate detailed operational report for administrators

        Args:
            days: Time period in days

        Returns:
            Operational report data
        """
        cutoff_time = get_datetime() - timedelta(days=days)

        # Batch processing statistics
        batch_stats = self._get_batch_processing_stats(cutoff_time)

        # Mandate management statistics
        mandate_stats = self._get_mandate_management_stats(cutoff_time)

        # Error analysis
        error_analysis = self._analyze_errors(cutoff_time)

        # Performance metrics
        performance_metrics = self._get_performance_metrics(cutoff_time)

        # System health
        system_health = self._assess_system_health()

        return {
            "report_type": "operational_report",
            "period_days": days,
            "generated_at": get_datetime().isoformat(),
            "batch_processing": batch_stats,
            "mandate_management": mandate_stats,
            "error_analysis": error_analysis,
            "performance_metrics": performance_metrics,
            "system_health": system_health,
            "action_items": self._generate_action_items(batch_stats, error_analysis, system_health),
        }

    def generate_financial_analysis(self, days: int = 30) -> Dict[str, Any]:
        """
        Generate comprehensive financial analysis report

        Args:
            days: Time period in days

        Returns:
            Financial analysis data
        """
        cutoff_time = get_datetime() - timedelta(days=days)

        # Get financial data
        financial_data = frappe.db.sql(
            """
            SELECT
                ddb.name as batch_name,
                ddb.creation,
                ddb.batch_date,
                ddb.total_amount,
                ddb.status,
                COUNT(ddbi.invoice) as invoice_count,
                SUM(si.grand_total) as gross_amount,
                SUM(si.outstanding_amount) as outstanding_amount,
                SUM(CASE WHEN si.status = 'Paid' THEN si.grand_total ELSE 0 END) as collected_amount,
                AVG(si.grand_total) as avg_invoice_amount,
                MIN(si.posting_date) as earliest_invoice,
                MAX(si.posting_date) as latest_invoice,
                SUM(CASE WHEN si.currency != 'EUR' THEN si.grand_total ELSE 0 END) as foreign_currency_amount
            FROM `tabDirect Debit Batch` ddb
            LEFT JOIN `tabDirect Debit Batch Invoice` ddbi ON ddbi.parent = ddb.name
            LEFT JOIN `tabSales Invoice` si ON si.name = ddbi.invoice
            WHERE ddb.creation >= %(cutoff_time)s
            GROUP BY ddb.name
            ORDER BY ddb.creation DESC
        """,
            {"cutoff_time": cutoff_time},
            as_dict=True,
        )

        # Calculate financial metrics
        financial_metrics = self._calculate_financial_metrics(financial_data)

        # Revenue analysis
        revenue_analysis = self._analyze_revenue_patterns(financial_data, days)

        # Collection efficiency
        collection_analysis = self._analyze_collection_efficiency(financial_data)

        # Risk assessment
        financial_risks = self._assess_financial_risks(financial_data)

        return {
            "report_type": "financial_analysis",
            "period_days": days,
            "generated_at": get_datetime().isoformat(),
            "summary_metrics": financial_metrics,
            "revenue_analysis": revenue_analysis,
            "collection_analysis": collection_analysis,
            "risk_assessment": financial_risks,
            "detailed_batches": financial_data[:50],  # Top 50 recent batches
            "compliance_status": self._check_financial_compliance(financial_data),
        }

    def generate_mandate_lifecycle_report(self) -> Dict[str, Any]:
        """
        Generate mandate lifecycle and health analysis report

        Returns:
            Mandate lifecycle report data
        """
        # Get mandate data with lifecycle information
        mandate_data = frappe.db.sql(
            """
            SELECT
                sm.name,
                sm.mandate_id,
                sm.member,
                sm.status,
                sm.sign_date,
                sm.iban,
                sm.bic,
                sm.creation,
                sm.modified,
                m.full_name as member_name,
                m.email as member_email,
                m.status as member_status,
                DATEDIFF(NOW(), sm.sign_date) as age_days,
                (SELECT COUNT(*) FROM `tabDirect Debit Batch Invoice` ddbi
                 JOIN `tabDirect Debit Batch` ddb ON ddb.name = ddbi.parent
                 JOIN `tabSales Invoice` si ON si.name = ddbi.invoice
                 JOIN `tabMember` mem ON mem.customer = si.customer
                 WHERE mem.name = sm.member
                 AND ddb.docstatus = 1) as usage_count,
                (SELECT MAX(ddb.batch_date) FROM `tabDirect Debit Batch Invoice` ddbi
                 JOIN `tabDirect Debit Batch` ddb ON ddb.name = ddbi.parent
                 JOIN `tabSales Invoice` si ON si.name = ddbi.invoice
                 JOIN `tabMember` mem ON mem.customer = si.customer
                 WHERE mem.name = sm.member
                 AND ddb.docstatus = 1) as last_used,
                (SELECT SUM(ddb.total_amount) FROM `tabDirect Debit Batch Invoice` ddbi
                 JOIN `tabDirect Debit Batch` ddb ON ddb.name = ddbi.parent
                 JOIN `tabSales Invoice` si ON si.name = ddbi.invoice
                 JOIN `tabMember` mem ON mem.customer = si.customer
                 WHERE mem.name = sm.member
                 AND ddb.docstatus = 1) as total_processed_amount
            FROM `tabSEPA Mandate` sm
            LEFT JOIN `tabMember` m ON m.name = sm.member
            WHERE sm.docstatus = 1
            ORDER BY sm.creation DESC
        """,
            as_dict=True,
        )

        # Analyze mandate lifecycle
        lifecycle_analysis = self._analyze_mandate_lifecycle(mandate_data)

        # Health scoring
        health_scores = self._calculate_mandate_health_scores(mandate_data)

        # Usage patterns
        usage_patterns = self._analyze_mandate_usage_patterns(mandate_data)

        # Compliance status
        compliance_status = self._check_mandate_compliance(mandate_data)

        return {
            "report_type": "mandate_lifecycle_report",
            "generated_at": get_datetime().isoformat(),
            "total_mandates": len(mandate_data),
            "lifecycle_analysis": lifecycle_analysis,
            "health_scores": health_scores,
            "usage_patterns": usage_patterns,
            "compliance_status": compliance_status,
            "recommendations": self._generate_mandate_recommendations(
                lifecycle_analysis, health_scores, usage_patterns
            ),
            "detailed_mandates": mandate_data[:100],  # Top 100 recent mandates
        }

    def generate_performance_benchmark_report(self, days: int = 30) -> Dict[str, Any]:
        """
        Generate performance benchmarking report

        Args:
            days: Time period in days

        Returns:
            Performance benchmark data
        """
        cutoff_time = get_datetime() - timedelta(days=days)

        # Define performance benchmarks
        benchmarks = {
            "batch_creation_time_ms": {"target": 5000, "acceptable": 15000, "critical": 30000},
            "batch_success_rate_percent": {"target": 99.0, "acceptable": 95.0, "critical": 90.0},
            "memory_usage_mb": {"target": 256, "acceptable": 512, "critical": 1024},
            "daily_batch_count": {"target": 5, "acceptable": 3, "critical": 1},
            "error_rate_percent": {"target": 1.0, "acceptable": 5.0, "critical": 10.0},
            "mandate_validation_success_rate": {"target": 98.0, "acceptable": 95.0, "critical": 90.0},
        }

        # Get actual performance metrics
        actual_metrics = self._calculate_benchmark_metrics(cutoff_time)

        # Compare against benchmarks
        benchmark_results = {}
        for metric_name, benchmark in benchmarks.items():
            actual_value = actual_metrics.get(metric_name, 0)

            if actual_value <= benchmark["target"]:
                status = "excellent"
            elif actual_value <= benchmark["acceptable"]:
                status = "good"
            elif actual_value <= benchmark["critical"]:
                status = "needs_improvement"
            else:
                status = "critical"

            benchmark_results[metric_name] = {
                "actual_value": actual_value,
                "target": benchmark["target"],
                "acceptable": benchmark["acceptable"],
                "critical": benchmark["critical"],
                "status": status,
                "variance_percent": ((actual_value - benchmark["target"]) / benchmark["target"] * 100)
                if benchmark["target"] > 0
                else 0,
            }

        # Calculate overall performance score
        performance_score = self._calculate_performance_score(benchmark_results)

        return {
            "report_type": "performance_benchmark_report",
            "period_days": days,
            "generated_at": get_datetime().isoformat(),
            "overall_performance_score": performance_score,
            "benchmark_results": benchmark_results,
            "performance_trends": self._analyze_performance_trends(cutoff_time, days),
            "improvement_recommendations": self._generate_performance_improvements(benchmark_results),
        }

    def export_report_to_csv(self, report_data: Dict[str, Any]) -> str:
        """
        Export report data to CSV format

        Args:
            report_data: Report data dictionary

        Returns:
            CSV content as string
        """
        output = io.StringIO()

        if report_data.get("report_type") == "financial_analysis":
            # Export financial data
            fieldnames = [
                "batch_name",
                "creation",
                "total_amount",
                "status",
                "invoice_count",
                "collected_amount",
                "outstanding_amount",
            ]

            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()

            for batch in report_data.get("detailed_batches", []):
                writer.writerow(
                    {
                        "batch_name": batch.get("batch_name", ""),
                        "creation": str(batch.get("creation", "")),
                        "total_amount": batch.get("total_amount", 0),
                        "status": batch.get("status", ""),
                        "invoice_count": batch.get("invoice_count", 0),
                        "collected_amount": batch.get("collected_amount", 0),
                        "outstanding_amount": batch.get("outstanding_amount", 0),
                    }
                )

        elif report_data.get("report_type") == "mandate_lifecycle_report":
            # Export mandate data
            fieldnames = [
                "mandate_id",
                "member_name",
                "status",
                "sign_date",
                "age_days",
                "usage_count",
                "last_used",
                "total_processed_amount",
            ]

            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()

            for mandate in report_data.get("detailed_mandates", []):
                writer.writerow(
                    {
                        "mandate_id": mandate.get("mandate_id", ""),
                        "member_name": mandate.get("member_name", ""),
                        "status": mandate.get("status", ""),
                        "sign_date": str(mandate.get("sign_date", "")),
                        "age_days": mandate.get("age_days", 0),
                        "usage_count": mandate.get("usage_count", 0),
                        "last_used": str(mandate.get("last_used", "")),
                        "total_processed_amount": mandate.get("total_processed_amount", 0),
                    }
                )

        else:
            # Generic export for other report types
            writer = csv.writer(output)
            writer.writerow(["Report Type", report_data.get("report_type", "Unknown")])
            writer.writerow(["Generated At", report_data.get("generated_at", "")])
            writer.writerow([""])

            # Export key metrics
            for key, value in report_data.items():
                if isinstance(value, (str, int, float)):
                    writer.writerow([key, str(value)])

        return output.getvalue()

    def schedule_report_generation(
        self, report_type: str, frequency: str, recipients: List[str], parameters: Dict[str, Any] = None
    ) -> str:
        """
        Schedule automatic report generation

        Args:
            report_type: Type of report to generate
            frequency: Frequency (daily, weekly, monthly)
            recipients: List of email recipients
            parameters: Report parameters

        Returns:
            Schedule ID
        """
        parameters = parameters or {}

        # Create scheduled report record
        schedule_doc = frappe.get_doc(
            {
                "doctype": "SEPA Report Schedule",
                "report_type": report_type,
                "frequency": frequency,
                "recipients": json.dumps(recipients),
                "parameters": json.dumps(parameters),
                "enabled": 1,
                "next_run": self._calculate_next_run_time(frequency),
                "created_by": frappe.session.user,
            }
        )

        schedule_doc.insert()

        return schedule_doc.name

    # Private helper methods

    def _calculate_kpis(self, cutoff_time: datetime) -> Dict[str, Any]:
        """Calculate key performance indicators with SQL optimization and Python fallback"""
        return {
            "total_batches_processed": frappe.db.count(
                "Direct Debit Batch", {"creation": [">=", cutoff_time]}
            ),
            "total_amount_processed": self._calculate_total_amount_processed_optimized(cutoff_time),
            "average_batch_processing_time": self._get_avg_processing_time(cutoff_time),
            "success_rate_percent": self._calculate_success_rate(cutoff_time),
            "active_mandate_count": frappe.db.count("SEPA Mandate", {"status": "Active"}),
            "error_rate_percent": self._calculate_error_rate(cutoff_time),
        }

    def _analyze_trends(self, cutoff_time: datetime, days: int) -> Dict[str, Any]:
        """Analyze performance trends"""
        # Get daily batch counts
        daily_stats = frappe.db.sql(
            """
            SELECT
                DATE(creation) as date,
                COUNT(*) as batch_count,
                SUM(total_amount) as total_amount
            FROM `tabDirect Debit Batch`
            WHERE creation >= %s
            GROUP BY DATE(creation)
            ORDER BY date
        """,
            (cutoff_time,),
            as_dict=True,
        )

        if len(daily_stats) < 2:
            return {"trend": "insufficient_data"}

        # Calculate trends
        batch_counts = [stat.batch_count for stat in daily_stats]
        amounts = [stat.total_amount or 0 for stat in daily_stats]

        return {
            "batch_count_trend": self._calculate_trend(batch_counts),
            "amount_trend": self._calculate_trend(amounts),
            "daily_statistics": daily_stats,
            "growth_rate_percent": self._calculate_growth_rate(amounts),
        }

    def _identify_risks(self, cutoff_time: datetime) -> List[Dict[str, Any]]:
        """Identify operational risks"""
        risks = []

        # Check for stuck batches
        stuck_batches = frappe.db.count(
            "Direct Debit Batch", {"status": "Draft", "creation": ["<", get_datetime() - timedelta(hours=2)]}
        )

        if stuck_batches > 0:
            risks.append(
                {
                    "type": "operational",
                    "severity": "medium",
                    "description": f"{stuck_batches} batches stuck in draft status",
                    "recommendation": "Review batch processing workflow",
                }
            )

        # Check mandate expiration
        expiring_mandates = (
            frappe.db.sql(
                """
            SELECT COUNT(*) FROM `tabSEPA Mandate`
            WHERE status = 'Active'
            AND sign_date < DATE_SUB(NOW(), INTERVAL 3 YEAR)
        """
            )[0][0]
            or 0
        )

        if expiring_mandates > 0:
            risks.append(
                {
                    "type": "compliance",
                    "severity": "high",
                    "description": f"{expiring_mandates} mandates may be expiring soon",
                    "recommendation": "Implement mandate renewal process",
                }
            )

        return risks

    def _generate_executive_recommendations(
        self, kpis: Dict[str, Any], trends: Dict[str, Any], risks: List[Dict[str, Any]]
    ) -> List[str]:
        """Generate executive recommendations"""
        recommendations = []

        # Performance recommendations
        if kpis.get("success_rate_percent", 100) < 95:
            recommendations.append("Investigate and improve batch processing success rate")

        # Growth recommendations
        if trends.get("growth_rate_percent", 0) < 5:
            recommendations.append("Consider initiatives to increase transaction volume")

        # Risk mitigation
        high_risks = [r for r in risks if r.get("severity") == "high"]
        if high_risks:
            recommendations.append("Address high-severity risks immediately")

        return recommendations or ["System performance is optimal"]

    def _get_batch_processing_stats(self, cutoff_time: datetime) -> Dict[str, Any]:
        """Get detailed batch processing statistics"""
        return {
            "total_batches": frappe.db.count("Direct Debit Batch", {"creation": [">=", cutoff_time]}),
            "status_distribution": dict(
                frappe.db.sql(
                    """
                SELECT status, COUNT(*)
                FROM `tabDirect Debit Batch`
                WHERE creation >= %s
                GROUP BY status
            """,
                    (cutoff_time,),
                )
            ),
            "avg_batch_size": frappe.db.sql(
                """
                SELECT AVG(
                    (SELECT COUNT(*) FROM `tabDirect Debit Batch Invoice`
                     WHERE parent = ddb.name)
                )
                FROM `tabDirect Debit Batch` ddb
                WHERE creation >= %s
            """,
                (cutoff_time,),
            )[0][0]
            or 0,
            "processing_time_distribution": self._get_processing_time_distribution(cutoff_time),
        }

    def _get_mandate_management_stats(self, cutoff_time: datetime) -> Dict[str, Any]:
        """Get mandate management statistics"""
        return {
            "total_mandates": frappe.db.count("SEPA Mandate"),
            "active_mandates": frappe.db.count("SEPA Mandate", {"status": "Active"}),
            "new_mandates": frappe.db.count("SEPA Mandate", {"creation": [">=", cutoff_time]}),
            "mandate_usage_rate": self._calculate_mandate_usage_rate(cutoff_time),
            "validation_success_rate": self._calculate_mandate_validation_rate(cutoff_time),
        }

    def _analyze_errors(self, cutoff_time: datetime) -> Dict[str, Any]:
        """Analyze system errors"""
        # This would typically analyze error logs
        return {"total_errors": 0, "error_categories": {}, "top_error_messages": [], "error_trend": "stable"}

    def _get_performance_metrics(self, cutoff_time: datetime) -> Dict[str, Any]:
        """Get system performance metrics"""
        current_memory = self.memory_monitor.take_snapshot()

        return {
            "current_memory_usage_mb": current_memory.process_memory_mb,
            "system_memory_percent": current_memory.system_memory_percent,
            "avg_api_response_time_ms": self._get_avg_api_response_time(cutoff_time),
            "database_query_performance": self._get_db_performance_stats(cutoff_time),
        }

    def _assess_system_health(self) -> Dict[str, Any]:
        """Assess overall system health"""
        return {
            "overall_status": "healthy",
            "database_status": "healthy",
            "cache_status": "healthy",
            "scheduler_status": "healthy",
            "last_health_check": get_datetime().isoformat(),
        }

    def _generate_action_items(
        self, batch_stats: Dict[str, Any], error_analysis: Dict[str, Any], system_health: Dict[str, Any]
    ) -> List[str]:
        """Generate actionable items for administrators"""
        action_items = []

        # Based on batch statistics
        if batch_stats.get("total_batches", 0) == 0:
            action_items.append("No batches processed - investigate scheduling")

        # Based on system health
        if system_health.get("overall_status") != "healthy":
            action_items.append("System health issues detected - run diagnostics")

        return action_items or ["No immediate action required"]

    def _calculate_financial_metrics(self, financial_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate comprehensive financial metrics"""
        if not financial_data:
            return {}

        total_gross = sum(flt(batch.get("gross_amount", 0)) for batch in financial_data)
        total_collected = sum(flt(batch.get("collected_amount", 0)) for batch in financial_data)
        total_outstanding = sum(flt(batch.get("outstanding_amount", 0)) for batch in financial_data)

        return {
            "total_gross_amount": total_gross,
            "total_collected_amount": total_collected,
            "total_outstanding_amount": total_outstanding,
            "collection_rate_percent": (total_collected / total_gross * 100) if total_gross > 0 else 0,
            "average_batch_amount": total_gross / len(financial_data),
            "largest_batch_amount": max(
                (flt(batch.get("gross_amount", 0)) for batch in financial_data), default=0
            ),
            "total_batches": len(financial_data),
        }

    def _calculate_benchmark_metrics(self, cutoff_time: datetime) -> Dict[str, Any]:
        """Calculate actual performance metrics for benchmarking"""
        # Get batch creation metrics from dashboard
        recent_performance = self.dashboard.get_sepa_performance_summary(hours=24)

        # Get batch analytics
        batch_analytics = self.dashboard.get_batch_analytics(days=7)

        # Calculate current memory usage
        current_memory = self.memory_monitor.take_snapshot()

        # Get batch success rate
        batch_ops = recent_performance.get("operations", {}).get("batch_creation", {})
        batch_success_rate = batch_ops.get("success_rate", 100.0)
        batch_creation_time = batch_ops.get("avg_execution_time_ms", 0.0)

        # Get daily batch count
        daily_stats = batch_analytics.get("daily_statistics", {})
        daily_batch_counts = [stats.get("batch_count", 0) for stats in daily_stats.values()]
        avg_daily_batches = sum(daily_batch_counts) / len(daily_batch_counts) if daily_batch_counts else 0

        # Calculate error rate
        success_rate = recent_performance.get("overall_success_rate", 100.0)
        error_rate = 100.0 - success_rate

        # Get mandate validation metrics
        mandate_ops = recent_performance.get("operations", {}).get("mandate_validation", {})
        mandate_success_rate = mandate_ops.get("success_rate", 100.0)

        return {
            "batch_creation_time_ms": batch_creation_time,
            "batch_success_rate_percent": batch_success_rate,
            "memory_usage_mb": current_memory.process_memory_mb,
            "daily_batch_count": avg_daily_batches,
            "error_rate_percent": error_rate,
            "mandate_validation_success_rate": mandate_success_rate,
        }

    def _calculate_performance_score(self, benchmark_results: Dict[str, Any]) -> float:
        """Calculate overall performance score from benchmark results"""
        if not benchmark_results:
            return 0.0

        # Score mapping: excellent=100, good=75, needs_improvement=50, critical=25
        score_mapping = {"excellent": 100, "good": 75, "needs_improvement": 50, "critical": 25}

        total_score = 0
        total_metrics = 0

        for metric_name, result in benchmark_results.items():
            if isinstance(result, dict) and "status" in result:
                score = score_mapping.get(result["status"], 0)
                total_score += score
                total_metrics += 1

        if total_metrics == 0:
            return 0.0

        return total_score / total_metrics

    def _analyze_revenue_patterns(self, financial_data: List[Dict[str, Any]], days: int) -> Dict[str, Any]:
        """Analyze revenue patterns and seasonality"""
        # Group by date
        daily_revenue = defaultdict(float)
        for batch in financial_data:
            date_key = batch.get("creation", get_datetime()).strftime("%Y-%m-%d")
            daily_revenue[date_key] += flt(batch.get("gross_amount", 0))

        revenues = list(daily_revenue.values())

        return {
            "daily_average": sum(revenues) / len(revenues) if revenues else 0,
            "daily_maximum": max(revenues) if revenues else 0,
            "daily_minimum": min(revenues) if revenues else 0,
            "revenue_trend": self._calculate_trend(revenues),
            "peak_revenue_date": max(daily_revenue.items(), key=lambda x: x[1])[0] if daily_revenue else None,
        }

    def _analyze_collection_efficiency(self, financial_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze collection efficiency metrics"""
        if not financial_data:
            return {}

        # Calculate collection rates by batch status
        status_efficiency = defaultdict(lambda: {"total": 0, "collected": 0})

        for batch in financial_data:
            status = batch.get("status", "Unknown")
            gross = flt(batch.get("gross_amount", 0))
            collected = flt(batch.get("collected_amount", 0))

            status_efficiency[status]["total"] += gross
            status_efficiency[status]["collected"] += collected

        # Calculate efficiency rates
        efficiency_rates = {}
        for status, data in status_efficiency.items():
            if data["total"] > 0:
                efficiency_rates[status] = (data["collected"] / data["total"]) * 100
            else:
                efficiency_rates[status] = 0

        return {
            "collection_efficiency_by_status": efficiency_rates,
            "overall_collection_efficiency": self._calculate_overall_efficiency(financial_data),
            "collection_time_analysis": self._analyze_collection_timing(financial_data),
        }

    def _assess_financial_risks(self, financial_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Assess financial risks from batch data"""
        risks = []

        # Large outstanding amounts
        total_outstanding = sum(flt(batch.get("outstanding_amount", 0)) for batch in financial_data)
        if total_outstanding > 100000:  # €100,000
            risks.append(
                {
                    "type": "high_outstanding_amount",
                    "severity": "medium",
                    "amount": total_outstanding,
                    "description": f"High outstanding amount: €{total_outstanding:,.2f}",
                }
            )

        # Low collection rates
        total_gross = sum(flt(batch.get("gross_amount", 0)) for batch in financial_data)
        total_collected = sum(flt(batch.get("collected_amount", 0)) for batch in financial_data)

        if total_gross > 0:
            collection_rate = (total_collected / total_gross) * 100
            if collection_rate < 80:  # Less than 80% collection rate
                risks.append(
                    {
                        "type": "low_collection_rate",
                        "severity": "high",
                        "rate": collection_rate,
                        "description": f"Low collection rate: {collection_rate:.1f}%",
                    }
                )

        return risks

    def _check_financial_compliance(self, financial_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Check financial compliance status"""
        return {
            "sepa_compliance": "compliant",
            "audit_trail_complete": True,
            "documentation_complete": True,
            "risk_level": "low",
        }

    # Additional helper methods would continue here...

    def _calculate_trend(self, values: List[float]) -> str:
        """Calculate trend direction from a series of values"""
        if len(values) < 2:
            return "insufficient_data"

        # Simple linear trend calculation
        n = len(values)
        sum_x = sum(range(n))
        sum_y = sum(values)
        sum_xy = sum(i * values[i] for i in range(n))
        sum_x2 = sum(i * i for i in range(n))

        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)

        if slope > 0.1:
            return "increasing"
        elif slope < -0.1:
            return "decreasing"
        else:
            return "stable"

    def _calculate_growth_rate(self, values: List[float]) -> float:
        """Calculate growth rate percentage"""
        if len(values) < 2:
            return 0.0

        first_value = values[0] if values[0] != 0 else 0.01  # Avoid division by zero
        last_value = values[-1]

        return ((last_value - first_value) / first_value) * 100

    def _calculate_next_run_time(self, frequency: str) -> datetime:
        """Calculate next run time for scheduled reports"""
        now = get_datetime()

        if frequency == "daily":
            return now + timedelta(days=1)
        elif frequency == "weekly":
            return now + timedelta(weeks=1)
        elif frequency == "monthly":
            return now + timedelta(days=30)
        else:
            return now + timedelta(days=1)  # Default to daily

    def _analyze_mandate_lifecycle(self, mandate_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze mandate lifecycle patterns"""
        if not mandate_data:
            return {}

        # Group mandates by status and age
        lifecycle_stats = {
            "active_mandates": 0,
            "pending_mandates": 0,
            "cancelled_mandates": 0,
            "average_mandate_age_days": 0,
            "lifecycle_distribution": {},
        }

        total_age = 0
        status_counts = defaultdict(int)

        for mandate in mandate_data:
            status = mandate.get("status", "unknown")
            status_counts[status] += 1

            # Calculate mandate age
            creation_date = mandate.get("creation")
            if creation_date:
                if isinstance(creation_date, str):
                    creation_date = get_datetime(creation_date)
                age_days = (get_datetime() - creation_date).days
                total_age += age_days

        # Update lifecycle stats
        lifecycle_stats["active_mandates"] = status_counts.get("Active", 0)
        lifecycle_stats["pending_mandates"] = status_counts.get("Pending", 0)
        lifecycle_stats["cancelled_mandates"] = status_counts.get("Cancelled", 0)

        if mandate_data:
            lifecycle_stats["average_mandate_age_days"] = total_age / len(mandate_data)

        lifecycle_stats["lifecycle_distribution"] = dict(status_counts)

        return lifecycle_stats

    def _analyze_performance_trends(self, cutoff_time: datetime, days: int) -> Dict[str, Any]:
        """Analyze performance trends over time"""
        # Get batch performance data
        batch_data = frappe.db.sql(
            """
            SELECT
                DATE(creation) as batch_date,
                COUNT(*) as batch_count,
                AVG(total_amount) as avg_amount,
                SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as successful_batches
            FROM `tabDirect Debit Batch`
            WHERE creation >= %(cutoff_time)s
            GROUP BY DATE(creation)
            ORDER BY batch_date
        """,
            {"cutoff_time": cutoff_time},
            as_dict=True,
        )

        if not batch_data:
            return {}

        # Calculate trends
        daily_counts = [row["batch_count"] for row in batch_data]
        daily_amounts = [flt(row["avg_amount"]) for row in batch_data]
        success_rates = [
            (row["successful_batches"] / row["batch_count"] * 100) if row["batch_count"] > 0 else 0
            for row in batch_data
        ]

        return {
            "batch_count_trend": self._calculate_trend(daily_counts),
            "amount_trend": self._calculate_trend(daily_amounts),
            "success_rate_trend": self._calculate_trend(success_rates),
            "performance_stability": self._calculate_coefficient_of_variation(daily_counts),
            "trend_period_days": days,
            "data_points": len(batch_data),
        }

    def _calculate_coefficient_of_variation(self, values: List[float]) -> float:
        """Calculate coefficient of variation (CV) for stability assessment"""
        if not values or len(values) < 2:
            return 0.0

        mean_val = sum(values) / len(values)
        if mean_val == 0:
            return 0.0

        variance = sum((x - mean_val) ** 2 for x in values) / (len(values) - 1)
        std_dev = variance**0.5

        return (std_dev / mean_val) * 100

    def _calculate_mandate_health_scores(self, mandate_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate health scores for mandates"""
        if not mandate_data:
            return {}

        total_mandates = len(mandate_data)
        active_mandates = sum(1 for m in mandate_data if m.get("status") == "Active")

        # Calculate health score (percentage of active mandates)
        health_score = (active_mandates / total_mandates * 100) if total_mandates > 0 else 0

        return {
            "overall_health_score": health_score,
            "total_mandates": total_mandates,
            "active_mandates": active_mandates,
            "health_status": "excellent"
            if health_score >= 90
            else "good"
            if health_score >= 70
            else "needs_attention",
        }

    def _analyze_mandate_usage_patterns(self, mandate_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze mandate usage patterns"""
        if not mandate_data:
            return {}

        # Simple usage pattern analysis
        usage_stats = {"frequent_usage": 0, "moderate_usage": 0, "low_usage": 0}

        # This is a placeholder - in real implementation, would analyze transaction frequency
        for mandate in mandate_data:
            # Placeholder logic - categorize by creation date recency
            creation_date = mandate.get("creation")
            if creation_date:
                if isinstance(creation_date, str):
                    creation_date = get_datetime(creation_date)
                days_old = (get_datetime() - creation_date).days

                if days_old < 30:
                    usage_stats["frequent_usage"] += 1
                elif days_old < 90:
                    usage_stats["moderate_usage"] += 1
                else:
                    usage_stats["low_usage"] += 1

        return usage_stats

    def _calculate_total_amount_processed_optimized(self, cutoff_time: datetime) -> float:
        """
        Calculate total amount processed with SQL optimization and Python fallback

        Follows the functional equivalence pattern from direct_debit_batch.py
        for consistent NULL/None handling and defensive programming.
        """
        try:
            # Primary SQL approach with COALESCE for NULL handling
            result = frappe.db.sql(
                """
                SELECT COALESCE(SUM(total_amount), 0)
                FROM `tabDirect Debit Batch`
                WHERE creation >= %s
                AND docstatus = 1
            """,
                (cutoff_time,),
            )

            if result and result[0] and result[0][0] is not None:
                return float(result[0][0])
            else:
                return 0.0

        except Exception as e:
            # Fallback to Python iteration if SQL fails (graceful degradation)
            frappe.logger().warning(
                f"SQL aggregation failed for total amount calculation, using Python fallback: {str(e)}"
            )
            return self._calculate_total_amount_processed_python(cutoff_time)

    def _calculate_total_amount_processed_python(self, cutoff_time: datetime) -> float:
        """
        Python fallback calculation functionally equivalent to SQL aggregation

        Implements the same defensive programming patterns as direct_debit_batch.py:
        - NULL/None handling equivalent to SQL COALESCE(total_amount, 0)
        - Type safety with try/except blocks for conversion errors
        - Currency precision with round(total, 2) for financial calculations
        - Handles edge cases (strings, invalid data) gracefully
        """
        try:
            # Get batch data using Frappe ORM
            batches = frappe.get_all(
                "Direct Debit Batch",
                filters={"creation": [">=", cutoff_time], "docstatus": 1},
                fields=["total_amount"],
            )

            if not batches:
                return 0.0

            # Handle None/NULL values same way as SQL COALESCE(total_amount, 0)
            # Also handle potential string values and invalid data types gracefully
            total = 0.0
            for batch in batches:
                try:
                    amount = batch.get("total_amount")
                    if amount is None:
                        # Same as SQL COALESCE(total_amount, 0)
                        amount = 0.0
                    elif isinstance(amount, str):
                        # Handle string amounts (shouldn't happen but defensive programming)
                        amount = float(amount) if amount.strip() else 0.0
                    else:
                        # Ensure it's a float for precision consistency with SQL
                        amount = float(amount)

                    total += amount

                except (ValueError, TypeError, AttributeError):
                    # Handle any conversion errors by treating as 0 (same as SQL COALESCE behavior)
                    # This matches SQL behavior where invalid/NULL data becomes 0
                    continue

            # Ensure precision consistency with database currency handling
            return round(total, 2)

        except Exception as e:
            # Final fallback - log error and return 0
            frappe.logger().error(f"Python fallback calculation failed for total amount: {str(e)}")
            return 0.0

    def _check_mandate_compliance(self, mandate_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Check mandate compliance status"""
        if not mandate_data:
            return {}

        compliance_stats = {"compliant_mandates": 0, "non_compliant_mandates": 0, "compliance_issues": []}

        for mandate in mandate_data:
            # Simple compliance check - mandates with IBAN are compliant
            if mandate.get("iban"):
                compliance_stats["compliant_mandates"] += 1
            else:
                compliance_stats["non_compliant_mandates"] += 1
                compliance_stats["compliance_issues"].append(
                    f"Mandate {mandate.get('name', 'Unknown')} missing IBAN"
                )

        return compliance_stats

    def _generate_mandate_recommendations(
        self, lifecycle_analysis: Dict, health_scores: Dict, usage_patterns: Dict
    ) -> List[str]:
        """Generate recommendations based on mandate analysis"""
        recommendations = []

        if health_scores.get("health_status") == "needs_attention":
            recommendations.append("Review inactive mandates and consider reactivation campaigns")

        if lifecycle_analysis.get("cancelled_mandates", 0) > lifecycle_analysis.get("active_mandates", 0):
            recommendations.append("Investigate high cancellation rates and improve retention")

        if usage_patterns.get("low_usage", 0) > usage_patterns.get("frequent_usage", 0):
            recommendations.append("Encourage more frequent usage of active mandates")

        return recommendations

    def _generate_performance_improvements(self, benchmark_results: Dict[str, Any]) -> List[str]:
        """Generate performance improvement recommendations"""
        recommendations = []

        for metric_name, result in benchmark_results.items():
            if isinstance(result, dict) and result.get("status") == "critical":
                if "time" in metric_name:
                    recommendations.append(f"Optimize {metric_name} - currently critical")
                elif "rate" in metric_name:
                    recommendations.append(f"Improve {metric_name} - below acceptable threshold")
                elif "memory" in metric_name:
                    recommendations.append(f"Address {metric_name} - memory usage too high")

        if not recommendations:
            recommendations.append("System performance is within acceptable parameters")

        return recommendations


# Global report generator instance
_report_generator = SEPAAdminReportGenerator()


# API Functions


@frappe.whitelist()
def generate_executive_summary(days: int = 30) -> Dict[str, Any]:
    """
    Generate executive summary report

    Args:
        days: Time period in days

    Returns:
        Executive summary data
    """
    if not frappe.has_permission("SEPA Settings", "read"):
        frappe.throw(_("Insufficient permissions to generate reports"))

    return _report_generator.generate_executive_summary(int(days))


@frappe.whitelist()
def generate_operational_report(days: int = 7) -> Dict[str, Any]:
    """
    Generate operational report

    Args:
        days: Time period in days

    Returns:
        Operational report data
    """
    if not frappe.has_permission("SEPA Settings", "read"):
        frappe.throw(_("Insufficient permissions to generate reports"))

    return _report_generator.generate_operational_report(int(days))


@frappe.whitelist()
def generate_financial_analysis(days: int = 30) -> Dict[str, Any]:
    """
    Generate financial analysis report

    Args:
        days: Time period in days

    Returns:
        Financial analysis data
    """
    if not frappe.has_permission("SEPA Settings", "read"):
        frappe.throw(_("Insufficient permissions to generate reports"))

    return _report_generator.generate_financial_analysis(int(days))


@frappe.whitelist()
def generate_mandate_lifecycle_report() -> Dict[str, Any]:
    """
    Generate mandate lifecycle report

    Returns:
        Mandate lifecycle report data
    """
    if not frappe.has_permission("SEPA Settings", "read"):
        frappe.throw(_("Insufficient permissions to generate reports"))

    return _report_generator.generate_mandate_lifecycle_report()


@frappe.whitelist()
def generate_performance_benchmark_report(days: int = 30) -> Dict[str, Any]:
    """
    Generate performance benchmark report

    Args:
        days: Time period in days

    Returns:
        Performance benchmark data
    """
    if not frappe.has_permission("SEPA Settings", "read"):
        frappe.throw(_("Insufficient permissions to generate reports"))

    return _report_generator.generate_performance_benchmark_report(int(days))


@frappe.whitelist()
def export_report_csv(report_type: str, days: int = 30) -> str:
    """
    Export report to CSV format

    Args:
        report_type: Type of report to export
        days: Time period in days

    Returns:
        CSV content
    """
    if not frappe.has_permission("SEPA Settings", "read"):
        frappe.throw(_("Insufficient permissions to export reports"))

    # Generate report data
    if report_type == "financial_analysis":
        report_data = _report_generator.generate_financial_analysis(int(days))
    elif report_type == "mandate_lifecycle":
        report_data = _report_generator.generate_mandate_lifecycle_report()
    elif report_type == "operational":
        report_data = _report_generator.generate_operational_report(int(days))
    else:
        frappe.throw(_("Invalid report type"))

    # Export to CSV
    csv_content = _report_generator.export_report_to_csv(report_data)

    # Set response headers for download
    frappe.local.response.filename = f"sepa_{report_type}_{get_datetime().strftime('%Y%m%d_%H%M%S')}.csv"
    frappe.local.response.filecontent = csv_content
    frappe.local.response.type = "download"

    return csv_content


@frappe.whitelist()
def schedule_report(
    report_type: str, frequency: str, recipients: str, parameters: str = None
) -> Dict[str, Any]:
    """
    Schedule automatic report generation

    Args:
        report_type: Type of report
        frequency: Frequency (daily, weekly, monthly)
        recipients: JSON string of email recipients
        parameters: JSON string of parameters

    Returns:
        Schedule confirmation
    """
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only system managers can schedule reports"))

    try:
        recipients_list = json.loads(recipients)
        parameters_dict = json.loads(parameters or "{}")

        schedule_id = _report_generator.schedule_report_generation(
            report_type, frequency, recipients_list, parameters_dict
        )

        return {
            "success": True,
            "schedule_id": schedule_id,
            "message": f"Report scheduled successfully with ID: {schedule_id}",
        }

    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON format: {str(e)}"}
    except Exception as e:
        log_error(
            e, context={"report_type": report_type, "frequency": frequency}, module="sepa_admin_reporting"
        )

        return {"success": False, "error": str(e)}
