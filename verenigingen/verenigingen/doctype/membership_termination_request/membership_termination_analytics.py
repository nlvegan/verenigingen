# Predictive Analytics and Trend Analysis for Membership Terminations
# Add to membership_termination_request.py or create as separate analytics module

import statistics
from collections import defaultdict
from datetime import datetime

import frappe
from frappe.utils import add_days, add_months, date_diff, getdate, now, today


@frappe.whitelist()
def get_termination_trends(period="12_months"):
    """Get comprehensive termination trends and patterns"""

    # Calculate date range
    end_date = getdate(today())
    if period == "6_months":
        start_date = add_months(end_date, -6)
    elif period == "2_years":
        start_date = add_months(end_date, -24)
    else:  # 12_months default
        start_date = add_months(end_date, -12)

    # Get termination data
    terminations = frappe.db.sql(
        """
        SELECT
            name,
            member,
            member_name,
            termination_type,
            status,
            request_date,
            execution_date,
            requested_by,
            sepa_mandates_cancelled,
            positions_ended
        FROM `tabMembership Termination Request`
        WHERE request_date >= %s AND request_date <= %s
        ORDER BY request_date DESC
    """,
        (start_date, end_date),
        as_dict=True,
    )

    # Analyze trends
    trends = {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "total_terminations": len(terminations),
        "monthly_breakdown": analyze_monthly_breakdown(terminations, start_date, end_date),
        "type_trends": analyze_type_trends(terminations),
        "chapter_analysis": analyze_chapter_patterns(terminations),
        "processing_efficiency": analyze_processing_efficiency(terminations),
        "risk_indicators": identify_risk_indicators(terminations),
        "predictions": generate_predictions(terminations),
        "seasonal_patterns": identify_seasonal_patterns(terminations),
    }

    return trends


def analyze_monthly_breakdown(terminations, start_date, end_date):
    """Analyze terminations by month"""
    monthly_data = defaultdict(
        lambda: {"total": 0, "voluntary": 0, "non_payment": 0, "disciplinary": 0, "executed": 0}
    )

    disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]

    for termination in terminations:
        request_date = getdate(termination.request_date)
        month_key = request_date.strftime("%Y-%m")

        monthly_data[month_key]["total"] += 1

        if termination.termination_type == "Voluntary":
            monthly_data[month_key]["voluntary"] += 1
        elif termination.termination_type == "Non-payment":
            monthly_data[month_key]["non_payment"] += 1
        elif termination.termination_type in disciplinary_types:
            monthly_data[month_key]["disciplinary"] += 1

        if termination.status == "Executed":
            monthly_data[month_key]["executed"] += 1

    # Fill in missing months with zeros
    current_date = start_date
    while current_date <= end_date:
        month_key = current_date.strftime("%Y-%m")
        if month_key not in monthly_data:
            monthly_data[month_key] = {
                "total": 0,
                "voluntary": 0,
                "non_payment": 0,
                "disciplinary": 0,
                "executed": 0,
            }
        current_date = add_months(current_date, 1)

    return dict(sorted(monthly_data.items()))


def analyze_type_trends(terminations):
    """Analyze trends by termination type"""
    type_data = defaultdict(list)

    # Group by month and type
    for termination in terminations:
        month = getdate(termination.request_date).strftime("%Y-%m")
        type_data[termination.termination_type].append(month)

    # Calculate trends for each type
    type_trends = {}
    for term_type, months in type_data.items():
        month_counts = defaultdict(int)
        for month in months:
            month_counts[month] += 1

        # Calculate trend (simple linear regression)
        if len(month_counts) >= 3:
            values = list(month_counts.values())
            trend = calculate_trend(values)
            type_trends[term_type] = {
                "count": len(months),
                "trend": trend,
                "recent_average": statistics.mean(values[-3:])
                if len(values) >= 3
                else statistics.mean(values),
                "monthly_distribution": dict(month_counts),
            }

    return type_trends


