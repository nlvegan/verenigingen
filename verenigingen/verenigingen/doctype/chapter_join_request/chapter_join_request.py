# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today


class ChapterJoinRequest(Document):
    def validate(self):
        """Validate chapter join request"""
        self.validate_field_references()
        self.validate_member_exists()
        self.validate_chapter_exists()
        self.validate_no_duplicate_request()
        self.validate_not_already_member()

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

        try:
            # Update request status first
            self.status = "Approved"
            self.reviewed_by = approved_by or frappe.session.user
            self.review_date = today()
            self.review_notes = notes
            self.save()

            # Use existing ChapterMembershipManager for proper workflow handling
            from verenigingen.utils.chapter_membership_manager import ChapterMembershipManager

            # Create membership using existing manager (this ensures proper validation and history)
            result = ChapterMembershipManager.assign_member_to_chapter(
                member_id=self.member,
                chapter_name=self.chapter,
                reason=f"Approved join request {self.name}",
                assigned_by=self.reviewed_by,
            )

            if not result.get("success"):
                frappe.throw(
                    _("Failed to create chapter membership: {0}").format(result.get("error", "Unknown error"))
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

            # Return success with notification status
            return {
                "success": True,
                "notification_sent": notification_success,
                "message": _("Request approved successfully"),
            }

        except Exception as e:
            frappe.throw(_("Failed to approve request: {0}").format(str(e)))

    def reject_request(self, rejected_by=None, reason=None):
        """Reject the chapter join request with proper error handling"""
        if self.status != "Pending":
            frappe.throw(_("Only pending requests can be rejected"))

        try:
            # Update request status
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

    def notify_chapter_board(self):
        """Send notification to chapter board members about new join request"""
        try:
            # Get chapter board members
            board_members = frappe.get_all(
                "Chapter Board Member", filters={"parent": self.chapter, "enabled": 1}, fields=["member"]
            )

            recipients = []
            for board_member in board_members:
                member_email = frappe.db.get_value("Member", board_member.member, "email")
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
                frappe.sendmail(
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
                )
        except Exception as e:
            frappe.log_error(f"Failed to send chapter board notification: {str(e)}")

    def notify_member_approved(self):
        """Send approval notification to member"""
        try:
            frappe.sendmail(
                recipients=[self.member_email],
                subject=_("Chapter Join Request Approved - {0}").format(self.chapter),
                message=_(
                    "Congratulations! Your request to join {0} has been approved.<br><br>"
                    "Welcome to the chapter!"
                ).format(self.chapter),
                header=[_("Request Approved"), "green"],
            )
        except Exception as e:
            frappe.log_error(f"Failed to send member approval notification: {str(e)}")

    def notify_member_rejected(self):
        """Send rejection notification to member"""
        try:
            message = _("Your request to join {0} has been rejected.").format(self.chapter)
            if self.rejection_reason:
                message += _("<br><br>Reason: {0}").format(self.rejection_reason)

            frappe.sendmail(
                recipients=[self.member_email],
                subject=_("Chapter Join Request Rejected - {0}").format(self.chapter),
                message=message,
                header=[_("Request Rejected"), "red"],
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
                action="joined",
                details=f"Joined via approved join request {self.name}",
                user_email=self.reviewed_by,
            )
        except Exception as e:
            frappe.log_error(f"Failed to add membership history: {str(e)}")


@frappe.whitelist()
def has_chapter_approval_permission(chapter_name, user=None):
    """Check if user has permission to approve/reject requests for a specific chapter"""
    if not user:
        user = frappe.session.user

    # Administrators and Managers can approve for any chapter
    user_roles = frappe.get_roles(user)
    if "Verenigingen Administrator" in user_roles or "Verenigingen Manager" in user_roles:
        return True

    # Check if user is a board member of this specific chapter
    board_member = frappe.db.exists(
        "Chapter Board Member",
        {"parent": chapter_name, "member": frappe.db.get_value("Member", {"email": user}), "enabled": 1},
    )

    return bool(board_member)


@frappe.whitelist()
def approve_join_request(request_name, notes=None):
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
def reject_join_request(request_name, reason=None):
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
def get_member_chapter_join_requests(member_name):
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
def get_chapter_join_requests(chapter_name):
    """Get all chapter join requests for a specific chapter"""
    try:
        # Check if user has permission to view requests for this chapter
        if not has_chapter_approval_permission(chapter_name):
            return []

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

        return requests

    except Exception as e:
        frappe.log_error(f"Failed to get chapter join requests for {chapter_name}: {str(e)}")
        return []


@frappe.whitelist()
def bulk_approve_requests(request_names):
    """Bulk approve multiple chapter join requests"""
    try:
        approved_count = 0
        failed_requests = []

        for request_name in request_names:
            try:
                doc = frappe.get_doc("Chapter Join Request", request_name)

                # Validate user has permission to approve for this chapter
                if not has_chapter_approval_permission(doc.chapter):
                    failed_requests.append(f"{request_name}: Insufficient permissions")
                    continue

                doc.approve_request()
                approved_count += 1

            except Exception as e:
                failed_requests.append(f"{request_name}: {str(e)}")

        message = _("Successfully approved {0} request(s)").format(approved_count)
        if failed_requests:
            message += _("<br>Failed requests:<br>") + "<br>".join(failed_requests)

        return message

    except Exception as e:
        frappe.log_error(f"Failed to bulk approve requests: {str(e)}")
        return _("Bulk approval failed: {0}").format(str(e))
