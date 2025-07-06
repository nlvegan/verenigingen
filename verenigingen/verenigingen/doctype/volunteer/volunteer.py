import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.utils import getdate, today

from verenigingen.utils.dutch_name_utils import format_dutch_full_name, is_dutch_installation


class Volunteer(Document):
    def onload(self):
        """Load address and contacts in `__onload`"""
        # If this volunteer is linked to a member, load member's address and contact info
        if self.member:
            # Load address and contact from the linked member instead of volunteer
            member_doc = frappe.get_doc("Member", self.member)
            load_address_and_contact(member_doc)
            # Copy the loaded address and contact info to volunteer
            if hasattr(member_doc, "__onload"):
                if not hasattr(self, "__onload"):
                    self.set("__onload", frappe._dict())
                self.get("__onload").update(member_doc.get("__onload"))
        else:
            # Fallback to volunteer's own address/contact if no member is linked
            load_address_and_contact(self)

        # Load aggregated assignments
        self.load_aggregated_assignments()

    def load_aggregated_assignments(self):
        """Load aggregated assignments from all sources"""
        self.get("__onload").aggregated_assignments = self.get_aggregated_assignments()

    def validate(self):
        """Validate volunteer data"""
        self.validate_required_fields()
        self.validate_member_link()
        self.validate_dates()

    def validate_required_fields(self):
        """Check if required fields are filled"""
        if not self.start_date:
            self.start_date = today()

    def validate_member_link(self):
        """Validate that member link is valid"""
        if self.member and not frappe.db.exists("Member", self.member):
            frappe.throw(_("Member {0} does not exist").format(self.member), frappe.DoesNotExistError)

    def validate_dates(self):
        """Validate date fields in child tables"""
        for assignment in self.assignment_history:
            if assignment.end_date and assignment.start_date:
                start_date = getdate(assignment.start_date)
                end_date = getdate(assignment.end_date)
                if start_date > end_date:
                    frappe.throw(
                        _("Assignment start date cannot be after end date for {0}").format(assignment.role)
                    )

    def before_save(self):
        """Actions before saving volunteer record"""
        # Update volunteer status based on assignments
        self.update_status()

    def after_insert(self):
        """Actions after inserting new volunteer record"""
        # Automatically create employee record for expense functionality
        self.create_employee_if_needed()

    def update_status(self):
        """Update volunteer status based on assignments"""
        if not self.status or self.status == "New":
            # If this is a new volunteer record
            assignments = self.get_aggregated_assignments()
            if assignments:
                self.status = "Active"
            else:
                self.status = "New"

    def get_contact_link_doctype(self):
        """Override to link contacts to member if available"""
        if self.member:
            return "Member"
        return "Volunteer"

    def get_contact_link_name(self):
        """Override to link contacts to member if available"""
        if self.member:
            return self.member
        return self.name

    @frappe.whitelist()
    def get_aggregated_assignments(self):
        """Get aggregated assignments from all sources with optimized single query"""
        try:
            # Use single optimized query to get all assignments at once
            return self.get_aggregated_assignments_optimized()
        except Exception as e:
            frappe.log_error(f"Error in optimized assignments query: {str(e)}")
            # Fallback to individual queries
            return self.get_aggregated_assignments_fallback()

    def get_aggregated_assignments_optimized(self):
        """Optimized single query to get all assignments"""
        assignments_data = frappe.db.sql(
            """
            SELECT
                'Board Position' as source_type,
                'Chapter Board Member' as source_doctype,
                cbm.parent as source_name,
                'Chapter' as source_doctype_display,
                c.name as source_name_display,
                cbm.chapter_role as role,
                cbm.from_date as start_date,
                cbm.to_date as end_date,
                cbm.is_active,
                0 as editable,
                CONCAT('/app/chapter/', cbm.parent) as source_link,
                '' as reference_display,
                '' as reference_link
            FROM `tabChapter Board Member` cbm
            LEFT JOIN `tabChapter` c ON cbm.parent = c.name
            WHERE cbm.volunteer = %s AND cbm.is_active = 1

            UNION ALL

            SELECT
                'Team' as source_type,
                'Team Member' as source_doctype,
                tm.parent as source_name,
                COALESCE(t.team_type, 'Team') as source_doctype_display,
                t.name as source_name_display,
                tm.role,
                tm.from_date as start_date,
                tm.to_date as end_date,
                CASE WHEN tm.status = 'Active' THEN 1 ELSE 0 END as is_active,
                0 as editable,
                CONCAT('/app/team/', tm.parent) as source_link,
                '' as reference_display,
                '' as reference_link
            FROM `tabTeam Member` tm
            LEFT JOIN `tabTeam` t ON tm.parent = t.name
            WHERE tm.volunteer = %s AND tm.status = 'Active'

            UNION ALL

            SELECT
                'Activity' as source_type,
                'Volunteer Activity' as source_doctype,
                va.name as source_name,
                va.activity_type as source_doctype_display,
                COALESCE(va.description, va.role) as source_name_display,
                va.role,
                va.start_date,
                va.end_date,
                CASE WHEN va.status = 'Active' THEN 1 ELSE 0 END as is_active,
                1 as editable,
                CONCAT('/app/volunteer-activity/', va.name) as source_link,
                CASE
                    WHEN va.reference_doctype IS NOT NULL AND va.reference_name IS NOT NULL
                    THEN CONCAT(va.reference_doctype, ': ', va.reference_name)
                    ELSE ''
                END as reference_display,
                CASE
                    WHEN va.reference_doctype IS NOT NULL AND va.reference_name IS NOT NULL
                    THEN CONCAT('/app/', LOWER(REPLACE(va.reference_doctype, ' ', '-')), '/', va.reference_name)
                    ELSE ''
                END as reference_link
            FROM `tabVolunteer Activity` va
            WHERE va.volunteer = %s AND va.status = 'Active'

            ORDER BY start_date DESC
        """,
            (self.name, self.name, self.name),
            as_dict=True,
        )

        # Convert to the expected format
        assignments = []
        for data in assignments_data:
            assignments.append(
                {
                    "source_type": data.source_type,
                    "source_doctype": data.source_doctype,
                    "source_name": data.source_name,
                    "source_doctype_display": data.source_doctype_display,
                    "source_name_display": data.source_name_display,
                    "role": data.role,
                    "start_date": data.start_date,
                    "end_date": data.end_date,
                    "is_active": bool(data.is_active),
                    "editable": bool(data.editable),
                    "source_link": data.source_link,
                    "reference_display": data.reference_display,
                    "reference_link": data.reference_link,
                }
            )

        return assignments

    def get_aggregated_assignments_fallback(self):
        """Fallback method using individual queries"""
        assignments = []

        # 1. Get board assignments
        board_assignments = self.get_board_assignments()
        assignments.extend(board_assignments)

        # 2. Get team assignments
        team_assignments = self.get_team_assignments()
        assignments.extend(team_assignments)

        # 3. Get activity assignments
        activity_assignments = self.get_activity_assignments()
        assignments.extend(activity_assignments)

        return assignments

    def get_board_assignments(self):
        """Get board assignments from Chapter Board Member"""
        board_assignments = []

        # Query board memberships for this volunteer using Query Builder
        CBM = DocType("Chapter Board Member")
        Chapter = DocType("Chapter")

        board_memberships = (
            frappe.qb.from_(CBM)
            .join(Chapter)
            .on(CBM.parent == Chapter.name)
            .select(
                CBM.name.as_("membership_id"),
                CBM.parent.as_("chapter"),
                CBM.chapter_role.as_("role"),
                CBM.from_date,
                CBM.to_date,
                CBM.is_active,
                Chapter.name.as_("chapter_name"),
            )
            .where((CBM.volunteer == self.name) & (CBM.is_active == 1))
        ).run(as_dict=True)

        for membership in board_memberships:
            board_assignments.append(
                {
                    "source_type": "Board Position",
                    "source_doctype": "Chapter",
                    "source_name": membership.chapter,
                    "source_doctype_display": "Chapter",
                    "source_name_display": membership.chapter_name,
                    "role": membership.role,
                    "start_date": membership.from_date,
                    "end_date": membership.to_date,
                    "is_active": membership.is_active,
                    "editable": False,
                    "source_link": f"/app/chapter/{membership.chapter}",
                }
            )

        return board_assignments

    def get_team_assignments(self):
        """Get team assignments from Team Member"""
        team_assignments = []

        # Query team memberships for this volunteer using Query Builder
        TM = DocType("Team Member")
        Team = DocType("Team")

        team_memberships = (
            frappe.qb.from_(TM)
            .join(Team)
            .on(TM.parent == Team.name)
            .select(
                TM.name.as_("membership_id"),
                TM.parent.as_("team"),
                TM.role,
                TM.role_type,
                TM.from_date,
                TM.to_date,
                TM.status,
                Team.name.as_("team_name"),
                Team.team_type,
            )
            .where((TM.volunteer == self.name) & (TM.status == "Active"))
        ).run(as_dict=True)

        for membership in team_memberships:
            team_assignments.append(
                {
                    "source_type": "Team",
                    "source_doctype": "Team",
                    "source_name": membership.team,
                    "source_doctype_display": f"{membership.team_type or 'Team'}",
                    "source_name_display": membership.team_name,
                    "role": membership.role,
                    "start_date": membership.from_date,
                    "end_date": membership.to_date,
                    "is_active": membership.status == "Active",
                    "editable": False,
                    "source_link": f"/app/team/{membership.team}",
                }
            )

        return team_assignments

    def get_activity_assignments(self):
        """Get active assignments from assignment history and Volunteer Activity"""
        activity_assignments = []

        # First check assignment_history child table
        if hasattr(self, "assignment_history") and self.assignment_history:
            for assignment in self.assignment_history:
                if assignment.status == "Active":
                    activity_assignments.append(assignment)
            # If we found assignments in history, return them
            if activity_assignments:
                return activity_assignments

        # Fallback to querying Volunteer Activity doctype
        activities = frappe.get_all(
            "Volunteer Activity",
            filters={"volunteer": self.name, "status": "Active"},
            fields=[
                "name",
                "activity_type",
                "role",
                "description",
                "status",
                "start_date",
                "end_date",
                "reference_doctype",
                "reference_name",
                "estimated_hours",
                "actual_hours",
                "notes",
            ],
        )

        for activity in activities:
            ref_display = ""
            ref_link = ""

            if activity.reference_doctype and activity.reference_name:
                ref_display = f"{activity.reference_doctype}: {activity.reference_name}"
                ref_link = f"/app/{frappe.scrub(activity.reference_doctype)}/{activity.reference_name}"

            activity_assignments.append(
                {
                    "source_type": "Activity",
                    "source_doctype": "Volunteer Activity",
                    "source_name": activity.name,
                    "source_doctype_display": activity.activity_type,
                    "source_name_display": activity.description or activity.role,
                    "role": activity.role,
                    "start_date": activity.start_date,
                    "end_date": activity.end_date,
                    "is_active": activity.status == "Active",
                    "editable": True,
                    "source_link": f"/app/volunteer-activity/{activity.name}",
                    "reference_display": ref_display,
                    "reference_link": ref_link,
                }
            )

        return activity_assignments

    @frappe.whitelist()
    def add_activity(
        self,
        activity_type,
        role,
        description=None,
        start_date=None,
        end_date=None,
        reference_doctype=None,
        reference_name=None,
        estimated_hours=None,
        notes=None,
    ):
        """Add a new volunteer activity"""
        try:
            if not start_date:
                start_date = getdate(today())
            else:
                start_date = getdate(start_date)

            if end_date:
                end_date = getdate(end_date)
                if start_date > end_date:
                    frappe.throw(_("Start date cannot be after end date"))

            # Validate required fields
            if not activity_type:
                frappe.throw(_("Activity type is required"))
            if not role:
                frappe.throw(_("Role is required"))

            activity = frappe.get_doc(
                {
                    "doctype": "Volunteer Activity",
                    "volunteer": self.name,
                    "activity_type": activity_type,
                    "role": role,
                    "description": description,
                    "start_date": start_date,
                    "end_date": end_date,
                    "status": "Active",
                    "reference_doctype": reference_doctype,
                    "reference_name": reference_name,
                    "estimated_hours": estimated_hours,
                    "notes": notes,
                }
            )

            activity.insert()

            return activity.name

        except frappe.ValidationError as e:
            frappe.throw(_("Failed to create activity: {0}").format(str(e)))
        except Exception as e:
            frappe.log_error(f"Error creating volunteer activity: {str(e)}")
            frappe.throw(_("An error occurred while creating the activity"))

    @frappe.whitelist()
    def end_activity(self, activity_name, end_date=None, notes=None):
        """End a volunteer activity"""
        try:
            if not end_date:
                end_date = getdate(today())
            else:
                end_date = getdate(end_date)

            if not activity_name:
                frappe.throw(_("Activity name is required"))

            activity = frappe.get_doc("Volunteer Activity", activity_name)

            # Validate that this activity belongs to this volunteer
            if activity.volunteer != self.name:
                frappe.throw(_("You can only end activities assigned to this volunteer"))

            activity.status = "Completed"
            activity.end_date = end_date

            if notes:
                activity.notes = notes

            activity.save()

            return True

        except frappe.DoesNotExistError:
            frappe.throw(_("Activity {0} not found").format(activity_name))
        except frappe.ValidationError as e:
            frappe.throw(_("Failed to end activity: {0}").format(str(e)))
        except Exception as e:
            frappe.log_error(f"Error ending volunteer activity: {str(e)}")
            frappe.throw(_("An error occurred while ending the activity"))

    @frappe.whitelist()
    def get_volunteer_history(self):
        """Get volunteer history in chronological order with optimized single query"""
        try:
            # Use optimized single query to get all history at once
            return self.get_volunteer_history_optimized()
        except Exception as e:
            frappe.log_error(f"Error in optimized history query: {str(e)}")
            # Fallback to individual queries
            return self.get_volunteer_history_fallback()

    def get_volunteer_history_optimized(self):
        """Optimized single query to get complete volunteer history"""
        history_data = frappe.db.sql(
            """
            SELECT
                'Board Position' as assignment_type,
                cbm.chapter_role as role,
                cbm.parent as reference,
                cbm.from_date as start_date,
                cbm.to_date as end_date,
                cbm.is_active,
                CASE WHEN cbm.is_active = 1 THEN 'Active' ELSE 'Completed' END as status
            FROM `tabChapter Board Member` cbm
            WHERE cbm.volunteer = %s

            UNION ALL

            SELECT
                'Team' as assignment_type,
                tm.role,
                tm.parent as reference,
                tm.from_date as start_date,
                tm.to_date as end_date,
                CASE WHEN tm.status = 'Active' THEN 1 ELSE 0 END as is_active,
                tm.status
            FROM `tabTeam Member` tm
            WHERE tm.volunteer = %s

            UNION ALL

            SELECT
                va.activity_type as assignment_type,
                va.role,
                COALESCE(va.description, va.name) as reference,
                va.start_date,
                va.end_date,
                CASE WHEN va.status = 'Active' THEN 1 ELSE 0 END as is_active,
                va.status
            FROM `tabVolunteer Activity` va
            WHERE va.volunteer = %s

            ORDER BY start_date DESC
        """,
            (self.name, self.name, self.name),
            as_dict=True,
        )

        # Convert to the expected format
        history = []
        for data in history_data:
            history.append(
                {
                    "assignment_type": data.assignment_type,
                    "role": data.role,
                    "reference": data.reference,
                    "start_date": data.start_date,
                    "end_date": data.end_date,
                    "is_active": bool(data.is_active),
                    "status": data.status,
                }
            )

        # Add assignment history from the child table (for historical records)
        for item in self.assignment_history:
            history.append(
                {
                    "assignment_type": item.assignment_type,
                    "role": item.role,
                    "reference": f"{item.reference_doctype}: {item.reference_name}"
                    if item.reference_doctype
                    else "",
                    "start_date": item.start_date,
                    "end_date": item.end_date,
                    "is_active": False,
                    "status": item.status,
                }
            )

        # Sort by start date (newest first)
        history.sort(
            key=lambda x: getdate(x.get("start_date")) if x.get("start_date") else getdate("1900-01-01"),
            reverse=True,
        )

        return history

    def get_volunteer_history_fallback(self):
        """Fallback method using individual queries"""
        history = []

        # Get board assignment history using Query Builder and consistent volunteer identification
        CBM = DocType("Chapter Board Member")
        board_history = (
            frappe.qb.from_(CBM)
            .select(
                frappe.qb.terms.ValueWrapper("Board Position").as_("assignment_type"),
                CBM.chapter_role.as_("role"),
                CBM.parent.as_("reference"),
                CBM.from_date.as_("start_date"),
                CBM.to_date.as_("end_date"),
                CBM.is_active,
            )
            .where(CBM.volunteer == self.name)
        ).run(as_dict=True)

        for item in board_history:
            history.append(
                {
                    "assignment_type": item.assignment_type,
                    "role": item.role,
                    "reference": item.reference,
                    "start_date": item.start_date,
                    "end_date": item.end_date,
                    "is_active": item.is_active,
                    "status": "Active" if item.is_active else "Completed",
                }
            )

        # Get team assignment history using Query Builder
        TM = DocType("Team Member")
        team_history = (
            frappe.qb.from_(TM)
            .select(
                frappe.qb.terms.ValueWrapper("Team").as_("assignment_type"),
                TM.role,
                TM.parent.as_("reference"),
                TM.from_date.as_("start_date"),
                TM.to_date.as_("end_date"),
                TM.status,
            )
            .where(TM.volunteer == self.name)
        ).run(as_dict=True)

        for item in team_history:
            history.append(
                {
                    "assignment_type": item.assignment_type,
                    "role": item.role,
                    "reference": item.reference,
                    "start_date": item.start_date,
                    "end_date": item.end_date,
                    "is_active": item.status == "Active",
                    "status": item.status,
                }
            )

        # Get activity history
        activity_history = frappe.get_all(
            "Volunteer Activity",
            filters={"volunteer": self.name},
            fields=[
                "activity_type as assignment_type",
                "role",
                "description as reference",
                "start_date",
                "end_date",
                "status",
                "name",
            ],
        )

        for item in activity_history:
            history.append(
                {
                    "assignment_type": item.assignment_type,
                    "role": item.role,
                    "reference": item.reference or item.name,
                    "start_date": item.start_date,
                    "end_date": item.end_date,
                    "is_active": item.status == "Active",
                    "status": item.status,
                }
            )

        # Add assignment history from the child table (for historical records)
        for item in self.assignment_history:
            history.append(
                {
                    "assignment_type": item.assignment_type,
                    "role": item.role,
                    "reference": f"{item.reference_doctype}: {item.reference_name}"
                    if item.reference_doctype
                    else "",
                    "start_date": item.start_date,
                    "end_date": item.end_date,
                    "is_active": False,
                    "status": item.status,
                }
            )

        # Sort by start date (newest first)
        history.sort(
            key=lambda x: getdate(x.get("start_date")) if x.get("start_date") else getdate("1900-01-01"),
            reverse=True,
        )

        return history

    def has_active_assignments_optimized(self):
        """Optimized query to check if volunteer has any active assignments"""
        result = frappe.db.sql(
            """
            SELECT 1 FROM (
                SELECT 1 FROM `tabChapter Board Member` cbm
                WHERE cbm.volunteer = %s AND cbm.is_active = 1
                LIMIT 1

                UNION ALL

                SELECT 1 FROM `tabTeam Member` tm
                WHERE tm.volunteer = %s AND tm.status = 'Active'
                LIMIT 1

                UNION ALL

                SELECT 1 FROM `tabVolunteer Activity` va
                WHERE va.volunteer = %s AND va.status = 'Active'
                LIMIT 1
            ) as assignments
            LIMIT 1
        """,
            (self.name, self.name, self.name),
        )

        return bool(result)

    @frappe.whitelist()
    def get_skills_by_category(self):
        """Get volunteer skills grouped by category"""
        skills_by_category = {}

        for skill in self.skills_and_qualifications:
            category = skill.skill_category
            if category not in skills_by_category:
                skills_by_category[category] = []

            skills_by_category[category].append(
                {
                    "skill": skill.volunteer_skill,
                    "level": skill.proficiency_level,
                    "experience": skill.experience_years,
                }
            )

        return skills_by_category

    @frappe.whitelist()
    def calculate_total_hours(self):
        """Calculate total volunteer hours from all activities and assignments"""
        total_hours = 0

        # Get hours from volunteer activities
        activities = frappe.get_all(
            "Volunteer Activity", filters={"volunteer": self.name}, fields=["actual_hours", "estimated_hours"]
        )

        for activity in activities:
            # Use actual hours if available, otherwise use estimated hours
            hours = activity.actual_hours or activity.estimated_hours or 0
            total_hours += hours

        # Get hours from assignment history (child table)
        for assignment in self.assignment_history:
            if assignment.actual_hours:
                total_hours += assignment.actual_hours

        return total_hours

    @frappe.whitelist()
    def create_minimal_employee(self):
        """Create a minimal employee record for ERPNext integration using native ERPNext system"""
        try:
            # Check if employee already exists
            if self.employee_id:
                if frappe.db.exists("Employee", self.employee_id):
                    return self.employee_id
                else:
                    # Employee ID exists but record is missing - clear it
                    self.employee_id = None

            # Get default company
            default_company = frappe.defaults.get_global_default("company")
            if not default_company:
                companies = frappe.get_all("Company", limit=1, fields=["name"])
                default_company = companies[0].name if companies else None

            if not default_company:
                frappe.throw(_("No company configured in the system. Please contact the administrator."))

            # Parse volunteer name for first/last name
            name_parts = self.volunteer_name.split() if self.volunteer_name else ["Volunteer"]
            first_name = name_parts[0] if name_parts else "Volunteer"
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            # Get expense approver based on volunteer's board positions and teams (native ERPNext approach)
            expense_approver = self.get_expense_approver_from_assignments()

            # Create minimal employee record with required fields
            employee_data = {
                "doctype": "Employee",
                "employee_name": self.volunteer_name,
                "first_name": first_name,  # Required field
                "last_name": last_name,
                "company": default_company,
                "status": "Active",
                "gender": "Prefer not to say",  # Required field with default
                "date_of_birth": "1990-01-01",  # Required field with default
                "date_of_joining": frappe.utils.today(),  # Required field with today's date
                "expense_approver": expense_approver,  # Direct approver assignment (native ERPNext)
            }

            # Add optional fields if available
            if self.email:
                employee_data["personal_email"] = self.email

            if self.personal_email:
                employee_data["company_email"] = self.personal_email

            # Create employee record
            employee = frappe.get_doc(employee_data)
            employee.insert(ignore_permissions=True)

            # Assign limited employee role for expense declarations
            self.assign_employee_role(employee.name)

            # Update volunteer record with employee ID
            self.employee_id = employee.name
            self.save(ignore_permissions=True)

            # Also update linked Member record with employee ID
            if self.member:
                try:
                    member_doc = frappe.get_doc("Member", self.member)
                    member_doc.employee = employee.name
                    member_doc.save(ignore_permissions=True)
                    frappe.logger().info(f"Updated Member {self.member} with employee ID {employee.name}")
                except Exception as e:
                    frappe.log_error(
                        f"Error updating Member {self.member} with employee ID: {str(e)}",
                        "Member Update Error",
                    )

            frappe.logger().info(
                f"Created minimal employee {employee.name} for volunteer {self.name} with approver {expense_approver}"
            )

            return employee.name

        except Exception as e:
            frappe.log_error(
                f"Error creating minimal employee for volunteer {self.name}: {str(e)}",
                "Employee Creation Error",
            )
            frappe.throw(_("Unable to create employee record: {0}").format(str(e)))

    def get_expense_approver_from_assignments(self):
        """Get appropriate expense approver based on volunteer's assignments (native ERPNext approach)"""
        try:
            # Priority 1: If volunteer is on national board, use national treasurer/financial officer
            settings = frappe.get_single("Verenigingen Settings")
            if settings.national_board_chapter:
                national_board_member = frappe.db.exists(
                    "Chapter Board Member",
                    {"parent": settings.national_board_chapter, "volunteer": self.name, "is_active": 1},
                )

                if national_board_member:
                    # For national board members, find another national board member who can approve
                    national_approver = self.get_board_financial_approver(
                        settings.national_board_chapter, exclude_volunteer=self.name
                    )
                    if national_approver:
                        return national_approver

            # Priority 2: For chapter members, find chapter treasurer/financial officer
            if self.member:
                chapter_memberships = frappe.get_all(
                    "Chapter Member", filters={"member": self.member, "enabled": 1}, fields=["parent"]
                )

                for membership in chapter_memberships:
                    chapter_approver = self.get_board_financial_approver(membership.parent)
                    if chapter_approver:
                        return chapter_approver

            # Priority 3: For team members, find chapter approver through team's chapter
            team_memberships = frappe.get_all(
                "Team Member", filters={"volunteer": self.name, "status": "Active"}, fields=["parent"]
            )

            for team_membership in team_memberships:
                team_doc = frappe.get_doc("Team", team_membership.parent)
                if team_doc.chapter:
                    team_chapter_approver = self.get_board_financial_approver(team_doc.chapter)
                    if team_chapter_approver:
                        return team_chapter_approver

            # Priority 4: Fallback to any system manager with expense approver role
            fallback_approver = frappe.db.get_value(
                "User", {"enabled": 1, "name": ["!=", "Administrator"]}, "name", order_by="creation"
            )

            if fallback_approver:
                # Ensure user has expense approver role
                self.ensure_user_has_expense_approver_role(fallback_approver)
                return fallback_approver

            # Last resort: Administrator
            return "Administrator"

        except Exception as e:
            frappe.log_error(
                f"Error determining expense approver for volunteer {self.name}: {str(e)}",
                "Expense Approver Error",
            )
            return "Administrator"  # Safe fallback

    def get_board_financial_approver(self, chapter_name, exclude_volunteer=None):
        """Get financial approver from chapter board (treasurer, financial officer, etc.)"""
        # Priority order for financial approval roles
        financial_roles = [
            "Treasurer",
            "Financial Officer",
            "Secretary-Treasurer",
            "Board Chair",
            "Secretary",
        ]

        for role in financial_roles:
            board_members = frappe.get_all(
                "Chapter Board Member",
                filters={
                    "parent": chapter_name,
                    "chapter_role": role,
                    "is_active": 1,
                    "volunteer": ["!=", exclude_volunteer] if exclude_volunteer else ["!=", ""],
                },
                fields=["volunteer"],
            )

            for member in board_members:
                volunteer_doc = frappe.get_doc("Volunteer", member.volunteer)
                user_email = volunteer_doc.email or volunteer_doc.personal_email

                if user_email and frappe.db.exists("User", user_email):
                    user = frappe.get_doc("User", user_email)
                    if user.enabled:
                        # Ensure user has expense approver role
                        self.ensure_user_has_expense_approver_role(user_email)
                        return user_email

        return None

    def ensure_user_has_expense_approver_role(self, user_email):
        """Ensure user has expense approver role for ERPNext expense claims"""
        try:
            user = frappe.get_doc("User", user_email)
            user_roles = [r.role for r in user.roles]

            if "Expense Approver" not in user_roles:
                user.append("roles", {"role": "Expense Approver"})
                user.save(ignore_permissions=True)
                frappe.logger().info(f"Added Expense Approver role to user {user_email}")
        except Exception as e:
            frappe.log_error(
                f"Error adding expense approver role to {user_email}: {str(e)}", "Role Assignment Error"
            )

    def assign_employee_role(self, employee_id):
        """Assign limited employee role to the user for expense declarations"""
        try:
            if not self.email:
                frappe.logger().warning(f"No email for volunteer {self.name}, cannot assign employee role")
                return

            # Check if user exists
            if not frappe.db.exists("User", self.email):
                frappe.logger().warning(f"User {self.email} does not exist, cannot assign employee role")
                return

            user_doc = frappe.get_doc("User", self.email)

            # Define the limited employee role
            employee_role = "Employee"

            # Check if user already has the role
            existing_roles = [role.role for role in user_doc.roles]
            if employee_role not in existing_roles:
                # Add the employee role
                user_doc.append("roles", {"role": employee_role})
                user_doc.save(ignore_permissions=True)
                frappe.logger().info(
                    f"Assigned {employee_role} role to user {self.email} for volunteer {self.name}"
                )
            else:
                frappe.logger().info(f"User {self.email} already has {employee_role} role")

        except Exception as e:
            frappe.log_error(
                f"Error assigning employee role for volunteer {self.name}: {str(e)}", "Role Assignment Error"
            )
            # Don't throw here as this is not critical for volunteer creation

    def create_employee_if_needed(self):
        """Create employee record if it doesn't exist, for automatic expense functionality"""
        try:
            # Only create employee if volunteer has email and no existing employee
            if self.email and not self.employee_id:
                # Check if this volunteer is linked to a member with pending application
                if self.member:
                    member = frappe.get_doc("Member", self.member)
                    if member.application_status == "Pending":
                        frappe.logger().info(
                            f"Skipping employee creation for volunteer {self.name} - member application still pending approval"
                        )
                        return
                
                frappe.logger().info(f"Auto-creating employee record for new volunteer: {self.name}")
                employee_id = self.create_minimal_employee()
                if employee_id:
                    frappe.logger().info(
                        f"Successfully auto-created employee {employee_id} for volunteer {self.name}"
                    )
                else:
                    frappe.logger().warning(f"Failed to auto-create employee for volunteer {self.name}")
            else:
                if not self.email:
                    frappe.logger().info(
                        f"Skipping employee creation for volunteer {self.name} - no email address"
                    )
                elif self.employee_id:
                    frappe.logger().info(
                        f"Skipping employee creation for volunteer {self.name} - employee already exists: {self.employee_id}"
                    )

        except Exception as e:
            # Log error but don't fail volunteer creation
            frappe.log_error(
                f"Error auto-creating employee for volunteer {self.name}: {str(e)}",
                "Auto Employee Creation Error",
            )
            frappe.logger().warning(f"Auto employee creation failed for volunteer {self.name}: {str(e)}")

    def get_default_expense_approver(self):
        """Get the default expense approver (treasurer) for expense claims"""
        try:
            # Method 1: Look for treasurer in national board settings
            settings = frappe.get_single("Verenigingen Settings")
            if settings and settings.national_board_chapter:
                # Get board members with financial permissions from national chapter
                # Try to get treasurer first
                board_members = frappe.get_all(
                    "Chapter Board Member",
                    filters={
                        "parent": settings.national_board_chapter,
                        "chapter_role": "Treasurer",
                        "is_active": 1,
                    },
                    fields=["volunteer", "chapter_role"],
                    limit=1,
                )

                # If no treasurer, try other financial roles
                if not board_members:
                    board_members = frappe.get_all(
                        "Chapter Board Member",
                        filters={
                            "parent": settings.national_board_chapter,
                            "chapter_role": [
                                "in",
                                ["Financial Officer", "Secretary-Treasurer", "Board Chair"],
                            ],
                            "is_active": 1,
                        },
                        fields=["volunteer", "chapter_role"],
                        limit=1,
                    )

                for board_member in board_members:
                    # Get the volunteer's email
                    volunteer = frappe.get_doc("Volunteer", board_member.volunteer)
                    if volunteer.email and frappe.db.exists("User", volunteer.email):
                        frappe.logger().info(
                            f"Found default expense approver: {volunteer.email} ({board_member.chapter_role})"
                        )
                        return volunteer.email
                    elif volunteer.personal_email and frappe.db.exists("User", volunteer.personal_email):
                        frappe.logger().info(
                            f"Found default expense approver: {volunteer.personal_email} ({board_member.chapter_role})"
                        )
                        return volunteer.personal_email

            # Method 2: Look for users with "Verenigingen Administrator" role
            admin_users = frappe.get_all(
                "Has Role", filters={"role": "Verenigingen Administrator"}, fields=["parent"]
            )

            for admin in admin_users:
                user = frappe.get_doc("User", admin.parent)
                if user.enabled and user.email:
                    frappe.logger().info(
                        f"Using Verenigingen Administrator as default expense approver: {user.email}"
                    )
                    return user.email

            # Method 3: Fallback to system manager
            system_managers = frappe.get_all(
                "Has Role", filters={"role": "System Manager"}, fields=["parent"]
            )

            for manager in system_managers:
                user = frappe.get_doc("User", manager.parent)
                if user.enabled and user.email and user.email != "Administrator":
                    frappe.logger().info(f"Using System Manager as fallback expense approver: {user.email}")
                    return user.email

            # Method 4: Last resort - use Administrator
            frappe.logger().warning("No suitable expense approver found, using Administrator as fallback")
            return "Administrator"

        except Exception as e:
            frappe.log_error(f"Error getting default expense approver: {str(e)}", "Expense Approver Error")
            frappe.logger().warning(f"Error finding expense approver, using Administrator: {str(e)}")
            return "Administrator"


