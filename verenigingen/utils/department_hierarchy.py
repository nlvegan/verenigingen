import frappe
from frappe import _


class DepartmentHierarchyManager:
    """Manages department hierarchy for expense approval alignment with ERPNext"""

    def __init__(self):
        self.company = frappe.defaults.get_global_default("company")
        if not self.company:
            companies = frappe.get_all("Company", limit=1)
            self.company = companies[0].name if companies else None

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
            chapter_dept = "Chapter {chapter.name}"
            self._ensure_department(chapter_dept, parent="Chapters")

            # Sub-departments
            self._ensure_department(f"{chapter_dept} Board", parent=chapter_dept)
            self._ensure_department(f"{chapter_dept} Teams", parent=chapter_dept)
            self._ensure_department("{chapter_dept} Volunteers", parent=chapter_dept)

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

            dept.insert(ignore_permissions=True)
            frappe.db.commit()
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
                dept_name = f"Chapter {chapter_doc.chapter_name} Board"
                self._update_department_approvers(dept_name, approvers)

                # Also update parent chapter department for fallback
                parent_dept = f"Chapter {chapter_doc.chapter_name}"
                self._update_department_approvers(parent_dept, approvers)

    def _sync_team_approvers(self):
        """Sync approvers for teams that have financial responsibilities"""
        # This is optional - only if teams have their own budgets

    def _get_financial_approvers(self, chapter_name):
        """Get users who can approve expenses for a chapter"""
        approvers = []

        # Priority order: Treasurer, Financial Officer, Secretary-Treasurer, Board Chair
        financial_roles = ["Treasurer", "Financial Officer", "Secretary-Treasurer", "Board Chair"]

        for role in financial_roles:
            board_members = frappe.get_all(
                "Chapter Board Member",
                filters={"parent": chapter_name, "chapter_role": role, "is_active": 1},
                fields=["volunteer"],
            )

            for member in board_members:
                volunteer = frappe.get_doc("Volunteer", member.volunteer)
                user_email = volunteer.email or volunteer.personal_email

                if user_email and frappe.db.exists("User", user_email):
                    user = frappe.get_doc("User", user_email)
                    if user.enabled:
                        approvers.append(user_email)
                        # Add expense approver role if not present
                        self._ensure_expense_approver_role(user_email)

            # Return after finding first valid approver
            if approvers:
                return approvers

        return approvers

    def _update_department_approvers(self, dept_name, approver_emails):
        """Update department's expense approvers"""
        if not frappe.db.exists("Department", dept_name):
            return

        dept = frappe.get_doc("Department", dept_name)

        # Clear existing approvers
        dept.expense_approvers = []

        # Add new approvers
        for email in approver_emails:
            dept.append("expense_approvers", {"approver": email})

        dept.save(ignore_permissions=True)
        frappe.db.commit()

    def _ensure_expense_approver_role(self, user_email):
        """Ensure user has expense approver role"""
        user = frappe.get_doc("User", user_email)

        if "Expense Approver" not in [r.role for r in user.roles]:
            user.append("roles", {"role": "Expense Approver"})
            user.save(ignore_permissions=True)

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
                frappe.db.set_value("Employee", volunteer.employee_id, "department", department)
                updated += 1

        frappe.db.commit()
        return updated


@frappe.whitelist()
def setup_departments():
    """Whitelist function to set up department hierarchy"""
    manager = DepartmentHierarchyManager()
    manager.setup_association_departments()
    return {"success": True, "message": "Department hierarchy created"}


@frappe.whitelist()
def sync_approvers():
    """Whitelist function to sync approvers"""
    manager = DepartmentHierarchyManager()
    manager.sync_all_approvers()
    return {"success": True, "message": "Approvers synced successfully"}


@frappe.whitelist()
def get_volunteer_department(volunteer):
    """Get department for a volunteer"""
    manager = DepartmentHierarchyManager()
    return manager.get_volunteer_department(volunteer)


def update_volunteer_employee_department(doc, method):
    """Hook to update employee department when volunteer is saved"""
    if doc.employee_id and frappe.db.exists("Employee", doc.employee_id):
        manager = DepartmentHierarchyManager()
        department = manager.get_volunteer_department(doc.name)
        frappe.db.set_value("Employee", doc.employee_id, "department", department)
