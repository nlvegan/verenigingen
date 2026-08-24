# verenigingen/verenigingen/doctype/chapter/managers/boardmanager.py
import json
from typing import Dict, List, Optional

import frappe
from frappe import STANDARD_USERS, _
from frappe.utils import add_days, getdate, today

from verenigingen.utils.constants import Roles
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS

from .base_manager import BaseManager


class BoardAccessWithdrawalError(frappe.ValidationError):
    """A board seat was vacated but the access it conferred is still attached to the user.

    Deliberately not swallowed like the other per-member board failures: a failed
    *grant* fails safe (nobody gains anything), a failed *revocation* does not — it
    leaves standing access behind a UI that reports the seat as gone.
    """


class BoardManager(BaseManager):
    """Manager for chapter board member operations"""

    def __init__(self, chapter_doc):
        super().__init__(chapter_doc)
        self.volunteer_cache = {}

    def _save_chapter_with_board_changes(self, operation_description: str) -> bool:
        """
        Save chapter document with board member changes using robust operations.

        Args:
            operation_description: Description of the board operation for audit purposes

        Returns:
            bool: True if successful, False otherwise
        """
        result = secure_document_operation(
            operation="update_child_table",
            doc=self.chapter_doc,
            justification=f"Board member operation: {operation_description}",
            required_permissions=["Chapter:write"],
            allow_system_user=True,  # Allow system user for automated board operations
            bypass_validations=["link_validation"],  # Allow bypass of problematic references
        )

        if not result.success:
            frappe.log_error(
                f"Failed board operation '{operation_description}' on chapter {self.chapter_doc.name}: {'; '.join(result.errors)}",
                "Board Manager Operation Failed",
            )
            return False

        return True

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

            # Save chapter with robust child table operations
            success = self._save_chapter_with_board_changes(f"Add board member {volunteer} with role {role}")

            if not success:
                return {
                    "success": False,
                    "message": "Failed to add board member - see error logs for details",
                }

            # Assignment history is handled by validation sync (handle_board_member_additions)

            # Create audit comment
            self.create_comment(
                "Info",
                _("Added {0} as {1} starting {2}").format(volunteer_doc.volunteer_name, role, from_date),
            )

            # Send notification
            if notify:
                self.chapter_doc.communication_manager.notify_board_member_added(volunteer, role)

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

            # Save chapter with robust operations
            success = self._save_chapter_with_board_changes(
                f"Remove board member {board_member.volunteer} from role {board_member.chapter_role}"
            )
            if not success:
                return {
                    "success": False,
                    "message": "Failed to remove board member - see error logs for details",
                }

            # Assignment history is handled by validation sync (handle_board_member_modifications)

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
                self.chapter_doc.communication_manager.notify_board_member_removed(volunteer)

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
                            self.chapter_doc.volunteer_integration_manager.update_volunteer_assignment_history(
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

                except NON_RESUMABLE_DB_ERRORS:
                    # Not a per-member problem, so it must not be collected as one.
                    # A 1213 has discarded the whole transaction and a 1205 has left it
                    # half-applied, which means the members already processed in this
                    # loop describe writes that either did not survive or cannot be
                    # reasoned about. Appending to `errors` here is the worse of this
                    # method's two swallow points: the method still returns
                    # `success: True`, so a deadlock during a privilege change is
                    # reported to the caller as a partial success. Same call
                    # `_log_or_reraise` makes for a single member.
                    raise
                except Exception as e:
                    errors.append(
                        f"Error processing volunteer {member_data.get('volunteer', 'unknown')}: {str(e)}"
                    )

            # Save the chapter document with robust operations
            success = self._save_chapter_with_board_changes("Bulk board member removal")
            if not success:
                errors.append("Failed to save chapter after bulk removal - see error logs for details")

            self.log_action(
                "Bulk board member removal",
                {"processed": processed_count, "errors": len(errors), "total_requested": len(board_members)},
            )

            return {"success": True, "processed": processed_count, "errors": errors}

        except NON_RESUMABLE_DB_ERRORS:
            # Re-raised BEFORE log_action, which would itself be a write issued on the
            # transaction the error has already destroyed. The structured failure below
            # is wrong in both directions for a non-resumable error: it tells the caller
            # "this operation did not happen", inviting a retry inside a transaction
            # that no longer exists, and `processed` counts writes the server discarded.
            # See utils/transaction_errors for what each error destroys.
            raise
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
                            self.chapter_doc.volunteer_integration_manager.update_volunteer_assignment_history(
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

                except NON_RESUMABLE_DB_ERRORS:
                    # Not a per-member problem, so it must not be collected as one.
                    # A 1213 has discarded the whole transaction and a 1205 has left it
                    # half-applied, which means the members already processed in this
                    # loop describe writes that either did not survive or cannot be
                    # reasoned about. Appending to `errors` here is the worse of this
                    # method's two swallow points: the method still returns
                    # `success: True`, so a deadlock during a privilege change is
                    # reported to the caller as a partial success. Same call
                    # `_log_or_reraise` makes for a single member.
                    raise
                except Exception as e:
                    errors.append(
                        f"Error processing volunteer {member_data.get('volunteer', 'unknown')}: {str(e)}"
                    )

            # Save the chapter document with robust operations
            success = self._save_chapter_with_board_changes("Bulk board member deactivation")
            if not success:
                errors.append("Failed to save chapter after bulk deactivation - see error logs for details")

            self.log_action(
                "Bulk board member deactivation",
                {"processed": processed_count, "errors": len(errors), "total_requested": len(board_members)},
            )

            return {"success": True, "processed": processed_count, "errors": errors}

        except NON_RESUMABLE_DB_ERRORS:
            # As in bulk_remove_board_members: re-raise before the log write, and do not
            # hand back a structured failure describing a transaction that is gone.
            raise
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
                self.chapter_doc.volunteer_integration_manager.update_volunteer_assignment_history(
                    board_member.volunteer,
                    old_board_member.chapter_role,  # Use old role
                    board_member.from_date,
                    change_date,
                )

                # Start new role assignment
                self.chapter_doc.volunteer_integration_manager.add_volunteer_assignment_history(
                    board_member.volunteer, board_member.chapter_role, change_date  # Use new role
                )

                # Recalculate role profile (may change if chapter uses role-specific
                # profiles). Deferred: the new chapter_role is not in the database yet.
                self._defer_board_access_recalculation(board_member.volunteer)

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
                self.chapter_doc.volunteer_integration_manager.update_volunteer_assignment_history(
                    board_member.volunteer,
                    board_member.chapter_role,
                    board_member.from_date,
                    board_member.to_date,
                )

                # Withdraw the Frappe role and recalculate the role profile once the
                # deactivation is in the database (see _defer_board_access_recalculation).
                self._defer_board_access_recalculation(board_member.volunteer)

                self.log_action(
                    "Deactivated board member",
                    {
                        "volunteer": board_member.volunteer,
                        "volunteer_name": board_member.volunteer_name,
                        "role": board_member.chapter_role,
                        "end_date": board_member.to_date,
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
                self.chapter_doc.volunteer_integration_manager.update_volunteer_assignment_history(
                    old_board_member.volunteer,
                    old_board_member.chapter_role,
                    old_board_member.from_date,
                    end_date,
                )

                # Withdraw the Frappe role and recalculate the role profile once the row
                # is really gone (see _defer_board_access_recalculation).
                self._defer_board_access_recalculation(old_board_member.volunteer)

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
            # For new chapters, add all active board members to history + assign roles
            for board_member in self.chapter_doc.board_members or []:
                if board_member.is_active and board_member.volunteer:
                    self.chapter_doc.volunteer_integration_manager.add_volunteer_assignment_history(
                        board_member.volunteer, board_member.chapter_role, board_member.from_date
                    )
                    try:
                        board_member.assign_board_member_role()
                    except Exception as e:
                        self._log_or_reraise(
                            "Failed to assign board member role",
                            {"volunteer": board_member.volunteer},
                            e,
                        )
            return

        # The `members`-table half of seating -- _add_to_chapter_members -- is NOT here.
        # It runs in its own earlier pass, seat_board_members_as_chapter_members(). See
        # that method for why.
        for board_member in self._newly_seated_board_members(old_doc):
            # Add volunteer assignment history
            self.chapter_doc.volunteer_integration_manager.add_volunteer_assignment_history(
                board_member.volunteer, board_member.chapter_role, board_member.from_date
            )

            # Assign Frappe role and role profile to the volunteer's user account.
            # Child table after_insert doesn't fire when rows are added via parent save,
            # so we call this explicitly here instead.
            try:
                board_member.assign_board_member_role()
            except Exception as e:
                self._log_or_reraise(
                    "Failed to assign board member role",
                    {"volunteer": board_member.volunteer},
                    e,
                )

            # Defer role-profile sync until after the Chapter (and its
            # board_members child rows) are persisted. handle_board_member_additions
            # runs during validate/before_save, so the new Chapter Board Member row
            # is NOT yet in the database. get_board_member_profiles() queries
            # `tabChapter Board Member`, so running the sync now would compute a
            # non-board profile and overwrite the "Verenigingen Chapter Board Member"
            # role that assign_board_member_role() just added — silently dropping it.
            self._defer_board_access_recalculation(board_member.volunteer)

    def seat_board_members_as_chapter_members(self, old_doc):
        """Auto-add newly seated board members to the chapter's `members` table.

        Split out of handle_board_member_additions and run FIRST, before the member
        handlers, for two reasons that point the same way:

        1. **Correctness.** handle_member_additions diffs chapter_doc.members against
           old_doc.members *when it runs*. An append that lands after that diff gets a
           `members` row and no Chapter Membership History row at all. That is what
           #459's first attempt did by moving the whole board group after the member
           group. Guarded by
           tests/unit/test_board_seating_chapter_membership.py.
        2. **Lock ordering.** This pass takes no row lock of its own -- it appends to an
           in-memory child table and reads a Volunteer by primary key -- so it is free
           to run before everything. The locking work then happens in one canonical
           order: member handlers lock Member (ChapterMembershipHistoryManager), board
           handlers lock Volunteer (AssignmentHistoryManager). #459.

        A `members` mutation belongs with the member group anyway; it only ever lived in
        the board handler because that is where the trigger for it is.
        """
        if not old_doc:
            return

        for board_member in self._newly_seated_board_members(old_doc):
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
                self._log_or_reraise(
                    "Failed to auto-add board member to chapter members",
                    {"volunteer": board_member.volunteer},
                    e,
                )

    def _newly_seated_board_members(self, old_doc):
        """Yield the board rows this save genuinely seats: new rows and reactivations.

        Look up old board rows by row identity (name) so a role change on an
        existing row is NOT mistaken for a brand-new member. Keying on
        (volunteer, role) treated a role change as a new addition, so the new
        role's assignment history was added here in addition to
        handle_board_member_changes() — creating two Active entries for the
        new role (the differing start_date slipped past the dedup).

        Role changes on an existing active row are handled by
        handle_board_member_changes(), not here.

        Shared by the two passes that act on a seating -- the `members` append and the
        assignment history / role grant. They run at different points in the save
        (see seat_board_members_as_chapter_members) and MUST agree on which rows are
        new; two copies of this diff that drift apart would seat a member with no
        history, or write history for a member never seated.
        """
        old_board_members_by_name = {bm.name: bm for bm in old_doc.board_members if bm.name}

        for board_member in self.chapter_doc.board_members or []:
            old_board_member = old_board_members_by_name.get(board_member.name) if board_member.name else None
            is_new_row = old_board_member is None
            is_reactivation = old_board_member is not None and not old_board_member.is_active
            if board_member.is_active and board_member.volunteer and (is_new_row or is_reactivation):
                yield board_member

    def _log_or_reraise(self, action: str, details: Dict, error: Exception) -> None:
        """Log a per-member failure and continue, unless the transaction itself is broken.

        Seating or unseating a board member rewrites the volunteer's ``User.roles`` child
        table, which issues a ``DELETE FROM tabHas Role WHERE parent=... AND name NOT IN
        (...)``. Under contention that statement can lose a deadlock (1213) or a lock-wait
        (1205). Continuing afterwards is the bug: the Chapter save reports success while
        subsequent statements run against state the server discarded, so the board member
        silently does not exist afterwards. See ``utils/transaction_errors`` for exactly
        what each error destroys and why neither is resumable.

        Everything else -- a missing User, a permission refusal, a bad Volunteer link -- is
        genuinely per-member and is logged and skipped, so one bad volunteer cannot block
        seating the rest of the board.
        """
        if isinstance(error, NON_RESUMABLE_DB_ERRORS):
            raise error
        self.log_action(action, {**details, "error": str(error)}, "error")

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
                    "new_member_dict": (
                        new_member.as_dict() if hasattr(new_member, "as_dict") else str(new_member)
                    ),
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

    def _is_chair_role(self, role_name: str) -> bool:
        """Check if a role is a chair role"""
        if not role_name:
            return False

        try:
            role = frappe.get_doc("Chapter Role", role_name)
            return role.is_chair and role.is_active
        except frappe.DoesNotExistError:
            return False

    def _defer_board_access_recalculation(self, volunteer_name: str):
        """Queue a volunteer's board access to be recalculated after this save.

        Every board change — seating, unseating, deactivating, changing role — is
        applied to the in-memory child table during validate(), so at that point the
        database still describes the *previous* board. Both halves of the derived
        access read the database:

        - get_board_member_profiles() queries `tabChapter Board Member`, so
          calculate_user_role_profile() still returns the old profile and
          sync_user_role_profile() reports changed=False;
        - withdraw_board_member_role_if_unseated() counts live seats there too.

        Deferring to Chapter.on_update (_flush_deferred_board_profile_syncs) is the
        only frame in the save where those reads are truthful. Additions were deferred
        for this reason already; removals were not, which is why vacating a seat never
        withdrew the board role profile (issue #211).
        """
        if not volunteer_name:
            return
        if not hasattr(self.chapter_doc, "_pending_board_profile_syncs"):
            self.chapter_doc._pending_board_profile_syncs = []
        if volunteer_name not in self.chapter_doc._pending_board_profile_syncs:
            self.chapter_doc._pending_board_profile_syncs.append(volunteer_name)

    def flush_pending_board_profile_syncs(self):
        """Recalculate deferred board access for everyone whose seat changed in this save.

        Called from Chapter.on_update() once the Chapter Board Member child rows are
        persisted, so get_board_member_profiles() can see them and compute the correct
        role profile — and, for anyone left without a seat, so the Frappe role can be
        withdrawn from a database that agrees they no longer sit on any board.

        Order matters. The profile is applied first because a User carrying a board
        role profile has its `roles` child table reset to that profile's roles on every
        save (User.populate_role_profile_roles), which would immediately undo a role
        removal performed before it.
        """
        pending = getattr(self.chapter_doc, "_pending_board_profile_syncs", None)
        if not pending:
            return
        # Clear first so a re-entrant save doesn't double-process.
        self.chapter_doc._pending_board_profile_syncs = []
        for volunteer_name in pending:
            self._sync_role_profile_for_volunteer(volunteer_name)
            self._withdraw_board_role_if_unseated(volunteer_name)
            self._assert_board_access_withdrawn(volunteer_name)

    def _withdraw_board_role_if_unseated(self, volunteer_name: str):
        """Drop the Frappe board role from a volunteer who no longer holds a seat.

        A no-op for the additions path (the volunteer demonstrably has a live seat),
        so the whole pending list can go through it without branching on why each
        entry was queued.
        """
        from verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member import (
            withdraw_board_member_role_if_unseated,
        )

        try:
            # No exclude_row: the save has persisted the change, so every row the query
            # can still see is a seat the volunteer genuinely holds.
            withdraw_board_member_role_if_unseated(volunteer_name)
        except Exception as e:
            self._log_or_reraise("Failed to withdraw board member role", {"volunteer": volunteer_name}, e)

    def _assert_board_access_withdrawn(self, volunteer_name: str):
        """Post-condition: a volunteer with no seat left must not still hold board access.

        Only checked for a volunteer who now sits on no active board at all, so the
        additions path and anyone who kept another seat never reach the raise.

        This is deliberately louder than the rest of this manager. _log_or_reraise()
        logs and continues, which is right for a failed *grant* — nobody gains access
        from it. A failed *withdrawal* is the opposite: the seat disappears from the
        UI while the role profile and its permissions stay attached, and nothing in
        the removal's return value says otherwise. Raising aborts the Chapter save, so
        the board record and the access it implies stay consistent and the operator
        gets told, instead of the removal silently reporting success.
        """
        from verenigingen.services.member.account.user_role_profile_calculator import (
            calculate_user_role_profile,
            get_user_role_profiles,
        )

        if frappe.db.count("Chapter Board Member", {"volunteer": volunteer_name, "is_active": 1}):
            return  # Still seated somewhere: the access is earned, not leaked.

        member = frappe.db.get_value("Volunteer", volunteer_name, "member")
        user = frappe.db.get_value("Member", member, "user") if member else None
        if not user:
            return  # No account, no access.
        if not frappe.db.get_value("User", user, "enabled"):
            return  # A disabled account cannot use what it still holds; sync skips it too.
        if user in STANDARD_USERS:
            # frappe.get_roles("Administrator") returns every role that exists, and
            # populate_role_profile_roles() refuses to touch these accounts anyway, so
            # there is nothing here to read as a leaked board grant.
            return

        # frappe.get_roles() memoises per user in frappe.local and this save rewrote
        # User.roles underneath it.
        frappe.clear_cache(user=user)

        outstanding = []
        if Roles.CHAPTER_BOARD_MEMBER in frappe.get_roles(user):
            outstanding.append(_("role '{0}'").format(Roles.CHAPTER_BOARD_MEMBER))

        applied = set(get_user_role_profiles(user))
        expected = calculate_user_role_profile(user)
        for profile in self._board_conferred_profiles():
            # `!= expected` keeps a chapter that configures an ordinary profile (say
            # Verenigingen Volunteer) as its board profile from reporting the correct
            # post-withdrawal profile as a leak.
            if profile in applied and profile != expected:
                outstanding.append(_("role profile '{0}'").format(profile))

        if not outstanding:
            return

        # File logger, not log_action(level="error"): that writes an Error Log row,
        # and the exception below aborts the save whose transaction the row would
        # live in, so it would be rolled back with it. The log file survives.
        frappe.logger().error(
            f"Chapter {self.chapter_name}: board access {', '.join(outstanding)} survived the "
            f"seat withdrawal for volunteer {volunteer_name} (user {user})"
        )
        raise BoardAccessWithdrawalError(
            _(
                "Board membership for {0} ended but {1} is still attached to {2} — access was not withdrawn."
            ).format(volunteer_name, ", ".join(outstanding), user)
        )

    def _board_conferred_profiles(self) -> set:
        """Role profiles this chapter's board seats can confer."""
        from verenigingen.services.member.account.user_role_profile_calculator import (
            PROFILE_BOARD_MEMBER,
        )

        profiles = {PROFILE_BOARD_MEMBER}
        if self.chapter_doc.get("default_board_role_profile"):
            profiles.add(self.chapter_doc.default_board_role_profile)
        if self.chapter_doc.get("enable_board_role_specific_profiles"):
            for mapping in self.chapter_doc.get("board_role_specific_profiles") or []:
                if mapping.role_profile:
                    profiles.add(mapping.role_profile)
        return profiles

    def _sync_role_profile_for_volunteer(self, volunteer_name: str):
        """Recalculate and apply the correct role profile for a volunteer's user account.

        Looks up volunteer → member → member.user, then calls auto_sync_on_role_change()
        which derives the correct profile from the user's current organizational roles.
        Per-volunteer failures are logged and skipped; a broken transaction is
        re-raised (see _log_or_reraise).
        """
        try:
            member_name = frappe.db.get_value("Volunteer", volunteer_name, "member")
            if not member_name:
                return
            user = frappe.db.get_value("Member", member_name, "user")
            if not user:
                return
            from verenigingen.utils.user_role_profile_calculator import auto_sync_on_role_change

            auto_sync_on_role_change(user)
        except Exception as e:
            self._log_or_reraise(
                "Failed to sync role profile for volunteer", {"volunteer": volunteer_name}, e
            )

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
