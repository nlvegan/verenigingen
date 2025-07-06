# verenigingen/verenigingen/doctype/chapter/managers/volunteer_integration_manager.py

from typing import Dict, List

import frappe
from frappe.utils import getdate, now, today

from .base_manager import BaseManager


class VolunteerIntegrationManager(BaseManager):
    """Manager for volunteer system integration and assignment history"""

    def __init__(self, chapter_doc):
        super().__init__(chapter_doc)
        self.assignment_cache = {}
        self.volunteer_cache = {}

    def add_volunteer_assignment_history(
        self, volunteer_id: str, role: str, start_date: str, assignment_type: str = "Board Position"
    ) -> bool:
        """
        Add active assignment to volunteer history when joining board

        Args:
            volunteer_id: Volunteer ID
            role: Chapter role
            start_date: Assignment start date
            assignment_type: Type of assignment

        Returns:
            bool: Whether assignment was added successfully
        """
        try:
            volunteer = frappe.get_doc("Volunteer", volunteer_id)

            # Check if this assignment already exists as active
            for assignment in volunteer.assignment_history or []:
                if (
                    assignment.reference_doctype == "Chapter"
                    and assignment.reference_name == self.chapter_name
                    and assignment.role == role
                    and assignment.status == "Active"
                ):
                    self.log_action(
                        "Assignment already exists as active",
                        {"volunteer": volunteer_id, "role": role, "chapter": self.chapter_name},
                        "warning",
                    )
                    return True  # Already exists, consider it successful

            # Add new active assignment
            volunteer.append(
                "assignment_history",
                {
                    "assignment_type": assignment_type,
                    "reference_doctype": "Chapter",
                    "reference_name": self.chapter_name,
                    "role": role,
                    "start_date": start_date,
                    "status": "Active",
                },
            )

            volunteer.save(ignore_permissions=True)

            self.log_action(
                "Added volunteer assignment history",
                {
                    "volunteer": volunteer_id,
                    "volunteer_name": volunteer.volunteer_name,
                    "role": role,
                    "start_date": start_date,
                    "assignment_type": assignment_type,
                },
            )

            # Clear cache
            self._clear_volunteer_cache(volunteer_id)

            return True

        except Exception as e:
            self.log_action(
                "Error adding volunteer assignment history",
                {"volunteer": volunteer_id, "role": role, "error": str(e)},
                "error",
            )
            return False

    def update_volunteer_assignment_history(
        self, volunteer_id: str, role: str, start_date: str, end_date: str
    ) -> bool:
        """
        Update volunteer assignment history when removing from board

        Args:
            volunteer_id: Volunteer ID
            role: Chapter role
            start_date: Assignment start date
            end_date: Assignment end date

        Returns:
            bool: Whether assignment was updated successfully
        """
        try:
            volunteer = frappe.get_doc("Volunteer", volunteer_id)

            # First, look for any active assignment for this chapter and role
            existing_active_assignment = None
            for assignment in volunteer.assignment_history or []:
                if (
                    assignment.reference_doctype == "Chapter"
                    and assignment.reference_name == self.chapter_name
                    and assignment.role == role
                    and assignment.status == "Active"
                ):
                    existing_active_assignment = assignment
                    break

            if existing_active_assignment:
                # Update the active assignment to completed
                existing_active_assignment.end_date = end_date
                existing_active_assignment.status = "Completed"

                self.log_action(
                    "Updated active assignment to completed",
                    {"volunteer": volunteer_id, "role": role, "end_date": end_date},
                )
            else:
                # Look for assignment by exact start date match (backup search)
                existing_assignment_by_date = None
                for assignment in volunteer.assignment_history or []:
                    if (
                        assignment.reference_doctype == "Chapter"
                        and assignment.reference_name == self.chapter_name
                        and assignment.role == role
                        and getdate(assignment.start_date) == getdate(start_date)
                    ):
                        existing_assignment_by_date = assignment
                        break

                if existing_assignment_by_date:
                    # Update existing assignment
                    existing_assignment_by_date.end_date = end_date
                    existing_assignment_by_date.status = "Completed"

                    self.log_action(
                        "Updated existing assignment by date",
                        {
                            "volunteer": volunteer_id,
                            "role": role,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    )
                else:
                    # No existing assignment found, create a new completed one
                    volunteer.append(
                        "assignment_history",
                        {
                            "assignment_type": "Board Position",
                            "reference_doctype": "Chapter",
                            "reference_name": self.chapter_name,
                            "role": role,
                            "start_date": start_date,
                            "end_date": end_date,
                            "status": "Completed",
                        },
                    )

                    self.log_action(
                        "Added new completed assignment",
                        {
                            "volunteer": volunteer_id,
                            "role": role,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    )

            volunteer.save(ignore_permissions=True)

            # Clear cache
            self._clear_volunteer_cache(volunteer_id)

            return True

        except Exception as e:
            self.log_action(
                "Error updating volunteer assignment history",
                {"volunteer": volunteer_id, "role": role, "error": str(e)},
                "error",
            )
            return False

    def sync_board_members_with_volunteer_system(self) -> Dict:
        """
        Synchronize chapter board members with volunteer system

        Returns:
            Dict with sync results
        """
        try:
            sync_stats = {
                "volunteers_processed": 0,
                "assignments_added": 0,
                "assignments_updated": 0,
                "errors": [],
                "warnings": [],
            }

            # Process each board member
            for board_member in self.chapter_doc.board_members or []:
                try:
                    sync_stats["volunteers_processed"] += 1

                    if not board_member.volunteer:
                        sync_stats["warnings"].append("Board member missing volunteer ID")
                        continue

                    # Check if volunteer exists
                    if not frappe.db.exists("Volunteer", board_member.volunteer):
                        sync_stats["errors"].append(f"Volunteer {board_member.volunteer} not found")
                        continue

                    if board_member.is_active:
                        # Ensure active assignment exists
                        result = self.add_volunteer_assignment_history(
                            board_member.volunteer, board_member.chapter_role, board_member.from_date
                        )
                        if result:
                            sync_stats["assignments_added"] += 1
                    else:
                        # Ensure assignment is marked as completed
                        if board_member.to_date:
                            result = self.update_volunteer_assignment_history(
                                board_member.volunteer,
                                board_member.chapter_role,
                                board_member.from_date,
                                board_member.to_date,
                            )
                            if result:
                                sync_stats["assignments_updated"] += 1

                except Exception as e:
                    sync_stats["errors"].append(
                        f"Error processing volunteer {board_member.volunteer}: {str(e)}"
                    )

            self.log_action("Volunteer system sync completed", sync_stats)

            return {"success": True, "stats": sync_stats}

        except Exception as e:
            self.log_action("Critical error in volunteer system sync", {"error": str(e)}, "error")
            return {
                "success": False,
                "error": str(e),
                "stats": sync_stats if "sync_stats" in locals() else {},
            }

    def get_volunteer_assignment_history(self, volunteer_id: str) -> List[Dict]:
        """
        Get assignment history for a volunteer in this chapter

        Args:
            volunteer_id: Volunteer ID

        Returns:
            List of assignment records
        """
        try:
            if volunteer_id in self.assignment_cache:
                return self.assignment_cache[volunteer_id]

            volunteer = frappe.get_doc("Volunteer", volunteer_id)
            chapter_assignments = []

            for assignment in volunteer.assignment_history or []:
                if (
                    assignment.reference_doctype == "Chapter"
                    and assignment.reference_name == self.chapter_name
                ):
                    chapter_assignments.append(
                        {
                            "assignment_type": assignment.assignment_type,
                            "role": assignment.role,
                            "start_date": assignment.start_date,
                            "end_date": assignment.end_date,
                            "status": assignment.status,
                            "duration_days": self._calculate_assignment_duration(
                                assignment.start_date, assignment.end_date
                            ),
                        }
                    )

            # Sort by start date
            chapter_assignments.sort(key=lambda x: x["start_date"], reverse=True)

            # Cache result
            self.assignment_cache[volunteer_id] = chapter_assignments

            return chapter_assignments

        except Exception as e:
            self.log_action(
                "Error getting volunteer assignment history",
                {"volunteer": volunteer_id, "error": str(e)},
                "error",
            )
            return []

    def get_chapter_volunteer_statistics(self) -> Dict:
        """
        Get volunteer-related statistics for the chapter

        Returns:
            Dict with volunteer statistics
        """
        try:
            stats = {
                "total_volunteers": 0,
                "active_volunteers": 0,
                "volunteers_with_members": 0,
                "assignment_history_count": 0,
                "average_tenure_days": 0,
                "role_distribution": {},
                "status_distribution": {},
            }

            volunteer_ids = set()
            tenure_days = []

            # Collect volunteer data from board members
            for board_member in self.chapter_doc.board_members or []:
                if board_member.volunteer:
                    volunteer_ids.add(board_member.volunteer)

                    if board_member.is_active:
                        stats["active_volunteers"] += 1

                        # Track role distribution
                        role = board_member.chapter_role
                        if role:
                            stats["role_distribution"][role] = stats["role_distribution"].get(role, 0) + 1

                    # Calculate tenure
                    if board_member.from_date:
                        end_date = board_member.to_date if board_member.to_date else today()
                        try:
                            tenure = (getdate(end_date) - getdate(board_member.from_date)).days
                            tenure_days.append(tenure)
                        except Exception:
                            pass

            stats["total_volunteers"] = len(volunteer_ids)

            # Check which volunteers have associated members
            for volunteer_id in volunteer_ids:
                try:
                    volunteer = frappe.get_doc("Volunteer", volunteer_id)
                    if volunteer.member:
                        stats["volunteers_with_members"] += 1

                    # Count assignment history entries
                    history = self.get_volunteer_assignment_history(volunteer_id)
                    stats["assignment_history_count"] += len(history)

                    # Track status distribution
                    status = volunteer.status
                    if status:
                        stats["status_distribution"][status] = stats["status_distribution"].get(status, 0) + 1

                except Exception:
                    pass

            # Calculate average tenure
            if tenure_days:
                stats["average_tenure_days"] = sum(tenure_days) // len(tenure_days)

            return stats

        except Exception as e:
            self.log_action("Error calculating volunteer statistics", {"error": str(e)}, "error")
            return {"error": str(e)}

    def validate_volunteer_board_consistency(self) -> Dict:
        """
        Validate consistency between board members and volunteer assignments

        Returns:
            Dict with validation results
        """
        try:
            issues = []
            warnings = []

            for board_member in self.chapter_doc.board_members or []:
                if not board_member.volunteer:
                    issues.append(f"Board member {board_member.volunteer_name} has no volunteer ID")
                    continue

                # Check if volunteer exists
                if not frappe.db.exists("Volunteer", board_member.volunteer):
                    issues.append(f"Volunteer {board_member.volunteer} not found in system")  # noqa: E713
                    continue

                # Check assignment history consistency
                assignments = self.get_volunteer_assignment_history(board_member.volunteer)

                if board_member.is_active:
                    # Should have an active assignment
                    active_assignments = [a for a in assignments if a["status"] == "Active"]
                    if not active_assignments:
                        warnings.append(
                            f"Active board member {board_member.volunteer_name} has no active assignment record"
                        )
                else:
                    # Should have completed assignment
                    if board_member.to_date:
                        matching_assignments = [
                            a
                            for a in assignments
                            if (
                                a["role"] == board_member.chapter_role
                                and getdate(a.get("start_date")) == getdate(board_member.from_date)
                            )
                        ]
                        if not matching_assignments:
                            warnings.append(
                                f"Inactive board member {board_member.volunteer_name} has no matching assignment record"
                            )

            return {
                "is_consistent": len(issues) == 0,
                "issues": issues,
                "warnings": warnings,
                "total_board_members": len(self.chapter_doc.board_members or []),
                "checked_date": now(),
            }

        except Exception as e:
            self.log_action("Error validating volunteer board consistency", {"error": str(e)}, "error")
            return {"is_consistent": False, "error": str(e)}

    def migrate_volunteer_assignments(self) -> Dict:
        """
        Migrate/fix volunteer assignment history for existing board members

        Returns:
            Dict with migration results
        """
        try:
            migration_stats = {
                "board_members_processed": 0,
                "assignments_created": 0,
                "assignments_fixed": 0,
                "errors": [],
            }

            for board_member in self.chapter_doc.board_members or []:
                try:
                    migration_stats["board_members_processed"] += 1

                    if not board_member.volunteer:
                        continue

                    # Check current assignment status
                    assignments = self.get_volunteer_assignment_history(board_member.volunteer)

                    if board_member.is_active:
                        # Ensure active assignment exists
                        active_assignments = [a for a in assignments if a["status"] == "Active"]
                        if not active_assignments:
                            success = self.add_volunteer_assignment_history(
                                board_member.volunteer, board_member.chapter_role, board_member.from_date
                            )
                            if success:
                                migration_stats["assignments_created"] += 1
                    else:
                        # Ensure completed assignment exists
                        if board_member.to_date:
                            matching_completed = [
                                a
                                for a in assignments
                                if (
                                    a["role"] == board_member.chapter_role
                                    and a["status"] == "Completed"
                                    and getdate(a.get("start_date")) == getdate(board_member.from_date)
                                )
                            ]
                            if not matching_completed:
                                success = self.update_volunteer_assignment_history(
                                    board_member.volunteer,
                                    board_member.chapter_role,
                                    board_member.from_date,
                                    board_member.to_date,
                                )
                                if success:
                                    migration_stats["assignments_fixed"] += 1

                except Exception as e:
                    migration_stats["errors"].append(
                        f"Error processing {board_member.volunteer_name}: {str(e)}"
                    )

            self.log_action("Volunteer assignment migration completed", migration_stats)

            return {"success": True, "stats": migration_stats}

        except Exception as e:
            self.log_action("Critical error in volunteer assignment migration", {"error": str(e)}, "error")
            return {"success": False, "error": str(e)}

    def cleanup_orphaned_assignments(self) -> Dict:
        """
        Clean up orphaned volunteer assignments that don't match current board

        Returns:
            Dict with cleanup results
        """
        try:
            cleanup_stats = {
                "volunteers_checked": 0,
                "orphaned_assignments": 0,
                "assignments_cleaned": 0,
                "errors": [],
            }

            # Get all volunteers who have assignments for this chapter
            volunteers_with_assignments = frappe.db.sql(
                """
                SELECT DISTINCT parent
                FROM `tabVolunteer Assignment History`
                WHERE reference_doctype = 'Chapter'
                AND reference_name = %s
            """,
                (self.chapter_name,),
                as_dict=True,
            )

            # Get current board member volunteer IDs
            current_volunteers = {bm.volunteer for bm in self.chapter_doc.board_members or [] if bm.volunteer}

            for volunteer_record in volunteers_with_assignments:
                try:
                    cleanup_stats["volunteers_checked"] += 1
                    volunteer_id = volunteer_record.parent

                    if volunteer_id not in current_volunteers:
                        # This volunteer is no longer on the board
                        volunteer = frappe.get_doc("Volunteer", volunteer_id)

                        # Find active assignments for this chapter
                        for assignment in volunteer.assignment_history or []:
                            if (
                                assignment.reference_doctype == "Chapter"
                                and assignment.reference_name == self.chapter_name
                                and assignment.status == "Active"
                            ):
                                cleanup_stats["orphaned_assignments"] += 1

                                # Mark as completed
                                assignment.status = "Completed"
                                assignment.end_date = today()
                                cleanup_stats["assignments_cleaned"] += 1

                        volunteer.save(ignore_permissions=True)

                except Exception as e:
                    cleanup_stats["errors"].append(
                        f"Error processing volunteer {volunteer_record.parent}: {str(e)}"
                    )

            self.log_action("Orphaned assignment cleanup completed", cleanup_stats)

            return {"success": True, "stats": cleanup_stats}

        except Exception as e:
            self.log_action("Critical error in orphaned assignment cleanup", {"error": str(e)}, "error")
            return {"success": False, "error": str(e)}

    def get_summary(self) -> Dict:
        """
        Get summary of volunteer integration status

        Returns:
            Dict with integration summary
        """
        try:
            stats = self.get_chapter_volunteer_statistics()
            validation = self.validate_volunteer_board_consistency()

            return {
                "volunteer_statistics": stats,
                "consistency_check": validation,
                "integration_health": "Good" if validation.get("is_consistent") else "Issues Found",
                "last_sync": self.get_cached("last_sync_date", "Never"),
                "total_assignment_records": stats.get("assignment_history_count", 0),
            }

        except Exception as e:
            self.log_action("Error generating volunteer integration summary", {"error": str(e)}, "error")
            return {"error": str(e), "integration_health": "Error"}

    # Private helper methods

    def _calculate_assignment_duration(self, start_date: str, end_date: str = None) -> int:
        """Calculate assignment duration in days"""
        try:
            start = getdate(start_date)
            end = getdate(end_date) if end_date else getdate(today())
            return (end - start).days
        except Exception:
            return 0

    def _clear_volunteer_cache(self, volunteer_id: str = None):
        """Clear volunteer-related cache"""
        if volunteer_id:
            self.assignment_cache.pop(volunteer_id, None)
            self.volunteer_cache.pop(volunteer_id, None)
        else:
            self.assignment_cache.clear()
            self.volunteer_cache.clear()

    def _get_volunteer_details(self, volunteer_id: str) -> Dict:
        """Get volunteer details with caching"""
        if volunteer_id not in self.volunteer_cache:
            try:
                volunteer = frappe.get_doc("Volunteer", volunteer_id)
                self.volunteer_cache[volunteer_id] = {
                    "name": volunteer.volunteer_name,
                    "email": volunteer.email,
                    "status": volunteer.status,
                    "member": volunteer.member,
                }
            except Exception:
                self.volunteer_cache[volunteer_id] = {
                    "name": volunteer_id,
                    "email": None,
                    "status": "Unknown",
                    "member": None,
                }

        return self.volunteer_cache[volunteer_id]
