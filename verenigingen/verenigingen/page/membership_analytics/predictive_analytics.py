# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import calendar
import json
from datetime import datetime, timedelta

import frappe
import numpy as np
import pandas as pd
from frappe.utils import add_days, add_months, getdate, now_datetime
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures


@frappe.whitelist()
def get_predictive_analytics(months_ahead=12):
    """Get predictive analytics for membership trends"""
    predictions = {
        "member_growth_forecast": forecast_member_growth(months_ahead),
        "revenue_forecast": forecast_revenue(months_ahead),
        "churn_risk_analysis": analyze_churn_risk(),
        "seasonal_patterns": detect_seasonal_patterns(),
        "growth_scenarios": calculate_growth_scenarios(),
        "recommendations": generate_recommendations(),
    }

    return predictions


def forecast_member_growth(months_ahead=12):
    """Forecast member growth using historical data"""
    # Get historical member counts by month
    historical_data = frappe.db.sql(
        """
        SELECT
            DATE_FORMAT(member_since, '%%Y-%%m') as month,
            COUNT(*) as new_members
        FROM `tabMember`
        WHERE member_since >= DATE_SUB(CURDATE(), INTERVAL 36 MONTH)
        AND status != 'Rejected'
        GROUP BY month
        ORDER BY month
    """,
        as_dict=True,
    )

    if len(historical_data) < 12:
        return {"error": "Insufficient historical data for forecasting"}

    # Prepare data for regression
    months = []
    member_counts = []
    cumulative_count = get_initial_member_count()

    for i, data in enumerate(historical_data):
        months.append(i)
        cumulative_count += data.new_members
        member_counts.append(cumulative_count)

    # Convert to numpy arrays
    X = np.array(months).reshape(-1, 1)
    y = np.array(member_counts)

    # Try polynomial regression for better fit
    poly = PolynomialFeatures(degree=2)
    X_poly = poly.fit_transform(X)

    model = LinearRegression()
    model.fit(X_poly, y)

    # Generate forecast
    forecast_months = []
    forecast_values = []
    confidence_intervals = []

    last_month_idx = len(months) - 1

    for i in range(1, months_ahead + 1):
        month_idx = last_month_idx + i
        X_pred = poly.transform([[month_idx]])
        prediction = model.predict(X_pred)[0]

        # Calculate confidence interval (simplified)
        std_dev = np.std(y) * (1 + 0.05 * i)  # Increasing uncertainty

        forecast_months.append(add_months(datetime.now(), i).strftime("%B %Y"))
        forecast_values.append(max(0, int(prediction)))
        confidence_intervals.append(
            {"lower": max(0, int(prediction - 1.96 * std_dev)), "upper": int(prediction + 1.96 * std_dev)}
        )

    # Calculate growth metrics
    current_members = member_counts[-1] if member_counts else 0
    forecast_end = forecast_values[-1] if forecast_values else current_members
    growth_rate = ((forecast_end - current_members) / current_members * 100) if current_members > 0 else 0

    return {
        "historical_trend": {
            "months": [datetime.strptime(d.month, "%Y-%m").strftime("%b %Y") for d in historical_data[-12:]],
            "values": member_counts[-12:],
        },
        "forecast": {
            "months": forecast_months,
            "values": forecast_values,
            "confidence_intervals": confidence_intervals,
        },
        "metrics": {
            "current_members": int(current_members),
            "forecast_members": int(forecast_end),
            "expected_growth": int(forecast_end - current_members),
            "growth_rate": round(growth_rate, 1),
        },
    }


