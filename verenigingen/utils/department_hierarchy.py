import frappe
from frappe import _

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api


class DepartmentHierarchyManager:
    """Manages department hierarchy for expense approval alignment with ERPNext"""

    def __init__(self):
        settings = frappe.get_single("Verenigingen Settings")
        if not settings.company:
            frappe.throw(_("Company not configured in Verenigingen Settings"))
        self.company = settings.company

    def setup_association_departments(self):
        """Create complete department structure mirroring association hierarchy"""
        if not self.company:
            frappe.throw(_("No company configured. Cannot create departments."))

        # Create root structure
        self._create_root_departments()

        # Create chapter departments
        self._create_chapter_departments()

        # Create team departments
        self._create_team_departments()

        # Sync approvers
        self.sync_all_approvers()

        frappe.msgprint(_("Department hierarchy created successfully"))

    def _create_root_departments(self):
        """Create root department structure"""
        # National Organization (root)
        self._ensure_department("National Organization", parent=None)

        # Main branches
        self._ensure_department("National Board", parent="National Organization")
        self._ensure_department("Chapters", parent="National Organization")
        self._ensure_department("National Teams", parent="National Organization")
        self._ensure_department("National Committees", parent="National Organization")

    def _create_chapter_departments(self):
        """Create department for each active chapter"""
        chapters = frappe.get_all("Chapter", filters={"published": 1}, fields=["name", "region"])

        for chapter in chapters:
            # Main chapter department
            chapter_dept = f"Chapter {chapter.name}"
            self._ensure_department(chapter_dept, parent="Chapters")

            # Sub-departments
            self._ensure_department(f"{chapter_dept} Board", parent=chapter_dept)
            self._ensure_department(f"{chapter_dept} Teams", parent=chapter_dept)
            self._ensure_department(f"{chapter_dept} Volunteers", parent=chapter_dept)

    def _create_team_departments(self):
        """Create departments for teams"""
        # National teams (no chapter association)
        national_teams = frappe.get_all(
            "Team",
            filters={"chapter": ["is", "not set"], "status": "Active"},
            fields=["name", "team_name", "team_type"],
        )

        for team in national_teams:
            dept_name = "{team.team_name} ({team.team_type or 'Team'})"
            self._ensure_department(dept_name, parent="National Teams")

    def _ensure_department(self, dept_name, parent=None):
        """Create department if it doesn't exist"""
        if not frappe.db.exists("Department", dept_name):
            dept = frappe.get_doc(
                {"doctype": "Department", "department_name": dept_name, "company": self.company}
            )

            if parent:
                dept.parent_department = parent

            result = secure_document_operation(
                operation="insert",
                doc=dept,
                justification=f"Create department {dept_name} for association hierarchy management",
                required_permissions=["Department:create"],
            )

            if not result.success:
                frappe.log_error(
                    f"Failed to create department {dept_name}: {'; '.join(result.errors)}",
                    "Department Creation Security",
                )
                frappe.throw(_("Unable to create department: Security validation failed"))

            return dept

        return frappe.get_doc("Department", dept_name)

    def get_volunteer_department(self, volunteer_name):
        """Determine appropriate department for a volunteer based on their assignments"""
        frappe.get_doc("Volunteer", volunteer_name)

        # Priority 1: Board positions
        board_positions = frappe.get_all(
            "Chapter Board Member",
            filters={"volunteer": volunteer_name, "is_active": 1},
            fields=["parent", "chapter_role"],
            order_by="from_date desc",
        )

        if board_positions:
            chapter = frappe.get_doc("Chapter", board_positions[0].parent)
            return f"Chapter {chapter.name} Board"

        # Priority 2: Team leadership positions
        team_leadership = frappe.db.sql(
            """
            SELECT tm.parent, t.team_name, t.chapter, t.team_type
            FROM `tabTeam Member` tm
            JOIN `tabTeam` t ON tm.parent = t.name
            WHERE tm.volunteer = %s
            AND tm.status = 'Active'
            AND tm.role IN ('Team Lead', 'Team Coordinator', 'Team Secretary')
            ORDER BY tm.from_date DESC
            LIMIT 1
        """,
            volunteer_name,
            as_dict=True,
        )

        if team_leadership:
            team = team_leadership[0]
            if team.chapter:
                chapter = frappe.get_doc("Chapter", team.chapter)
                return f"Chapter {chapter.name} Teams"
            else:
                return f"{team.team_name} ({team.team_type or 'Team'})"

        # Priority 3: Regular team membership
        team_memberships = frappe.db.sql(
            """
            SELECT tm.parent, t.team_name, t.chapter, t.team_type
            FROM `tabTeam Member` tm
            JOIN `tabTeam` t ON tm.parent = t.name
            WHERE tm.volunteer = %s
            AND tm.status = 'Active'
            ORDER BY tm.from_date DESC
            LIMIT 1
        """,
            volunteer_name,
            as_dict=True,
        )

        if team_memberships:
            team = team_memberships[0]
            if team.chapter:
                chapter = frappe.get_doc("Chapter", team.chapter)
                return f"Chapter {chapter.name} Volunteers"
            else:
                return "National Teams"

        # Default: National Organization
        return "National Organization"

    def sync_all_approvers(self):
        """Sync expense approvers from board positions to departments"""
        # National level
        self._sync_national_approvers()

        # Chapter level
        self._sync_chapter_approvers()

        # Team level (if teams have financial officers)
        self._sync_team_approvers()

    def _sync_national_approvers(self):
        """Sync national board approvers"""
        # Get national treasurer or financial officer
        settings = frappe.get_single("Verenigingen Settings")
        if not settings.national_board_chapter:
            return

        approvers = self._get_financial_approvers(settings.national_board_chapter)
        if approvers:
            self._update_department_approvers("National Board", approvers)

    def _sync_chapter_approvers(self):
        """Sync approvers for each chapter"""
        chapters = frappe.get_all("Chapter", filters={"published": 1})

        for chapter in chapters:
            # chapter_doc = frappe.get_doc("Chapter", chapter.name)
            chapter_doc = frappe.get_doc("Chapter", chapter.name)
            approvers = self._get_financial_approvers(chapter.name)

            if approvers:
                # Update chapter board department
                dept_name = f"Chapter {chapter_doc.name} Board"
                self._update_department_approvers(dept_name, approvers)

                # Also update parent chapter department for fallback
                parent_dept = f"Chapter {chapter_doc.name}"
                self._update_department_approvers(parent_dept, approvers)

    def _sync_team_approvers(self):
        """Sync approvers for teams that have financial responsibilities"""
        # This is optional - only if teams have their own budgets

    def sync_chapter_approvers_for_chapter(self, chapter_name):
        """
        Sync approvers for a single chapter to its department.

        Called by board member hooks when financial role holders change.
        More efficient than sync_all_approvers() for single-chapter updates.

        Args:
            chapter_name: Name of the chapter to sync
        """
        if not frappe.db.exists("Chapter", chapter_name):
            frappe.logger().warning(
                f"Cannot sync department approvers: Chapter {chapter_name} does not exist"
            )
            return

        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        approvers = self._get_financial_approvers(chapter_name)

        if approvers:
            # Update chapter board department
            dept_name = f"Chapter {chapter_doc.name} Board"
            self._update_department_approvers(dept_name, approvers)

            # Also update parent chapter department for fallback
            parent_dept = f"Chapter {chapter_doc.name}"
            self._update_department_approvers(parent_dept, approvers)

            frappe.logger().info(
                f"Synced {len(approvers)} approver(s) to departments for chapter {chapter_name}"
            )
        else:
            frappe.logger().debug(f"No financial approvers found for chapter {chapter_name}")

    def _get_financial_approvers(self, chapter_name):
        """Get users who can approve expenses for a chapter"""
        # Priority order: Treasurer, Financial Officer, Secretary-Treasurer, Board Chair
        financial_roles = ["Treasurer", "Financial Officer", "Secretary-Treasurer", "Board Chair"]

        # Single query for all financial roles
        board_members = frappe.get_all(
            "Chapter Board Member",
            filters={"parent": chapter_name, "chapter_role": ["in", financial_roles], "is_active": 1},
            fields=["volunteer", "chapter_role"],
        )

        if not board_members:
            return []

        # Sort by role priority
        role_priority = {role: idx for idx, role in enumerate(financial_roles)}
        board_members.sort(key=lambda x: role_priority.get(x.chapter_role, 999))

        # Process in priority order and return first valid approver
        for member in board_members:
            # Use db.get_value for efficiency - only need email fields
            volunteer_data = frappe.db.get_value(
                "Volunteer", member.volunteer, ["email", "personal_email"], as_dict=True
            )
            if not volunteer_data:
                continue

            user_email = volunteer_data.email or volunteer_data.personal_email

            if user_email:
                # Check if user exists and is enabled in single query
                is_enabled = frappe.db.get_value("User", user_email, "enabled")
                if is_enabled:
                    # Add expense approver role if not present
                    self._ensure_expense_approver_role(user_email)
                    return [user_email]  # Return first valid approver

        return []

    def _update_department_approvers(self, dept_name, approver_emails):
        """Update department's expense approvers"""
        if not frappe.db.exists("Department", dept_name):
            frappe.logger().debug(f"Department {dept_name} does not exist, skipping approver sync")
            return

        dept = frappe.get_doc("Department", dept_name)

        # Validate expense_approvers field exists (requires HRMS)
        if not hasattr(dept, "expense_approvers"):
            frappe.logger().warning(
                f"Department {dept_name} does not have expense_approvers field - HRMS may not be installed"
            )
            return

        # Validate approver emails before clearing existing approvers
        valid_approvers = []
        for email in approver_emails:
            if frappe.db.exists("User", email):
                valid_approvers.append(email)
            else:
                frappe.logger().warning(f"User {email} does not exist, skipping as department approver")

        if not valid_approvers:
            frappe.logger().info(f"No valid approvers found for department {dept_name}")
            return

        # Clear existing approvers and add validated ones
        dept.expense_approvers = []
        for email in valid_approvers:
            dept.append("expense_approvers", {"approver": email})

        result = secure_document_operation(
            operation="save",
            doc=dept,
            justification=f"Update department {dept_name} expense approvers for financial workflow",
            required_permissions=["Department:write"],
        )

        if not result.success:
            frappe.log_error(
                f"Failed to update department approvers for {dept_name}: {'; '.join(result.errors)}",
                "Department Approver Update Security",
            )

    def _ensure_expense_approver_role(self, user_email):
        """Ensure user has expense approver role"""
        user = frappe.get_doc("User", user_email)

        if "Expense Approver" not in [r.role for r in user.roles]:
            user.append("roles", {"role": "Expense Approver"})
            result = secure_document_operation(
                operation="save",
                doc=user,
                justification=f"Add Expense Approver role to user {user_email} for department approval workflow",
                required_permissions=["User:write"],
            )

            if not result.success:
                frappe.log_error(
                    f"Failed to add Expense Approver role to user {user_email}: {'; '.join(result.errors)}",
                    "User Role Update Security",
                )
                # Continue without failing - role addition is not critical to main workflow

    def update_employee_departments(self, volunteer_name=None):
        """Update employee departments for volunteers"""
        filters = {"employee_id": ["!=", ""]}
        if volunteer_name:
            filters["name"] = volunteer_name

        volunteers = frappe.get_all("Volunteer", filters=filters, fields=["name", "employee_id"])

        updated = 0
        for volunteer in volunteers:
            department = self.get_volunteer_department(volunteer.name)

            if frappe.db.exists("Employee", volunteer.employee_id):
                # Only set department if it exists - skip if not created yet
                if department and frappe.db.exists("Department", department):
                    frappe.db.set_value("Employee", volunteer.employee_id, "department", department)
                    updated += 1
                else:
                    frappe.logger().info(
                        f"Skipping employee department update for {volunteer.name}: "
                        f"Department '{department}' does not exist"
                    )

        return updated


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def setup_departments():
    """Whitelist function to set up department hierarchy"""
    manager = DepartmentHierarchyManager()
    manager.setup_association_departments()
    return {"success": True, "message": "Department hierarchy created"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def sync_approvers():
    """Whitelist function to sync approvers"""
    manager = DepartmentHierarchyManager()
    manager.sync_all_approvers()
    return {"success": True, "message": "Approvers synced successfully"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_volunteer_department(volunteer):
    """Get department for a volunteer"""
    manager = DepartmentHierarchyManager()
    return manager.get_volunteer_department(volunteer)


def update_volunteer_employee_department(doc, method):
    """Hook to update employee department when volunteer is saved"""
    if doc.employee_id and frappe.db.exists("Employee", doc.employee_id):
        manager = DepartmentHierarchyManager()
        department = manager.get_volunteer_department(doc.name)

        # Only set department if it exists - don't fail if department hasn't been created yet
        # Departments are created when chapters are saved, but volunteers might be created first
        if department and frappe.db.exists("Department", department):
            frappe.db.set_value("Employee", doc.employee_id, "department", department)
        else:
            frappe.logger().info(
                f"Skipping employee department assignment for {doc.name}: "
                f"Department '{department}' does not exist yet"
            )
