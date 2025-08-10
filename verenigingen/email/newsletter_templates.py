#!/usr/bin/env python3
"""
Newsletter Templates System
Phase 3 Implementation - Pre-designed Email Templates

This module provides pre-designed newsletter templates for common communication scenarios
in the association management system.
"""

import json
from typing import Dict, List, Optional

import frappe
from frappe import _


class NewsletterTemplateManager:
    """Manager for newsletter templates and content generation"""

    def __init__(self):
        self.templates = self._load_templates()

    def _load_templates(self) -> Dict:
        """Load predefined newsletter templates"""
        return {
            "monthly_update": {
                "name": "Monthly Chapter Update",
                "category": "Chapter Communication",
                "subject_template": "Monthly Update - {chapter_name} - {month_year}",
                "content_template": self._get_monthly_update_template(),
                "variables": [
                    "chapter_name",
                    "month_year",
                    "highlights",
                    "upcoming_events",
                    "volunteer_spotlight",
                ],
            },
            "event_announcement": {
                "name": "Event Announcement",
                "category": "Events",
                "subject_template": "Join us: {event_title} - {event_date}",
                "content_template": self._get_event_announcement_template(),
                "variables": [
                    "event_title",
                    "event_date",
                    "event_location",
                    "event_description",
                    "registration_link",
                ],
            },
            "welcome_new_members": {
                "name": "Welcome New Members",
                "category": "Membership",
                "subject_template": "Welcome to {chapter_name}!",
                "content_template": self._get_welcome_template(),
                "variables": ["chapter_name", "new_member_names", "orientation_info", "contact_person"],
            },
            "volunteer_recruitment": {
                "name": "Volunteer Recruitment",
                "category": "Volunteers",
                "subject_template": "Volunteer Opportunity: {opportunity_title}",
                "content_template": self._get_volunteer_recruitment_template(),
                "variables": ["opportunity_title", "time_commitment", "skills_needed", "contact_info"],
            },
            "agm_invitation": {
                "name": "Annual General Meeting",
                "category": "Governance",
                "subject_template": "Annual General Meeting - {agm_date} - Your Attendance Required",
                "content_template": self._get_agm_invitation_template(),
                "variables": ["agm_date", "agm_time", "agm_location", "agenda_items", "voting_matters"],
            },
            "fundraising_campaign": {
                "name": "Fundraising Campaign",
                "category": "Fundraising",
                "subject_template": "Support Our Mission: {campaign_title}",
                "content_template": self._get_fundraising_template(),
                "variables": [
                    "campaign_title",
                    "campaign_goal",
                    "current_amount",
                    "deadline",
                    "donation_link",
                ],
            },
        }

    def _get_monthly_update_template(self) -> str:
        """Monthly update template with modern HTML design"""
        return """
        <div style="max-width: 600px; margin: 0 auto; font-family: Arial, sans-serif; line-height: 1.6;">
            <header style="background-color: #2e7d32; color: white; padding: 20px; text-align: center;">
                <h1 style="margin: 0; font-size: 24px;">Monthly Update</h1>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">{chapter_name} - {month_year}</p>
            </header>

            <div style="padding: 30px 20px; background-color: #ffffff;">
                <section style="margin-bottom: 30px;">
                    <h2 style="color: #2e7d32; border-bottom: 2px solid #4caf50; padding-bottom: 10px;">This Month's Highlights</h2>
                    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-top: 15px;">
                        {highlights}
                    </div>
                </section>

                <section style="margin-bottom: 30px;">
                    <h2 style="color: #2e7d32; border-bottom: 2px solid #4caf50; padding-bottom: 10px;">Upcoming Events</h2>
                    <div style="background-color: #e8f5e8; padding: 20px; border-radius: 8px; margin-top: 15px;">
                        {upcoming_events}
                    </div>
                </section>

                <section style="margin-bottom: 30px;">
                    <h2 style="color: #2e7d32; border-bottom: 2px solid #4caf50; padding-bottom: 10px;">Volunteer Spotlight</h2>
                    <div style="background-color: #fff3e0; padding: 20px; border-radius: 8px; margin-top: 15px;">
                        {volunteer_spotlight}
                    </div>
                </section>
            </div>

            <footer style="background-color: #f5f5f5; padding: 20px; text-align: center; color: #666;">
                <p style="margin: 0; font-size: 14px;">
                    Thank you for being part of {chapter_name}!
                </p>
                <p style="margin: 10px 0 0 0; font-size: 12px;">
                    <a href="#unsubscribe" style="color: #666; text-decoration: underline;">Unsubscribe</a> |
                    <a href="#preferences" style="color: #666; text-decoration: underline;">Email Preferences</a>
                </p>
            </footer>
        </div>
        """

    def _get_event_announcement_template(self) -> str:
        """Event announcement template"""
        return """
        <div style="max-width: 600px; margin: 0 auto; font-family: Arial, sans-serif; line-height: 1.6;">
            <header style="background-color: #1976d2; color: white; padding: 25px; text-align: center;">
                <h1 style="margin: 0; font-size: 28px;">You're Invited!</h1>
                <p style="margin: 10px 0 0 0; font-size: 18px; opacity: 0.9;">{event_title}</p>
            </header>

            <div style="padding: 30px 20px; background-color: #ffffff;">
                <div style="text-align: center; margin-bottom: 30px;">
                    <div style="background-color: #e3f2fd; padding: 20px; border-radius: 8px; display: inline-block;">
                        <h2 style="margin: 0; color: #1976d2; font-size: 24px;">{event_date}</h2>
                        <p style="margin: 5px 0 0 0; color: #666; font-size: 16px;">{event_location}</p>
                    </div>
                </div>

                <section style="margin-bottom: 30px;">
                    <h3 style="color: #1976d2;">Event Details</h3>
                    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px;">
                        {event_description}
                    </div>
                </section>

                <div style="text-align: center; margin-top: 30px;">
                    <a href="{registration_link}"
                       style="background-color: #1976d2; color: white; padding: 15px 30px;
                              text-decoration: none; border-radius: 25px; font-weight: bold;
                              display: inline-block; font-size: 16px;">
                        Register Now
                    </a>
                </div>
            </div>

            <footer style="background-color: #f5f5f5; padding: 20px; text-align: center; color: #666;">
                <p style="margin: 0; font-size: 14px;">We look forward to seeing you there!</p>
            </footer>
        </div>
        """

    def _get_welcome_template(self) -> str:
        """Welcome new members template"""
        return """
        <div style="max-width: 600px; margin: 0 auto; font-family: Arial, sans-serif; line-height: 1.6;">
            <header style="background-color: #4caf50; color: white; padding: 25px; text-align: center;">
                <h1 style="margin: 0; font-size: 28px;">Welcome to Our Community!</h1>
                <p style="margin: 10px 0 0 0; font-size: 18px; opacity: 0.9;">{chapter_name}</p>
            </header>

            <div style="padding: 30px 20px; background-color: #ffffff;">
                <section style="margin-bottom: 30px;">
                    <h2 style="color: #4caf50;">Welcome Our New Members!</h2>
                    <div style="background-color: #e8f5e8; padding: 20px; border-radius: 8px; margin-top: 15px;">
                        {new_member_names}
                    </div>
                </section>

                <section style="margin-bottom: 30px;">
                    <h3 style="color: #4caf50;">Getting Started</h3>
                    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px;">
                        {orientation_info}
                    </div>
                </section>

                <section style="margin-bottom: 30px;">
                    <h3 style="color: #4caf50;">Need Help?</h3>
                    <div style="background-color: #fff3e0; padding: 20px; border-radius: 8px;">
                        <p>If you have any questions, don't hesitate to reach out:</p>
                        {contact_person}
                    </div>
                </section>
            </div>

            <footer style="background-color: #f5f5f5; padding: 20px; text-align: center; color: #666;">
                <p style="margin: 0; font-size: 14px;">
                    Welcome to the {chapter_name} family!
                </p>
            </footer>
        </div>
        """

    def _get_volunteer_recruitment_template(self) -> str:
        """Volunteer recruitment template"""
        return """
        <div style="max-width: 600px; margin: 0 auto; font-family: Arial, sans-serif; line-height: 1.6;">
            <header style="background-color: #ff9800; color: white; padding: 25px; text-align: center;">
                <h1 style="margin: 0; font-size: 28px;">Make a Difference!</h1>
                <p style="margin: 10px 0 0 0; font-size: 18px; opacity: 0.9;">Volunteer Opportunity</p>
            </header>

            <div style="padding: 30px 20px; background-color: #ffffff;">
                <section style="margin-bottom: 30px;">
                    <h2 style="color: #ff9800; text-align: center; font-size: 24px;">{opportunity_title}</h2>
                </section>

                <section style="margin-bottom: 30px;">
                    <h3 style="color: #ff9800;">Time Commitment</h3>
                    <div style="background-color: #fff3e0; padding: 20px; border-radius: 8px;">
                        {time_commitment}
                    </div>
                </section>

                <section style="margin-bottom: 30px;">
                    <h3 style="color: #ff9800;">Skills Needed</h3>
                    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px;">
                        {skills_needed}
                    </div>
                </section>

                <section style="margin-bottom: 30px;">
                    <h3 style="color: #ff9800;">Get Involved</h3>
                    <div style="background-color: #e8f5e8; padding: 20px; border-radius: 8px;">
                        <p>Ready to volunteer? Contact us:</p>
                        {contact_info}
                    </div>
                </section>

                <div style="text-align: center; margin-top: 30px;">
                    <a href="mailto:{contact_email}"
                       style="background-color: #ff9800; color: white; padding: 15px 30px;
                              text-decoration: none; border-radius: 25px; font-weight: bold;
                              display: inline-block; font-size: 16px;">
                        Volunteer Today
                    </a>
                </div>
            </div>

            <footer style="background-color: #f5f5f5; padding: 20px; text-align: center; color: #666;">
                <p style="margin: 0; font-size: 14px;">Your contribution makes our mission possible!</p>
            </footer>
        </div>
        """

    def _get_agm_invitation_template(self) -> str:
        """AGM invitation template"""
        return """
        <div style="max-width: 600px; margin: 0 auto; font-family: Arial, sans-serif; line-height: 1.6;">
            <header style="background-color: #d32f2f; color: white; padding: 25px; text-align: center;">
                <h1 style="margin: 0; font-size: 28px;">IMPORTANT NOTICE</h1>
                <p style="margin: 10px 0 0 0; font-size: 18px; opacity: 0.9;">Annual General Meeting</p>
            </header>

            <div style="padding: 30px 20px; background-color: #ffffff;">
                <div style="background-color: #ffebee; padding: 20px; border-radius: 8px; margin-bottom: 30px; border-left: 4px solid #d32f2f;">
                    <h2 style="margin: 0 0 10px 0; color: #d32f2f;">Your Attendance is Required</h2>
                    <p style="margin: 0; font-weight: bold;">As a member, your participation in our Annual General Meeting is important for our organization's governance.</p>
                </div>

                <section style="margin-bottom: 30px;">
                    <h3 style="color: #d32f2f;">Meeting Details</h3>
                    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px;">
                        <p><strong>Date:</strong> {agm_date}</p>
                        <p><strong>Time:</strong> {agm_time}</p>
                        <p><strong>Location:</strong> {agm_location}</p>
                    </div>
                </section>

                <section style="margin-bottom: 30px;">
                    <h3 style="color: #d32f2f;">Agenda Items</h3>
                    <div style="background-color: #fff3e0; padding: 20px; border-radius: 8px;">
                        {agenda_items}
                    </div>
                </section>

                <section style="margin-bottom: 30px;">
                    <h3 style="color: #d32f2f;">Voting Matters</h3>
                    <div style="background-color: #ffebee; padding: 20px; border-radius: 8px;">
                        {voting_matters}
                    </div>
                </section>
            </div>

            <footer style="background-color: #f5f5f5; padding: 20px; text-align: center; color: #666;">
                <p style="margin: 0; font-size: 14px; font-weight: bold;">
                    This is a legal requirement for all members. Thank you for your participation.
                </p>
            </footer>
        </div>
        """

    def _get_fundraising_template(self) -> str:
        """Fundraising campaign template"""
        return """
        <div style="max-width: 600px; margin: 0 auto; font-family: Arial, sans-serif; line-height: 1.6;">
            <header style="background-color: #7b1fa2; color: white; padding: 25px; text-align: center;">
                <h1 style="margin: 0; font-size: 28px;">Support Our Mission</h1>
                <p style="margin: 10px 0 0 0; font-size: 18px; opacity: 0.9;">{campaign_title}</p>
            </header>

            <div style="padding: 30px 20px; background-color: #ffffff;">
                <section style="margin-bottom: 30px; text-align: center;">
                    <div style="background-color: #f3e5f5; padding: 25px; border-radius: 8px; display: inline-block;">
                        <h2 style="margin: 0; color: #7b1fa2; font-size: 32px;">€{current_amount}</h2>
                        <p style="margin: 5px 0 0 0; color: #666;">raised of €{campaign_goal} goal</p>
                        <div style="background-color: #e0e0e0; height: 10px; border-radius: 5px; margin: 15px 0; width: 200px;">
                            <div style="background-color: #7b1fa2; height: 100%; border-radius: 5px; width: {progress_percentage}%;"></div>
                        </div>
                    </div>
                </section>

                <section style="margin-bottom: 30px;">
                    <h3 style="color: #7b1fa2;">Why We Need Your Support</h3>
                    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px;">
                        <p>Your contribution directly supports our mission and helps us continue making a positive impact in our community.</p>
                    </div>
                </section>

                <section style="margin-bottom: 30px;">
                    <h3 style="color: #7b1fa2;">Campaign Deadline</h3>
                    <div style="background-color: #fff3e0; padding: 20px; border-radius: 8px;">
                        <p><strong>Time remaining:</strong> {deadline}</p>
                        <p>Every donation counts - no matter the size!</p>
                    </div>
                </section>

                <div style="text-align: center; margin-top: 30px;">
                    <a href="{donation_link}"
                       style="background-color: #7b1fa2; color: white; padding: 15px 30px;
                              text-decoration: none; border-radius: 25px; font-weight: bold;
                              display: inline-block; font-size: 16px;">
                        Donate Now
                    </a>
                </div>
            </div>

            <footer style="background-color: #f5f5f5; padding: 20px; text-align: center; color: #666;">
                <p style="margin: 0; font-size: 14px;">Thank you for supporting our cause!</p>
            </footer>
        </div>
        """

    def get_template(self, template_id: str) -> Optional[Dict]:
        """Get a specific template by ID"""
        return self.templates.get(template_id)

    def list_templates(self, category: str = None) -> List[Dict]:
        """List available templates, optionally filtered by category"""
        templates = []
        for template_id, template_data in self.templates.items():
            if category is None or template_data.get("category") == category:
                templates.append(
                    {"id": template_id, "name": template_data["name"], "category": template_data["category"]}
                )
        return templates

    def render_template(self, template_id: str, variables: Dict) -> Optional[Dict]:
        """
        Render a template with provided variables

        Args:
            template_id: Template identifier
            variables: Dictionary of variables to substitute

        Returns:
            Dict with rendered subject and content, or None if template not found
        """
        template = self.get_template(template_id)
        if not template:
            return None

        # Render subject with safe formatting
        try:
            # Sanitize variables before formatting
            sanitized_variables = {k: self._sanitize_template_value(str(v)) for k, v in variables.items()}
            rendered_subject = template["subject_template"].format(**sanitized_variables)
        except KeyError:
            # Handle missing variables gracefully
            rendered_subject = template["subject_template"]
            for var, value in variables.items():
                # Sanitize subject variables too
                sanitized_value = self._sanitize_template_value(str(value))
                rendered_subject = rendered_subject.replace(f"{{{var}}}", sanitized_value)
            # Replace any remaining placeholders with empty strings
            import re

            rendered_subject = re.sub(r"\{[^}]+\}", "", rendered_subject)

        # Render content with sanitization
        rendered_content = template["content_template"]
        for var, value in variables.items():
            # Sanitize input to prevent XSS attacks
            sanitized_value = self._sanitize_template_value(str(value))
            rendered_content = rendered_content.replace(f"{{{var}}}", sanitized_value)

        return {"subject": rendered_subject, "content": rendered_content, "template_name": template["name"]}

    def _sanitize_template_value(self, value: str) -> str:
        """
        Sanitize template values to prevent XSS attacks

        Args:
            value: Raw input value

        Returns:
            Sanitized value safe for HTML rendering
        """
        import html

        # HTML escape dangerous characters
        sanitized = html.escape(value, quote=True)

        # Additional sanitization for common attack vectors
        dangerous_patterns = [
            ("<script", "&lt;script"),
            ("</script>", "&lt;/script&gt;"),
            ("javascript:", "javascript-blocked:"),
            ("vbscript:", "vbscript-blocked:"),
            ("onload=", "onload-blocked="),
            ("onerror=", "onerror-blocked="),
            ("onclick=", "onclick-blocked="),
        ]

        for pattern, replacement in dangerous_patterns:
            sanitized = sanitized.replace(pattern.lower(), replacement)
            sanitized = sanitized.replace(pattern.upper(), replacement)

        return sanitized


