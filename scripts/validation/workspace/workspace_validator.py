#!/usr/bin/env python3
"""
Workspace Validation Script for Pre-commit Hooks

Validates workspace integrity and catches common issues before they reach production.
Can be run as a standalone script or integrated into pre-commit hooks.
"""

import sys
import frappe
from typing import Dict, List, Tuple


class WorkspaceValidator:
    """Comprehensive workspace validation"""
    
    def __init__(self, workspace_name: str = "Verenigingen"):
        self.workspace_name = workspace_name
        self.errors = []
        self.warnings = []
        self.info = []
    
    def validate_all(self) -> Dict:
        """Run all workspace validations"""
        print(f"🔍 Validating workspace: {self.workspace_name}")
        print("=" * 50)
        
        # Core validations
        self._validate_workspace_exists()
        self._validate_workspace_structure()
        self._validate_doctype_links()
        self._validate_report_links()
        self._validate_page_links()
        self._validate_card_breaks()
        self._validate_content_structure()
        
        # Summary
        return self._generate_summary()
    
    def _validate_workspace_exists(self):
        """Check if workspace exists in database"""
        try:
            workspace = frappe.db.get_value(
                "Workspace", 
                self.workspace_name, 
                ["name", "public", "is_hidden", "module"], 
                as_dict=True
            )
            
            if not workspace:
                self.errors.append(f"Workspace '{self.workspace_name}' not found in database")
                return
            
            if not workspace.public:
                self.warnings.append("Workspace is not public - may not be visible to users")
            
            if workspace.is_hidden:
                self.warnings.append("Workspace is hidden - will not appear in navigation")
            
            self.info.append(f"✅ Workspace found: public={workspace.public}, hidden={workspace.is_hidden}")
            
        except Exception as e:
            self.errors.append(f"Error checking workspace existence: {str(e)}")
    
    def _validate_workspace_structure(self):
        """Validate workspace has proper link structure"""
        try:
            links = frappe.db.sql("""
                SELECT COUNT(*) as total_links,
                       COUNT(CASE WHEN hidden = 1 THEN 1 END) as hidden_links,
                       COUNT(CASE WHEN type = 'Link' THEN 1 END) as regular_links,
                       COUNT(CASE WHEN type = 'Card Break' THEN 1 END) as card_breaks
                FROM `tabWorkspace Link` 
                WHERE parent = %s
            """, (self.workspace_name,), as_dict=True)[0]
            
            if links.total_links == 0:
                self.errors.append("Workspace has no links - will appear empty to users")
                return
            
            if links.total_links < 50:
                self.warnings.append(f"Workspace has only {links.total_links} links - seems low for Verenigingen")
            
            if links.card_breaks == 0:
                self.warnings.append("No card breaks found - workspace may lack organization")
            
            self.info.append(
                f"✅ Link structure: {links.total_links} total "
                f"({links.regular_links} links, {links.card_breaks} breaks, {links.hidden_links} hidden)"
            )
            
        except Exception as e:
            self.errors.append(f"Error validating workspace structure: {str(e)}")
    
    def _validate_doctype_links(self):
        """Check for broken DocType links"""
        try:
            # Get all DocType links
            doctype_links = frappe.db.sql("""
                SELECT link_to, label, COUNT(*) as count
                FROM `tabWorkspace Link`
                WHERE parent = %s AND link_type = 'DocType' AND link_to IS NOT NULL
                GROUP BY link_to
                ORDER BY link_to
            """, (self.workspace_name,), as_dict=True)
            
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
                self.info.append(f"✅ All {len(doctype_links)} DocType links are valid")
                
        except Exception as e:
            self.errors.append(f"Error validating DocType links: {str(e)}")
    
    def _validate_report_links(self):
        """Check for broken Report links"""
        try:
            report_links = frappe.db.sql("""
                SELECT link_to, label
                FROM `tabWorkspace Link`
                WHERE parent = %s AND link_type = 'Report' AND link_to IS NOT NULL
            """, (self.workspace_name,), as_dict=True)
            
            broken_reports = []
            for link in report_links:
                if not frappe.db.exists("Report", link.link_to):
                    broken_reports.append(link.link_to)
            
            if broken_reports:
                self.warnings.append(f"Broken Report links found: {', '.join(broken_reports)}")
            else:
                self.info.append(f"✅ All {len(report_links)} Report links are valid")
                
        except Exception as e:
            self.errors.append(f"Error validating Report links: {str(e)}")
    
    def _validate_page_links(self):
        """Validate Page links point to existing pages"""
        try:
            page_links = frappe.db.sql("""
                SELECT link_to, label
                FROM `tabWorkspace Link`
                WHERE parent = %s AND link_type = 'Page'
            """, (self.workspace_name,), as_dict=True)
            
            # Check for essential page links
            essential_pages = ['/workflow_demo', '/member_portal', '/volunteer/dashboard']
            found_pages = [link.link_to for link in page_links]
            
            missing_essential = [page for page in essential_pages if page not in found_pages]
            if missing_essential:
                self.warnings.append(f"Missing essential page links: {', '.join(missing_essential)}")
            
            self.info.append(f"✅ Found {len(page_links)} Page links including portal pages")
            
        except Exception as e:
            self.errors.append(f"Error validating Page links: {str(e)}")
    
    def _validate_card_breaks(self):
        """Validate card break structure and link counts"""
        try:
            card_breaks = frappe.db.sql("""
                SELECT label, link_count, idx
                FROM `tabWorkspace Link`
                WHERE parent = %s AND type = 'Card Break'
                ORDER BY idx
            """, (self.workspace_name,), as_dict=True)
            
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
            
            self.info.append(f"✅ Found {len(card_breaks)} card breaks with proper organization")
            
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
                
                self.info.append(f"✅ Content structure valid with {len(content_data)} elements")
                
            except json.JSONDecodeError as e:
                self.errors.append(f"Invalid JSON in workspace content: {str(e)}")
                
        except Exception as e:
            self.errors.append(f"Error validating content structure: {str(e)}")
    
    def _generate_summary(self) -> Dict:
        """Generate validation summary"""
        print("\n📊 Validation Summary:")
        print("=" * 50)
        
        if self.errors:
            print(f"❌ ERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"   • {error}")
        
        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"   • {warning}")
        
        if self.info:
            print(f"\n✅ INFO ({len(self.info)}):")
            for info in self.info:
                print(f"   • {info}")
        
        # Overall status
        if self.errors:
            print(f"\n🔴 VALIDATION FAILED: {len(self.errors)} errors found")
            exit_code = 1
        elif self.warnings:
            print(f"\n🟡 VALIDATION PASSED WITH WARNINGS: {len(self.warnings)} warnings")
            exit_code = 0
        else:
            print(f"\n🟢 VALIDATION PASSED: No issues found")
            exit_code = 0
        
        return {
            "status": "failed" if self.errors else "passed",
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
            "exit_code": exit_code
        }