def forecast_revenue(months_ahead=12):
    """Forecast revenue based on member projections and historical patterns"""
    member_forecast = forecast_member_growth(months_ahead)

    if "error" in member_forecast:
        return {"error": "Cannot forecast revenue without member projections"}

    # Get average revenue per member by type
    revenue_by_type = frappe.db.sql(
        """
        SELECT
            ms.membership_type,
            COUNT(DISTINCT ms.member) as member_count,
            AVG(COALESCE(m.membership_fee_override, mt.amount)) as avg_fee
        FROM `tabMembership` ms
        JOIN `tabMember` m ON ms.member = m.name
        JOIN `tabMembership Type` mt ON ms.membership_type = mt.name
        WHERE ms.status = 'Active'
        GROUP BY ms.membership_type
    """,
        as_dict=True,
    )

    # Calculate weighted average revenue per member
    total_members = sum(r.member_count for r in revenue_by_type)
    avg_revenue_per_member = (
        sum(r.avg_fee * r.member_count for r in revenue_by_type) / total_members if total_members > 0 else 0
    )

    # Apply seasonal adjustments
    seasonal_factors = get_seasonal_revenue_factors()

    # Generate revenue forecast
    revenue_forecast = []
    current_month = datetime.now().month

    for i, member_count in enumerate(member_forecast["forecast"]["values"]):
        forecast_month = (current_month + i) % 12 + 1
        seasonal_factor = seasonal_factors.get(forecast_month, 1.0)

        monthly_revenue = member_count * avg_revenue_per_member * seasonal_factor / 12
        revenue_forecast.append(
            {
                "month": member_forecast["forecast"]["months"][i],
                "revenue": round(monthly_revenue, 2),
                "member_count": member_count,
                "avg_member_value": round(avg_revenue_per_member * seasonal_factor, 2),
            }
        )

    # Calculate cumulative revenue
    cumulative_revenue = []
    total = 0
    for item in revenue_forecast:
        total += item["revenue"]
        cumulative_revenue.append(round(total, 2))

    return {
        "monthly_forecast": revenue_forecast,
        "cumulative_revenue": cumulative_revenue,
        "annual_projection": round(sum(item["revenue"] for item in revenue_forecast[:12]), 2),
        "avg_member_value": round(avg_revenue_per_member, 2),
    }


def analyze_churn_risk():
    """Identify members at risk of churning"""

    # Get at-risk members
    at_risk_members = []

    # Payment failures
    payment_failures = frappe.db.sql(
        """
        SELECT
            m.name,
            m.full_name,
            COUNT(DISTINCT si.name) as failed_payments
        FROM `tabMember` m
        JOIN `tabSales Invoice` si ON si.member = m.name
        WHERE m.status = 'Active'
        AND si.status = 'Overdue'
        AND si.due_date < CURDATE()
        GROUP BY m.name
        HAVING failed_payments > 0
    """,
        as_dict=True,
    )

    for member in payment_failures:
        risk_score = min(member.failed_payments * 0.3, 0.9)
        at_risk_members.append(
            {
                "member": member.name,
                "member_name": member.full_name,
                "risk_score": risk_score,
                "risk_factors": ["Payment failures"],
                "recommended_action": "Contact for payment arrangement",
            }
        )

    # No recent activity (simplified - would need activity tracking)
    inactive_members = frappe.db.sql(
        """
        SELECT
            name,
            full_name,
            DATEDIFF(CURDATE(), modified) as days_inactive
        FROM `tabMember`
        WHERE status = 'Active'
        AND DATEDIFF(CURDATE(), modified) > 90
        LIMIT 20
    """,
        as_dict=True,
    )

    for member in inactive_members:
        risk_score = min(member.days_inactive / 365 * 0.5, 0.7)
        existing = next((m for m in at_risk_members if m["member"] == member.name), None)
        if existing:
            existing["risk_score"] = min(existing["risk_score"] + risk_score * 0.2, 0.95)
            existing["risk_factors"].append("No recent activity")
        else:
            at_risk_members.append(
                {
                    "member": member.name,
                    "member_name": member.full_name,
                    "risk_score": risk_score,
                    "risk_factors": ["No recent activity"],
                    "recommended_action": "Engagement campaign",
                }
            )

    # Sort by risk score
    at_risk_members.sort(key=lambda x: x["risk_score"], reverse=True)

    # Calculate statistics
    total_active = frappe.db.count("Member", {"status": "Active"})
    high_risk_count = len([m for m in at_risk_members if m["risk_score"] > 0.7])
    medium_risk_count = len([m for m in at_risk_members if 0.4 <= m["risk_score"] <= 0.7])

    return {
        "high_risk_members": at_risk_members[:10],  # Top 10
        "statistics": {
            "total_at_risk": len(at_risk_members),
            "high_risk": high_risk_count,
            "medium_risk": medium_risk_count,
            "low_risk": len(at_risk_members) - high_risk_count - medium_risk_count,
            "risk_percentage": round(len(at_risk_members) / total_active * 100, 1) if total_active > 0 else 0,
        },
        "risk_distribution": {"payment_issues": len(payment_failures), "inactive": len(inactive_members)},
    }


