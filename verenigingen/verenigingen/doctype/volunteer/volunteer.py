"""
Volunteer DocType Implementation

This module implements the Volunteer DocType for the Verenigingen association
management system. It manages volunteer registration, assignments, tracking,
and coordination with comprehensive validation and business logic.

Key Features:
    - Volunteer registration and profile management
    - Member integration with shared contact information
    - Assignment tracking and aggregation
    - Age validation and compliance checking
    - Dutch name formatting for localization
    - Address and contact management integration

Business Logic:
    - Volunteers must be at least 16 years old
    - Integration with Member records for shared information
    - Automatic contact information inheritance from linked members
    - Assignment aggregation from multiple sources
    - Date validation and consistency checking

Architecture:
    - Document-based with comprehensive validation hooks
    - Integration with Member DocType for shared data
    - Address and contact system integration
    - Caching for performance optimization
    - Event-driven assignment tracking

Validation Rules:
    - Required field validation with sensible defaults
    - Member link validation and existence checking
    - Age requirement validation (minimum 16 years)
    - Date consistency and logical validation
    - Contact information validation through inheritance

Integration Points:
    - Member DocType for personal information
    - Address and Contact systems for location data
    - Assignment tracking systems
    - Chapter management for volunteer coordination
    - Expense management for volunteer reimbursements

Security Model:
    - Standard document permissions
    - Member-based access controls
    - Assignment visibility controls
    - Personal information protection

Performance Considerations:
    - Cached aggregated assignments
    - Efficient member data lookup
    - Optimized address and contact loading
    - Query optimization for assignment aggregation

Author: Verenigingen Development Team
License: MIT
"""

import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.utils import getdate, today

