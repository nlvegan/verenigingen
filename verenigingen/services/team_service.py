"""
Team Service

Business logic service for team management operations,
extracted from the Team DocType controller to maintain clean architecture.
"""

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService


class TeamService(StatelessService):
    """Service class for team business logic operations"""

    def __init__(self):
        """Initialize the Team Service"""
        super().__init__(service_name="TeamService")

    def sync_with_volunteers(self, team_doc):
        """Sync team members with volunteer system"""
        # Trigger volunteer assignment history updates
        if hasattr(team_doc, "handle_team_member_changes"):
            team_doc.handle_team_member_changes()
        self.logger.info(f"Successfully synced team {team_doc.name} with volunteers")
        return True

    def add_assignment_history(self, team_doc, volunteer_id: str, team_role: str, start_date: str):
        """Add assignment history for a team member"""
        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        # Get the team member to access both team_role and role fields
        team_member = None
        for member in team_doc.team_members:
            if member.volunteer == volunteer_id and str(member.from_date) == str(start_date):
                team_member = member
                break

        if not team_member:
            self.logger.warning(f"Could not find team member for volunteer {volunteer_id}")
            return False

        # Create role description using Team Role system
        role_description = self._get_role_description_for_history(team_member)

        success = AssignmentHistoryManager.add_assignment_history(
            volunteer_id=volunteer_id,
            assignment_type="Team",
            reference_doctype="Team",
            reference_name=team_doc.name,
            role=role_description,
            start_date=start_date,
        )

        if success:
            self.logger.info(
                f"Added team assignment history for volunteer {volunteer_id}: {role_description}"
            )
        else:
            self.logger.error(
                f"Error adding team assignment history for volunteer {volunteer_id}: {role_description}"
            )

        return success

    def complete_assignment_history(
        self, team_doc, volunteer_id: str, team_role: str, start_date: str, end_date: str
    ):
        """Complete assignment history for a team member"""
        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        # Get the team member to access both team_role and role fields
        team_member = None
        for member in team_doc.team_members:
            if member.volunteer == volunteer_id and str(member.from_date) == str(start_date):
                team_member = member
                break

        # If not in current members, check the old document
        if not team_member and hasattr(team_doc, "_doc_before_save"):
            for member in team_doc._doc_before_save.team_members or []:
                if member.volunteer == volunteer_id and str(member.from_date) == str(start_date):
                    team_member = member
                    break

        if not team_member:
            # Use team_role as-is if we can't find the member
            role_description = team_role or "Team Member"
        else:
            # Create role description using Team Role system
            role_description = self._get_role_description_for_history(team_member)

        success = AssignmentHistoryManager.complete_assignment_history(
            volunteer_id=volunteer_id,
            assignment_type="Team",
            reference_doctype="Team",
            reference_name=team_doc.name,
            role=role_description,
            start_date=start_date,
            end_date=end_date,
        )

        if success:
            self.logger.info(
                f"Completed team assignment history for volunteer {volunteer_id}: {role_description}"
            )
        else:
            self.logger.error(
                f"Error completing team assignment history for volunteer {volunteer_id}: {role_description}"
            )

        return success

    def _get_role_description_for_history(self, team_member):
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

    def validate_team_member_changes(self, team_doc):
        """Validate team member changes before save"""
        # This could include business rule validation
        # that doesn't belong in the DocType controller
        return True

    def handle_member_role_change(self, team_doc, old_member, new_member):
        """Handle role changes for team members"""
        if not old_member or not new_member:
            return

        # Check for role changes
        role_changed = (
            old_member.role != new_member.role
            or old_member.team_role != new_member.team_role
            or old_member.role_type != new_member.role_type
        )

        if role_changed and old_member.is_active and new_member.is_active:
            # Role changed - complete old assignment and create new one
            change_date = frappe.utils.today()
            self.complete_assignment_history(
                team_doc, old_member.volunteer, old_member.team_role, old_member.from_date, change_date
            )

            # Start new assignment with new role using today's date
            self.add_assignment_history(team_doc, new_member.volunteer, new_member.team_role, change_date)

    def validate_unique_roles(self, team_doc):
        """Validate unique role constraints across teams"""
        # This logic could be moved here from the controller
        # to separate business logic from document lifecycle

        # Get all unique roles that need validation
        unique_roles_to_check = set()
        role_assignments = {}

        for member in team_doc.team_members:
            if not member.is_active or not member.team_role:
                continue

            try:
                team_role_doc = frappe.get_cached_doc("Team Role", member.team_role)
                if not team_role_doc or not team_role_doc.is_unique:
                    continue
                unique_roles_to_check.add(member.team_role)
            except frappe.DoesNotExistError:
                continue

            # Track assignments of unique roles
            role_name = team_role_doc.role_name
            if role_name not in role_assignments:
                role_assignments[role_name] = []

            role_assignments[role_name].append(
                {"volunteer_name": member.volunteer_name or member.volunteer, "team_role": member.team_role}
            )

        # If no unique roles to validate, exit early
        if not unique_roles_to_check:
            return True

        # REMOVED: Global validation across teams - unique roles should only be unique WITHIN a team
        # self._validate_unique_roles_globally(team_doc, unique_roles_to_check, role_assignments)

        # Check for violations within this team (this is the correct behavior)
        for role_name, assignments in role_assignments.items():
            if len(assignments) > 1:
                member_names = [a["volunteer_name"] for a in assignments]
                frappe.throw(
                    f"Unique role '{role_name}' conflicts. Assigned: {', '.join(member_names[:2])}...",
                    title="Role Conflict",
                )

        return True

    def _validate_unique_roles_globally(self, team_doc, unique_roles_to_check, role_assignments):
        """Validate unique roles across all teams with database-level concurrency protection"""

        if not unique_roles_to_check:
            return

        try:
            # Use proper parameterized query to prevent SQL injection
            roles_list = list(unique_roles_to_check)
            if not roles_list:
                return

            roles_placeholder = ", ".join(["%s"] * len(roles_list))
            existing_assignments = frappe.db.sql(
                f"""
                SELECT tm.parent, tm.volunteer, tm.volunteer_name, tm.team_role, tr.role_name
                FROM `tabTeam Member` tm
                INNER JOIN `tabTeam Role` tr ON tm.team_role = tr.name
                WHERE tm.team_role IN ({roles_placeholder})
                    AND tm.is_active = 1
                    AND tr.is_unique = 1
                    AND tm.parent != %s
                FOR UPDATE
            """,
                roles_list + [team_doc.name or ""],
                as_dict=True,
            )

            # Check for conflicts with existing assignments
            for assignment in existing_assignments:
                role_name = assignment.role_name
                if role_name in role_assignments:
                    # We have a conflict - this unique role is already assigned elsewhere
                    existing_assignee = assignment.volunteer_name or assignment.volunteer
                    existing_team = assignment.parent

                    frappe.throw(
                        f"'{role_name}' already assigned to {existing_assignee} in {existing_team}.",
                        title="Unique Role Conflict",
                    )

        except Exception as e:
            if "Unique role" in str(e) or "conflict" in str(e).lower():
                raise  # Re-raise validation errors
            else:
                # Log other errors but don't block the transaction
                self.logger.error(f"Error in unique role validation: {e}")