# API Functions
@frappe.whitelist()
def get_newsletter_templates(category: str = None) -> Dict:
    """
    Get available newsletter templates

    Args:
        category: Optional category filter

    Returns:
        Dict with templates list
    """
    manager = NewsletterTemplateManager()
    templates = manager.list_templates(category)

    return {
        "success": True,
        "templates": templates,
        "categories": [
            "Chapter Communication",
            "Events",
            "Membership",
            "Volunteers",
            "Governance",
            "Fundraising",
        ],
    }


@frappe.whitelist()
def get_template_details(template_id: str) -> Dict:
    """
    Get detailed information about a specific template

    Args:
        template_id: Template identifier

    Returns:
        Dict with template details
    """
    manager = NewsletterTemplateManager()
    template = manager.get_template(template_id)

    if not template:
        return {"success": False, "error": "Template not found"}

    return {"success": True, "template": template}


@frappe.whitelist()
def preview_template(template_id: str, variables: str) -> Dict:
    """
    Preview a rendered template

    Args:
        template_id: Template identifier
        variables: JSON string of variables

    Returns:
        Dict with rendered template
    """
    try:
        # Parse variables
        if isinstance(variables, str):
            variables = json.loads(variables)

        manager = NewsletterTemplateManager()
        rendered = manager.render_template(template_id, variables)

        if not rendered:
            return {"success": False, "error": "Template not found"}

        return {"success": True, "preview": rendered}

    except json.JSONDecodeError:
        return {"success": False, "error": "Invalid variables JSON"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def send_templated_email(
    template_id: str, variables: str, chapter_name: str = None, segment: str = "all"
) -> Dict:
    """
    Send a templated email

    Args:
        template_id: Template identifier
        variables: JSON string of variables
        chapter_name: Chapter name (for chapter emails)
        segment: Target segment

    Returns:
        Dict with send results
    """
    # Check permissions
    if chapter_name and not frappe.has_permission("Chapter", "write", doc=chapter_name):
        frappe.throw(_("You don't have permission to send emails for this chapter"))

    try:
        # Parse variables
        if isinstance(variables, str):
            variables = json.loads(variables)

        # Render template
        manager = NewsletterTemplateManager()
        rendered = manager.render_template(template_id, variables)

        if not rendered:
            return {"success": False, "error": "Template not found"}

        # Send email using SimplifiedEmailManager
        if chapter_name:
            from verenigingen.email.simplified_email_manager import SimplifiedEmailManager

            chapter_doc = frappe.get_doc("Chapter", chapter_name)
            email_manager = SimplifiedEmailManager(chapter_doc)

            result = email_manager.send_to_chapter_segment(
                chapter_name=chapter_name,
                segment=segment,
                subject=rendered["subject"],
                content=rendered["content"],
            )
        else:
            # Organization-wide email
            if not ("System Manager" in frappe.get_roles() or "Verenigingen Manager" in frappe.get_roles()):
                frappe.throw(_("You don't have permission to send organization-wide emails"))

            # CIRCULAR IMPORT FIX: Import at function level to avoid circular import
            from verenigingen.email.simplified_email_manager import SimplifiedEmailManager

            # Use SimplifiedEmailManager directly instead of the API wrapper
            chapters = frappe.get_all("Chapter", limit=1)
            if not chapters:
                return {"success": False, "error": "No chapters found"}

            chapter_doc = frappe.get_doc("Chapter", chapters[0].name)
            email_manager = SimplifiedEmailManager(chapter_doc)

            result = email_manager.send_organization_wide(
                filters=None, subject=rendered["subject"], content=rendered["content"]
            )

        return result

    except json.JSONDecodeError:
        return {"success": False, "error": "Invalid variables JSON"}
    except Exception as e:
        frappe.log_error(f"Error sending templated email: {str(e)}", "Newsletter Templates")
        return {"success": False, "error": str(e)}
