# Copyright (c) 2025, R.S.P. and contributors
# For license information, please see license.txt

import json

import frappe
import requests
from frappe.model.document import Document
from frappe.utils import now_datetime


class EBoekhoudenSettings(Document):
    def test_connection(self):
        """Test connection to e-Boekhouden API"""
        try:
            # Step 1: Get session token using API token
            session_token = self._get_session_token()
            if not session_token:
                self.connection_status = "❌ Failed to get session token"
                self.last_tested = now_datetime()
                frappe.msgprint("Failed to get session token. Check your API token.", indicator="red")
                return False

            # Step 2: Test API call with session token
            headers = {
                "Authorization": session_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            # Test with chart of accounts (ledger) endpoint
            url = f"{self.api_url}/v1/ledger"

            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                # Check if response contains valid JSON data
                try:
                    data = response.json()
                    if "items" in data or isinstance(data, list):
                        self.connection_status = "✅ Connection Successful"
                        self.last_tested = now_datetime()
                        frappe.msgprint("Connection test successful!", indicator="green")
                        return True
                    else:
                        error_msg = "Invalid response format from API"
                        self.connection_status = f"❌ {error_msg}"
                        self.last_tested = now_datetime()
                        frappe.msgprint(f"Connection failed: {error_msg}", indicator="red")
                        return False
                except json.JSONDecodeError:
                    error_msg = "Invalid JSON response from API"
                    self.connection_status = f"❌ {error_msg}"
                    self.last_tested = now_datetime()
                    frappe.msgprint(f"Connection failed: {error_msg}", indicator="red")
                    return False
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                self.connection_status = f"❌ {error_msg}"
                self.last_tested = now_datetime()
                frappe.msgprint(f"Connection failed: {error_msg}", indicator="red")
                return False

        except requests.exceptions.Timeout:
            error_msg = "Connection timeout"
            self.connection_status = f"❌ {error_msg}"
            self.last_tested = now_datetime()
            frappe.msgprint(f"Connection failed: {error_msg}", indicator="red")
            return False

        except Exception as e:
            error_msg = str(e)
            self.connection_status = f"❌ {error_msg}"
            self.last_tested = now_datetime()
            frappe.msgprint(f"Connection failed: {error_msg}", indicator="red")
            return False

    def _get_session_token(self):
        """Get session token using API token"""
        try:
            session_url = f"{self.api_url}/v1/session"
            session_data = {
                "accessToken": self.get_password("api_token"),
                "source": self.source_application or "Verenigingen ERPNext",
            }

            response = requests.post(session_url, json=session_data, timeout=30)

            if response.status_code == 200:
                session_response = response.json()
                return session_response.get("token")
            else:
                frappe.log_error(f"Session token request failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            frappe.log_error(f"Error getting session token: {str(e)}")
            return None

    def get_api_data(self, endpoint, method="GET", params=None):
        """Generic method to call e-Boekhouden API"""
        try:
            # Get session token first
            session_token = self._get_session_token()
            if not session_token:
                return {"success": False, "error": "Failed to get session token"}

            headers = {
                "Authorization": session_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            url = f"{self.api_url}/{endpoint}"

            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=60)
            else:
                response = requests.post(url, headers=headers, json=params, timeout=60)

            if response.status_code == 200:
                return {"success": True, "data": response.text, "raw_response": response}
            else:
                return {"success": False, "error": f"HTTP {response.status_code}: {response.text[:500]}"}

        except Exception as e:
            return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_connection():
    """API method to test connection"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        result = settings.test_connection()
        settings.save()
        return {"success": result}
    except Exception as e:
        frappe.log_error(f"Error testing e-Boekhouden connection: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_grootboekrekeningen():
    """Test method to fetch Chart of Accounts from e-Boekhouden"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        result = settings.get_api_data("Grootboekrekeningen")

        if result["success"]:
            return {
                "success": True,
                "message": "Successfully fetched Chart of Accounts",
                "data_preview": result["data"][:1000] + "..."
                if len(result["data"]) > 1000
                else result["data"],
            }
        else:
            return result

    except Exception as e:
        frappe.log_error(f"Error fetching Chart of Accounts: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def parse_groups_and_suggest_cost_centers(group_mappings_text, company):
    """Parse account group mappings text and suggest cost center configuration"""
    try:
        if not group_mappings_text or not group_mappings_text.strip():
            return {"success": False, "error": "No account group mappings provided"}

        # Parse the text input (same as current logic)
        groups = []
        lines = group_mappings_text.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Split on first space to separate code from name
            parts = line.split(" ", 1)
            if len(parts) >= 2:
                code = parts[0].strip()
                name = parts[1].strip()
                groups.append({"code": code, "name": name})

        if not groups:
            return {"success": False, "error": "No valid account groups found"}

        # Generate cost center suggestions
        suggestions = []
        suggested_count = 0

        for group in groups:
            code = group["code"]
            name = group["name"]

            # Determine if this should be a cost center
            should_create, reason = should_suggest_cost_center(code, name)
            cost_center_name = clean_cost_center_name(name) if should_create else ""

            if should_create:
                suggested_count += 1

            # Check if this might be a group (has potential children)
            is_group = might_be_group_cost_center(code, name, groups)

            suggestions.append(
                {
                    "group_code": code,
                    "group_name": name,
                    "create_cost_center": should_create,
                    "cost_center_name": cost_center_name,
                    "is_group": is_group,
                    "reason": reason,
                    "account_count": 0,  # Could enhance later with actual account count
                }
            )

        return {
            "success": True,
            "suggestions": suggestions,
            "total_groups": len(groups),
            "suggested_count": suggested_count,
        }

    except Exception as e:
        frappe.log_error(f"Error parsing account groups for cost centers: {str(e)}")
        return {"success": False, "error": str(e)}


def should_suggest_cost_center(code, name):
    """Determine if an account group should become a cost center"""
    name_lower = name.lower()

    # Expense groups are prime candidates
    if code.startswith(("5", "6")):  # Personnel costs, other expenses
        if any(keyword in name_lower for keyword in ["personeel", "salaris", "kosten", "uitgaven"]):
            return True, "Expense group - good for cost tracking"

    # Revenue groups for departmental analysis
    if code.startswith("3"):  # Revenue accounts
        if any(keyword in name_lower for keyword in ["opbrengst", "omzet", "verkoop"]):
            return True, "Revenue group - useful for departmental income tracking"

    # Specific departmental or operational indicators
    operational_keywords = [
        "afdeling",
        "departement",
        "team",
        "project",
        "activiteit",
        "programma",
        "campagne",
        "dienst",
        "sector",
    ]
    if any(keyword in name_lower for keyword in operational_keywords):
        return True, "Contains departmental/operational keywords"

    # Cost-related groups
    cost_keywords = ["kosten", "uitgaven", "lasten", "onkosten"]
    if any(keyword in name_lower for keyword in cost_keywords):
        return True, "Cost-related group"

    # Skip balance sheet items that don't need cost tracking
    if code.startswith(("1", "2")):  # Assets, Liabilities
        balance_keywords = ["activa", "passiva", "schuld", "vordering", "bank", "kas"]
        if any(keyword in name_lower for keyword in balance_keywords):
            return False, "Balance sheet item - cost center not needed"

    return False, "Not suitable for cost center tracking"


def clean_cost_center_name(name):
    """Clean and format cost center name"""
    # Remove common prefixes/suffixes that might not be needed
    cleaned = name.strip()

    # Remove account-specific words
    remove_words = ["rekeningen", "grootboek", "accounts"]
    for word in remove_words:
        cleaned = cleaned.replace(word, "").strip()

    # Capitalize first letter
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:] if len(cleaned) > 1 else cleaned.upper()

    return cleaned


def might_be_group_cost_center(code, name, all_groups):
    """Determine if this might be a parent/group cost center"""
    # Check if there are other groups that could be children
    code_prefix = code[:2] if len(code) >= 2 else code

    potential_children = [
        g
        for g in all_groups
        if g["code"] != code and g["code"].startswith(code_prefix) and len(g["code"]) > len(code)
    ]

    return len(potential_children) > 0


@frappe.whitelist()
def create_cost_centers_from_mappings():
    """Create ERPNext cost centers based on configured mappings"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")

        if not settings.cost_center_mappings:
            return {"success": False, "error": "No cost center mappings configured"}

        if not settings.default_company:
            return {"success": False, "error": "Default company not configured"}

        # Validate company exists
        if not frappe.db.exists("Company", settings.default_company):
            return {"success": False, "error": f"Company '{settings.default_company}' does not exist"}

        created_cost_centers = []
        skipped_cost_centers = []
        failed_cost_centers = []

        # First pass: collect all mappings that should create cost centers
        mappings_to_create = []
        for mapping in settings.cost_center_mappings:
            if mapping.create_cost_center and mapping.cost_center_name:
                mappings_to_create.append(mapping)

        if not mappings_to_create:
            return {"success": False, "error": "No cost center mappings are configured for creation"}

        # Sort by hierarchy - create parent groups first
        mappings_to_create.sort(key=lambda x: (0 if x.is_group else 1, x.group_code))

        # Create cost centers
        for mapping in mappings_to_create:
            try:
                result = create_single_cost_center(mapping, settings.default_company)

                if result["success"]:
                    created_cost_centers.append(
                        {
                            "group_code": mapping.group_code,
                            "group_name": mapping.group_name,
                            "cost_center_name": result["cost_center_name"],
                            "cost_center_id": result["cost_center_id"],
                            "is_group": mapping.is_group,
                        }
                    )
                elif result["skipped"]:
                    skipped_cost_centers.append(
                        {
                            "group_code": mapping.group_code,
                            "group_name": mapping.group_name,
                            "cost_center_name": mapping.cost_center_name,
                            "reason": result["reason"],
                        }
                    )
                else:
                    failed_cost_centers.append(
                        {
                            "group_code": mapping.group_code,
                            "group_name": mapping.group_name,
                            "cost_center_name": mapping.cost_center_name,
                            "error": result["error"],
                        }
                    )

            except Exception as e:
                failed_cost_centers.append(
                    {
                        "group_code": mapping.group_code,
                        "group_name": mapping.group_name,
                        "cost_center_name": mapping.cost_center_name,
                        "error": str(e),
                    }
                )

        return {
            "success": True,
            "created_count": len(created_cost_centers),
            "skipped_count": len(skipped_cost_centers),
            "failed_count": len(failed_cost_centers),
            "created_cost_centers": created_cost_centers,
            "skipped_cost_centers": skipped_cost_centers,
            "failed_cost_centers": failed_cost_centers,
            "total_processed": len(mappings_to_create),
        }

    except Exception as e:
        frappe.log_error(f"Error creating cost centers from mappings: {str(e)}")
        return {"success": False, "error": str(e)}


def create_single_cost_center(mapping, company):
    """Create a single cost center from mapping configuration"""
    try:
        cost_center_name = mapping.cost_center_name.strip()

        # Check if cost center already exists
        existing_cost_center = frappe.db.get_value(
            "Cost Center",
            {"cost_center_name": cost_center_name, "company": company},
            ["name", "cost_center_name"],
            as_dict=True,
        )

        if existing_cost_center:
            return {
                "success": False,
                "skipped": True,
                "reason": f"Cost center '{cost_center_name}' already exists as '{existing_cost_center.name}'",
            }

        # Create the cost center document
        cost_center_doc = frappe.new_doc("Cost Center")
        cost_center_doc.cost_center_name = cost_center_name
        cost_center_doc.company = company
        cost_center_doc.is_group = 1 if mapping.is_group else 0

        # Set parent cost center if specified
        if mapping.parent_cost_center:
            if frappe.db.exists("Cost Center", mapping.parent_cost_center):
                cost_center_doc.parent_cost_center = mapping.parent_cost_center
            else:
                frappe.log_error(
                    f"Parent cost center '{mapping.parent_cost_center}' not found for '{cost_center_name}'"
                )

        # If no parent specified, set to company's default cost center (usually company name)
        if not cost_center_doc.parent_cost_center:
            company_cost_center = frappe.db.get_value(
                "Cost Center", {"company": company, "is_group": 1}, "name", order_by="creation asc"
            )
            if company_cost_center:
                cost_center_doc.parent_cost_center = company_cost_center

        # Add description with source information
        cost_center_doc.description = (
            f"Created from eBoekhouden account group: {mapping.group_code} - {mapping.group_name}\\n"
            f"Suggestion reason: {mapping.suggestion_reason or 'User configured'}"
        )

        # Save the document
        cost_center_doc.insert()

        return {
            "success": True,
            "skipped": False,
            "cost_center_name": cost_center_name,
            "cost_center_id": cost_center_doc.name,
        }

    except Exception as e:
        return {"success": False, "skipped": False, "error": str(e)}


def generate_cost_center_id(cost_center_name, company):
    """Generate a unique cost center ID based on name and company"""
    # Start with clean name
    base_name = cost_center_name.strip()

    # Add company suffix if not already present
    if not base_name.endswith(f" - {company}"):
        base_name = f"{base_name} - {company}"

    return base_name


@frappe.whitelist()
def preview_cost_center_creation():
    """Preview what cost centers would be created without actually creating them"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")

        if not settings.cost_center_mappings:
            return {"success": False, "error": "No cost center mappings configured"}

        if not settings.default_company:
            return {"success": False, "error": "Default company not configured"}

        preview_results = []

        for mapping in settings.cost_center_mappings:
            if mapping.create_cost_center and mapping.cost_center_name:
                cost_center_name = mapping.cost_center_name.strip()
                cost_center_id = generate_cost_center_id(cost_center_name, settings.default_company)

                # Check if already exists
                existing = frappe.db.get_value(
                    "Cost Center",
                    {"cost_center_name": cost_center_name, "company": settings.default_company},
                    "name",
                )

                preview_results.append(
                    {
                        "group_code": mapping.group_code,
                        "group_name": mapping.group_name,
                        "cost_center_name": cost_center_name,
                        "cost_center_id": cost_center_id,
                        "is_group": mapping.is_group,
                        "parent_cost_center": mapping.parent_cost_center,
                        "already_exists": bool(existing),
                        "existing_id": existing if existing else None,
                        "action": "Skip (already exists)" if existing else "Create new",
                    }
                )

        return {
            "success": True,
            "preview_results": preview_results,
            "total_to_process": len(preview_results),
            "would_create": len([r for r in preview_results if not r["already_exists"]]),
            "would_skip": len([r for r in preview_results if r["already_exists"]]),
        }

    except Exception as e:
        frappe.log_error(f"Error previewing cost center creation: {str(e)}")
        return {"success": False, "error": str(e)}