def detect_seasonal_patterns():
    """Detect seasonal patterns in membership and revenue"""
    # Get monthly patterns over past 3 years
    monthly_patterns = frappe.db.sql(
        """
        SELECT
            MONTH(member_since) as month,
            MONTHNAME(member_since) as month_name,
            COUNT(*) as new_members,
            AVG(COUNT(*)) OVER (PARTITION BY MONTH(member_since)) as avg_for_month
        FROM `tabMember`
        WHERE member_since >= DATE_SUB(CURDATE(), INTERVAL 3 YEAR)
        AND status != 'Rejected'
        GROUP BY YEAR(member_since), MONTH(member_since)
        ORDER BY month
    """,
        as_dict=True,
    )

    # Calculate seasonal indices
    seasonal_indices = {}
    months_data = {}

    for pattern in monthly_patterns:
        month = pattern.month
        if month not in months_data:
            months_data[month] = []
        months_data[month].append(pattern.new_members)

    # Calculate average for each month
    overall_avg = sum(sum(counts) for counts in months_data.values()) / sum(
        len(counts) for counts in months_data.values()
    )

    for month, counts in months_data.items():
        month_avg = sum(counts) / len(counts)
        seasonal_indices[month] = month_avg / overall_avg if overall_avg > 0 else 1.0

    # Identify peak and low seasons
    sorted_months = sorted(seasonal_indices.items(), key=lambda x: x[1], reverse=True)
    peak_months = sorted_months[:3]
    low_months = sorted_months[-3:]

    return {
        "seasonal_indices": {calendar.month_name[k]: round(v, 2) for k, v in seasonal_indices.items()},
        "peak_seasons": [{"month": calendar.month_name[m[0]], "index": round(m[1], 2)} for m in peak_months],
        "low_seasons": [{"month": calendar.month_name[m[0]], "index": round(m[1], 2)} for m in low_months],
        "insights": generate_seasonal_insights(seasonal_indices),
    }


def calculate_growth_scenarios():
    """Calculate different growth scenarios"""
    current_members = frappe.db.count("Member", {"status": "Active"})
    current_revenue = calculate_current_annual_revenue()

    # Base growth rate from historical data
    base_growth_rate = calculate_historical_growth_rate()

    scenarios = {
        "conservative": {
            "name": "Conservative",
            "growth_rate": max(0, base_growth_rate * 0.5),
            "description": "Assumes reduced growth due to market conditions",
        },
        "moderate": {
            "name": "Moderate",
            "growth_rate": base_growth_rate,
            "description": "Maintains current growth trajectory",
        },
        "optimistic": {
            "name": "Optimistic",
            "growth_rate": base_growth_rate * 1.5,
            "description": "Assumes successful growth initiatives",
        },
        "aggressive": {
            "name": "Aggressive",
            "growth_rate": base_growth_rate * 2,
            "description": "Requires significant investment and campaigns",
        },
    }

    # Calculate projections for each scenario
    for key, scenario in scenarios.items():
        growth_rate = scenario["growth_rate"] / 100

        # 1-year projection
        year1_members = int(current_members * (1 + growth_rate))
        year1_revenue = current_revenue * (1 + growth_rate)

        # 3-year projection
        year3_members = int(current_members * (1 + growth_rate) ** 3)
        year3_revenue = current_revenue * (1 + growth_rate) ** 3

        scenario["projections"] = {
            "year_1": {
                "members": year1_members,
                "revenue": round(year1_revenue, 2),
                "new_members": year1_members - current_members,
            },
            "year_3": {
                "members": year3_members,
                "revenue": round(year3_revenue, 2),
                "total_new_members": year3_members - current_members,
            },
        }

        # Calculate required resources
        scenario["requirements"] = calculate_scenario_requirements(scenario["growth_rate"])

    return {
        "current_state": {
            "members": current_members,
            "annual_revenue": round(current_revenue, 2),
            "growth_rate": round(base_growth_rate, 1),
        },
        "scenarios": scenarios,
    }


