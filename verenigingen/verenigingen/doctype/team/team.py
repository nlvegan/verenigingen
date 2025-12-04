# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import DocType

from verenigingen.events.team_events import (
    emit_team_leadership_changed,
    emit_team_membership_changed,
    emit_team_settings_changed,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    development_only_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.security_decorators import development_only


class Team(Document):
    """
    Clean Team DocType controller with separated concerns.

    This controller focuses only on document lifecycle events
    and delegates business logic to service classes.
    """

    def validate(self):
        """Validate team document"""
        from verenigingen.services.team_service import TeamValidationService

        TeamValidationService().validate_dates(self)
        TeamValidationService().validate_team_members(self)
        TeamValidationService().validate_role_profile_configuration(self)
        self._validate_unique_roles()
        self._update_team_lead()

    def before_save(self):
        """Store document state before save for change tracking"""
        if not self.is_new():
            # Store full document state for proper change tracking
            self._doc_before_save = frappe.get_doc("Team", self.name)
            # Also store snapshot for memory efficiency in simple cases
            self._original_members = self._get_member_snapshot()

    def on_update(self):
        """Handle team member changes with event emission for background processing"""
        if hasattr(self, "_team_member_changes_processed"):
            return  # Prevent recursive calls

        try:
            self._team_member_changes_processed = True

            # Emit events for significant changes to trigger background operations
            if hasattr(self, "_doc_before_save") and self._doc_before_save:
                self._emit_team_change_events(self._doc_before_save)

            # Keep the lightweight immediate operations only
            self._handle_immediate_team_changes()

        finally:
            if hasattr(self, "_team_member_changes_processed"):
                delattr(self, "_team_member_changes_processed")
            # Clean up stored document state
            if hasattr(self, "_doc_before_save"):
                delattr(self, "_doc_before_save")
            if hasattr(self, "_original_members"):
                delattr(self, "_original_members")

    def after_insert(self):
        """Handle initial team member assignments"""
        self.handle_team_member_changes()

    def _get_member_snapshot(self):
        """Get lightweight snapshot of current members"""
        if not self.team_members:
            return {}

        snapshot = {}
        for member in self.team_members:
            if member.volunteer:
                key = (member.volunteer, str(member.from_date))
                snapshot[key] = {
                    "role": member.role,
                    "team_role": member.team_role,
                    "role_type": member.role_type,
                    "is_active": member.is_active,
                    "volunteer_name": member.volunteer_name,
                }
        return snapshot

    def _validate_unique_roles(self):
        """Validate unique role constraints"""
        from verenigingen.services.team_service import TeamService

        TeamService().validate_unique_roles(self)

    def _update_team_lead(self):
        """Auto-populate team_lead field from active Team Leader"""
        current_leader = None

        for member in self.team_members or []:
            if member.is_active and member.team_role and member.volunteer:
                try:
                    team_role_doc = frappe.get_cached_doc("Team Role", member.team_role)
                    if team_role_doc and team_role_doc.is_team_leader:
                        # Get the user associated with this volunteer
                        volunteer_doc = frappe.get_doc("Volunteer", member.volunteer)
                        if volunteer_doc.member:
                            user = frappe.db.get_value("Member", volunteer_doc.member, "user")
                            if user:
                                current_leader = user
                                break
                except frappe.DoesNotExistError:
                    continue

        self.team_lead = current_leader

    def handle_team_member_changes(self):
        """Handle team member changes and update assignment history"""
        if not hasattr(self, "_doc_before_save") or self._doc_before_save is None:
            # For new teams, add all active members to history
            for member in self.team_members or []:
                if member.is_active and member.volunteer:
                    self.add_team_assignment_history(member.volunteer, member.team_role, member.from_date)
            return

        # Get old team members - group by volunteer and from_date (not role)
        old_members_by_volunteer = {}
        for m in self._doc_before_save.team_members or []:
            if m.volunteer:
                key = (m.volunteer, str(m.from_date))
                old_members_by_volunteer[key] = m

        # Check current team members - group by volunteer and from_date
        current_members_by_volunteer = {}
        for m in self.team_members or []:
            if m.volunteer:
                key = (m.volunteer, str(m.from_date))
                current_members_by_volunteer[key] = m

        # Process each current member
        for key, member in current_members_by_volunteer.items():
            volunteer_id, from_date = key

            if key not in old_members_by_volunteer:
                # New member assignment
                if member.is_active:
                    self.add_team_assignment_history(member.volunteer, member.team_role, member.from_date)
            else:
                old_member = old_members_by_volunteer[key]

                # Check for role changes (same volunteer, same from_date, different team_role or role)
                role_changed = (
                    old_member.role != member.role
                    or old_member.team_role != member.team_role
                    or old_member.role_type != member.role_type
                )

                if role_changed and old_member.is_active and member.is_active:
                    # Role changed - complete old assignment and create new one
                    change_date = frappe.utils.today()
                    self.complete_team_assignment_history(
                        old_member.volunteer, old_member.team_role, old_member.from_date, change_date
                    )
                    # Start new assignment with new role using today's date
                    self.add_team_assignment_history(
                        member.volunteer,
                        member.team_role,
                        change_date,  # Use change date, not original from_date
                    )

                # Check if member was reactivated
                elif not old_member.is_active and member.is_active:
                    self.add_team_assignment_history(member.volunteer, member.team_role, member.from_date)
                # Check if member was deactivated
                elif old_member.is_active and not member.is_active:
                    end_date = member.to_date or frappe.utils.today()
                    self.complete_team_assignment_history(
                        member.volunteer, member.team_role, member.from_date, end_date
                    )

        # Find removed assignments
        for key, old_member in old_members_by_volunteer.items():
            if key not in current_members_by_volunteer and old_member.is_active:
                # Member was removed entirely
                end_date = frappe.utils.today()
                self.complete_team_assignment_history(
                    old_member.volunteer, old_member.team_role, old_member.from_date, end_date
                )

    def add_team_assignment_history(self, volunteer_id: str, team_role: str, start_date: str):
        """Add active assignment to volunteer history when joining team"""
        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        # Get the team member to access both team_role and role fields
        team_member = None
        for member in self.team_members:
            if member.volunteer == volunteer_id and str(member.from_date) == str(start_date):
                team_member = member
                break

        if not team_member:
            frappe.logger().warning(f"Could not find team member for volunteer {volunteer_id}")
            return False

        # Create role description using Team Role system
        role_description = self.get_role_description_for_history(team_member)

        success = AssignmentHistoryManager.add_assignment_history(
            volunteer_id=volunteer_id,
            assignment_type="Team",
            reference_doctype="Team",
            reference_name=self.name,
            role=role_description,
            start_date=start_date,
        )

        if success:
            frappe.logger().info(
                f"Added team assignment history for volunteer {volunteer_id}: {role_description}"
            )
        else:
            frappe.logger().error(
                f"Error adding team assignment history for volunteer {volunteer_id}: {role_description}"
            )

        return success

    def complete_team_assignment_history(
        self, volunteer_id: str, team_role: str, start_date: str, end_date: str
    ):
        """Complete volunteer assignment history when leaving team"""
        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        # Get the team member to access both team_role and role fields
        team_member = None
        for member in self.team_members:
            if member.volunteer == volunteer_id and str(member.from_date) == str(start_date):
                team_member = member
                break

        # If not in current members, check the old document
        if not team_member and hasattr(self, "_doc_before_save"):
            for member in self._doc_before_save.team_members or []:
                if member.volunteer == volunteer_id and str(member.from_date) == str(start_date):
                    team_member = member
                    break

        if not team_member:
            # Use team_role as-is if we can't find the member
            role_description = team_role or "Team Member"
        else:
            # Create role description using Team Role system
            role_description = self.get_role_description_for_history(team_member)

        success = AssignmentHistoryManager.complete_assignment_history(
            volunteer_id=volunteer_id,
            assignment_type="Team",
            reference_doctype="Team",
            reference_name=self.name,
            role=role_description,
            start_date=start_date,
            end_date=end_date,
        )

        if success:
            frappe.logger().info(
                f"Completed team assignment history for volunteer {volunteer_id}: {role_description}"
            )
        else:
            frappe.logger().error(
                f"Error completing team assignment history for volunteer {volunteer_id}: {role_description}"
            )

    def get_role_description_for_history(self, team_member):
        """Generate role description for assignment history using Team Role system"""
        role_description = "Team Member"  # Default fallback

        # Get the Team Role name as primary identifier
        if team_member.team_role:
            try:
                team_role_doc = frappe.get_cached_doc("Team Role", team_member.team_role)
                if team_role_doc:
                    role_description = team_role_doc.role_name
            except frappe.DoesNotExistError:
                # Fallback to role_type if Team Role doesn't exist
                role_description = team_member.role_type or "Team Member"
        elif team_member.role_type:
            # Fallback to old role_type system for backwards compatibility
            role_description = team_member.role_type

        # Append additional role description if provided
        if team_member.role and team_member.role.strip():
            role_description = f"{role_description} - {team_member.role}"

        return role_description

    def _handle_team_member_changes_atomic(self):
        """Handle team member changes with proper error handling"""
        try:
            # Transaction already managed by Frappe framework
            # No nested transaction needed - let Frappe handle rollback
            self.handle_team_member_changes()

            # Validate that all assignment history updates succeeded
            self._validate_assignment_history_consistency()

        except Exception as e:
            # Log the error for debugging
            frappe.log_error(f"Team member change failed for {self.name}: {e}", "Team Member Change Error")
            # Re-raise to trigger framework rollback
            raise

    def _validate_assignment_history_consistency(self):
        """Validate that assignment history is consistent after changes"""
        try:
            # Check that active team members have corresponding assignment history
            active_members = [m for m in self.team_members if m.is_active and m.volunteer]

            for member in active_members:
                # Verify assignment history exists for this member (child table in Volunteer)
                history_exists = frappe.db.exists(
                    "Volunteer Assignment",
                    {
                        "parent": member.volunteer,
                        "reference_doctype": "Team",
                        "reference_name": self.name,
                        "status": "Active",
                    },
                )

                if not history_exists:
                    # This indicates a consistency problem - attempt to fix it automatically
                    try:
                        # Try to create the missing assignment history
                        success = self.add_team_assignment_history(
                            member.volunteer,
                            member.team_role or member.role or "Team Member",
                            member.from_date or frappe.utils.today(),
                        )

                        if success:
                            frappe.logger().info(
                                f"✅ Auto-fixed missing assignment history for {member.volunteer_name} in team {self.name}"
                            )
                        else:
                            # Create more informative error message with resolution steps
                            error_msg = (
                                f"Assignment history missing for volunteer '{member.volunteer_name}' "
                                f"in team '{self.name}'. "
                                f"\n\nTo fix this issue manually:\n"
                                f"1. Go to Workspace > Teams > {self.name}\n"
                                f"2. Remove and re-add the volunteer: {member.volunteer_name}\n"
                                f"3. Or run: fix_missing_assignment_history('{self.name}', '{member.volunteer}')\n\n"
                                f"Technical details: Active team member without corresponding Assignment History record"
                            )
                            frappe.log_error(error_msg, "Assignment History - Action Required")

                    except Exception as fix_error:
                        # Fallback to informative error if auto-fix fails
                        error_msg = (
                            f"Assignment history missing for volunteer '{member.volunteer_name}' "
                            f"in team '{self.name}'. Auto-repair failed: {str(fix_error)[:100]}\n\n"
                            f"Manual fix required:\n"
                            f"1. Go to Workspace > Teams > {self.name}\n"
                            f"2. Remove and re-add the volunteer: {member.volunteer_name}\n"
                            f"3. Or run: fix_missing_assignment_history('{self.name}', '{member.volunteer}')"
                        )
                        frappe.log_error(error_msg, "Assignment History - Manual Fix Required")

        except Exception as e:
            # Create informative error message for validation failures
            error_msg = (
                f"Assignment history validation failed for team '{self.name}'. "
                f"Error: {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}\n\n"
                f"This may indicate data consistency issues. "
                f"Consider running team data validation or contact administrator."
            )
            frappe.log_error(error_msg, "Team Assignment History Validation Error")

    def _emit_team_change_events(self, old_doc):
        """Emit events for significant team changes to trigger background processing"""
        try:
            # Detect team membership changes
            self._detect_and_emit_membership_changes(old_doc)

            # Detect settings changes
            self._detect_and_emit_settings_changes(old_doc)

            # Detect leadership changes
            self._detect_and_emit_leadership_changes(old_doc)

        except Exception as e:
            frappe.log_error(
                f"Failed to emit team change events for {self.name}: {str(e)}", "Team Event Emission Error"
            )

    def _detect_and_emit_membership_changes(self, old_doc):
        """Detect and emit team membership changes"""
        # Group by volunteer to detect changes
        old_by_volunteer = {}
        for m in old_doc.team_members or []:
            if m.volunteer:
                key = (m.volunteer, m.from_date)
                old_by_volunteer[key] = m

        new_by_volunteer = {}
        for m in self.team_members or []:
            if m.volunteer:
                key = (m.volunteer, m.from_date)
                new_by_volunteer[key] = m

        # Find added members
        for key, member in new_by_volunteer.items():
            if key not in old_by_volunteer and member.is_active:
                emit_team_membership_changed(
                    self.name,
                    {
                        "volunteer": member.volunteer,
                        "action": "added",
                        "role": member.team_role,
                        "from_date": member.from_date,
                        "changed_by": frappe.session.user,
                    },
                )

        # Find removed members
        for key, old_member in old_by_volunteer.items():
            if key not in new_by_volunteer and old_member.is_active:
                emit_team_membership_changed(
                    self.name,
                    {
                        "volunteer": old_member.volunteer,
                        "action": "removed",
                        "old_role": old_member.team_role,
                        "from_date": old_member.from_date,
                        "to_date": frappe.utils.today(),
                        "changed_by": frappe.session.user,
                    },
                )

        # Find role changes and status changes
        for key, member in new_by_volunteer.items():
            if key in old_by_volunteer:
                old_member = old_by_volunteer[key]

                # Check for role change
                if old_member.team_role != member.team_role and old_member.is_active and member.is_active:
                    emit_team_membership_changed(
                        self.name,
                        {
                            "volunteer": member.volunteer,
                            "action": "role_changed",
                            "role": member.team_role,
                            "old_role": old_member.team_role,
                            "from_date": member.from_date,
                            "changed_by": frappe.session.user,
                        },
                    )

                # Check for status change from active to inactive
                if old_member.is_active and not member.is_active:
                    emit_team_membership_changed(
                        self.name,
                        {
                            "volunteer": member.volunteer,
                            "action": "removed",
                            "old_role": old_member.team_role,
                            "from_date": old_member.from_date,
                            "to_date": frappe.utils.today(),
                            "changed_by": frappe.session.user,
                        },
                    )

                # Check for status change from inactive to active
                elif not old_member.is_active and member.is_active:
                    emit_team_membership_changed(
                        self.name,
                        {
                            "volunteer": member.volunteer,
                            "action": "added",
                            "role": member.team_role,
                            "from_date": member.from_date,
                            "changed_by": frappe.session.user,
                        },
                    )

    def _detect_and_emit_settings_changes(self, old_doc):
        """Detect and emit team settings changes"""
        important_fields = [
            "enable_role_profiles",
            "default_role_profile",
            "is_active",
            "team_description",
            "team_type",
        ]

        changed_fields = []
        for field in important_fields:
            if self.has_value_changed(field):
                changed_fields.append(field)

        if changed_fields:
            emit_team_settings_changed(
                self.name, {"changed_fields": changed_fields, "changed_by": frappe.session.user}
            )

    def _detect_and_emit_leadership_changes(self, old_doc):
        """Detect and emit team leadership changes"""
        if self.has_value_changed("team_lead"):
            emit_team_leadership_changed(
                self.name,
                {
                    "old_lead": old_doc.team_lead,
                    "new_lead": self.team_lead,
                    "changed_by": frappe.session.user,
                },
            )

    def _handle_immediate_team_changes(self):
        """Handle only immediate, lightweight team changes"""
        # Keep only the essential immediate operations
        # Heavy operations like assignment history are now handled via events
        pass


# Backward compatibility API wrappers
@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_team_members(team):
    """Get team members with volunteer info - backward compatibility wrapper"""
    from verenigingen.api.team_management import get_team_members as _get_team_members

    return _get_team_members(team)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def sync_team_with_volunteers(team_name=None):
    """Sync team members with volunteer system - backward compatibility wrapper"""
    from verenigingen.api.team_management import sync_team_with_volunteers as _sync_team_with_volunteers

    return _sync_team_with_volunteers(team_name)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_role_profile_preview(team_name):
    """Get preview of role profiles - backward compatibility wrapper"""
    from verenigingen.api.team_management import get_role_profile_preview as _get_role_profile_preview

    return _get_role_profile_preview(team_name)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def bulk_apply_team_role_profiles(team_name):
    """Apply role profiles to team members - backward compatibility wrapper"""
    from verenigingen.api.team_management import (
        bulk_apply_team_role_profiles as _bulk_apply_team_role_profiles,
    )

    return _bulk_apply_team_role_profiles(team_name)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def fix_all_missing_assignment_history():
    """Fix missing assignment history - backward compatibility wrapper"""
    from verenigingen.api.team_admin_utilities import (
        fix_all_missing_assignment_history as _fix_all_missing_assignment_history,
    )

    return _fix_all_missing_assignment_history()


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def fix_missing_assignment_history(team_name=None, volunteer_name=None):
    """Fix missing assignment history for specific team/volunteer - backward compatibility wrapper"""
    from verenigingen.api.team_admin_utilities import (
        fix_missing_assignment_history as _fix_missing_assignment_history,
    )

    return _fix_missing_assignment_history(team_name, volunteer_name)


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_team_assignments():
    """Debug team assignments - backward compatibility wrapper"""
    from verenigingen.api.team_admin_utilities import debug_team_assignments as _debug_team_assignments

    return _debug_team_assignments()


def get_team_permission_query_conditions(user=None):
    """Get permission query conditions for Teams"""
    try:
        if not user:
            user = frappe.session.user

        if "System Manager" in frappe.get_roles(user) or "Verenigingen Administrator" in frappe.get_roles(
            user
        ):
            return ""

        # Get member record for the user
        member = frappe.db.get_value("Member", {"user": user}, "name")
        if not member:
            return "`tabTeam`.name = ''"

        # Get volunteer record for the member
        volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
        if not volunteer:
            return "`tabTeam`.name = ''"

        # Get teams where user is a team member using Query Builder
        TM = DocType("Team Member")
        team_memberships = (
            frappe.qb.from_(TM).select(TM.parent).where((TM.volunteer == volunteer) & (TM.is_active == 1))
        ).run(as_dict=True)

        if team_memberships:
            team_names = [team.parent for team in team_memberships]
            escaped_teams = [frappe.db.escape(name) for name in team_names]
            return f"`tabTeam`.name in ({', '.join(escaped_teams)})"

        return "`tabTeam`.name = ''"

    except Exception as e:
        frappe.log_error(f"Error in team permission query: {str(e)}")
        return "`tabTeam`.name = ''"
