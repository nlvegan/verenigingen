# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, getdate, today

from verenigingen.services.communication.email_service import get_email_service
from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS

# Fields approve_request writes; restored on the in-memory doc when the save is rolled back.
REVIEW_FIELDS = ("status", "reviewed_by", "review_date", "review_notes")
# The review audit trail; written only by approve_request / reject_request (#1745).
AUDIT_FIELDS = ("reviewed_by", "review_date", "review_notes", "rejection_reason")


class ChapterJoinRequest(Document):
    def validate(self):
        """Validate chapter join request"""
        # Auto-default status. status is reqd=1 with JSON default "Pending",
        # but Frappe v16 only applies field defaults at the form layer, not for
        # frappe.get_doc({...}).insert(). The mandatory check runs after validate()
        # but before on_submit(), so the default must be set here to avoid
        # MandatoryError on raw-dict inserts. "Pending" is the correct initial
        # state: a new join request awaits board review.
        if not self.status:
            self.status = "Pending"

        # Materialize the "Today" default for request_date here for the same
        # reason as status above: Frappe v16 applies field defaults only at the
        # form layer, not for frappe.get_doc({...}).insert(). request_date is NOT
        # allow_on_submit, so if it stays empty until a post-submit save the
        # default is applied then (None -> today) and raises UpdateAfterSubmitError.
        if not self.request_date:
            self.request_date = today()

        self.validate_field_references()
        self.validate_member_ownership()
        self.validate_member_exists()
        self.validate_chapter_exists()
        self.validate_no_duplicate_request()
        self.validate_not_already_member()
        self.validate_status_change()

    def validate_status_change(self):
        """Only approve_request / reject_request may move status or write the review trail
        (#1704, #1745).

        status and the review fields (who reviewed, when, why) are allow_on_submit and writable
        by every role with write access (Member, Staff, Chapter Board Member, Administrator), so
        a form save or REST PUT could otherwise set Approved with no Chapter Member row, or
        rewrite who approved a request afterwards, and a REST insert could create a request that
        is born Approved or born reviewed. The two review methods set flags.review_in_progress; a
        client cannot.
        """
        if self.get_doc_before_save() is None:
            if self.amended_from:
                # An amendment copies the cancelled request; it needs a fresh review.
                self.status = "Pending"
                for field in AUDIT_FIELDS:
                    self.set(field, None)
            elif self.status != "Pending":
                frappe.throw(_("A new join request must start as Pending"))
            elif any(self.get(field) for field in AUDIT_FIELDS):
                frappe.throw(_("A new join request cannot carry a review"))
        elif not self.flags.review_in_progress:
            if self.has_value_changed("status"):
                frappe.throw(_("The status can only be changed by approving or rejecting the request"))
            if self._audit_field_changed():
                frappe.throw(_("The review details can only be set by approving or rejecting the request"))

    def _audit_field_changed(self):
        """True when a review field differs from the saved row. NULL and "" count as equal: a form
        round-trip sends "" for a field the database holds as NULL (e.g. review_notes on a rejected
        request), and refusing that would block a save that changes nothing."""
        before = self.get_doc_before_save()
        return any(cstr(self.get(f)) != cstr(before.get(f)) for f in AUDIT_FIELDS)

    def before_update_after_submit(self):
        """Frappe runs this, not validate(), when a SUBMITTED request is saved again."""
        self.validate_status_change()

    def validate_field_references(self):
        """Validate that referenced fields exist in target DocTypes"""
        # Validate Chapter DocType has expected fields
        chapter_meta = frappe.get_meta("Chapter")
        if not chapter_meta.get_field("members"):
            frappe.throw(_("Chapter DocType missing required 'members' field"))

        # Validate Chapter Member child table has expected fields
        chapter_member_meta = frappe.get_meta("Chapter Member")
        required_fields = ["member", "enabled", "status", "chapter_join_date"]
        for field_name in required_fields:
            if not chapter_member_meta.get_field(field_name):
                frappe.throw(_("Chapter Member DocType missing required field: {0}").format(field_name))

    def validate_member_ownership(self):
        """A request may only name the caller's own Member, unless staff act for the member (#1786).

        The whitelisted join_chapter pins `member` to the caller, but the doctype grants create and
        submit to every Verenigingen Member, so a REST/form insert could name anyone. Checked on
        insert and whenever `member` changes, before validate_member_exists so a refused caller
        learns nothing about the named member (existence, status). Identity is Member.user only
        (#1546, no email fallback); the staff exemption is Roles.ADMIN_ROLES (#1101), so board
        members and treasurers are not exempt. flags.member_verified_by_caller is set by server
        code that has already resolved the caller's own Member by its own rule (join_chapter);
        a client cannot set a flag.
        """
        if self.flags.member_verified_by_caller:
            return
        if not self.is_new() and not self.has_value_changed("member"):
            return
        user = frappe.session.user
        if user == "Administrator" or Roles.ADMIN_ROLES.intersection(frappe.get_roles(user)):
            return
        from verenigingen.utils.member_utils import get_member_name_for_board_access

        own_member = get_member_name_for_board_access(user)
        if not self.member or self.member != own_member:
            frappe.throw(
                _("You can only create a join request for your own membership"), frappe.PermissionError
            )

    def validate_member_exists(self):
        """Ensure member exists and is active"""
        if not self.member:
            frappe.throw(_("Member is required"))

        member = frappe.get_doc("Member", self.member)
        if member.status != "Active":
            frappe.throw(_("Only active members can request to join chapters"))

    def validate_chapter_exists(self):
        """Ensure chapter exists and is active"""
        if not self.chapter:
            frappe.throw(_("Chapter is required"))

        chapter = frappe.get_doc("Chapter", self.chapter)
        if chapter.status != "Active":
            frappe.throw(_("Chapter is not accepting new members"))

    def validate_no_duplicate_request(self):
        """Validate that there are no existing pending requests for this member and chapter"""
        if self.is_new():
            existing_request = frappe.db.exists(
                "Chapter Join Request",
                {"member": self.member, "chapter": self.chapter, "status": "Pending", "docstatus": 1},
            )

            if existing_request:
                frappe.throw(_("You already have a pending request to join this chapter"))

    def validate_not_already_member(self):
        """Validate that member is not already a member of this chapter"""
        if self.is_new():
            existing_membership = frappe.db.exists(
                "Chapter Member",
                {"parent": self.chapter, "member": self.member, "status": ["in", ["Active", "Pending"]]},
            )

            if existing_membership:
                frappe.throw(_("You are already a member or have a pending membership in this chapter"))

    def on_submit(self):
        """Handle submission of join request"""
        # Ensure status is set (already defaults to "Pending" but confirm)
        if not self.status:
            self.status = "Pending"

        # Ensure request date is set (already defaults to "Today" but confirm)
        if not self.request_date:
            self.request_date = today()

        # Send notification to chapter board members
        self.notify_chapter_board()

    def approve_request(self, approved_by=None, notes=None):
        """Approve the chapter join request and create chapter membership with proper transaction handling"""
        if self.status != "Pending":
            frappe.throw(_("Only pending requests can be approved"))

        # The Approved save and the membership assignment are one unit (#1632): the whitelisted
        # wrappers swallow a failure and return a dict, so the request would otherwise commit as
        # Approved with no membership and no retry path. A savepoint (not a full rollback) undoes
        # only this request, so bulk approval keeps the requests that already succeeded.
        savepoint = "cjr_approve_" + frappe.generate_hash(length=8)
        before = {field: self.get(field) for field in REVIEW_FIELDS}
        frappe.db.savepoint(savepoint)
        try:
            # Update request status first
            self.flags.review_in_progress = True
            self.status = "Approved"
            self.reviewed_by = approved_by or frappe.session.user
            self.review_date = today()
            self.review_notes = notes
            self.save()

            # Use existing ChapterMembershipManager for proper workflow handling
            from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager

            # Create membership using existing manager (this ensures proper validation and history)
            result = ChapterMembershipManager.assign_member_to_chapter(
                member_id=self.member,
                chapter_name=self.chapter,
                reason=f"Approved join request {self.name}",
                assigned_by=self.reviewed_by,
            )

            if not result.get("success"):
                frappe.throw(
                    _("Failed to create chapter membership: {0}").format(self._failure_reason(result))
                )

            # Add membership history
            self.add_membership_history()

            # Send notifications (non-critical - don't fail if these don't work)
            notification_success = False
            try:
                self.notify_member_approved()
                notification_success = True
            except Exception as e:
                frappe.log_error(f"Approval notification failed but approval succeeded: {str(e)}")
                # Add user-visible message about notification failure
                frappe.msgprint(
                    _(
                        "Chapter join request approved successfully, but email notification failed. Please inform the member manually."
                    )
                )

            frappe.db.release_savepoint(savepoint)

            # Return success with notification status
            return {
                "success": True,
                "notification_sent": notification_success,
                "message": _("Request approved successfully"),
            }

        except Exception as e:
            self._undo_failed_approval(savepoint, e, before)
            frappe.throw(_("Failed to approve request: {0}").format(str(e)))
        finally:
            self.flags.review_in_progress = False

    def _undo_failed_approval(self, savepoint, error, before):
        """Roll the Approved save back to *savepoint* and restore the in-memory doc.

        Every failure is rolled back, including a 1205 lock timeout: it leaves the transaction
        and savepoint live, so skipping the rollback would let a swallowing wrapper commit the
        Approved row (#1632). rollback_to_savepoint returns False when the savepoint is already
        gone. That is the signal that the transaction was destroyed (a 1213 deadlock), and it is
        independent of the exception's type: assign_member_to_chapter swallows a deadlock from
        the roster write into a {"success": False} dict, so the error arriving here is an
        ordinary ValidationError (#1703). The server has rolled the Approved save back too, so
        the in-memory doc is put back from *before*, and a QueryDeadlockError is raised so
        bulk approval can stop. (A nested commit also removes the savepoint; the work is then
        committed rather than rolled back, which is why the caller must not retry blindly.)
        """
        from verenigingen.utils.transaction_errors import rollback_to_savepoint

        if rollback_to_savepoint(savepoint):
            self.reload()
        else:
            self.update(before)
            if not isinstance(error, frappe.QueryDeadlockError):
                raise frappe.QueryDeadlockError(str(error)) from error
        if isinstance(error, NON_RESUMABLE_DB_ERRORS):
            raise error

    def _failure_reason(self, result):
        """The reason ChapterMembershipManager.assign_member_to_chapter failed.

        The manager's own early exits key the reason "error" but whatever it passes
        through from MemberManager.add_member keys it "message", so read both (#1591).
        add_member's "not_reenabled" message names the member's current status; an
        approver who cannot read that Member must not learn it from here (#1590),
        so they get the same refusal without the status.
        """
        if result.get("action") == "not_reenabled" and not frappe.has_permission(
            "Member", "read", doc=self.member
        ):
            return _("the member could not be re-enabled in this chapter")
        return result.get("error") or result.get("message") or _("Unknown error")

    def reject_request(self, rejected_by=None, reason=None):
        """Reject the chapter join request with proper error handling"""
        if self.status != "Pending":
            frappe.throw(_("Only pending requests can be rejected"))

        try:
            # Update request status
            self.flags.review_in_progress = True
            self.status = "Rejected"
            self.reviewed_by = rejected_by or frappe.session.user
            self.review_date = today()
            self.rejection_reason = reason

            # Save the updated request
            self.save()

            # Send rejection notification to member (non-critical)
            notification_success = False
            try:
                self.notify_member_rejected()
                notification_success = True
            except Exception as e:
                frappe.log_error(f"Rejection notification failed but rejection succeeded: {str(e)}")
                frappe.msgprint(
                    _(
                        "Chapter join request rejected successfully, but email notification failed. Please inform the member manually."
                    )
                )

            return {
                "success": True,
                "notification_sent": notification_success,
                "message": _("Request rejected successfully"),
            }

        except Exception as e:
            frappe.log_error(f"Failed to reject join request: {str(e)}")
            frappe.throw(_("Failed to reject request: {0}").format(str(e)))
        finally:
            self.flags.review_in_progress = False

    def notify_chapter_board(self):
        """Send notification to chapter board members about new join request"""
        try:
            # Get chapter board members
            board_members = frappe.get_all(
                "Chapter Board Member", filters={"parent": self.chapter, "is_active": 1}, fields=["volunteer"]
            )

            recipients = []
            for board_member in board_members:
                # Get the member from the volunteer record
                volunteer_member = frappe.db.get_value("Volunteer", board_member.volunteer, "member")
                if volunteer_member:
                    member_email = frappe.db.get_value("Member", volunteer_member, "email")
                    if member_email:
                        recipients.append(member_email)

            # Also notify chapter managers
            managers = frappe.get_all(
                "User", filters={"role_profile_name": ["like", "%Chapter%"], "enabled": 1}, fields=["email"]
            )
            for manager in managers:
                if manager.email not in recipients:
                    recipients.append(manager.email)

            if recipients:
                email_service = get_email_service()
                email_service.send_simple_email(
                    recipients=recipients,
                    subject=_("New Chapter Join Request - {0}").format(self.chapter),
                    message=_(
                        "A new member has requested to join your chapter.<br><br>"
                        "Member: {0}<br>"
                        "Chapter: {1}<br>"
                        "Request Date: {2}<br><br>"
                        "Please review and approve/reject this request."
                    ).format(self.member_name, self.chapter, self.request_date),
                    header=[_("Chapter Join Request"), "blue"],
                    notification_key="chapter_join_request_submitted",
                    reference_doctype="Chapter Join Request",
                    reference_name=self.name,
                )
        except Exception as e:
            frappe.log_error(f"Failed to send chapter board notification: {str(e)}")

    def notify_member_approved(self):
        """Send approval notification to member"""
        try:
            email_service = get_email_service()
            email_service.send_simple_email(
                recipients=[self.member_email],
                subject=_("Chapter Join Request Approved - {0}").format(self.chapter),
                message=_(
                    "Congratulations! Your request to join {0} has been approved.<br><br>"
                    "Welcome to the chapter!"
                ).format(self.chapter),
                header=[_("Request Approved"), "green"],
                notification_key="chapter_join_request_approved",
                reference_doctype="Chapter Join Request",
                reference_name=self.name,
            )
        except Exception as e:
            frappe.log_error(f"Failed to send member approval notification: {str(e)}")

    def notify_member_rejected(self):
        """Send rejection notification to member"""
        try:
            message = _("Your request to join {0} has been rejected.").format(self.chapter)
            if self.rejection_reason:
                message += _("<br><br>Reason: {0}").format(self.rejection_reason)

            email_service = get_email_service()
            email_service.send_simple_email(
                recipients=[self.member_email],
                subject=_("Chapter Join Request Rejected - {0}").format(self.chapter),
                message=message,
                header=[_("Request Rejected"), "red"],
                notification_key="chapter_join_request_rejected",
                reference_doctype="Chapter Join Request",
                reference_name=self.name,
            )
        except Exception as e:
            frappe.log_error(f"Failed to send member rejection notification: {str(e)}")

    def add_membership_history(self):
        """Add entry to chapter membership history"""
        try:
            from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

            ChapterMembershipHistoryManager.add_membership_history(
                member_id=self.member,
                chapter_name=self.chapter,
                assignment_type="Member",
                start_date=frappe.utils.today(),
                reason=f"Joined via approved join request {self.name}",
                status="Active",
            )
        except Exception as e:
            frappe.log_error(f"Failed to add membership history: {str(e)}")


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def has_chapter_approval_permission(chapter_name: str = None, user: str = None):
    """Check if user has permission to approve/reject requests for a specific chapter"""
    if not chapter_name:
        # Return False if no chapter specified, rather than throwing an error
        # This prevents JavaScript errors when the function is called during form load
        return False

    if not user:
        user = frappe.session.user

    # Administrators and Managers can approve for any chapter
    user_roles = frappe.get_roles(user)
    if Roles.VERENIGINGEN_ADMIN in user_roles or Roles.VERENIGINGEN_STAFF in user_roles:
        return True

    # Check if user is a board member of this specific chapter.
    #
    # This previously filtered Chapter Board Member on a `member` field, which that
    # doctype does not have - its columns are volunteer, volunteer_name, email,
    # chapter_role, from_date, to_date, is_active, notes - so the query could never
    # answer the question it was asked. Board membership hangs off the VOLUNTEER,
    # so resolve user -> member -> volunteer -> board row, the way the rest of the
    # app does.
    #
    # #1546 maintainer ruling: the member is resolved strictly (Member.user link
    # ONLY, no Member.email fallback) -- this whitelisted endpoint gates approving/
    # rejecting Chapter Join Requests, a board-access decision like any other, and
    # matches permissions.assign_chapter_board_role() (the lookup that decides who
    # IS a board member) and get_user_board_chapters()/get_user_board_role(), both
    # of which are strict for the same reason.
    from verenigingen.utils.member_utils import get_member_name_for_board_access

    member = get_member_name_for_board_access(user)
    volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name") if member else None
    if not volunteer:
        return False

    board_member = frappe.db.exists(
        "Chapter Board Member",
        {"parent": chapter_name, "volunteer": volunteer, "is_active": 1},
    )

    return bool(board_member)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def approve_join_request(request_name: str, notes=None):
    """API method to approve a chapter join request with proper permission validation"""
    try:
        doc = frappe.get_doc("Chapter Join Request", request_name)

        # Validate user has permission to approve for this chapter
        if not has_chapter_approval_permission(doc.chapter):
            frappe.throw(
                _("Insufficient permissions to approve requests for chapter {0}").format(doc.chapter)
            )

        doc.approve_request(notes=notes)
        return {"success": True, "message": _("Chapter join request approved successfully")}

    except Exception as e:
        frappe.log_error(f"Failed to approve join request {request_name}: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def reject_join_request(request_name: str, reason=None):
    """API method to reject a chapter join request with proper permission validation"""
    try:
        doc = frappe.get_doc("Chapter Join Request", request_name)

        # Validate user has permission to reject for this chapter
        if not has_chapter_approval_permission(doc.chapter):
            frappe.throw(_("Insufficient permissions to reject requests for chapter {0}").format(doc.chapter))

        doc.reject_request(reason=reason)
        return {"success": True, "message": _("Chapter join request rejected")}

    except Exception as e:
        frappe.log_error(f"Failed to reject join request {request_name}: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_member_chapter_join_requests(member_name: str):
    """Get all chapter join requests for a specific member"""
    try:
        requests = frappe.get_all(
            "Chapter Join Request",
            filters={"member": member_name, "docstatus": 1},
            fields=[
                "name",
                "chapter",
                "status",
                "request_date",
                "review_date",
                "introduction",
                "reviewed_by",
                "review_notes",
                "rejection_reason",
            ],
            order_by="request_date desc",
        )

        return requests

    except Exception as e:
        frappe.log_error(f"Failed to get member chapter join requests for {member_name}: {str(e)}")
        return []


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_chapter_join_requests(chapter_name: str):
    """Get all chapter join requests for a specific chapter"""
    try:
        # Get requests first, then check permissions for approve/deny buttons
        # This allows all users to see requests but only authorized users to act on them

        requests = frappe.get_all(
            "Chapter Join Request",
            filters={"chapter": chapter_name, "docstatus": 1},
            fields=[
                "name",
                "member",
                "member_name",
                "member_email",
                "status",
                "request_date",
                "review_date",
                "introduction",
                "reviewed_by",
                "review_notes",
                "rejection_reason",
            ],
            order_by="request_date desc",
        )

        # Add permission flag to each request for button display
        can_approve = has_chapter_approval_permission(chapter_name)
        for request in requests:
            request["can_approve"] = can_approve

        return requests

    except Exception as e:
        frappe.log_error(f"Failed to get chapter join requests for {chapter_name}: {str(e)}")
        return []


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def bulk_approve_requests(request_names):
    """Bulk approve multiple chapter join requests"""
    try:
        approved_names = []
        failed_requests = []
        interrupted_by = None
        remaining = []

        for position, request_name in enumerate(request_names):
            try:
                doc = frappe.get_doc("Chapter Join Request", request_name)

                # Validate user has permission to approve for this chapter
                if not has_chapter_approval_permission(doc.chapter):
                    failed_requests.append(f"{request_name}: Insufficient permissions")
                    continue

                doc.approve_request()
                approved_names.append(request_name)

            except NON_RESUMABLE_DB_ERRORS as e:
                # A deadlock/lock timeout means the database is contended or the transaction is
                # gone; carrying on would only add more work to the same fate (#1703).
                interrupted_by = e
                remaining = list(request_names)[position + 1 :]
                failed_requests.append(f"{request_name}: {str(e)}")
                break
            except Exception as e:
                failed_requests.append(f"{request_name}: {str(e)}")

        applied_names = approved_names
        rolled_back_names = []
        if isinstance(interrupted_by, frappe.QueryDeadlockError):
            # A 1213 rolls the WHOLE transaction back server-side, so the approvals made earlier
            # in this loop did not survive either. Report them as not applied instead of as
            # successes; no commit is added here, the request-level commit has nothing to keep.
            applied_names, rolled_back_names = [], approved_names

        message = _("Successfully approved {0} request(s)").format(len(applied_names))
        if failed_requests:
            message += _("<br>Failed requests:<br>") + "<br>".join(failed_requests)
        if interrupted_by is not None:
            message += _("<br>Bulk approval stopped after a database error ({0}).").format(
                type(interrupted_by).__name__
            )
            if rolled_back_names:
                message += _("<br>Approvals rolled back, please retry: {0}").format(
                    ", ".join(rolled_back_names)
                )
            if remaining:
                message += _("<br>Requests not processed: {0}").format(", ".join(remaining))

        return message

    except Exception as e:
        frappe.log_error(f"Failed to bulk approve requests: {str(e)}")
        return _("Bulk approval failed: {0}").format(str(e))