def generate_recommendations():
    """Generate actionable recommendations based on analytics"""
    recommendations = []

    # Analyze current state
    growth_rate = calculate_historical_growth_rate()
    churn_rate = calculate_current_churn_rate()
    revenue_per_member = calculate_average_revenue_per_member()

    # Growth recommendations
    if growth_rate < 5:
        recommendations.append(
            {
                "category": "Growth",
                "priority": "High",
                "recommendation": "Implement targeted acquisition campaigns",
                "impact": "Could increase new member acquisition by 20-30%",
                "actions": [
                    "Launch referral program with incentives",
                    "Partner with aligned organizations",
                    "Increase social media presence",
                ],
            }
        )

    # Retention recommendations
    if churn_rate > 10:
        recommendations.append(
            {
                "category": "Retention",
                "priority": "Critical",
                "recommendation": "Focus on member retention programs",
                "impact": f"Reducing churn by 2% could save {int(churn_rate * 0.02 * frappe.db.count('Member', {'status': 'Active'}))} members annually",
                "actions": [
                    "Implement member engagement scoring",
                    "Create re-engagement campaigns for at-risk members",
                    "Improve member benefits and communication",
                ],
            }
        )

    # Revenue recommendations
    if revenue_per_member < 100:  # Adjust threshold as needed
        recommendations.append(
            {
                "category": "Revenue",
                "priority": "Medium",
                "recommendation": "Optimize membership pricing and value",
                "impact": "10% increase in average member value could generate additional revenue",
                "actions": [
                    "Review and adjust membership tiers",
                    "Introduce premium benefits",
                    "Implement dynamic pricing strategies",
                ],
            }
        )

    # Operational recommendations
    payment_failure_rate = calculate_payment_failure_rate()
    if payment_failure_rate > 5:
        recommendations.append(
            {
                "category": "Operations",
                "priority": "High",
                "recommendation": "Improve payment processing",
                "impact": f"Reducing payment failures could recover {int(payment_failure_rate * 0.5)}% of revenue",
                "actions": [
                    "Implement payment retry logic",
                    "Send payment reminder notifications",
                    "Offer alternative payment methods",
                ],
            }
        )

    # Seasonal recommendations
    seasonal_patterns = detect_seasonal_patterns()
    peak_months = [m["month"] for m in seasonal_patterns.get("peak_seasons", [])]
    if peak_months:
        recommendations.append(
            {
                "category": "Seasonal",
                "priority": "Medium",
                "recommendation": f"Prepare for peak seasons in {', '.join(peak_months[:2])}",
                "impact": "Proper preparation could maximize conversion during high-traffic periods",
                "actions": [
                    "Increase marketing budget 1 month before peak",
                    "Ensure adequate support staff",
                    "Prepare targeted campaigns",
                ],
            }
        )

    return sorted(
        recommendations, key=lambda x: {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}.get(x["priority"], 4)
    )


# Helper functions
def get_initial_member_count():
    """Get member count from 3 years ago"""
    count = frappe.db.sql(
        """
        SELECT COUNT(*) as count
        FROM `tabMember`
        WHERE member_since < DATE_SUB(CURDATE(), INTERVAL 36 MONTH)
        AND status = 'Active'
    """
    )[0][0]
    return count or 0


def get_seasonal_revenue_factors():
    """Get seasonal adjustment factors for revenue"""
    # This would ideally be calculated from historical data
    # For now, using typical patterns
    return {
        1: 1.1,  # January - New Year resolutions
        2: 1.05,
        3: 1.0,
        4: 0.95,
        5: 0.9,
        6: 0.9,
        7: 0.85,  # Summer low
        8: 0.85,
        9: 1.05,  # Back to routine
        10: 1.1,
        11: 1.05,
        12: 0.95,  # Holiday season
    }


