# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
ChapterFinanceService - Cost Center management for Chapter

This service handles Cost Center creation, validation, and synchronization for
Chapter records, enabling native ERPNext cost accounting integration while
maintaining Chapter as the primary organizational unit.

Extracted from chapter.py:
- _create_chapter_cost_center() - Lines 973-1074 (102 LOC)
- _get_validated_company() - Lines 1075-1107 (33 LOC)
- _get_appropriate_parent_cost_center() - Lines 1109-1162 (55 LOC)
- _update_chapter_cost_center_name() - Lines 1164-1215 (52 LOC)
Total extraction: ~242 LOC

Architecture:
- Static methods for stateless operations
- Chapter document passed as parameter
- Secure operations instead of permission bypasses
- Transaction handling for race conditions
- Comprehensive error handling with logging

Security:
- Uses secure_document_operation for all Cost Center modifications
- Required permissions: Cost Center:create, Cost Center:write
- Justifications logged for all privileged operations
- Permission control enforced at Chapter level

Dependencies:
- frappe.db for Cost Center queries
- secure_document_operation for secure operations
- Global Defaults and Company validation
"""

from typing import TYPE_CHECKING, Optional

import frappe

if TYPE_CHECKING:
    from frappe.model.document import Document


class ChapterFinanceService:
    """
    Service for managing Cost Center operations for Chapter.

    This service handles:
    - Cost Center creation on Chapter insert
    - Cost Center name updates on Chapter rename
    - Company validation and selection
    - Parent cost center hierarchy management
    - Transaction-safe creation with race condition handling
    """

    @staticmethod
    def create_chapter_cost_center(chapter_doc: "Document") -> None:
        """
        Create a cost center for this chapter with proper security validation.

        This enables expense claims and financial operations to use the native
        ERPNext cost center field for cost accounting, while maintaining chapter
        as the primary organizational unit.

        Args:
            chapter_doc: Chapter document instance

        Security Note:
            Uses secure_document_operation instead of ignore_permissions=True.
            All Cost Center operations require explicit permission validation
            with logged justifications for audit trail compliance.

            Required permissions:
            - Cost Center:create for new cost center creation

        Transaction Safety:
            Uses explicit transaction handling (begin/commit/rollback) to prevent
            race conditions when multiple processes attempt to create the same
            cost center simultaneously.

        Business Logic:
            - Skips if cost center already exists and is linked
            - Validates company before creation
            - Generates cost center name: "{chapter_name} - Chapter"
            - Links existing cost center if found during transaction
            - Creates new cost center with appropriate parent
            - Links cost center to chapter on success
            - Non-fatal: Logs error but doesn't fail chapter creation

        Example:
            >>> ChapterFinanceService.create_chapter_cost_center(chapter_doc)
            # Creates Cost Center, links to chapter.cost_center field
        """
        frappe.logger().error(
            f"DEBUG: *** ENTERING create_chapter_cost_center for chapter {chapter_doc.name}"
        )

        try:
            frappe.logger().error("DEBUG: About to import secure_document_operation...")
            from verenigingen.utils.secure_operations import secure_document_operation

            frappe.logger().error("DEBUG: Successfully imported secure_document_operation")
        except Exception as import_error:
            frappe.logger().error(f"DEBUG: IMPORT ERROR: {import_error}")
            raise

        try:
            # Skip if cost center already exists
            if chapter_doc.cost_center and frappe.db.exists("Cost Center", chapter_doc.cost_center):
                frappe.log_error(
                    f"Cost center {chapter_doc.cost_center} already exists for chapter {chapter_doc.name}",
                    "Chapter Cost Center",
                )
                return

            # Get and validate company
            company = ChapterFinanceService.get_validated_company(chapter_doc)
            if not company:
                frappe.log_error(
                    f"No valid company found - cannot create cost center for chapter {chapter_doc.name}",
                    "Chapter Cost Center",
                )
                return

            # Generate cost center name
            cost_center_name = f"{chapter_doc.name} - Chapter"

            # Use transaction to prevent race conditions
            frappe.db.begin()
            try:
                # Check if cost center already exists by name (within transaction)
                existing_cost_center = frappe.db.exists(
                    "Cost Center", {"cost_center_name": cost_center_name, "company": company}
                )
                if existing_cost_center:
                    # Link existing cost center to chapter
                    chapter_doc.db_set("cost_center", existing_cost_center, update_modified=False)
                    frappe.log_error(
                        f"Linked existing cost center {existing_cost_center} to chapter {chapter_doc.name}",
                        "Chapter Cost Center",
                    )
                    frappe.db.commit()
                    return

                # Create new cost center
                cost_center_doc = frappe.new_doc("Cost Center")
                cost_center_doc.cost_center_name = cost_center_name
                cost_center_doc.company = company
                cost_center_doc.is_group = 0  # Individual cost center, not a group

                # Find appropriate parent cost center
                frappe.logger().info("DEBUG: About to call get_appropriate_parent_cost_center...")
                parent_cost_center = ChapterFinanceService.get_appropriate_parent_cost_center(
                    chapter_doc, company
                )
                frappe.logger().info(
                    f"DEBUG: get_appropriate_parent_cost_center returned: {parent_cost_center}"
                )

                if parent_cost_center:
                    cost_center_doc.parent_cost_center = parent_cost_center
                    frappe.logger().info(f"DEBUG: Set parent_cost_center to: {parent_cost_center}")

                # Use secure operation instead of ignore_permissions
                frappe.logger().info("DEBUG: About to call secure_document_operation...")
                result = secure_document_operation(
                    operation="insert",
                    doc=cost_center_doc,
                    justification=f"Auto-create cost center for chapter {chapter_doc.name}",
                    required_permissions=["Cost Center:create"],
                )

                if result.success:
                    # Link the created cost center to this chapter
                    chapter_doc.db_set("cost_center", cost_center_doc.name, update_modified=False)
                    frappe.log_error(
                        f"Created cost center {cost_center_doc.name} for chapter {chapter_doc.name}",
                        "Chapter Cost Center",
                    )
                    frappe.db.commit()
                else:
                    frappe.db.rollback()
                    frappe.log_error(
                        f"Failed to create cost center for chapter {chapter_doc.name}: {'; '.join(result.errors)}",
                        "Chapter Cost Center",
                    )

            except Exception as transaction_error:
                frappe.db.rollback()
                raise transaction_error

        except Exception as e:
            frappe.log_error(
                f"Error creating cost center for chapter {chapter_doc.name}: {str(e)}", "Chapter Cost Center"
            )
            # Don't fail chapter creation if cost center creation fails

    @staticmethod
    def get_validated_company(chapter_doc: "Document") -> Optional[str]:
        """
        Get and validate company for cost center creation.

        Implements fallback logic for determining which company to use when
        creating cost centers for chapters.

        Args:
            chapter_doc: Chapter document instance (for logging context)

        Returns:
            Optional[str]: Company name if valid company found, None otherwise

        Selection Logic:
            1. Try default company from Global Defaults
            2. Validate company exists and is not disabled
            3. Fallback: Use single active company if exactly one exists
            4. Return None if multiple companies (ambiguous) or no companies found

        Example:
            >>> company = ChapterFinanceService.get_validated_company(chapter_doc)
            >>> if company:
            ...     # Proceed with cost center creation
        """
        # First try default company
        company = frappe.db.get_single_value("Global Defaults", "default_company")

        if company:
            # Validate the company exists and is active
            company_data = frappe.db.get_value("Company", company, ["name", "disabled"], as_dict=True)
            if company_data and not company_data.disabled:
                return company
            else:
                frappe.log_error(
                    f"Default company {company} is disabled or doesn't exist", "Chapter Cost Center"
                )

        # Fallback: get first active company, but only if there's exactly one
        active_companies = frappe.get_all("Company", filters={"disabled": 0}, pluck="name")

        if len(active_companies) == 1:
            frappe.log_error(
                f"Using single active company {active_companies[0]} for chapter {chapter_doc.name}",
                "Chapter Cost Center",
            )
            return active_companies[0]
        elif len(active_companies) > 1:
            frappe.log_error(
                f"Multiple active companies found - cannot auto-select for chapter {chapter_doc.name}: {active_companies}",
                "Chapter Cost Center",
            )
            return None
        else:
            frappe.log_error(
                f"No active companies found for chapter {chapter_doc.name}", "Chapter Cost Center"
            )
            return None

    @staticmethod
    def get_appropriate_parent_cost_center(chapter_doc: "Document", company: str) -> Optional[str]:
        """
        Get appropriate parent cost center for the given company using ORM methods.

        Implements hierarchy-aware parent cost center selection for proper
        nested set tree structure in ERPNext cost center hierarchy.

        Args:
            chapter_doc: Chapter document instance (for logging context)
            company: Company name to find parent cost center for

        Returns:
            Optional[str]: Parent cost center name if found, None otherwise

        Selection Logic:
            1. Try to find root cost center (company name as cost_center_name)
            2. Fallback: Find any active group cost center, ordered by lft (nested set left value)
            3. Return None if no suitable parent found

        Nested Set Ordering:
            Uses lft (left value) ordering to prefer parents higher in the
            hierarchy, ensuring proper tree structure for ERPNext nested sets.

        Example:
            >>> parent = ChapterFinanceService.get_appropriate_parent_cost_center(chapter_doc, "Company")
            >>> if parent:
            ...     cost_center_doc.parent_cost_center = parent
        """
        frappe.logger().info(f"DEBUG: Starting parent cost center lookup for company: {company}")

        try:
            # First try to find the company's root cost center (should be the company name itself)
            frappe.logger().info("DEBUG: Attempting root cost center query...")
            root_cost_centers = frappe.get_all(
                "Cost Center",
                filters={"company": company, "is_group": 1, "is_disabled": 0, "cost_center_name": company},
                fields=["name"],
                limit=1,
            )
            frappe.logger().info(f"DEBUG: Root cost center query succeeded. Results: {root_cost_centers}")

            if root_cost_centers:
                frappe.logger().info(f"DEBUG: Found root cost center: {root_cost_centers[0].name}")
                return root_cost_centers[0].name

            # Fallback: find any active group cost center, preferring one with minimal hierarchy depth
            frappe.logger().info("DEBUG: Attempting fallback cost center query...")
            fallback_cost_centers = frappe.get_all(
                "Cost Center",
                filters={"company": company, "is_group": 1, "is_disabled": 0},
                fields=["name", "cost_center_name"],
                order_by="lft asc",  # Use nested set ordering for proper hierarchy
                limit=1,
            )
            frappe.logger().info(
                f"DEBUG: Fallback cost center query succeeded. Results: {fallback_cost_centers}"
            )

            if fallback_cost_centers:
                parent_cost_center = fallback_cost_centers[0].name
                frappe.log_error(
                    f"Using fallback parent cost center {parent_cost_center} for chapter {chapter_doc.name}",
                    "Chapter Cost Center",
                )
                frappe.logger().info(f"DEBUG: Using fallback parent: {parent_cost_center}")
                return parent_cost_center
            else:
                frappe.log_error(
                    f"No suitable parent cost center found for company {company}", "Chapter Cost Center"
                )
                frappe.logger().info("DEBUG: No cost centers found")
                return None

        except Exception as e:
            frappe.logger().error(f"DEBUG: ERROR in get_appropriate_parent_cost_center: {e}")
            frappe.logger().error(f"DEBUG: Exception type: {type(e)}")
            import traceback

            frappe.logger().error(f"DEBUG: Traceback: {traceback.format_exc()}")
            raise

    @staticmethod
    def update_chapter_cost_center_name(chapter_doc: "Document") -> None:
        """
        Update cost center name when chapter name changes with recreation logic.

        Handles cost center name synchronization when chapters are renamed,
        ensuring cost center names stay aligned with chapter names.

        Args:
            chapter_doc: Chapter document instance

        Security Note:
            Uses secure_document_operation instead of ignore_permissions=True.
            All Cost Center operations require explicit permission validation
            with logged justifications for audit trail compliance.

            Required permissions:
            - Cost Center:write for cost center name updates

        Recovery Logic:
            If the referenced cost center doesn't exist (DoesNotExistError):
            1. Clear the invalid cost_center reference
            2. Attempt to recreate the cost center
            This handles cases where cost centers were manually deleted.

        Business Logic:
            - If no cost center assigned, attempt creation
            - If cost center exists, update name to match chapter name
            - If cost center missing, clear reference and recreate
            - Non-fatal: Logs error but doesn't fail chapter save

        Example:
            >>> ChapterFinanceService.update_chapter_cost_center_name(chapter_doc)
            # Updates cost center name to "{chapter_doc.name} - Chapter"
        """
        from verenigingen.utils.secure_operations import secure_document_operation

        try:
            if not chapter_doc.cost_center:
                # No cost center assigned, try to create one
                ChapterFinanceService.create_chapter_cost_center(chapter_doc)
                return

            try:
                # Get the old cost center document
                cost_center_doc = frappe.get_doc("Cost Center", chapter_doc.cost_center)

                # Update cost center name to match new chapter name
                new_cost_center_name = f"{chapter_doc.name} - Chapter"

                if cost_center_doc.cost_center_name != new_cost_center_name:
                    cost_center_doc.cost_center_name = new_cost_center_name

                    # Use secure operation instead of ignore_permissions
                    result = secure_document_operation(
                        operation="save",
                        doc=cost_center_doc,
                        justification=f"Update cost center name for renamed chapter {chapter_doc.name}",
                        required_permissions=["Cost Center:write"],
                    )

                    if result.success:
                        frappe.log_error(
                            f"Updated cost center name to {new_cost_center_name} for chapter {chapter_doc.name}",
                            "Chapter Cost Center",
                        )
                    else:
                        frappe.log_error(
                            f"Failed to update cost center name for chapter {chapter_doc.name}: {'; '.join(result.errors)}",
                            "Chapter Cost Center",
                        )

            except frappe.DoesNotExistError:
                frappe.log_error(
                    f"Cost center {chapter_doc.cost_center} not found for chapter {chapter_doc.name} - attempting recreation",
                    "Chapter Cost Center",
                )
                # Clear the invalid cost center reference and recreate
                chapter_doc.db_set("cost_center", None, update_modified=False)
                ChapterFinanceService.create_chapter_cost_center(chapter_doc)

        except Exception as e:
            frappe.log_error(
                f"Error updating cost center name for chapter {chapter_doc.name}: {str(e)}",
                "Chapter Cost Center",
            )


def get_chapter_finance_service() -> ChapterFinanceService:
    """Get singleton instance of ChapterFinanceService"""
    return ChapterFinanceService()
