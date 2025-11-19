# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class VerenigingenPaymentsSettings(Document):
    def validate(self):
        """Validate webhook user has appropriate role and security requirements"""
        if self.webhook_user:
            # Check if user exists
            if not frappe.db.exists("User", self.webhook_user):
                frappe.throw(f"User {self.webhook_user} does not exist")

            user_doc = frappe.get_doc("User", self.webhook_user)

            # Check if user has required role
            webhook_role_assigned = any(role.role == "Verenigingen Webhook User" for role in user_doc.roles)

            if not webhook_role_assigned:
                frappe.throw(
                    f"User {self.webhook_user} must have the 'Verenigingen Webhook User' role assigned. "
                    "This role is required for webhook operations and provides minimal security permissions."
                )

            # Security validation: ensure webhook user is not Administrator
            if self.webhook_user == "Administrator":
                frappe.throw(
                    "Administrator account cannot be used as webhook user. "
                    "Please create a dedicated webhook user account with 'Verenigingen Webhook User' role for security."
                )

            # Ensure user doesn't have excessive permissions
            user_roles = [role.role for role in user_doc.roles]
            dangerous_roles = ["System Manager", "Administrator", "All"]
            has_dangerous_roles = any(role in dangerous_roles for role in user_roles)

            if has_dangerous_roles:
                frappe.throw(
                    f"Security violation: Webhook user {self.webhook_user} has excessive permissions ({', '.join([r for r in user_roles if r in dangerous_roles])}). "
                    "Webhook users should only have the 'Verenigingen Webhook User' role for security."
                )
