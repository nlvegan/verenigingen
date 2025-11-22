# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
DepartmentSyncService - ERPNext Department synchronization for Chapter

This service handles synchronization between Chapter records and ERPNext Department
records, enabling native ERPNext integration for expense claims and organizational
structure while maintaining Chapter as the primary organizational unit.

Extracted from chapter.py:
- _sync_department() - Lines 712-798 (87 LOC)

Architecture:
- Static methods for stateless operations
- Chapter document passed as parameter
- Permission bypass justified for system sync operations
- Comprehensive error handling with logging

Security:
- Uses ignore_permissions=True for automated sync (justified)
- Permission control enforced at Chapter level
- Users must have Chapter permissions to trigger sync

Dependencies:
- frappe.db for Department queries
- Verenigingen Settings for company configuration
"""

from typing import TYPE_CHECKING, Optional

import frappe

if TYPE_CHECKING:
    from frappe.model.document import Document


class DepartmentSyncService:
    """
    Service for synchronizing ERPNext Department records with Chapter.

    This service handles:
    - Department creation on Chapter insert
    - Department status updates on Chapter update
    - Department field linking for Chapter reference
    - Company configuration management
    """

    @staticmethod
    def sync_department(chapter_doc: "Document", old_doc: Optional["Document"] = None) -> None:
        """
        Synchronize ERPNext Department record with Chapter for native integration.

        This enables expense claims to use the native ERPNext department field
        for filtering and user permissions, while maintaining chapter as the
        primary organizational unit.

        Args:
            chapter_doc: Chapter document instance
            old_doc: Previous version of the document (for name change detection)

        Security Note:
            Uses ignore_permissions=True because this is an automated system sync
            triggered by Chapter document lifecycle hooks (after_insert, on_update).
            Permission control is enforced at the Chapter level - users must have
            permission to modify the Chapter to trigger this department sync.
            This prevents requiring separate Department permissions for chapter
            administrators while maintaining proper access control.

        Business Logic:
            - Creates new Department if doesn't exist
            - Updates Department status when Chapter status changes
            - Links Department reference to Chapter.department field
            - Maps Active Chapter → Enabled Department, else → Disabled

        Example:
            >>> DepartmentSyncService.sync_department(chapter_doc)
            # Creates/updates Department, links to chapter
        """
        try:
            # Get company first to check for existing department
            company = frappe.db.get_single_value("Verenigingen Settings", "company")
            if not company:
                # Fallback to global default if not set
                company = frappe.db.get_single_value("Global Defaults", "default_company")

            # Check if department exists with current chapter name and company
            # Note: Department autoname creates "{department_name} - {company_abbr}",
            # so we check by department_name field, not by name
            department_exists = frappe.db.exists(
                "Department", {"department_name": chapter_doc.name, "company": company}
            )

            # Map chapter status to department disabled status
            is_disabled = 0 if chapter_doc.status == "Active" else 1

            if department_exists:
                # Update existing department (rename handled in after_rename hook)
                # Get the actual department name (after autoname)
                actual_dept_name = frappe.db.get_value(
                    "Department", {"department_name": chapter_doc.name, "company": company}, "name"
                )
                dept_doc = frappe.get_doc("Department", actual_dept_name)

                # Update status if changed
                if dept_doc.disabled != is_disabled:
                    dept_doc.disabled = is_disabled
                    dept_doc.save(ignore_permissions=True)
                    frappe.logger().info(
                        f"Updated Department {actual_dept_name} disabled status to {is_disabled}"
                    )
            else:
                # Create new department (company already retrieved above)
                dept_doc = frappe.get_doc(
                    {
                        "doctype": "Department",
                        "department_name": chapter_doc.name,
                        "parent_department": "All Departments",  # ERPNext default root
                        "disabled": is_disabled,
                        "company": company,
                    }
                )
                dept_doc.insert(ignore_permissions=True)
                frappe.logger().info(
                    f"Created Department {dept_doc.name} for chapter {chapter_doc.name} "
                    f"(disabled={is_disabled}, company={company})"
                )

            # Update the chapter's department field to show the link
            # Get the actual department name (after autoname, e.g., "Test Chapter - TC")
            if department_exists:
                actual_dept_name = frappe.db.get_value(
                    "Department", {"department_name": chapter_doc.name, "company": company}, "name"
                )
            else:
                actual_dept_name = dept_doc.name  # Just created, use the autoname'd name

            if actual_dept_name and chapter_doc.department != actual_dept_name:
                frappe.db.set_value(
                    "Chapter", chapter_doc.name, "department", actual_dept_name, update_modified=False
                )

        except Exception as e:
            # Don't block chapter save if department sync fails
            frappe.log_error(
                f"Failed to sync Department for chapter {chapter_doc.name}: {str(e)}",
                "Chapter Department Sync Error",
            )


def get_department_sync_service() -> DepartmentSyncService:
    """Get singleton instance of DepartmentSyncService"""
    return DepartmentSyncService()
