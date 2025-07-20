"""
Setup Account Group Mappings
Creates default mappings for organizations using the framework.
"""

import frappe

from verenigingen.utils.account_group_project_framework import setup_nvv_default_mappings


@frappe.whitelist()
def setup_default_mappings():
    """Setup default mappings for current organization"""
    try:
        setup_nvv_default_mappings()
        return {"success": True, "message": "Default mappings created successfully"}
    except Exception as e:
        frappe.log_error(f"Error setting up default mappings: {e}")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def get_setup_status():
    """Get the setup status of account group mappings"""

    # Count total expense groups
    total_expense_groups = frappe.db.count("Account", {"is_group": 1, "root_type": "Expense"})

    # Count mapped expense groups
    mapped_expense_groups = frappe.db.count("Account Group Project Mapping")

    # Get unmapped groups
    mapped_accounts = frappe.get_all("Account Group Project Mapping", fields=["account_group"])
    mapped_account_names = [m.account_group for m in mapped_accounts]

    all_expense_groups = frappe.get_all(
        "Account", filters={"is_group": 1, "root_type": "Expense"}, fields=["name", "account_name"]
    )

    unmapped_groups = [g for g in all_expense_groups if g.name not in mapped_account_names]

    return {
        "total_expense_groups": total_expense_groups,
        "mapped_expense_groups": mapped_expense_groups,
        "unmapped_groups": unmapped_groups,
        "setup_complete": len(unmapped_groups) == 0,
    }


@frappe.whitelist()
def create_sample_projects():
    """Create sample projects for testing the framework"""

    sample_projects = [
        {
            "project_name": "Vegan Challenge 2025",
            "status": "Open",
            "project_type": "External",
            "is_active": "Yes",
        },
        {
            "project_name": "Magazine Production Q1 2025",
            "status": "Open",
            "project_type": "Internal",
            "is_active": "Yes",
        },
        {
            "project_name": "Community Event - Amsterdam",
            "status": "Open",
            "project_type": "External",
            "is_active": "Yes",
        },
        {
            "project_name": "Content Creation - Video Series",
            "status": "Open",
            "project_type": "Internal",
            "is_active": "Yes",
        },
        {
            "project_name": "Education Program - School Visits",
            "status": "Open",
            "project_type": "External",
            "is_active": "Yes",
        },
    ]

    created_projects = []

    for project_data in sample_projects:
        if not frappe.db.exists("Project", project_data["project_name"]):
            try:
                project = frappe.new_doc("Project")
                project.project_name = project_data["project_name"]
                project.status = project_data["status"]
                project.project_type = project_data["project_type"]
                project.is_active = project_data["is_active"]
                project.save()
                created_projects.append(project.name)
            except Exception as e:
                frappe.log_error(f"Error creating project {project_data['project_name']}: {e}")

    return {
        "created_projects": created_projects,
        "message": "Created {len(created_projects)} sample projects",
    }


@frappe.whitelist()
def update_mappings_with_sample_projects():
    """Update existing mappings with sample projects"""

    # Define which projects are valid for which account groups
    project_mappings = {
        "Programma Promotie - NVV": ["Vegan Challenge 2025", "Community Event - Amsterdam"],
        "Programma Community - NVV": ["Community Event - Amsterdam", "Education Program - School Visits"],
        "Programma Content - NVV": ["Content Creation - Video Series", "Magazine Production Q1 2025"],
        "Programma Vegan Magazine - NVV": ["Magazine Production Q1 2025"],
        "Programma Vegan Challenge - NVV": ["Vegan Challenge 2025"],
        "Evenementen - NVV": ["Community Event - Amsterdam"],
        "Interne evenementen - NVV": ["Community Event - Amsterdam"],
    }

    updated_mappings = []

    for account_group, project_names in project_mappings.items():
        if frappe.db.exists("Account Group Project Mapping", account_group):
            try:
                mapping = frappe.get_doc("Account Group Project Mapping", account_group)

                # Clear existing valid projects
                mapping.valid_projects = []

                # Add new valid projects
                for project_name in project_names:
                    if frappe.db.exists("Project", project_name):
                        mapping.append("valid_projects", {"project": project_name})

                mapping.save()
                updated_mappings.append(account_group)

            except Exception as e:
                frappe.log_error(f"Error updating mapping for {account_group}: {e}")

    return {
        "updated_mappings": updated_mappings,
        "message": "Updated {len(updated_mappings)} mappings with sample projects",
    }


@frappe.whitelist()
def get_framework_overview():
    """Get overview of the framework setup"""

    setup_status = get_setup_status()

    # Get mapping statistics
    mapping_stats = frappe.db.sql(
        """
        SELECT
            account_group_type,
            tracking_mode,
            COUNT(*) as count
        FROM `tabAccount Group Project Mapping`
        GROUP BY account_group_type, tracking_mode
    """,
        as_dict=True,
    )

    # Get projects count
    projects_count = frappe.db.count("Project", {"status": "Open"})

    # Get cost centers count
    cost_centers_count = frappe.db.count("Cost Center", {"disabled": 0})

    return {
        "setup_status": setup_status,
        "mapping_stats": mapping_stats,
        "projects_count": projects_count,
        "cost_centers_count": cost_centers_count,
        "framework_active": True,
    }


def run_full_setup():
    """Run complete setup for NVV"""

    results = {}

    # Step 1: Create default mappings
    results["mappings"] = setup_default_mappings()

    # Step 2: Create sample projects
    results["projects"] = create_sample_projects()

    # Step 3: Update mappings with projects
    results["project_mappings"] = update_mappings_with_sample_projects()

    # Step 4: Get final overview
    results["overview"] = get_framework_overview()

    return results
