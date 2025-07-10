"""
Account Group Project Framework
A configurable system for linking P&L account groups to projects and cost centers.
"""

import frappe
from frappe import _


class AccountGroupProjectFramework:
    """Framework for managing account group to project/cost center mappings"""

    def __init__(self):
        self.cache = {}

    def get_mapping(self, account_group):
        """Get mapping configuration for an account group"""
        if account_group in self.cache:
            return self.cache[account_group]

        mapping = frappe.db.get_value(
            "Account Group Project Mapping",
            account_group,
            [
                "account_group_type",
                "tracking_mode",
                "requires_project",
                "requires_cost_center",
                "default_project",
                "default_cost_center",
                "description",
            ],
            as_dict=True,
        )

        self.cache[account_group] = mapping
        return mapping

    def get_defaults_for_transaction(self, account_group):
        """Get default project and cost center for a transaction"""
        mapping = self.get_mapping(account_group)
        if not mapping:
            return {}

        return {
            "project": mapping.get("default_project"),
            "cost_center": mapping.get("default_cost_center"),
            "requires_project": mapping.get("requires_project", 0),
            "requires_cost_center": mapping.get("requires_cost_center", 0),
        }

    def validate_transaction(self, account_group, project=None, cost_center=None):
        """Validate that a transaction meets account group requirements"""
        mapping = self.get_mapping(account_group)
        if not mapping:
            return {"valid": True, "errors": []}

        errors = []

        # Check project requirement
        if mapping.get("requires_project") and not project:
            errors.append(_("Project is required for account group {0}").format(account_group))

        # Check cost center requirement
        if mapping.get("requires_cost_center") and not cost_center:
            errors.append(_("Cost center is required for account group {0}").format(account_group))

        # Validate project is in valid list
        if project:
            valid_projects = self.get_valid_projects(account_group)
            if valid_projects and project not in [p["name"] for p in valid_projects]:
                errors.append(
                    _("Project {0} is not valid for account group {1}").format(project, account_group)
                )

        # Validate cost center is in valid list
        if cost_center:
            valid_cost_centers = self.get_valid_cost_centers(account_group)
            if valid_cost_centers and cost_center not in [cc["name"] for cc in valid_cost_centers]:
                errors.append(
                    _("Cost center {0} is not valid for account group {1}").format(cost_center, account_group)
                )

        return {"valid": len(errors) == 0, "errors": errors, "mapping": mapping}

    def get_valid_projects(self, account_group):
        """Get valid projects for an account group"""
        mapping_doc = frappe.get_doc("Account Group Project Mapping", account_group)
        if not mapping_doc.valid_projects:
            # Return all active projects if no restriction
            return frappe.get_all("Project", filters={"status": "Open"}, fields=["name", "project_name"])

        return [{"name": p.project, "project_name": p.project_name} for p in mapping_doc.valid_projects]

    def get_valid_cost_centers(self, account_group):
        """Get valid cost centers for an account group"""
        mapping_doc = frappe.get_doc("Account Group Project Mapping", account_group)
        if not mapping_doc.valid_cost_centers:
            # Return all active cost centers if no restriction
            return frappe.get_all("Cost Center", filters={"disabled": 0}, fields=["name", "cost_center_name"])

        return [
            {"name": cc.cost_center, "cost_center_name": cc.cost_center_name}
            for cc in mapping_doc.valid_cost_centers
        ]

    def is_account_group_trackable(self, account_group):
        """Check if an account group should be tracked"""
        mapping = self.get_mapping(account_group)
        if not mapping:
            return False

        return mapping.get("tracking_mode") != "No Tracking"

    def get_account_group_type(self, account_group):
        """Get the type of an account group"""
        mapping = self.get_mapping(account_group)
        if not mapping:
            return "General Overhead"

        return mapping.get("account_group_type", "General Overhead")

    def clear_cache(self):
        """Clear the mapping cache"""
        self.cache = {}


# Global instance
account_group_framework = AccountGroupProjectFramework()


# Convenience functions for external use
@frappe.whitelist()
def get_account_group_defaults(account_group):
    """Get defaults for an account group"""
    return account_group_framework.get_defaults_for_transaction(account_group)


@frappe.whitelist()
def validate_account_group_transaction(account_group, project=None, cost_center=None):
    """Validate a transaction for an account group"""
    return account_group_framework.validate_transaction(account_group, project, cost_center)


@frappe.whitelist()
def get_valid_projects_for_account_group(account_group):
    """Get valid projects for an account group"""
    return account_group_framework.get_valid_projects(account_group)


@frappe.whitelist()
def get_valid_cost_centers_for_account_group(account_group):
    """Get valid cost centers for an account group"""
    return account_group_framework.get_valid_cost_centers(account_group)