@frappe.whitelist()
def validate_workspace(workspace_name: str = "Verenigingen") -> Dict:
    """API endpoint for workspace validation"""
    validator = WorkspaceValidator(workspace_name)
    return validator.validate_all()


def main():
    """Main entry point for script execution"""
    try:
        # Initialize Frappe
        frappe.init(site="dev.veganisme.net")
        frappe.connect()
        
        # Run validation
        validator = WorkspaceValidator()
        result = validator.validate_all()
        
        # Exit with appropriate code
        sys.exit(result["exit_code"])
        
    except Exception as e:
        print(f"❌ Validation script failed: {str(e)}")
        sys.exit(1)
    finally:
        if frappe.db:
            frappe.destroy()


    def validate_doctype_api_calls(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """FIRST-LAYER CHECK: Validate DocType existence in API calls"""
        violations = []
        
        # Patterns for Frappe API calls that use DocType names
        api_patterns = [
            r'frappe\.get_all\(\s*["\']([^"\']+)["\']',
            r'frappe\.get_doc\(\s*["\']([^"\']+)["\']',
            r'frappe\.new_doc\(\s*["\']([^"\']+)["\']',
            r'frappe\.delete_doc\(\s*["\']([^"\']+)["\']',
            r'frappe\.db\.get_value\(\s*["\']([^"\']+)["\']',
            r'frappe\.db\.exists\(\s*["\']([^"\']+)["\']',
            r'frappe\.db\.count\(\s*["\']([^"\']+)["\']',
            r'DocType\(\s*["\']([^"\']+)["\']',
        ]
        
        lines = content.splitlines()
        
        for line_num, line in enumerate(lines, 1):
            for pattern in api_patterns:
                matches = re.finditer(pattern, line)
                for match in matches:
                    doctype_name = match.group(1)
                    
                    # FIRST-LAYER CHECK: Does this DocType actually exist?
                    available_doctypes = getattr(self, 'doctypes', getattr(self, 'schemas', {}).get('schemas', {}))
                    if doctype_name not in available_doctypes:
                        # Suggest similar DocType names
                        suggestions = self._suggest_similar_doctype(doctype_name)
                        
                        violations.append(ValidationIssue(
                            file=str(file_path.relative_to(self.app_path)),
                            line=line_num,
                            field="<doctype_reference>",
                            doctype=doctype_name,
                            reference=line.strip(),
                            message=f"DocType '{doctype_name}' does not exist. {suggestions}",
                            context=line.strip(),
                            confidence="high",
                            issue_type="missing_doctype",
                            suggested_fix=suggestions
                        ))
        
        return violations
    
    def _suggest_similar_doctype(self, invalid_name: str) -> str:
        """Suggest similar DocType names for typos"""
        available_doctypes = getattr(self, 'doctypes', getattr(self, 'schemas', {}).get('schemas', {}))
        available = list(available_doctypes.keys())
        
        # Look for exact substring matches first
        exact_matches = [dt for dt in available if invalid_name.replace('Verenigingen ', '') in dt]
        if exact_matches:
            return f"Did you mean '{exact_matches[0]}'?"
        
        # Look for partial matches
        partial_matches = [dt for dt in available if any(word in dt for word in invalid_name.split())]
        if partial_matches:
            return f"Similar: {', '.join(partial_matches[:3])}"
        
        return f"Check {len(available)} available DocTypes"

if __name__ == "__main__":
    main()