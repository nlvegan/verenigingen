# Volunteer Expense Approver Solution - Aligning with ERPNext/HRMS

## Problem Statement
The current implementation tries to set expense approvers based on association-specific roles (team roles, board membership) which isn't accepted by ERPNext. We need a solution that works within ERPNext's department-based approver hierarchy.

## ERPNext/HRMS Official Implementation

### How ERPNext Handles Expense Approvers

1. **Department-Based Hierarchy**
   - Expense approvers are configured at the Department level
   - Departments have an `expense_approvers` child table
   - If an employee has no direct approver, the system looks up the department hierarchy

2. **Approver Selection Logic**
   ```
   1. Check employee.expense_approver first
   2. If not set, check department.expense_approvers
   3. Check parent department if needed (hierarchy)
   4. Error if mandatory and none found
   ```

3. **Key Constraints**
   - Expense approver must be a User (email), not an Employee
   - Single approver model (not multi-level by default)
   - Approver gets "Expense Approver" role automatically
   - Document sharing happens automatically

## Proposed Solution for Verenigingen

### 1. Create Department Structure Mirroring Association Structure

```python
# Department hierarchy example:
National Organization
├── National Board
├── Chapters
│   ├── Chapter Amsterdam
│   │   ├── Chapter Amsterdam Board
│   │   └── Chapter Amsterdam Teams
│   │       ├── Outreach Team
│   │       └── Events Team
│   └── Chapter Rotterdam
│       ├── Chapter Rotterdam Board
│       └── Chapter Rotterdam Teams
└── National Teams
    ├── IT Team
    └── Communications Team
```

### 2. Implementation Steps

#### A. Create Department Setup Script

```python
def setup_association_departments():
    """Create department structure mirroring association hierarchy"""

    # Create root department
    if not frappe.db.exists("Department", "National Organization"):
        root = frappe.get_doc({
            "doctype": "Department",
            "department_name": "National Organization",
            "company": frappe.defaults.get_global_default("company")
        }).insert()

    # Create national board department
    if not frappe.db.exists("Department", "National Board"):
        national_board = frappe.get_doc({
            "doctype": "Department",
            "department_name": "National Board",
            "parent_department": "National Organization",
            "company": frappe.defaults.get_global_default("company")
        }).insert()

        # Add treasurer as expense approver
        add_department_approver(national_board.name, get_national_treasurer())

    # Create departments for each chapter
    for chapter in frappe.get_all("Chapter", filters={"status": "Active"}):
        create_chapter_departments(chapter.name)

    # Create national teams departments
    create_team_departments()

def create_chapter_departments(chapter_name):
    """Create department structure for a chapter"""
    chapter_doc = frappe.get_doc("Chapter", chapter_name)

    # Create main chapter department
    chapter_dept_name = f"Chapter {chapter_doc.chapter_name}"
    if not frappe.db.exists("Department", chapter_dept_name):
        chapter_dept = frappe.get_doc({
            "doctype": "Department",
            "department_name": chapter_dept_name,
            "parent_department": "Chapters",
            "company": frappe.defaults.get_global_default("company")
        }).insert()

    # Create board department
    board_dept_name = f"{chapter_dept_name} Board"
    if not frappe.db.exists("Department", board_dept_name):
        board_dept = frappe.get_doc({
            "doctype": "Department",
            "department_name": board_dept_name,
            "parent_department": chapter_dept_name,
            "company": frappe.defaults.get_global_default("company")
        }).insert()

        # Add chapter treasurer as approver
        treasurer = get_chapter_treasurer(chapter_name)
        if treasurer:
            add_department_approver(board_dept.name, treasurer)
```

#### B. Update Employee Creation to Assign Departments

```python
def create_minimal_employee(self):
    """Enhanced employee creation with department assignment"""

    # ... existing code ...

    # Determine department based on volunteer's primary assignment
    department = self.get_volunteer_department()

    employee_data = {
        "doctype": "Employee",
        "employee_name": self.volunteer_name,
        "first_name": first_name,
        "last_name": last_name,
        "company": default_company,
        "status": "Active",
        "department": department,  # Add department
        # Don't set expense_approver - let department hierarchy handle it
    }

    # ... rest of existing code ...

def get_volunteer_department(self):
    """Determine appropriate department for volunteer"""

    # Check board positions first (highest priority)
    board_positions = frappe.get_all(
        "Chapter Board Member",
        filters={"volunteer": self.name, "is_active": 1},
        fields=["parent", "chapter_role"]
    )

    if board_positions:
        chapter = board_positions[0].parent
        chapter_doc = frappe.get_doc("Chapter", chapter)
        return f"Chapter {chapter_doc.chapter_name} Board"

    # Check team memberships
    team_memberships = frappe.get_all(
        "Team Member",
        filters={"volunteer": self.name, "status": "Active"},
        fields=["parent"]
    )

    if team_memberships:
        team = frappe.get_doc("Team", team_memberships[0].parent)
        if team.chapter:
            chapter_doc = frappe.get_doc("Chapter", team.chapter)
            return f"Chapter {chapter_doc.chapter_name} Teams"
        else:
            return "National Teams"

    # Default to National Organization
    return "National Organization"
```

