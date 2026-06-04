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

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class ChapterFinanceService(StatelessService):
    """
    Service for managing Cost Center operations for Chapter.

    Inherits from StatelessService for consistent logging, metrics, and error handling.

    This service handles:
    - Cost Center creation on Chapter insert
    - Cost Center name updates on Chapter rename
    - Company validation and selection
    - Parent cost center hierarchy management
    - Transaction-safe creation with race condition handling
    """

    def __init__(self) -> None:
        """Initialize the chapter finance service."""
        super().__init__(service_name="ChapterFinanceService")

    def create_chapter_cost_center(self, chapter_doc: "Document") -> None:
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

        Concurrency:
            Runs inside the caller's transaction (typically after_insert).
            If a concurrent process creates the same cost center between our
            existence check and our insert attempt, the insert will fail.
            On failure we re-check for an existing CC and link it, so the
            chapter always ends up with the correct cost center.

        Naming Convention:
            Cost centers are named "{chapter_doc.name} - Chapter".  This is
            the canonical pattern used by the auto-create path.  Integration
            tests that create cost centers manually may use other patterns
            (e.g. "{chapter.name} - {company_abbr}") for their own purposes.

        Business Logic:
            - Skips if cost center already exists and is linked
            - Validates company before creation
            - Links existing cost center if found by naming pattern
            - Creates new cost center with appropriate parent
            - On insert failure, re-checks for concurrent creation and links
            - Links cost center to chapter on success
            - Non-fatal: Logs error but doesn't fail chapter creation

        Example:
            >>> ChapterFinanceService.create_chapter_cost_center(chapter_doc)
            # Creates Cost Center, links to chapter.cost_center field
        """
        from verenigingen.utils.secure_operations import secure_document_operation

        try:
            # Skip if cost center already exists
            if chapter_doc.cost_center and frappe.db.exists("Cost Center", chapter_doc.cost_center):
                self.logger.info(
                    f"Cost center {chapter_doc.cost_center} already exists for chapter {chapter_doc.name}"
                )
                return

            # Get and validate company
            company = self.get_validated_company(chapter_doc)
            if not company:
                self.logger.error(
                    f"No valid company found - cannot create cost center for chapter {chapter_doc.name}"
                )
                return

            # Generate cost center name
            cost_center_name = f"{chapter_doc.name} - Chapter"

            # Check if cost center already exists by name (race condition safe via db_set)
            existing_cost_center = frappe.db.exists(
                "Cost Center", {"cost_center_name": cost_center_name, "company": company}
            )
            if existing_cost_center:
                # Link existing cost center to chapter
                chapter_doc.db_set("cost_center", existing_cost_center, update_modified=False)
                self.logger.info(
                    f"Linked existing cost center {existing_cost_center} to chapter {chapter_doc.name}"
                )
                return

            # Create new cost center
            cost_center_doc = frappe.new_doc("Cost Center")
            cost_center_doc.cost_center_name = cost_center_name
            cost_center_doc.company = company
            cost_center_doc.is_group = 0  # Individual cost center, not a group

            # Find appropriate parent cost center
            parent_cost_center = self.get_appropriate_parent_cost_center(chapter_doc, company)

            if parent_cost_center:
                cost_center_doc.parent_cost_center = parent_cost_center

            # Use secure operation instead of ignore_permissions
            result = secure_document_operation(
                operation="insert",
                doc=cost_center_doc,
                justification=f"Auto-create cost center for chapter {chapter_doc.name}",
                required_permissions=["Cost Center:create"],
            )

            if result.success:
                # Link the created cost center to this chapter
                chapter_doc.db_set("cost_center", cost_center_doc.name, update_modified=False)
                self.logger.info(f"Created cost center {cost_center_doc.name} for chapter {chapter_doc.name}")
            else:
                # Insert failed — possibly a concurrent process created the CC.
                # Use get_value (not db.exists) to guarantee we get the name string.
                concurrent_cc = frappe.db.get_value(
                    "Cost Center",
                    {"cost_center_name": cost_center_name, "company": company},
                    "name",
                )
                if concurrent_cc:
                    chapter_doc.db_set("cost_center", concurrent_cc, update_modified=False)
                    self.logger.info(
                        f"[CHAPTER-CC-CREATE] Linked cost center {concurrent_cc} "
                        f"created concurrently for chapter {chapter_doc.name}"
                    )
                else:
                    self.logger.error(
                        f"[CHAPTER-CC-CREATE-ERR] Failed to create cost center "
                        f"for chapter {chapter_doc.name}: {'; '.join(result.errors)}"
                    )

        except Exception as e:
            self.logger.error(
                f"[CHAPTER-CC-CREATE-ERR] Error creating cost center "
                f"for chapter {chapter_doc.name}: {str(e)}"
            )
            # Don't fail chapter creation if cost center creation fails

    def get_validated_company(self, chapter_doc: "Document") -> Optional[str]:
        """
        Get and validate company for cost center creation.

        Implements fallback logic for determining which company to use when
        creating cost centers for chapters.

        Args:
            chapter_doc: Chapter document instance (for logging context)

        Returns:
            Optional[str]: Company name if valid company found, None otherwise

        Selection Logic:
            1. Try the app-configured company from Verenigingen Settings
            2. Try default company from Global Defaults
            3. Validate company exists and is not disabled
            4. Fallback: Use single active company if exactly one exists
            5. Return None if multiple companies (ambiguous) or no companies found

        Example:
            >>> company = ChapterFinanceService.get_validated_company(chapter_doc)
            >>> if company:
            ...     # Proceed with cost center creation
        """
        # Prefer the app-configured company. Verenigingen Settings.company is the
        # canonical company for this app; many sites set it but leave Global Defaults'
        # default_company blank, so check it first before falling back.
        for source_doctype, source_field in (
            ("Verenigingen Settings", "company"),
            ("Global Defaults", "default_company"),
        ):
            company = frappe.db.get_single_value(source_doctype, source_field)
            if not company:
                continue
            # Validate the company exists (Company DocType has no 'disabled' field in ERPNext v15+)
            if frappe.db.exists("Company", company):
                return company
            else:
                self.logger.warning(f"Configured company {company} ({source_doctype}) doesn't exist")

        # Fallback: get first active company, but only if there's exactly one
        active_companies = frappe.get_all("Company", pluck="name")

        if len(active_companies) == 1:
            self.logger.info(
                f"Using single active company {active_companies[0]} for chapter {chapter_doc.name}"
            )
            return active_companies[0]
        elif len(active_companies) > 1:
            self.logger.warning(
                f"Multiple active companies found - cannot auto-select for chapter {chapter_doc.name}: {active_companies}"
            )
            return None
        else:
            self.logger.error(f"No active companies found for chapter {chapter_doc.name}")
            return None

    def get_appropriate_parent_cost_center(self, chapter_doc: "Document", company: str) -> Optional[str]:
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
        try:
            # First try to find the company's root cost center (should be the company name itself)
            root_cost_centers = frappe.get_all(
                "Cost Center",
                filters={"company": company, "is_group": 1, "disabled": 0, "cost_center_name": company},
                fields=["name"],
                limit=1,
            )

            if root_cost_centers:
                return root_cost_centers[0].name

            # Fallback: find any active group cost center, preferring one with minimal hierarchy depth
            fallback_cost_centers = frappe.get_all(
                "Cost Center",
                filters={"company": company, "is_group": 1, "disabled": 0},
                fields=["name", "cost_center_name"],
                order_by="lft asc",  # Use nested set ordering for proper hierarchy
                limit=1,
            )

            if fallback_cost_centers:
                parent_cost_center = fallback_cost_centers[0].name
                self.logger.info(
                    f"Using fallback parent cost center {parent_cost_center} for chapter {chapter_doc.name}"
                )
                return parent_cost_center
            else:
                self.logger.warning(f"No suitable parent cost center found for company {company}")
                return None

        except Exception as e:
            self.logger.error(f"Error finding parent cost center for company {company}: {e}")
            raise

    def update_chapter_cost_center_name(self, chapter_doc: "Document") -> None:
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
                self.create_chapter_cost_center(chapter_doc)
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
                        self.logger.info(
                            f"Updated cost center name to {new_cost_center_name} for chapter {chapter_doc.name}"
                        )
                    else:
                        self.logger.error(
                            f"Failed to update cost center name for chapter {chapter_doc.name}: {'; '.join(result.errors)}"
                        )

            except frappe.DoesNotExistError:
                self.logger.warning(
                    f"Cost center {chapter_doc.cost_center} not found for chapter {chapter_doc.name} - attempting recreation"
                )
                # Clear the invalid cost center reference and recreate
                chapter_doc.db_set("cost_center", None, update_modified=False)
                self.create_chapter_cost_center(chapter_doc)

        except Exception as e:
            self.logger.error(f"Error updating cost center name for chapter {chapter_doc.name}: {str(e)}")


def get_chapter_finance_service() -> ChapterFinanceService:
    """Get singleton instance of ChapterFinanceService"""
    return ChapterFinanceService()