class TeamValidationService(StatelessService):
    """Separate service for team validation logic"""

    def __init__(self):
        """Initialize the Team Validation Service"""
        super().__init__(service_name="TeamValidationService")

    def validate_team_members(self, team_doc):
        """Validate team members data and structure"""
        # Check if there's at least one team leader
        has_leader = False

        for member in team_doc.team_members:
            if member.is_active and member.team_role:
                try:
                    team_role_doc = frappe.get_cached_doc("Team Role", member.team_role)
                    if team_role_doc and team_role_doc.is_team_leader:
                        has_leader = True
                        break
                except frappe.DoesNotExistError:
                    continue

        if not has_leader and team_doc.status == "Active" and team_doc.team_members:
            frappe.msgprint(_("Warning: Active team should have at least one active team leader"))

        return True

    def validate_role_profile_configuration(self, team_doc):
        """Validate role profile configuration"""
        # Validate default role profile exists
        if team_doc.default_role_profile and not frappe.db.exists(
            "Role Profile", team_doc.default_role_profile
        ):
            frappe.throw(_("Default Role Profile '{0}' does not exist").format(team_doc.default_role_profile))

        # Validate role-specific profiles if enabled
        if team_doc.enable_role_specific_profiles:
            if not team_doc.default_role_profile:
                frappe.msgprint(
                    _(
                        "Warning: Role-specific profiles are enabled but no default role profile is set. "
                        "Team members without specific role assignments will not get any role profile."
                    )
                )

            # Check for duplicate role assignments
            role_assignments = {}
            for row in team_doc.role_specific_profiles or []:
                if row.team_role:
                    if row.team_role in role_assignments:
                        frappe.throw(
                            _("Duplicate role profile assignment for Team Role '{0}'").format(row.team_role)
                        )
                    role_assignments[row.team_role] = row.role_profile

                    # Validate that the role profile exists
                    if row.role_profile and not frappe.db.exists("Role Profile", row.role_profile):
                        frappe.throw(_("Role Profile '{0}' does not exist").format(row.role_profile))

                    # Validate that the team role exists
                    if not frappe.db.exists("Team Role", row.team_role):
                        frappe.throw(_("Team Role '{0}' does not exist").format(row.team_role))

        return True

    def validate_dates(self, team_doc):
        """Validate start and end dates"""
        if team_doc.end_date and team_doc.start_date and team_doc.end_date < team_doc.start_date:
            frappe.throw(_("End date cannot be before start date"))

        return True

    def validate_team_member_rows(self, team_doc):
        """Enforce the per-row rules `Team Member.validate()` stated but never ran.

        Team Member is a child table (`"istable": 1`), so Frappe never calls its own
        validate() -- see #596. `required volunteer` and `Team Role must exist` are
        already covered by the field's own `reqd`/Link-field validation, which DOES
        run for children regardless of custom validate(). Unique-role-per-team is
        already covered by `TeamService.validate_unique_roles`, called from
        `Team._validate_unique_roles()` in `Team.validate()`. Neither of those,
        nor anything else, checked a per-row date range or is_active/status
        consistency, so this is what's left to port.
        """
        for member in team_doc.team_members or []:
            if member.to_date and member.from_date and member.to_date < member.from_date:
                frappe.throw(_("Row {0}: End date cannot be before start date").format(member.idx))

            if not member.is_active and member.status == "Active":
                member.status = "Inactive"
            elif member.is_active and member.status != "Active":
                member.is_active = 0

        return True


def get_team_service() -> TeamService:
    """Get instance of TeamService."""
    return TeamService()


def get_team_validation_service() -> TeamValidationService:
    """Get instance of TeamValidationService."""
    return TeamValidationService()
