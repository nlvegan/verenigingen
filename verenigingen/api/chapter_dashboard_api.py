"""
Chapter Dashboard API — Production Endpoints

API endpoints for the Chapter Dashboard: member management, statistics,
announcements, and financial reporting. Debug/admin/setup functions are
in chapter_dashboard_debug.py.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.utils.error_handling import (
    PermissionError,
    handle_api_error,
    validate_required_fields,
)
from verenigingen.utils.performance_utils import cached, performance_monitor
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.validation.api_validators import APIValidator


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)  # Member data access
@handle_api_error
@performance_monitor(threshold_ms=500)
@cached(ttl=300)  # Cache for 5 minutes
def get_chapter_member_emails(chapter_name: str):
    """
    Retrieve email addresses of all active chapter members.

    This function provides chapter board members with a list of email addresses
    for all active members in their chapter, enabling bulk communication and
    member outreach activities.

    Args:
        chapter_name (str): The name/ID of the chapter to get member emails for.
                           Must be a valid chapter that the requesting user has
                           board access to.

    Returns:
        list[str]: List of unique email addresses of active chapter members,
                  sorted alphabetically. Empty strings and None values are filtered out.

    Example:
        >>> emails = get_chapter_member_emails("Amsterdam")
        >>> print(emails)
        ['alice@example.com', 'bob@example.com', 'charlie@example.com']

    Raises:
        PermissionError: If the user doesn't have board access to the specified chapter
        ValidationError: If chapter_name is empty or invalid

    Security:
        - Validates user has board access to the requested chapter
        - Sanitizes input to prevent injection attacks
        - Uses high-security API decorators
        - Caches results for performance (5-minute TTL)

    Performance:
        - Optimized SQL query with proper joins
        - Monitoring threshold: 500ms
        - Result caching to reduce database load
        - Returns only distinct email addresses

    Database Access:
        - Reads from: tabChapter Member, tabMember
        - Filters: Active members only, non-empty emails
        - Join: Chapter Member -> Member on member field
    """

    # Validate inputs
    validate_required_fields({"chapter_name": chapter_name}, ["chapter_name"])

    chapter_name = APIValidator.sanitize_text(chapter_name, max_length=100)

    # Verify user has access to this chapter
    from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

    user_chapters = get_user_board_chapters()
    if not any(ch["chapter_name"] == chapter_name for ch in user_chapters):
        raise PermissionError("You don't have access to this chapter")

    # Get active member emails
    emails = frappe.db.sql(
        """
        SELECT DISTINCT m.email
        FROM `tabChapter Member` cm
        INNER JOIN `tabMember` m ON cm.member = m.name
        WHERE cm.parent = %s
        AND cm.enabled = 1
        AND (cm.status = 'Active' OR cm.status IS NULL)
        AND m.email IS NOT NULL
        AND m.email != ''
        ORDER BY m.email
    """,
        (chapter_name,),
        as_list=True,
    )

    return [email[0] for email in emails if email[0]]


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)  # Member approval operations
@handle_api_error
@performance_monitor(threshold_ms=2000)
def quick_approve_member(member_name: str, chapter_name: str | None = None):
    """
    Quickly approve a pending member application from the chapter dashboard.

    This function allows chapter board members to approve pending membership
    applications with a single API call. It handles the complete approval
    workflow including status updates and notification triggers.

    Args:
        member_name (str): The unique identifier/name of the member to approve.
                          Must be a valid Member document name.
        chapter_name (str, optional): The chapter name for the approval.
                                     If not provided, will be determined from
                                     the member's current chapter or pending
                                     chapter membership records.

    Returns:
        dict: Approval result with success status and updated member information.

    Example:
        >>> result = quick_approve_member("MEM-2024-001", "Amsterdam")
        >>> print(result)
        {
            'success': True,
            'member_name': 'MEM-2024-001',
            'chapter': 'Amsterdam',
            'status': 'Approved',
            'approval_date': '2024-08-02 14:30:00'
        }

    Raises:
        PermissionError: If user is not a board member or lacks access to the chapter
        ValidationError: If member_name is invalid or member is not in pending status

    Security:
        - Validates user has board member role for the target chapter
        - Sanitizes all input parameters
        - Uses high-security API decorators
        - Logs all approval actions for audit trail

    Performance:
        - Monitoring threshold: 2000ms (approval can involve multiple operations)
        - Optimized database queries for member lookup
        - Batch processing for related updates

    Business Logic:
        - Only pending applications can be approved
        - Triggers post-approval workflows (welcome emails, etc.)
        - Updates member status and chapter membership records
        - Creates audit trail for the approval action

    Database Access:
        - Reads from: tabMember, tabChapter Member
        - Updates: Member status, Chapter Member status
        - Creates: Audit log entries
    """

    # Validate inputs
    validate_required_fields({"member_name": member_name}, ["member_name"])

    member_name = APIValidator.sanitize_text(member_name, max_length=100)
    chapter_name = APIValidator.sanitize_text(chapter_name, max_length=100) if chapter_name else None

    # Verify permissions
    from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters, get_user_board_role

    user_chapters = get_user_board_chapters()
    if not user_chapters:
        raise PermissionError("You must be a board member to approve applications")

    # Get member's chapter if not specified
    if not chapter_name:
        member_chapter = frappe.db.get_value("Member", member_name, "current_chapter_display")
        if not member_chapter:
            # Find from Chapter Member records
            chapter_member = frappe.db.get_value(
                "Chapter Member", {"member": member_name, "status": "Pending"}, "parent"
            )
            if chapter_member:
                chapter_name = chapter_member
            else:
                frappe.throw(_("Could not determine member's chapter"))
        else:
            chapter_name = member_chapter

    # Verify user has access to this chapter
    if not any(ch["chapter_name"] == chapter_name for ch in user_chapters):
        frappe.throw(_("You don't have access to this chapter"))

    # Check approval permissions
    user_role = get_user_board_role(chapter_name)
    if not (user_role and user_role.get("permissions", {}).get("can_approve_members", False)):
        frappe.throw(_("You don't have permission to approve members"))

    try:
        # Check if this is a chapter join request (pending Chapter Member) or membership application
        pending_chapter_member = frappe.db.get_value(
            "Chapter Member", {"member": member_name, "parent": chapter_name, "status": "Pending"}, "name"
        )

        if pending_chapter_member:
            chapter_doc = frappe.get_doc("Chapter", chapter_name)
            result = chapter_doc.member_manager.approve_member_request(  # ast-skip: @property not field
                member_id=member_name, approved_by=frappe.session.user
            )
        else:
            # This is a membership application - use existing approval function
            from verenigingen.api.membership_application_review import approve_membership_application

            result = approve_membership_application(
                member_name=member_name,
                chapter=chapter_name,
                notes=f"Approved via chapter dashboard by {frappe.session.user}",
            )

        if result.get("success"):
            # Log the dashboard approval
            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            from verenigingen.utils.secure_operations import secure_document_operation

            comment_doc = frappe.get_doc(
                {
                    "doctype": "Comment",
                    "comment_type": "Info",
                    "reference_doctype": "Member",
                    "reference_name": member_name,
                    "content": f"Member approved via chapter dashboard by {frappe.get_user().full_name}",
                }
            )

            # Secure audit trail comment creation with explicit permission validation
            comment_result = secure_document_operation(
                operation="insert",
                doc=comment_doc,
                justification=f"Chapter governance audit trail for member approval {member_name}",
                required_permissions=["Comment:create"],
            )

            if not comment_result.success:
                frappe.logger().warning(
                    f"Failed to create approval audit trail comment: {'; '.join(comment_result.errors)}"
                )
                # Don't block the approval if audit trail fails

            return {"success": True, "message": _("Member approved successfully"), "member_name": member_name}
        else:
            return {"success": False, "error": result.get("message", "Unknown error occurred")}

    except Exception as e:
        frappe.log_error(f"Error in quick_approve_member: {str(e)}", "Chapter Dashboard API")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def reprocess_mt940_import(import_name: str):
    """Reprocess an existing MT940 import"""
    try:
        import_doc = frappe.get_doc("MT940 Import", import_name)

        # Reset counters
        import_doc.transactions_created = 0
        import_doc.transactions_skipped = 0
        import_doc.import_status = "In Progress"
        import_doc.save()

        # Process the import
        result = import_doc.process_mt940_import()

        if result.get("success"):
            import_doc.import_status = "Completed"
            import_doc.import_summary = result.get("message", "Import completed successfully")
            import_doc.transactions_created = result.get("transactions_created", 0)
            import_doc.transactions_skipped = result.get("transactions_skipped", 0)

            # Extract and set date range information
            import_doc.extract_date_range_from_result(result)
        else:
            import_doc.import_status = "Failed"
            import_doc.import_summary = result.get("message", "Import failed")
            import_doc.error_log = str(result.get("errors", []))

        import_doc.save()

        return {
            "success": True,
            "result": result,
            "import_doc": {
                "name": import_doc.name,
                "import_status": import_doc.import_status,
                "transactions_created": import_doc.transactions_created,
                "transactions_skipped": import_doc.transactions_skipped,
                "import_summary": import_doc.import_summary,
                "descriptive_name": (
                    import_doc.descriptive_name if hasattr(import_doc, "descriptive_name") else None
                ),
                "statement_from_date": (
                    str(import_doc.statement_from_date)
                    if hasattr(import_doc, "statement_from_date") and import_doc.statement_from_date
                    else None
                ),
                "statement_to_date": (
                    str(import_doc.statement_to_date)
                    if hasattr(import_doc, "statement_to_date") and import_doc.statement_to_date
                    else None
                ),
            },
        }

    except Exception as e:
        frappe.log_error(f"Error in reprocess_mt940_import: {str(e)}", "MT940 Reprocessing")
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)  # Dashboard notifications - read-only
def get_dashboard_notifications():
    """Get notifications for dashboard (upcoming deadlines, overdue items, etc.)"""

    from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

    user_chapters = get_user_board_chapters()
    if not user_chapters:
        return []

    notifications = []

    for chapter_info in user_chapters:
        chapter_name = chapter_info["chapter_name"]

        # Check for overdue applications
        overdue_apps = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabChapter Member` cm
            INNER JOIN `tabMember` m ON cm.member = m.name
            WHERE cm.parent = %s
            AND cm.status = 'Pending'
            AND DATEDIFF(CURDATE(), COALESCE(m.application_date, cm.chapter_join_date)) > 7
        """,
            (chapter_name,),
            as_dict=True,
        )[0]

        if overdue_apps.count > 0:
            notifications.append(
                {
                    "type": "warning",
                    "chapter": chapter_name,
                    "title": _("Overdue Applications"),
                    "message": _("{0} membership applications are overdue for review").format(
                        overdue_apps.count
                    ),
                    "action": "review_applications",
                    "priority": "high",
                }
            )

        # Check for pending applications
        pending_apps = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabChapter Member` cm
            WHERE cm.parent = %s AND cm.status = 'Pending'
        """,
            (chapter_name,),
            as_dict=True,
        )[0]

        if pending_apps.count > 0 and overdue_apps.count == 0:
            notifications.append(
                {
                    "type": "info",
                    "chapter": chapter_name,
                    "title": _("Pending Applications"),
                    "message": _("{0} membership applications pending review").format(pending_apps.count),
                    "action": "review_applications",
                    "priority": "medium",
                }
            )

    return notifications


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)  # Chapter statistics - read-only
def get_chapter_quick_stats(chapter_name: str):
    """Get quick statistics for a specific chapter"""

    from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

    user_chapters = get_user_board_chapters()
    if not any(ch["chapter_name"] == chapter_name for ch in user_chapters):
        frappe.throw(_("You don't have access to this chapter"))

    # Member statistics - SQL query result with custom field names (not DocType fields)
    member_stats = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN (status = 'Active' OR status IS NULL) AND enabled = 1 THEN 1 ELSE 0 END) as active,
            SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN enabled = 0 THEN 1 ELSE 0 END) as inactive,
            SUM(CASE WHEN chapter_join_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) as new_this_week,
            SUM(CASE WHEN chapter_join_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) THEN 1 ELSE 0 END) as new_this_month
        FROM `tabChapter Member`
        WHERE parent = %s
    """,
        (chapter_name,),
        as_dict=True,
    )[0]

    # Board member count
    board_count = frappe.db.count("Chapter Board Member", {"parent": chapter_name, "is_active": 1})

    # Recent activity count (last 7 days)
    recent_activity = frappe.db.count(
        "Comment",
        {
            "reference_doctype": "Chapter",
            "reference_name": chapter_name,
            "creation": [">=", frappe.utils.add_days(today(), -7)],
        },
    )

    return {
        "chapter_name": chapter_name,
        "members": {
            "total": frappe.utils.cint(member_stats.total or 0),
            "active": frappe.utils.cint(member_stats.active or 0),
            "pending": frappe.utils.cint(member_stats.pending or 0),
            "inactive": frappe.utils.cint(member_stats.inactive or 0),
            "new_this_week": frappe.utils.cint(member_stats.new_this_week or 0),
            "new_this_month": frappe.utils.cint(member_stats.new_this_month or 0),
        },
        "board_members": board_count,
        "recent_activity_count": recent_activity,
        "last_updated": now_datetime(),
    }


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)  # Member application rejection
def reject_member_application(member_name: str, chapter_name: str, reason: str | None = None):
    """Reject a member application from dashboard"""

    from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters, get_user_board_role

    # Verify permissions
    user_chapters = get_user_board_chapters()
    if not any(ch["chapter_name"] == chapter_name for ch in user_chapters):
        frappe.throw(_("You don't have access to this chapter"))

    user_role = get_user_board_role(chapter_name)
    if not (user_role and user_role.get("permissions", {}).get("can_approve_members", False)):
        frappe.throw(_("You don't have permission to reject members"))

    try:
        # Check if this is a chapter join request (pending Chapter Member) or membership application
        pending_chapter_member = frappe.db.get_value(
            "Chapter Member", {"member": member_name, "parent": chapter_name, "status": "Pending"}, "name"
        )

        if pending_chapter_member:
            chapter_doc = frappe.get_doc("Chapter", chapter_name)
            result = chapter_doc.member_manager.reject_member_request(  # ast-skip: @property not field
                member_id=member_name,
                reason=reason or "Rejected via chapter dashboard",
                rejected_by=frappe.session.user,
            )

            if not result.get("success"):
                return {"success": False, "error": result.get("message", "Unknown error occurred")}

            # Log the dashboard rejection
            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            from verenigingen.utils.secure_operations import secure_document_operation

            rejection_comment_doc = frappe.get_doc(
                {
                    "doctype": "Comment",
                    "comment_type": "Info",
                    "reference_doctype": "Member",
                    "reference_name": member_name,
                    "content": f"Chapter join request rejected via dashboard by {frappe.get_user().full_name}. Reason: {reason or 'No reason provided'}",
                }
            )

            # Secure audit trail comment creation with explicit permission validation
            rejection_comment_result = secure_document_operation(
                operation="insert",
                doc=rejection_comment_doc,
                justification=f"Chapter governance audit trail for join request rejection {member_name}",
                required_permissions=["Comment:create"],
            )

            if not rejection_comment_result.success:
                frappe.logger().warning(
                    f"Failed to create rejection audit trail comment: {'; '.join(rejection_comment_result.errors)}"
                )
                # Don't block the rejection if audit trail fails

            return {"success": True, "message": _("Join request rejected successfully")}

        # Original membership application rejection logic
        chapter_member = frappe.db.get_value(
            "Chapter Member", {"member": member_name, "parent": chapter_name, "status": "Pending"}, "name"
        )

        if not chapter_member:
            frappe.throw(_("Pending application not found"))

        # Update member status
        member_doc = frappe.get_doc("Member", member_name)
        member_doc.application_status = "Rejected"
        member_doc.review_notes = reason or f"Rejected via chapter dashboard by {frappe.session.user}"
        member_doc.reviewed_by = frappe.session.user
        member_doc.review_date = now_datetime()
        member_doc.save()

        # Remove from Chapter Member table
        frappe.delete_doc("Chapter Member", chapter_member)

        # Add comment
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        from verenigingen.utils.secure_operations import secure_document_operation

        app_rejection_comment_doc = frappe.get_doc(
            {
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "Member",
                "reference_name": member_name,
                "content": f"Application rejected via chapter dashboard by {frappe.get_user().full_name}. Reason: {reason or 'No reason provided'}",
            }
        )

        # Secure audit trail comment creation with explicit permission validation
        app_rejection_result = secure_document_operation(
            operation="insert",
            doc=app_rejection_comment_doc,
            justification=f"Chapter governance audit trail for application rejection {member_name}",
            required_permissions=["Comment:create"],
        )

        if not app_rejection_result.success:
            frappe.logger().warning(
                f"Failed to create application rejection audit trail comment: {'; '.join(app_rejection_result.errors)}"
            )
            # Don't block the rejection if audit trail fails

        return {"success": True, "message": _("Application rejected successfully")}

    except Exception as e:
        frappe.log_error(f"Error rejecting member application: {str(e)}", "Chapter Dashboard API")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)  # Chapter announcement operations
def send_chapter_announcement(chapter_name: str, subject: str, message: str, send_to: str = "all"):
    """Send announcement to chapter members"""

    from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters, get_user_board_role

    # Verify permissions
    user_chapters = get_user_board_chapters()
    if not any(ch["chapter_name"] == chapter_name for ch in user_chapters):
        frappe.throw(_("You don't have access to this chapter"))

    user_role = get_user_board_role(chapter_name)
    if not (user_role and user_role.get("permissions", {}).get("can_approve_members", False)):
        frappe.throw(_("You don't have permission to send announcements"))

    try:
        # Get recipient emails based on send_to parameter
        if send_to == "all":
            emails = get_chapter_member_emails(chapter_name)
        elif send_to == "active":
            emails = frappe.db.sql(
                """
                SELECT DISTINCT m.email
                FROM `tabChapter Member` cm
                INNER JOIN `tabMember` m ON cm.member = m.name
                WHERE cm.parent = %s
                AND cm.enabled = 1
                AND (cm.status = 'Active' OR cm.status IS NULL)
                AND m.email IS NOT NULL
            """,
                (chapter_name,),
                as_list=True,
            )
            emails = [email[0] for email in emails if email[0]]
        elif send_to == "board":
            emails = frappe.db.sql(
                """
                SELECT DISTINCT cbm.email
                FROM `tabChapter Board Member` cbm
                WHERE cbm.parent = %s
                AND cbm.is_active = 1
                AND cbm.email IS NOT NULL
            """,
                (chapter_name,),
                as_list=True,
            )
            emails = [email[0] for email in emails if email[0]]
        else:
            frappe.throw(_("Invalid recipient type"))

        if not emails:
            frappe.throw(_("No email addresses found for the selected recipients"))

        # Send emails (this would typically use Frappe's email queue)
        from frappe.utils.email_lib import sendmail

        for email in emails:
            try:
                sendmail(
                    recipients=[email],
                    subject=f"[{chapter_name}] {subject}",
                    message=message,
                    sender=frappe.session.user,
                )
            except Exception as e:
                frappe.log_error(f"Failed to send email to {email}: {str(e)}", "Chapter Announcement")

        # Log the announcement
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        from verenigingen.utils.secure_operations import secure_document_operation

        announcement_comment_doc = frappe.get_doc(
            {
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "Chapter",
                "reference_name": chapter_name,
                "content": f"Announcement sent to {send_to} members by {frappe.get_user().full_name}: {subject}",
            }
        )

        # Secure audit trail comment creation with explicit permission validation
        announcement_result = secure_document_operation(
            operation="insert",
            doc=announcement_comment_doc,
            justification=f"Chapter governance audit trail for announcement to {chapter_name}",
            required_permissions=["Comment:create"],
        )

        if not announcement_result.success:
            frappe.logger().warning(
                f"Failed to create announcement audit trail comment: {'; '.join(announcement_result.errors)}"
            )
            # Don't block the announcement if audit trail fails

        return {
            "success": True,
            "message": _("Announcement sent to {0} recipients").format(len(emails)),
            "recipients_count": len(emails),
        }

    except Exception as e:
        frappe.log_error(f"Error sending chapter announcement: {str(e)}", "Chapter Dashboard API")
        return {"success": False, "error": str(e)}


# Number Card API methods for Frappe Dashboard
@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)  # Member count statistics - read-only
def get_active_members_count(chapter: str | None = None):
    """Get count of active members for dashboard number card"""

    if not chapter:
        # If no chapter specified, get user's chapters and sum them
        from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

        user_chapters = get_user_board_chapters()
        if not user_chapters:
            return {"value": 0, "fieldtype": "Data"}

        total = 0
        for ch in user_chapters:
            count = frappe.db.count(
                "Chapter Member",
                {"parent": ch["chapter_name"], "enabled": 1, "status": ["in", ["Active", ""]]},
            )
            total += count
        return {"value": total, "fieldtype": "Data"}
    else:
        # Specific chapter
        count = frappe.db.count(
            "Chapter Member", {"parent": chapter, "enabled": 1, "status": ["in", ["Active", ""]]}
        )
        return {"value": count, "fieldtype": "Data"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)  # Application count statistics - read-only
def get_pending_applications_count(chapter: str | None = None):
    """Get count of pending applications for dashboard number card"""

    if not chapter:
        from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

        user_chapters = get_user_board_chapters()
        if not user_chapters:
            return {"value": 0, "fieldtype": "Data"}

        total = 0
        for ch in user_chapters:
            count = frappe.db.count("Chapter Member", {"parent": ch["chapter_name"], "status": "Pending"})
            total += count
        return {"value": total, "fieldtype": "Data"}
    else:
        count = frappe.db.count("Chapter Member", {"parent": chapter, "status": "Pending"})
        return {"value": count, "fieldtype": "Data"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)  # Board member count statistics - read-only
def get_board_members_count(chapter: str | None = None):
    """Get count of active board members for dashboard number card"""

    if not chapter:
        from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

        user_chapters = get_user_board_chapters()
        if not user_chapters:
            return {"value": 0, "fieldtype": "Data"}

        total = 0
        for ch in user_chapters:
            count = frappe.db.count("Chapter Board Member", {"parent": ch["chapter_name"], "is_active": 1})
            total += count
        return {"value": total, "fieldtype": "Data"}
    else:
        count = frappe.db.count("Chapter Board Member", {"parent": chapter, "is_active": 1})
        return {"value": count, "fieldtype": "Data"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)  # New member count statistics - read-only
def get_new_members_count(chapter: str | None = None):
    """Get count of new members this month for dashboard number card"""

    from frappe.utils import getdate, today

    # Get first day of current month
    today_date = getdate(today())
    month_start = today_date.replace(day=1)

    if not chapter:
        from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

        user_chapters = get_user_board_chapters()
        if not user_chapters:
            return {"value": 0, "fieldtype": "Data"}

        total = 0
        for ch in user_chapters:
            count = frappe.db.count(
                "Chapter Member",
                {"parent": ch["chapter_name"], "chapter_join_date": [">=", month_start], "enabled": 1},
            )
            total += count
        return {"value": total, "fieldtype": "Data"}
    else:
        count = frappe.db.count(
            "Chapter Member", {"parent": chapter, "chapter_join_date": [">=", month_start], "enabled": 1}
        )
        return {"value": count, "fieldtype": "Data"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_dashboard_completion_summary():
    """Get final summary of the completed dashboard"""

    try:
        # Get dashboard details
        dashboard = frappe.get_doc("Dashboard", "Chapter Board Dashboard")

        # Get number of cards and charts
        cards = [card.card for card in dashboard.cards]
        charts = [chart.chart for chart in dashboard.charts]

        # Check if user has access
        user_chapters = []
        try:
            from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

            user_chapters = get_user_board_chapters()
        except Exception:
            pass

        return {
            "success": True,
            "dashboard_info": {
                "name": dashboard.dashboard_name,
                "module": dashboard.module,
                "is_standard": dashboard.is_standard,
                "creation": str(dashboard.creation),
                "modified": str(dashboard.modified),
            },
            "components": {
                "cards_count": len(cards),
                "charts_count": len(charts),
                "cards": cards,
                "charts": charts,
            },
            "access_info": {
                "current_user": frappe.session.user,
                "user_roles": frappe.get_roles(),
                "has_board_access": len(user_chapters) > 0,
                "board_chapters": user_chapters,
            },
            "urls": {
                "desktop": "https://dev.veganisme.net/app/dashboard-view/Chapter%20Board%20Dashboard",
                "mobile": "https://dev.veganisme.net/app/dashboard-view/Chapter%20Board%20Dashboard",
                "direct_link": "/app/dashboard-view/Chapter%20Board%20Dashboard",
            },
            "navigation_instructions": [
                "1. Go to https://dev.veganisme.net",
                "2. Login with your credentials",
                "3. Navigate to Desk > Dashboard menu",
                "4. Click on Chapter Board Dashboard",
                "OR",
                "5. Use direct URL: https://dev.veganisme.net/app/dashboard-view/Chapter%20Board%20Dashboard",
            ],
            "features": [
                "Real-time chapter metrics via number cards",
                "Visual charts for member data analysis",
                "Board member access control",
                "Multi-chapter support for board members",
                "Native Frappe dashboard UI",
                "Mobile responsive design",
                "Auto-refreshing data",
            ],
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_filed_expense_claims_count(chapter: str | None = None):
    """Get count of filed expense claims for dashboard number card"""

    if not chapter:
        # For board members, get claims from their chapters
        from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

        user_chapters = get_user_board_chapters()
        if not user_chapters:
            return {"value": 0, "fieldtype": "Data"}

        # Count all filed expense claims (non-draft status)
        total = frappe.db.count("Expense Claim", {"approval_status": ["!=", "Draft"]})
        return {"value": total, "fieldtype": "Data"}
    else:
        # For specific chapter (if we add chapter filtering later)
        count = frappe.db.count("Expense Claim", {"approval_status": ["!=", "Draft"]})
        return {"value": count, "fieldtype": "Data"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_approved_expense_claims_count(chapter: str | None = None):
    """Get count of approved expense claims for dashboard number card"""

    if not chapter:
        # For board members, get approved claims
        from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

        user_chapters = get_user_board_chapters()
        if not user_chapters:
            return {"value": 0, "fieldtype": "Data"}

        # Count approved expense claims
        total = frappe.db.count("Expense Claim", {"approval_status": "Approved"})
        return {"value": total, "fieldtype": "Data"}
    else:
        # For specific chapter
        count = frappe.db.count("Expense Claim", {"approval_status": "Approved"})
        return {"value": count, "fieldtype": "Data"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_volunteer_expenses_count(chapter: str | None = None):
    """Get count of volunteer expenses for dashboard number card"""

    if not chapter:
        from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

        user_chapters = get_user_board_chapters()
        if not user_chapters:
            return {"value": 0, "fieldtype": "Data"}

        # Count submitted volunteer expenses
        total = frappe.db.count("Volunteer Expense", {"status": "Submitted"})
        return {"value": total, "fieldtype": "Data"}
    else:
        count = frappe.db.count("Volunteer Expense", {"status": "Submitted"})
        return {"value": count, "fieldtype": "Data"}
