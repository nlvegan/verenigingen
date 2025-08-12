#!/usr/bin/env python3
"""
Automated Newsletter Campaigns
Phase 3 Implementation - Scheduled and Automated Email Campaigns

This module provides automated campaign functionality for recurring newsletters
and event-driven email communications.
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import add_days, add_months, formatdate, get_datetime, now_datetime


class AutomatedCampaignManager:
    """Manager for automated email campaigns"""

    def __init__(self):
        self.campaign_types = self._get_campaign_types()

    def _get_campaign_types(self) -> Dict:
        """Define available campaign types"""
        return {
            "monthly_newsletter": {
                "name": "Monthly Newsletter",
                "description": "Automated monthly newsletter to all active members",
                "frequency": "monthly",
                "template_id": "monthly_update",
                "default_segment": "all",
                "requires_content": True,
            },
            "welcome_series": {
                "name": "Welcome Series",
                "description": "Automated welcome emails for new members",
                "frequency": "event_driven",
                "template_id": "welcome_new_members",
                "trigger_event": "member_activation",
                "requires_content": False,
            },
            "event_reminders": {
                "name": "Event Reminders",
                "description": "Automated reminders for upcoming events",
                "frequency": "event_driven",
                "template_id": "event_announcement",
                "trigger_event": "event_upcoming",
                "requires_content": False,
            },
            "membership_renewal": {
                "name": "Membership Renewal",
                "description": "Automated renewal reminders",
                "frequency": "annual",
                "template_id": "membership_renewal",
                "days_before": 30,
                "requires_content": False,
            },
            "volunteer_recruitment": {
                "name": "Volunteer Recruitment",
                "description": "Quarterly volunteer recruitment campaigns",
                "frequency": "quarterly",
                "template_id": "volunteer_recruitment",
                "default_segment": "all",
                "requires_content": True,
            },
        }

    def create_campaign(
        self,
        campaign_type: str,
        chapter_name: str = None,
        title: str = None,
        description: str = None,
        schedule_config: Dict = None,
        content_config: Dict = None,
    ) -> Dict:
        """
        Create a new automated campaign

        Args:
            campaign_type: Type of campaign
            chapter_name: Chapter name (None for organization-wide)
            title: Campaign title
            description: Campaign description
            schedule_config: Scheduling configuration
            content_config: Content configuration

        Returns:
            Dict with creation result
        """
        campaign_def = self.campaign_types.get(campaign_type)
        if not campaign_def:
            return {"success": False, "error": "Invalid campaign type"}

        try:
            # Create campaign document
            campaign_doc = frappe.get_doc(
                {
                    "doctype": "Email Campaign",
                    "campaign_name": title or campaign_def["name"],
                    "campaign_type": campaign_type,
                    "description": description or campaign_def["description"],
                    "chapter": chapter_name,
                    "template_id": campaign_def["template_id"],
                    "frequency": campaign_def["frequency"],
                    "segment": campaign_def.get("default_segment", "all"),
                    "is_active": 1,
                    "schedule_config": json.dumps(schedule_config or {}),
                    "content_config": json.dumps(content_config or {}),
                    "created_by": frappe.session.user,
                    "next_run_date": self._calculate_next_run(campaign_def, schedule_config),
                }
            )

            campaign_doc.insert()

            return {
                "success": True,
                "campaign_id": campaign_doc.name,
                "message": f"Campaign '{campaign_doc.campaign_name}' created successfully",
            }

        except Exception as e:
            frappe.log_error(f"Error creating campaign: {str(e)}", "Automated Campaigns")
            return {"success": False, "error": str(e)}

    def _calculate_next_run(self, campaign_def: Dict, schedule_config: Dict = None) -> datetime:
        """Calculate the next run date for a campaign"""
        now = now_datetime()

        if campaign_def["frequency"] == "monthly":
            # First day of next month
            return add_months(now.replace(day=1, hour=9, minute=0, second=0, microsecond=0), 1)
        elif campaign_def["frequency"] == "quarterly":
            # First day of next quarter
            current_quarter = (now.month - 1) // 3 + 1
            next_quarter_month = current_quarter * 3 + 1
            if next_quarter_month > 12:
                next_quarter_month = 1
                year = now.year + 1
            else:
                year = now.year
            return datetime(year, next_quarter_month, 1, 9, 0, 0)
        elif campaign_def["frequency"] == "annual":
            # Same date next year
            return now.replace(year=now.year + 1, hour=9, minute=0, second=0, microsecond=0)
        else:
            # Event-driven campaigns don't have scheduled runs
            return None

    def process_scheduled_campaigns(self) -> Dict:
        """
        Process all scheduled campaigns that are due to run
        This function is called by the scheduler
        """
        now = now_datetime()
        processed = []
        errors = []

        # SECURITY FIX: Check if DocType exists before querying
        if not frappe.db.exists("DocType", "Email Campaign"):
            return {
                "success": False,
                "processed": [],
                "errors": ["Email Campaign DocType not found"],
                "total_processed": 0,
            }

        # Get campaigns that are due to run
        due_campaigns = frappe.get_all(
            "Email Campaign",
            filters={"status": "In Progress", "start_date": ["<=", now]},
            fields=[
                "name",
                "campaign_name",
                "email_campaign_for",
                "recipient",
                "sender",
                "start_date",
                "end_date",
                "status",
            ],
        )

        for campaign in due_campaigns:
            try:
                result = self._execute_campaign(campaign)
                if result["success"]:
                    processed.append(campaign["campaign_name"])
                    # Update next run date
                    self._update_next_run_date(campaign["name"])
                else:
                    errors.append(f"{campaign['campaign_name']}: {result['error']}")

            except Exception as e:
                errors.append(f"{campaign['campaign_name']}: {str(e)}")

        return {
            "success": len(errors) == 0,
            "processed": processed,
            "errors": errors,
            "total_processed": len(processed),
        }

    def _execute_campaign(self, campaign: Dict) -> Dict:
        """Execute a single campaign"""
        try:
            # Get campaign configuration
            content_config = json.loads(campaign.get("content_config") or "{}")
            campaign_def = self.campaign_types.get(campaign["campaign_type"], {})

            # Generate content if needed
            if campaign_def.get("requires_content"):
                content = self._generate_campaign_content(campaign, content_config)
            else:
                content = self._get_default_content(campaign)

            if not content:
                return {"success": False, "error": "Could not generate content"}

            # Send email using template system
            from verenigingen.email.newsletter_templates import send_templated_email

            result = send_templated_email(
                template_id=campaign["template_id"],
                variables=json.dumps(content),
                chapter_name=campaign.get("chapter"),
                segment=campaign.get("segment", "all"),
            )

            # Log campaign execution
            self._log_campaign_execution(campaign["name"], result)

            return result

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _generate_campaign_content(self, campaign: Dict, content_config: Dict) -> Optional[Dict]:
        """Generate dynamic content for campaigns that require it"""
        campaign_type = campaign["campaign_type"]

        if campaign_type == "monthly_newsletter":
            return self._generate_monthly_newsletter_content(campaign, content_config)
        elif campaign_type == "volunteer_recruitment":
            return self._generate_volunteer_content(campaign, content_config)
        else:
            return None

    def _generate_monthly_newsletter_content(self, campaign: Dict, config: Dict) -> Dict:
        """Generate content for monthly newsletter"""
        now = now_datetime()
        chapter_name = campaign.get("chapter", "Organization")

        # Get chapter highlights (placeholder - would integrate with actual data)
        highlights = config.get(
            "highlights",
            "• Successfully completed our monthly community outreach program<br>"
            "• Welcomed 15 new members to our chapter<br>"
            "• Raised €1,200 for our annual fundraising campaign",
        )

        # Get upcoming events (placeholder - would integrate with Events system)
        upcoming_events = config.get(
            "upcoming_events",
            "• <strong>Community Cleanup Day</strong> - Next Saturday 10:00 AM<br>"
            "• <strong>Monthly Board Meeting</strong> - First Tuesday of next month<br>"
            "• <strong>Volunteer Training Session</strong> - March 15th, 7:00 PM",
        )

        # Get volunteer spotlight (placeholder)
        volunteer_spotlight = config.get(
            "volunteer_spotlight",
            "<strong>This month we recognize Sarah Johnson</strong> for her outstanding "
            "dedication to our community programs. Sarah has volunteered over 40 hours "
            "this month and has been instrumental in organizing our food drive initiative.",
        )

        return {
            "chapter_name": chapter_name,
            "month_year": now.strftime("%B %Y"),
            "highlights": highlights,
            "upcoming_events": upcoming_events,
            "volunteer_spotlight": volunteer_spotlight,
        }

    def _generate_volunteer_content(self, campaign: Dict, config: Dict) -> Dict:
        """Generate content for volunteer recruitment"""
        chapter_name = campaign.get("chapter", "Organization")

        return {
            "opportunity_title": config.get("opportunity_title", "Community Outreach Volunteers Needed"),
            "time_commitment": config.get("time_commitment", "2-4 hours per week, flexible scheduling"),
            "skills_needed": config.get(
                "skills_needed",
                "• Enthusiasm for community service<br>"
                "• Good communication skills<br>"
                "• Reliability and commitment<br>"
                "• No prior experience necessary - training provided!",
            ),
            "contact_info": config.get(
                "contact_info",
                f"Email: volunteers@{chapter_name.lower().replace(' ', '')}.org<br>" "Phone: +31 20 123 4567",
            ),
            "contact_email": config.get("contact_email", "volunteers@organization.org"),
        }

    def _get_default_content(self, campaign: Dict) -> Dict:
        """Get default content for campaigns that don't require dynamic generation"""
        # This would be implemented based on campaign type
        # For now, return minimal content
        return {
            "chapter_name": campaign.get("chapter", "Organization"),
            "date": formatdate(now_datetime().date()),
        }

    def _update_next_run_date(self, campaign_id: str):
        """Update the next run date for a campaign"""
        campaign_doc = frappe.get_doc("Email Campaign", campaign_id)
        campaign_def = self.campaign_types.get(campaign_doc.campaign_type, {})

        schedule_config = json.loads(campaign_doc.schedule_config or "{}")
        next_run = self._calculate_next_run(campaign_def, schedule_config)

        if next_run:
            campaign_doc.next_run_date = next_run
            campaign_doc.last_run_date = now_datetime()
            campaign_doc.save()

    def _log_campaign_execution(self, campaign_id: str, result: Dict):
        """Log campaign execution for analytics"""
        try:
            log_doc = frappe.get_doc(
                {
                    "doctype": "Campaign Execution Log",
                    "campaign": campaign_id,
                    "execution_date": now_datetime(),
                    "status": "Success" if result.get("success") else "Failed",
                    "recipients_count": result.get("recipients_count", 0),
                    "newsletter_id": result.get("newsletter"),
                    "error_message": result.get("error"),
                    "execution_details": json.dumps(result),
                }
            )
            log_doc.insert()

        except Exception as e:
            frappe.log_error(f"Error logging campaign execution: {str(e)}", "Campaign Logging")

    def trigger_event_campaigns(self, event_type: str, event_data: Dict) -> Dict:
        """
        Trigger event-driven campaigns

        Args:
            event_type: Type of event (member_activation, event_upcoming, etc.)
            event_data: Event-specific data

        Returns:
            Dict with trigger results
        """
        # Get campaigns for this event type
        campaigns = frappe.get_all(
            "Email Campaign",
            filters={"status": "In Progress"},  # Use available fields
            fields=["name", "campaign_name", "email_campaign_for", "recipient", "sender"],
        )

        triggered = []
        errors = []

        for campaign in campaigns:
            try:
                # Generate event-specific content
                content = self._generate_event_content(event_type, event_data, campaign)

                if content:
                    # Send templated email
                    from verenigingen.email.newsletter_templates import send_templated_email

                    result = send_templated_email(
                        template_id=campaign["template_id"],
                        variables=json.dumps(content),
                        chapter_name=campaign.get("chapter"),
                        segment=campaign.get("segment", "all"),
                    )

                    if result["success"]:
                        triggered.append(campaign["campaign_name"])
                        self._log_campaign_execution(campaign["name"], result)
                    else:
                        errors.append(f"{campaign['campaign_name']}: {result['error']}")

            except Exception as e:
                errors.append(f"{campaign['campaign_name']}: {str(e)}")

        return {"success": len(errors) == 0, "triggered": triggered, "errors": errors}

    def _generate_event_content(self, event_type: str, event_data: Dict, campaign: Dict) -> Optional[Dict]:
        """Generate content for event-driven campaigns"""
        if event_type == "member_activation":
            return {
                "chapter_name": event_data.get("chapter_name", campaign.get("chapter", "Organization")),
                "new_member_names": event_data.get("member_names", "New members"),
                "orientation_info": "Join us for our monthly orientation meeting every first Saturday at 10:00 AM.",
                "contact_person": f"Contact: {event_data.get('contact_email', 'info@organization.org')}",
            }
        elif event_type == "event_upcoming":
            return {
                "event_title": event_data.get("event_title", "Upcoming Event"),
                "event_date": event_data.get("event_date", "TBD"),
                "event_location": event_data.get("event_location", "TBD"),
                "event_description": event_data.get("event_description", "Join us for this exciting event!"),
                "registration_link": event_data.get("registration_link", "#"),
            }

        return None


