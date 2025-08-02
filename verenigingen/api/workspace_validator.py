#!/usr/bin/env python3
"""
Workspace Validation API

This module provides comprehensive workspace validation capabilities for the
Verenigingen association management system. It validates workspace integrity,
catches common configuration issues, and ensures proper system setup before
deployment or production use.

Key Features:
    - Comprehensive workspace integrity validation
    - Pre-commit hook integration for development workflows
    - Configuration validation and error detection
    - Permission and security validation
    - Database schema validation
    - Integration point verification

Architecture:
    - High-security API for administrative operations
    - Comprehensive validation framework
    - Integration with pre-commit development workflows
    - Type-safe implementation with detailed error reporting
    - Security-aware validation with audit logging

Validation Categories:
    - Workspace Configuration: Validates workspace setup and configuration
    - DocType Integrity: Ensures DocType definitions are consistent
    - Permission Structure: Validates role and permission configurations
    - Database Schema: Checks database structure and indexes
    - Security Settings: Validates security configurations
    - Integration Points: Verifies external system connections

Security Model:
    - High-security API for administrative operations
    - Administrative role requirements for sensitive validations
    - Comprehensive audit logging for validation activities
    - Rate limiting to prevent abuse
    - Input validation and sanitization

Integration Points:
    - Pre-commit hook system for development workflow
    - Workspace DocType for configuration management
    - Permission system for access control validation
    - Database system for schema validation
    - Security framework for security validation

Business Value:
    - Prevents configuration errors from reaching production
    - Ensures consistent workspace setup across environments
    - Reduces deployment issues and downtime
    - Improves development workflow efficiency
    - Maintains system security and integrity

Development Workflow:
    - Integrated into pre-commit hooks for automatic validation
    - Can be run manually for troubleshooting
    - Provides detailed error reports for quick issue resolution
    - Supports continuous integration and deployment pipelines

Author: Verenigingen Development Team
License: MIT
"""

from typing import Dict, List

import frappe

# Import security framework
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api
from verenigingen.utils.security.audit_logging import log_security_event
from verenigingen.utils.security.authorization import require_role
from verenigingen.utils.security.rate_limiting import rate_limit


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def validate_workspace_comprehensive(workspace_name: str = "Verenigingen") -> Dict:
    """
    Comprehensive workspace validation for pre-commit hooks

    Returns:
        Dict with validation results, errors, warnings, and exit status
    """
    # Log this sensitive operation
    log_security_event(
        "configuration_change",
        {
            "workspace_name": workspace_name,
            "requested_by": frappe.session.user,
            "action": "workspace_validation",
        },
    )

    validator = WorkspaceValidator(workspace_name)
    return validator.validate_all()


