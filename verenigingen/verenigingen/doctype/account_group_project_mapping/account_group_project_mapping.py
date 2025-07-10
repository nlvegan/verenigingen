import frappe
from frappe.model.document import Document


class AccountGroupProjectMapping(Document):
    def validate(self):
        self.validate_account_group()
        self.validate_tracking_mode()
        self.validate_defaults()
        self.sync_child_table_names()

    def validate_account_group(self):
        """Ensure account group is valid and is a group account"""
        if not self.account_group:
            return

        account = frappe.get_doc("Account", self.account_group)
        if not account.is_group:
            frappe.throw(f"Account {self.account_group} must be a group account")

        if account.root_type not in ["Income", "Expense"]:
            frappe.throw(f"Account {self.account_group} must be an Income or Expense account")

    def validate_tracking_mode(self):
        """Validate tracking mode settings"""
        if self.tracking_mode == "Project Required":
            self.requires_project = 1
        elif self.tracking_mode == "Project Optional":
            self.requires_project = 0
        elif self.tracking_mode == "Cost Center Only":
            self.requires_project = 0
            self.requires_cost_center = 1
        elif self.tracking_mode == "No Tracking":
            self.requires_project = 0
            self.requires_cost_center = 0

    def validate_defaults(self):
        """Validate default values"""
        if self.default_project and not self.requires_project:
            frappe.msgprint("Warning: Default project set but project is not required")

        if self.default_cost_center and not self.requires_cost_center:
            frappe.msgprint("Warning: Default cost center set but cost center is not required")

        # Validate defaults are in valid lists
        if self.default_project and self.valid_projects:
            valid_project_names = [p.project for p in self.valid_projects]
            if self.default_project not in valid_project_names:
                frappe.throw(f"Default project {self.default_project} is not in valid projects list")

        if self.default_cost_center and self.valid_cost_centers:
            valid_cost_center_names = [cc.cost_center for cc in self.valid_cost_centers]
            if self.default_cost_center not in valid_cost_center_names:
                frappe.throw(
                    f"Default cost center {self.default_cost_center} is not in valid cost centers list"
                )

    def sync_child_table_names(self):
        """Sync project and cost center names in child tables"""
        # Sync project names
        for row in self.valid_projects:
            if row.project:
                project_name = frappe.db.get_value("Project", row.project, "project_name")
                row.project_name = project_name

        # Sync cost center names
        for row in self.valid_cost_centers:
            if row.cost_center:
                cost_center_name = frappe.db.get_value("Cost Center", row.cost_center, "cost_center_name")
                row.cost_center_name = cost_center_name


@frappe.whitelist()
def get_account_group_defaults(account_group):
    """Get default project and cost center for an account group"""
    if not account_group:
        return {}

    mapping = frappe.db.get_value(
        "Account Group Project Mapping",
        account_group,
        [
            "default_project",
            "default_cost_center",
            "requires_project",
            "requires_cost_center",
            "tracking_mode",
        ],
        as_dict=True,
    )

    if not mapping:
        return {}

    return mapping


@frappe.whitelist()
def get_valid_projects_for_account_group(account_group):
    """Get valid projects for an account group"""
    if not account_group:
        return []

    mapping = frappe.get_doc("Account Group Project Mapping", account_group)
    if not mapping or not mapping.valid_projects:
        # If no specific projects configured, return all active projects
        return frappe.get_all("Project", filters={"status": "Open"}, fields=["name", "project_name"])

    return [{"name": p.project, "project_name": p.project_name} for p in mapping.valid_projects]


@frappe.whitelist()
def get_valid_cost_centers_for_account_group(account_group):
    """Get valid cost centers for an account group"""
    if not account_group:
        return []

    mapping = frappe.get_doc("Account Group Project Mapping", account_group)
    if not mapping or not mapping.valid_cost_centers:
        # If no specific cost centers configured, return all active cost centers
        return frappe.get_all("Cost Center", filters={"disabled": 0}, fields=["name", "cost_center_name"])

    return [
        {"name": cc.cost_center, "cost_center_name": cc.cost_center_name} for cc in mapping.valid_cost_centers
    ]


@frappe.whitelist()
def validate_account_group_selection(account_group, project=None, cost_center=None):
    """Validate project and cost center selection for an account group"""
    if not account_group:
        return {"valid": True}

    mapping = frappe.db.get_value(
        "Account Group Project Mapping",
        account_group,
        ["requires_project", "requires_cost_center", "tracking_mode"],
        as_dict=True,
    )

    if not mapping:
        return {"valid": True}

    errors = []

    # Check project requirement
    if mapping.requires_project and not project:
        errors.append(f"Project is required for account group {account_group}")

    # Check cost center requirement
    if mapping.requires_cost_center and not cost_center:
        errors.append(f"Cost center is required for account group {account_group}")

    # Validate project is in valid list
    if project:
        valid_projects = get_valid_projects_for_account_group(account_group)
        if valid_projects and project not in [p["name"] for p in valid_projects]:
            errors.append(f"Project {project} is not valid for account group {account_group}")

    # Validate cost center is in valid list
    if cost_center:
        valid_cost_centers = get_valid_cost_centers_for_account_group(account_group)
        if valid_cost_centers and cost_center not in [cc["name"] for cc in valid_cost_centers]:
            errors.append(f"Cost center {cost_center} is not valid for account group {account_group}")

    return {"valid": len(errors) == 0, "errors": errors, "mapping": mapping}


def setup_default_mappings():
    """Setup default mappings for current organization"""
    # This would be called during app installation or setup
    # Create default mappings based on existing account groups

    expense_groups = frappe.get_all(
        "Account", filters={"is_group": 1, "root_type": "Expense"}, fields=["name", "account_name"]
    )

    for group in expense_groups:
        # Skip if mapping already exists
        if frappe.db.exists("Account Group Project Mapping", group.name):
            continue

        # Create default mapping based on account name patterns
        mapping = frappe.new_doc("Account Group Project Mapping")
        mapping.account_group = group.name
        mapping.account_group_type = determine_account_group_type(group.account_name)
        mapping.tracking_mode = determine_tracking_mode(group.account_name)
        mapping.description = f"Auto-generated mapping for {group.account_name}"

        try:
            mapping.save()
        except Exception as e:
            frappe.log_error(f"Error creating default mapping for {group.name}: {e}")


def determine_account_group_type(account_name):
    """Determine account group type based on name patterns"""
    name_lower = account_name.lower()

    if any(term in name_lower for term in ["programma", "program", "campaign", "challenge"]):
        return "Program-Specific"
    elif any(term in name_lower for term in ["event", "evenement", "conference", "workshop"]):
        return "Event-Based"
    elif any(term in name_lower for term in ["bestuur", "board", "management", "admin"]):
        return "Department-Specific"
    elif any(term in name_lower for term in ["project", "ontwikkeling", "development"]):
        return "Project-Driven"
    else:
        return "General Overhead"


def determine_tracking_mode(account_name):
    """Determine tracking mode based on account name patterns"""
    name_lower = account_name.lower()

    if any(term in name_lower for term in ["programma", "program", "project", "event", "evenement"]):
        return "Project Required"
    elif any(term in name_lower for term in ["bestuur", "board", "management"]):
        return "Cost Center Only"
    elif any(term in name_lower for term in ["algemeen", "general", "overig", "other"]):
        return "No Tracking"
    else:
        return "Project Optional"
