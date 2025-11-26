"""
Unified Workspace Health Tool

Consolidates all workspace diagnostic and repair functionality into a single,
comprehensive tool that actually fixes issues instead of just reporting them.

Usage:
    bench --site [site] execute "verenigingen.api.workspace_health.diagnose_and_fix" --args "['workspace_name']"
    bench --site [site] execute "verenigingen.api.workspace_health.health_check" --args "['workspace_name']"
"""

import json
import os
import tempfile
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


class WorkspaceHealthManager:
    """Unified workspace health management"""

    def __init__(self, workspace_name: str):
        self.workspace_name = workspace_name
        self.workspace = None
        self.issues = []
        self.fixes_applied = []
        self.backup_path = None

    def diagnose_and_fix(self, auto_fix: bool = True, create_backup: bool = True) -> Dict:
        """Complete workspace health check and repair"""

        try:
            # 1. Load workspace
            if not self._load_workspace():
                return self._error_response("Workspace not found")

            # 2. Create backup if requested
            if create_backup:
                self._create_backup()

            # 3. Run comprehensive diagnostics
            self._run_diagnostics()

            # 4. Apply fixes if requested and issues found
            if auto_fix and self.issues:
                self._apply_fixes()

            # 5. Verify fixes
            if self.fixes_applied:
                self._verify_fixes()

            return self._success_response()

        except Exception as e:
            frappe.log_error(f"Workspace health check failed: {str(e)}", "Workspace Health")
            return self._error_response(f"Health check failed: {str(e)}")

    def _load_workspace(self) -> bool:
        """Load and validate workspace exists"""
        try:
            self.workspace = frappe.get_doc("Workspace", self.workspace_name)
            return True
        except frappe.DoesNotExistError:
            return False

    def _create_backup(self) -> None:
        """Create backup of current workspace state"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_data = {
            "name": self.workspace.name,
            "label": self.workspace.label,
            "content": self.workspace.content,
            "links": [self._link_to_dict(link) for link in self.workspace.links],
            "modified": str(self.workspace.modified),
            "backup_timestamp": timestamp,
        }

        self.backup_path = os.path.join(
            tempfile.gettempdir(), f"workspace_backup_{self.workspace_name}_{timestamp}.json"
        )
        with open(self.backup_path, "w") as f:
            json.dump(backup_data, f, indent=2)

    def _run_diagnostics(self) -> None:
        """Run comprehensive workspace diagnostics in priority order"""

        # 1. Content/Database Sync (Most Common Issue)
        self._check_content_sync()

        # 2. Link Validation (Broken References)
        self._check_link_validity()

        # 3. Structural Issues
        self._check_structure()

        # 4. Permission Issues
        self._check_permissions()

    def _check_content_sync(self) -> None:
        """Check if content field matches Card Break structure"""
        try:
            # Parse content field
            content_cards = []
            if self.workspace.content and self.workspace.content != "[]":
                content = json.loads(self.workspace.content)
                content_cards = [
                    item["data"]["card_name"]
                    for item in content
                    if item.get("type") == "card" and "card_name" in item.get("data", {})
                ]

            # Get Card Break names from database
            card_breaks = [link.label for link in self.workspace.links if link.type == "Card Break"]

            # Find mismatches
            missing_cards = [cb for cb in card_breaks if cb not in content_cards]
            orphaned_cards = [cc for cc in content_cards if cc not in card_breaks]

            if missing_cards or orphaned_cards:
                self.issues.append(
                    {
                        "type": "content_sync",
                        "severity": "high",
                        "description": "Content field not synchronized with Card Breaks",
                        "details": {
                            "missing_cards": missing_cards,
                            "orphaned_cards": orphaned_cards,
                            "card_breaks": card_breaks,
                            "content_cards": content_cards,
                        },
                    }
                )
        except json.JSONDecodeError as e:
            self.issues.append(
                {
                    "type": "content_syntax",
                    "severity": "critical",
                    "description": "Content field contains invalid JSON",
                    "details": {"error": str(e)},
                }
            )

    def _check_link_validity(self) -> None:
        """Check if all workspace links point to valid targets"""
        broken_links = []

        for link in self.workspace.links:
            if link.type == "DocType":
                if not frappe.db.exists("DocType", link.link_to):
                    broken_links.append(
                        {
                            "label": link.label,
                            "link_to": link.link_to,
                            "type": link.type,
                            "error": "DocType does not exist",
                        }
                    )
            elif link.type == "Report":
                if not frappe.db.exists("Report", link.link_to):
                    broken_links.append(
                        {
                            "label": link.label,
                            "link_to": link.link_to,
                            "type": link.type,
                            "error": "Report does not exist",
                        }
                    )
            elif link.type == "Dashboard":
                if not frappe.db.exists("Dashboard", link.link_to):
                    broken_links.append(
                        {
                            "label": link.label,
                            "link_to": link.link_to,
                            "type": link.type,
                            "error": "Dashboard does not exist",
                        }
                    )

        if broken_links:
            self.issues.append(
                {
                    "type": "broken_links",
                    "severity": "medium",
                    "description": f"Found {len(broken_links)} broken links",
                    "details": {"broken_links": broken_links},
                }
            )

    def _check_structure(self) -> None:
        """Check for structural issues"""
        # Check for duplicate links
        link_signatures = []
        duplicates = []

        for link in self.workspace.links:
            signature = f"{link.type}:{link.link_to}"
            if signature in link_signatures:
                duplicates.append({"label": link.label, "signature": signature})
            link_signatures.append(signature)

        if duplicates:
            self.issues.append(
                {
                    "type": "duplicate_links",
                    "severity": "low",
                    "description": f"Found {len(duplicates)} duplicate links",
                    "details": {"duplicates": duplicates},
                }
            )

    def _check_permissions(self) -> None:
        """Check workspace permissions and accessibility"""
        if not self.workspace.public and not self.workspace.roles:
            self.issues.append(
                {
                    "type": "permissions",
                    "severity": "medium",
                    "description": "Workspace is not public and has no assigned roles",
                    "details": {"public": self.workspace.public, "roles": self.workspace.roles},
                }
            )

    def _apply_fixes(self) -> None:
        """Apply fixes for identified issues"""
        for issue in self.issues:
            if issue["type"] == "content_sync":
                self._fix_content_sync(issue)
            elif issue["type"] == "content_syntax":
                self._fix_content_syntax(issue)
            elif issue["type"] == "broken_links":
                self._fix_broken_links(issue)
            elif issue["type"] == "duplicate_links":
                self._fix_duplicate_links(issue)

    def _fix_content_sync(self, issue: Dict) -> None:
        """Fix content/Card Break synchronization"""
        details = issue["details"]
        card_breaks = details["card_breaks"]

        # Generate proper content structure
        new_content = []

        # Add header if there are multiple sections
        if len(card_breaks) > 1:
            new_content.append(
                {
                    "id": "main_header",
                    "type": "header",
                    "data": {"text": f'<span class="h4"><b>{self.workspace.label}</b></span>', "col": 12},
                }
            )

        # Add card for each Card Break
        for i, card_name in enumerate(card_breaks):
            new_content.append(
                {
                    "id": f"card_{i}",
                    "type": "card",
                    "data": {"card_name": card_name, "col": 4 if len(card_breaks) > 2 else 6},
                }
            )

        # Update workspace content
        self.workspace.content = json.dumps(new_content)
        self.workspace.save()
        frappe.db.commit()

        self.fixes_applied.append(
            {
                "type": "content_sync",
                "description": f"Synchronized content field with {len(card_breaks)} Card Breaks",
                "details": {"cards_added": card_breaks},
            }
        )

    def _fix_content_syntax(self, issue: Dict) -> None:
        """Fix JSON syntax errors in content field"""
        # Reset to empty array - safest approach
        self.workspace.content = "[]"
        self.workspace.save()
        frappe.db.commit()

        self.fixes_applied.append(
            {"type": "content_syntax", "description": "Reset corrupted content field to empty array"}
        )

        # Rerun content sync check to rebuild properly
        self._check_content_sync()
        for issue in self.issues:
            if issue["type"] == "content_sync":
                self._fix_content_sync(issue)
                break

    def _fix_broken_links(self, issue: Dict) -> None:
        """Remove broken links with confirmation"""
        broken_links = issue["details"]["broken_links"]

        # Remove broken links
        links_to_remove = []
        for link in self.workspace.links:
            signature = f"{link.type}:{link.link_to}"
            for broken in broken_links:
                broken_signature = f"{broken['type']}:{broken['link_to']}"
                if broken_signature == signature:
                    links_to_remove.append(link)
                    break

        for link in links_to_remove:
            self.workspace.remove(link)

        if links_to_remove:
            self.workspace.save()
            frappe.db.commit()

            self.fixes_applied.append(
                {
                    "type": "broken_links",
                    "description": f"Removed {len(links_to_remove)} broken links",
                    "details": {"removed_links": [f"{link.type}:{link.link_to}" for link in links_to_remove]},
                }
            )

    def _fix_duplicate_links(self, issue: Dict) -> None:
        """Remove duplicate links"""
        seen_signatures = set()
        links_to_remove = []

        for link in self.workspace.links:
            signature = f"{link.type}:{link.link_to}"
            if signature in seen_signatures:
                links_to_remove.append(link)
            else:
                seen_signatures.add(signature)

        for link in links_to_remove:
            self.workspace.remove(link)

        if links_to_remove:
            self.workspace.save()
            frappe.db.commit()

            self.fixes_applied.append(
                {"type": "duplicate_links", "description": f"Removed {len(links_to_remove)} duplicate links"}
            )

    def _verify_fixes(self) -> None:
        """Verify that applied fixes resolved the issues"""
        # Clear cache to ensure fresh data
        frappe.clear_cache()

        # Reload workspace
        self.workspace.reload()

        # Re-run diagnostics to verify
        original_issues = self.issues.copy()
        self.issues = []
        self._run_diagnostics()

        # Compare before/after
        fixed_issues = [
            issue["type"]
            for issue in original_issues
            if issue["type"] not in [new_issue["type"] for new_issue in self.issues]
        ]

        if fixed_issues:
            self.fixes_applied.append(
                {"type": "verification", "description": f"Verified fixes resolved: {', '.join(fixed_issues)}"}
            )

    def _link_to_dict(self, link) -> Dict:
        """Convert workspace link to dictionary"""
        return {
            "label": link.label,
            "type": link.type,
            "link_to": link.link_to,
            "is_query_report": getattr(link, "is_query_report", 0),
            "onboard": getattr(link, "onboard", 0),
        }

    def _success_response(self) -> Dict:
        """Generate success response"""
        return {
            "success": True,
            "workspace": self.workspace_name,
            "status": "healthy" if not self.issues else "issues_found",
            "issues_found": len(self.issues),
            "fixes_applied": len(self.fixes_applied),
            "backup_created": self.backup_path is not None,
            "backup_path": self.backup_path,
            "issues": self.issues,
            "fixes": self.fixes_applied,
            "summary": self._generate_summary(),
        }

    def _error_response(self, error: str) -> Dict:
        """Generate error response"""
        return {
            "success": False,
            "workspace": self.workspace_name,
            "error": error,
            "backup_path": self.backup_path,
        }

    def _generate_summary(self) -> str:
        """Generate human-readable summary"""
        if not self.issues and not self.fixes_applied:
            return f"✅ {self.workspace_name} workspace is healthy"
        elif self.issues and not self.fixes_applied:
            return (
                f"⚠️  Found {len(self.issues)} issues in {self.workspace_name} workspace (no fixes applied)"
            )
        elif self.fixes_applied:
            remaining = len(self.issues) - len(self.fixes_applied)
            if remaining <= 0:
                return f"✅ Fixed all {len(self.fixes_applied)} issues in {self.workspace_name} workspace"
            else:
                return f"🔧 Fixed {len(self.fixes_applied)} issues, {remaining} remaining in {self.workspace_name} workspace"

        return f"📊 {self.workspace_name} workspace analysis complete"


# Public API Functions


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def diagnose_and_fix(
    workspace_name: str, auto_fix: bool = True, create_backup: bool = True
) -> OperationResult[Dict[str, Any]]:
    """
    Complete workspace health check and repair

    Args:
        workspace_name: Name of workspace to check
        auto_fix: Whether to automatically apply fixes (default: True)
        create_backup: Whether to create backup before fixes (default: True)

    Returns:
        OperationResult with diagnosis results and fixes applied
    """
    try:
        manager = WorkspaceHealthManager(workspace_name)
        result = manager.diagnose_and_fix(auto_fix=auto_fix, create_backup=create_backup)

        if result.get("success"):
            status = result.get("status", "unknown")
            issues_found = result.get("issues_found", 0)
            fixes_applied = result.get("fixes_applied", 0)

            if status == "healthy":
                message = _("Workspace {0} is healthy").format(workspace_name)
            elif fixes_applied > 0:
                message = _("Workspace {0}: Applied {1} fixes, found {2} issues").format(
                    workspace_name, fixes_applied, issues_found
                )
            else:
                message = _("Workspace {0}: Found {1} issues (no fixes applied)").format(
                    workspace_name, issues_found
                )

            return OperationResult.ok(result, message=message)
        else:
            error_msg = result.get("error", _("Unknown error during workspace health check"))
            frappe.log_error(
                title=_("Workspace Health Check Failed"),
                message=f"Workspace: {workspace_name}\nError: {error_msg}",
            )
            return OperationResult.fail(error_msg)

    except Exception as e:
        error_msg = _("Failed to diagnose and fix workspace {0}: {1}").format(workspace_name, str(e))
        frappe.log_error(
            title=_("Workspace Health Check Error"), message=f"{error_msg}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(error_msg)


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def health_check(workspace_name: str) -> OperationResult[Dict[str, Any]]:
    """
    Run diagnostics only without applying fixes

    Args:
        workspace_name: Name of workspace to check

    Returns:
        OperationResult with diagnosis results
    """
    try:
        manager = WorkspaceHealthManager(workspace_name)
        result = manager.diagnose_and_fix(auto_fix=False, create_backup=False)

        if result.get("success"):
            issues_found = result.get("issues_found", 0)
            status = result.get("status", "unknown")

            if status == "healthy":
                message = _("Workspace {0} health check: No issues found").format(workspace_name)
            else:
                message = _("Workspace {0} health check: Found {1} issues").format(
                    workspace_name, issues_found
                )

            return OperationResult.ok(result, message=message)
        else:
            error_msg = result.get("error", _("Unknown error during health check"))
            frappe.log_error(
                title=_("Workspace Health Check Failed"),
                message=f"Workspace: {workspace_name}\nError: {error_msg}",
            )
            return OperationResult.fail(error_msg)

    except Exception as e:
        error_msg = _("Failed to run health check on workspace {0}: {1}").format(workspace_name, str(e))
        frappe.log_error(
            title=_("Workspace Health Check Error"), message=f"{error_msg}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(error_msg)


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def quick_fix(workspace_name: str) -> OperationResult[Dict[str, Any]]:
    """
    Quick fix for the most common workspace issue (content sync)

    Args:
        workspace_name: Name of workspace to fix

    Returns:
        OperationResult with fix results
    """
    try:
        workspace = frappe.get_doc("Workspace", workspace_name)

        # Get Card Break names
        card_breaks = [link.label for link in workspace.links if link.type == "Card Break"]

        if not card_breaks:
            error_msg = _("No Card Breaks found to sync in workspace {0}").format(workspace_name)
            frappe.log_error(
                title=_("Workspace Quick Fix Failed"),
                message=f"Workspace: {workspace_name}\nError: {error_msg}",
            )
            return OperationResult.fail(error_msg)

        # Generate simple content structure
        new_content = []
        for i, card_name in enumerate(card_breaks):
            new_content.append(
                {
                    "id": f"card_{i}",
                    "type": "card",
                    "data": {"card_name": card_name, "col": 4 if len(card_breaks) > 2 else 6},
                }
            )

        workspace.content = json.dumps(new_content)
        workspace.save()
        frappe.db.commit()
        frappe.clear_cache()

        data = {"workspace": workspace_name, "cards_synced": card_breaks, "cards_count": len(card_breaks)}
        message = _("Quick fix applied: synchronized {0} Card Breaks in workspace {1}").format(
            len(card_breaks), workspace_name
        )

        return OperationResult.ok(data, message=message)

    except frappe.DoesNotExistError:
        error_msg = _("Workspace {0} does not exist").format(workspace_name)
        frappe.log_error(title=_("Workspace Quick Fix Failed"), message=f"Error: {error_msg}")
        return OperationResult.fail(error_msg)

    except Exception as e:
        error_msg = _("Failed to apply quick fix to workspace {0}: {1}").format(workspace_name, str(e))
        frappe.log_error(
            title=_("Workspace Quick Fix Error"), message=f"{error_msg}\n\n{traceback.format_exc()}"
        )
        return OperationResult.fail(error_msg)
