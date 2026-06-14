# verenigingen/verenigingen/doctype/chapter/managers/communication_manager.py

from typing import Dict, List

import frappe
from frappe import _

from verenigingen.utils.secure_operations import secure_document_operation

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
                notification_key="chapter_board_added",
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
                notification_key="chapter_board_removed",
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
                notification_key="chapter_board_added",  # Role change treated as board update
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
                notification_key="chapter_member_joined",
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
                notification_key="chapter_member_left",
            )

        except Exception as e:
            self.log_action(
                "Failed to send member removed notification", {"member": member_id, "error": str(e)}, "error"
            )
            return False

    def notify_board_of_member_joined(self, member_id: str) -> bool:
        """Notify all active board members that a regular member joined (or transferred in).

        Reads ``frappe.flags.chapter_transfer`` to decide whether to use the
        transfer-specific template.  This is the board-facing counterpart to
        ``notify_member_added`` (which emails only the joining member).

        Returns True if at least one email was queued.
        """
        enabled = self._board_lifecycle_notifications_enabled()
        print(
            f"\nDEBUG notify_board_of_member_joined: member_id={member_id}, enabled={enabled}, board_members={len(self.chapter_doc.board_members)}"
        )
        if not enabled:
            return False

        transfer = frappe.flags.get("chapter_transfer") or {}
        is_transfer_in = transfer.get("member") == member_id and transfer.get("to") == self.chapter_name
        template_name = (
            "chapter_board_member_transferred_in" if is_transfer_in else "chapter_board_member_joined"
        )
        notification_key = "chapter_member_transferred_in" if is_transfer_in else "chapter_member_joined"
        other_chapter = transfer.get("from") if is_transfer_in else None

        return self._dispatch_board_lifecycle_notification(
            member_id=member_id,
            template_name=template_name,
            notification_key=notification_key,
            other_chapter=other_chapter,
            effective_date=frappe.utils.today(),
        )

    def notify_board_of_member_left(self, member_id: str, leave_reason: str = None) -> bool:
        """Notify all active board members that a regular member left (or transferred out).

        Reads ``frappe.flags.chapter_transfer`` to decide whether to use the
        transfer-specific template.  This is the board-facing counterpart to
        ``notify_member_removed`` (which emails only the leaving member).

        Returns True if at least one email was queued.
        """
        if not self._board_lifecycle_notifications_enabled():
            return False

        transfer = frappe.flags.get("chapter_transfer") or {}
        is_transfer_out = transfer.get("member") == member_id and transfer.get("from") == self.chapter_name
        template_name = (
            "chapter_board_member_transferred_out" if is_transfer_out else "chapter_board_member_left"
        )
        notification_key = "chapter_member_transferred_out" if is_transfer_out else "chapter_member_left"
        other_chapter = transfer.get("to") if is_transfer_out else None

        return self._dispatch_board_lifecycle_notification(
            member_id=member_id,
            template_name=template_name,
            notification_key=notification_key,
            other_chapter=other_chapter,
            effective_date=frappe.utils.today(),
            leave_reason=leave_reason,
        )

    def _board_lifecycle_notifications_enabled(self) -> bool:
        """Gate: returns True only if none of the suppression rules fire."""
        if getattr(frappe.flags, "is_bulk_import", False):
            return False
        if getattr(frappe.flags, "suppress_chapter_notifications", False):
            return False
        setting_value = frappe.db.get_single_value(
            "Verenigingen Settings", "send_chapter_assignment_notifications"
        )
        return bool(setting_value)

    def _dispatch_board_lifecycle_notification(
        self,
        member_id: str,
        template_name: str,
        notification_key: str,
        other_chapter: str,
        effective_date: str,
        leave_reason: str = None,
    ) -> bool:
        """Send an email template to every active board member of this chapter.

        Board member rows carry a pre-fetched ``email`` field (fetched from
        ``volunteer.email``), so no additional lookup is needed.
        Returns True if at least one email was queued.
        """
        try:
            from verenigingen.services.communication.email_service import get_email_service

            recipients = []
            seen: set = set()
            for board_row in self.chapter_doc.board_members or []:
                print(
                    f"DEBUG board_row: is_active={board_row.is_active}, email={board_row.email!r}, volunteer={board_row.volunteer!r}"
                )
                if not board_row.is_active:
                    continue
                email = board_row.email
                if email and email not in seen:
                    recipients.append(email)
                    seen.add(email)

            print(f"DEBUG _dispatch_board_lifecycle_notification: recipients={recipients}")
            if not recipients:
                return False

            member_doc = frappe.get_doc("Member", member_id)
            member_name = member_doc.full_name or (
                f"{member_doc.first_name or ''} {member_doc.last_name or ''}".strip() or member_id
            )

            context = {
                "member_name": member_name,
                "member_id": member_id,
                "member_link": frappe.utils.get_url(f"/app/member/{member_id}"),
                "chapter_name": self.chapter_name,
                "other_chapter": other_chapter,
                "effective_date": frappe.utils.formatdate(effective_date),
                "leave_reason": leave_reason,
            }

            result = get_email_service().send_templated_email(
                template_name=template_name,
                recipients=recipients,
                context=context,
                reference_doctype="Chapter",
                reference_name=self.chapter_name,
                notification_key=notification_key,
            )
            return result.success if result else False

        except Exception as e:
            self.log_action(
                "Failed to dispatch board lifecycle notification",
                {"member": member_id, "template": template_name, "error": str(e)},
                "error",
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
                    notification_key="chapter_generic_notification",
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
        self, recipients: List[str], subject: str, content: str, communication_type: str = "Communication"
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
        # WHY: The Communication doctype's `communication_type` Select only accepts
        # "Communication" / "Automated Message" -- NOT "Email" ("Email" is a
        # `communication_medium` value, set separately below). The old default of
        # "Email" made every insert fail validation, so this method silently
        # returned None for all callers and no chapter Communication record was
        # ever created. "Communication" is the correct type for an emailed message.
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
                    # WHY: Communication validates `recipients` as a COMMA-separated
                    # email list (frappe.utils.split_emails splits on comma/semicolon,
                    # not newline). Joining with "\n" made the validator treat the
                    # whole blob as a single invalid address, so any call with 2+
                    # recipients failed and this method silently returned None.
                    "recipients": ", ".join(recipients),
                    "sent_or_received": "Sent",
                }
            )

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            comm_result = secure_document_operation(
                operation="insert",
                doc=communication,
                justification=f"Create communication record for chapter {self.chapter_name} email",
                required_permissions=["Communication:create"],
            )

            if not comm_result.success:
                self.log_action(
                    "Failed to create communication record: Permission denied",
                    {"subject": subject, "error": "Permission denied"},
                    "warning",
                )
                return None

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
        notification_key: str = None,
    ) -> bool:
        """Send email using template - MIGRATED to unified EmailService"""
        try:
            # MIGRATED: Use unified EmailService instead of direct frappe.sendmail
            from verenigingen.services.communication.compatibility import send_chapter_email

            result = send_chapter_email(
                chapter_name=self.chapter_name,
                recipients=recipients,
                subject=subject,
                template=template.name if template else None,
                context=context,
                communication_type="Email",
                reference_doctype=reference_doctype,
                reference_name=reference_name,
                notification_key=notification_key,
            )

            if result.get("success"):
                self.log_action(
                    f"Email sent using template {template.name if template else 'direct'}",
                    {"recipients_count": len(recipients), "subject": subject},
                )
                return True
            else:
                self.log_action(
                    "Failed to send templated email",
                    {
                        "template": template.name if template else "None",
                        "recipients_count": len(recipients),
                        "errors": result.get("errors", []),
                    },
                    "error",
                )
                return False

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
                # All chapter members who accept optional communications
                for member in self.chapter_doc.members or []:
                    if member.enabled:
                        member_doc = frappe.get_doc("Member", member.member)
                        # Check opt-in preference
                        if member_doc.email and member_doc.get("accepts_optional_communications", True):
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
                # Only regular members who accept optional communications
                for member in self.chapter_doc.members or []:
                    if member.enabled:
                        member_doc = frappe.get_doc("Member", member.member)
                        # Check opt-in preference for optional communications
                        if member_doc.email and member_doc.get("accepts_optional_communications", True):
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

    def send_statutory_communication(
        self, subject: str, content: str, communication_type: str = "agm"
    ) -> Dict:
        """
        Send legally required communications to ALL members regardless of preferences

        Args:
            subject: Email subject
            content: Email content
            communication_type: Type of statutory communication (agm, egm, voting, dues)

        Returns:
            Dict with send results
        """
        # Get ALL members with email addresses (ignoring opt-out preferences)
        all_recipients = []

        # Get all chapter members
        for member in self.chapter_doc.members or []:
            if member.enabled:
                member_doc = frappe.get_doc("Member", member.member)
                if member_doc.email:
                    all_recipients.append(member_doc.email)

        # Get all board members
        for board_member in self.chapter_doc.board_members or []:
            if board_member.is_active and board_member.email:
                all_recipients.append(board_member.email)

        # Remove duplicates
        all_recipients = list(set(all_recipients))

        if not all_recipients:
            return {"success": False, "error": "No recipients found"}

        # Log this as a statutory communication
        self.log_action(
            "Statutory communication sent",
            {"type": communication_type, "recipient_count": len(all_recipients), "subject": subject},
        )

        # Prepare context with statutory flag
        context = {
            "is_statutory": True,
            "communication_type": communication_type,
            "content": content,
            "chapter": self.chapter_doc,
            "chapter_name": self.chapter_name,
        }

        # Send with special subject prefix indicating statutory nature
        statutory_subject = f"[STATUTORY] {subject}"

        # Use template if available, otherwise send directly
        template_name = f"statutory_{communication_type}"
        template = self._get_email_template(template_name)

        if template:
            return self.send_bulk_notification(
                template_name=template_name,
                recipients=all_recipients,
                subject=statutory_subject,
                context=context,
            )
        else:
            # Send without template
            return self.send_bulk_notification(
                template_name="default_statutory",
                recipients=all_recipients,
                subject=statutory_subject,
                context=context,
            )
