"""
Unified Email Service for Verenigingen

Consolidates all email functionality from various modules into a single,
consistent service with proper error handling, logging, and security.
"""

import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.utils import get_datetime, now

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.service_error_handler import create_service_result, handle_service_error


class BoundedLRUCache:
    """LRU cache with size limits and TTL expiration."""

    def __init__(self, max_size: int = 100, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache = OrderedDict()
        self._timestamps = {}

    def get(self, key: str) -> Optional[Any]:
        """Get item from cache, None if not found or expired."""
        if key not in self._cache:
            return None

        # Check TTL expiration
        if time.time() - self._timestamps[key] > self.ttl_seconds:
            self._evict(key)
            return None

        # Move to end (mark as recently used)
        self._cache.move_to_end(key)
        return self._cache[key]

    def set(self, key: str, value: Any) -> None:
        """Set item in cache with LRU eviction if needed."""
        current_time = time.time()

        if key in self._cache:
            # Update existing
            self._cache[key] = value
            self._timestamps[key] = current_time
            self._cache.move_to_end(key)
        else:
            # Add new item
            if len(self._cache) >= self.max_size:
                # Evict least recently used
                oldest_key = next(iter(self._cache))
                self._evict(oldest_key)

            self._cache[key] = value
            self._timestamps[key] = current_time

    def _evict(self, key: str) -> None:
        """Remove item from cache."""
        self._cache.pop(key, None)
        self._timestamps.pop(key, None)

    def clear(self) -> None:
        """Clear all cached items."""
        self._cache.clear()
        self._timestamps.clear()

    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)


