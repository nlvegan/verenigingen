#!/usr/bin/env python3
"""
Enhanced Workspace Content Validator
Catches content field vs Card Break synchronization issues
"""

import json
from typing import Any, Dict, List, Tuple

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, standard_api


class WorkspaceContentValidator:
    """Validates workspace content field synchronization with database structure"""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = []

    def validate_workspace_content_sync(self, workspace_name: str) -> Dict[str, Any]:
        """Validate content field synchronization with Card Break structure"""

        try:
            workspace = frappe.get_doc("Workspace", workspace_name)
        except:
            self.errors.append(f"Workspace '{workspace_name}' not found")
            return self._generate_result()

        # Parse content field
        content_structure = self._parse_content_field(workspace.content)

        # Get Card Break structure from database
        card_break_structure = self._get_card_break_structure(workspace_name)

        # Analyze synchronization
        sync_analysis = self._analyze_content_sync(content_structure, card_break_structure)

        # Check for empty sections (headers without cards)
        empty_sections = self._detect_empty_sections(content_structure)

        # Validate section hierarchy
        hierarchy_issues = self._validate_section_hierarchy(content_structure)

        return {
            **self._generate_result(),
            "workspace_name": workspace_name,
            "content_structure": content_structure,
            "card_break_structure": card_break_structure,
            "sync_analysis": sync_analysis,
            "empty_sections": empty_sections,
            "hierarchy_issues": hierarchy_issues,
            "is_synchronized": len(sync_analysis["content_only"]) == 0 and len(sync_analysis["db_only"]) == 0,
            "has_empty_sections": len(empty_sections) > 0,
        }

    def _parse_content_field(self, content_json: str) -> Dict[str, Any]:
        """Parse workspace content field and extract structure"""

        if not content_json:
            self.warnings.append("Workspace has no content field")
            return {"items": [], "cards": [], "headers": [], "sections": []}

        try:
            content_items = json.loads(content_json)
        except json.JSONDecodeError as e:
            self.errors.append(f"Invalid JSON in content field: {str(e)}")
            return {"items": [], "cards": [], "headers": [], "sections": []}

        cards = []
        headers = []
        sections = []
        current_section = None

        for i, item in enumerate(content_items):
            item_type = item.get("type")

            if item_type == "header":
                # Extract header text without HTML
                import re

                header_text = item.get("data", {}).get("text", "")
                clean_text = re.sub(r"<[^>]+>", "", header_text)
                header_info = {"index": i, "text": clean_text, "raw_html": header_text}
                headers.append(header_info)

                # Start new section
                if current_section:
                    sections.append(current_section)
                current_section = {"header": header_info, "cards": [], "has_cards": False}

            elif item_type == "card":
                card_name = item.get("data", {}).get("card_name")
                card_info = {"index": i, "name": card_name, "col": item.get("data", {}).get("col", 4)}
                cards.append(card_info)

                # Add to current section if exists
                if current_section:
                    current_section["cards"].append(card_info)
                    current_section["has_cards"] = True

        # Add final section
        if current_section:
            sections.append(current_section)

        return {
            "items": content_items,
            "cards": cards,
            "headers": headers,
            "sections": sections,
            "total_items": len(content_items),
        }

    def _get_card_break_structure(self, workspace_name: str) -> Dict[str, Any]:
        """Get Card Break structure from database"""

        try:
            card_breaks = frappe.db.sql(
                """
                SELECT label, idx, link_count, hidden
                FROM `tabWorkspace Link`
                WHERE parent = %s AND type = 'Card Break'
                ORDER BY idx
            """,
                workspace_name,
                as_dict=True,
            )

            # Also get regular links for context
            links = frappe.db.sql(
                """
                SELECT label, link_to, link_type, idx, hidden
                FROM `tabWorkspace Link`
                WHERE parent = %s AND type = 'Link'
                ORDER BY idx
            """,
                workspace_name,
                as_dict=True,
            )

        except Exception as e:
            self.errors.append(f"Error querying workspace links: {str(e)}")
            return {"card_breaks": [], "links": [], "total_breaks": 0, "total_links": 0}

        return {
            "card_breaks": card_breaks,
            "links": links,
            "total_breaks": len(card_breaks),
            "total_links": len(links),
        }

    def _analyze_content_sync(self, content_structure: Dict, card_break_structure: Dict) -> Dict[str, Any]:
        """Analyze synchronization between content cards and Card Breaks"""

        # Extract card names from content
        content_cards = [card["name"] for card in content_structure["cards"] if card["name"]]

        # Extract Card Break labels
        card_break_labels = [cb["label"] for cb in card_break_structure["card_breaks"]]

        # Find mismatches
        content_only = list(set(content_cards) - set(card_break_labels))
        db_only = list(set(card_break_labels) - set(content_cards))
        matches = list(set(content_cards) & set(card_break_labels))

        # Report issues
        if content_only:
            self.warnings.append(f"Cards in content but no Card Break in database: {', '.join(content_only)}")

        if db_only:
            self.warnings.append(f"Card Breaks in database but no content card: {', '.join(db_only)}")

        if matches:
            self.info.append(f"Properly synchronized cards: {', '.join(matches)}")

        return {
            "content_cards": content_cards,
            "card_break_labels": card_break_labels,
            "content_only": content_only,
            "db_only": db_only,
            "matches": matches,
            "sync_percentage": len(matches) / max(len(content_cards) + len(db_only), 1) * 100,
        }

    def _detect_empty_sections(self, content_structure: Dict) -> List[Dict[str, Any]]:
        """Detect sections that have headers but no cards underneath"""

        empty_sections = []

        for section in content_structure["sections"]:
            if not section["has_cards"]:
                empty_section = {
                    "header_text": section["header"]["text"],
                    "header_index": section["header"]["index"],
                    "card_count": len(section["cards"]),
                }
                empty_sections.append(empty_section)
                self.warnings.append(f"Empty section detected: '{section['header']['text']}' has no cards")

        return empty_sections

    def _validate_section_hierarchy(self, content_structure: Dict) -> List[str]:
        """Validate proper section hierarchy (header → cards → spacer pattern)"""

        issues = []
        items = content_structure["items"]

        for i, item in enumerate(items):
            if item.get("type") == "header":
                # Check what comes after header
                if i + 1 < len(items):
                    next_item = items[i + 1]
                    next_type = next_item.get("type")

                    if next_type == "spacer":
                        # Header followed immediately by spacer = empty section
                        header_text = item.get("data", {}).get("text", "")
                        import re

                        clean_text = re.sub(r"<[^>]+>", "", header_text)
                        issues.append(f"Header '{clean_text}' immediately followed by spacer (empty section)")
                        self.warnings.append(f"Section hierarchy issue: '{clean_text}' has no content cards")

                    elif next_type == "header":
                        # Two headers in a row
                        issues.append(f"Two consecutive headers detected at index {i} and {i + 1}")
                        self.warnings.append("Section hierarchy issue: consecutive headers without content")

        return issues

    def _generate_result(self) -> Dict[str, Any]:
        """Generate validation result summary"""
        return {
            "status": "failed" if self.errors else ("warning" if self.warnings else "passed"),
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
def validate_workspace_content_sync(workspace_name: str = "Verenigingen"):
    """Validate workspace content field synchronization with database structure"""
    validator = WorkspaceContentValidator()
    return validator.validate_workspace_content_sync(workspace_name)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def validate_all_workspaces_content():
    """Validate content synchronization for all workspaces"""

    results = {}

    try:
        workspace_names = frappe.get_all("Workspace", pluck="name")

        for workspace_name in workspace_names:
            # Create fresh validator for each workspace
            ws_validator = WorkspaceContentValidator()
            results[workspace_name] = ws_validator.validate_workspace_content_sync(workspace_name)

        # Generate overall summary
        total_errors = sum(len(result["errors"]) for result in results.values())
        total_warnings = sum(len(result["warnings"]) for result in results.values())
        workspaces_with_issues = sum(1 for result in results.values() if not result["is_synchronized"])
        workspaces_with_empty_sections = sum(1 for result in results.values() if result["has_empty_sections"])

        return {
            "status": "failed" if total_errors > 0 else ("warning" if total_warnings > 0 else "passed"),
            "summary": {
                "total_workspaces": len(workspace_names),
                "workspaces_with_sync_issues": workspaces_with_issues,
                "workspaces_with_empty_sections": workspaces_with_empty_sections,
                "total_errors": total_errors,
                "total_warnings": total_warnings,
            },
            "workspace_results": results,
        }

    except Exception as e:
        return {
            "status": "failed",
            "error": f"Error validating workspaces: {str(e)}",
            "workspace_results": results,
        }


if __name__ == "__main__":
    # Test the validator
    result = validate_workspace_content_sync("Verenigingen")
    print(json.dumps(result, indent=2))
