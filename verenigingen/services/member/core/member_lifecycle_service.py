"""
Member Lifecycle Service - Centralized member lifecycle management.

This service handles all aspects of member lifecycle including application processing,
status transitions, membership management, and workflow coordination.

Extracted from Member DocType to improve maintainability, testability, and reusability.

Key Features:
    - Application approval and rejection workflows
    - Status synchronization and validation
    - Membership lifecycle management
    - Integration with chapter management and user creation
    - Comprehensive error handling and audit trails
    - Concurrency-safe operations

Author: Verenigingen Development Team
Created: 2025-09-18
"""

import logging
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime, today

logger = logging.getLogger(__name__)


class MemberLifecycleService:
    """
    Centralized service for managing member lifecycle operations.

    This service provides a clean interface for all member lifecycle operations
    including application processing, status management, and membership handling.
    """

    def __init__(self):
        """Initialize the Member Lifecycle Service"""
        pass

    def approve_application(self, member) -> Dict[str, Any]:
        """
        Validate application and assign member_id.

        Status field setting is delegated to create_membership_on_approval()
        via the approval_fields dict pattern to prevent duplicate saves.

        Args:
            member: Member document to approve

        Returns:
            Dict containing success status, member_id, and any errors
        """
        try:
            # Validate pre-conditions
            validation_result = self._validate_application_approval(member)
            if not validation_result["success"]:
                return validation_result

            # Assign member ID if needed (this is the only field this service should set)
            if not member.member_id:
                member.member_id = member.generate_member_id()
                # Save ONLY member_id field to avoid duplicate full saves
                frappe.db.set_value("Member", member.name, "member_id", member.member_id)
                frappe.db.commit()

            return {
                "success": True,
                "member_id": member.member_id,
                "errors": [],
            }

        except Exception as e:
            logger.error(f"Error validating application for member {member.name}: {str(e)}")
            return {
                "success": False,
                "member_id": None,
                "errors": [f"Application validation failed: {str(e)}"],
            }

    def reject_application(self, member, reason: str) -> Dict[str, Any]:
        """
        Reject member application and clean up pending records.

        Args:
            member: Member document to reject
            reason: Reason for rejection

        Returns:
            Dict containing success status and any errors
        """
        try:
            # Validate pre-conditions
            validation_result = self._validate_application_rejection(member)
            if not validation_result["success"]:
                return validation_result

            # Update status fields
            member.application_status = "Rejected"
            member.status = "Rejected"
            member.reviewed_by = frappe.session.user
            member.review_date = now_datetime()
            member.rejection_reason = reason

            # Save with concurrency handling
            save_result = self._save_member_with_retry(member, "reject")
            if not save_result["success"]:
                return save_result

            # Perform post-rejection cleanup
            cleanup_result = self._perform_post_rejection_cleanup(member)

            return {
                "success": True,
                "status": member.status,
                "review_date": member.review_date,
                "cleanup_results": cleanup_result,
                "errors": [],
            }

        except Exception as e:
            logger.error(f"Error rejecting application for member {member.name}: {str(e)}")
            return {
                "success": False,
                "status": None,
                "review_date": None,
                "cleanup_results": {},
                "errors": [f"Application rejection failed: {str(e)}"],
            }

    def update_membership_status(self, member) -> Dict[str, Any]:
        """
        Update member's membership status based on active memberships.

        Args:
            member: Member document to update

        Returns:
            Dict containing success status, membership status, and membership type
        """
        try:
            # Get active membership
            active_membership = self._get_active_membership(member)

            if active_membership:
                member.membership_status = "Active"
                # Update current membership type if field exists
                if hasattr(member, "current_membership_type"):
                    member.current_membership_type = active_membership.membership_type

                return {
                    "success": True,
                    "membership_status": "Active",
                    "membership_type": active_membership.membership_type,
                    "membership_name": active_membership.name,
                    "errors": [],
                }
            else:
                # Check for expired memberships
                expired_membership = self._get_most_recent_expired_membership(member)

                if expired_membership:
                    member.membership_status = "Expired"
                    # Keep the last membership type even if expired
                    if hasattr(member, "current_membership_type"):
                        member.current_membership_type = expired_membership.membership_type

                    return {
                        "success": True,
                        "membership_status": "Expired",
                        "membership_type": expired_membership.membership_type,
                        "membership_name": expired_membership.name,
                        "errors": [],
                    }
                else:
                    # No memberships found
                    member.membership_status = None
                    if hasattr(member, "current_membership_type"):
                        member.current_membership_type = None

                    return {
                        "success": True,
                        "membership_status": None,
                        "membership_type": None,
                        "membership_name": None,
                        "errors": [],
                    }

        except Exception as e:
            logger.error(f"Error updating membership status for member {member.name}: {str(e)}")
            return {
                "success": False,
                "membership_status": None,
                "membership_type": None,
                "membership_name": None,
                "errors": [f"Membership status update failed: {str(e)}"],
            }

    def sync_status_fields(self, member) -> Dict[str, Any]:
        """
        Synchronize status and application_status fields.

        Args:
            member: Member document to synchronize

        Returns:
            Dict containing success status and any changes made
        """
        try:
            changes_made = []

            # Check if this member was created through application process
            is_application_member = bool(getattr(member, "application_id", None))

            if is_application_member:
                # Handle application-created members
                if hasattr(member, "application_status") and member.application_status:
                    if member.application_status == "Approved" and member.status != "Active":
                        member.status = "Active"
                        changes_made.append("Set status to Active (application approved)")

                        # Set member_since date when application becomes approved
                        if not getattr(member, "member_since", None):
                            member.member_since = today()
                            changes_made.append("Set member_since date")

                    elif member.application_status == "Rejected" and member.status != "Rejected":
                        # Don't override status if member was terminated
                        if member.status not in ["Terminated", "Suspended"]:
                            member.status = "Rejected"
                            changes_made.append("Set status to Rejected (application rejected)")
            else:
                # Handle backend-created members
                if not hasattr(member, "application_status") or not member.application_status:
                    member.application_status = "Approved"
                    changes_made.append("Set application_status to Approved (backend-created member)")

            return {
                "success": True,
                "changes_made": changes_made,
                "is_application_member": is_application_member,
                "final_status": member.status,
                "final_application_status": getattr(member, "application_status", None),
                "errors": [],
            }

        except Exception as e:
            logger.error(f"Error syncing status fields for member {member.name}: {str(e)}")
            return {
                "success": False,
                "changes_made": [],
                "is_application_member": False,
                "final_status": None,
                "final_application_status": None,
                "errors": [f"Status synchronization failed: {str(e)}"],
            }

    def get_status_color(self, status: str) -> str:
        """
        Get display color for member status.

        Args:
            status: Member status

        Returns:
            Color code for status display
        """
        status_colors = {
            "Active": "green",
            "Inactive": "gray",
            "Suspended": "orange",
            "Terminated": "red",
            "Pending": "blue",
            "Rejected": "red",
            "Application": "blue",
        }
        return status_colors.get(status, "gray")

    def is_application_member(self, member) -> bool:
        """
        Check if member was created through application process.

        Args:
            member: Member document to check

        Returns:
            True if member has application_id, False otherwise
        """
        return bool(getattr(member, "application_id", None))

    def set_application_status_defaults(self, member) -> Dict[str, Any]:
        """
        Set appropriate defaults for application_status based on member type.

        Args:
            member: Member document to set defaults for

        Returns:
            Dict containing success status and any changes made
        """
        try:
            changes_made = []

            # Check if application_status is not set
            if not hasattr(member, "application_status") or not member.application_status:
                is_application_member = self.is_application_member(member)

                if is_application_member:
                    # Application members start as Pending
                    member.application_status = "Pending"
                    changes_made.append("Set application_status to Pending (application member)")
                else:
                    # Backend-created members are considered approved
                    member.application_status = "Approved"
                    changes_made.append("Set application_status to Approved (backend-created member)")

            return {
                "success": True,
                "changes_made": changes_made,
                "application_status": getattr(member, "application_status", None),
                "errors": [],
            }

        except Exception as e:
            logger.error(f"Error setting application status defaults for member {member.name}: {str(e)}")
            return {
                "success": False,
                "changes_made": [],
                "application_status": None,
                "errors": [f"Setting application status defaults failed: {str(e)}"],
            }

    # Private helper methods

    def _validate_application_approval(self, member) -> Dict[str, Any]:
        """Validate that application can be approved"""
        if not self.is_application_member(member):
            return {"success": False, "errors": ["This is not an application member"]}

        if getattr(member, "application_status", None) == "Approved":
            return {"success": False, "errors": ["Application is already approved"]}

        return {"success": True, "errors": []}

    def _validate_application_rejection(self, member) -> Dict[str, Any]:
        """Validate that application can be rejected"""
        if not self.is_application_member(member):
            return {"success": False, "errors": ["This is not an application member"]}

        if getattr(member, "application_status", None) == "Rejected":
            return {"success": False, "errors": ["Application is already rejected"]}

        return {"success": True, "errors": []}

    def _save_member_with_retry(self, member, operation: str) -> Dict[str, Any]:
        """Save member with concurrency handling"""
        try:
            member.save()
            return {"success": True, "errors": []}
        except frappe.TimestampMismatchError:
            # Reload member and retry save once
            try:
                member.reload()

                # Re-apply changes based on operation
                if operation == "approve":
                    if not member.member_id:
                        member.member_id = member.generate_member_id()
                    member.application_status = "Approved"
                    member.status = "Active"
                    member.reviewed_by = frappe.session.user
                    member.review_date = now_datetime()
                elif operation == "reject":
                    member.application_status = "Rejected"
                    member.status = "Rejected"
                    member.reviewed_by = frappe.session.user
                    member.review_date = now_datetime()

                member.save()
                return {"success": True, "errors": []}
            except Exception as e:
                return {"success": False, "errors": [f"Failed to save after retry: {str(e)}"]}
        except Exception as e:
            return {"success": False, "errors": [f"Failed to save member: {str(e)}"]}

    def _perform_post_approval_setup(self, member) -> Dict[str, Any]:
        """Perform post-approval setup tasks"""
        setup_results = {
            "user_creation_queued": False,
            "customer_created": False,
            "chapter_activated": False,
            "errors": [],
        }

        try:
            # Queue user account creation via AccountCreationManager instead of direct creation
            if not member.user:
                try:
                    from verenigingen.utils.account_creation_manager import queue_account_creation_for_member

                    result = queue_account_creation_for_member(
                        member_name=member.name,
                        roles=["Verenigingen Member"],
                        priority="High",  # Approval workflow gets high priority
                    )

                    if result and result.get("success"):
                        setup_results["user_creation_queued"] = True
                        setup_results["account_request"] = result.get("request_name")
                        logger.info(
                            f"Queued account creation for member {member.name}: {result.get('request_name')}"
                        )
                    else:
                        error_msg = result.get("error") if result else "Unknown error"
                        setup_results["errors"].append(f"Failed to queue user creation: {error_msg}")
                        logger.error(f"Account creation queue failed for {member.name}: {error_msg}")
                except Exception as e:
                    setup_results["errors"].append(f"Failed to queue user creation: {str(e)}")
                    logger.error(f"Exception queuing account creation for {member.name}: {str(e)}")

            # Create customer if not exists
            if not member.customer:
                try:
                    member.create_customer()
                    setup_results["customer_created"] = True
                except Exception as e:
                    setup_results["errors"].append(f"Failed to create customer: {str(e)}")

            # Activate pending Chapter Member records
            try:
                from verenigingen.utils.application_helpers import activate_pending_chapter_membership

                # Find pending chapter memberships for this member
                pending_chapters = frappe.db.sql(
                    """
                    SELECT chapter, name
                    FROM `tabChapter Member`
                    WHERE member = %s AND status = 'Pending'
                    """,
                    (member.name,),
                    as_dict=True,
                )

                activated_chapters = []
                for chapter_record in pending_chapters:
                    try:
                        success = activate_pending_chapter_membership(member, chapter_record.chapter)
                        if success:
                            activated_chapters.append(chapter_record.chapter)
                    except Exception as e:
                        setup_results["errors"].append(
                            f"Failed to activate chapter {chapter_record.chapter}: {str(e)}"
                        )

                if activated_chapters:
                    setup_results["chapter_activated"] = True
                    setup_results["activated_chapters"] = activated_chapters

            except Exception as e:
                setup_results["errors"].append(f"Failed to activate chapter memberships: {str(e)}")

        except Exception as e:
            setup_results["errors"].append(f"Post-approval setup failed: {str(e)}")

        return setup_results

    def _perform_post_rejection_cleanup(self, member) -> Dict[str, Any]:
        """Perform post-rejection cleanup tasks"""
        cleanup_results = {"chapters_removed": [], "errors": []}

        try:
            from verenigingen.utils.application_helpers import remove_pending_chapter_membership

            # Check for suggested chapter or current chapter display
            chapter_to_remove = None
            if hasattr(member, "current_chapter_display") and member.current_chapter_display:
                chapter_to_remove = member.current_chapter_display
            elif hasattr(member, "previous_chapter") and member.previous_chapter:
                chapter_to_remove = member.previous_chapter

            if chapter_to_remove:
                try:
                    success = remove_pending_chapter_membership(member, chapter_to_remove)
                    if success:
                        cleanup_results["chapters_removed"].append(chapter_to_remove)
                        frappe.logger().info(
                            f"Removed pending chapter membership for {member.name} from {chapter_to_remove}"
                        )
                    else:
                        cleanup_results["errors"].append(
                            f"Failed to remove pending chapter membership from {chapter_to_remove}"
                        )
                except Exception as e:
                    cleanup_results["errors"].append(
                        f"Error removing chapter membership from {chapter_to_remove}: {str(e)}"
                    )

        except Exception as e:
            cleanup_results["errors"].append(f"Post-rejection cleanup failed: {str(e)}")

        return cleanup_results

    def _get_active_membership(self, member):
        """Get active membership for member"""
        try:
            active_membership = frappe.get_all(
                "Membership",
                filters={"member": member.name, "renewal_date": [">=", today()], "docstatus": 1},
                fields=["name", "membership_type"],
                limit=1,
            )

            if active_membership:
                return frappe.get_doc("Membership", active_membership[0].name)
            return None
        except Exception:
            return None

    def _get_most_recent_expired_membership(self, member):
        """Get most recent expired membership for member"""
        try:
            expired = frappe.get_all(
                "Membership",
                filters={"member": member.name, "renewal_date": ["<", today()], "docstatus": 1},
                fields=["name", "membership_type", "renewal_date"],
                order_by="renewal_date desc",
                limit=1,
            )

            if expired:
                return frappe.get_doc("Membership", expired[0].name)
            return None
        except Exception:
            return None


# Singleton instance
member_lifecycle_service = MemberLifecycleService()
