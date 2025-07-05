# verenigingen/verenigingen/doctype/chapter/managers/communication_manager.py

from typing import Dict, List

import frappe
from frappe import _

from .base_manager import BaseManager


class CommunicationManager(BaseManager):
    """Manager for all chapter communications and notifications"""

    def __init__(self, chapter_doc):
        super().__init__(chapter_doc)
        self.email_settings = self._load_email_settings()
        self.template_cache = {}

    def notify_board_member_added(self, volunteer: str, role: str) -> bool:
        """
        Send notification when a volunteer is added to the board

        Args:
            volunteer: Volunteer ID
            role: Chapter role name

        Returns:
            bool: Whether notification was sent successfully
        """
        try:
            volunteer_doc = frappe.get_doc("Volunteer", volunteer)

            if not volunteer_doc.member:
                self.log_action("No member associated with volunteer", {"volunteer": volunteer}, "warning")
                return False

            member_doc = frappe.get_doc("Member", volunteer_doc.member)

            if not member_doc.email:
                self.log_action("No email address for member", {"member": member_doc.name}, "warning")
                return False

            # Get email template
            template = self._get_email_template("board_member_added")
            if not template:
                self.log_action("Email template 'board_member_added' not found", level="warning")
                return False

            # Prepare context for email
            context = {
                "member": member_doc,
                "volunteer": volunteer_doc,
                "chapter": self.chapter_doc,
                "role": role,
                "chapter_name": self.chapter_name,
            }

            # Send email
            return self._send_templated_email(
                template=template,
                recipients=[member_doc.email],
                subject=_("Board Role Assignment: {0}").format(self.chapter_name),
                context=context,
                reference_doctype="Chapter",
                reference_name=self.chapter_name,
            )

        except Exception as e:
            self.log_action(
                "Failed to send board member added notification",
                {"volunteer": volunteer, "role": role, "error": str(e)},
                "error",
            )
            return False

    def notify_board_member_removed(self, volunteer: str, reason: str = None) -> bool:
        """
        Send notification when a volunteer is removed from the board

        Args:
            volunteer: Volunteer ID
            reason: Reason for removal

        Returns:
            bool: Whether notification was sent successfully
        """
        try:
            volunteer_doc = frappe.get_doc("Volunteer", volunteer)

            if not volunteer_doc.member:
                return False

            member_doc = frappe.get_doc("Member", volunteer_doc.member)

            if not member_doc.email:
                return False

            # Get email template
            template = self._get_email_template("board_member_removed")
            if not template:
                return False

            # Prepare context for email
            context = {
                "member": member_doc,
                "volunteer": volunteer_doc,
                "chapter": self.chapter_doc,
                "reason": reason,
                "chapter_name": self.chapter_name,
            }

            # Send email
            return self._send_templated_email(
                template=template,
                recipients=[member_doc.email],
                subject=_("Board Role Ended: {0}").format(self.chapter_name),
                context=context,
                reference_doctype="Chapter",
                reference_name=self.chapter_name,
            )

        except Exception as e:
            self.log_action(
                "Failed to send board member removed notification",
                {"volunteer": volunteer, "error": str(e)},
                "error",
            )
            return False

    def notify_role_transition(self, volunteer: str, old_role: str, new_role: str) -> bool:
        """
        Send notification for board role transition

        Args:
            volunteer: Volunteer ID
            old_role: Previous role
            new_role: New role

        Returns:
            bool: Whether notification was sent successfully
        """
        try:
            volunteer_doc = frappe.get_doc("Volunteer", volunteer)

            if not volunteer_doc.member:
                return False

            member_doc = frappe.get_doc("Member", volunteer_doc.member)

            if not member_doc.email:
                return False

            # Get email template
            template = self._get_email_template("board_role_transition")
            if not template:
                # Fallback to generic template
                template = self._get_email_template("board_member_added")
                if not template:
                    return False

            # Prepare context for email
            context = {
                "member": member_doc,
                "volunteer": volunteer_doc,
                "chapter": self.chapter_doc,
                "old_role": old_role,
                "new_role": new_role,
                "chapter_name": self.chapter_name,
                "transition_type": "role_change",
            }

            # Send email
            return self._send_templated_email(
                template=template,
                recipients=[member_doc.email],
                subject=_("Role Transition: {0}").format(self.chapter_name),
                context=context,
                reference_doctype="Chapter",
                reference_name=self.chapter_name,
            )

        except Exception as e:
            self.log_action(
                "Failed to send role transition notification",
                {"volunteer": volunteer, "old_role": old_role, "new_role": new_role, "error": str(e)},
                "error",
            )
            return False

    def notify_member_added(self, member_id: str) -> bool:
        """
        Send notification when member is added to chapter

        Args:
            member_id: Member ID

        Returns:
            bool: Whether notification was sent successfully
        """
        try:
            member_doc = frappe.get_doc("Member", member_id)

            if not member_doc.email:
                return False

            # Get email template
            template = self._get_email_template("member_added_to_chapter")
            if not template:
                return False

            # Prepare context for email
            context = {"member": member_doc, "chapter": self.chapter_doc, "chapter_name": self.chapter_name}

            # Send email
            return self._send_templated_email(
                template=template,
                recipients=[member_doc.email],
                subject=_("Welcome to {0}").format(self.chapter_name),
                context=context,
                reference_doctype="Chapter",
                reference_name=self.chapter_name,
            )

        except Exception as e:
            self.log_action(
                "Failed to send member added notification", {"member": member_id, "error": str(e)}, "error"
            )
            return False

    def notify_member_removed(self, member_id: str, reason: str = None) -> bool:
        """
        Send notification when member is removed from chapter

        Args:
            member_id: Member ID
            reason: Reason for removal

        Returns:
            bool: Whether notification was sent successfully
        """
        try:
            member_doc = frappe.get_doc("Member", member_id)

            if not member_doc.email:
                return False

            # Get email template
            template = self._get_email_template("member_removed_from_chapter")
            if not template:
                return False

            # Prepare context for email
            context = {
                "member": member_doc,
                "chapter": self.chapter_doc,
                "reason": reason,
                "chapter_name": self.chapter_name,
            }

            # Send email
            return self._send_templated_email(
                template=template,
                recipients=[member_doc.email],
                subject=_("Chapter Membership Update: {0}").format(self.chapter_name),
                context=context,
                reference_doctype="Chapter",
                reference_name=self.chapter_name,
            )

        except Exception as e:
            self.log_action(
                "Failed to send member removed notification", {"member": member_id, "error": str(e)}, "error"
            )
            return False

    def send_bulk_notification(
        self, template_name: str, recipients: List[str], subject: str, context: Dict, batch_size: int = 50
    ) -> Dict:
        """
        Send bulk notifications using template

        Args:
            template_name: Email template name
            recipients: List of email addresses
            subject: Email subject
            context: Template context
            batch_size: Number of emails per batch

        Returns:
            Dict with send results
        """
        if not recipients:
            return {"success": False, "error": "No recipients specified"}

        template = self._get_email_template(template_name)
        if not template:
            return {"success": False, "error": f"Template '{template_name}' not found"}

        sent_count = 0
        errors = []

        # Process in batches
        for i in range(0, len(recipients), batch_size):
            batch = recipients[i : i + batch_size]

            try:
                success = self._send_templated_email(
                    template=template,
                    recipients=batch,
                    subject=subject,
                    context=context,
                    reference_doctype="Chapter",
                    reference_name=self.chapter_name,
                )

                if success:
                    sent_count += len(batch)
                else:
                    errors.append(f"Failed to send batch {i // batch_size + 1}")

            except Exception as e:
                errors.append(f"Error in batch {i // batch_size + 1}: {str(e)}")

        self.log_action(
            "Bulk notification sent",
            {
                "template": template_name,
                "total_recipients": len(recipients),
                "sent_count": sent_count,
                "error_count": len(errors),
            },
        )

        return {
            "success": True,
            "sent_count": sent_count,
            "total_recipients": len(recipients),
            "errors": errors,
        }

    def send_chapter_newsletter(self, subject: str, content: str, recipient_filter: str = "all") -> Dict:
        """
        Send newsletter to chapter members

        Args:
            subject: Newsletter subject
            content: Newsletter content
            recipient_filter: Filter for recipients ("all", "board", "members")

        Returns:
            Dict with send results
        """
        try:
            # Get recipients based on filter
            recipients = self._get_newsletter_recipients(recipient_filter)

            if not recipients:
                return {"success": False, "error": "No recipients found"}

            # Prepare context
            context = {
                "chapter": self.chapter_doc,
                "chapter_name": self.chapter_name,
                "newsletter_content": content,
                "unsubscribe_url": self._generate_unsubscribe_url(),
            }

            # Send newsletter
            result = self.send_bulk_notification(
                template_name="chapter_newsletter", recipients=recipients, subject=subject, context=context
            )

            # Log newsletter activity
            self.create_comment(
                "Info",
                _("Newsletter sent: '{0}' to {1} recipients").format(subject, result.get("sent_count", 0)),
            )

            return result

        except Exception as e:
            self.log_action(
                "Failed to send newsletter",
                {"subject": subject, "recipient_filter": recipient_filter, "error": str(e)},
                "error",
            )
            return {"success": False, "error": str(e)}

    def create_email_communication(
        self, recipients: List[str], subject: str, content: str, communication_type: str = "Email"
    ) -> str:
        """
        Create communication record for tracking

        Args:
            recipients: List of recipients
            subject: Email subject
            content: Email content
            communication_type: Type of communication

        Returns:
            Communication document name
        """
        try:
            communication = frappe.get_doc(
                {
                    "doctype": "Communication",
                    "communication_type": communication_type,
                    "communication_medium": "Email",
                    "subject": subject,
                    "content": content,
                    "status": "Sent",
                    "reference_doctype": "Chapter",
                    "reference_name": self.chapter_name,
                    "recipients": "\n".join(recipients),
                    "sent_or_received": "Sent",
                }
            )

            communication.insert(ignore_permissions=True)

            self.log_action(
                "Communication record created",
                {
                    "communication": communication.name,
                    "recipients_count": len(recipients),
                    "subject": subject,
                },
            )

            return communication.name

        except Exception as e:
            self.log_action(
                "Failed to create communication record", {"subject": subject, "error": str(e)}, "error"
            )
            return None

    def get_communication_history(self, limit: int = 50) -> List[Dict]:
        """
        Get chapter communication history

        Args:
            limit: Maximum number of records to return

        Returns:
            List of communication records
        """
        try:
            communications = frappe.get_all(
                "Communication",
                filters={"reference_doctype": "Chapter", "reference_name": self.chapter_name},
                fields=["name", "subject", "communication_type", "creation", "status", "recipients"],
                order_by="creation desc",
                limit=limit,
            )

            return communications

        except Exception as e:
            self.log_action("Error fetching communication history", {"error": str(e)}, "error")
            return []

    def get_summary(self) -> Dict:
        """
        Get summary of communication activities

        Returns:
            Dict with communication summary
        """
        try:
            # Get recent communications
            recent_comms = self.get_communication_history(limit=10)

            # Count by type
            comm_counts = {}
            for comm in recent_comms:
                comm_type = comm.get("communication_type", "Unknown")
                comm_counts[comm_type] = comm_counts.get(comm_type, 0) + 1

            # Get pending notifications (if any tracking system exists)
            pending_count = 0  # This would need actual implementation

            return {
                "recent_communications": len(recent_comms),
                "communication_types": comm_counts,
                "pending_notifications": pending_count,
                "email_settings_valid": self._validate_email_settings(),
                "last_communication": recent_comms[0].get("creation") if recent_comms else None,
            }

        except Exception as e:
            self.log_action("Error generating communication summary", {"error": str(e)}, "error")
            return {"error": str(e), "recent_communications": 0}

    # Private helper methods

    def _load_email_settings(self) -> Dict:
        """Load email settings from system"""
        try:
            settings = frappe.get_single("Email Account")
            return {
                "smtp_server": settings.get("smtp_server"),
                "port": settings.get("port"),
                "use_tls": settings.get("use_tls"),
                "email_id": settings.get("email_id"),
            }
        except Exception:
            return {}

    def _get_email_template(self, template_name: str):
        """Get email template with caching"""
        if template_name not in self.template_cache:
            try:
                if frappe.db.exists("Email Template", template_name):
                    self.template_cache[template_name] = frappe.get_doc("Email Template", template_name)
                else:
                    self.template_cache[template_name] = None
            except Exception:
                self.template_cache[template_name] = None

        return self.template_cache[template_name]

    def _send_templated_email(
        self,
        template,
        recipients: List[str],
        subject: str,
        context: Dict,
        reference_doctype: str = None,
        reference_name: str = None,
    ) -> bool:
        """Send email using template"""
        try:
            # Prepare email content
            if hasattr(template, "response"):
                content = frappe.render_template(template.response, context)
            else:
                content = frappe.render_template(template.message, context)

            # Send email
            frappe.sendmail(
                recipients=recipients,
                subject=subject,
                message=content,
                reference_doctype=reference_doctype,
                reference_name=reference_name,
                header=[_("Chapter Notification"), "blue"],
            )

            # Create communication record
            self.create_email_communication(recipients, subject, content)

            self.log_action(
                f"Email sent using template {template.name}",
                {"recipients_count": len(recipients), "subject": subject},
            )

            return True

        except Exception as e:
            self.log_action(
                "Failed to send templated email",
                {
                    "template": template.name if template else "None",
                    "recipients_count": len(recipients),
                    "error": str(e),
                },
                "error",
            )
            return False

    def _get_newsletter_recipients(self, filter_type: str) -> List[str]:
        """Get recipients for newsletter based on filter"""
        recipients = []

        try:
            if filter_type == "all":
                # All chapter members
                for member in self.chapter_doc.members or []:
                    if member.enabled:
                        member_doc = frappe.get_doc("Member", member.member)
                        if member_doc.email:
                            recipients.append(member_doc.email)

                # All board members
                for board_member in self.chapter_doc.board_members or []:
                    if board_member.is_active and board_member.email:
                        recipients.append(board_member.email)

            elif filter_type == "board":
                # Only board members
                for board_member in self.chapter_doc.board_members or []:
                    if board_member.is_active and board_member.email:
                        recipients.append(board_member.email)

            elif filter_type == "members":
                # Only regular members
                for member in self.chapter_doc.members or []:
                    if member.enabled:
                        member_doc = frappe.get_doc("Member", member.member)
                        if member_doc.email:
                            recipients.append(member_doc.email)

            # Remove duplicates
            recipients = list(set(recipients))

        except Exception as e:
            self.log_action(
                "Error getting newsletter recipients", {"filter_type": filter_type, "error": str(e)}, "error"
            )

        return recipients

    def _generate_unsubscribe_url(self) -> str:
        """Generate unsubscribe URL for newsletters"""
        # This would need actual implementation based on your unsubscribe system
        return f"/unsubscribe?chapter={self.chapter_name}"

    def _validate_email_settings(self) -> bool:
        """Validate email settings are properly configured"""
        return bool(self.email_settings.get("smtp_server") and self.email_settings.get("email_id"))
