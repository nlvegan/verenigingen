#!/usr/bin/env python3
"""
Email Analytics and Tracking System
Phase 3 Implementation - Email Performance Analytics

This module provides comprehensive analytics and tracking for email campaigns,
newsletters, and member engagement.
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import add_days, formatdate, get_datetime, now_datetime


class EmailAnalyticsTracker:
    """Tracker for email campaign analytics and performance metrics"""

    def __init__(self):
        self.default_retention_days = 90  # Keep detailed analytics for 90 days

    def track_email_sent(
        self,
        newsletter_id: str,
        campaign_id: str = None,
        template_id: str = None,
        chapter_name: str = None,
        segment: str = "all",
        recipient_count: int = 0,
        subject: str = None,
    ) -> str:
        """
        Track when an email is sent

        Args:
            newsletter_id: Newsletter document ID
            campaign_id: Campaign ID (if from automated campaign)
            template_id: Template used
            chapter_name: Chapter name (if chapter-specific)
            segment: Target segment
            recipient_count: Number of recipients
            subject: Email subject line

        Returns:
            Tracking ID for this email send
        """
        try:
            # SECURITY FIX: Check if DocType exists before using
            if not frappe.db.exists("DocType", "Email Analytics Tracking"):
                frappe.log_error(
                    "Email Analytics Tracking DocType not found - analytics disabled", "Email Analytics"
                )
                return None

            tracking_doc = frappe.get_doc(
                {
                    "doctype": "Email Analytics Tracking",
                    "newsletter": newsletter_id,
                    "campaign": campaign_id,
                    "template_id": template_id,
                    "chapter": chapter_name,
                    "segment": segment,
                    "subject": subject,
                    "recipient_count": recipient_count,
                    "sent_date": now_datetime(),
                    "tracking_status": "Active",
                    "open_count": 0,
                    "click_count": 0,
                    "unsubscribe_count": 0,
                }
            )
            tracking_doc.insert()

            return tracking_doc.name

        except Exception as e:
            frappe.log_error(f"Error tracking email send: {str(e)}", "Email Analytics")
            return None

    def track_email_open(self, tracking_id: str, recipient_email: str = None) -> bool:
        """
        Track when an email is opened

        Args:
            tracking_id: Email tracking ID
            recipient_email: Email address of recipient (optional)

        Returns:
            Success status
        """
        try:
            # SECURITY FIX: Validate DocTypes exist
            if not frappe.db.exists("DocType", "Email Analytics Tracking"):
                return False

            # SECURITY FIX: Validate tracking_id exists and is not malicious
            if not tracking_id or not frappe.db.exists("Email Analytics Tracking", tracking_id):
                return False

            # Update tracking document
            tracking_doc = frappe.get_doc("Email Analytics Tracking", tracking_id)
            tracking_doc.open_count += 1
            tracking_doc.last_opened = now_datetime()
            tracking_doc.save()

            # Create detailed open event
            if recipient_email and frappe.db.exists("DocType", "Email Open Event"):
                # SECURITY FIX: Validate email format
                if not frappe.utils.validate_email_address(recipient_email):
                    recipient_email = None

                open_event = frappe.get_doc(
                    {
                        "doctype": "Email Open Event",
                        "tracking_id": tracking_id,
                        "recipient_email": recipient_email,
                        "opened_at": now_datetime(),
                        "user_agent": (
                            frappe.request.headers.get("User-Agent", "")[:500] if frappe.request else ""
                        ),  # Truncate for safety
                        "ip_address": frappe.local.request_ip if hasattr(frappe.local, "request_ip") else "",
                    }
                )
                open_event.insert()

            return True

        except Exception as e:
            frappe.log_error(f"Error tracking email open: {str(e)}", "Email Analytics")
            return False

    def track_email_click(self, tracking_id: str, link_url: str, recipient_email: str = None) -> bool:
        """
        Track when a link in an email is clicked

        Args:
            tracking_id: Email tracking ID
            link_url: URL that was clicked
            recipient_email: Email address of recipient (optional)

        Returns:
            Success status
        """
        try:
            # Update tracking document
            tracking_doc = frappe.get_doc("Email Analytics Tracking", tracking_id)
            tracking_doc.click_count += 1
            tracking_doc.last_clicked = now_datetime()
            tracking_doc.save()

            # Create detailed click event
            click_event = frappe.get_doc(
                {
                    "doctype": "Email Click Event",
                    "tracking_id": tracking_id,
                    "recipient_email": recipient_email,
                    "link_url": link_url,
                    "clicked_at": now_datetime(),
                    "user_agent": frappe.request.headers.get("User-Agent", "") if frappe.request else "",
                    "ip_address": frappe.local.request_ip if hasattr(frappe.local, "request_ip") else "",
                }
            )
            click_event.insert()

            return True

        except Exception as e:
            frappe.log_error(f"Error tracking email click: {str(e)}", "Email Analytics")
            return False

    def track_unsubscribe(self, tracking_id: str, recipient_email: str, reason: str = None) -> bool:
        """
        Track when someone unsubscribes

        Args:
            tracking_id: Email tracking ID
            recipient_email: Email address of recipient
            reason: Reason for unsubscribing (optional)

        Returns:
            Success status
        """
        try:
            # Update tracking document
            tracking_doc = frappe.get_doc("Email Analytics Tracking", tracking_id)
            tracking_doc.unsubscribe_count += 1
            tracking_doc.save()

            # Create unsubscribe event
            unsubscribe_event = frappe.get_doc(
                {
                    "doctype": "Email Unsubscribe Event",
                    "tracking_id": tracking_id,
                    "recipient_email": recipient_email,
                    "unsubscribed_at": now_datetime(),
                    "reason": reason,
                    "ip_address": frappe.local.request_ip if hasattr(frappe.local, "request_ip") else "",
                }
            )
            unsubscribe_event.insert()

            # Update member opt-out status
            member = frappe.db.get_value("Member", {"email": recipient_email}, "name")
            if member:
                member_doc = frappe.get_doc("Member", member)
                member_doc.opt_out_optional_emails = 1
                member_doc.add_comment(
                    "Comment", f"Unsubscribed from emails: {reason or 'No reason provided'}"
                )
                member_doc.save()

            return True

        except Exception as e:
            frappe.log_error(f"Error tracking unsubscribe: {str(e)}", "Email Analytics")
            return False

    def get_campaign_analytics(
        self, campaign_id: str = None, chapter_name: str = None, days: int = 30
    ) -> Dict:
        """
        Get analytics for campaigns

        Args:
            campaign_id: Specific campaign ID (optional)
            chapter_name: Chapter name filter (optional)
            days: Number of days to analyze

        Returns:
            Analytics data
        """
        try:
            # Build filters
            filters = {"sent_date": [">=", add_days(now_datetime(), -days)]}

            if campaign_id:
                filters["campaign"] = campaign_id
            if chapter_name:
                filters["chapter"] = chapter_name

            # Get tracking data
            tracking_data = frappe.get_all(
                "Email Analytics Tracking",
                filters=filters,
                fields=[
                    "name",
                    "newsletter",
                    "campaign",
                    "template_id",
                    "chapter",
                    "segment",
                    "recipient_count",
                    "open_count",
                    "click_count",
                    "unsubscribe_count",
                    "sent_date",
                    "subject",
                ],
            )

            # Calculate aggregate metrics
            total_sent = sum(t["recipient_count"] for t in tracking_data)
            total_opens = sum(t["open_count"] for t in tracking_data)
            total_clicks = sum(t["click_count"] for t in tracking_data)
            total_unsubscribes = sum(t["unsubscribe_count"] for t in tracking_data)

            # Calculate rates
            open_rate = (total_opens / total_sent * 100) if total_sent > 0 else 0
            click_rate = (total_clicks / total_sent * 100) if total_sent > 0 else 0
            unsubscribe_rate = (total_unsubscribes / total_sent * 100) if total_sent > 0 else 0

            # Get top performing templates
            template_performance = {}
            for tracking in tracking_data:
                template_id = tracking.get("template_id")
                if template_id:
                    if template_id not in template_performance:
                        template_performance[template_id] = {"sent": 0, "opens": 0, "clicks": 0}
                    template_performance[template_id]["sent"] += tracking["recipient_count"]
                    template_performance[template_id]["opens"] += tracking["open_count"]
                    template_performance[template_id]["clicks"] += tracking["click_count"]

            # Calculate template rates
            for template_id, perf in template_performance.items():
                if perf["sent"] > 0:
                    perf["open_rate"] = perf["opens"] / perf["sent"] * 100
                    perf["click_rate"] = perf["clicks"] / perf["sent"] * 100

            return {
                "success": True,
                "period_days": days,
                "summary": {
                    "total_emails_sent": len(tracking_data),
                    "total_recipients": total_sent,
                    "total_opens": total_opens,
                    "total_clicks": total_clicks,
                    "total_unsubscribes": total_unsubscribes,
                    "open_rate": round(open_rate, 2),
                    "click_rate": round(click_rate, 2),
                    "unsubscribe_rate": round(unsubscribe_rate, 2),
                },
                "template_performance": dict(
                    sorted(template_performance.items(), key=lambda x: x[1]["open_rate"], reverse=True)
                ),
                "recent_campaigns": tracking_data[-10:],  # Last 10 campaigns
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_engagement_trends(self, chapter_name: str = None, days: int = 90) -> Dict:
        """
        Get engagement trends over time

        Args:
            chapter_name: Chapter name filter (optional)
            days: Number of days to analyze

        Returns:
            Trend data
        """
        try:
            # Build base query
            conditions = ["t.sent_date >= %(start_date)s"]
            values = {"start_date": add_days(now_datetime(), -days)}

            if chapter_name:
                conditions.append("t.chapter = %(chapter)s")
                values["chapter"] = chapter_name

            # SECURITY FIX: Use parameterized queries to prevent SQL injection
            base_query = """
                SELECT
                    DATE(t.sent_date) as date,
                    SUM(t.recipient_count) as sent,
                    SUM(t.open_count) as opens,
                    SUM(t.click_count) as clicks,
                    SUM(t.unsubscribe_count) as unsubscribes
                FROM `tabEmail Analytics Tracking` t
                WHERE t.sent_date >= %(start_date)s
            """

            if chapter_name:
                base_query += " AND t.chapter = %(chapter)s"

            base_query += """
                GROUP BY DATE(t.sent_date)
                ORDER BY date ASC
            """

            daily_data = frappe.db.sql(base_query, values, as_dict=True)

            # Calculate running averages
            for i, day in enumerate(daily_data):
                if day["sent"] > 0:
                    day["open_rate"] = round(day["opens"] / day["sent"] * 100, 2)
                    day["click_rate"] = round(day["clicks"] / day["sent"] * 100, 2)
                else:
                    day["open_rate"] = 0
                    day["click_rate"] = 0

                day["date"] = formatdate(day["date"])

            return {
                "success": True,
                "period_days": days,
                "daily_trends": daily_data,
                "trend_summary": {
                    "total_days_with_activity": len(daily_data),
                    "avg_daily_sent": (
                        sum(d["sent"] for d in daily_data) / len(daily_data) if daily_data else 0
                    ),
                    "avg_open_rate": (
                        sum(d["open_rate"] for d in daily_data) / len(daily_data) if daily_data else 0
                    ),
                    "avg_click_rate": (
                        sum(d["click_rate"] for d in daily_data) / len(daily_data) if daily_data else 0
                    ),
                },
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_member_engagement_score(self, member_email: str) -> Dict:
        """
        Calculate engagement score for a specific member

        Args:
            member_email: Member's email address

        Returns:
            Engagement score and details
        """
        try:
            # Get member's email activity in last 90 days
            recent_activity = frappe.db.sql(
                """
                SELECT
                    COUNT(DISTINCT o.tracking_id) as emails_opened,
                    COUNT(DISTINCT c.tracking_id) as emails_clicked,
                    COUNT(DISTINCT t.name) as emails_received
                FROM `tabEmail Analytics Tracking` t
                LEFT JOIN `tabEmail Open Event` o ON o.tracking_id = t.name
                    AND o.recipient_email = %(email)s
                LEFT JOIN `tabEmail Click Event` c ON c.tracking_id = t.name
                    AND c.recipient_email = %(email)s
                WHERE t.sent_date >= DATE_SUB(NOW(), INTERVAL 90 DAY)
                    AND t.recipient_count > 0
            """,
                {"email": member_email},
                as_dict=True,
            )[0]

            emails_received = recent_activity["emails_received"] or 0
            emails_opened = recent_activity["emails_opened"] or 0
            emails_clicked = recent_activity["emails_clicked"] or 0

            # Calculate engagement score (0-100)
            if emails_received == 0:
                engagement_score = 0
                engagement_level = "No Activity"
            else:
                open_rate = emails_opened / emails_received
                click_rate = emails_clicked / emails_received if emails_received > 0 else 0

                # Weight: 60% opens, 40% clicks
                engagement_score = round((open_rate * 60) + (click_rate * 40), 1)

                if engagement_score >= 75:
                    engagement_level = "Highly Engaged"
                elif engagement_score >= 50:
                    engagement_level = "Moderately Engaged"
                elif engagement_score >= 25:
                    engagement_level = "Low Engagement"
                else:
                    engagement_level = "Minimal Engagement"

            return {
                "success": True,
                "member_email": member_email,
                "engagement_score": engagement_score,
                "engagement_level": engagement_level,
                "activity_summary": {
                    "emails_received": emails_received,
                    "emails_opened": emails_opened,
                    "emails_clicked": emails_clicked,
                    "open_rate": (
                        round(emails_opened / emails_received * 100, 1) if emails_received > 0 else 0
                    ),
                    "click_rate": (
                        round(emails_clicked / emails_received * 100, 1) if emails_received > 0 else 0
                    ),
                },
                "period": "Last 90 days",
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def cleanup_old_analytics(self, retention_days: int = None) -> Dict:
        """
        Clean up old analytics data to prevent database bloat

        Args:
            retention_days: Days to retain data (default from config)

        Returns:
            Cleanup results
        """
        if retention_days is None:
            retention_days = self.default_retention_days

        try:
            cutoff_date = add_days(now_datetime(), -retention_days)

            # Delete old tracking records
            old_tracking = frappe.get_all(
                "Email Analytics Tracking", filters={"sent_date": ["<", cutoff_date]}, fields=["name"]
            )

            deleted_count = 0
            for tracking in old_tracking:
                # Delete related events first
                frappe.db.delete("Email Open Event", {"tracking_id": tracking.name})
                frappe.db.delete("Email Click Event", {"tracking_id": tracking.name})
                frappe.db.delete("Email Unsubscribe Event", {"tracking_id": tracking.name})

                # Delete tracking record
                frappe.delete_doc("Email Analytics Tracking", tracking.name)
                deleted_count += 1

            frappe.db.commit()

            return {
                "success": True,
                "deleted_records": deleted_count,
                "retention_days": retention_days,
                "cutoff_date": formatdate(cutoff_date.date()),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


# API Functions
@frappe.whitelist()
def get_email_analytics(campaign_id: str = None, chapter_name: str = None, days: int = 30) -> Dict:
    """
    Get email campaign analytics

    Args:
        campaign_id: Specific campaign ID (optional)
        chapter_name: Chapter name filter (optional)
        days: Number of days to analyze

    Returns:
        Analytics data
    """
    # Check permissions
    if chapter_name and not frappe.has_permission("Chapter", "read", doc=chapter_name):
        frappe.throw(_("You don't have permission to view analytics for this chapter"))

    if not chapter_name and not (
        "System Manager" in frappe.get_roles() or "Verenigingen Manager" in frappe.get_roles()
    ):
        frappe.throw(_("You don't have permission to view organization-wide analytics"))

    tracker = EmailAnalyticsTracker()
    return tracker.get_campaign_analytics(campaign_id, chapter_name, int(days))


@frappe.whitelist()
def get_engagement_trends(chapter_name: str = None, days: int = 90) -> Dict:
    """
    Get engagement trends over time

    Args:
        chapter_name: Chapter name filter (optional)
        days: Number of days to analyze

    Returns:
        Trend data
    """
    # Check permissions
    if chapter_name and not frappe.has_permission("Chapter", "read", doc=chapter_name):
        frappe.throw(_("You don't have permission to view analytics for this chapter"))

    tracker = EmailAnalyticsTracker()
    return tracker.get_engagement_trends(chapter_name, int(days))


@frappe.whitelist()
def get_member_engagement(member_email: str) -> Dict:
    """
    Get engagement score for a specific member

    Args:
        member_email: Member's email address

    Returns:
        Engagement data
    """
    # Check if user can view this member's data
    member = frappe.db.get_value("Member", {"email": member_email}, ["name", "chapter"])
    if not member:
        frappe.throw(_("Member not found"))

    member_name, chapter = member
    if not frappe.has_permission("Member", "read", doc=member_name):
        frappe.throw(_("You don't have permission to view this member's engagement data"))

    tracker = EmailAnalyticsTracker()
    return tracker.get_member_engagement_score(member_email)


# Tracking endpoints for email opens and clicks
@frappe.whitelist(allow_guest=True)
def track_open(tracking_id: str, email: str = None):
    """Track email open (called from email pixel)"""
    tracker = EmailAnalyticsTracker()
    tracker.track_email_open(tracking_id, email)

    # Return 1x1 transparent pixel
    frappe.local.response.filename = "pixel.gif"
    frappe.local.response.filecontent = b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x04\x01\x00\x3b"
    frappe.local.response.type = "binary"


@frappe.whitelist(allow_guest=True)
def track_click(tracking_id: str, url: str, email: str = None):
    """Track email click and redirect"""
    tracker = EmailAnalyticsTracker()
    tracker.track_email_click(tracking_id, url, email)

    # Redirect to original URL
    frappe.local.response.type = "redirect"
    frappe.local.response.location = url


# Scheduled cleanup job
def cleanup_old_email_analytics():
    """
    Scheduled job to clean up old analytics data
    Add this to hooks.py scheduler_events
    """
    # Only run if analytics is enabled
    if frappe.db.get_single_value("Verenigingen Settings", "enable_email_analytics"):
        tracker = EmailAnalyticsTracker()
        result = tracker.cleanup_old_analytics()

        if not result["success"]:
            frappe.log_error(f"Email analytics cleanup failed: {result['error']}", "Email Analytics Cleanup")