from verenigingen.utils.dutch_name_utils import format_dutch_full_name, is_dutch_installation
from verenigingen.utils.error_handling import cache_with_ttl


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
        self.validate_volunteer_age()
        self.validate_dates()

    def validate_required_fields(self):
        """Check if required fields are filled"""
        if not self.start_date:
            self.start_date = today()

    def validate_member_link(self):
        """Validate that member link is valid"""
        if self.member and not frappe.db.exists("Member", self.member):
            frappe.throw(_("Member {0} does not exist").format(self.member), frappe.DoesNotExistError)

    def validate_volunteer_age(self):
        """Validate volunteer age requirements"""
        if not self.member:
            return  # Skip if no member linked

        try:
            # Get member's age
            member = frappe.get_doc("Member", self.member)
            if not member.birth_date:
                return  # Skip if no birth date

            # Calculate age or use existing age field
            if hasattr(member, "age") and member.age is not None:
                age = member.age
            else:
                from datetime import date, datetime

                today_date = date.today()
                if isinstance(member.birth_date, str):
                    born = datetime.strptime(member.birth_date, "%Y-%m-%d").date()
                else:
                    born = member.birth_date
                age = (
                    today_date.year
                    - born.year
                    - ((today_date.month, today_date.day) < (born.month, born.day))
                )

            # Get minimum volunteer age from configuration
            from verenigingen.utils.config_manager import ConfigManager

            min_volunteer_age = ConfigManager.get("min_volunteer_age", 12)

            if age < min_volunteer_age:
                frappe.throw(
                    _("Volunteers must be at least {0} years old. Member age: {1}").format(
                        min_volunteer_age, age
                    ),
                    frappe.ValidationError,
                )

        except Exception as e:
            frappe.log_error(
                f"Error validating volunteer age for {self.name}: {str(e)}", "Volunteer Age Validation Error"
            )

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
        # Queue secure account creation instead of immediate processing
        if self.email:
            self.queue_secure_account_creation()
        else:
            frappe.logger().warning(
                f"No email provided for volunteer {self.name} - skipping account creation"
            )

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
                'Verenigingen Chapter Board Member' as source_doctype,
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
                t.team_name as source_name_display,
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

    def _transform_membership_to_assignment(self, membership, config):
        """Transform membership data to standardized assignment format"""
        return {
            "source_type": config["source_type"],
            "source_doctype": config["source_doctype"],
            "source_name": membership[config["source_name_field"]],
            "source_doctype_display": config.get("source_doctype_display", config["source_doctype"]),
            "source_name_display": membership[config["display_name_field"]],
            "role": membership[config["role_field"]],
            "start_date": membership.get("from_date"),
            "end_date": membership.get("to_date"),
            "is_active": config["is_active_func"](membership),
            "editable": config.get("editable", False),
            "source_link": config["source_link_template"].format(
                source_id=membership[config["source_name_field"]]
            ),
        }

    def _build_membership_query(self, child_doctype, parent_doctype, config):
        """Build standardized membership query using Query Builder"""
        ChildDT = DocType(child_doctype)
        ParentDT = DocType(parent_doctype)

        query = (
            frappe.qb.from_(ChildDT)
            .join(ParentDT)
            .on(ChildDT.parent == ParentDT.name)
            .select(
                ChildDT.name.as_("membership_id"),
                ChildDT.parent.as_(config["source_name_field"]),
                *config["select_fields"],
            )
            .where((ChildDT.volunteer == self.name) & config["where_condition"](ChildDT))
        )

        return query.run(as_dict=True)

    def get_board_assignments(self):
        """Get board assignments from Chapter Board Member"""
        CBM = DocType("Chapter Board Member")
        Chapter = DocType("Chapter")

        config = {
            "source_type": "Board Position",
            "source_doctype": "Chapter",
            "source_name_field": "chapter",
            "source_doctype_display": "Chapter",
            "display_name_field": "chapter_name",
            "role_field": "role",
            "editable": False,
            "source_link_template": "/app/chapter/{source_id}",
            "is_active_func": lambda m: bool(m.is_active),
            "where_condition": lambda dt: dt.is_active == 1,
            "select_fields": [
                CBM.chapter_role.as_("role"),
                CBM.from_date,
                CBM.to_date,
                CBM.is_active,
                Chapter.name.as_("chapter_name"),
            ],
        }

        board_memberships = self._build_membership_query("Chapter Board Member", "Chapter", config)

        return [
            self._transform_membership_to_assignment(membership, config) for membership in board_memberships
        ]

    def get_team_assignments(self):
        """Get team assignments from Team Member"""
        TM = DocType("Team Member")
        Team = DocType("Team")

        config = {
            "source_type": "Team",
            "source_doctype": "Team",
            "source_name_field": "team",
            "display_name_field": "team_name",
            "role_field": "role",
            "editable": False,
            "source_link_template": "/app/team/{source_id}",
            "is_active_func": lambda m: m.status == "Active",
            "where_condition": lambda dt: dt.status == "Active",
            "select_fields": [
                TM.role,
                TM.role_type,
                TM.from_date,
                TM.to_date,
                TM.status,
                Team.team_name,
                Team.team_type,
            ],
        }

        team_memberships = self._build_membership_query("Team Member", "Team", config)

        # Transform with special handling for team_type display
        assignments = []
        for membership in team_memberships:
            assignment = self._transform_membership_to_assignment(membership, config)
            # Special case: customize source_doctype_display for teams
            assignment["source_doctype_display"] = f"{membership.team_type or 'Team'}"
            assignments.append(assignment)

        return assignments

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

    # Removed create_minimal_employee method - now handled by secure AccountCreationManager

    def get_expense_approver_from_assignments(self):
        """Get appropriate expense approver based on volunteer's assignments (native ERPNext approach)"""
        try:
            # Priority 1: If volunteer is on national board, use national treasurer/financial officer
            settings = frappe.get_single("Verenigingen Settings")
            if settings.national_board_chapter:
                national_board_member = frappe.db.exists(
                    "Verenigingen Chapter Board Member",
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
                "Verenigingen Chapter Board Member",
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

    # Removed ensure_user_has_expense_approver_role method - now handled by secure AccountCreationManager

    # Removed assign_employee_role method - now handled by secure AccountCreationManager

    def queue_secure_account_creation(self):
        """Queue secure account creation through the AccountCreationManager"""
        try:
            # Import the account creation manager
            from verenigingen.utils.account_creation_manager import queue_account_creation_for_volunteer

            frappe.logger().info(f"Queueing secure account creation for volunteer {self.name}")

            # Queue account creation with proper security validation
            result = queue_account_creation_for_volunteer(volunteer_name=self.name, priority="Normal")

            frappe.logger().info(f"Account creation queued successfully: {result['request_name']}")

            # Optionally notify the user about the process
            if frappe.session.user != "Administrator":
                frappe.publish_realtime(
                    "volunteer_account_creation_queued",
                    {
                        "volunteer_name": self.name,
                        "request_name": result["request_name"],
                        "message": "Account creation has been queued and will be processed shortly",
                    },
                    user=frappe.session.user,
                )

        except Exception as e:
            # Don't fail volunteer creation if account creation queueing fails
            frappe.logger().error(f"Failed to queue account creation for volunteer {self.name}: {str(e)}")
            frappe.log_error(
                f"Account creation queueing failed for volunteer {self.name}: {str(e)}",
                "Volunteer Account Creation Queue Error",
            )


@frappe.whitelist()
def create_from_member(member):
    """Wrapper function for JavaScript compatibility

    Args:
        member: Member name to create volunteer from

    Returns:
        dict: Result from create_volunteer_from_member
    """
    return create_volunteer_from_member(member)


@frappe.whitelist()
def create_volunteer_from_member(member_name, volunteer_name=None, status="New", interested_skills=None):
    """Create a volunteer record from an existing member

    Args:
        member_name: Name of the Member record to create volunteer from
        volunteer_name: Optional custom volunteer name (defaults to member's full name)
        status: Initial volunteer status (default: "New")
        interested_skills: Optional list/string of skills the volunteer is interested in

    Returns:
        dict: Result with volunteer name if successful, error message if failed
    """
    try:
        # Validate member exists
        if not frappe.db.exists("Member", member_name):
            return {"success": False, "error": f"Member {member_name} does not exist"}

        # Check if volunteer already exists for this member
        existing_volunteer = frappe.db.get_value("Volunteer", {"member": member_name}, "name")
        if existing_volunteer:
            return {
                "success": False,
                "error": f"Volunteer record already exists for member {member_name}: {existing_volunteer}",
            }

        # Get member data
        member = frappe.get_doc("Member", member_name)

        # Determine volunteer name
        if not volunteer_name:
            if member.full_name:
                volunteer_name = member.full_name
            elif is_dutch_installation() and hasattr(member, "tussenvoegsel") and member.tussenvoegsel:
                volunteer_name = format_dutch_full_name(
                    member.first_name, None, member.tussenvoegsel, member.last_name
                )
            else:
                volunteer_name = f"{member.first_name} {member.last_name}".strip()

        if not volunteer_name:
            volunteer_name = member.email or f"Volunteer-{member.name}"

        # Create volunteer record
        volunteer_data = {
            "doctype": "Volunteer",
            "volunteer_name": volunteer_name,
            "member": member.name,
            "email": member.email,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "status": status,
            "available": 1,
            "date_joined": frappe.utils.today(),
            "start_date": frappe.utils.today(),
        }

        # Add optional fields if available
        if hasattr(member, "personal_email") and member.personal_email:
            volunteer_data["personal_email"] = member.personal_email
        if hasattr(member, "contact_number") and member.contact_number:
            volunteer_data["contact_number"] = member.contact_number

        volunteer = frappe.get_doc(volunteer_data)

        # Add skills if provided
        if interested_skills:
            if isinstance(interested_skills, str):
                try:
                    import json

                    interested_skills = json.loads(interested_skills)
                except json.JSONDecodeError as e:
                    frappe.log_error(
                        message=f"Failed to parse JSON skills data '{interested_skills}': {str(e)}",
                        title="Volunteer - JSON Parsing Error",
                        reference_doctype="Volunteer",
                        reference_name=volunteer_data.get("name", "New Volunteer"),
                    )
                    # Fallback to treating the string as a single skill
                    interested_skills = [interested_skills]
                except Exception as e:
                    frappe.log_error(
                        message=f"Unexpected error parsing skills data '{interested_skills}': {str(e)}",
                        title="Volunteer - Skills Parsing Error",
                        reference_doctype="Volunteer",
                        reference_name=volunteer_data.get("name", "New Volunteer"),
                    )
                    # Fallback to treating the string as a single skill
                    interested_skills = [interested_skills]

            if isinstance(interested_skills, list):
                for skill in interested_skills:
                    if isinstance(skill, str):
                        volunteer.append(
                            "skills_and_qualifications",
                            {
                                "volunteer_skill": skill,
                                "skill_category": "General",
                                "proficiency_level": "1 - Beginner",
                            },
                        )
                    elif isinstance(skill, dict):
                        volunteer.append(
                            "skills_and_qualifications",
                            {
                                "volunteer_skill": skill.get("name", skill.get("skill", "Unknown")),
                                "skill_category": skill.get("category", "General"),
                                "proficiency_level": skill.get("level", "1 - Beginner"),
                            },
                        )

        # Save volunteer with proper permissions - no bypasses
        # User must have proper permissions to create volunteer records
        volunteer.insert()

        return {
            "success": True,
            "volunteer_name": volunteer.name,
            "volunteer_display_name": volunteer.volunteer_name,
            "message": f"Successfully created volunteer record {volunteer.name} for member {member_name}",
        }

    except frappe.ValidationError as e:
        return {"success": False, "error": f"Validation failed: {str(e)}"}
    except frappe.PermissionError as e:
        return {"success": False, "error": f"Permission denied: {str(e)}"}
    except Exception as e:
        frappe.log_error(
            f"Error creating volunteer from member {member_name}: {str(e)}", "Volunteer Creation Error"
        )
        return {"success": False, "error": f"Failed to create volunteer: {str(e)}"}


@frappe.whitelist()
def search_volunteers_by_skill(skill_name, category=None, min_level=None):
    """Search volunteers by specific skill

    Args:
        skill_name: Skill name to search for (partial match)
        category: Optional skill category filter
        min_level: Optional minimum proficiency level filter

    Returns:
        List of volunteers with matching skills
    """
    conditions = ["v.status = 'Active'"]
    params = {"skill_name": f"%{skill_name}%"}

    if category:
        conditions.append("vs.skill_category = %(category)s")
        params["category"] = category

    if min_level:
        conditions.append("CAST(LEFT(vs.proficiency_level, 1) AS UNSIGNED) >= %(min_level)s")
        params["min_level"] = min_level

    volunteers = frappe.db.sql(
        """
        SELECT DISTINCT
            v.name,
            v.volunteer_name,
            v.status,
            vs.volunteer_skill as matched_skill,
            vs.proficiency_level,
            vs.skill_category
        FROM `tabVolunteer` v
        INNER JOIN `tabVolunteer Skill` vs ON vs.parent = v.name
        WHERE v.status = 'Active'
            AND vs.volunteer_skill LIKE %(skill_name)s
            {additional_conditions}
        ORDER BY
            CAST(LEFT(vs.proficiency_level, 1) AS UNSIGNED) DESC,
            v.volunteer_name
    """.format(
            additional_conditions=" AND " + " AND ".join(conditions[1:]) if len(conditions) > 1 else ""
        ),
        params,
        as_dict=True,
    )

    return volunteers


@frappe.whitelist()
def get_all_skills_list():
    """Get unique list of all skills for autocomplete and overview - cached for performance

    Returns:
        List of unique skills with usage statistics
    """
    return _get_all_skills_list_cached()


@cache_with_ttl(ttl=3600)  # Cache for 1 hour - skills change infrequently
def _get_all_skills_list_cached():
    """Get all skills using modern Query Builder for better type safety"""
    from frappe.query_builder import DocType
    from frappe.query_builder.functions import Avg, Cast, Count

    # Define DocTypes for Query Builder
    VolunteerSkill = DocType("Volunteer Skill")
    Volunteer = DocType("Volunteer")

    try:
        # Modern Query Builder approach for better maintainability
        query = (
            frappe.qb.from_(VolunteerSkill)
            .inner_join(Volunteer)
            .on(VolunteerSkill.parent == Volunteer.name)
            .select(
                VolunteerSkill.volunteer_skill,
                VolunteerSkill.skill_category,
                Count("*").as_("volunteer_count"),
                Avg(Cast(VolunteerSkill.proficiency_level.left(1), "UNSIGNED")).as_("avg_level"),
            )
            .where(
                (VolunteerSkill.volunteer_skill.isnotnull())
                & (VolunteerSkill.volunteer_skill != "")
                & (Volunteer.status == "Active")
            )
            .groupby(VolunteerSkill.volunteer_skill, VolunteerSkill.skill_category)
            .orderby(Count("*"), order=frappe.qb.desc)
            .orderby(VolunteerSkill.volunteer_skill)
            .distinct()
        )

        skills = query.run(as_dict=True)
        return skills

    except Exception as e:
        # Fallback to original SQL if Query Builder fails
        frappe.log_error(f"Query Builder failed for skills query: {str(e)}")

        skills = frappe.db.sql(
            """
            SELECT DISTINCT
                volunteer_skill,
                skill_category,
                COUNT(*) as volunteer_count,
                AVG(CAST(LEFT(proficiency_level, 1) AS UNSIGNED)) as avg_level
            FROM `tabVolunteer Skill` vs
            INNER JOIN `tabVolunteer` v ON vs.parent = v.name
            WHERE vs.volunteer_skill IS NOT NULL
                AND vs.volunteer_skill != ''
                AND v.status = 'Active'
            GROUP BY volunteer_skill, skill_category
            ORDER BY volunteer_count DESC, volunteer_skill
        """,
            as_dict=True,
        )

        return skills


@frappe.whitelist()
def get_skill_suggestions(partial_skill):
    """Get skill suggestions for autocomplete

    Args:
        partial_skill: Partial skill name to search for

    Returns:
        List of skill names matching the partial input
    """
    if not partial_skill or len(partial_skill) < 2:
        return []

    suggestions = frappe.db.sql(
        """
        SELECT DISTINCT volunteer_skill, COUNT(*) as frequency
        FROM `tabVolunteer Skill`
        WHERE volunteer_skill LIKE %(partial)s
            AND volunteer_skill IS NOT NULL
            AND volunteer_skill != ''
        GROUP BY volunteer_skill
        ORDER BY frequency DESC, volunteer_skill
        LIMIT 10
    """,
        {"partial": f"%{partial_skill}%"},
        as_dict=True,
    )

    return [s.volunteer_skill for s in suggestions]


@frappe.whitelist()
def get_volunteers_with_filters(category=None, skill=None, min_level=None, max_results=50):
    """Get volunteers with skill-based filters

    Args:
        category: Optional skill category filter
        skill: Optional specific skill filter
        min_level: Optional minimum proficiency level
        max_results: Maximum number of results to return

    Returns:
        List of volunteers matching the filters
    """
    conditions = ["v.status = 'Active'"]
    params = {"max_results": max_results}

    join_clause = ""
    if skill or category or min_level:
        join_clause = "INNER JOIN `tabVolunteer Skill` vs ON vs.parent = v.name"

        if skill:
            conditions.append("vs.volunteer_skill LIKE %(skill)s")
            params["skill"] = f"%{skill}%"
        if category:
            conditions.append("vs.skill_category = %(category)s")
            params["category"] = category
        if min_level:
            conditions.append("CAST(LEFT(vs.proficiency_level, 1) AS UNSIGNED) >= %(min_level)s")
            params["min_level"] = min_level

    # Build skills summary field based on whether we're joining skills table
    if join_clause:
        skills_field = """GROUP_CONCAT(DISTINCT CONCAT(vs.volunteer_skill, ' (', vs.proficiency_level, ')')
            ORDER BY vs.skill_category, vs.volunteer_skill SEPARATOR ', ') as skills_summary"""
    else:
        skills_field = "NULL as skills_summary"

    volunteers = frappe.db.sql(
        """
        SELECT DISTINCT
            v.name,
            v.volunteer_name,
            v.status,
            v.email,
            {skills_field}
        FROM `tabVolunteer` v
        {join_clause}
        WHERE {conditions}
        GROUP BY v.name
        ORDER BY v.volunteer_name
        LIMIT %(max_results)s
    """.format(
            skills_field=skills_field, join_clause=join_clause, conditions=" AND ".join(conditions)
        ),
        params,
        as_dict=True,
    )

    return volunteers


@frappe.whitelist()
def get_skill_insights():
    """Get skill insights for dashboard

    Returns:
        Dictionary with popular skills, skill gaps, and category distribution
    """
    # Most common skills
    popular_skills = frappe.db.sql(
        """
        SELECT volunteer_skill, skill_category, COUNT(*) as count
        FROM `tabVolunteer Skill` vs
        INNER JOIN `tabVolunteer` v ON vs.parent = v.name
        WHERE v.status = 'Active'
            AND vs.volunteer_skill IS NOT NULL
            AND vs.volunteer_skill != ''
        GROUP BY volunteer_skill, skill_category
        ORDER BY count DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    # Skills by category (to identify gaps)
    category_distribution = frappe.db.sql(
        """
        SELECT
            skill_category,
            COUNT(DISTINCT parent) as volunteer_count,
            COUNT(*) as skill_count,
            AVG(CAST(LEFT(proficiency_level, 1) AS UNSIGNED)) as avg_proficiency
        FROM `tabVolunteer Skill` vs
        INNER JOIN `tabVolunteer` v ON vs.parent = v.name
        WHERE v.status = 'Active'
        GROUP BY skill_category
        ORDER BY volunteer_count DESC
    """,
        as_dict=True,
    )

    # High-level skills (Expert level)
    expert_skills = frappe.db.sql(
        """
        SELECT volunteer_skill, skill_category, COUNT(*) as expert_count
        FROM `tabVolunteer Skill` vs
        INNER JOIN `tabVolunteer` v ON vs.parent = v.name
        WHERE v.status = 'Active'
            AND vs.proficiency_level LIKE '5%'
        GROUP BY volunteer_skill, skill_category
        ORDER BY expert_count DESC
        LIMIT 5
    """,
        as_dict=True,
    )

    # Skills in development (from development goals)
    development_skills = frappe.db.sql(
        """
        SELECT skill, COUNT(*) as learner_count
        FROM `tabVolunteer Development Goal` vdg
        INNER JOIN `tabVolunteer` v ON vdg.parent = v.name
        WHERE v.status = 'Active'
            AND vdg.skill IS NOT NULL
            AND vdg.skill != ''
        GROUP BY skill
        ORDER BY learner_count DESC
        LIMIT 5
    """,
        as_dict=True,
    )

    return {
        "popular_skills": popular_skills,
        "category_distribution": category_distribution,
        "expert_skills": expert_skills,
        "development_skills": development_skills,
        "total_skills": len(get_all_skills_list()),
        "total_volunteers_with_skills": frappe.db.count(
            "Volunteer Skill", filters={"parenttype": "Volunteer"}
        ),
    }
