"""
Chapter Dashboard API — Production Endpoints

API endpoints for the Chapter Dashboard: member management, statistics,
announcements, and financial reporting. Debug/admin/setup functions are
in chapter_dashboard_debug.py.
"""

import frappe
from frappe import _

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
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS
from verenigingen.utils.validation.api_validators import APIValidator


@cached(ttl=300)  # Cache for 5 minutes
def _fetch_chapter_member_emails(chapter_name: str) -> list:
    """Return active member emails for a chapter. NO permission check - callers must gate.

    Split out of get_chapter_member_emails so the cache holds only chapter-scoped data.
    The access check must run on every call and therefore cannot live inside a cached
    function; see the SECURITY note on the caller.
    """
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
@high_security_api(operation_type=OperationType.MEMBER_DATA)  # Member data access
@handle_api_error
@performance_monitor(threshold_ms=500)
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
        - Validates user has board access to the requested chapter, on EVERY call
        - Sanitizes input to prevent injection attacks
        - Uses high-security API decorators
        - Only the chapter-scoped query is cached (see _fetch_chapter_member_emails);
          the access check deliberately sits outside the cache

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

    # Verify user has access to this chapter.
    #
    # SECURITY: this must run on every call, so it cannot sit inside a cached function.
    # @cached used to be the innermost decorator on this endpoint, which put this check
    # inside the cache: a hit returned before it ran, and the cache key
    # (performance_utils.py::cached) carries no user while CacheManager._cache is
    # process-wide. Any caller clearing the HIGH tier - e.g. a board member of another
    # chapter, who holds HIGH per authorization_policy.py - therefore read any warmed
    # chapter's member emails for 5 minutes. Only the chapter-scoped query is cached now.
    from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

    user_chapters = get_user_board_chapters()
    if not any(ch["chapter_name"] == chapter_name for ch in user_chapters):
        raise PermissionError("You don't have access to this chapter")

    return _fetch_chapter_member_emails(chapter_name)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)  # Member approval operations
@handle_api_error
@performance_monitor(threshold_ms=2000)
def quick_approve_application(application_name: str):
    """Approve a Pending Review application from the chapter dashboard (#1765).

    This is `approve_application` and nothing else: it creates or updates the Member, assigns the
    chapter and runs the approval core. The permission check (an Admin-level seat on the application's
    chapter, or an administrator) is approve_application's own and comes first, so an unknown and a
    foreign application are refused the same way. The old branch that flipped only the Chapter
    Member row of a "pending" member is gone: an application has no Member until it is approved.
    (A chapter JOIN request from an existing member is approved by quick_approve_join_request.)

    Returns the dict `approve_application` returns (`success`, `member`, `application`, ...).
    """
    from verenigingen.api.membership_application_review import approve_application
    from verenigingen.services.chapter.chapter_security import validate_application_permission_or_throw
    from verenigingen.templates.pages.chapter_dashboard import get_user_board_role

    validate_required_fields({"application_name": application_name}, ["application_name"])
    application_name = str(application_name)

    # approve_application repeats this check; it comes first here so the dashboard's own gate below
    # never runs for an application the caller may not even see (an unknown and a foreign application
    # are refused identically, #1765 Ruling M).
    validate_application_permission_or_throw(application_name, "approve")

    # The dashboard's own gate, kept from before: approving here needs a board role that carries
    # can_approve_members on the application's chapter (or an administrator). Staff have no board role,
    # so this stays a board action even though staff may approve on the review page.
    chapter = frappe.db.get_value("Membership Application Submission", application_name, "chapter")
    user_role = get_user_board_role(chapter)
    if not (user_role and user_role.get("permissions", {}).get("can_approve_members", False)):
        frappe.throw(_("You don't have permission to approve members"))

    return approve_application(
        application_name=application_name,
        notes=f"Approved via chapter dashboard by {frappe.session.user}",
    )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)  # Member approval operations