def setup_nvv_default_mappings():
    """Setup default mappings for NVV (can be used as template for other organizations)"""

    # Define NVV-specific mapping templates
    nvv_mappings = {
        "Programma Promotie - NVV": {
            "account_group_type": "Program-Specific",
            "tracking_mode": "Project Required",
            "default_cost_center": "content - NVV",
            "description": "Promotion program expenses - requires project tracking",
        },
        "Programma Community - NVV": {
            "account_group_type": "Program-Specific",
            "tracking_mode": "Project Required",
            "default_cost_center": "content - NVV",
            "description": "Community program expenses - requires project tracking",
        },
        "Programma Content - NVV": {
            "account_group_type": "Program-Specific",
            "tracking_mode": "Project Required",
            "default_cost_center": "content - NVV",
            "description": "Content program expenses - requires project tracking",
        },
        "Programma Vegan Magazine - NVV": {
            "account_group_type": "Program-Specific",
            "tracking_mode": "Project Required",
            "default_cost_center": "magazine - NVV",
            "description": "Magazine production expenses - requires project tracking",
        },
        "Programma Vegan Challenge - NVV": {
            "account_group_type": "Program-Specific",
            "tracking_mode": "Project Required",
            "default_cost_center": "content - NVV",
            "description": "Vegan Challenge expenses - requires project tracking",
        },
        "Evenementen - NVV": {
            "account_group_type": "Event-Based",
            "tracking_mode": "Project Required",
            "default_cost_center": "Main - NVV",
            "description": "Event expenses - requires project tracking",
        },
        "Interne evenementen - NVV": {
            "account_group_type": "Event-Based",
            "tracking_mode": "Project Required",
            "default_cost_center": "Main - NVV",
            "description": "Internal event expenses - requires project tracking",
        },
        "Bestuur - NVV": {
            "account_group_type": "Department-Specific",
            "tracking_mode": "Cost Center Only",
            "default_cost_center": "Main - NVV",
            "description": "Board/governance expenses - cost center tracking only",
        },
        "ICT-Kosten - NVV": {
            "account_group_type": "Department-Specific",
            "tracking_mode": "Project Optional",
            "default_cost_center": "Main - NVV",
            "description": "IT expenses - optional project tracking",
        },
        "Personeelskosten - NVV": {
            "account_group_type": "General Overhead",
            "tracking_mode": "No Tracking",
            "description": "Personnel costs - no project tracking required",
        },
        "Algemene kosten - NVV": {
            "account_group_type": "General Overhead",
            "tracking_mode": "No Tracking",
            "description": "General expenses - no project tracking required",
        },
        "Verzekeringen - NVV": {
            "account_group_type": "General Overhead",
            "tracking_mode": "No Tracking",
            "description": "Insurance expenses - no project tracking required",
        },
        "Kantoorkosten - NVV": {
            "account_group_type": "General Overhead",
            "tracking_mode": "No Tracking",
            "description": "Office expenses - no project tracking required",
        },
        "Administratiekosten - NVV": {
            "account_group_type": "General Overhead",
            "tracking_mode": "No Tracking",
            "description": "Administrative expenses - no project tracking required",
        },
        "Afschrijvingen - NVV": {
            "account_group_type": "General Overhead",
            "tracking_mode": "No Tracking",
            "description": "Depreciation - no project tracking required",
        },
    }

    # Create mappings
    for account_group, config in nvv_mappings.items():
        if frappe.db.exists("Account", account_group) and not frappe.db.exists(
            "Account Group Project Mapping", account_group
        ):
            try:
                mapping = frappe.new_doc("Account Group Project Mapping")
                mapping.account_group = account_group
                mapping.account_group_type = config["account_group_type"]
                mapping.tracking_mode = config["tracking_mode"]
                mapping.description = config["description"]

                if config.get("default_cost_center"):
                    mapping.default_cost_center = config["default_cost_center"]

                mapping.save()
                frappe.db.commit()

            except Exception as e:
                frappe.log_error(f"Error creating mapping for {account_group}: {e}")


def generate_organization_setup_guide():
    """Generate setup guide for new organizations"""

    guide = """
    # Account Group Project Mapping Setup Guide

    ## Step 1: Analyze Your Chart of Accounts
    1. Identify which expense account groups are program/project-specific
    2. Identify which are department-specific
    3. Identify which are general overhead

    ## Step 2: Create Project Structure
    1. Create projects for major programs/campaigns
    2. Set up cost centers for departments/programs
    3. Define project templates for recurring activities

    ## Step 3: Configure Mappings
    For each account group, decide:
    - Account Group Type (Program-Specific, Department-Specific, etc.)
    - Tracking Mode (Project Required, Project Optional, Cost Center Only, No Tracking)
    - Default project and/or cost center
    - Valid projects and cost centers (if restrictions needed)

    ## Step 4: Test Configuration
    1. Create test transactions to verify defaults work
    2. Test validation rules
    3. Run reports to ensure data is properly categorized

    ## Common Patterns:
    - Program expenses → Project Required
    - Department expenses → Cost Center Only
    - General overhead → No Tracking
    - Event expenses → Project Required
    - IT/Admin expenses → Project Optional
    """

    return guide
