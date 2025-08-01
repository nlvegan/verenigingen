# verenigingen/verenigingen/doctype/chapter/managers/member_manager.py

import json
from typing import Dict, List

import frappe
from frappe import _
from frappe.utils import now, today

from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

from .base_manager import BaseManager


class MemberManager(BaseManager):
    """Manager for chapter member operations"""

    def __init__(self, chapter_doc):
        super().__init__(chapter_doc)
        self.member_cache = {}

    def add_member(
        self,
        member_id: str,
        introduction: str = None,
        website_url: str = None,
        enabled: bool = True,
        notify: bool = True,
    ) -> Dict:
        """
        Add a member to this chapter

        Args:
            member_id: Member ID
            introduction: Member introduction text
            website_url: Member website URL
            enabled: Whether member is enabled
            notify: Whether to send notification

        Returns:
            Dict with operation result
        """
        self.validate_chapter_doc()

        if not member_id:
            frappe.throw(_("Member ID is required"))

        try:
            # Check if member exists
            if not frappe.db.exists("Member", member_id):
                frappe.throw(_("Member {0} does not exist").format(member_id))

            # Check if member already exists in chapter
            existing_member = self._find_chapter_member(member_id)
            if existing_member:
                if not existing_member.enabled and enabled:
                    # Re-enable disabled member
                    existing_member.enabled = 1
                    existing_member.leave_reason = None

                    self.chapter_doc.save()

                    self.create_comment(
                        "Info", _("Re-enabled member {0}").format(self._get_member_name(member_id))
                    )

                    return {
                        "success": True,
                        "message": _("Member re-enabled successfully"),
                        "action": "re-enabled",
                    }
                else:
                    return {
                        "success": False,
                        "message": _("Member is already in this chapter"),
                        "action": "already_exists",
                    }

            # Get member details
            member_doc = frappe.get_doc("Member", member_id)

            # Validate member data
            self._validate_member_data(member_doc, introduction, website_url)

            # Add to members table
            new_member = self.chapter_doc.append(
                "members",
                {
                    "member": member_id,
                    "enabled": enabled,
                    "status": "Active",  # Explicitly set to Active for direct adds
                },
            )

            # Note: Primary chapter concept is handled through Chapter Member ordering
            # The first (most recent) chapter membership is considered primary

            # Save chapter with concurrency handling
            try:
                self.chapter_doc.save()
            except frappe.TimestampMismatchError:
                # Reload chapter and retry save once
                self.chapter_doc.reload()
                # Re-add the member to the reloaded document if not exists
                if not any(m.member == member_id for m in self.chapter_doc.members):
                    self.chapter_doc.append(
                        "members",
                        {
                            "member": member_id,
                            "chapter_join_date": today(),
                            "enabled": enabled,
                        },
                    )
                    self.chapter_doc.save()

            # Add membership history tracking
            ChapterMembershipHistoryManager.add_membership_history(
                member_id=member_id,
                chapter_name=self.chapter_name,
                assignment_type="Member",
                start_date=today(),
                reason=f"Added to {self.chapter_name} chapter",
            )

            # Create audit comment
            self.create_comment("Info", _("Added member {0} to chapter").format(member_doc.full_name))

            # Send notification
            if notify:
                self._notify_member_added(member_id)

            self.log_action(
                "Member added", {"member": member_id, "member_name": member_doc.full_name, "enabled": enabled}
            )

            return {
                "success": True,
                "message": _("Member added successfully"),
                "member": new_member,
                "action": "added",
            }

        except Exception as e:
            self.log_action("Failed to add member", {"member": member_id, "error": str(e)}, "error")
            raise

    def request_to_join(
        self,
        member_id: str,
        introduction: str = None,
        website_url: str = None,
        notify: bool = True,
    ) -> Dict:
        """
        Request to join this chapter (creates pending membership)

        Args:
            member_id: Member ID
            introduction: Member introduction text
            website_url: Member website URL
            notify: Whether to send notification

        Returns:
            Dict with operation result
        """
        self.validate_chapter_doc()

        if not member_id:
            frappe.throw(_("Member ID is required"))

        try:
            # Check if member exists
            if not frappe.db.exists("Member", member_id):
                frappe.throw(_("Member {0} does not exist").format(member_id))

            # Check if member already exists in chapter
            existing_member = self._find_chapter_member(member_id)
            if existing_member:
                if existing_member.status == "Pending":
                    return {
                        "success": False,
                        "message": _("Your membership request is already pending approval"),
                        "action": "already_pending",
                    }
                elif existing_member.status == "Active":
                    return {
                        "success": False,
                        "message": _("You are already a member of this chapter"),
                        "action": "already_member",
                    }
                elif existing_member.status == "Inactive" and existing_member.enabled:
                    # Reactivate request
                    existing_member.status = "Pending"
                    existing_member.chapter_join_date = None
                    self.chapter_doc.save()

                    self.create_comment(
                        "Info",
                        _("Member {0} requested to rejoin chapter").format(self._get_member_name(member_id)),
                    )

                    if notify:
                        self._notify_board_of_join_request(member_id)

                    return {
                        "success": True,
                        "message": _("Your request to rejoin has been submitted for approval"),
                        "action": "rejoin_requested",
                    }

            # Get member details
            member_doc = frappe.get_doc("Member", member_id)

            # Add to members table with Pending status
            self.chapter_doc.append(
                "members",
                {
                    "member": member_id,
                    "enabled": 1,
                    "status": "Pending",
                    "chapter_join_date": None,  # Will be set upon approval
                },
            )

            # Save chapter
            try:
                self.chapter_doc.save()
            except frappe.TimestampMismatchError:
                # Reload chapter and retry save once
                self.chapter_doc.reload()
                # Re-add the member to the reloaded document if not exists
                if not any(m.member == member_id for m in self.chapter_doc.members):
                    self.chapter_doc.append(
                        "members",
                        {
                            "member": member_id,
                            "enabled": 1,
                            "status": "Pending",
                        },
                    )
                    self.chapter_doc.save()

            # Add membership history tracking
            ChapterMembershipHistoryManager.add_membership_history(
                member_id=member_id,
                chapter_name=self.chapter_name,
                assignment_type="Member",
                start_date=today(),
                reason=f"Requested to join {self.chapter_name} chapter",
                new_status="Pending",
            )

            # Create audit comment
            self.create_comment(
                "Info", _("Member {0} requested to join chapter").format(member_doc.full_name)
            )

            # Send notification to board members
            if notify:
                self._notify_board_of_join_request(member_id)

            return {
                "success": True,
                "message": _("Your request to join has been submitted for approval"),
                "action": "requested",
            }

        except Exception as e:
            frappe.log_error(f"Error in request_to_join: {str(e)}")
            return {"success": False, "message": str(e)}

    def _notify_board_of_join_request(self, member_id: str):
        """Notify chapter board members of a new join request"""
        try:
            member_doc = frappe.get_doc("Member", member_id)

            # Get board members
            board_members = []
            for board_member in self.chapter_doc.board_members:
                if board_member.member:
                    member_email = frappe.db.get_value("Member", board_member.member, "email")
                    if member_email:
                        board_members.append(member_email)

            if board_members:
                frappe.sendmail(
                    recipients=board_members,
                    subject=_("New Chapter Join Request - {0}").format(self.chapter_name),
                    message=_(
                        """
                        <p>A new member has requested to join your chapter:</p>
                        <p><strong>Member:</strong> {0}</p>
                        <p><strong>Chapter:</strong> {1}</p>
                        <p>Please review and approve/reject this request in the chapter dashboard.</p>
                    """
                    ).format(member_doc.full_name, self.chapter_name),
                    delayed=False,
                )
        except Exception as e:
            frappe.log_error(f"Error sending join request notification: {str(e)}")

    def approve_member_request(self, member_id: str, approved_by: str = None) -> Dict:
        """
        Approve a pending member request

        Args:
            member_id: Member ID to approve
            approved_by: User who approved the request

        Returns:
            Dict with operation result
        """
        self.validate_chapter_doc()

        try:
            # Find pending member request
            existing_member = self._find_chapter_member(member_id)
            if not existing_member:
                return {"success": False, "message": _("No membership request found")}

            if existing_member.status != "Pending":
                return {"success": False, "message": _("Member request is not pending approval")}

            # Approve the member
            existing_member.status = "Active"
            existing_member.chapter_join_date = today()

            self.chapter_doc.save()

            # Update membership history
            ChapterMembershipHistoryManager.add_membership_history(
                member_id=member_id,
                chapter_name=self.chapter_name,
                assignment_type="Member",
                start_date=today(),
                reason=f"Membership approved by {approved_by or frappe.session.user}",
                new_status="Active",
            )

            # Create audit comment
            member_doc = frappe.get_doc("Member", member_id)
            self.create_comment(
                "Info",
                _("Approved membership request for {0} by {1}").format(
                    member_doc.full_name, approved_by or frappe.session.user
                ),
            )

            # Notify member of approval
            self._notify_member_approved(member_id)

            return {"success": True, "message": _("Member request approved successfully")}

        except Exception as e:
            frappe.log_error(f"Error approving member request: {str(e)}")
            return {"success": False, "message": str(e)}

    def reject_member_request(self, member_id: str, reason: str = None, rejected_by: str = None) -> Dict:
        """
        Reject a pending member request

        Args:
            member_id: Member ID to reject
            reason: Reason for rejection
            rejected_by: User who rejected the request

        Returns:
            Dict with operation result
        """
        self.validate_chapter_doc()

        try:
            # Find pending member request
            existing_member = self._find_chapter_member(member_id)
            if not existing_member:
                return {"success": False, "message": _("No membership request found")}

            if existing_member.status != "Pending":
                return {"success": False, "message": _("Member request is not pending approval")}

            # Remove the pending request
            for i, member in enumerate(self.chapter_doc.members):
                if member.member == member_id:
                    self.chapter_doc.members.pop(i)
                    break

            self.chapter_doc.save()

            # Update membership history
            ChapterMembershipHistoryManager.add_membership_history(
                member_id=member_id,
                chapter_name=self.chapter_name,
                assignment_type="Member",
                start_date=today(),
                end_date=today(),
                reason=f"Membership request rejected: {reason or 'No reason provided'}",
                new_status="Rejected",
            )

            # Create audit comment
            member_doc = frappe.get_doc("Member", member_id)
            self.create_comment(
                "Info",
                _("Rejected membership request for {0} by {1}. Reason: {2}").format(
                    member_doc.full_name, rejected_by or frappe.session.user, reason or "No reason provided"
                ),
            )

            # Notify member of rejection
            self._notify_member_rejected(member_id, reason)

            return {"success": True, "message": _("Member request rejected successfully")}

        except Exception as e:
            frappe.log_error(f"Error rejecting member request: {str(e)}")
            return {"success": False, "message": str(e)}

    def _notify_member_approved(self, member_id: str):
        """Notify member that their request was approved"""
        try:
            member_doc = frappe.get_doc("Member", member_id)
            if member_doc.email:
                frappe.sendmail(
                    recipients=[member_doc.email],
                    subject=_("Chapter Membership Approved - {0}").format(self.chapter_name),
                    message=_(
                        """
                        <p>Great news! Your request to join {0} has been approved.</p>
                        <p>You are now an active member of the chapter and can participate in all chapter activities.</p>
                        <p>Welcome to {0}!</p>
                    """
                    ).format(self.chapter_name),
                    delayed=False,
                )
        except Exception as e:
            frappe.log_error(f"Error sending approval notification: {str(e)}")

    def _notify_member_rejected(self, member_id: str, reason: str = None):
        """Notify member that their request was rejected"""
        try:
            member_doc = frappe.get_doc("Member", member_id)
            if member_doc.email:
                frappe.sendmail(
                    recipients=[member_doc.email],
                    subject=_("Chapter Membership Request - {0}").format(self.chapter_name),
                    message=_(
                        """
                        <p>Thank you for your interest in joining {0}.</p>
                        <p>Unfortunately, your membership request could not be approved at this time.</p>
                        {1}
                        <p>You are welcome to contact the chapter directly if you have any questions.</p>
                    """
                    ).format(
                        self.chapter_name, f"<p><strong>Reason:</strong> {reason}</p>" if reason else ""
                    ),
                    delayed=False,
                )
        except Exception as e:
            frappe.log_error(f"Error sending rejection notification: {str(e)}")

    def remove_member(
        self, member_id: str, leave_reason: str = None, permanent: bool = False, notify: bool = True
    ) -> Dict:
        """
        Remove or disable a member from this chapter

        Args:
            member_id: Member ID
            leave_reason: Reason for leaving
            permanent: Whether to remove completely or just disable
            notify: Whether to send notification

        Returns:
            Dict with operation result
        """
        self.validate_chapter_doc()

        if not member_id:
            frappe.throw(_("Member ID is required"))

        try:
            # Find the member in the table
            member_row = self._find_chapter_member(member_id)
            if not member_row:
                return {
                    "success": False,
                    "message": _("Member is not in this chapter"),
                    "action": "not_found",
                }

            member_name = self._get_member_name(member_id)

            if permanent:
                # Remove completely
                self.chapter_doc.members.remove(member_row)
                action = "removed"
                message = _("Member removed permanently")
            else:
                # Disable with reason
                member_row.enabled = 0
                member_row.leave_reason = leave_reason or _("Left on {0}").format(today())
                action = "disabled"
                message = _("Member disabled")

            # Note: Primary chapter is determined by Chapter Member ordering
            # No need to clear a specific primary_chapter field

            # Save chapter
            self.chapter_doc.save()

            # Update membership history tracking
            if permanent:
                # End the membership history for permanent removal
                ChapterMembershipHistoryManager.end_chapter_membership(
                    member_id=member_id,
                    chapter_name=self.chapter_name,
                    assignment_type="Member",
                    start_date=today(),  # We'll find the actual start date
                    end_date=today(),
                    reason=leave_reason or f"Permanently removed from {self.chapter_name}",
                )
            else:
                # Terminate the membership history for disabled member
                ChapterMembershipHistoryManager.terminate_chapter_membership(
                    member_id=member_id,
                    chapter_name=self.chapter_name,
                    assignment_type="Member",
                    end_date=today(),
                    reason=leave_reason or f"Disabled in {self.chapter_name}",
                )

            # Create audit comment
            self.create_comment(
                "Info",
                _("{0} member {1}").format(action.title(), member_name)
                + (f". Reason: {leave_reason}" if leave_reason else ""),
            )

            # Send notification
            if notify:
                self._notify_member_removed(member_id, leave_reason)

            self.log_action(
                f"Member {action}",
                {
                    "member": member_id,
                    "member_name": member_name,
                    "reason": leave_reason,
                    "permanent": permanent,
                },
            )

            return {"success": True, "message": message, "action": action}

        except Exception as e:
            self.log_action("Failed to remove member", {"member": member_id, "error": str(e)}, "error")
            raise

    def update_member_info(
        self, member_id: str, introduction: str = None, website_url: str = None, enabled: bool = None
    ) -> Dict:
        """
        Update member information in the chapter

        Args:
            member_id: Member ID
            introduction: New introduction
            website_url: New website URL
            enabled: New enabled status

        Returns:
            Dict with operation result
        """
        self.validate_chapter_doc()

        try:
            member_row = self._find_chapter_member(member_id)
            if not member_row:
                frappe.throw(_("Member is not in this chapter"))

            # Track changes
            changes = []

            if enabled is not None and member_row.enabled != enabled:
                member_row.enabled = enabled
                if not enabled and not member_row.leave_reason:
                    member_row.leave_reason = _("Disabled on {0}").format(today())
                elif enabled:
                    member_row.leave_reason = None
                changes.append("enabled status")

            if not changes:
                return {"success": True, "message": _("No changes to update"), "action": "no_changes"}

            # Save chapter
            self.chapter_doc.save()

            # Create audit comment
            self.create_comment(
                "Info",
                _("Updated member {0}: {1}").format(self._get_member_name(member_id), ", ".join(changes)),
            )

            self.log_action("Member info updated", {"member": member_id, "changes": changes})

            return {
                "success": True,
                "message": _("Member information updated"),
                "changes": changes,
                "action": "updated",
            }

        except Exception as e:
            self.log_action("Failed to update member info", {"member": member_id, "error": str(e)}, "error")
            raise

    def bulk_add_members(self, member_data_list: List[Dict]) -> Dict:
        """
        Bulk add members to chapter

        Args:
            member_data_list: List of member data dicts

        Returns:
            Dict with operation results
        """
        self.validate_chapter_doc()

        if isinstance(member_data_list, str):
            member_data_list = json.loads(member_data_list)

        if not member_data_list:
            return {"success": False, "error": "No members specified"}

        processed_count = 0
        errors = []
        added_members = []

        try:
            for member_data in member_data_list:
                try:
                    member_id = member_data.get("member_id")
                    introduction = member_data.get("introduction", "")
                    website_url = member_data.get("website_url", "")

                    if not member_id:
                        errors.append("Missing member ID")
                        continue

                    result = self.add_member(
                        member_id=member_id,
                        introduction=introduction,
                        website_url=website_url,
                        notify=False,  # Don't send individual notifications
                    )

                    if result["success"]:
                        processed_count += 1
                        added_members.append(member_id)
                    else:
                        errors.append(f"Failed to add {member_id}: {result.get('message', 'Unknown error')}")

                except Exception as e:
                    errors.append(
                        f"Error processing member {member_data.get('member_id', 'unknown')}: {str(e)}"
                    )

            # Create summary comment
            self.create_comment(
                "Info",
                _("Bulk member addition: {0} members added").format(processed_count)
                + (f", {len(errors)} errors" if errors else ""),
            )

            self.log_action(
                "Bulk member addition",
                {
                    "processed": processed_count,
                    "errors": len(errors),
                    "total_requested": len(member_data_list),
                },
            )

            return {
                "success": True,
                "processed": processed_count,
                "errors": errors,
                "added_members": added_members,
            }

        except Exception as e:
            self.log_action(
                "Critical error in bulk member addition",
                {"error": str(e), "processed": processed_count},
                "error",
            )
            return {"success": False, "error": str(e), "processed": processed_count}

    def get_members(self, include_disabled: bool = False, with_details: bool = False) -> List[Dict]:
        """
        Get list of chapter members

        Args:
            include_disabled: Whether to include disabled members
            with_details: Whether to include detailed member information

        Returns:
            List of member dictionaries
        """
        self.validate_chapter_doc()

        members = []

        for member in self.chapter_doc.members or []:
            if include_disabled or member.enabled:
                member_data = {
                    "member_id": member.member,
                    "member_name": self._get_member_name(member.member),
                    "introduction": "",  # Field doesn't exist in doctype
                    "website_url": "",  # Field doesn't exist in doctype
                    "enabled": member.enabled,
                    "leave_reason": member.leave_reason,
                }

                if with_details:
                    try:
                        member_doc = frappe.get_doc("Member", member.member)
                        member_data.update(
                            {
                                "email": member_doc.email,
                                "status": member_doc.status,
                                "member_since": member_doc.member_since,
                            }
                        )
                    except Exception:
                        # Handle case where member might have been deleted
                        pass

                members.append(member_data)

        return members

    def get_member_statistics(self) -> Dict:
        """
        Get statistics about chapter members

        Returns:
            Dict with member statistics
        """
        self.validate_chapter_doc()

        members = self.chapter_doc.members or []
        enabled_members = [m for m in members if m.enabled]
        disabled_members = [m for m in members if not m.enabled]

        # Count members with additional info
        with_introduction = 0  # Field doesn't exist in doctype
        with_website = 0  # Field doesn't exist in doctype

        # Get primary vs secondary members
        # Primary members are determined by Chapter Member ordering (first entry is primary)
        primary_members = 0
        try:
            for member in enabled_members:
                # Check if this is the member's primary chapter (first/most recent)
                member_chapters = frappe.get_all(
                    "Chapter Member",
                    filters={"member": member.member, "enabled": 1},
                    fields=["parent"],
                    order_by="chapter_join_date desc",
                    limit=1,
                )
                if member_chapters and member_chapters[0].parent == self.chapter_name:
                    primary_members += 1
        except Exception:
            pass

        return {
            "total_members": len(members),
            "enabled_members": len(enabled_members),
            "disabled_members": len(disabled_members),
            "primary_members": primary_members,
            "secondary_members": len(enabled_members) - primary_members,
            "with_introduction": with_introduction,
            "with_website": with_website,
            "completion_rate": {
                "introduction": (with_introduction / len(enabled_members) * 100) if enabled_members else 0,
                "website": (with_website / len(enabled_members) * 100) if enabled_members else 0,
            },
        }

    def search_members(self, query: str, include_disabled: bool = False) -> List[Dict]:
        """
        Search chapter members by name or introduction

        Args:
            query: Search query
            include_disabled: Whether to include disabled members

        Returns:
            List of matching members
        """
        self.validate_chapter_doc()

        if not query:
            return self.get_members(include_disabled)

        query_lower = query.lower()
        matching_members = []

        for member in self.chapter_doc.members or []:
            if not include_disabled and not member.enabled:
                continue

            # Search in name and introduction
            if query_lower in (self._get_member_name(member.member) or "").lower():
                matching_members.append(
                    {
                        "member_id": member.member,
                        "member_name": self._get_member_name(member.member),
                        "introduction": "",  # Field doesn't exist in doctype
                        "website_url": "",  # Field doesn't exist in doctype
                        "enabled": member.enabled,
                    }
                )

        return matching_members

    def export_members(self, format: str = "csv", include_disabled: bool = False) -> str:
        """
        Export chapter members data

        Args:
            format: Export format ('csv' or 'json')
            include_disabled: Whether to include disabled members

        Returns:
            Exported data as string
        """
        self.validate_chapter_doc()

        members = self.get_members(include_disabled, with_details=True)

        if format.lower() == "json":
            return json.dumps(members, indent=2, default=str)

        elif format.lower() == "csv":
            if not members:
                return "No members to export"

            # CSV headers
            headers = [
                "Member ID",
                "Name",
                "Email",
                "Status",
                "Introduction",
                "Website",
                "Enabled",
                "Leave Reason",
            ]

            lines = [",".join(f'"{h}"' for h in headers)]

            for member in members:
                row = [
                    member.get("member_id", ""),
                    self._get_member_name(member.get("member", "")),
                    member.get("email", ""),
                    member.get("status", ""),
                    member.get("introduction", ""),
                    member.get("website_url", ""),
                    str(member.get("enabled", True)),
                    member.get("leave_reason", ""),
                ]
                # Fix unterminated string literal by properly escaping quotes
                escaped_values = []
                for val in row:
                    str_val = str(val)
                    escaped_val = str_val.replace('"', '""')
                    escaped_values.append(f'"{escaped_val}"')
                lines.append(",".join(escaped_values))

            return "\n".join(lines)

        else:
            frappe.throw(_("Unsupported export format: {0}").format(format))

    # Private helper methods

    def _find_chapter_member(self, member_id: str):
        """Find chapter member by ID"""
        for member in self.chapter_doc.members or []:
            if member.member == member_id:
                return member
        return None

    def _get_member_name(self, member_id: str) -> str:
        """Get member name, with caching"""
        if member_id not in self.member_cache:
            try:
                member_doc = frappe.get_doc("Member", member_id)
                self.member_cache[member_id] = member_doc.full_name
            except Exception:
                self.member_cache[member_id] = member_id

        return self.member_cache[member_id]

    def _validate_member_data(self, member_doc, introduction: str = None, website_url: str = None):
        """Validate member data"""
        if member_doc.status != "Active":
            frappe.msgprint(
                _("Warning: Member {0} is not active (status: {1})").format(
                    member_doc.full_name, member_doc.status
                ),
                indicator="orange",
            )

        if introduction and len(introduction) > 500:
            frappe.throw(_("Introduction exceeds maximum length of 500 characters"))

        if website_url and not self._validate_url(website_url):
            frappe.throw(_("Invalid website URL format"))

    def _validate_url(self, url: str) -> bool:
        """Validate URL format"""
        import re

        url_pattern = re.compile(
            r"^https?://"  # http:// or https://
            r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"  # domain...
            r"localhost|"  # localhost...
            r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
            r"(?::\d+)?"  # optional port
            r"(?:/?|[/?]\S+)$",
            re.IGNORECASE,
        )

        return url_pattern.match(url) is not None

    def _notify_member_added(self, member_id: str):
        """Send notification when member is added"""
        try:
            member_doc = frappe.get_doc("Member", member_id)

            if not member_doc.email:
                return

            context = {"member": member_doc, "chapter": self.chapter_doc}

            self.send_notification(
                "member_added_to_chapter", [member_doc.email], context, f"Welcome to {self.chapter_name}"
            )

        except Exception as e:
            self.log_action(
                "Failed to send member added notification", {"member": member_id, "error": str(e)}, "error"
            )

    def _notify_member_removed(self, member_id: str, reason: str = None):
        """Send notification when member is removed"""
        try:
            member_doc = frappe.get_doc("Member", member_id)

            if not member_doc.email:
                return

            context = {"member": member_doc, "chapter": self.chapter_doc, "reason": reason}

            self.send_notification(
                "member_removed_from_chapter",
                [member_doc.email],
                context,
                f"Chapter Membership Update: {self.chapter_name}",
            )

        except Exception as e:
            self.log_action(
                "Failed to send member removed notification", {"member": member_id, "error": str(e)}, "error"
            )

    def get_summary(self) -> Dict:
        """
        Get summary of member management status

        Returns:
            Dict with member summary information
        """
        self.validate_chapter_doc()

        stats = self.get_member_statistics()
        recent_additions = self._get_recent_member_changes("added")
        recent_removals = self._get_recent_member_changes("removed")

        return {
            **stats,
            "recent_additions": recent_additions,
            "recent_removals": recent_removals,
            "last_updated": now(),
        }

    def _get_recent_member_changes(self, change_type: str, days: int = 30) -> List[Dict]:
        """Get recent member changes from comments"""
        try:
            cutoff_date = frappe.utils.add_days(today(), -days)

            comments = frappe.get_all(
                "Comment",
                filters={
                    "reference_doctype": "Chapter",
                    "reference_name": self.chapter_name,
                    "creation": [">=", cutoff_date],
                    "content": ["like", f"%{change_type} member%"],
                },
                fields=["content", "creation"],
                order_by="creation desc",
                limit=10,
            )

            return [{"content": comment.content, "date": comment.creation} for comment in comments]

        except Exception:
            return []

    def handle_member_changes(self, old_doc):
        """
        Handle member changes between document versions

        Args:
            old_doc: Previous version of the chapter document
        """
        if not old_doc:
            return

        # Create lookup for old members
        old_members = {m.name: m for m in old_doc.members if m.name}

        # Check each current member for changes
        for member in self.chapter_doc.members or []:
            if not member.name:
                continue

            old_member = old_members.get(member.name)
            if not old_member:
                continue

            # Check if member was disabled
            if old_member.enabled and not member.enabled:
                # Member was disabled - update history
                ChapterMembershipHistoryManager.end_chapter_membership(
                    member_id=member.member,
                    chapter_name=self.chapter_name,
                    assignment_type="Member",
                    start_date=member.chapter_join_date or member.creation,
                    end_date=today(),
                    reason=member.leave_reason or "Membership disabled",
                )

                self.log_action(
                    "Member disabled",
                    {
                        "member": member.member,
                        "member_name": self._get_member_name(member.member),
                        "reason": member.leave_reason,
                    },
                )

            # Check if member was re-enabled
            elif not old_member.enabled and member.enabled:
                # Member was re-enabled - add new history entry
                ChapterMembershipHistoryManager.add_membership_history(
                    member_id=member.member,
                    chapter_name=self.chapter_name,
                    assignment_type="Member",
                    start_date=today(),
                    reason="Membership re-enabled",
                )

                self.log_action(
                    "Member re-enabled",
                    {"member": member.member, "member_name": self._get_member_name(member.member)},
                )

        # Handle deleted members
        self.handle_member_deletions(old_doc)

    def handle_member_deletions(self, old_doc):
        """
        Handle members that were deleted from the chapter

        Args:
            old_doc: Previous version of the chapter document
        """
        if not old_doc:
            return

        # Get current member identifiers
        current_members = set()
        for m in self.chapter_doc.members or []:
            if m.member and m.name:
                current_members.add(m.name)

        # Check for deleted members
        for old_member in old_doc.members or []:
            if (
                old_member.name
                and old_member.name not in current_members
                and old_member.enabled
                and old_member.member
            ):
                # Member was deleted - update history
                ChapterMembershipHistoryManager.end_chapter_membership(
                    member_id=old_member.member,
                    chapter_name=self.chapter_name,
                    assignment_type="Member",
                    start_date=old_member.chapter_join_date or old_member.creation,
                    end_date=today(),
                    reason="Removed from chapter (row deleted)",
                )

                self.log_action(
                    "Member deleted from chapter",
                    {
                        "member": old_member.member,
                        "member_name": self._get_member_name(old_member.member),
                        "end_date": today(),
                    },
                )

    def handle_member_additions(self, old_doc):
        """
        Handle new member additions

        Args:
            old_doc: Previous version of the chapter document
        """
        if not old_doc:
            # For new chapters, add all enabled members to history
            for member in self.chapter_doc.members or []:
                if member.enabled and member.member:
                    ChapterMembershipHistoryManager.add_membership_history(
                        member_id=member.member,
                        chapter_name=self.chapter_name,
                        assignment_type="Member",
                        start_date=member.chapter_join_date or today(),
                        reason="Added to chapter",
                    )
            return

        # Create lookup for old members
        old_member_ids = {m.member for m in old_doc.members if m.member and m.enabled}

        # Check for new members
        for member in self.chapter_doc.members or []:
            if member.enabled and member.member and member.member not in old_member_ids:
                # New member added - create history entry
                ChapterMembershipHistoryManager.add_membership_history(
                    member_id=member.member,
                    chapter_name=self.chapter_name,
                    assignment_type="Member",
                    start_date=member.chapter_join_date or today(),
                    reason="Added to chapter",
                )

                self.log_action(
                    "Member added to chapter",
                    {
                        "member": member.member,
                        "member_name": self._get_member_name(member.member),
                        "join_date": member.chapter_join_date or today(),
                    },
                )
