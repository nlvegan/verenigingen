"""
Backward Compatibility Layer for Email Services

Provides compatibility wrappers for existing email implementations
while gradually migrating them to use the unified EmailService.

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
All compatibility wrappers return OperationResult[Dict] with type-safe error handling.
Never throw exceptions - all errors returned as OperationResult.fail().

Public API Functions:
- send_sepa_email: Returns OperationResult[Dict] (SEPA email results)
- send_member_notification: Returns OperationResult[Dict] (member notification results)
- send_chapter_email: Returns OperationResult[Dict] (chapter email results)
- send_templated_email_legacy: Returns OperationResult[Dict] (legacy template results)

Migration Status: ✅ COMPLETE (2025-11-24)
- All 4 compatibility wrappers migrated from dict-based to OperationResult pattern
- EmailService integration preserved
- Type-safe error handling with comprehensive metadata

See: docs/patterns/OPERATION_RESULT_PATTERN.md
"""

from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult

from .email_service import get_email_service


# Compatibility wrapper for SEPA notifications
def send_sepa_email(
    recipients: Union[str, List[str]],
    subject: str,
    template: str = None,
    context: Dict[str, Any] = None,
    member: str = None,
    **kwargs,
) -> OperationResult[Dict[str, Any]]:
    """
    Backward compatibility wrapper for SEPA email sending.

    Replaces the various _send_email methods in SEPA modules.

    Returns:
        OperationResult[Dict]: Email sending result

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - Compatibility wrapper for gradual migration
    """
    try:
        email_service = get_email_service()

        if template:
            # Use template-based sending
            result = email_service.send_templated_email(
                template_name=template,
                recipients=recipients,
                context=context or {},
                subject_override=subject,
                reference_doctype="Member" if member else None,
                reference_name=member,
                **kwargs,
            )
        else:
            # Use direct email sending
            result = email_service._send_email_internal(
                recipients=recipients if isinstance(recipients, list) else [recipients],
                subject=subject,
                content=context.get("message", "") if context else "",
                reference_doctype="Member" if member else None,
                reference_name=member,
                **kwargs,
            )

        # Convert dict result to OperationResult
        if isinstance(result, dict):
            if result.get("success"):
                return OperationResult.ok(result, message=result.get("message", "Email sent successfully"))
            else:
                return OperationResult.fail(
                    result.get("message", "Email sending failed"), errors=result.get("errors", [])
                )
        return result  # Already OperationResult

    except Exception as e:
        frappe.logger("email_compatibility").error(f"SEPA email compatibility failed: {str(e)}")
        return OperationResult.fail(f"SEPA email failed: {str(e)}", errors=[str(e)])


# Compatibility wrapper for member notifications
def send_member_notification(
    member_name: str, notification_type: str, context: Dict[str, Any] = None, **kwargs
) -> OperationResult[Dict[str, Any]]:
    """
    Backward compatibility wrapper for member notification sending.

    Replaces the notification methods in member_subscribers.py.

    Returns:
        OperationResult[Dict]: Notification sending result

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - Compatibility wrapper for gradual migration
    """
    try:
        member = frappe.get_doc("Member", member_name)
        if not member.email:
            return OperationResult.fail(
                "Member has no email address", errors=["No email"], member=member_name
            )

        email_service = get_email_service()

        # Map old notification types to new system
        notification_mapping = {
            "approval": "member_approval",
            "suspension": "member_suspension",
            "termination": "member_termination",
            "reactivation": "member_reactivation",
        }

        mapped_type = notification_mapping.get(notification_type, notification_type)

        notification_context = context or {}
        notification_context.update(
            {"member_name": member.full_name, "membership_number": member.name, "member": member}
        )

        result = email_service.send_notification(
            notification_type=mapped_type,
            recipients=[member.email],
            data=notification_context,
            reference_doctype="Member",
            reference_name=member_name,
            **kwargs,
        )

        # Convert dict result to OperationResult
        if isinstance(result, dict):
            if result.get("success"):
                return OperationResult.ok(
                    result, message=result.get("message", "Notification sent successfully")
                )
            else:
                return OperationResult.fail(
                    result.get("message", "Notification sending failed"),
                    errors=result.get("errors", []),
                    member=member_name,
                )
        return result  # Already OperationResult

    except Exception as e:
        frappe.logger("email_compatibility").error(f"Member notification compatibility failed: {str(e)}")
        return OperationResult.fail(
            f"Member notification failed: {str(e)}", errors=[str(e)], member=member_name
        )