def analyze_chapter_patterns(terminations):
    """Analyze patterns by chapter and initiator"""

    # Get chapter data for terminations
    chapter_analysis = defaultdict(
        lambda: {"total": 0, "disciplinary": 0, "voluntary": 0, "by_requester": defaultdict(int)}
    )

    disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]

    for termination in terminations:
        # Get member's chapter
        try:
            member_chapter = frappe.db.get_value("Member", termination.member, "primary_chapter")
            if member_chapter:
                chapter_key = member_chapter
            else:
                chapter_key = "No Chapter"

            chapter_analysis[chapter_key]["total"] += 1
            chapter_analysis[chapter_key]["by_requester"][termination.requested_by] += 1

            if termination.termination_type in disciplinary_types:
                chapter_analysis[chapter_key]["disciplinary"] += 1
            elif termination.termination_type == "Voluntary":
                chapter_analysis[chapter_key]["voluntary"] += 1

        except Exception:
            # Handle cases where member might not exist
            continue

    # Calculate risk scores for chapters
    for chapter, data in chapter_analysis.items():
        if data["total"] > 0:
            data["disciplinary_rate"] = (data["disciplinary"] / data["total"]) * 100
            data["risk_score"] = calculate_chapter_risk_score(data)

    return dict(chapter_analysis)


def calculate_chapter_risk_score(chapter_data):
    """Calculate risk score for a chapter based on termination patterns"""
    risk_score = 0

    # High disciplinary rate increases risk
    if chapter_data["disciplinary_rate"] > 50:
        risk_score += 30
    elif chapter_data["disciplinary_rate"] > 25:
        risk_score += 15

    # High volume of terminations increases risk
    if chapter_data["total"] > 10:
        risk_score += 20
    elif chapter_data["total"] > 5:
        risk_score += 10

    # Single requester doing many terminations increases risk
    max_by_requester = max(chapter_data["by_requester"].values()) if chapter_data["by_requester"] else 0
    if max_by_requester > chapter_data["total"] * 0.7:  # One person doing >70% of terminations
        risk_score += 25

    return min(risk_score, 100)


def analyze_processing_efficiency(terminations):
    """Analyze processing time efficiency"""
    processing_times = []
    status_distribution = defaultdict(int)

    for termination in terminations:
        status_distribution[termination.status] += 1

        if termination.execution_date and termination.request_date:
            days = date_diff(termination.execution_date, termination.request_date)
            processing_times.append(days)

    efficiency_metrics = {
        "status_distribution": dict(status_distribution),
        "avg_processing_time": statistics.mean(processing_times) if processing_times else 0,
        "median_processing_time": statistics.median(processing_times) if processing_times else 0,
        "processing_time_trend": calculate_processing_time_trend(terminations),
        "efficiency_score": calculate_efficiency_score(status_distribution, processing_times),
    }

    return efficiency_metrics


def calculate_processing_time_trend(terminations):
    """Calculate trend in processing times over the period"""
    monthly_processing = defaultdict(list)

    for termination in terminations:
        if termination.execution_date and termination.request_date:
            month = getdate(termination.request_date).strftime("%Y-%m")
            days = date_diff(termination.execution_date, termination.request_date)
            monthly_processing[month].append(days)

    # Calculate average processing time per month
    monthly_averages = {}
    for month, times in monthly_processing.items():
        monthly_averages[month] = statistics.mean(times)

    # Calculate trend
    if len(monthly_averages) >= 3:
        values = list(monthly_averages.values())
        trend = calculate_trend(values)
        return {
            "trend": trend,
            "monthly_averages": monthly_averages,
            "improvement": trend < -0.5,  # Negative trend means improving (shorter times)
        }

    return {"trend": 0, "monthly_averages": monthly_averages, "improvement": False}


def calculate_efficiency_score(status_distribution, processing_times):
    """Calculate overall efficiency score"""
    score = 100

    total = sum(status_distribution.values())
    if total == 0:
        return 0

    # Reduce score for high percentage of pending/draft items
    pending_rate = (
        status_distribution.get("Draft", 0)
        + status_distribution.get("Pending", 0)
        + status_distribution.get("Approved", 0)
    ) / total

    score -= pending_rate * 30

    # Reduce score for slow processing times
    if processing_times:
        avg_time = statistics.mean(processing_times)
        if avg_time > 30:  # More than 30 days
            score -= 25
        elif avg_time > 14:  # More than 14 days
            score -= 15

    return max(score, 0)