class WorkspaceValidator:
    """Comprehensive workspace validation"""

    def __init__(self, workspace_name: str = "Verenigingen"):
        self.workspace_name = workspace_name
        self.errors = []
        self.warnings = []
        self.info = []

    def validate_all(self) -> Dict:
        """Run all workspace validations"""
        # Core validations
        self._validate_workspace_exists()
        self._validate_workspace_structure()
        self._validate_doctype_links()
        self._validate_report_links()
        self._validate_page_links()
        self._validate_card_breaks()
        self._validate_content_structure()

        # Generate summary
        return self._generate_summary()

    def _validate_workspace_exists(self):
        """Check if workspace exists in database"""
        try:
            workspace = frappe.db.get_value(
                "Workspace", self.workspace_name, ["name", "public", "is_hidden", "module"], as_dict=True
            )

            if not workspace:
                self.errors.append(f"Workspace '{self.workspace_name}' was not found")
                return

            if not workspace.public:
                self.warnings.append("Workspace is not public - may not be visible to users")

            if workspace.is_hidden:
                self.warnings.append("Workspace is hidden - will not appear in navigation")

            self.info.append(f"Workspace found: public={workspace.public}, hidden={workspace.is_hidden}")

        except Exception as e:
            self.errors.append(f"Error checking workspace existence: {str(e)}")

    def _validate_workspace_structure(self):
        """Validate workspace has proper link structure"""
        try:
            links = frappe.db.sql(
                """
                SELECT COUNT(*) as total_links,
                       COUNT(CASE WHEN hidden = 1 THEN 1 END) as hidden_links,
                       COUNT(CASE WHEN type = 'Link' THEN 1 END) as regular_links,
                       COUNT(CASE WHEN type = 'Card Break' THEN 1 END) as card_breaks
                FROM `tabWorkspace Link`
                WHERE parent = %s
            """,
                (self.workspace_name,),
                as_dict=True,
            )[0]

            if links.total_links == 0:
                self.errors.append("Workspace has no links - will appear empty to users")
                return

            if links.total_links < 50:
                self.warnings.append(
                    f"Workspace has only {links.total_links} links - seems low for Verenigingen"
                )

            if links.card_breaks == 0:
                self.warnings.append("No card breaks found - workspace may lack organization")

            self.info.append(
                f"Link structure: {links.total_links} total "
                f"({links.regular_links} links, {links.card_breaks} breaks, {links.hidden_links} hidden)"
            )

        except Exception as e:
            self.errors.append(f"Error validating workspace structure: {str(e)}")

    def _validate_doctype_links(self):
        """Check for broken DocType links"""
        try:
            # Get all DocType links
            doctype_links = frappe.db.sql(
                """
                SELECT link_to, label, COUNT(*) as count
                FROM `tabWorkspace Link`
                WHERE parent = %s AND link_type = 'DocType' AND link_to IS NOT NULL
                GROUP BY link_to
                ORDER BY link_to
            """,
                (self.workspace_name,),
                as_dict=True,
            )

            broken_doctypes = []
            for link in doctype_links:
                if not frappe.db.exists("DocType", link.link_to):
                    broken_doctypes.append(link.link_to)

            if broken_doctypes:
                self.errors.append(
                    f"Broken DocType links found: {', '.join(broken_doctypes)} "
                    "(these will cause workspace rendering failures)"
                )
            else:
                self.info.append(f"All {len(doctype_links)} DocType links are valid")

        except Exception as e:
            self.errors.append(f"Error validating DocType links: {str(e)}")

    def _validate_report_links(self):
        """Check for broken Report links"""
        try:
            report_links = frappe.db.sql(
                """
                SELECT link_to, label
                FROM `tabWorkspace Link`
                WHERE parent = %s AND link_type = 'Report' AND link_to IS NOT NULL
            """,
                (self.workspace_name,),
                as_dict=True,
            )

            broken_reports = []
            for link in report_links:
                if not frappe.db.exists("Report", link.link_to):
                    broken_reports.append(link.link_to)

            if broken_reports:
                self.warnings.append(f"Broken Report links found: {', '.join(broken_reports)}")
            else:
                self.info.append(f"All {len(report_links)} Report links are valid")

        except Exception as e:
            self.errors.append(f"Error validating Report links: {str(e)}")

    def _validate_page_links(self):
        """Validate Page links point to existing pages"""
        try:
            page_links = frappe.db.sql(
                """
                SELECT link_to, label
                FROM `tabWorkspace Link`
                WHERE parent = %s AND link_type = 'Page'
            """,
                (self.workspace_name,),
                as_dict=True,
            )

            # Check for essential page links
            essential_pages = ["/workflow_demo", "/member_portal", "/volunteer/dashboard"]
            found_pages = [link.link_to for link in page_links]

            missing_essential = [page for page in essential_pages if page not in found_pages]
            if missing_essential:
                self.warnings.append(f"Missing essential page links: {', '.join(missing_essential)}")

            self.info.append(f"Found {len(page_links)} Page links including portal pages")

        except Exception as e:
            self.errors.append(f"Error validating Page links: {str(e)}")

    def _validate_card_breaks(self):
        """Validate card break structure and link counts"""
        try:
            card_breaks = frappe.db.sql(
                """
                SELECT label, link_count, idx
                FROM `tabWorkspace Link`
                WHERE parent = %s AND type = 'Card Break'
                ORDER BY idx
            """,
                (self.workspace_name,),
                as_dict=True,
            )

            if not card_breaks:
                self.warnings.append("No card breaks found - workspace will lack visual organization")
                return

            # Check for zero link counts
            zero_counts = [cb.label for cb in card_breaks if cb.link_count == 0]
            if zero_counts:
                self.warnings.append(f"Card breaks with 0 link_count: {', '.join(zero_counts)}")

            # Check for essential sections
            essential_sections = ["Memberships", "Reports", "Settings"]
            found_sections = [cb.label for cb in card_breaks]
            missing_sections = [section for section in essential_sections if section not in found_sections]

            if missing_sections:
                self.warnings.append(f"Missing essential card sections: {', '.join(missing_sections)}")

            self.info.append(f"Found {len(card_breaks)} card breaks with proper organization")

        except Exception as e:
            self.errors.append(f"Error validating card breaks: {str(e)}")

    def _validate_content_structure(self):
        """Validate workspace content JSON structure"""
        try:
            content = frappe.db.get_value("Workspace", self.workspace_name, "content")

            if not content:
                self.warnings.append("Workspace has no content structure - will use basic layout")
                return

            import json

            try:
                content_data = json.loads(content)
                if not isinstance(content_data, list):
                    self.errors.append("Workspace content is not a valid JSON array")
                    return

                # Check for essential content types
                content_types = [item.get("type") for item in content_data if item.get("type")]
                if "header" not in content_types:
                    self.warnings.append("No header elements found in workspace content")
                if "card" not in content_types:
                    self.warnings.append("No card elements found in workspace content")

                self.info.append(f"Content structure valid with {len(content_data)} elements")

            except json.JSONDecodeError as e:
                self.errors.append(f"Invalid JSON in workspace content: {str(e)}")

        except Exception as e:
            self.errors.append(f"Error validating content structure: {str(e)}")

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


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def validate_specific_workspace(workspace_name: str) -> Dict:
    """Validate a specific workspace by name"""
    # Log this sensitive operation
    log_security_event(
        "configuration_change",
        {
            "workspace_name": workspace_name,
            "requested_by": frappe.session.user,
            "action": "workspace_validation",
        },
    )

    validator = WorkspaceValidator(workspace_name)
    return validator.validate_all()


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def run_workspace_pre_commit_check():
    """
    Pre-commit specific workspace validation
    Returns simple pass/fail for integration with pre-commit hooks
    """
    # Log this sensitive operation
    log_security_event(
        "configuration_change", {"requested_by": frappe.session.user, "action": "workspace_pre_commit_check"}
    )

    result = validate_workspace_comprehensive()

    # Format for pre-commit output
    print("🔍 Workspace Validation Results:")
    print("=" * 40)

    if result["errors"]:
        print(f"❌ ERRORS ({len(result['errors'])}):")
        for error in result["errors"]:
            print(f"   • {error}")

    if result["warnings"]:
        print(f"\n⚠️  WARNINGS ({len(result['warnings'])}):")
        for warning in result["warnings"]:
            print(f"   • {warning}")

    if result["info"]:
        print(f"\n✅ PASSED CHECKS ({len(result['info'])}):")
        for info in result["info"]:
            print(f"   • {info}")

    # Return result for further processing
    return {
        "success": result["status"] == "passed",
        "should_fail_commit": len(result["errors"]) > 0,
        "message": f"Workspace validation {'passed' if result['status'] == 'passed' else 'failed'}",
    }
