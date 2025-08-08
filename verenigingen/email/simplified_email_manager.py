#!/usr/bin/env python3
"""
Simplified Email Manager for Newsletter Functionality
Phase 2 Implementation - Email/Newsletter Infrastructure

This module provides a simplified approach to sending newsletters and bulk emails
to various member segments, leveraging the existing CommunicationManager and
Frappe's Newsletter module.
"""

from typing import Dict, List, Optional

import frappe
from frappe import _

from verenigingen.verenigingen.doctype.chapter.managers.communication_manager import CommunicationManager


class SimplifiedEmailManager(CommunicationManager):
    """Minimal enhancement using existing infrastructure for bulk email sending"""

    def send_to_chapter_segment(
        self,
        chapter_name: str,
        segment: str = "all",
        subject: str = None,
        content: str = None,
        test_mode: bool = False,
    ) -> Dict:
        """
        Send email to specific chapter segments using direct queries

        Args:
            chapter_name: Name of the chapter
            segment: Target segment ('all', 'board', 'volunteers')
            subject: Email subject
            content: Email content (HTML)
            test_mode: If True, only return recipient count without sending

        Returns:
            Dict with success status and details
        """
        # Build recipient query based on segment
        if segment == "all":
            recipients = frappe.db.sql_list(
                """
                SELECT DISTINCT m.email
                FROM `tabMember` m
                INNER JOIN `tabChapter Member` cm ON m.name = cm.member
                WHERE cm.parent = %s
                    AND cm.enabled = 1
                    AND m.status = 'Active'
                    AND m.email IS NOT NULL
                    AND (m.opt_out_optional_emails IS NULL OR m.opt_out_optional_emails = 0)  -- FIELD FIX: Handle NULL values properly
            """,
                chapter_name,
            )

        elif segment == "board":
            recipients = frappe.db.sql_list(
                """
                SELECT DISTINCT m.email
                FROM `tabChapter Board Member` cbm
                INNER JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                INNER JOIN `tabMember` m ON v.member = m.name
                WHERE cbm.parent = %s
                    AND cbm.is_active = 1
                    AND m.email IS NOT NULL
                    AND (m.opt_out_optional_emails IS NULL OR m.opt_out_optional_emails = 0)  -- FIELD FIX: Handle NULL values properly
            """,
                chapter_name,
            )

        elif segment == "volunteers":
            recipients = frappe.db.sql_list(
                """
                SELECT DISTINCT m.email
                FROM `tabVolunteer` v
                INNER JOIN `tabMember` m ON v.member = m.name
                INNER JOIN `tabChapter Member` cm ON m.name = cm.member
                WHERE cm.parent = %s
                    AND v.status = 'Active'
                    AND m.email IS NOT NULL
                    AND (m.opt_out_optional_emails IS NULL OR m.opt_out_optional_emails = 0)  -- FIELD FIX: Handle NULL values properly
            """,
                chapter_name,
            )
        else:
            return {"success": False, "error": f"Unknown segment: {segment}"}

        if not recipients:
            return {"success": False, "error": "No eligible recipients found"}

        # If test mode, just return the count
        if test_mode:
            return {
                "success": True,
                "test_mode": True,
                "recipients_count": len(recipients),
                "segment": segment,
            }

        # Use Newsletter module for actual sending
        try:
            newsletter = frappe.get_doc(
                {
                    "doctype": "Newsletter",
                    "subject": subject or f"Newsletter from {chapter_name}",
                    "content_type": "Rich Text",
                    "message": content,
                    "send_from": frappe.session.user,
                    "schedule_send": 0,  # Send immediately
                }
            )

            # Add recipients directly
            for email in recipients:
                newsletter.append("recipients", {"email": email})

            newsletter.save()

            # Queue for sending
            if not frappe.flags.in_test:
                newsletter.queue_all()

            return {
                "success": True,
                "recipients_count": len(recipients),
                "newsletter": newsletter.name,
                "segment": segment,
            }

        except Exception as e:
            frappe.log_error(f"Error sending chapter email: {str(e)}", "SimplifiedEmailManager")
            return {"success": False, "error": str(e)}

    def send_organization_wide(
        self, filters: Dict = None, subject: str = None, content: str = None, test_mode: bool = False
    ) -> Dict:
        """
        Send email to all members matching filters

        Args:
            filters: Frappe filters for Member DocType
            subject: Email subject
            content: Email content (HTML)
            test_mode: If True, only return recipient count without sending

        Returns:
            Dict with success status and details
        """
        # Default to active members with emails
        if not filters:
            filters = {"status": "Active", "email": ["!=", ""]}

        # Add opt-out check to filters
        filters["opt_out_optional_emails"] = ["!=", 1]

        # Get eligible members
        members = frappe.db.get_all("Member", filters=filters, fields=["email"], limit=10000)  # Safety limit

        eligible_emails = [m.email for m in members if m.email]

        if not eligible_emails:
            return {"success": False, "error": "No eligible recipients"}

        # If test mode, just return the count
        if test_mode:
            return {"success": True, "test_mode": True, "recipients_count": len(eligible_emails)}

        # Send via Newsletter
        try:
            newsletter = frappe.get_doc(
                {
                    "doctype": "Newsletter",
                    "subject": subject or "Organization Newsletter",
                    "content_type": "Rich Text",
                    "message": content,
                    "send_from": frappe.session.user,
                    "schedule_send": 0,  # Send immediately
                }
            )

            for email in eligible_emails:
                newsletter.append("recipients", {"email": email})

            newsletter.save()

            # Queue for sending
            if not frappe.flags.in_test:
                newsletter.queue_all()

            return {"success": True, "recipients_count": len(eligible_emails), "newsletter": newsletter.name}

        except Exception as e:
            frappe.log_error(f"Error sending organization-wide email: {str(e)}", "SimplifiedEmailManager")
            return {"success": False, "error": str(e)}

    def get_segment_preview(self, chapter_name: str, segment: str = "all") -> Dict:
        """
        Get a preview of recipients for a segment without sending

        Args:
            chapter_name: Name of the chapter
            segment: Target segment

        Returns:
            Dict with recipient count and sample emails
        """
        result = self.send_to_chapter_segment(chapter_name=chapter_name, segment=segment, test_mode=True)

        if result.get("success"):
            # Get sample recipients for preview
            if segment == "all":
                sample_recipients = frappe.db.sql(
                    """
                    SELECT m.full_name, m.email
                    FROM `tabMember` m
                    INNER JOIN `tabChapter Member` cm ON m.name = cm.member
                    WHERE cm.parent = %s
                        AND cm.enabled = 1
                        AND m.status = 'Active'
                        AND m.email IS NOT NULL
                        AND (m.opt_out_optional_emails IS NULL OR m.opt_out_optional_emails = 0)  -- FIELD FIX: Handle NULL values properly
                    LIMIT 5
                """,
                    chapter_name,
                    as_dict=True,
                )
            elif segment == "board":
                sample_recipients = frappe.db.sql(
                    """
                    SELECT m.full_name, m.email, cbm.chapter_role
                    FROM `tabChapter Board Member` cbm
                    INNER JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                    INNER JOIN `tabMember` m ON v.member = m.name
                    WHERE cbm.parent = %s
                        AND cbm.is_active = 1
                        AND m.email IS NOT NULL
                        AND (m.opt_out_optional_emails IS NULL OR m.opt_out_optional_emails = 0)  -- FIELD FIX: Handle NULL values properly
                    LIMIT 5
                """,
                    chapter_name,
                    as_dict=True,
                )
            elif segment == "volunteers":
                sample_recipients = frappe.db.sql(
                    """
                    SELECT m.full_name, m.email
                    FROM `tabVolunteer` v
                    INNER JOIN `tabMember` m ON v.member = m.name
                    INNER JOIN `tabChapter Member` cm ON m.name = cm.member
                    WHERE cm.parent = %s
                        AND v.status = 'Active'
                        AND m.email IS NOT NULL
                        AND (m.opt_out_optional_emails IS NULL OR m.opt_out_optional_emails = 0)  -- FIELD FIX: Handle NULL values properly
                    LIMIT 5
                """,
                    chapter_name,
                    as_dict=True,
                )
            else:
                sample_recipients = []

            result["sample_recipients"] = sample_recipients

        return result


