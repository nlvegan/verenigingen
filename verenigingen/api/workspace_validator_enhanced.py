#!/usr/bin/env python3
"""
Enhanced Workspace Validator that checks both database and fixtures file
"""

import json
import os
from typing import Dict, List, Set

import frappe

# Security framework imports
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


class EnhancedWorkspaceValidator:
    """Validates workspaces in both database and fixtures file"""

    def __init__(self):
        import frappe

        self.app_path = frappe.get_app_path("verenigingen")
        self.fixtures_path = os.path.join(self.app_path, "fixtures", "workspace.json")
        self.modules_path = os.path.join(self.app_path, "modules.txt")
        self.errors = []
        self.warnings = []
        self.info = []

    def validate_all_workspaces(self) -> Dict:
        """Validate all workspaces in fixtures and database"""

        # Load fixtures
        fixtures_workspaces = self._load_fixtures_workspaces()

        # Get database workspaces
        db_workspaces = self._get_database_workspaces()

        # Compare and validate
        self._compare_fixtures_vs_database(fixtures_workspaces, db_workspaces)

        # Validate each workspace
        for ws_name in set(list(fixtures_workspaces.keys()) + list(db_workspaces.keys())):
            self._validate_workspace(ws_name, fixtures_workspaces.get(ws_name), db_workspaces.get(ws_name))

        return self._generate_summary()

    def _discover_module_workspaces(self) -> List[str]:
        """Discover all workspace files by scanning modules.txt and their workspace directories"""
        workspace_paths = []

        # Read modules.txt to get list of modules
        if not os.path.exists(self.modules_path):
            self.warnings.append(f"modules.txt not found at {self.modules_path}")
            return workspace_paths

        try:
            with open(self.modules_path, "r") as f:
                modules = [line.strip() for line in f.readlines() if line.strip()]

            self.info.append(f"Found {len(modules)} modules in modules.txt: {', '.join(modules)}")

            # For each module, look for workspace directories
            for module in modules:
                # Convert module name to directory name (e.g., "Verenigingen Payments" -> "verenigingen_payments")
                module_dir = module.lower().replace(" ", "_").replace("-", "_")
                module_path = os.path.join(self.app_path, module_dir)

                if os.path.exists(module_path):
                    workspace_dir = os.path.join(module_path, "workspace")
                    if os.path.exists(workspace_dir):
                        # Look for workspace subdirectories
                        for item in os.listdir(workspace_dir):
                            workspace_subdir = os.path.join(workspace_dir, item)
                            if os.path.isdir(workspace_subdir):
                                # Look for JSON file with same name as directory
                                json_file = os.path.join(workspace_subdir, f"{item}.json")
                                if os.path.exists(json_file):
                                    workspace_paths.append(json_file)
                                    self.info.append(f"Found workspace: {json_file}")

        except Exception as e:
            self.errors.append(f"Error discovering module workspaces: {str(e)}")

        return workspace_paths

    def _load_fixtures_workspaces(self) -> Dict:
        """Load workspaces from fixtures file and dynamically discovered module workspaces"""
        workspaces = {}

        # Load from main fixtures file
        if not os.path.exists(self.fixtures_path):
            self.errors.append("Fixtures file not found: " + self.fixtures_path)
        else:
            try:
                with open(self.fixtures_path, "r") as f:
                    workspace_list = json.load(f)

                for ws in workspace_list:
                    workspaces[ws.get("name")] = ws

                self.info.append(f"Loaded {len(workspace_list)} workspaces from main fixtures file")
            except Exception as e:
                self.errors.append(f"Error loading fixtures workspace: {str(e)}")

        # Dynamically discover and load module workspaces
        module_workspace_paths = self._discover_module_workspaces()

        for workspace_path in module_workspace_paths:
            try:
                with open(workspace_path, "r") as f:
                    workspace_data = json.load(f)
                    workspace_name = workspace_data.get("name")
                    if workspace_name:
                        workspaces[workspace_name] = workspace_data
                        self.info.append(f"Loaded module workspace: {workspace_name}")
                    else:
                        self.warnings.append(f"Workspace at {workspace_path} has no name field")
            except Exception as e:
                self.errors.append(f"Error loading workspace from {workspace_path}: {str(e)}")

        self.info.append(f"Loaded {len(workspaces)} workspaces total")
        return workspaces

    def _get_database_workspaces(self) -> Dict:
        """Get all workspaces from database"""
        workspaces = {}

        try:
            # Get workspace names
            workspace_names = frappe.get_all("Workspace", pluck="name")

            for name in workspace_names:
                workspace = frappe.get_doc("Workspace", name)
                workspaces[name] = {
                    "name": workspace.name,
                    "label": workspace.label,
                    "public": workspace.public,
                    "is_hidden": workspace.is_hidden,
                    "module": workspace.module,
                    "links": [
                        {
                            "link_type": link.link_type,
                            "link_to": link.link_to,
                            "label": link.label,
                            "hidden": link.hidden,
                            "type": link.type,
                        }
                        for link in workspace.links
                    ],
                }

            self.info.append(f"Found {len(workspaces)} workspaces in database")

        except Exception as e:
            self.errors.append(f"Error reading database workspaces: {str(e)}")

        return workspaces

    def _compare_fixtures_vs_database(self, fixtures: Dict, database: Dict):
        """Compare fixtures and database workspaces"""

        fixtures_names = set(fixtures.keys())
        db_names = set(database.keys())

        # Check for workspaces only in fixtures
        only_in_fixtures = fixtures_names - db_names
        if only_in_fixtures:
            self.warnings.append(
                f"Workspaces in fixtures but not in database: {', '.join(sorted(only_in_fixtures))}"
            )

        # Check for workspaces only in database
        only_in_db = db_names - fixtures_names
        if only_in_db:
            self.warnings.append(
                f"Workspaces in database but not in fixtures: {', '.join(sorted(only_in_db))}"
            )

        # Check for differences in common workspaces
        common_workspaces = fixtures_names & db_names
        for ws_name in common_workspaces:
            fix_ws = fixtures[ws_name]
            db_ws = database[ws_name]

            # Compare key properties
            if fix_ws.get("public") != db_ws.get("public"):
                self.warnings.append(
                    f"{ws_name}: public setting differs (fixtures={fix_ws.get('public')}, db={db_ws.get('public')})"
                )

            if fix_ws.get("is_hidden") != db_ws.get("is_hidden"):
                self.warnings.append(
                    f"{ws_name}: hidden setting differs (fixtures={fix_ws.get('is_hidden')}, db={db_ws.get('is_hidden')})"
                )

            # Compare link counts
            fix_links = len(fix_ws.get("links", []))
            db_links = len(db_ws.get("links", []))
            if fix_links != db_links:
                self.info.append(f"{ws_name}: link count differs (fixtures={fix_links}, db={db_links})")

    def _validate_workspace(self, name: str, fixtures_data: Dict, db_data: Dict):
        """Validate a specific workspace"""

        # If only in fixtures, check if all doctypes exist
        if fixtures_data and not db_data:
            self._validate_fixtures_workspace(name, fixtures_data)

        # If in database, validate links
        elif db_data:
            self._validate_database_workspace(name, db_data)

    def _validate_fixtures_workspace(self, name: str, workspace: Dict):
        """Validate workspace from fixtures"""

        for link in workspace.get("links", []):
            if link.get("link_type") == "DocType" and link.get("link_to"):
                doctype_name = link["link_to"]

                # Convert to directory name
                dir_name = doctype_name.lower().replace(" ", "_").replace("-", "_")
                doctype_path = f"/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/{dir_name}"

                if not os.path.exists(doctype_path):
                    self.errors.append(f"{name} (fixtures): DocType '{doctype_name}' directory not found")

    def _validate_database_workspace(self, name: str, workspace: Dict):
        """Validate workspace from database"""

        for link in workspace.get("links", []):
            if link.get("link_type") == "DocType" and link.get("link_to"):
                if not frappe.db.exists("DocType", link["link_to"]):
                    self.errors.append(f"{name} (database): DocType '{link['link_to']}' not found")

            elif link.get("link_type") == "Report" and link.get("link_to"):
                if not frappe.db.exists("Report", link["link_to"]):
                    self.warnings.append(f"{name} (database): Report '{link['link_to']}' not found")

    def _generate_summary(self) -> Dict:
        """Generate validation summary"""
        return {
            "status": "failed" if self.errors else "passed",
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
            "summary": {
                "error_count": len(self.errors),
                "warning_count": len(self.warnings),
                "info_count": len(self.info),
            },
        }


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def validate_workspaces_enhanced():
    """Enhanced workspace validation that checks both fixtures and database"""
    validator = EnhancedWorkspaceValidator()
    return validator.validate_all_workspaces()


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def check_workspace_rendering_issue(workspace_name: str = "E-Boekhouden"):
    """Debug why a workspace might not render properly"""

    result = {"workspace_name": workspace_name, "database_check": {}, "possible_issues": []}

    try:
        # Check if workspace exists
        if not frappe.db.exists("Workspace", workspace_name):
            result["database_check"]["exists"] = False
            result["possible_issues"].append("Workspace does not exist in database")
            return result

        workspace = frappe.get_doc("Workspace", workspace_name)
        result["database_check"]["exists"] = True
        result["database_check"]["data"] = {
            "name": workspace.name,
            "label": workspace.label,
            "public": workspace.public,
            "hidden": workspace.is_hidden,
            "module": workspace.module,
            "links_count": len(workspace.links),
            "content": workspace.content[:200] if workspace.content else None,
            "parent_page": workspace.parent_page,
        }

        # Check common issues
        if workspace.is_hidden:
            result["possible_issues"].append("Workspace is marked as hidden")

        if not workspace.public:
            result["possible_issues"].append("Workspace is not public - check user permissions")

        if not workspace.module:
            result["possible_issues"].append("Workspace has no module assigned")

        # Check if module is installed
        if workspace.module and not frappe.db.exists("Module Def", workspace.module):
            result["possible_issues"].append(f"Module '{workspace.module}' not found")

        # Check content structure
        if workspace.content:
            try:
                content_data = json.loads(workspace.content)
                if not isinstance(content_data, list):
                    result["possible_issues"].append("Content is not a valid JSON array")
                elif len(content_data) == 0:
                    result["possible_issues"].append("Content array is empty")
                elif len(content_data) == 1 and content_data[0].get("type") == "card":
                    result["possible_issues"].append("Workspace has only one card element - may appear empty")
            except json.JSONDecodeError:
                result["possible_issues"].append("Content contains invalid JSON")

        else:
            result["possible_issues"].append("Workspace has no content structure")

        # Check permissions
        result["user_permissions"] = {
            "has_read": frappe.has_permission("Workspace", "read", workspace_name),
            "current_user": frappe.session.user,
            "user_roles": frappe.get_roles(),
        }

        if not result["user_permissions"]["has_read"]:
            result["possible_issues"].append("Current user lacks read permission")

    except Exception as e:
        result["error"] = str(e)
        result["possible_issues"].append(f"Error accessing workspace: {str(e)}")

    return result


if __name__ == "__main__":
    # Can be run directly for testing
    print("Running enhanced workspace validation...")
    result = validate_workspaces_enhanced()
    print(json.dumps(result, indent=2))