def identify_risk_indicators(terminations):
    """Identify potential risk indicators and warning signs"""

    risk_indicators = {
        "high_disciplinary_rate": False,
        "processing_delays": False,
        "concentrated_requesters": False,
        "unusual_patterns": [],
        "risk_level": "LOW",
    }

    total_terminations = len(terminations)
    if total_terminations == 0:
        return risk_indicators

    # Check disciplinary rate
    disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]
    disciplinary_count = len([t for t in terminations if t.termination_type in disciplinary_types])
    disciplinary_rate = (disciplinary_count / total_terminations) * 100

    if disciplinary_rate > 30:
        risk_indicators["high_disciplinary_rate"] = True
        risk_indicators["unusual_patterns"].append(f"High disciplinary rate: {disciplinary_rate:.1f}%")

    # Check for processing delays
    pending_count = len([t for t in terminations if t.status in ["Draft", "Pending", "Approved"]])
    if pending_count > total_terminations * 0.4:  # More than 40% pending
        risk_indicators["processing_delays"] = True
        risk_indicators["unusual_patterns"].append(
            f"High pending rate: {(pending_count / total_terminations) * 100:.1f}%"
        )

    # Check for concentrated requesters
    requester_counts = defaultdict(int)
    for termination in terminations:
        requester_counts[termination.requested_by] += 1

    max_requests = max(requester_counts.values()) if requester_counts else 0
    if max_requests > total_terminations * 0.6:  # One person doing >60% of terminations
        risk_indicators["concentrated_requesters"] = True
        risk_indicators["unusual_patterns"].append(
            f"Single requester responsible for {(max_requests / total_terminations) * 100:.1f}% of terminations"
        )

    # Calculate overall risk level
    risk_score = 0
    if risk_indicators["high_disciplinary_rate"]:
        risk_score += 40
    if risk_indicators["processing_delays"]:
        risk_score += 30
    if risk_indicators["concentrated_requesters"]:
        risk_score += 30

    if risk_score >= 70:
        risk_indicators["risk_level"] = "HIGH"
    elif risk_score >= 40:
        risk_indicators["risk_level"] = "MEDIUM"

    return risk_indicators


def generate_predictions(terminations):
    """Generate predictions for next period"""
    if len(terminations) < 6:  # Need minimum data for predictions
        return {"insufficient_data": True}

    # Group by month
    monthly_counts = defaultdict(int)
    for termination in terminations:
        month = getdate(termination.request_date).strftime("%Y-%m")
        monthly_counts[month] += 1

    # Get recent 6 months for trend calculation
    recent_months = sorted(monthly_counts.keys())[-6:]
    recent_counts = [monthly_counts[month] for month in recent_months]

    # Simple linear prediction
    if len(recent_counts) >= 3:
        trend = calculate_trend(recent_counts)
        last_count = recent_counts[-1]

        # Predict next month
        next_month_prediction = max(0, round(last_count + trend))

        # Predict next quarter
        next_quarter_prediction = max(0, round((last_count + trend) * 3))

        predictions = {
            "next_month": next_month_prediction,
            "next_quarter": next_quarter_prediction,
            "trend": "increasing" if trend > 0.5 else "decreasing" if trend < -0.5 else "stable",
            "confidence": calculate_prediction_confidence(recent_counts),
        }

        return predictions

    return {"insufficient_data": True}


def identify_seasonal_patterns(terminations):
    """Identify seasonal patterns in terminations"""

    monthly_patterns = defaultdict(list)

    for termination in terminations:
        month_num = getdate(termination.request_date).month
        monthly_patterns[month_num].append(termination)

    # Calculate average by month
    seasonal_data = {}
    for month in range(1, 13):
        month_name = datetime(2024, month, 1).strftime("%B")
        count = len(monthly_patterns[month])
        seasonal_data[month_name] = {
            "count": count,
            "avg_per_year": count / 2 if len(terminations) > 365 else count,  # Rough approximation
            "disciplinary_rate": len(
                [
                    t
                    for t in monthly_patterns[month]
                    if t.termination_type in ["Policy Violation", "Disciplinary Action", "Expulsion"]
                ]
            )
            / max(count, 1)
            * 100,
        }

    # Identify peak months
    counts_by_month = {month: data["count"] for month, data in seasonal_data.items()}
    if counts_by_month:
        peak_month = max(counts_by_month.keys(), key=lambda x: counts_by_month[x])
        low_month = min(counts_by_month.keys(), key=lambda x: counts_by_month[x])

        return {
            "monthly_data": seasonal_data,
            "peak_month": peak_month,
            "low_month": low_month,
            "has_seasonal_pattern": max(counts_by_month.values()) > min(counts_by_month.values()) * 2,
        }

    return {"monthly_data": seasonal_data}


def calculate_trend(values):
    """Calculate simple linear trend"""
    if len(values) < 2:
        return 0

    n = len(values)
    x_values = list(range(n))

    # Simple linear regression
    x_mean = statistics.mean(x_values)
    y_mean = statistics.mean(values)

    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, values))
    denominator = sum((x - x_mean) ** 2 for x in x_values)

    if denominator == 0:
        return 0

    return numerator / denominator