# Whitelisted API functions
@frappe.whitelist()
def send_chapter_email(chapter_name: str, segment: str, subject: str, content: str) -> Dict:
    """
    API endpoint for sending chapter emails

    Args:
        chapter_name: Name of the chapter
        segment: Target segment ('all', 'board', 'volunteers')
        subject: Email subject
        content: Email content (HTML)

    Returns:
        Dict with success status and details
    """
    # Check permissions
    if not frappe.has_permission("Chapter", "write", doc=chapter_name):
        frappe.throw(_("You don't have permission to send emails for this chapter"))

    # Initialize manager with chapter doc
    chapter_doc = frappe.get_doc("Chapter", chapter_name)
    manager = SimplifiedEmailManager(chapter_doc)

    return manager.send_to_chapter_segment(
        chapter_name=chapter_name, segment=segment, subject=subject, content=content
    )


@frappe.whitelist()
def get_segment_recipient_count(chapter_name: str, segment: str) -> Dict:
    """
    Get recipient count for a segment

    Args:
        chapter_name: Name of the chapter
        segment: Target segment

    Returns:
        Dict with recipient count
    """
    # Check permissions
    if not frappe.has_permission("Chapter", "read", doc=chapter_name):
        frappe.throw(_("You don't have permission to view this chapter"))

    # Initialize manager with chapter doc
    chapter_doc = frappe.get_doc("Chapter", chapter_name)
    manager = SimplifiedEmailManager(chapter_doc)

    return manager.get_segment_preview(chapter_name, segment)


@frappe.whitelist()
def send_organization_newsletter(subject: str, content: str, filters: Dict = None) -> Dict:
    """
    Send organization-wide newsletter

    Args:
        subject: Email subject
        content: Email content (HTML)
        filters: Optional filters for recipients

    Returns:
        Dict with success status and details
    """
    # Check permissions - only System Manager or Verenigingen Manager
    if not ("System Manager" in frappe.get_roles() or "Verenigingen Manager" in frappe.get_roles()):
        frappe.throw(_("You don't have permission to send organization-wide emails"))

    # Use a dummy chapter doc for initialization (manager doesn't really need it for org-wide)
    chapters = frappe.get_all("Chapter", limit=1)
    if not chapters:
        frappe.throw(_("No chapters found"))

    chapter_doc = frappe.get_doc("Chapter", chapters[0].name)
    manager = SimplifiedEmailManager(chapter_doc)

    return manager.send_organization_wide(filters=filters, subject=subject, content=content)
