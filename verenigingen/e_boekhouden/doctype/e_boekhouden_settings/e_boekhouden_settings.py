# Copyright (c) 2025, R.S.P. and contributors
# For license information, please see license.txt

import json

import frappe
import requests
from frappe.model.document import Document
from frappe.utils import now_datetime

from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api


class EBoekhoudenSettings(Document):
    def get_classification_rules(self):
        """Get account classification rules from settings

        Returns:
            dict: Classification configuration with ranges, keywords, and group mappings
                  including group_type_mappings for the AccountClassificationService
        """
        return {
            "use_classification_service": self.get("enable_account_classification_service", 1),
            "strategy": self.get("classification_strategy", "Prefer Groups"),
            "balance_sheet_group_mappings": self._parse_balance_sheet_group_mappings(),
            "pl_group_mappings": self._parse_pl_group_mappings(),
            "group_type_mappings": self._parse_group_type_mappings(),
            "bal_rules": {
                "asset_ranges": self._parse_ranges(self.get("bal_asset_ranges", "")),
                "liability_ranges": self._parse_ranges(self.get("bal_liability_ranges", "")),
                "equity_ranges": self._parse_ranges(self.get("bal_equity_ranges", "")),
                "equity_keywords": self._parse_keywords(self.get("bal_equity_keywords", "")),
            },
            "vw_rules": {
                "income_ranges": self._parse_ranges(self.get("vw_income_ranges", "")),
                "expense_ranges": self._parse_ranges(self.get("vw_expense_ranges", "")),
                "income_keywords": self._parse_keywords(self.get("vw_income_keywords", "")),
                "expense_keywords": self._parse_keywords(self.get("vw_expense_keywords", "")),
            },
        }

    def _parse_group_type_mappings(self):
        """Parse the group_type_mappings child table into the format expected by
        AccountClassificationService.

        Returns:
            dict: Group code to account type mapping in format:
                  {"001": {"account_type": "Fixed Asset", "root_type": "Asset"}, ...}
        """
        mappings = {}
        group_type_mappings = self.get("group_type_mappings", [])

        for row in group_type_mappings:
            if not row.group_code or not row.root_type:
                continue

            mappings[row.group_code] = {
                "account_type": row.account_type or "",
                "root_type": row.root_type,
                "group_name": row.group_name or "",
                "confidence": row.confidence or "High",
                "notes": row.notes or "",
            }

        return mappings

    def _parse_balance_sheet_group_mappings(self):
        """Parse balance sheet account group mappings

        The field contains text like:
        001 Vaste activa
        002 Liquide middelen
        004 Vorderingen
        006 Schulden

        Returns:
            dict: Group code to group name mapping for balance sheet accounts
        """
        mappings_text = self.get("balance_sheet_group_mappings", "")
        if not mappings_text or not mappings_text.strip():
            return {}

        mappings = {}
        for line in mappings_text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            # Split on first space to separate code from name
            parts = line.split(" ", 1)
            if len(parts) >= 2:
                code = parts[0].strip()
                name = parts[1].strip()
                if code and name:
                    mappings[code] = name

        return mappings

    def _parse_pl_group_mappings(self):
        """Parse P&L account group mappings

        The field contains text like:
        055 Opbrengsten
        056 Personeelskosten
        057 Overige kosten

        Returns:
            dict: Group code to group name mapping for P&L accounts
        """
        mappings_text = self.get("pl_group_mappings", "")
        if not mappings_text or not mappings_text.strip():
            return {}

        mappings = {}
        for line in mappings_text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            # Split on first space to separate code from name
            parts = line.split(" ", 1)
            if len(parts) >= 2:
                code = parts[0].strip()
                name = parts[1].strip()
                if code and name:
                    mappings[code] = name

        return mappings

    def _parse_ranges(self, ranges_text):
        """Parse account code ranges from text with validation

        Args:
            ranges_text: Text with ranges like '0000-2999\n1000-1999'

        Returns:
            list: List of (start, end) tuples
        """
        if not ranges_text or not ranges_text.strip():
            return []

        ranges = []
        line_number = 0

        for line in ranges_text.strip().split("\n"):
            line_number += 1
            line = line.strip()
            if not line:
                continue

            if "-" not in line:
                frappe.log_error(
                    f"Range validation error on line {line_number}: '{line}' - Missing '-' separator. "
                    "Expected format: 'start-end' (e.g., '0000-2999')",
                    "Settings Validation Error",
                )
                continue

            parts = line.split("-", 1)
            if len(parts) != 2:
                frappe.log_error(
                    f"Range validation error on line {line_number}: '{line}' - Invalid format. "
                    "Expected format: 'start-end' (e.g., '0000-2999')",
                    "Settings Validation Error",
                )
                continue

            start = parts[0].strip()
            end = parts[1].strip()

            # Validate both start and end exist
            if not start or not end:
                frappe.log_error(
                    f"Range validation error on line {line_number}: '{line}' - Start or end value is empty",
                    "Settings Validation Error",
                )
                continue

            # Validate reasonable length (prevent abuse with extremely long ranges)
            if len(start) > 10 or len(end) > 10:
                frappe.log_error(
                    f"Range validation error on line {line_number}: '{line}' - Account codes longer than 10 characters are not supported",
                    "Settings Validation Error",
                )
                continue

            # Validate start <= end using zero-padded comparison
            max_len = max(len(start), len(end))
            padded_start = start.zfill(max_len)
            padded_end = end.zfill(max_len)

            if padded_start > padded_end:
                frappe.log_error(
                    f"Range validation error on line {line_number}: '{line}' - Start value '{start}' is greater than end value '{end}'. "
                    "Ranges must have start <= end",
                    "Settings Validation Error",
                )
                continue

            ranges.append((start, end))

        # Check for overlaps within the same category
        if len(ranges) > 1:
            self._check_range_overlaps(ranges, ranges_text[:30])  # Pass first 30 chars as category hint

        return ranges

    def _check_range_overlaps(self, ranges, category_hint):
        """Check for overlapping ranges and log warnings

        Args:
            ranges: List of (start, end) tuples
            category_hint: String hint about which category (for error messages)
        """
        for i, (start1, end1) in enumerate(ranges):
            for j, (start2, end2) in enumerate(ranges):
                if i >= j:  # Only check each pair once
                    continue

                # Normalize for comparison
                max_len = max(len(start1), len(end1), len(start2), len(end2))
                padded_start1 = start1.zfill(max_len)
                padded_end1 = end1.zfill(max_len)
                padded_start2 = start2.zfill(max_len)
                padded_end2 = end2.zfill(max_len)

                # Check if ranges overlap
                # Range1 overlaps Range2 if: start1 <= end2 AND start2 <= end1
                if padded_start1 <= padded_end2 and padded_start2 <= padded_end1:
                    # Pass the detail as `message` (Long Text) with a short `title`.
                    # The long string must NOT be the title: frappe.log_error treats
                    # the first positional arg as the title, which is stored in the
                    # 140-char `method` field and raises CharacterLengthExceededError
                    # in strict/test mode — crashing overlap detection.
                    frappe.log_error(
                        message=(
                            f"Range overlap detected in '{category_hint}': "
                            f"Range '{start1}-{end1}' overlaps with '{start2}-{end2}'. "
                            "This may cause unexpected account classification behavior. "
                            "Consider revising your ranges to eliminate overlaps."
                        ),
                        title="Settings Validation Warning",
                    )
                    # Note: We log but don't reject - overlaps might be intentional in some cases

    def _parse_keywords(self, keywords_text):
        """Parse keywords from text

        Args:
            keywords_text: Text with keywords, one per line

        Returns:
            list: List of lowercase keywords
        """
        if not keywords_text or not keywords_text.strip():
            return []

        keywords = []
        for line in keywords_text.strip().split("\n"):
            line = line.strip().lower()
            if line:
                keywords.append(line)

        return keywords

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

    def validate_api_connection(self):
        """Validate API connection without UI side effects.

        Returns:
            dict: {"success": True/False, "error": str (on failure)}

        Use this method for programmatic connection validation before
        starting migrations or imports. Unlike test_connection(), this
        method does not update status fields or show frappe.msgprint messages.
        """
        try:
            session_token = self._get_session_token()
            if not session_token:
                return {
                    "success": False,
                    "error": "Failed to authenticate. Please check your API token.",
                }
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}

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
@high_security_api(operation_type=OperationType.ADMIN)
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
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_grootboekrekeningen():
    """Test method to fetch Chart of Accounts from e-Boekhouden"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        result = settings.get_api_data("Grootboekrekeningen")

        if result["success"]:
            return {
                "success": True,
                "message": "Successfully fetched Chart of Accounts",
                "data_preview": (
                    result["data"][:1000] + "..." if len(result["data"]) > 1000 else result["data"]
                ),
            }
        else:
            return result

    except Exception as e:
        frappe.log_error(f"Error fetching Chart of Accounts: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def parse_groups_and_suggest_cost_centers(group_mappings_text, company):
    """Parse account group mappings text and suggest cost center configuration"""
    import html
    import re

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

            # Split on first whitespace (space or tab) to separate code from name
            # Use regex split to handle tabs and multiple spaces
            parts = re.split(r"\s+", line, maxsplit=1)
            if len(parts) >= 2:
                code = parts[0].strip()
                # Decode HTML entities immediately after parsing
                name = html.unescape(parts[1].strip())
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
    import html
    import re

    # Decode HTML entities (e.g., &#x27; → ')
    cleaned = html.unescape(name.strip())

    # Remove account-specific words (case-insensitive)
    remove_words = ["rekeningen", "grootboek", "accounts"]
    for word in remove_words:
        # Use regex for case-insensitive replacement
        cleaned = re.sub(rf"\b{word}\b", "", cleaned, flags=re.IGNORECASE).strip()

    # Clean up multiple spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

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
@critical_api(operation_type=OperationType.FINANCIAL)
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
            # Debug logging to show why rows are included/excluded
            frappe.logger().info(
                f"Cost Center Mapping Row: code={mapping.group_code}, name={mapping.group_name}, "
                f"create_cc={mapping.create_cost_center}, cc_name={mapping.cost_center_name}"
            )

            if mapping.create_cost_center and mapping.cost_center_name:
                mappings_to_create.append(mapping)
                frappe.logger().info("  → INCLUDED for creation")
            else:
                skip_reason = []
                if not mapping.create_cost_center:
                    skip_reason.append("create_cost_center checkbox not checked")
                if not mapping.cost_center_name:
                    skip_reason.append("cost_center_name is empty")
                frappe.logger().warning(f"  → SKIPPED: {', '.join(skip_reason)}")

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
@high_security_api(operation_type=OperationType.FINANCIAL)
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


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def parse_groups_and_suggest_type_mappings(merge_mode=False):
    """Parse account group mappings and suggest ERPNext account types.

    Reads the balance_sheet_group_mappings and pl_group_mappings text fields
    and generates suggested type mappings based on group codes and names.

    Args:
        merge_mode: If True, only return new groups not already in group_type_mappings.
                   If False (default), return all parsed groups (replacing existing).

    Returns:
        dict: {
            "success": True/False,
            "suggestions": [...],
            "total_groups": int,
            "suggested_count": int,
            "duplicates": [{"code": "...", "name": "...", "existing_name": "..."}],
            "merge_mode": bool,
            "skipped_existing": int  # Only in merge mode
        }
    """
    import html
    import re

    try:
        # Convert string to boolean if needed (from JS)
        if isinstance(merge_mode, str):
            merge_mode = merge_mode.lower() == "true"

        settings = frappe.get_single("E-Boekhouden Settings")

        balance_sheet_text = settings.get("balance_sheet_group_mappings", "") or ""
        pl_text = settings.get("pl_group_mappings", "") or ""

        if not balance_sheet_text.strip() and not pl_text.strip():
            return {
                "success": False,
                "error": "No account group mappings found. Please enter Balance Sheet and/or P&L group mappings first.",
            }

        # Track existing mappings for merge mode and duplicate detection
        existing_mappings = {}
        for row in settings.get("group_type_mappings", []):
            if row.group_code:
                existing_mappings[row.group_code] = row.group_name

        suggestions = []
        duplicates = []
        seen_codes = {}  # Track codes seen in THIS parse (for duplicate detection in source text)
        skipped_existing = 0

        def process_line(line, is_balance_sheet):
            nonlocal skipped_existing
            line = line.strip()
            if not line:
                return

            parts = re.split(r"\s+", line, maxsplit=1)
            if len(parts) >= 2:
                code = parts[0].strip()
                name = html.unescape(parts[1].strip())

                # Check for duplicate in source text
                if code in seen_codes:
                    duplicates.append(
                        {
                            "code": code,
                            "name": name,
                            "existing_name": seen_codes[code],
                            "source": "input_text",
                        }
                    )
                    return  # Skip duplicates from source text

                seen_codes[code] = name

                # In merge mode, skip codes that already exist in saved mappings
                if merge_mode and code in existing_mappings:
                    skipped_existing += 1
                    return

                suggestion = _suggest_account_type_for_group(code, name, is_balance_sheet=is_balance_sheet)
                suggestions.append(suggestion)

        # Parse balance sheet groups
        for line in balance_sheet_text.strip().split("\n"):
            process_line(line, is_balance_sheet=True)

        # Parse P&L groups
        for line in pl_text.strip().split("\n"):
            process_line(line, is_balance_sheet=False)

        suggested_count = len([s for s in suggestions if s.get("root_type")])

        result = {
            "success": True,
            "suggestions": suggestions,
            "total_groups": len(suggestions),
            "suggested_count": suggested_count,
            "duplicates": duplicates,
            "merge_mode": merge_mode,
        }

        if merge_mode:
            result["skipped_existing"] = skipped_existing

        return result

    except Exception as e:
        frappe.log_error(f"Error parsing groups for type mappings: {str(e)}")
        return {"success": False, "error": str(e)}


def _suggest_account_type_for_group(code, name, is_balance_sheet=True):
    """Suggest ERPNext account type based on group code and name.

    Args:
        code: Group code (e.g., "001", "055")
        name: Group name (e.g., "Vaste activa", "Opbrengsten")
        is_balance_sheet: True for balance sheet groups, False for P&L

    Returns:
        dict: Suggestion with group_code, group_name, root_type, account_type, confidence, notes
    """
    name_lower = name.lower()

    # Default values
    suggestion = {
        "group_code": code,
        "group_name": name,
        "root_type": "",
        "account_type": "",
        "confidence": "Medium",
        "notes": "",
    }

    # P&L accounts
    if not is_balance_sheet:
        # Income patterns
        income_keywords = [
            "opbrengst",
            "omzet",
            "verkoop",
            "inkomst",
            "baten",
            "ontvangst",
            "revenue",
            "income",
            "sales",
        ]
        if any(kw in name_lower for kw in income_keywords):
            suggestion["root_type"] = "Income"
            suggestion["account_type"] = "Income Account"
            suggestion["confidence"] = "High"
            suggestion["notes"] = "Income based on group name keywords"
            return suggestion

        # Expense patterns
        expense_keywords = [
            "kosten",
            "uitgaven",
            "lasten",
            "onkosten",
            "afschrijving",
            "expense",
            "cost",
            "personeel",
            "salaris",
        ]
        if any(kw in name_lower for kw in expense_keywords):
            suggestion["root_type"] = "Expense"
            suggestion["account_type"] = "Expense Account"
            suggestion["confidence"] = "High"
            suggestion["notes"] = "Expense based on group name keywords"
            return suggestion

        # Default P&L to Expense (more common)
        suggestion["root_type"] = "Expense"
        suggestion["account_type"] = "Expense Account"
        suggestion["confidence"] = "Low"
        suggestion["notes"] = "Defaulted to Expense for P&L group"
        return suggestion

    # Balance sheet accounts
    # Fixed assets
    fixed_asset_keywords = [
        "vaste activa",
        "materiele activa",
        "immateriele activa",
        "fixed asset",
        "inventaris",
        "machines",
        "gebouw",
    ]
    if any(kw in name_lower for kw in fixed_asset_keywords):
        suggestion["root_type"] = "Asset"
        suggestion["account_type"] = "Fixed Asset"
        suggestion["confidence"] = "High"
        suggestion["notes"] = "Fixed assets based on group name"
        return suggestion

    # Bank/Cash (liquide middelen)
    bank_keywords = ["liquide", "bank", "geld", "kas", "cash", "liquid"]
    if any(kw in name_lower for kw in bank_keywords):
        suggestion["root_type"] = "Asset"
        # Distinguish between bank and cash
        if "kas" in name_lower and "bank" not in name_lower:
            suggestion["account_type"] = "Cash"
        else:
            suggestion["account_type"] = "Bank"
        suggestion["confidence"] = "High"
        suggestion["notes"] = "Bank/Cash based on group name"
        return suggestion

    # Receivables (vorderingen)
    receivable_keywords = ["vordering", "debiteur", "receivable", "te ontvangen"]
    if any(kw in name_lower for kw in receivable_keywords):
        suggestion["root_type"] = "Asset"
        suggestion["account_type"] = "Receivable"
        suggestion["confidence"] = "High"
        suggestion["notes"] = "Receivables based on group name"
        return suggestion

    # Payables (schulden)
    payable_keywords = ["schuld", "crediteur", "te betalen", "payable", "creditor"]
    if any(kw in name_lower for kw in payable_keywords):
        suggestion["root_type"] = "Liability"
        suggestion["account_type"] = "Payable"
        suggestion["confidence"] = "High"
        suggestion["notes"] = "Payables based on group name"
        return suggestion

    # General liabilities
    liability_keywords = ["passiva", "voorziening", "lening", "obligatie", "liability", "provision", "loan"]
    if any(kw in name_lower for kw in liability_keywords):
        suggestion["root_type"] = "Liability"
        suggestion["account_type"] = "Current Liability"
        suggestion["confidence"] = "Medium"
        suggestion["notes"] = "Liability based on group name"
        return suggestion

    # Equity
    equity_keywords = ["eigen vermogen", "kapitaal", "reserve", "equity", "capital", "retained"]
    if any(kw in name_lower for kw in equity_keywords):
        suggestion["root_type"] = "Equity"
        suggestion["account_type"] = "Equity"
        suggestion["confidence"] = "High"
        suggestion["notes"] = "Equity based on group name"
        return suggestion

    # Code-based fallbacks for balance sheet
    first_digit = code[0] if code else ""

    if first_digit in ("0", "1", "2"):
        # Typical asset range in Dutch accounting
        suggestion["root_type"] = "Asset"
        suggestion["account_type"] = ""
        suggestion["confidence"] = "Low"
        suggestion["notes"] = f"Asset suggested based on code range (starts with {first_digit})"
    elif first_digit in ("3", "4"):
        # Could be liability or equity
        suggestion["root_type"] = "Liability"
        suggestion["account_type"] = "Current Liability"
        suggestion["confidence"] = "Low"
        suggestion["notes"] = f"Liability suggested based on code range (starts with {first_digit})"
    else:
        # Leave empty for manual classification
        suggestion["notes"] = "Unable to determine type - please configure manually"

    return suggestion


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def reclassify_accounts_by_group_mappings(dry_run=True):
    """Re-classify existing ERPNext accounts based on configured group type mappings.

    Thin wrapper that delegates to account_hierarchy_service.
    """
    from verenigingen.e_boekhouden.services.account_hierarchy_service import (
        reclassify_accounts_by_group_mappings as _reclassify,
    )

    return _reclassify(dry_run=dry_run)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def reorganize_account_hierarchy(dry_run=True):
    """Reorganize existing accounts into proper group hierarchy based on group_type_mappings.

    Thin wrapper that delegates to account_hierarchy_service.
    """
    from verenigingen.e_boekhouden.services.account_hierarchy_service import (
        reorganize_account_hierarchy as _reorganize,
    )

    return _reorganize(dry_run=dry_run)
