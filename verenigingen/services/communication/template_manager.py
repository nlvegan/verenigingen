"""
Email Template Manager

Handles template loading, caching, and validation for the EmailService.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe import _


class TemplateManager:
    """Manages email templates with caching and validation."""

    def __init__(self):
        self.cache = {}
        self.validation_cache = {}

    def get_template(self, template_name: str) -> Optional[Dict[str, Any]]:
        """
        Get email template with caching.

        Args:
            template_name: Name of the email template

        Returns:
            Template data dict or None if not found
        """
        if template_name in self.cache:
            return self.cache[template_name]

        try:
            if frappe.db.exists("Email Template", template_name):
                template_doc = frappe.get_doc("Email Template", template_name)
                template_data = {
                    "name": template_name,
                    "subject": template_doc.subject,
                    "content": template_doc.response_,
                    "doc": template_doc,
                }
                self.cache[template_name] = template_data
                return template_data
            return None

        except Exception as e:
            frappe.logger("template_manager").error(f"Template loading failed for {template_name}: {str(e)}")
            return None

    def validate_template(self, template_name: str) -> Dict[str, Any]:
        """
        Validate template exists and has required fields.

        Args:
            template_name: Name of template to validate

        Returns:
            Validation result dict
        """
        if template_name in self.validation_cache:
            return self.validation_cache[template_name]

        result = {"valid": False, "errors": [], "warnings": []}

        try:
            template = self.get_template(template_name)
            if not template:
                result["errors"].append(f"Template '{template_name}' not found")
            else:
                # Check required fields
                if not template.get("subject"):
                    result["errors"].append("Template missing subject")
                if not template.get("content"):
                    result["errors"].append("Template missing content")

                result["valid"] = len(result["errors"]) == 0

            self.validation_cache[template_name] = result
            return result

        except Exception as e:
            result["errors"].append(f"Validation error: {str(e)}")
            return result

    def render_template(self, template: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, str]:
        """
        Render template with context variables.

        Args:
            template: Template data dict
            context: Variables for rendering

        Returns:
            Rendered subject and content
        """
        try:
            rendered_subject = frappe.render_template(template["subject"], context)
            rendered_content = frappe.render_template(template["content"], context)

            return {"subject": rendered_subject, "content": rendered_content}
        except Exception as e:
            frappe.logger("template_manager").error(f"Template rendering failed: {str(e)}")
            return {
                "subject": "Email Notification",
                "content": "There was an error rendering this email template.",
            }

    def clear_cache(self, template_name: str = None):
        """Clear template cache."""
        if template_name:
            self.cache.pop(template_name, None)
            self.validation_cache.pop(template_name, None)
        else:
            self.cache.clear()
            self.validation_cache.clear()

    def get_available_templates(self) -> List[str]:
        """Get list of available email templates."""
        try:
            templates = frappe.get_all("Email Template", fields=["name"])
            return [t.name for t in templates]
        except Exception as e:
            frappe.logger("template_manager").error(f"Failed to get available templates: {str(e)}")
            return []