@handle_api_error
@performance_monitor(threshold_ms=2000)
def quick_approve_join_request(member_name: str, chapter_name: str | None = None):
    """Approve a chapter JOIN request (a Pending Chapter Member row of an existing member) from the dashboard.

    This is the half of the old quick_approve_member that served join requests (#1867). An application
    is approved by quick_approve_application; it has no Member until then.

    The chapter is the one with exactly one Pending row for this member when `chapter_name` is not
    given. An unknown member, a row in a chapter the caller does not manage, and a row pending in several
    chapters all refuse with the same message (existence oracle, #1360). Approving needs a board role
    carrying can_approve_members on that chapter (or an administrator); staff have no board role.
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

    # Get member's chapter if not specified. The chapter an approval is FOR is
    # whichever chapter has a "Pending" Chapter Member row for this member --
    # both the chapter-join-request flow and the membership-application flow
    # write that row at submission (application_helpers.py::
    # create_pending_chapter_membership). Member.current_chapter_display is an
    # HTML-fieldtype field with no DB column (#1516): querying it here always
    # raised OperationalError, before the access check below -- or the two
    # frappe.throw()s #1360 flagged as a possible existence-oracle pair --
    # were ever reached.
    #
    # WHY refuse identically for "no pending row anywhere" (nonexistent member,
    # or one with none) and "pending in more than one chapter at once"
    # (picking either would be a silent wrong-chapter approval): both now
    # throw the exact same message as "resolved a chapter, but not one the
    # caller manages" below. Distinguishing any of these would let a board
    # member learn things about members outside their chapter -- the
    # existence-oracle variant #1360 flagged, dormant only because this line
    # always crashed first.
    if not chapter_name:
        pending_chapters = set(
            frappe.get_all(
                "Chapter Member",
                filters={"member": member_name, "status": "Pending"},
                pluck="parent",
            )
        )
        if len(pending_chapters) != 1:
            frappe.throw(_("You don't have access to this chapter"))
        chapter_name = pending_chapters.pop()

    # Verify user has access to this chapter
    if not any(ch["chapter_name"] == chapter_name for ch in user_chapters):
        frappe.throw(_("You don't have access to this chapter"))

    # Check approval permissions
    user_role = get_user_board_role(chapter_name)
    if not (user_role and user_role.get("permissions", {}).get("can_approve_members", False)):
        frappe.throw(_("You don't have permission to approve members"))

    try:
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        result = chapter_doc.member_manager.approve_member_request(  # ast-skip: @property not field
            member_id=member_name, approved_by=frappe.session.user
        )

        if result.get("success"):
            # Log the dashboard approval
            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            from verenigingen.utils.secure_operations import secure_document_operation

            # WHY: frappe.get_user() returns a UserPermissions object, which has
            # no `full_name` attribute -> AttributeError. That exception was caught
            # by the broad except below and surfaced as {"success": False}, so the
            # caller saw a *failure* even though the membership approval had already
            # committed. Use frappe.utils.get_fullname(session.user) instead.
            approver_full_name = frappe.utils.get_fullname(frappe.session.user)
            comment_doc = frappe.get_doc(
                {
                    "doctype": "Comment",
                    "comment_type": "Info",
                    "reference_doctype": "Member",
                    "reference_name": member_name,
                    "content": f"Member approved via chapter dashboard by {approver_full_name}",
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
                frappe.log_error(
                    title="Chapter Dashboard approval audit comment failed",
                    message=f"Join request approval of {member_name}: {'; '.join(comment_result.errors)}",
                )
                # Don't block the approval if audit trail fails

            return {"success": True, "message": _("Member approved successfully"), "member_name": member_name}
        else:
            return {"success": False, "error": result.get("message", "Unknown error occurred")}

    # #505: this catch-all sits below @handle_api_error; without this a 1205/1213
    # here is logged and returned as a plain failure dict one frame below the
    # decorator's own guard (#504). Re-raise unconditionally.
    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.log_error(
            title="Chapter Dashboard API", message=f"Error in quick_approve_join_request: {str(e)}"
        )
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


# Number Card API methods for Frappe Dashboard
def _dashboard_chapter_scope(chapter):
    """Chapter names a number card may count, or [] when there are none.

    An explicit ``chapter`` must be one the caller may see on the dashboard
    (``get_user_board_chapters``); an unknown name and a chapter the caller has no
    access to are refused with the same error, so the card is not an existence oracle
    (#1666). Without ``chapter`` the scope is every chapter the caller can see.
    """
    from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

    visible = [ch["chapter_name"] for ch in get_user_board_chapters()]
    if chapter:
        if chapter not in visible:
            raise PermissionError("You don't have access to this chapter")
        return [chapter]
    return visible


def _expense_claim_card(filters, chapter):
    """Count Expense Claims the caller may list, for a number card.

    Goes through ``frappe.get_list`` so ``get_expense_claim_permission_query`` applies: a
    count channel must not disclose claims the list view hides (maintainer ruling on
    #1606: Staff must not see every claim). With no ``chapter`` the count IS the caller's
    list (including claims without a chapter), gated on having any dashboard chapter; with
    one, it is narrowed to that chapter after the access gate.
    """
    scope = _dashboard_chapter_scope(chapter)
    if not scope or not frappe.has_permission("Expense Claim", "read"):
        return {"value": 0, "fieldtype": "Data"}

    # A site restored from an old snapshot may lack the field until `bench migrate`, and the
    # permission query itself filters on it for approvers: fail closed on both branches.
    if not frappe.get_meta("Expense Claim").has_field("custom_chapter"):
        return {"value": 0, "fieldtype": "Data"}

    if chapter:
        filters = {**filters, "custom_chapter": chapter}

    rows = frappe.get_list("Expense Claim", filters=filters, fields=[{"COUNT": "name", "as": "total"}])
    return {"value": rows[0].total if rows else 0, "fieldtype": "Data"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)  # Member count statistics - read-only
def get_active_members_count(chapter: str | None = None):
    """Get count of active members for dashboard number card"""

    if chapter:
        _dashboard_chapter_scope(chapter)  # refuse a chapter the caller cannot see (#1666)

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
    """Count of Pending Review applications for the dashboard number card (#1765).

    The same rows the application list shows: the MAS permission query scopes them, and the chapter
    scope (an explicit chapter the caller cannot see is refused, #1666) narrows them further.
    """
    from verenigingen.services.member.application.pending_applications import (
        count_pending_review_applications,
    )

    scope = _dashboard_chapter_scope(chapter)
    return {"value": count_pending_review_applications(chapters=scope), "fieldtype": "Data"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)  # Board member count statistics - read-only
def get_board_members_count(chapter: str | None = None):
    """Get count of active board members for dashboard number card"""

    if chapter:
        _dashboard_chapter_scope(chapter)  # refuse a chapter the caller cannot see (#1666)

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

    if chapter:
        _dashboard_chapter_scope(chapter)  # refuse a chapter the caller cannot see (#1666)

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
def get_filed_expense_claims_count(chapter: str | None = None):
    """Get count of filed expense claims for dashboard number card"""

    return _expense_claim_card({"approval_status": ["!=", "Draft"]}, chapter)


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_approved_expense_claims_count(chapter: str | None = None):
    """Get count of approved expense claims for dashboard number card"""

    return _expense_claim_card({"approval_status": "Approved"}, chapter)


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_volunteer_expenses_count(chapter: str | None = None):
    """Get count of volunteer expenses for dashboard number card.

    Volunteer Expense was archived; on migrated sites the DocType is gone
    (see patches/v2_2/drop_volunteer_expense_archived_doctype.py). Returns
    0 in that case rather than raising "Unknown table" SQL errors from
    the chapter dashboard card.
    """
    if not frappe.db.exists("DocType", "Volunteer Expense"):
        return {"value": 0, "fieldtype": "Data"}

    if chapter:
        _dashboard_chapter_scope(chapter)  # refuse a chapter the caller cannot see (#1666)

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