# API Functions
@frappe.whitelist()
def create_automated_campaign(
    campaign_type: str,
    chapter_name: str = None,
    title: str = None,
    description: str = None,
    schedule_config: str = None,
    content_config: str = None,
) -> Dict:
    """
    Create a new automated campaign

    Args:
        campaign_type: Type of campaign
        chapter_name: Chapter name (None for organization-wide)
        title: Campaign title
        description: Campaign description
        schedule_config: JSON string of schedule configuration
        content_config: JSON string of content configuration

    Returns:
        Dict with creation result
    """
    # Check permissions
    if chapter_name and not frappe.has_permission("Chapter", "write", doc=chapter_name):
        frappe.throw(_("You don't have permission to create campaigns for this chapter"))

    if not chapter_name and not (
        "System Manager" in frappe.get_roles() or "Verenigingen Manager" in frappe.get_roles()
    ):
        frappe.throw(_("You don't have permission to create organization-wide campaigns"))

    try:
        # Parse JSON strings
        schedule_config = json.loads(schedule_config or "{}")
        content_config = json.loads(content_config or "{}")

        manager = AutomatedCampaignManager()
        return manager.create_campaign(
            campaign_type=campaign_type,
            chapter_name=chapter_name,
            title=title,
            description=description,
            schedule_config=schedule_config,
            content_config=content_config,
        )

    except json.JSONDecodeError:
        return {"success": False, "error": "Invalid JSON configuration"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_campaign_types() -> Dict:
    """Get available campaign types"""
    manager = AutomatedCampaignManager()
    return {"success": True, "campaign_types": manager.campaign_types}


@frappe.whitelist()
def get_active_campaigns(chapter_name: str = None) -> Dict:
    """Get active campaigns for a chapter or organization"""
    filters = {"status": "In Progress"}  # Use actual field for filtering active campaigns
    if chapter_name:
        filters["chapter"] = chapter_name

    campaigns = frappe.get_all(
        "Email Campaign",
        filters=filters,
        fields=[
            "name",
            "campaign_name",
            "email_campaign_for",
            "recipient",
            "sender",
            "start_date",
            "end_date",
            "status",
        ],
        order_by="creation desc",
    )

    return {"success": True, "campaigns": campaigns}


@frappe.whitelist()
def trigger_campaign_test(campaign_id: str) -> Dict:
    """Trigger a test run of a campaign"""
    # Check permissions
    campaign_doc = frappe.get_doc("Email Campaign", campaign_id)

    if campaign_doc.chapter and not frappe.has_permission("Chapter", "write", doc=campaign_doc.chapter):
        frappe.throw(_("You don't have permission to test this campaign"))

    if not campaign_doc.chapter and not (
        "System Manager" in frappe.get_roles() or "Verenigingen Manager" in frappe.get_roles()
    ):
        frappe.throw(_("You don't have permission to test organization-wide campaigns"))

    try:
        manager = AutomatedCampaignManager()
        campaign_data = {
            "name": campaign_doc.name,
            "campaign_name": campaign_doc.campaign_name,
            "campaign_type": campaign_doc.campaign_type,
            "chapter": campaign_doc.chapter,
            "template_id": campaign_doc.template_id,
            "segment": campaign_doc.segment,
            "content_config": campaign_doc.content_config,
        }

        return manager._execute_campaign(campaign_data)

    except Exception as e:
        return {"success": False, "error": str(e)}


# Scheduled function for automated campaigns
def process_scheduled_campaigns():
    """
    Process scheduled campaigns
    Add this to hooks.py scheduler_events
    """
    manager = AutomatedCampaignManager()
    return manager.process_scheduled_campaigns()
