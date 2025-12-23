"""
Email API Endpoints

Provides JavaScript-accessible API endpoints for the unified EmailService.
These endpoints allow frontend applications to send emails through the
consolidated email infrastructure.
"""

import traceback
from typing import Any, Dict, List, Union

import frappe
from frappe import _

from verenigingen.services.communication.compatibility import (
    send_chapter_email,
    send_member_notification,
    send_sepa_email,
)
from verenigingen.services.communication.email_service import get_email_service
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def send_templated_email(
    template_name: str,
    recipients: Union[str, List[str]],
    context: Dict[str, Any] = None,
    subject_override: str = None,
    reference_doctype: str = None,
    reference_name: str = None,
) -> OperationResult[Dict[str, Any]]:
    """
    Send templated email via unified EmailService.

    Args:
        template_name: Name of the email template
        recipients: Email addresses (string or JSON array)
        context: Template context variables (JSON object)
        subject_override: Override template subject
        reference_doctype: Link to specific DocType
        reference_name: Link to specific document

    Returns:
        OperationResult with email sending status and details
    """
    try:
        # Parse recipients if it's a JSON string
        if isinstance(recipients, str):
            try:
                import json

                recipients = json.loads(recipients)
            except json.JSONDecodeError:
                # If not JSON, treat as single email
                recipients = [recipients]

        # Parse context if it's a JSON string
        if isinstance(context, str):
            try:
                import json

                context = json.loads(context)
            except json.JSONDecodeError:
                context = {}

        email_service = get_email_service()

        result = email_service.send_templated_email(
            template_name=template_name,
            recipients=recipients,
            context=context or {},
            subject_override=subject_override,
            reference_doctype=reference_doctype,
            reference_name=reference_name,
        )

        return OperationResult.ok(result, message=_("Templated email sent successfully"))

    except Exception as e:
        frappe.log_error(f"Email API error: {str(e)}\n{traceback.format_exc()}", "Email API")
        return OperationResult.fail(
            error=str(e),
            message=_("Failed to send templated email"),
            details={"operation": "send_templated_email", "traceback": traceback.format_exc()},
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def send_notification(
    notification_type: str,
    recipients: Union[str, List[str]],
    data: Dict[str, Any],
    reference_doctype: str = None,
    reference_name: str = None,
) -> OperationResult[Dict[str, Any]]:
    """
    Send system notification via unified EmailService.

    Args:
        notification_type: Type of notification (approval, suspension, etc.)
        recipients: Email addresses
        data: Notification data
        reference_doctype: Link to specific DocType
        reference_name: Link to specific document

    Returns:
        OperationResult with notification sending status and details
    """
    try:
        # Parse recipients if it's a JSON string
        if isinstance(recipients, str):
            try:
                import json

                recipients = json.loads(recipients)
            except json.JSONDecodeError:
                recipients = [recipients]

        # Parse data if it's a JSON string
        if isinstance(data, str):
            try:
                import json

                data = json.loads(data)
            except json.JSONDecodeError:
                data = {}

        email_service = get_email_service()

        result = email_service.send_notification(
            notification_type=notification_type,
            recipients=recipients,
            data=data,
            reference_doctype=reference_doctype,
            reference_name=reference_name,
        )

        return OperationResult.ok(result, message=_("Notification sent successfully"))

    except Exception as e:
        frappe.log_error(f"Notification API error: {str(e)}\n{traceback.format_exc()}", "Email API")
        return OperationResult.fail(
            error=str(e),
            message=_("Failed to send notification"),
            details={"operation": "send_notification", "traceback": traceback.format_exc()},
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def send_member_email(
    member_name: str, notification_type: str, context: Dict[str, Any] = None
) -> OperationResult[Dict[str, Any]]:
    """
    Send email to member via compatibility layer.

    Args:
        member_name: Name/ID of member
        notification_type: Type of notification
        context: Email context variables

    Returns:
        OperationResult with member email sending status and details
    """
    try:
        # Parse context if it's a JSON string
        if isinstance(context, str):
            try:
                import json

                context = json.loads(context)
            except json.JSONDecodeError:
                context = {}

        result = send_member_notification(
            member_name=member_name, notification_type=notification_type, context=context or {}
        )

        return OperationResult.ok(result, message=_("Member email sent successfully"))

    except Exception as e:
        frappe.log_error(f"Member email API error: {str(e)}\n{traceback.format_exc()}", "Email API")
        return OperationResult.fail(
            error=str(e),
            message=_("Failed to send member email"),
            details={"operation": "send_member_email", "traceback": traceback.format_exc()},
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def send_chapter_email_api(
    chapter_name: str,
    recipients: Union[str, List[str]],
    subject: str,
    content: str = None,
    template: str = None,
    context: Dict[str, Any] = None,
) -> OperationResult[Dict[str, Any]]:
    """
    Send email via chapter communication system.

    Args:
        chapter_name: Name of chapter
        recipients: Email addresses
        subject: Email subject
        content: Email content (if not using template)
        template: Template name (if using template)
        context: Template context variables

    Returns:
        OperationResult with chapter email sending status and details
    """
    try:
        # Parse recipients if it's a JSON string
        if isinstance(recipients, str):
            try:
                import json

                recipients = json.loads(recipients)
            except json.JSONDecodeError:
                recipients = [recipients]

        # Parse context if it's a JSON string
        if isinstance(context, str):
            try:
                import json

                context = json.loads(context)
            except json.JSONDecodeError:
                context = {}

        result = send_chapter_email(
            chapter_name=chapter_name,
            recipients=recipients,
            subject=subject,
            content=content,
            template=template,
            context=context or {},
        )

        return OperationResult.ok(result, message=_("Chapter email sent successfully"))

    except Exception as e:
        frappe.log_error(f"Chapter email API error: {str(e)}\n{traceback.format_exc()}", "Email API")
        return OperationResult.fail(
            error=str(e),
            message=_("Failed to send chapter email"),
            details={"operation": "send_chapter_email", "traceback": traceback.format_exc()},
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def get_available_templates() -> OperationResult[Dict[str, Any]]:
    """
    Get list of available email templates.

    Returns:
        OperationResult with template names and details
    """
    try:
        templates = [t.name for t in frappe.get_all("Email Template", fields=["name"])]

        return OperationResult.ok(
            {"templates": templates, "count": len(templates)},
            message=_("Retrieved available templates successfully"),
        )

    except Exception as e:
        frappe.log_error(f"Template list API error: {str(e)}\n{traceback.format_exc()}", "Email API")
        return OperationResult.fail(
            error=str(e),
            message=_("Failed to retrieve available templates"),
            details={"operation": "get_available_templates", "traceback": traceback.format_exc()},
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def get_supported_notification_types() -> OperationResult[Dict[str, Any]]:
    """
    Get list of configured Frappe Notification DocTypes.

    Returns:
        OperationResult with notification names and their document types
    """
    try:
        notifications = frappe.get_all(
            "Notification",
            filters={"enabled": 1},
            fields=["name", "document_type", "event", "channel"]
        )

        # Extract just names for backwards compatibility
        notification_names = [n.name for n in notifications]

        return OperationResult.ok(
            {
                "notifications": notifications,
                "notification_types": notification_names,  # Backwards compatible
                "count": len(notifications)
            },
            message=_("Retrieved configured notifications successfully"),
        )

    except Exception as e:
        frappe.log_error(f"Notification types API error: {str(e)}\n{traceback.format_exc()}", "Email API")
        return OperationResult.fail(
            error=str(e),
            message=_("Failed to retrieve notification types"),
            details={"operation": "get_supported_notification_types", "traceback": traceback.format_exc()},
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def validate_template(template_name: str) -> OperationResult[Dict[str, Any]]:
    """
    Validate email template exists and is properly configured.

    Args:
        template_name: Name of template to validate

    Returns:
        OperationResult with validation results
    """
    try:
        from jinja2 import TemplateSyntaxError

        validation_result = {"valid": False, "errors": [], "warnings": []}

        if not frappe.db.exists("Email Template", template_name):
            validation_result["errors"].append(f"Template '{template_name}' not found")
        else:
            template_doc = frappe.get_doc("Email Template", template_name)
            if not template_doc.subject:
                validation_result["errors"].append("Template missing subject")
            if not template_doc.response and not template_doc.response_html:
                validation_result["errors"].append("Template missing content")

            # Validate Jinja syntax in subject
            if template_doc.subject:
                try:
                    frappe.render_template(template_doc.subject, {})
                except TemplateSyntaxError as e:
                    validation_result["errors"].append(f"Subject Jinja syntax error: {e.message}")
                except Exception:
                    pass  # Other errors (missing variables) are OK for syntax validation

            # Validate Jinja syntax in content
            content = template_doc.response_html if template_doc.use_html else template_doc.response
            if content:
                try:
                    frappe.render_template(content, {})
                except TemplateSyntaxError as e:
                    validation_result["errors"].append(f"Content Jinja syntax error: {e.message}")
                except Exception:
                    pass  # Other errors (missing variables) are OK for syntax validation

            validation_result["valid"] = len(validation_result["errors"]) == 0

        return OperationResult.ok(
            {"template": template_name, "validation": validation_result},
            message=_("Template validated successfully"),
        )

    except Exception as e:
        frappe.log_error(f"Template validation API error: {str(e)}\n{traceback.format_exc()}", "Email API")
        return OperationResult.fail(
            error=str(e),
            message=_("Failed to validate template"),
            details={"operation": "validate_template", "traceback": traceback.format_exc()},
        )
