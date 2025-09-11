# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import DocType


class Team(Document):
    def validate(self):
        self.validate_dates()
        self.validate_team_members()
        self.validate_role_profile_configuration()
        self.update_team_lead()

    def validate_dates(self):
        """Validate start and end dates"""
        if self.end_date and self.start_date and self.end_date < self.start_date:
            frappe.throw(_("End date cannot be before start date"))

    def validate_team_members(self):
        """Validate team members data"""
        # Check if there's at least one team leader using the new Team Role system
        has_leader = False

        # Validate unique roles constraint
        self.validate_unique_roles()

        for member in self.team_members:
            if member.is_active and member.team_role:
                try:
                    team_role_doc = frappe.get_cached_doc("Team Role", member.team_role)
                    if team_role_doc and team_role_doc.is_team_leader:
                        has_leader = True
                        break
                except frappe.DoesNotExistError:
                    # Handle case where team_role doesn't exist
                    continue

        if not has_leader and self.status == "Active" and self.team_members:
            frappe.msgprint(_("Warning: Active team should have at least one active team leader"))

    def validate_unique_roles(self):
        """Validate that unique roles are not assigned to multiple team members with concurrency protection"""

        # Get all unique roles that need validation
        unique_roles_to_check = set()
        role_assignments = {}

        for member in self.team_members:
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
            return

        # Check for concurrent assignments across all teams with database-level locking
        self._validate_unique_roles_globally(unique_roles_to_check, role_assignments)

        # Check for violations within this team
        for role_name, assignments in role_assignments.items():
            if len(assignments) > 1:
                member_names = [a["volunteer_name"] for a in assignments]
                frappe.throw(
                    f"Unique role '{role_name}' conflicts. Assigned: {', '.join(member_names[:2])}...",
                    title="Role Conflict",
                )

    def update_team_lead(self):
        """Auto-populate team_lead field from active Team Leader using Team Role system"""
        current_leader = None

        # Find the first active Team Leader using the new Team Role system
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
                    # Handle case where team_role doesn't exist
                    continue

        # Update the team_lead field
        self.team_lead = current_leader

    def validate_role_profile_configuration(self):
        """Validate role profile configuration"""
        # Validate default role profile exists
        if self.default_role_profile and not frappe.db.exists("Role Profile", self.default_role_profile):
            frappe.throw(_("Default Role Profile '{0}' does not exist").format(self.default_role_profile))

        # Validate role-specific profiles if enabled
        if self.enable_role_specific_profiles:
            if not self.default_role_profile:
                frappe.msgprint(
                    _(
                        "Warning: Role-specific profiles are enabled but no default role profile is set. Team members without specific role assignments will not get any role profile."
                    )
                )

            # Check for duplicate role assignments
            role_assignments = {}
            for row in self.role_specific_profiles or []:
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

    def before_save(self):
        """Store document state before save for comparison"""
        if not self.is_new():
            self._doc_before_save = frappe.get_doc("Team", self.name)

    def before_insert(self):
        """Prepare for initial team creation"""

    def after_insert(self):
        """Handle team member assignments after team creation"""
        self.handle_team_member_changes()

    def on_update(self):
        """Update volunteer assignments when team is updated with atomic transaction management"""
        if hasattr(self, "_team_member_changes_processed"):
            return  # Prevent recursive calls

        try:
            self._team_member_changes_processed = True
            self._handle_team_member_changes_atomic()
        finally:
            if hasattr(self, "_team_member_changes_processed"):
                delattr(self, "_team_member_changes_processed")

    def handle_team_member_changes(self):
        """Handle team member changes and update assignment history"""
        if not hasattr(self, "_doc_before_save") or self._doc_before_save is None:
            # For new teams, add all active members to history
            for member in self.team_members or []:
                if member.is_active and member.volunteer:
                    self.add_team_assignment_history(member.volunteer, member.role, member.from_date)
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
            return

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
            print(f"Could not find team member for volunteer {volunteer_id}")
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

    def _validate_unique_roles_globally(self, unique_roles_to_check, role_assignments):
        """Validate unique roles across all teams with database-level concurrency protection"""

        if not unique_roles_to_check:
            return

        try:
            # Use SELECT FOR UPDATE with proper parameterization to prevent SQL injection
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
                roles_list + [self.name or ""],
                as_dict=True,
            )

            # Check for conflicts with existing assignments
            for assignment in existing_assignments:
                role_name = assignment.role_name
                if role_name in role_assignments:
                    # We have a conflict - this unique role is already assigned elsewhere
                    # current_assignees = [a["volunteer_name"] for a in role_assignments[role_name]]
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
                frappe.log_error(f"Error in unique role validation: {e}", "Unique Role Validation Error")

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
                # Verify assignment history exists for this member
                history_exists = frappe.db.exists(
                    "Assignment History",
                    {
                        "volunteer": member.volunteer,
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


@frappe.whitelist()
def get_team_members(team):
    """Get team members with volunteer info"""
    if not team:
        return []

    team_doc = frappe.get_doc("Team", team)

    members = []
    for member in team_doc.team_members:
        if not member.volunteer:
            continue

        try:
            vol_doc = frappe.get_doc("Volunteer", member.volunteer)
            # Get role information using Team Role system
            team_doc = frappe.get_doc("Team", team)
            role_description = team_doc.get_role_description_for_history(member)

            members.append(
                {
                    "volunteer": member.volunteer,
                    "name": vol_doc.volunteer_name,
                    "role": member.role,
                    "role_type": member.role_type,
                    "team_role": member.team_role,
                    "role_description": role_description,
                    "status": member.status,
                    "from_date": member.from_date,
                    "to_date": member.to_date,
                    "skills": vol_doc.get_skills_by_category(),
                }
            )
        except Exception:
            pass

    return members


@frappe.whitelist()
def sync_team_with_volunteers(team_name=None):
    """Sync all team members with volunteer system"""
    filters = {}
    if team_name:
        filters["name"] = team_name

    # Get all active teams
    teams = frappe.get_all("Team", filters=filters, fields=["name"])

    updated_count = 0

    for team in teams:
        try:
            team_doc = frappe.get_doc("Team", team.name)
            # Trigger volunteer assignment history updates by calling the handler
            team_doc.handle_team_member_changes()
            updated_count += 1
            frappe.logger().info(f"Successfully synced team {team.name} with volunteers")
        except Exception as e:
            frappe.log_error(f"Failed to sync team {team.name}: {str(e)}")
            frappe.logger().error(f"Error syncing team {team.name}: {str(e)}")

    return {"updated_count": updated_count}


@frappe.whitelist()
def fix_all_missing_assignment_history():
    """Fix missing assignment history for all teams - admin utility function"""
    try:
        teams_fixed = 0
        volunteers_fixed = 0

        # Get all teams with active members
        teams = frappe.get_all("Team", fields=["name"])

        for team_data in teams:
            team = frappe.get_doc("Team", team_data.name)

            for member in team.team_members:
                if member.is_active and member.volunteer:
                    # Check if assignment history exists
                    history_exists = frappe.db.exists(
                        "Assignment History",
                        {
                            "volunteer": member.volunteer,
                            "reference_doctype": "Team",
                            "reference_name": team.name,
                            "status": "Active",
                        },
                    )

                    if not history_exists:
                        # Fix missing history
                        success = team.add_team_assignment_history(
                            member.volunteer,
                            member.team_role or member.role or "Team Member",
                            member.from_date or frappe.utils.today(),
                        )

                        if success:
                            volunteers_fixed += 1
                            frappe.logger().info(
                                f"✅ Fixed assignment history for {member.volunteer_name} in {team.name}"
                            )
                        else:
                            frappe.logger().error(
                                f"❌ Failed to fix assignment history for {member.volunteer_name} in {team.name}"
                            )

            if volunteers_fixed > 0:
                teams_fixed += 1

        return {
            "success": True,
            "message": f"Fixed assignment history for {volunteers_fixed} volunteers across {teams_fixed} teams",
            "teams_fixed": teams_fixed,
            "volunteers_fixed": volunteers_fixed,
        }

    except Exception as e:
        frappe.log_error(
            f"Error in bulk assignment history fix: {str(e)}", "Assignment History Bulk Fix Error"
        )
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_missing_assignment_history(team_name=None, volunteer_name=None):
    """Fix missing team assignment history for existing assignments"""

    try:
        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        if team_name and volunteer_name:
            # Fix specific team-volunteer assignment
            team = frappe.get_doc("Team", team_name)

            for member in team.team_members:
                if member.volunteer == volunteer_name and member.is_active:
                    frappe.logger().info(f"Found active assignment: {member.volunteer} -> {member.role}")

                    # Check if assignment history already exists
                    volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
                    has_assignment = False

                    for assignment in volunteer_doc.assignment_history or []:
                        if (
                            assignment.reference_doctype == "Team"
                            and assignment.reference_name == team_name
                            and assignment.role == member.role
                            and assignment.status == "Active"
                        ):
                            has_assignment = True
                            frappe.logger().info("Assignment already exists in history")
                            break

                    if not has_assignment:
                        success = AssignmentHistoryManager.add_assignment_history(
                            volunteer_id=volunteer_name,
                            assignment_type="Team",
                            reference_doctype="Team",
                            reference_name=team_name,
                            role=member.role,
                            start_date=member.from_date,
                        )

                        if success:
                            frappe.logger().info(
                                f"✅ Successfully added assignment history for {volunteer_name}"
                            )
                            return {"success": True, "message": "Assignment history added successfully"}
                        else:
                            frappe.logger().error(f"❌ Failed to add assignment history for {volunteer_name}")
                            return {"success": False, "error": "Failed to add assignment history"}
                    else:
                        return {"success": True, "message": "Assignment history already exists"}

        return {"success": False, "error": "No matching assignment found"}

    except Exception as e:
        frappe.logger().error(f"❌ Error: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_team_assignments():
    """Debug team assignments and volunteers"""

    result = {}

    # Get teams
    teams = frappe.get_all("Team", fields=["name", "team_name"])
    result["teams"] = []
    for team in teams:
        team_doc = frappe.get_doc("Team", team.name)
        team_info = {"name": team.name, "team_name": team.team_name, "members": []}
        for member in team_doc.team_members:
            team_info["members"].append(
                {
                    "volunteer": member.volunteer,
                    "volunteer_name": member.volunteer_name,
                    "role": member.role,
                    "is_active": member.is_active,
                    "from_date": str(member.from_date) if member.from_date else None,
                }
            )
        result["teams"].append(team_info)

    # Get Foppe volunteers
    volunteers = frappe.get_all(
        "Volunteer",
        filters={"volunteer_name": ["like", "%Foppe%"]},
        fields=["name", "volunteer_name"],
    )
    result["foppe_volunteers"] = []
    for vol in volunteers:
        volunteer_doc = frappe.get_doc("Volunteer", vol.name)
        vol_info = {"name": vol.name, "volunteer_name": vol.volunteer_name, "assignment_history": []}
        for assignment in volunteer_doc.assignment_history or []:
            vol_info["assignment_history"].append(
                {
                    "assignment_type": assignment.assignment_type,
                    "reference_doctype": assignment.reference_doctype,
                    "reference_name": assignment.reference_name,
                    "role": assignment.role,
                    "status": assignment.status,
                    "start_date": str(assignment.start_date) if assignment.start_date else None,
                    "end_date": str(assignment.end_date) if assignment.end_date else None,
                }
            )
        result["foppe_volunteers"].append(vol_info)

    return result


@frappe.whitelist()
def test_team_member_removal():
    """Test that removing a team member properly updates assignment history"""

    print("=== Testing Team Member Removal ===")

    try:
        # Create a test team with a member
        test_team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"Removal Test Team {frappe.utils.random_string(5)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
            }
        )
        test_team.insert()

        # Get Foppe de Haan as our test volunteer
        volunteer_name = "Foppe de  Haan"  # Note the double space

        # Add him to the team
        test_team.append(
            "team_members",
            {
                "volunteer": volunteer_name,
                "volunteer_name": volunteer_name,
                "role": "Test Removal Role",
                "role_type": "Team Member",
                "from_date": frappe.utils.today(),
                "is_active": 1,
                "status": "Active",
            },
        )

        print(f"1. Adding {volunteer_name} to team {test_team.name}")
        test_team.save()

        # Check if assignment history was created
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
        active_assignment = None
        for assignment in volunteer_doc.assignment_history or []:
            if assignment.reference_name == test_team.name and assignment.status == "Active":
                active_assignment = assignment
                break

        if active_assignment:
            # active_assignment is a Volunteer Assignment which has 'role' field
            assignment_role = getattr(active_assignment, "role", "No role specified")
            print(f"✅ Active assignment created: {assignment_role}")
        else:
            print("❌ No active assignment found")
            return {"success": False, "error": "No active assignment created"}

        # Now test removal by deactivating the member
        print(f"2. Deactivating {volunteer_name} from team")
        team_member = test_team.team_members[0]
        team_member.is_active = 0
        team_member.to_date = frappe.utils.today()
        team_member.status = "Completed"

        test_team.save()

        # Check if assignment history was completed
        volunteer_doc.reload()
        completed_assignment = None
        for assignment in volunteer_doc.assignment_history or []:
            if assignment.reference_name == test_team.name and assignment.status == "Completed":
                completed_assignment = assignment
                break

        if completed_assignment:
            print(f"✅ Assignment completed with end date: {completed_assignment.end_date}")

            # Now test complete removal
            print(f"3. Completely removing {volunteer_name} from team")
            test_team.team_members = []  # Remove all members
            test_team.save()

            # Check that assignment history is still completed (not removed)
            volunteer_doc.reload()
            still_completed = None
            for assignment in volunteer_doc.assignment_history or []:
                if assignment.reference_name == test_team.name and assignment.status == "Completed":
                    still_completed = assignment
                    break

            if still_completed:
                print("✅ Assignment history preserved after complete removal")
            else:
                print("❌ Assignment history lost after complete removal")
        else:
            print("❌ Assignment was not completed")
            return {"success": False, "error": "Assignment not completed"}

        # Clean up - remove assignment history and delete team
        print("4. Cleaning up test data")
        volunteer_doc.reload()
        assignments_to_remove = []
        for assignment in volunteer_doc.assignment_history or []:
            if assignment.reference_name == test_team.name:
                assignments_to_remove.append(assignment)

        for assignment in assignments_to_remove:
            volunteer_doc.assignment_history.remove(assignment)

        if assignments_to_remove:
            volunteer_doc.save()

        try:
            frappe.delete_doc("Team", test_team.name)
        except Exception:
            pass  # Ignore deletion errors for testing

        print("✅ Test completed successfully!")
        return {"success": True, "message": "Team member removal test passed"}

    except Exception as e:
        print(f"❌ Error during test: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}


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
            return "`tabTeam`.name = ''"  # No access if not a member

        # Get volunteer record for the member
        volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
        if not volunteer:
            return "`tabTeam`.name = ''"  # No access if not a volunteer

        # Get teams where user is a team member using Query Builder
        TM = DocType("Team Member")
        team_memberships = (
            frappe.qb.from_(TM).select(TM.parent).where((TM.volunteer == volunteer) & (TM.is_active == 1))
        ).run(as_dict=True)

        if team_memberships:
            # Modernized string formatting with proper SQL escaping
            team_names = [team.parent for team in team_memberships]
            escaped_teams = [frappe.db.escape(name) for name in team_names]
            return f"`tabTeam`.name in ({', '.join(escaped_teams)})"

        return "`tabTeam`.name = ''"  # No access if not part of any teams

    except Exception as e:
        frappe.log_error(f"Error in team permission query: {str(e)}")
        return "`tabTeam`.name = ''"  # Default to no access on error


@frappe.whitelist()
def get_role_profile_preview(team_name):
    """Get preview of which role profiles would be assigned to team members"""
    if not team_name or not frappe.db.exists("Team", team_name):
        return {"error": "Team not found"}

    team_doc = frappe.get_doc("Team", team_name)

    preview = {
        "team_name": team_name,
        "default_profile": team_doc.get("default_role_profile"),
        "role_specific_enabled": team_doc.get("enable_role_specific_profiles", False),
        "role_specific_profiles": {},
        "member_assignments": [],
    }

    # Build role-specific mapping
    if preview["role_specific_enabled"] and team_doc.get("role_specific_profiles"):
        for row in team_doc.role_specific_profiles:
            if row.team_role and row.role_profile:
                preview["role_specific_profiles"][row.team_role] = row.role_profile

    # Preview assignments for current team members
    from verenigingen.utils.team_role_profile_manager import determine_role_profile_for_team_member

    for member in team_doc.team_members or []:
        if member.volunteer and member.is_active:
            assigned_profile = determine_role_profile_for_team_member(team_name, member.team_role)

            member_info = {
                "volunteer": member.volunteer,
                "volunteer_name": member.volunteer_name,
                "team_role": member.team_role,
                "assigned_profile": assigned_profile,
                "assignment_source": "none",
            }

            # Determine assignment source
            if assigned_profile:
                if preview["role_specific_enabled"] and member.team_role in preview["role_specific_profiles"]:
                    member_info["assignment_source"] = "role_specific"
                elif assigned_profile == preview["default_profile"]:
                    member_info["assignment_source"] = "default"
                else:
                    member_info["assignment_source"] = "hardcoded_fallback"

            preview["member_assignments"].append(member_info)

    return preview


@frappe.whitelist()
def bulk_apply_team_role_profiles(team_name):
    """Apply role profiles to all current team members based on team configuration"""
    from verenigingen.utils.team_role_profile_manager import bulk_assign_team_role_profiles

    if not team_name or not frappe.db.exists("Team", team_name):
        return {"success": False, "error": "Team not found"}

    try:
        result = bulk_assign_team_role_profiles(team_name)
        return result
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Bulk Team Role Profile Assignment Error")
        return {"success": False, "error": str(e)}
