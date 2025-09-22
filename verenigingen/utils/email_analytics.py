#!/usr/bin/env python3
"""
Email Analytics Utilities
=========================

Wrapper utilities for email analytics and campaign performance reporting.
Maps to the actual implementation in verenigingen.email.analytics_tracker
"""

from typing import Any, Dict, List

import frappe

from verenigingen.email.analytics_tracker import (
    EmailAnalyticsTracker,
    get_email_analytics,
    get_engagement_trends,
)


def generate_campaign_analytics(campaign_id: str = None, days: int = 30) -> Dict[str, Any]:
    """
    Generate comprehensive analytics for email campaigns

    Args:
        campaign_id: Specific campaign to analyze (optional)
        days: Number of days to analyze

    Returns:
        Dict with campaign analytics data
    """
    try:
        # Use the actual analytics tracker implementation
        analytics_data = get_email_analytics(campaign_id=campaign_id, days=days)

        # Add engagement trends
        engagement_data = get_engagement_trends(days=days)

        return {
            "success": True,
            "campaign_id": campaign_id,
            "period_days": days,
            "analytics": analytics_data,
            "engagement_trends": engagement_data,
            "summary": {
                "total_campaigns": analytics_data.get("total_campaigns", 0),
                "total_emails_sent": analytics_data.get("total_sent", 0),
                "total_opens": analytics_data.get("total_opens", 0),
                "total_clicks": analytics_data.get("total_clicks", 0),
                "open_rate": analytics_data.get("open_rate", 0),
                "click_rate": analytics_data.get("click_rate", 0),
            },
        }

    except Exception as e:
        frappe.log_error(f"Generate campaign analytics failed: {str(e)}")
        return {"success": False, "error": str(e)}


def get_member_analytics(member_email: str, days: int = 90) -> Dict[str, Any]:
    """
    Get analytics for a specific member's email engagement

    Args:
        member_email: Member email address
        days: Number of days to analyze

    Returns:
        Dict with member analytics
    """
    try:
        # Use the actual analytics tracker
        tracker = EmailAnalyticsTracker()
        member_data = tracker.get_member_engagement_score(member_email)

        return {
            "success": True,
            "member_email": member_email,
            "period_days": days,
            "engagement_data": member_data,
        }

    except Exception as e:
        frappe.log_error(f"Get member analytics failed: {str(e)}")
        return {"success": False, "error": str(e)}


def get_campaign_performance_report(chapter_name: str = None, days: int = 30) -> Dict[str, Any]:
    """
    Generate performance report for campaigns

    Args:
        chapter_name: Filter by specific chapter (optional)
        days: Number of days to analyze

    Returns:
        Dict with performance report data
    """
    try:
        # Get engagement trends with chapter filter
        trends_data = get_engagement_trends(chapter_name=chapter_name, days=days)

        # Get overall analytics
        analytics_data = get_email_analytics(days=days)

        return {
            "success": True,
            "chapter_name": chapter_name,
            "period_days": days,
            "performance_metrics": {"engagement_trends": trends_data, "overall_analytics": analytics_data},
            "recommendations": _generate_recommendations(analytics_data),
        }

    except Exception as e:
        frappe.log_error(f"Get campaign performance report failed: {str(e)}")
        return {"success": False, "error": str(e)}


def _generate_recommendations(analytics_data: Dict[str, Any]) -> List[str]:
    """Generate recommendations based on analytics data"""
    recommendations = []

    try:
        open_rate = analytics_data.get("open_rate", 0)
        click_rate = analytics_data.get("click_rate", 0)

        if open_rate < 20:
            recommendations.append("Consider improving subject lines to increase open rates")

        if click_rate < 3:
            recommendations.append("Add more compelling call-to-action buttons to increase clicks")

        if open_rate > 25 and click_rate < 2:
            recommendations.append(
                "Content is engaging enough to open but not compelling enough to click - review email content"
            )

    except Exception:
        recommendations.append("Insufficient data for recommendations")

    return recommendations


def export_analytics_data(campaign_id: str = None, format: str = "json") -> Dict[str, Any]:
    """
    Export analytics data in specified format

    Args:
        campaign_id: Specific campaign to export (optional)
        format: Export format (json, csv)

    Returns:
        Dict with export result
    """
    try:
        analytics_data = generate_campaign_analytics(campaign_id=campaign_id)

        if format.lower() == "json":
            return {
                "success": True,
                "format": format,
                "data": analytics_data,
                "message": "Analytics data exported successfully",
            }
        elif format.lower() == "csv":
            # For CSV export, we'd typically convert to CSV format
            # For now, return the structured data
            return {
                "success": True,
                "format": format,
                "data": analytics_data,
                "message": "Analytics data prepared for CSV export",
            }
        else:
            return {"success": False, "error": f"Unsupported format: {format}"}

    except Exception as e:
        frappe.log_error(f"Export analytics data failed: {str(e)}")
        return {"success": False, "error": str(e)}