# Integration functions to be called from other doctypes


@frappe.whitelist()
def create_volunteer_from_member(member_doc):
    """Create or update volunteer record from member and automatically create user account"""
    try:
        if not member_doc:
            return None

        if isinstance(member_doc, str):
            member_doc = frappe.get_doc("Member", member_doc)

        if not member_doc.email:
            frappe.msgprint(_("Member does not have an email address. Cannot create volunteer record."))
            return None

        # Note: We allow volunteer creation even if member already has a user account
        # The volunteer will get an organization email address for volunteer activities

        # Check if volunteer record already exists
        existing_volunteer = frappe.db.exists("Volunteer", {"member": member_doc.name})

        if existing_volunteer:
            existing_vol = frappe.get_doc("Volunteer", existing_volunteer)
            if existing_vol.status not in ["Inactive", "Cancelled"]:
                frappe.throw(
                    _("Member {0} already has an active volunteer record: {1}").format(
                        member_doc.full_name, existing_volunteer
                    )
                )
            else:
                # Reactivate existing inactive volunteer record
                existing_vol.status = "Active"
                existing_vol.save()
                frappe.msgprint(
                    _("Reactivated existing volunteer record for {0}").format(member_doc.full_name)
                )
                return existing_vol

        # Generate organization email based on full name including middle names/particles
        domain = (
            frappe.db.get_single_value("Verenigingen Settings", "organization_email_domain") or "example.org"
        )
        name_for_email = member_doc.full_name.replace(" ", ".").lower() if member_doc.full_name else ""

        # Clean up special characters but preserve name particles (van, de, etc.)
        import re

        # Remove special characters except dots and letters, but keep the name particles
        name_for_email = re.sub(r"[^a-z\.]", "", name_for_email)
        # Clean up multiple consecutive dots and trim dots from ends
        name_for_email = re.sub(r"\.+", ".", name_for_email).strip(".")

        org_email = f"{name_for_email}@{domain}" if name_for_email else ""

        # Create new volunteer record
        volunteer = frappe.new_doc("Volunteer")

        # Use proper Dutch naming if applicable
        if member_doc.full_name:
            # Use the member's properly formatted full_name (which includes Dutch naming if applicable)
            volunteer_name = member_doc.full_name
        elif is_dutch_installation() and hasattr(member_doc, "tussenvoegsel") and member_doc.tussenvoegsel:
            # For Dutch installations, format name with tussenvoegsel
            volunteer_name = format_dutch_full_name(
                member_doc.first_name,
                None,  # Don't use middle_name when tussenvoegsel is available
                member_doc.tussenvoegsel,
                member_doc.last_name,
            )
        else:
            # Standard name formatting for non-Dutch installations
            volunteer_name = f"{member_doc.first_name} {member_doc.last_name}".strip()

        volunteer.update(
            {
                "volunteer_name": volunteer_name,
                "member": member_doc.name,
                "email": org_email,
                "personal_email": member_doc.email,
                "preferred_pronouns": getattr(member_doc, "pronouns", ""),
                "status": "New",
                "start_date": getdate(today()),
            }
        )

        volunteer.insert(ignore_permissions=True)

        # Create organization user account if org_email is valid
        user_created = False
        if org_email and org_email != "":
            try:
                user_created = create_organization_user_for_volunteer(volunteer, member_doc)
            except Exception as e:
                frappe.log_error(f"Error creating user account for volunteer {volunteer.name}: {str(e)}")
                frappe.msgprint(
                    _("Volunteer record created, but failed to create user account: {0}").format(str(e))
                )

        success_message = _("Volunteer record created for {0}").format(member_doc.full_name)
        if user_created:
            success_message += _(" with organization user account ({0})").format(volunteer.email)

        if member_doc.user:
            success_message += _(" (member keeps existing personal user account)")

        frappe.msgprint(success_message)
        return volunteer

    except frappe.DoesNotExistError:
        frappe.throw(_("Member record not found"))
    except frappe.ValidationError as e:
        frappe.throw(_("Failed to create volunteer record: {0}").format(str(e)))
    except Exception as e:
        frappe.log_error(f"Error creating volunteer from member: {str(e)}")
        frappe.throw(_("An error occurred while creating the volunteer record"))