class EmailService:
    """
    Centralized email service that replaces scattered email implementations.

    Features:
    - Template-based emails with context rendering
    - Bulk email handling with rate limiting
    - Communication record creation for audit trails
    - Error handling and retry logic
    - Security validation and permission checking
    """

    def __init__(self):
        self.settings = self._load_email_settings()
        # Bounded cache with max 50 templates, 1 hour TTL
        self.template_cache = BoundedLRUCache(max_size=50, ttl_seconds=3600)

    def send_templated_email(
        self,
        template_name: str,
        recipients: Union[str, List[str]],
        context: Dict[str, Any] = None,
        subject_override: str = None,
        reference_doctype: str = None,
        reference_name: str = None,
        create_communication: bool = True,
        **options,
    ) -> Dict[str, Any]:
        """
        Send email using a template with context variables.

        Args:
            template_name: Name of the email template
            recipients: Email addresses (string or list)
            context: Variables for template rendering
            subject_override: Override template subject
            reference_doctype: Link to specific DocType
            reference_name: Link to specific document
            create_communication: Whether to create Communication record
            **options: Additional email options

        Returns:
            Dict with success status and details
        """
        try:
            # Normalize recipients to list
            if isinstance(recipients, str):
                recipients = [recipients]

            # Load and validate template
            template = self._get_template(template_name)
            if not template:
                return create_service_result(
                    success=False,
                    error=f"Email template '{template_name}' not found",
                    service_name="EmailService",
                    operation="send_templated_email",
                )

            # Prepare context with validation
            if context is None:
                email_context = {}
            elif isinstance(context, dict):
                email_context = context.copy()
            else:
                # Invalid context type - log warning and use empty dict
                frappe.logger("email_service").warning(
                    f"Invalid context type {type(context)}, expected dict. Using empty context."
                )
                email_context = {}

            email_context.update(self._get_default_context())

            # Render template
            rendered_content = self._render_template(template, email_context)
            subject = subject_override or rendered_content.get(
                "subject", f"Message from {self.settings.get('organization_name', 'Verenigingen')}"
            )

            # Send email
            result = self._send_email_internal(
                recipients=recipients,
                subject=subject,
                content=rendered_content.get("content", ""),
                reference_doctype=reference_doctype,
                reference_name=reference_name,
                create_communication=create_communication,
                **options,
            )

            return create_service_result(
                success=result["success"],
                data={
                    "template": template_name,
                    "recipients_count": len(recipients),
                    "communication_id": result.get("communication_id"),
                    "message": "Email sent successfully" if result["success"] else "Email sending failed",
                }
                if result["success"]
                else None,
                error="; ".join(result.get("errors", [])) if not result["success"] else None,
                service_name="EmailService",
                operation="send_templated_email",
            )

        except Exception as e:
            return handle_service_error(
                e,
                "EmailService",
                "Send templated email",
                {
                    "template": template_name,
                    "recipients_count": len(recipients) if isinstance(recipients, list) else 1,
                },
                raise_error=False,
            )

    def send_notification(
        self, notification_type: str, recipients: Union[str, List[str]], data: Dict[str, Any], **options
    ) -> Dict[str, Any]:
        """
        Send system notifications using predefined templates.

        Args:
            notification_type: Type of notification (approval, suspension, etc.)
            recipients: Email addresses
            data: Notification data
            **options: Additional options

        Returns:
            Dict with success status and details
        """
        try:
            # Map notification types to templates
            template_mapping = {
                "member_approval": "membership_application_approved",
                "member_suspension": "Member Suspension Notification",
                "member_termination": "Member Termination Notification",
                "member_reactivation": "Member Reactivation Notification",
                "member_rejection": "membership_application_rejected",
                "payment_failure": "Payment Failure Notification",
                "sepa_mandate_created": "SEPA Mandate Created",
                "board_member_added": "Board Member Added",
            }

            template_name = template_mapping.get(notification_type)
            if not template_name:
                return create_service_result(
                    success=False,
                    error=f"Unknown notification type: {notification_type}",
                    service_name="EmailService",
                    operation="send_notification",
                )

            return self.send_templated_email(
                template_name=template_name, recipients=recipients, context=data, **options
            )

        except Exception as e:
            return handle_service_error(
                e,
                "EmailService",
                "Send notification",
                {"notification_type": notification_type},
                raise_error=False,
            )

    def send_bulk_emails(
        self,
        email_batch: List[Dict[str, Any]],
        batch_size: int = 50,
        delay_between_batches: float = 1.0,
        **options,
    ) -> Dict[str, Any]:
        """
        Send multiple emails efficiently with rate limiting.

        Args:
            email_batch: List of email configurations
            batch_size: Number of emails per batch
            delay_between_batches: Seconds to wait between batches
            **options: Additional options

        Returns:
            Dict with batch results
        """
        try:
            import time

            total_emails = len(email_batch)
            sent_count = 0
            failed_count = 0
            results = []

            # Process in batches
            for i in range(0, total_emails, batch_size):
                batch = email_batch[i : i + batch_size]

                for email_config in batch:
                    try:
                        result = self.send_templated_email(**email_config)
                        if result["success"]:
                            sent_count += 1
                        else:
                            failed_count += 1
                        results.append(result)

                    except Exception as e:
                        failed_count += 1
                        results.append({"success": False, "errors": [str(e)], "email_config": email_config})

                # Rate limiting delay
                if i + batch_size < total_emails:
                    time.sleep(delay_between_batches)

            return create_service_result(
                success=True,
                data={
                    "total_emails": total_emails,
                    "sent_count": sent_count,
                    "failed_count": failed_count,
                    "success_rate": (sent_count / total_emails) * 100 if total_emails > 0 else 0,
                    "results": results,
                },
                service_name="EmailService",
                operation="send_bulk_emails",
            )

        except Exception as e:
            return handle_service_error(
                e, "EmailService", "Send bulk emails", {"batch_size": len(email_batch)}, raise_error=False
            )

    def _send_email_internal(
        self,
        recipients: List[str],
        subject: str,
        content: str,
        reference_doctype: str = None,
        reference_name: str = None,
        create_communication: bool = True,
        **options,
    ) -> Dict[str, Any]:
        """Internal email sending with Communication record creation."""
        try:
            # Send via Frappe's email system
            frappe.sendmail(
                recipients=recipients,
                subject=subject,
                message=content,
                reference_doctype=reference_doctype,
                reference_name=reference_name,
                **options,
            )

            communication_id = None
            if create_communication:
                communication_id = self._create_communication_record(
                    recipients, subject, content, reference_doctype, reference_name
                )

            return {"success": True, "communication_id": communication_id}

        except Exception as e:
            frappe.logger("email_service").error(f"Email sending failed: {str(e)}")
            return {"success": False, "errors": [str(e)]}

    def _create_communication_record(
        self,
        recipients: List[str],
        subject: str,
        content: str,
        reference_doctype: str = None,
        reference_name: str = None,
    ) -> Optional[str]:
        """Create Communication record for audit trail."""
        try:
            communication_data = {
                "doctype": "Communication",
                "communication_type": "Email",
                "communication_medium": "Email",
                "subject": subject,
                "content": content,
                "status": "Sent",
                "recipients": "\n".join(recipients),
                "sent_or_received": "Sent",
                "creation": now(),
            }

            if reference_doctype and reference_name:
                communication_data.update(
                    {"reference_doctype": reference_doctype, "reference_name": reference_name}
                )

            result = secure_document_operation(
                operation="insert",
                doc=frappe.get_doc(communication_data),
                justification="Email service communication record creation",
                required_permissions=["Communication:create"],
            )

            if result.success:
                return result.data.name
            else:
                frappe.logger("email_service").warning(
                    f"Failed to create communication record: {'; '.join(result.errors)}"
                )
                return None

        except Exception as e:
            frappe.logger("email_service").error(f"Communication record creation failed: {str(e)}")
            return None

    def _get_template(self, template_name: str) -> Optional[Dict[str, Any]]:
        """Load email template with bounded caching."""
        # Check bounded cache first
        cached_template = self.template_cache.get(template_name)
        if cached_template:
            return cached_template

        try:
            if frappe.db.exists("Email Template", template_name):
                template_doc = frappe.get_doc("Email Template", template_name)
                template_data = {
                    "subject": template_doc.subject,
                    "content": template_doc.response_html if template_doc.use_html else template_doc.response,
                    "doc": template_doc,
                }
                # Store in bounded cache
                self.template_cache.set(template_name, template_data)
                return template_data
            return None

        except Exception as e:
            frappe.logger("email_service").error(f"Template loading failed for {template_name}: {str(e)}")
            return None

    def _render_template(self, template: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, str]:
        """Render template with context variables."""
        try:
            rendered_subject = frappe.render_template(template["subject"], context)
            rendered_content = frappe.render_template(template["content"], context)

            return {"subject": rendered_subject, "content": rendered_content}
        except Exception as e:
            frappe.logger("email_service").error(f"Template rendering failed: {str(e)}")
            raise e

    def _get_default_context(self) -> Dict[str, Any]:
        """Get default context variables for all emails."""
        try:
            settings = frappe.get_single("Verenigingen Settings")
            return {
                "organization_name": getattr(settings, "organization_name", "Verenigingen"),
                "contact_email": getattr(settings, "contact_email", ""),
                "website_url": getattr(settings, "website_url", ""),
                "current_date": get_datetime(),
            }
        except Exception:
            return {
                "organization_name": "Verenigingen",
                "current_date": get_datetime(),
            }

    def _load_email_settings(self) -> Dict[str, Any]:
        """Load email configuration settings."""
        try:
            settings = frappe.get_single("Verenigingen Settings")
            return {
                "organization_name": getattr(settings, "organization_name", "Verenigingen"),
                "default_sender": getattr(settings, "default_email_sender", "noreply@verenigingen.org"),
                "contact_email": getattr(settings, "contact_email", ""),
            }
        except Exception:
            return {
                "organization_name": "Verenigingen",
                "default_sender": "noreply@verenigingen.org",
            }


# Singleton instance for easy access
_email_service_instance = None


def get_email_service() -> EmailService:
    """Get singleton EmailService instance."""
    global _email_service_instance
    if _email_service_instance is None:
        _email_service_instance = EmailService()
    return _email_service_instance
