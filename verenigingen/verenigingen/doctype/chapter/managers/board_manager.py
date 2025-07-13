# verenigingen/verenigingen/doctype/chapter/managers/boardmanager.py
import json
from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

from .base_manager import BaseManager


class BoardManager(BaseManager):
    """Manager for chapter board member operations"""

    def __init__(self, chapter_doc):
        super().__init__(chapter_doc)
        self.volunteer_cache = {}

    def add_board_member(
        self, volunteer: str, role: str, from_date: str = None, to_date: str = None, notify: bool = True
    ) -> Dict:
        """
        Add a new board member to the chapter

        Args:
            volunteer: Volunteer ID
            role: Chapter role name
            from_date: Start date (defaults to today)
            to_date: End date (optional)
            notify: Whether to send notification

        Returns:
            Dict with operation result
        """
        self.validate_chapter_doc()

        if not from_date:
            from_date = today()

        try:
            # Validate inputs
            self._validate_add_board_member_inputs(volunteer, role)

            # Get volunteer and member details
            volunteer_doc = frappe.get_doc("Volunteer", volunteer)
            member_doc = frappe.get_doc("Member", volunteer_doc.member) if volunteer_doc.member else None

            if not member_doc:
                frappe.throw(
                    _("Volunteer {0} does not have an associated member").format(volunteer_doc.volunteer_name)
                )

            # Handle unique role constraints
            self._handle_unique_role_assignment(role, from_date)

            # Add board member
            board_member = self.chapter_doc.append(
                "board_members",
                {
                    "volunteer": volunteer,
                    "volunteer_name": volunteer_doc.volunteer_name,
                    "email": volunteer_doc.email,
                    "chapter_role": role,
                    "from_date": from_date,
                    "to_date": to_date,
                    "is_active": 1,
                },
            )

            # Add to chapter members if not already a member
            self._add_to_chapter_members(member_doc.name)

            # Save chapter
            self.chapter_doc.save()

            # Add to volunteer assignment history
            self.add_volunteer_assignment_history(volunteer, role, from_date)

            # Add to chapter membership history for the associated member
            if member_doc:
                ChapterMembershipHistoryManager.add_membership_history(
                    member_id=member_doc.name,
                    chapter_name=self.chapter_name,
                    assignment_type="Board Member",
                    start_date=from_date,
                    reason=f"Appointed as {role} in {self.chapter_name}",
                )

            # Create audit comment
            self.create_comment(
                "Info",
                _("Added {0} as {1} starting {2}").format(volunteer_doc.volunteer_name, role, from_date),
            )

            # Send notification
            if notify:
                self._notify_board_member_added(volunteer, role)

            self.log_action(
                "Board member added",
                {
                    "volunteer": volunteer,
                    "volunteer_name": volunteer_doc.volunteer_name,
                    "role": role,
                    "from_date": from_date,
                },
            )

            return {
                "success": True,
                "board_member": board_member,
                "message": _("Board member added successfully"),
            }

        except Exception as e:
            self.log_action(
                "Failed to add board member", {"volunteer": volunteer, "role": role, "error": str(e)}, "error"
            )
            raise

    def remove_board_member(
        self, volunteer: str, end_date: str = None, reason: str = None, notify: bool = True
    ) -> Dict:
        """
        Remove a board member from the chapter

        Args:
            volunteer: Volunteer ID
            end_date: End date (defaults to today)
            reason: Reason for removal
            notify: Whether to send notification

        Returns:
            Dict with operation result
        """
        self.validate_chapter_doc()

        if not end_date:
            end_date = today()

        try:
            # Find the active board membership
            board_member = self._find_active_board_member(volunteer)
            if not board_member:
                frappe.throw(_("Volunteer {0} is not an active board member").format(volunteer))

            # Store data for history update
            board_member_data = {
                "volunteer": board_member.volunteer,
                "volunteer_name": board_member.volunteer_name,
                "chapter_role": board_member.chapter_role,
                "from_date": board_member.from_date,
            }

            # Deactivate board member
            board_member.is_active = 0
            board_member.to_date = end_date

            # Add reason to notes if provided
            if reason:
                existing_notes = board_member.notes or ""
                board_member.notes = f"{existing_notes}\nRemoved: {reason}".strip()

            # Save chapter
            self.chapter_doc.save()

            # Update volunteer assignment history
            self.update_volunteer_assignment_history(
                board_member_data["volunteer"],
                board_member_data["chapter_role"],
                board_member_data["from_date"],
                end_date,
            )

            # Update chapter membership history for the associated member
            try:
                volunteer_doc = frappe.get_doc("Volunteer", board_member_data["volunteer"])
                if volunteer_doc.member:
                    ChapterMembershipHistoryManager.end_chapter_membership(
                        member_id=volunteer_doc.member,
                        chapter_name=self.chapter_name,
                        assignment_type="Board Member",
                        start_date=board_member_data["from_date"],
                        end_date=end_date,
                        reason=reason or f"Removed from {board_member_data['chapter_role']} role",
                    )
            except Exception as e:
                frappe.log_error(f"Error updating chapter membership history: {str(e)}")

            # Create audit comment
            self.create_comment(
                "Info",
                ("Removed {0} from {1} role on {2}").format(
                    board_member_data["volunteer_name"], board_member_data["chapter_role"], end_date
                )
                + (f". Reason: {reason}" if reason else ""),
            )

            # Send notification
            if notify:
                self._notify_board_member_removed(volunteer)

            self.log_action(
                "Board member removed",
                {
                    "volunteer": volunteer,
                    "volunteer_name": board_member_data["volunteer_name"],
                    "role": board_member_data["chapter_role"],
                    "end_date": end_date,
                    "reason": reason,
                },
            )

            return {"success": True, "message": _("Board member removed successfully")}

        except Exception as e:
            self.log_action(
                "Failed to remove board member", {"volunteer": volunteer, "error": str(e)}, "error"
            )
            raise

    def transition_board_role(
        self, volunteer: str, new_role: str, transition_date: str = None, reason: str = None
    ) -> Dict:
        """
        Transition a board member to a new role

        Args:
            volunteer: Volunteer ID
            new_role: New chapter role
            transition_date: Date of transition (defaults to today)
            reason: Reason for transition

        Returns:
            Dict with operation result
        """
        self.validate_chapter_doc()

        if not transition_date:
            transition_date = today()

        try:
            # Find current active role
            current_board_member = self._find_active_board_member(volunteer)
            if not current_board_member:
                frappe.throw(_("Volunteer {0} is not an active board member").format(volunteer))

            current_role = current_board_member.chapter_role
            volunteer_name = current_board_member.volunteer_name

            # End current role
            self.remove_board_member(
                volunteer,
                transition_date,
                f"Role transition to {new_role}" + (f". {reason}" if reason else ""),
                notify=False,
            )

            # Add new role
            # result = self.add_board_member(volunteer, new_role, transition_date, notify=False)

            # Create audit comment for transition
            self.create_comment(
                "Info",
                ("Role transition: {0} changed from {1} to {2} on {3}").format(
                    volunteer_name, current_role, new_role, transition_date
                )
                + (f". Reason: {reason}" if reason else ""),
            )

            # Send single notification for the transition
            self._notify_role_transition(volunteer, current_role, new_role)

            self.log_action(
                "Board role transition",
                {
                    "volunteer": volunteer,
                    "volunteer_name": volunteer_name,
                    "old_role": current_role,
                    "new_role": new_role,
                    "transition_date": transition_date,
                    "reason": reason,
                },
            )

            return {"success": True, "message": _("Role transition completed successfully")}

        except Exception as e:
            self.log_action(
                "Failed to transition board role",
                {"volunteer": volunteer, "new_role": new_role, "error": str(e)},
                "error",
            )
            raise

    def bulk_remove_board_members(self, board_members: List[Dict]) -> Dict:
        """
        Bulk remove board members from chapter

        Args:
            board_members: List of board member data dicts

        Returns:
            Dict with operation results
        """
        self.validate_chapter_doc()

        if isinstance(board_members, str):
            board_members = json.loads(board_members)

        if not board_members:
            return {"success": False, "error": "No board members specified"}

        processed_count = 0
        errors = []

        try:
            for member_data in board_members:
                try:
                    volunteer = member_data.get("volunteer")
                    end_date = member_data.get("end_date")
                    reason = member_data.get("reason", "")

                    if not volunteer:
                        errors.append("Missing volunteer ID")
                        continue

                    # Find and remove the board member
                    removed = False
                    for board_member in self.chapter_doc.board_members[:]:  # Create copy for safe iteration
                        if (
                            board_member.volunteer == volunteer
                            and board_member.is_active
                            and board_member.chapter_role == member_data.get("chapter_role")
                            and str(board_member.from_date) == str(member_data.get("from_date"))
                        ):
                            # Store data for history update before removal
                            history_data = {
                                "volunteer": board_member.volunteer,
                                "volunteer_name": board_member.volunteer_name,
                                "chapter_role": board_member.chapter_role,
                                "from_date": board_member.from_date,
                            }

                            # Remove the board member completely
                            self.chapter_doc.board_members.remove(board_member)
                            removed = True
                            processed_count += 1

                            # Update volunteer assignment history
                            self.update_volunteer_assignment_history(
                                history_data["volunteer"],
                                history_data["chapter_role"],
                                history_data["from_date"],
                                end_date,
                            )

                            # Create audit comment
                            self.create_comment(
                                "Info",
                                ("Bulk removal: {0} removed from {1} role").format(
                                    history_data["volunteer_name"], history_data["chapter_role"]
                                )
                                + (f". Reason: {reason}" if reason else ""),
                            )

                            break

                    if not removed:
                        errors.append(f"Active board member not found for volunteer {volunteer}")

                except Exception as e:
                    errors.append(
                        f"Error processing volunteer {member_data.get('volunteer', 'unknown')}: {str(e)}"
                    )

            # Save the chapter document
            self.chapter_doc.save()

            self.log_action(
                "Bulk board member removal",
                {"processed": processed_count, "errors": len(errors), "total_requested": len(board_members)},
            )

            return {"success": True, "processed": processed_count, "errors": errors}

        except Exception as e:
            self.log_action(
                "Critical error in bulk board member removal",
                {"error": str(e), "processed": processed_count},
                "error",
            )
            return {"success": False, "error": str(e), "processed": processed_count}

    def bulk_deactivate_board_members(self, board_members: List[Dict]) -> Dict:
        """
        Bulk deactivate board members (keep in list but mark inactive)

        Args:
            board_members: List of board member data dicts

        Returns:
            Dict with operation results
        """
        self.validate_chapter_doc()

        if isinstance(board_members, str):
            board_members = json.loads(board_members)

        if not board_members:
            return {"success": False, "error": "No board members specified"}

        processed_count = 0
        errors = []

        try:
            for member_data in board_members:
                try:
                    volunteer = member_data.get("volunteer")
                    end_date = member_data.get("end_date")
                    reason = member_data.get("reason", "")

                    if not volunteer:
                        errors.append("Missing volunteer ID")
                        continue

                    # Find and deactivate the board member
                    deactivated = False
                    for board_member in self.chapter_doc.board_members:
                        if (
                            board_member.volunteer == volunteer
                            and board_member.is_active
                            and board_member.chapter_role == member_data.get("chapter_role")
                            and str(board_member.from_date) == str(member_data.get("from_date"))
                        ):
                            # Deactivate the board member
                            board_member.is_active = 0
                            board_member.to_date = end_date

                            # Add reason to notes if provided
                            if reason:
                                existing_notes = board_member.notes or ""
                                board_member.notes = f"{existing_notes}\nDeactivated: {reason}".strip()

                            deactivated = True
                            processed_count += 1

                            # Update volunteer assignment history
                            self.update_volunteer_assignment_history(
                                board_member.volunteer,
                                board_member.chapter_role,
                                board_member.from_date,
                                end_date,
                            )

                            # Create audit comment
                            self.create_comment(
                                "Info",
                                ("Bulk deactivation: {0} deactivated from {1} role").format(
                                    board_member.volunteer_name, board_member.chapter_role
                                )
                                + (f". Reason: {reason}" if reason else ""),
                            )

                            break

                    if not deactivated:
                        errors.append(f"Active board member not found for volunteer {volunteer}")

                except Exception as e:
                    errors.append(
                        f"Error processing volunteer {member_data.get('volunteer', 'unknown')}: {str(e)}"
                    )

            # Save the chapter document
            self.chapter_doc.save()

            self.log_action(
                "Bulk board member deactivation",
                {"processed": processed_count, "errors": len(errors), "total_requested": len(board_members)},
            )

            return {"success": True, "processed": processed_count, "errors": errors}

        except Exception as e:
            self.log_action(
                "Critical error in bulk board member deactivation",
                {"error": str(e), "processed": processed_count},
                "error",
            )
            return {"success": False, "error": str(e), "processed": processed_count}

    def get_board_members(self, include_inactive: bool = False, role: str = None) -> List[Dict]:
        """
        Get list of board members with details using optimized queries

        Args:
            include_inactive: Whether to include inactive members
            role: Filter by specific role

        Returns:
            List of board member dictionaries
        """
        self.validate_chapter_doc()

        # Filter board members
        filtered_members = []
        volunteer_ids = []

        for board_member in self.chapter_doc.board_members or []:
            if (include_inactive or board_member.is_active) and (
                not role or board_member.chapter_role == role
            ):
                filtered_members.append(board_member)
                if board_member.volunteer:
                    volunteer_ids.append(board_member.volunteer)

        if not filtered_members:
            return []

        # Batch query for volunteer-member mapping
        volunteer_member_map = {}
        if volunteer_ids:
            volunteer_data = frappe.get_all(
                "Volunteer", filters={"name": ["in", volunteer_ids]}, fields=["name", "member"]
            )
            volunteer_member_map = {v.name: v.member for v in volunteer_data if v.member}

        # Build result list
        members = []
        for board_member in filtered_members:
            member_id = volunteer_member_map.get(board_member.volunteer)

            members.append(
                {
                    "volunteer": board_member.volunteer,
                    "volunteer_name": board_member.volunteer_name,
                    "member": member_id,
                    "email": board_member.email,
                    "role": board_member.chapter_role,
                    "from_date": board_member.from_date,
                    "to_date": board_member.to_date,
                    "is_active": board_member.is_active,
                    "notes": board_member.notes,
                }
            )
        return members

    def get_active_board_roles(self) -> Dict[str, Dict]:
        """
        Get all active board roles using optimized queries

        Returns:
            Dict mapping role names to board member info
        """
        self.validate_chapter_doc()

        # Get active board members
        active_members = [m for m in self.chapter_doc.board_members or [] if m.is_active and m.chapter_role]

        if not active_members:
            return {}

        # Batch query for volunteer-member mapping
        volunteer_ids = [m.volunteer for m in active_members if m.volunteer]
        volunteer_member_map = {}

        if volunteer_ids:
            volunteer_data = frappe.get_all(
                "Volunteer", filters={"name": ["in", volunteer_ids]}, fields=["name", "member"]
            )
            volunteer_member_map = {v.name: v.member for v in volunteer_data if v.member}

        # Build roles dict
        roles = {}
        for member in active_members:
            member_id = volunteer_member_map.get(member.volunteer)

            roles[member.chapter_role] = {
                "volunteer": member.volunteer,
                "volunteer_name": member.volunteer_name,
                "member": member_id,
                "email": member.email,
                "from_date": member.from_date,
            }
        return roles

    def is_board_member(self, member_name: str = None, user: str = None, volunteer_name: str = None) -> bool:
        """
        Check if a member/user/volunteer is on the board of this chapter using optimized query

        Args:
            member_name: Member name
            user: User email
            volunteer_name: Volunteer name

        Returns:
            bool: Whether user is a board member
        """
        self.validate_chapter_doc()

        # Use optimized single query approach
        if not member_name and not user and not volunteer_name:
            user = frappe.session.user

        if user and not member_name:
            member_name = frappe.db.get_value("Member", {"user": user}, "name")

        if member_name:
            # Single query to check board membership
            result = frappe.db.sql(
                """
                SELECT 1
                FROM `tabChapter Board Member` cbm
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                WHERE cbm.parent = %s
                AND v.member = %s
                AND cbm.is_active = 1
                LIMIT 1
            """,
                (self.chapter_doc.name, member_name),
            )

            return bool(result)

        if volunteer_name:
            # Direct volunteer check
            for board_member in self.chapter_doc.board_members or []:
                if board_member.volunteer == volunteer_name and board_member.is_active:
                    return True

        return False

    def get_member_role(
        self, member_name: str = None, user: str = None, volunteer_name: str = None
    ) -> Optional[str]:
        """
        Get the board role of a member/user/volunteer using optimized query

        Args:
            member_name: Member name
            user: User email
            volunteer_name: Volunteer name

        Returns:
            str: Role name or None
        """
        self.validate_chapter_doc()

        # Use optimized single query approach
        if not member_name and not user and not volunteer_name:
            user = frappe.session.user

        if user and not member_name:
            member_name = frappe.db.get_value("Member", {"user": user}, "name")

        if member_name:
            # Single query to get board role
            result = frappe.db.sql(
                """
                SELECT cbm.chapter_role
                FROM `tabChapter Board Member` cbm
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                WHERE cbm.parent = %s
                AND v.member = %s
                AND cbm.is_active = 1
                LIMIT 1
            """,
                (self.chapter_doc.name, member_name),
                as_dict=True,
            )

            return result[0].chapter_role if result else None

        if volunteer_name:
            # Direct volunteer check
            for board_member in self.chapter_doc.board_members or []:
                if board_member.volunteer == volunteer_name and board_member.is_active:
                    return board_member.chapter_role

        return None

    def can_view_member_payments(self, member_name: str = None, user: str = None) -> bool:
        """
        Check if a board member can view payment information

        Args:
            member_name: Member name
            user: User email

        Returns:
            bool: Whether member can view payments
        """
        if not member_name and not user:
            user = frappe.session.user
            member_name = frappe.db.get_value("Member", {"user": user}, "name")

        if not member_name:
            return False

        # Get the role
        role = self.get_member_role(member_name)
        if not role:
            return False

        # Check if role has financial permissions
        try:
            role_doc = frappe.get_doc("Chapter Role", role)
            return role_doc.permissions_level in ["Financial", "Admin"]
        except Exception:
            # If role doesn't exist or has no permissions level
            return False

    def handle_board_member_changes(self, old_doc):
        """
        Handle board member changes between document versions

        Args:
            old_doc: Previous version of the chapter document
        """
        if not old_doc:
            return

        # Create lookup for old board members
        old_board_members = {bm.name: bm for bm in old_doc.board_members if bm.name}

        # Check each current board member for changes
        members_to_remove = []
        for board_member in self.chapter_doc.board_members or []:
            if not board_member.name:
                continue

            old_board_member = old_board_members.get(board_member.name)
            if not old_board_member:
                continue

            # Check for role changes (same volunteer, same activity status, different role)
            if (
                old_board_member.is_active == 1
                and board_member.is_active == 1
                and board_member.volunteer
                and old_board_member.chapter_role != board_member.chapter_role
            ):
                # Role changed - complete old assignment and create new one
                change_date = today()

                # Complete old role assignment
                self.update_volunteer_assignment_history(
                    board_member.volunteer,
                    old_board_member.chapter_role,  # Use old role
                    board_member.from_date,
                    change_date,
                )

                # Start new role assignment
                self.add_volunteer_assignment_history(
                    board_member.volunteer, board_member.chapter_role, change_date  # Use new role
                )

                self.log_action(
                    "Board member role changed",
                    {
                        "volunteer": board_member.volunteer,
                        "volunteer_name": board_member.volunteer_name,
                        "old_role": old_board_member.chapter_role,
                        "new_role": board_member.chapter_role,
                        "change_date": change_date,
                    },
                )

            # Check if board member was deactivated
            elif old_board_member.is_active == 1 and board_member.is_active == 0 and board_member.volunteer:
                # Set to_date if not already set
                if not board_member.to_date:
                    board_member.to_date = today()

                # Update volunteer assignment history
                self.update_volunteer_assignment_history(
                    board_member.volunteer,
                    board_member.chapter_role,
                    board_member.from_date,
                    board_member.to_date,
                )

                # Mark for removal from active board display
                members_to_remove.append(board_member)

        # Remove deactivated board members from the list
        # This ensures they don't show up in the active board display
        for member_to_remove in members_to_remove:
            self.chapter_doc.board_members.remove(member_to_remove)

            self.log_action(
                "Removed deactivated board member from display",
                {
                    "volunteer": member_to_remove.volunteer,
                    "volunteer_name": member_to_remove.volunteer_name,
                    "role": member_to_remove.chapter_role,
                    "end_date": member_to_remove.to_date,
                },
            )

        # Handle deleted board members (existed in old doc but not in new)
        self.handle_board_member_deletions(old_doc)

    def handle_board_member_deletions(self, old_doc):
        """
        Handle board members that were deleted from the chapter

        Args:
            old_doc: Previous version of the chapter document
        """
        if not old_doc:
            return

        # Get current board member identifiers
        current_board_members = set()
        for bm in self.chapter_doc.board_members or []:
            if bm.volunteer and bm.name:
                current_board_members.add(bm.name)

        # Check for deleted board members
        for old_board_member in old_doc.board_members or []:
            if (
                old_board_member.name
                and old_board_member.name not in current_board_members
                and old_board_member.is_active
                and old_board_member.volunteer
            ):
                # Board member was deleted - update histories
                end_date = today()

                # Update volunteer assignment history
                self.update_volunteer_assignment_history(
                    old_board_member.volunteer,
                    old_board_member.chapter_role,
                    old_board_member.from_date,
                    end_date,
                )

                # Update chapter membership history for the associated member
                try:
                    volunteer_doc = frappe.get_doc("Volunteer", old_board_member.volunteer)
                    if volunteer_doc.member:
                        ChapterMembershipHistoryManager.end_chapter_membership(
                            member_id=volunteer_doc.member,
                            chapter_name=self.chapter_name,
                            assignment_type="Board Member",
                            start_date=old_board_member.from_date,
                            end_date=end_date,
                            reason="Removed from board (row deleted)",
                        )
                except Exception as e:
                    frappe.log_error(
                        f"Error updating chapter membership history for deleted board member: {str(e)}"
                    )

                self.log_action(
                    "Board member deleted from chapter",
                    {
                        "volunteer": old_board_member.volunteer,
                        "volunteer_name": old_board_member.volunteer_name,
                        "role": old_board_member.chapter_role,
                        "end_date": end_date,
                    },
                )

    def handle_board_member_additions(self, old_doc):
        """
        Handle new board member additions

        Args:
            old_doc: Previous version of the chapter document
        """
        if not old_doc:
            # For new chapters, add all active board members to history
            for board_member in self.chapter_doc.board_members or []:
                if board_member.is_active and board_member.volunteer:
                    self.add_volunteer_assignment_history(
                        board_member.volunteer, board_member.chapter_role, board_member.from_date
                    )
            return

        # Create lookup for old board members (volunteer + role combination)
        old_board_member_keys = {
            (bm.volunteer, bm.chapter_role) for bm in old_doc.board_members if bm.volunteer and bm.is_active
        }

        # Check for new active board members (truly new, not role changes)
        for board_member in self.chapter_doc.board_members or []:
            current_key = (board_member.volunteer, board_member.chapter_role)
            if board_member.is_active and board_member.volunteer and current_key not in old_board_member_keys:
                # Add volunteer assignment history
                self.add_volunteer_assignment_history(
                    board_member.volunteer, board_member.chapter_role, board_member.from_date
                )

                # Add to chapter members if they have an associated member
                try:
                    volunteer_doc = frappe.get_doc("Volunteer", board_member.volunteer)
                    if volunteer_doc.member:
                        self._add_to_chapter_members(volunteer_doc.member)
                        self.log_action(
                            "Auto-added board member to chapter members",
                            {
                                "volunteer": board_member.volunteer,
                                "member": volunteer_doc.member,
                                "role": board_member.chapter_role,
                            },
                        )
                except Exception as e:
                    self.log_action(
                        "Failed to auto-add board member to chapter members",
                        {"volunteer": board_member.volunteer, "error": str(e)},
                        "error",
                    )

    def get_summary(self) -> Dict:
        """
        Get summary of board status

        Returns:
            Dict with board summary information
        """
        self.validate_chapter_doc()

        board_members = self.chapter_doc.board_members or []
        active_members = [m for m in board_members if m.is_active]

        # Get role distribution
        role_distribution = {}
        for member in active_members:
            role = member.chapter_role
            if role:
                role_distribution[role] = role_distribution.get(role, 0) + 1

        # Check for critical roles
        has_chair = any(self._is_chair_role(m.chapter_role) for m in active_members if m.chapter_role)

        # Calculate average tenure
        total_tenure_days = 0
        tenure_count = 0

        for member in board_members:
            if member.from_date:
                end_date = member.to_date if member.to_date else today()
                try:
                    tenure_days = (getdate(end_date) - getdate(member.from_date)).days
                    total_tenure_days += tenure_days
                    tenure_count += 1
                except Exception:
                    pass

        avg_tenure_days = total_tenure_days // tenure_count if tenure_count > 0 else 0

        return {
            "total_board_members": len(board_members),
            "active_board_members": len(active_members),
            "inactive_board_members": len(board_members) - len(active_members),
            "role_distribution": role_distribution,
            "has_chair": has_chair,
            "average_tenure_days": avg_tenure_days,
            "recent_changes": self._get_recent_board_changes(),
        }

    # Private helper methods

    def _validate_add_board_member_inputs(self, volunteer: str, role: str):
        """Validate inputs for adding board member"""
        # Check if volunteer exists
        if not frappe.db.exists("Volunteer", volunteer):
            frappe.throw(_("Volunteer {0} does not exist").format(volunteer))

        # Check if role exists
        if not frappe.db.exists("Chapter Role", role):
            frappe.throw(_("Chapter Role {0} does not exist").format(role))

        # Check if role is active
        role_doc = frappe.get_doc("Chapter Role", role)
        if not role_doc.is_active:
            frappe.throw(_("Chapter Role {0} is not active").format(role))

    def _handle_unique_role_assignment(self, role: str, from_date: str):
        """Handle unique role constraints when assigning role"""
        try:
            role_doc = frappe.get_doc("Chapter Role", role)
            if role_doc.is_unique:
                # Deactivate any existing board member with the same role
                for board_member in self.chapter_doc.board_members or []:
                    if board_member.chapter_role == role and board_member.is_active:
                        board_member.is_active = 0
                        board_member.to_date = from_date

                        self.log_action(
                            "Deactivated existing unique role assignment",
                            {"volunteer": board_member.volunteer, "role": role, "end_date": from_date},
                        )
        except frappe.DoesNotExistError:
            pass

    def _add_to_chapter_members(self, member_id: str):
        """Add board member to chapter members if not already there"""
        try:
            self.log_action(
                "Starting _add_to_chapter_members",
                {"member_id": member_id, "current_members_count": len(self.chapter_doc.members or [])},
            )

            # Check if already a member
            for member in self.chapter_doc.members or []:
                if member.member == member_id:
                    if not member.enabled:
                        # Re-enable if disabled
                        member.enabled = 1
                        member.leave_reason = None
                        self.log_action("Re-enabled existing chapter member", {"member_id": member_id})
                    else:
                        self.log_action("Member already exists and is enabled", {"member_id": member_id})
                    return

            # Not a member yet, add them
            member_doc = frappe.get_doc("Member", member_id)
            new_member = self.chapter_doc.append(
                "members",
                {
                    "member": member_id,
                    "chapter_join_date": today(),
                    "enabled": 1,
                    "status": "Active",  # Set required status field
                },
            )

            self.log_action(
                "Added new chapter member",
                {
                    "member_id": member_id,
                    "member_full_name": member_doc.full_name,
                    "join_date": today(),
                    "new_members_count": len(self.chapter_doc.members),
                    "new_member_dict": new_member.as_dict()
                    if hasattr(new_member, "as_dict")
                    else str(new_member),
                },
            )

        except Exception as e:
            self.log_action(
                "Error in _add_to_chapter_members", {"member_id": member_id, "error": str(e)}, "error"
            )
            raise

    def _find_active_board_member(self, volunteer: str):
        """Find active board member by volunteer ID"""
        for board_member in self.chapter_doc.board_members or []:
            if board_member.volunteer == volunteer and board_member.is_active:
                return board_member
        return None

    def add_volunteer_assignment_history(self, volunteer_id: str, role: str, start_date: str):
        """Add active assignment to volunteer history when joining board"""
        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        success = AssignmentHistoryManager.add_assignment_history(
            volunteer_id=volunteer_id,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.chapter_name,
            role=role,
            start_date=start_date,
        )

        if success:
            self.log_action(
                "Added volunteer assignment history",
                {"volunteer": volunteer_id, "role": role, "start_date": start_date},
            )
        else:
            self.log_action(
                "Error adding volunteer assignment history",
                {"volunteer": volunteer_id, "role": role},
                "error",
            )

    def update_volunteer_assignment_history(
        self, volunteer_id: str, role: str, start_date: str, end_date: str
    ):
        """Update volunteer assignment history when removing from board"""
        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        success = AssignmentHistoryManager.complete_assignment_history(
            volunteer_id=volunteer_id,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.chapter_name,
            role=role,
            start_date=start_date,
            end_date=end_date,
        )

        if success:
            self.log_action(
                "Updated volunteer assignment history",
                {"volunteer": volunteer_id, "role": role, "start_date": start_date, "end_date": end_date},
            )
        else:
            self.log_action(
                "Error updating volunteer assignment history",
                {"volunteer": volunteer_id, "role": role},
                "error",
            )

    def _notify_board_member_added(self, volunteer: str, role: str):
        """Send notification when a volunteer is added to the board"""
        try:
            volunteer_doc = frappe.get_doc("Volunteer", volunteer)

            if not volunteer_doc.member:
                return

            member_doc = frappe.get_doc("Member", volunteer_doc.member)

            if not member_doc.email:
                return

            context = {
                "member": member_doc,
                "volunteer": volunteer_doc,
                "chapter": self.chapter_doc,
                "role": role,
            }

            self.send_notification(
                "board_member_added",
                [member_doc.email],
                context,
                f"Board Role Assignment: {self.chapter_name}",
            )

        except Exception as e:
            self.log_action(
                "Failed to send board member added notification",
                {"volunteer": volunteer, "error": str(e)},
                "error",
            )

    def _notify_board_member_removed(self, volunteer: str):
        """Send notification when a volunteer is removed from the board"""
        try:
            volunteer_doc = frappe.get_doc("Volunteer", volunteer)

            if not volunteer_doc.member:
                return

            member_doc = frappe.get_doc("Member", volunteer_doc.member)

            if not member_doc.email:
                return

            context = {"member": member_doc, "volunteer": volunteer_doc, "chapter": self.chapter_doc}

            self.send_notification(
                "board_member_removed", [member_doc.email], context, f"Board Role Ended: {self.chapter_name}"
            )

        except Exception as e:
            self.log_action(
                "Failed to send board member removed notification",
                {"volunteer": volunteer, "error": str(e)},
                "error",
            )

    def _notify_role_transition(self, volunteer: str, old_role: str, new_role: str):
        """Send notification for role transition"""
        try:
            volunteer_doc = frappe.get_doc("Volunteer", volunteer)

            if not volunteer_doc.member:
                return

            member_doc = frappe.get_doc("Member", volunteer_doc.member)

            if not member_doc.email:
                return

            context = {
                "member": member_doc,
                "volunteer": volunteer_doc,
                "chapter": self.chapter_doc,
                "old_role": old_role,
                "new_role": new_role,
            }

            self.send_notification(
                "board_role_transition", [member_doc.email], context, f"Role Transition: {self.chapter_name}"
            )

        except Exception as e:
            self.log_action(
                "Failed to send role transition notification",
                {"volunteer": volunteer, "old_role": old_role, "new_role": new_role, "error": str(e)},
                "error",
            )

    def _is_chair_role(self, role_name: str) -> bool:
        """Check if a role is a chair role"""
        if not role_name:
            return False

        try:
            role = frappe.get_doc("Chapter Role", role_name)
            return role.is_chair and role.is_active
        except frappe.DoesNotExistError:
            return False

    def _get_recent_board_changes(self, days: int = 30) -> List[Dict]:
        """Get recent board changes"""
        cutoff_date = add_days(today(), -days)
        changes = []

        for board_member in self.chapter_doc.board_members or []:
            # Check for recent additions
            if board_member.from_date and getdate(board_member.from_date) >= getdate(cutoff_date):
                changes.append(
                    {
                        "type": "addition",
                        "volunteer_name": board_member.volunteer_name,
                        "role": board_member.chapter_role,
                        "date": board_member.from_date,
                    }
                )

            # Check for recent removals
            if (
                board_member.to_date
                and getdate(board_member.to_date) >= getdate(cutoff_date)
                and not board_member.is_active
            ):
                changes.append(
                    {
                        "type": "removal",
                        "volunteer_name": board_member.volunteer_name,
                        "role": board_member.chapter_role,
                        "date": board_member.to_date,
                    }
                )

        # Sort by date
        changes.sort(key=lambda x: x["date"], reverse=True)
        return changes[:10]  # Return most recent 10 changes