#### C. Add Department Approvers Based on Roles

```python
def sync_department_approvers():
    """Sync expense approvers from board positions to departments"""

    # Update national board department
    national_treasurer = get_user_with_role("Treasurer", national=True)
    if national_treasurer:
        update_department_approvers("National Board", [national_treasurer])

    # Update each chapter's departments
    for chapter in frappe.get_all("Chapter", filters={"status": "Active"}):
        # Get chapter treasurer or financial officer
        treasurer = get_chapter_treasurer(chapter.name)
        if treasurer:
            dept_name = f"Chapter {chapter.chapter_name} Board"
            update_department_approvers(dept_name, [treasurer])

def update_department_approvers(department_name, approver_emails):
    """Update department's expense approvers"""

    if not frappe.db.exists("Department", department_name):
        return

    dept = frappe.get_doc("Department", department_name)

    # Clear existing approvers
    dept.expense_approvers = []

    # Add new approvers
    for email in approver_emails:
        if frappe.db.exists("User", email):
            dept.append("expense_approvers", {
                "approver": email
            })

    dept.save()
```

### 3. Migration Plan

1. **Create Department Structure**
   - Run setup script to create departments
   - Map existing chapters/teams to departments

2. **Update Existing Employees**
   ```python
   def migrate_existing_employees():
       """Assign departments to existing volunteer employees"""

       volunteers = frappe.get_all("Volunteer",
           filters={"employee_id": ["!=", ""]},
           fields=["name", "employee_id"])

       for volunteer in volunteers:
           vol_doc = frappe.get_doc("Volunteer", volunteer.name)
           department = vol_doc.get_volunteer_department()

           if frappe.db.exists("Employee", volunteer.employee_id):
               frappe.db.set_value("Employee", volunteer.employee_id,
                   "department", department)
   ```

3. **Sync Approvers**
   - Run approver sync to populate department approvers
   - Set up scheduled job to keep them in sync

### 4. Benefits of This Approach

1. **Aligns with ERPNext Standards**
   - Uses built-in department hierarchy
   - Leverages native approval chain lookup
   - Works with future workflow enhancements

2. **Maintains Association Structure**
   - Departments mirror chapters/teams
   - Board members naturally become approvers
   - Hierarchy reflects real organization

3. **Automatic Approver Resolution**
   - No need to manually set approvers
   - Falls back through hierarchy
   - Treasurer at each level handles expenses

4. **Scalable**
   - New chapters automatically get departments
   - Role changes update approvers
   - Works with ERPNext permissions

### 5. Additional Enhancements

#### A. Custom Validation Rules
```python
# In hooks.py
doc_events = {
    "Expense Claim": {
        "validate": "verenigingen.utils.expense_validations.validate_expense_claim"
    }
}

# In expense_validations.py
def validate_expense_claim(doc, method):
    """Custom validations for expense claims"""

    # Prevent self-approval
    if doc.expense_approver == frappe.session.user:
        frappe.throw(_("You cannot approve your own expense claim"))

    # Amount-based routing (optional)
    if doc.total_claim_amount > 1000:
        # Require higher-level approval
        ensure_senior_approver(doc)
```

#### B. Scheduled Sync Job
```python
# In hooks.py
scheduler_events = {
    "daily": [
        "verenigingen.utils.department_sync.sync_association_departments"
    ]
}
```

#### C. UI Improvements
- Show department hierarchy in expense claim form
- Display approver name (not just email)
- Add helper to show approval chain

### 6. Implementation Timeline

1. **Phase 1** (Week 1): Create department structure and setup scripts
2. **Phase 2** (Week 2): Implement employee department assignment
3. **Phase 3** (Week 3): Migrate existing data
4. **Phase 4** (Week 4): Testing and refinement

This solution provides a robust, ERPNext-compliant way to handle expense approvals while maintaining the association's organizational structure.