@frappe.whitelist()
def sync_chapter_board_members():
    """Sync all chapter board members with volunteer system"""
    # Get all active chapter board members
    board_members = frappe.db.sql(
        """
        SELECT
            cbm.name, cbm.parent as chapter, cbm.member, cbm.chapter_role,
            cbm.from_date, cbm.to_date, cbm.is_active
        FROM `tabChapter Board Member` cbm
        WHERE cbm.is_active = 1
    """,
        as_dict=True,
    )

    updated_count = 0

    for board_member in board_members:
        # Get or create volunteer record
        volunteer = None
        member_doc = frappe.get_doc("Member", board_member.member)

        # Find volunteer by member link
        existing_volunteer = frappe.db.exists("Volunteer", {"member": board_member.member})

        if existing_volunteer:
            volunteer = frappe.get_doc("Volunteer", existing_volunteer)
        else:
            # Create new volunteer from member
            volunteer = create_volunteer_from_member(member_doc)

        if volunteer:
            updated_count += 1

    return {"updated_count": updated_count}


def create_organization_user_for_volunteer(volunteer, member_doc):
    """Link volunteer to existing member user account instead of creating new one"""
    try:
        # Check if member already has a user account from membership approval
        if member_doc.user:
            existing_user = frappe.get_doc("User", member_doc.user)

            # Add volunteer role to existing user if not already present
            existing_roles = [role.role for role in existing_user.roles]
            volunteer_role = "Verenigingen Volunteer"

            if volunteer_role not in existing_roles and frappe.db.exists("Role", volunteer_role):
                existing_user.append("roles", {"role": volunteer_role})
                existing_user.save(ignore_permissions=True)
                frappe.msgprint(_("Added volunteer role to existing user account"))

            # Link existing user to volunteer record
            volunteer.user = existing_user.name
            volunteer.save(ignore_permissions=True)

            frappe.msgprint(
                _("Linked volunteer to existing member user account {0}").format(existing_user.email)
            )
            return True

        # Fallback: if no member user exists, check for organizational email user
        org_email = volunteer.email
        if org_email and frappe.db.exists("User", org_email):
            existing_user = frappe.get_doc("User", org_email)

            # Link existing user to volunteer if not already linked
            if not volunteer.user:
                volunteer.user = existing_user.name
                volunteer.save(ignore_permissions=True)

            frappe.msgprint(_("Linked existing user account {0} to volunteer").format(org_email))
            return True

        # Last resort: create new user account only if no existing user found
        if org_email:
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": org_email,
                    "first_name": member_doc.first_name or "",
                    "last_name": member_doc.last_name or "",
                    "full_name": member_doc.full_name or "",
                    "send_welcome_email": 1,
                    "user_type": "System User",
                    "new_password": frappe.generate_hash(length=12),
                }
            )

            # Add volunteer-related roles
            volunteer_roles = ["Verenigingen Volunteer", "Verenigingen Member"]

            for role in volunteer_roles:
                if frappe.db.exists("Role", role):
                    user.append("roles", {"role": role})

            # Add default system roles for volunteers
            default_roles = ["All"]
            for role in default_roles:
                if frappe.db.exists("Role", role):
                    user.append("roles", {"role": role})

            user.insert(ignore_permissions=True)

            # Link user to volunteer record
            volunteer.user = user.name
            volunteer.save(ignore_permissions=True)

            frappe.logger().info(f"Created new user {org_email} for volunteer {volunteer.name}")
            frappe.msgprint(_("Created new user account {0} for volunteer").format(org_email))
            return True

        return False

    except frappe.DuplicateEntryError:
        frappe.msgprint(_("User account already exists"))
        return False
    except Exception as e:
        frappe.log_error(f"Error linking user to volunteer: {str(e)}")
        raise e


@frappe.whitelist()
def create_from_member(member=None, member_name=None):
    """Create volunteer from member - alias for create_volunteer_from_member"""
    # Handle both 'member' and 'member_name' parameters for compatibility
    target_member = member or member_name

    if not target_member:
        frappe.throw(_("Member is required"))

    return create_volunteer_from_member(target_member)