def calculate_prediction_confidence(recent_counts):
    """Calculate confidence level for predictions"""
    if len(recent_counts) < 3:
        return "LOW"

    # Calculate variance
    variance = statistics.variance(recent_counts)
    mean_val = statistics.mean(recent_counts)

    # Coefficient of variation
    cv = (variance**0.5) / mean_val if mean_val > 0 else float("inf")

    if cv < 0.3:
        return "HIGH"
    elif cv < 0.6:
        return "MEDIUM"
    else:
        return "LOW"


@frappe.whitelist()
def get_early_warning_system():
    """Get early warning indicators for potential issues"""

    warnings = {"critical": [], "warning": [], "info": [], "last_updated": now()}

    # Appeals system has been removed
    overdue_appeals = []

    if len(overdue_appeals) > 0:
        warnings["critical"].append(
            {
                "type": "overdue_appeals",
                "message": f"{len(overdue_appeals)} appeal(s) are past their review deadline",
                "count": len(overdue_appeals),
                "details": overdue_appeals,
            }
        )

    # Check for high pending approvals
    pending_count = frappe.db.count("Membership Termination Request", {"status": "Pending"})

    if pending_count > 10:
        warnings["critical"].append(
            {
                "type": "high_pending_approvals",
                "message": f"{pending_count} termination requests are pending approval",
                "count": pending_count,
            }
        )
    elif pending_count > 5:
        warnings["warning"].append(
            {
                "type": "moderate_pending_approvals",
                "message": f"{pending_count} termination requests are pending approval",
                "count": pending_count,
            }
        )

    # Check for unusual patterns in last 30 days
    recent_terminations = frappe.get_all(
        "Membership Termination Request",
        filters={"request_date": [">=", add_days(today(), -30)]},
        fields=["termination_type", "requested_by"],
    )

    if len(recent_terminations) > 0:
        # Check disciplinary rate
        disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]
        disciplinary_count = len([t for t in recent_terminations if t.termination_type in disciplinary_types])
        disciplinary_rate = (disciplinary_count / len(recent_terminations)) * 100

        if disciplinary_rate > 40:
            warnings["warning"].append(
                {
                    "type": "high_disciplinary_rate",
                    "message": f"High disciplinary termination rate: {disciplinary_rate:.1f}% in last 30 days",
                    "rate": disciplinary_rate,
                }
            )

        # Check for concentrated requesters
        requester_counts = defaultdict(int)
        for termination in recent_terminations:
            requester_counts[termination.requested_by] += 1

        max_requests = max(requester_counts.values()) if requester_counts else 0
        if max_requests > len(recent_terminations) * 0.7:
            top_requester = max(requester_counts.keys(), key=lambda x: requester_counts[x])
            warnings["warning"].append(
                {
                    "type": "concentrated_requester",
                    "message": f"Single user ({top_requester}) initiated {max_requests} of {len(recent_terminations)} recent terminations",
                    "requester": top_requester,
                    "count": max_requests,
                }
            )

    # Check system health indicators
    system_health = check_system_health()
    if system_health["issues"]:
        for issue in system_health["issues"]:
            warnings[issue["severity"]].append(issue)

    return warnings


def check_system_health():
    """Check overall system health indicators"""

    health = {"status": "healthy", "issues": []}

    # Check for stalled processes (requests older than 90 days still pending)
    stalled_requests = frappe.db.count(
        "Membership Termination Request",
        {"status": ["in", ["Draft", "Pending", "Approved"]], "request_date": ["<", add_days(today(), -90)]},
    )

    if stalled_requests > 0:
        health["issues"].append(
            {
                "type": "stalled_processes",
                "severity": "warning",
                "message": f"{stalled_requests} termination request(s) have been pending for over 90 days",
                "count": stalled_requests,
            }
        )

    # Check for missing documentation in disciplinary cases
    disciplinary_without_docs = frappe.db.count(
        "Membership Termination Request",
        {
            "termination_type": ["in", ["Policy Violation", "Disciplinary Action", "Expulsion"]],
            "disciplinary_documentation": ["in", ["", None]],
        },
    )

    if disciplinary_without_docs > 0:
        health["issues"].append(
            {
                "type": "missing_documentation",
                "severity": "warning",
                "message": f"{disciplinary_without_docs} disciplinary termination(s) lack required documentation",
                "count": disciplinary_without_docs,
            }
        )

    # Set overall health status
    if len([i for i in health["issues"] if i["severity"] == "critical"]) > 0:
        health["status"] = "critical"
    elif len([i for i in health["issues"] if i["severity"] == "warning"]) > 0:
        health["status"] = "warning"

    return health


