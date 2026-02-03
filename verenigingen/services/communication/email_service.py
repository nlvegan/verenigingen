"""
Unified Email Service for Verenigingen

Consolidates all email functionality from various modules into a single,
consistent service with proper error handling, logging, and security.
"""

import time
import warnings
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.utils import get_datetime, now

from verenigingen.services.infrastructure.base_service import StatelessService
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


class EmailService(StatelessService):
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
        super().__init__(service_name="EmailService")
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
        notification_key: str = None,
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
            notification_key: Optional key for Email Configuration lookup.
                             Enables per-notification settings and cooldown tracking.
            **options: Additional email options

        Returns:
            Dict with success status and details
        """
        try:
            # Check Email Configuration early - before any template loading
            # This prevents template-not-found errors when email is disabled
            config_service = self._get_config_service()
            if config_service and not config_service.is_email_enabled():
                self.logger.info("Email sending disabled via Email Configuration - skipping templated email")
                return create_service_result(
                    success=True,
                    data={"skipped": True, "reason": "Email disabled in configuration"},
                    service_name="EmailService",
                    operation="send_templated_email",
                )

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
                self.logger.warning(
                    f"Invalid context type {type(context)}, expected dict. Using empty context."
                )
                email_context = {}

            email_context.update(self._get_default_context())

            # Render template
            rendered_content = self._render_template(template, email_context)
            subject = subject_override or rendered_content.get(
                "subject", f"Message from {self.settings.get('organization_name') or 'Your Organization'}"
            )

            # Send email
            result = self._send_email_internal(
                recipients=recipients,
                subject=subject,
                content=rendered_content.get("content", ""),
                reference_doctype=reference_doctype,
                reference_name=reference_name,
                create_communication=create_communication,
                notification_key=notification_key,
                **options,
            )

            return create_service_result(
                success=result["success"],
                data=(
                    {
                        "template": template_name,
                        "recipients_count": len(recipients),
                        "queued": result.get("queued", False),
                        "message": (
                            "Email queued successfully" if result["success"] else "Email queueing failed"
                        ),
                    }
                    if result["success"]
                    else None
                ),
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

        .. deprecated:: 2.0
            This method uses hardcoded template mappings and will be removed in a future version.
            Use Frappe's native Notification DocType instead, which provides:
            - UI-configurable notifications without code changes
            - Document-triggered events (New, Save, Value Change, etc.)
            - Role-based and field-based recipient selection
            - Condition-based filtering

            See: Setup > Email > Notification in Frappe Desk

        Args:
            notification_type: Type of notification (approval, suspension, etc.)
            recipients: Email addresses
            data: Notification data
            **options: Additional options

        Returns:
            Dict with success status and details
        """
        warnings.warn(
            "EmailService.send_notification() is deprecated. "
            "Use Frappe's native Notification DocType for document-triggered notifications. "
            "Configure via Setup > Email > Notification in Frappe Desk.",
            DeprecationWarning,
            stacklevel=2,
        )
        try:
            # Map notification types to templates
            template_mapping = {
                "member_approval": "membership_application_approved",
                "chapter_membership_approval": "chapter_membership_approved",
                "member_suspension": "Member Suspension Notification",
                "member_termination": "Member Termination Notification",
                "member_reactivation": "Member Reactivation Notification",
                "member_rejection": "membership_application_rejected",
                "payment_failure": "Payment Failure Notification",
                "sepa_mandate_created": "SEPA Mandate Created",
                "board_member_added": "Board Member Added",
            }

            # Map notification types to notification keys for Email Configuration control
            key_mapping = {
                "member_approval": "member_application_approved",
                "chapter_membership_approval": "chapter_membership_approved",
                "member_suspension": "member_suspended",
                "member_termination": "member_terminated",
                "member_reactivation": "member_activated",
                "member_rejection": "member_application_rejected",
                "payment_failure": "payment_failure",
                "sepa_mandate_created": "sepa_mandate_created",
                "board_member_added": "board_member_added",
            }

            template_name = template_mapping.get(notification_type)
            if not template_name:
                return create_service_result(
                    success=False,
                    error=f"Unknown notification type: {notification_type}",
                    service_name="EmailService",
                    operation="send_notification",
                )

            # Get the notification key for configuration-based control
            notification_key = key_mapping.get(notification_type)

            return self.send_templated_email(
                template_name=template_name,
                recipients=recipients,
                context=data,
                notification_key=notification_key,
                **options,
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

            # Check Email Configuration early - before processing any emails
            config_service = self._get_config_service()
            if config_service and not config_service.is_email_enabled():
                self.logger.info(
                    f"Email sending disabled via Email Configuration - skipping batch of {len(email_batch)} emails"
                )
                return create_service_result(
                    success=True,
                    data={
                        "skipped": True,
                        "reason": "Email disabled in configuration",
                        "total_emails": len(email_batch),
                        "skipped_count": len(email_batch),
                    },
                    service_name="EmailService",
                    operation="send_bulk_emails",
                )

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

    def send_simple_email(
        self,
        recipients: Union[str, List[str]],
        subject: str,
        message: str,
        reference_doctype: str = None,
        reference_name: str = None,
        notification_key: str = None,
        **options,
    ) -> Dict[str, Any]:
        """
        Send simple non-templated email for system notifications and alerts.

        Use this for:
        - System alerts and monitoring notifications
        - Error notifications
        - Administrative messages
        - Any email that doesn't require a template

        Args:
            recipients: Email address(es)
            subject: Email subject
            message: Email content (plain text or HTML)
            reference_doctype: Optional DocType reference for tracking
            reference_name: Optional document name for tracking
            notification_key: Optional key for Email Configuration lookup.
                             Enables per-notification settings and cooldown tracking.
            **options: Additional options (delayed, etc.)

        Returns:
            Dict with success status and details
        """
        try:
            # Normalize recipients
            if isinstance(recipients, str):
                recipients = [recipients]

            return self._send_email_internal(
                recipients=recipients,
                subject=subject,
                content=message,
                reference_doctype=reference_doctype,
                reference_name=reference_name,
                notification_key=notification_key,
                **options,
            )

        except Exception as e:
            return handle_service_error(
                e,
                "EmailService",
                "Send simple email",
                {
                    "subject": subject,
                    "recipient_count": len(recipients) if isinstance(recipients, list) else 1,
                },
                raise_error=False,
            )

    def _send_email_internal(
        self,
        recipients: List[str],
        subject: str,
        content: str,
        reference_doctype: str = None,
        reference_name: str = None,
        create_communication: bool = True,  # Deprecated - kept for backward compatibility
        notification_key: str = None,
        **options,
    ) -> Dict[str, Any]:
        """
        Internal email sending using Frappe's Email Queue system.

        Uses Frappe's Email Queue system instead of direct sendmail() to prevent
        broken pipe errors from SMTP subprocess failures. Emails are queued and
        sent asynchronously via background workers.

        Note: Tracking is handled by Email Queue records, not Communication records.
        Use Email Queue reports for delivery status and audit trails.

        Args:
            notification_key: Optional key for Email Configuration lookup. If provided,
                             checks per-notification-type settings and cooldown.
        """
        try:
            # Check Email Configuration if available
            config_service = self._get_config_service()
            if config_service:
                # Check master email enable
                if not config_service.is_email_enabled():
                    self.logger.info("Email sending disabled via Email Configuration")
                    return create_service_result(
                        success=True,
                        data={"skipped": True, "reason": "Email disabled in configuration"},
                        service_name="EmailService",
                        operation="_send_email_internal",
                    )

                # Check notification-specific settings if key provided
                if notification_key:
                    # Validate notification_key exists in registry
                    self._validate_notification_key(notification_key)

                    if not config_service.is_notification_enabled(notification_key):
                        self.logger.info(f"Notification '{notification_key}' disabled in Email Configuration")
                        return create_service_result(
                            success=True,
                            data={"skipped": True, "reason": f"Notification '{notification_key}' disabled"},
                            service_name="EmailService",
                            operation="_send_email_internal",
                        )

                    # Check cooldown for each recipient
                    recipients_to_send = []
                    for recipient in recipients:
                        if config_service.check_cooldown(notification_key, recipient):
                            recipients_to_send.append(recipient)
                        else:
                            self.logger.debug(f"Skipping {recipient} for '{notification_key}' - in cooldown")

                    if not recipients_to_send:
                        return create_service_result(
                            success=True,
                            data={"skipped": True, "reason": "All recipients in cooldown"},
                            service_name="EmailService",
                            operation="_send_email_internal",
                        )
                    recipients = recipients_to_send

            # Input validation
            if not recipients:
                return create_service_result(
                    success=False,
                    error="No recipients provided",
                    service_name="EmailService",
                    operation="_send_email_internal",
                )

            if not subject or not content:
                return create_service_result(
                    success=False,
                    error="Subject and content are required",
                    service_name="EmailService",
                    operation="_send_email_internal",
                )

            # Check if email account is configured
            if not self._has_active_email_account():
                self.logger.warning(
                    f"No active email account configured. Email not queued.\n"
                    f"Recipients: {recipients}\n"
                    f"Subject: {subject[:50]}..."
                )
                return create_service_result(
                    success=False,
                    error="No active email account configured. Please configure an email account in Settings.",
                    service_name="EmailService",
                    operation="_send_email_internal",
                )

            # Use frappe.sendmail with delayed=True (default) to queue for background processing
            # This queues the email for background processing by RQ workers
            email_args = {
                "recipients": recipients,
                "subject": subject,
                "message": content,
                "reference_doctype": reference_doctype,
                "reference_name": reference_name,
                "send_priority": 1,  # Normal priority
                "delayed": True,  # Queue for background sending (default)
            }

            # Add any additional options (but filter out unsupported ones)
            supported_keys = {
                "sender",
                "cc",
                "bcc",
                "reply_to",
                "attachments",
                "template",
                "args",
                "header",
                "with_container",
            }
            filtered_options = {k: v for k, v in options.items() if k in supported_keys}
            email_args.update(filtered_options)

            # Queue the email via frappe.sendmail
            frappe.sendmail(**email_args)

            # NOTE: We don't create Communication records for queued emails because:
            # 1. Frappe's Email Queue system creates its own "Email Queue" records with proper status tracking
            # 2. Communication records would stay "Queued" forever (no automatic status updates)
            # 3. Email Queue records provide better observability (retries, failures, etc.)
            # For audit trails, use Email Queue reports instead of Communication records.

            # Record cooldown for sent emails
            if notification_key:
                self._record_cooldown(notification_key, recipients)

            return create_service_result(
                success=True,
                data={
                    "queued": True,
                    "message": f"Email queued for {len(recipients)} recipient(s)",
                    "tracking": "Check Email Queue for delivery status",
                },
                service_name="EmailService",
                operation="_send_email_internal",
            )

        except Exception as e:
            self.logger.error(
                f"Email queueing failed: {str(e)}\n"
                f"Recipients: {recipients}\n"
                f"Subject: {subject[:50] if subject else 'None'}..."
            )
            return create_service_result(
                success=False,
                error=f"Failed to queue email: {str(e)}",
                service_name="EmailService",
                operation="_send_email_internal",
            )

    def _create_communication_record(
        self,
        recipients: List[str],
        subject: str,
        content: str,
        reference_doctype: str = None,
        reference_name: str = None,
        status: str = "Queued",
    ) -> Optional[str]:
        """
        Create Communication record for audit trail.

        Args:
            recipients: List of email addresses
            subject: Email subject
            content: Email content
            reference_doctype: Linked DocType
            reference_name: Linked document name
            status: Communication status ("Queued", "Sent", "Failed")
                    Default is "Queued" since emails are sent asynchronously

        Returns:
            Communication document name if created, None otherwise
        """
        try:
            communication_data = {
                "doctype": "Communication",
                "communication_type": "Email",
                "communication_medium": "Email",
                "subject": subject,
                "content": content,
                "status": status,  # Use provided status (default "Queued")
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
                self.logger.warning(f"Failed to create communication record: {'; '.join(result.errors)}")
                return None

        except Exception as e:
            self.logger.error(f"Communication record creation failed: {str(e)}")
            return None

    def _get_config_service(self):
        """Get EmailConfigurationService if available.

        Returns None if the service or DocType is not yet installed,
        allowing graceful degradation during migrations.
        """
        try:
            from verenigingen.services.communication.email_configuration_service import (
                get_email_configuration_service,
            )

            return get_email_configuration_service()
        except Exception:
            # Configuration service not available - continue without it
            return None

    def _record_cooldown(self, notification_key: str, recipients: List[str]) -> None:
        """Record send timestamp for cooldown tracking.

        Args:
            notification_key: The notification type key.
            recipients: List of recipients that were sent to.
        """
        try:
            config_service = self._get_config_service()
            if config_service and notification_key:
                for recipient in recipients:
                    config_service.record_send(notification_key, recipient)
        except Exception as e:
            self.logger.debug(f"Cooldown recording failed: {e}")

    def _validate_notification_key(self, notification_key: str) -> bool:
        """Validate that a notification_key exists in the registry.

        Logs a warning if the key is not found but does not raise an exception.
        This allows emails to still be sent while alerting developers to add
        missing keys to the registry.

        Args:
            notification_key: The notification type key to validate.

        Returns:
            True if key exists in registry, False otherwise.
        """
        try:
            from verenigingen.notification_registry import NOTIFICATION_KEYS

            if notification_key not in NOTIFICATION_KEYS:
                self.logger.warning(
                    f"notification_key '{notification_key}' not found in NOTIFICATION_KEYS registry. "
                    f"Add it to verenigingen/notification_registry.py for proper configuration control. "
                    f"Email will still be sent."
                )
                return False
            return True
        except ImportError:
            # Registry module not available - skip validation
            return True

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
            self.logger.error(f"Template loading failed for {template_name}: {str(e)}")
            return None

    def _render_template(self, template: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, str]:
        """Render template with context variables."""
        try:
            rendered_subject = frappe.render_template(template["subject"], context)
            rendered_content = frappe.render_template(template["content"], context)

            return {"subject": rendered_subject, "content": rendered_content}
        except Exception as e:
            self.logger.error(f"Template rendering failed: {str(e)}")
            raise e

    def _get_default_context(self) -> Dict[str, Any]:
        """Get default context variables for all emails.

        Includes organization info and brand settings for template styling.
        Brand colors are provided for inline style fallbacks in templates
        (CSS classes from email_brand.css are preferred when available).
        """
        try:
            settings = frappe.get_single("Verenigingen Settings")
            brand = frappe.get_single("Brand Settings")

            return {
                # Organization info
                "organization_name": getattr(settings, "company_name", ""),
                "contact_email": getattr(settings, "contact_email", ""),
                "website_url": getattr(settings, "website_url", ""),
                "current_date": get_datetime(),
                "current_year": get_datetime().year,
                # Brand assets for templates
                "brand_logo": getattr(brand, "logo", None),
                "brand_primary_color": getattr(brand, "primary_color", "#007bff"),
                "brand_secondary_color": getattr(brand, "secondary_color", "#6c757d"),
            }
        except Exception:
            return {
                "organization_name": "",
                "current_date": get_datetime(),
                "current_year": get_datetime().year,
            }

    def _load_email_settings(self) -> Dict[str, Any]:
        """Load email configuration settings."""
        try:
            settings = frappe.get_single("Verenigingen Settings")
            return {
                "organization_name": getattr(settings, "company_name", ""),
                "default_sender": getattr(settings, "default_email_sender", "noreply@verenigingen.org"),
                "contact_email": getattr(settings, "contact_email", ""),
            }
        except Exception:
            return {
                "organization_name": "",
                "default_sender": "noreply@verenigingen.org",
            }

    def _has_active_email_account(self) -> bool:
        """Check if there's at least one active email account configured."""
        try:
            # Check for any enabled email accounts
            active_accounts = frappe.get_all(
                "Email Account", filters={"enable_outgoing": 1, "default_outgoing": 1}, limit=1
            )
            return len(active_accounts) > 0
        except Exception as e:
            self.logger.error(f"Error checking email accounts: {str(e)}")
            return False


# Singleton instance for easy access
_email_service_instance = None


def get_email_service() -> EmailService:
    """Get singleton EmailService instance."""
    global _email_service_instance
    if _email_service_instance is None:
        _email_service_instance = EmailService()
    return _email_service_instance