def calculate_historical_growth_rate():
    """Calculate average growth rate from historical data"""
    growth_data = frappe.db.sql(
        """
        SELECT
            YEAR(member_since) as year,
            COUNT(*) as members
        FROM `tabMember`
        WHERE member_since >= DATE_SUB(CURDATE(), INTERVAL 3 YEAR)
        AND status != 'Rejected'
        GROUP BY year
        ORDER BY year
    """,
        as_dict=True,
    )

    if len(growth_data) < 2:
        return 5.0  # Default 5% if insufficient data

    # Calculate year-over-year growth rates
    growth_rates = []
    for i in range(1, len(growth_data)):
        prev_year = growth_data[i - 1].members
        curr_year = growth_data[i].members
        if prev_year > 0:
            rate = ((curr_year - prev_year) / prev_year) * 100
            growth_rates.append(rate)

    return sum(growth_rates) / len(growth_rates) if growth_rates else 5.0


def calculate_current_churn_rate():
    """Calculate current annual churn rate"""
    active_members = frappe.db.count("Member", {"status": "Active"})
    terminated_last_year = frappe.db.count(
        "Membership Termination Request",
        {"status": "Completed", "termination_date": [">=", add_months(getdate(), -12)]},
    )

    return (terminated_last_year / active_members * 100) if active_members > 0 else 0


def calculate_average_revenue_per_member():
    """Calculate average annual revenue per member"""
    result = frappe.db.sql(
        """
        SELECT AVG(COALESCE(m.membership_fee_override, mt.amount)) as avg_revenue
        FROM `tabMembership` ms
        JOIN `tabMember` m ON ms.member = m.name
        JOIN `tabMembership Type` mt ON ms.membership_type = mt.name
        WHERE ms.status = 'Active'
    """
    )[0][0]

    return result or 0


def calculate_current_annual_revenue():
    """Calculate current annual revenue from all active members"""
    result = frappe.db.sql(
        """
        SELECT SUM(COALESCE(m.membership_fee_override, mt.amount)) as total
        FROM `tabMembership` ms
        JOIN `tabMember` m ON ms.member = m.name
        JOIN `tabMembership Type` mt ON ms.membership_type = mt.name
        WHERE ms.status = 'Active'
    """
    )[0][0]

    return result or 0


def calculate_payment_failure_rate():
    """Calculate payment failure rate"""
    total_invoices = frappe.db.count(
        "Sales Invoice",
        {"member": ["!=", ""], "docstatus": 1, "posting_date": [">=", add_months(getdate(), -12)]},
    )

    failed_invoices = frappe.db.count(
        "Sales Invoice",
        {"member": ["!=", ""], "status": "Overdue", "posting_date": [">=", add_months(getdate(), -12)]},
    )

    return (failed_invoices / total_invoices * 100) if total_invoices > 0 else 0


def calculate_scenario_requirements(growth_rate):
    """Calculate resource requirements for a growth scenario"""
    # Simplified calculation - would be more complex in reality
    if growth_rate < 5:
        return {
            "marketing_budget_increase": "10%",
            "staff_requirements": "Maintain current",
            "technology_investment": "Minor upgrades",
        }
    elif growth_rate < 10:
        return {
            "marketing_budget_increase": "25%",
            "staff_requirements": "+1-2 FTE",
            "technology_investment": "Automation tools",
        }
    elif growth_rate < 20:
        return {
            "marketing_budget_increase": "50%",
            "staff_requirements": "+3-5 FTE",
            "technology_investment": "Platform scaling",
        }
    else:
        return {
            "marketing_budget_increase": "100%+",
            "staff_requirements": "+5-10 FTE",
            "technology_investment": "Major infrastructure",
        }


def generate_seasonal_insights(seasonal_indices):
    """Generate insights from seasonal patterns"""
    insights = []

    # Find the highest and lowest months
    max_month = max(seasonal_indices.items(), key=lambda x: x[1])
    min_month = min(seasonal_indices.items(), key=lambda x: x[1])

    variance = max_month[1] - min_month[1]

    if variance > 0.5:
        insights.append("Strong seasonal variation detected - consider seasonal staffing")

    if max_month[1] > 1.3:
        insights.append(
            f"Peak season in {calendar.month_name[max_month[0]]} shows {int((max_month[1] - 1) * 100)}% higher activity"
        )

    if min_month[1] < 0.7:
        insights.append(f"Low season in {calendar.month_name[min_month[0]]} requires retention focus")

    return insights