# Compatibility wrapper for chapter communications
def send_chapter_email(
    chapter_name: str,
    recipients: List[str],
    subject: str,
    content: str = None,
    template: str = None,
    context: Dict[str, Any] = None,
    communication_type: str = "Email",
    **kwargs,
) -> OperationResult[Dict[str, Any]]:
    """
    Backward compatibility wrapper for chapter communication sending.

    Replaces CommunicationManager._send_templated_email.

    Returns:
        OperationResult[Dict]: Email sending result

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - Compatibility wrapper for gradual migration
    """
    try:
        email_service = get_email_service()

        if template:
            result = email_service.send_templated_email(
                template_name=template,
                recipients=recipients,
                context=context or {},
                subject_override=subject,
                reference_doctype="Chapter",
                reference_name=chapter_name,
                **kwargs,
            )
        else:
            result = email_service._send_email_internal(
                recipients=recipients,
                subject=subject,
                content=content or "",
                reference_doctype="Chapter",
                reference_name=chapter_name,
                **kwargs,
            )

        # Convert dict result to OperationResult
        if isinstance(result, dict):
            if result.get("success"):
                return OperationResult.ok(
                    result, message=result.get("message", "Chapter email sent successfully")
                )
            else:
                return OperationResult.fail(
                    result.get("message", "Chapter email sending failed"),
                    errors=result.get("errors", []),
                    chapter=chapter_name,
                )
        return result  # Already OperationResult

    except Exception as e:
        frappe.logger("email_compatibility").error(f"Chapter email compatibility failed: {str(e)}")
        return OperationResult.fail(f"Chapter email failed: {str(e)}", errors=[str(e)], chapter=chapter_name)


# Legacy template email function (for newsletter templates)
def send_templated_email_legacy(
    template_id: str, variables: str, chapter_name: str = None, segment: str = "all", **kwargs
) -> OperationResult[Dict[str, Any]]:
    """
    Backward compatibility for newsletter template system.

    Returns:
        OperationResult[Dict]: Email sending result

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - Compatibility wrapper for gradual migration
    """
    try:
        import json

        email_service = get_email_service()

        # Parse variables JSON
        context = json.loads(variables) if isinstance(variables, str) else variables

        # Get recipients based on segment
        recipients = get_segment_recipients(segment, chapter_name)

        result = email_service.send_templated_email(
            template_name=template_id,
            recipients=recipients,
            context=context,
            reference_doctype="Chapter" if chapter_name else None,
            reference_name=chapter_name,
            **kwargs,
        )

        # Convert dict result to OperationResult
        if isinstance(result, dict):
            if result.get("success"):
                return OperationResult.ok(
                    result, message=result.get("message", "Template email sent successfully")
                )
            else:
                return OperationResult.fail(
                    result.get("message", "Template email sending failed"),
                    errors=result.get("errors", []),
                    template=template_id,
                )
        return result  # Already OperationResult

    except Exception as e:
        frappe.logger("email_compatibility").error(f"Template email legacy compatibility failed: {str(e)}")
        return OperationResult.fail(
            f"Legacy template email failed: {str(e)}", errors=[str(e)], template=template_id
        )


def get_segment_recipients(segment: str, chapter_name: str = None) -> List[str]:
    """Get email recipients based on segment and chapter."""
    try:
        filters = {"status": "Active"}
        if chapter_name:
            # Get members of specific chapter
            chapter_members = frappe.get_all(
                "Chapter Member", filters={"chapter": chapter_name, "status": "Active"}, fields=["member"]
            )
            member_names = [cm.member for cm in chapter_members]
            filters["name"] = ["in", member_names]

        if segment == "all":
            members = frappe.get_all("Member", filters=filters, fields=["email"])
        elif segment == "board":
            # Get board members only
            board_members = frappe.get_all(
                "Chapter Board Member", filters={"status": "Active"}, fields=["member"]
            )
            board_member_names = [bm.member for bm in board_members]
            filters["name"] = ["in", board_member_names]
            members = frappe.get_all("Member", filters=filters, fields=["email"])
        else:
            # Default to all
            members = frappe.get_all("Member", filters=filters, fields=["email"])

        return [m.email for m in members if m.email]

    except Exception as e:
        frappe.logger("email_compatibility").error(f"Segment recipient lookup failed: {str(e)}")
        return []


# Function aliases for gradual migration
send_email_notification = send_member_notification  # Alias for member notifications
send_templated_chapter_email = send_chapter_email  # Alias for chapter communications