@frappe.whitelist()
def generate_executive_summary():
    """Generate executive summary for leadership"""

    # Get data for last quarter
    end_date = getdate(today())
    start_date = add_months(end_date, -3)

    terminations = frappe.get_all(
        "Membership Termination Request",
        filters={"request_date": ["between", [start_date, end_date]]},
        fields=["termination_type", "status", "request_date", "execution_date"],
    )

    # Appeals system has been removed
    appeals = []

    summary = {
        "period": f"{start_date.strftime('%B %Y')} - {end_date.strftime('%B %Y')}",
        "total_terminations": len(terminations),
        "disciplinary_terminations": len(
            [
                t
                for t in terminations
                if t.termination_type in ["Policy Violation", "Disciplinary Action", "Expulsion"]
            ]
        ),
        "completed_terminations": len([t for t in terminations if t.status == "Executed"]),
        "pending_terminations": len(
            [t for t in terminations if t.status in ["Draft", "Pending", "Approved"]]
        ),
        "appeals_filed": len(appeals),
        "appeals_successful": len(
            [a for a in appeals if a.decision_outcome in ["Upheld", "Partially Upheld"]]
        ),
        "key_metrics": calculate_key_metrics(terminations, appeals),
        "recommendations": generate_recommendations(terminations, appeals),
    }

    return summary


def calculate_key_metrics(terminations, appeals):
    """Calculate key performance metrics"""

    metrics = {}

    # Processing efficiency
    executed_terminations = [t for t in terminations if t.status == "Executed" and t.execution_date]
    if executed_terminations:
        processing_times = [date_diff(t.execution_date, t.request_date) for t in executed_terminations]
        metrics["avg_processing_time"] = statistics.mean(processing_times)
        metrics["median_processing_time"] = statistics.median(processing_times)

    # Appeal success rate
    decided_appeals = [a for a in appeals if a.decision_outcome]
    if decided_appeals:
        successful = len([a for a in decided_appeals if a.decision_outcome in ["Upheld", "Partially Upheld"]])
        metrics["appeal_success_rate"] = (successful / len(decided_appeals)) * 100

    # Disciplinary rate
    if terminations:
        disciplinary = len(
            [
                t
                for t in terminations
                if t.termination_type in ["Policy Violation", "Disciplinary Action", "Expulsion"]
            ]
        )
        metrics["disciplinary_rate"] = (disciplinary / len(terminations)) * 100

    return metrics


def generate_recommendations(terminations, appeals):
    """Generate actionable recommendations based on data"""

    recommendations = []

    # Check processing times
    executed_terminations = [t for t in terminations if t.status == "Executed" and t.execution_date]
    if executed_terminations:
        processing_times = [date_diff(t.execution_date, t.request_date) for t in executed_terminations]
        avg_time = statistics.mean(processing_times)

        if avg_time > 30:
            recommendations.append(
                {
                    "priority": "high",
                    "category": "efficiency",
                    "recommendation": "Review approval processes to reduce average processing time",
                    "current_metric": f"{avg_time:.1f} days average",
                    "target": "< 21 days",
                }
            )

    # Check appeal rates
    if len(appeals) > len(terminations) * 0.2:  # More than 20% appeal rate
        recommendations.append(
            {
                "priority": "medium",
                "category": "quality",
                "recommendation": "Review termination decision quality - high appeal rate indicates potential issues",
                "current_metric": f"{len(appeals)}/{len(terminations)} appeals filed",
                "target": "< 15% appeal rate",
            }
        )

    # Check disciplinary rates
    if terminations:
        disciplinary = len(
            [
                t
                for t in terminations
                if t.termination_type in ["Policy Violation", "Disciplinary Action", "Expulsion"]
            ]
        )
        disciplinary_rate = (disciplinary / len(terminations)) * 100

        if disciplinary_rate > 30:
            recommendations.append(
                {
                    "priority": "high",
                    "category": "governance",
                    "recommendation": "Investigate high disciplinary termination rate - may indicate systemic issues",
                    "current_metric": f"{disciplinary_rate:.1f}% disciplinary",
                    "target": "< 25% disciplinary rate",
                }
            )

    return recommendations
