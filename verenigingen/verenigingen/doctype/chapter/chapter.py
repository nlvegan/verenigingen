# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""
Chapter DocType Implementation

This module implements the Chapter DocType for the Verenigingen association
management system. It represents local chapters/branches of the organization
with comprehensive management capabilities including board management, member
coordination, and communication systems.

Key Features:
    - Board member management with role-based permissions
    - Member registration and coordination
    - Communication and announcement systems
    - Volunteer integration and coordination
    - Website integration with public chapter pages
    - Financial tracking and reporting

Architecture:
    - Manager Pattern: Delegates specific responsibilities to specialized managers
    - Validator Pattern: Centralized validation logic with comprehensive error handling
    - Custom Web Pages: Public chapter pages handled by /www/chapter.py (not WebsiteGenerator)
    - Event-driven: Hooks into document lifecycle for automated processing

Migration Note (2025-11-02):
    Switched from WebsiteGenerator to Document base class to fix form rendering issues.
    WebsiteGenerator was interfering with desk form display for board members, causing
    child tables to not render properly. Public chapter pages now use custom web pages.

Manager Components:
    - BoardManager: Handles board member appointments and permissions
    - MemberManager: Manages chapter membership and registration
    - CommunicationManager: Handles announcements and member communication
    - VolunteerIntegrationManager: Coordinates with volunteer management system
    - ChapterValidator: Comprehensive validation and business rule enforcement

Business Logic:
    - Chapter autonomy with central coordination
    - Board member role and permission management
    - Member application approval workflows
    - Financial dues and payment coordination
    - Event and activity management

Security Model:
    - Role-based access control for board positions
    - Chapter-specific permission scoping
    - Audit logging for sensitive operations
    - Validation of board member authorities

Integration Points:
    - Member DocType for membership management
    - Volunteer system for activity coordination
    - Financial systems for dues and payments
    - Communication systems for announcements
    - Custom web pages (/www/chapter.py) for public chapter pages

Author: Verenigingen Development Team
License: MIT
"""

from datetime import date
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.utils import getdate, now, today

from verenigingen.events.chapter_events import (
    emit_chapter_board_changed,
    emit_chapter_membership_changed,
    emit_chapter_settings_changed,
)
from verenigingen.utils.error_handling import handle_api_error, log_error
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)

# Import managers and validators
from .managers import BoardManager, CommunicationManager, MemberManager, VolunteerIntegrationManager
from .validators import ChapterValidator


class Chapter(Document):
    """
    Chapter document with refactored manager pattern

    Core responsibilities:
    - Document lifecycle (validate, save, etc.)
    - Manager coordination
    - Public API compatibility

    Delegated responsibilities:
    - Board management -> BoardManager
    - Member management -> MemberManager
    - Communications -> CommunicationManager
    - Volunteer integration -> VolunteerIntegrationManager
    - Validation -> ChapterValidator
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._managers = {}
        self._validator = None

    # ========================================================================
    # CORE DOCUMENT LIFECYCLE
    # ========================================================================

    def validate(self) -> None:
        """Main validation - streamlined workflow with centralized error handling"""
        # Basic validations
        self._ensure_route()
        self._auto_fix_required_fields()
        self.validate_role_profile_configuration()
        self.validate_chapter_access()  # Moved from hooks.py

        # Comprehensive validation using validator - streamlined approach
        validation_result = self.validator.validate_before_save()
        self._process_validation_result(validation_result)

        # Handle board member changes (delegation to managers)
        self._handle_document_changes()

    def _process_validation_result(self, validation_result):
        """Process validation results with proper error handling"""
        if not validation_result.is_valid:
            # Log warnings but don't block save
            for warning in validation_result.warnings:
                frappe.msgprint(warning, indicator="orange", alert=True)

            # Throw errors that block save
            if validation_result.errors:
                error_context = {"chapter": self.name, "errors": validation_result.errors}
                log_error(
                    frappe.ValidationError(", ".join(validation_result.errors)),
                    context=error_context,
                    module="verenigingen.doctype.chapter",
                )
                frappe.throw(_("Validation failed: {0}").format(", ".join(validation_result.errors)))

    def before_save(self) -> None:
        """Before save hook - streamlined with safe manager operations"""
        # Auto-populate uploaded_by and upload_date for board documents
        self._populate_board_document_fields()

        old_doc = self.get_doc_before_save()
        if old_doc:
            self._safe_manager_operation(
                "board_member_changes", lambda: self.board_manager.handle_board_member_changes(old_doc)
            )
            self._safe_manager_operation(
                "board_member_additions", lambda: self.board_manager.handle_board_member_additions(old_doc)
            )

    def after_insert(self):
        """After insert hook"""
        # Create corresponding Department for ERPNext integration
        self._sync_department()
        # Create corresponding Cost Center for financial tracking
        self._create_chapter_cost_center()

    def after_save(self):
        """After save hook - streamlined with safe operations"""
        # Handle cost center renaming if chapter name changed
        if self.has_value_changed("name"):
            self._safe_manager_operation(
                "cost_center_rename",
                lambda: self._update_chapter_cost_center_name(),
            )

        # NOTE: Volunteer sync removed from here (2025-11-18)
        # Now handled exclusively via event-driven architecture in on_update()
        # This prevents duplicate processing and race conditions

    def _safe_manager_operation(self, operation_name: str, operation_func):
        """Execute manager operation safely with proper error handling"""
        try:
            operation_func()
        except Exception as e:
            error_context = {"chapter": self.name, "operation": operation_name}
            log_error(e, context=error_context, module="verenigingen.doctype.chapter")
            # Don't block save for manager operation errors, just log them

    def on_update(self):
        """On update hook with event emission for background processing"""
        self._clear_manager_caches()

        # Sync Department status if changed (name changes handled in after_rename)
        old_doc = self.get_doc_before_save()
        if old_doc and self.has_value_changed("status"):
            self._sync_department(old_doc)

        # Emit events for significant changes to trigger background operations
        if old_doc:
            self._emit_chapter_change_events(old_doc)

    def after_rename(self, old_name, new_name, merge=False):
        """Handle department renaming when chapter is renamed.

        Note: Department names use the format "{department_name} - {company_abbr}"
        so we must look up by department_name field, not by the primary key name.
        """
        if merge:
            return  # Don't sync departments during merge operations

        try:
            # Get company to find the department (same pattern as DepartmentSyncService)
            company = frappe.db.get_single_value("Verenigingen Settings", "company")
            if not company:
                company = frappe.db.get_single_value("Global Defaults", "default_company")

            # Look up department by department_name field, not by name
            # Department name format is "{department_name} - {company_abbr}"
            old_dept_name = frappe.db.get_value(
                "Department", {"department_name": old_name, "company": company}, "name"
            )

            if old_dept_name:
                # Update the department_name field - ERPNext's before_rename hook
                # will handle adding the company abbreviation to the new name
                frappe.rename_doc("Department", old_dept_name, new_name, force=True)

                # Get the new department name after rename (includes company abbr)
                new_dept_name = frappe.db.get_value(
                    "Department", {"department_name": new_name, "company": company}, "name"
                )

                frappe.logger().info(
                    f"Renamed Department from {old_dept_name} to {new_dept_name} to match chapter rename"
                )

                # Update the chapter's department field link with actual department name
                if new_dept_name:
                    frappe.db.set_value(
                        "Chapter", new_name, "department", new_dept_name, update_modified=False
                    )
        except Exception as e:
            # Don't block rename if department sync fails, but notify user
            frappe.log_error(
                f"Failed to rename Department for chapter {old_name} -> {new_name}: {str(e)}",
                "Chapter Department Rename Error",
            )
            frappe.msgprint(
                _(
                    "Chapter renamed successfully, but the linked Department could not be updated. "
                    "You may need to manually rename the Department in ERPNext."
                ),
                indicator="orange",
                title=_("Department Sync Warning"),
            )

    # ========================================================================
    # MANAGER PROPERTIES (Lazy Loading)
    # ========================================================================

    @property
    def board_manager(self) -> BoardManager:
        """Get board manager instance"""
        if "board" not in self._managers:
            self._managers["board"] = BoardManager(self)
        return self._managers["board"]

    @property
    def member_manager(self) -> MemberManager:
        """Get member manager instance"""
        if "member" not in self._managers:
            self._managers["member"] = MemberManager(self)
        return self._managers["member"]

    @property
    def communication_manager(self) -> CommunicationManager:
        """Get communication manager instance"""
        if "communication" not in self._managers:
            self._managers["communication"] = CommunicationManager(self)
        return self._managers["communication"]

    @property
    def volunteer_integration_manager(self) -> VolunteerIntegrationManager:
        """Get volunteer integration manager instance"""
        if "volunteer_integration" not in self._managers:
            self._managers["volunteer_integration"] = VolunteerIntegrationManager(self)
        return self._managers["volunteer_integration"]

    @property
    def validator(self) -> ChapterValidator:
        """Get validator instance"""
        if self._validator is None:
            self._validator = ChapterValidator(self)
        return self._validator

    # ========================================================================
    # BOARD MANAGEMENT API (Delegated)
    # ========================================================================

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def add_board_member(self, volunteer, role, from_date=None, to_date=None):
        """Add a new board member - delegates to BoardManager"""
        return self.board_manager.add_board_member(volunteer, role, from_date, to_date)

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def remove_board_member(self, volunteer, end_date=None):
        """Remove a board member - delegates to BoardManager"""
        return self.board_manager.remove_board_member(volunteer, end_date)

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def transition_board_role(self, volunteer, new_role, transition_date=None):
        """Transition a board member's role - delegates to BoardManager"""
        return self.board_manager.transition_board_role(volunteer, new_role, transition_date)

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def bulk_remove_board_members(self, board_members):
        """Bulk remove board members - delegates to BoardManager"""
        return self.board_manager.bulk_remove_board_members(board_members)

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def bulk_deactivate_board_members(self, board_members):
        """Bulk deactivate board members - delegates to BoardManager"""
        return self.board_manager.bulk_deactivate_board_members(board_members)

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.ADMIN)
    def sync_board_members(self):
        """Sync board members with volunteer system - delegates to VolunteerIntegrationManager"""
        return self.volunteer_integration_manager.sync_board_members_with_volunteer_system()

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.ADMIN)
    def update_volunteer_assignment_history(self, volunteer_id, role, start_date, end_date):
        """Update volunteer assignment history - delegates to BoardManager"""
        return self.board_manager.update_volunteer_assignment_history(
            volunteer_id, role, start_date, end_date
        )

    def get_board_members(self, include_inactive=False, role=None):
        """Get board members - delegates to BoardManager"""
        return self.board_manager.get_board_members(include_inactive, role)

    def validate_role_profile_configuration(self):
        """Validate board role profile configuration"""
        # Validate default board role profile exists
        if self.default_board_role_profile and not frappe.db.exists(
            "Role Profile", self.default_board_role_profile
        ):
            frappe.throw(
                _("Default Board Role Profile '{0}' does not exist").format(self.default_board_role_profile)
            )

        # Validate board role-specific profiles if enabled
        if self.enable_board_role_specific_profiles:
            if not self.default_board_role_profile:
                frappe.msgprint(
                    _(
                        "Warning: Board role-specific profiles are enabled but no default board role profile is set. Board members without specific role assignments will not get any role profile."
                    )
                )

            # Check for duplicate role assignments
            role_assignments = {}
            for row in self.board_role_specific_profiles or []:
                if row.chapter_role:
                    if row.chapter_role in role_assignments:
                        frappe.throw(
                            _("Duplicate role profile assignment for Chapter Role '{0}'").format(
                                row.chapter_role
                            )
                        )
                    role_assignments[row.chapter_role] = row.role_profile

                    # Validate that the role profile exists
                    if row.role_profile and not frappe.db.exists("Role Profile", row.role_profile):
                        frappe.throw(_("Role Profile '{0}' does not exist").format(row.role_profile))

                    # Validate that the chapter role exists
                    if not frappe.db.exists("Chapter Role", row.chapter_role):
                        frappe.throw(_("Chapter Role '{0}' does not exist").format(row.chapter_role))

    def validate_chapter_access(self):
        """
        Validate chapter access permissions to prevent unauthorized edits.

        EXTRACTED: Moved to ChapterValidationService.validate_chapter_access()
        for service layer separation (Chapter Phase 2).
        """
        from verenigingen.services.chapter.chapter_validation_service import get_chapter_validation_service

        get_chapter_validation_service().validate_chapter_access(self)

    def is_board_member(self, member_name=None, user=None, volunteer_name=None):
        """Check if user is board member - delegates to BoardManager"""
        return self.board_manager.is_board_member(member_name, user, volunteer_name)

    def get_member_role(self, member_name=None, user=None, volunteer_name=None):
        """Get member's board role - delegates to BoardManager"""
        return self.board_manager.get_member_role(member_name, user, volunteer_name)

    def can_view_member_payments(self, member_name=None, user=None):
        """Check payment viewing permissions - delegates to BoardManager"""
        return self.board_manager.can_view_member_payments(member_name, user)

    def get_active_board_roles(self):
        """Get active board roles - delegates to BoardManager"""
        return self.board_manager.get_active_board_roles()

    # ========================================================================
    # MEMBER MANAGEMENT API (Delegated)
    # ========================================================================

    def add_member(self, member_id, introduction=None, website_url=None):
        """Add member to chapter - delegates to MemberManager"""
        result = self.member_manager.add_member(member_id, introduction, website_url)
        return result.get("success", False)

    def remove_member(self, member_id, leave_reason=None):
        """Remove member from chapter - delegates to MemberManager"""
        result = self.member_manager.remove_member(member_id, leave_reason)
        return result.get("success", False)

    def get_members(self, include_disabled=False):
        """Get chapter members - delegates to MemberManager"""
        return self.member_manager.get_members(include_disabled, with_details=True)

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def bulk_add_members(self, member_data_list):
        """Bulk add members - delegates to MemberManager"""
        return self.member_manager.bulk_add_members(member_data_list)

    # ========================================================================
    # COMMUNICATION API (Delegated)
    # ========================================================================

    def notify_board_member_added(self, volunteer, role):
        """Notify board member added - delegates to CommunicationManager"""
        self.communication_manager.notify_board_member_added(volunteer, role)

    def notify_board_member_removed(self, volunteer):
        """Notify board member removed - delegates to CommunicationManager"""
        self.communication_manager.notify_board_member_removed(volunteer)

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def send_chapter_newsletter(self, subject, content, recipient_filter="all"):
        """Send newsletter - delegates to CommunicationManager"""
        return self.communication_manager.send_chapter_newsletter(subject, content, recipient_filter)

    def get_communication_history(self, limit=50):
        """Get communication history - delegates to CommunicationManager"""
        return self.communication_manager.get_communication_history(limit)

    # ========================================================================
    # VALIDATION API (Delegated)
    # ========================================================================

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.UTILITY)
    def validate_postal_codes(self):
        """Validate postal codes"""
        try:
            if self.postal_codes:
                result = self.validator.postal_validator.validate_postal_codes(self.postal_codes)
                if not result.is_valid:
                    return False
                return True
            return True
        except Exception as e:
            frappe.log_error(f"Error validating postal codes for {self.name}: {str(e)}")
            return False

    def matches_postal_code(self, postal_code):
        """Check if postal code matches chapter patterns"""
        return self.validator.validate_postal_code_match(postal_code)

    # ========================================================================
    # CORE CHAPTER FUNCTIONALITY (Kept in main class)
    # ========================================================================

    def update_chapter_head(self):
        """
        Update chapter_head field based on board members with chair roles.

        EXTRACTED: Moved to ChapterBoardService.update_chapter_head()
        for service layer separation (Chapter Phase 2).
        """
        from verenigingen.services.chapter.chapter_board_service import get_chapter_board_service

        return get_chapter_board_service().update_chapter_head(self)

    def get_chapter_chair_optimized(self):
        """
        Find chapter chair member using optimized single query.

        EXTRACTED: Moved to ChapterBoardService.get_chapter_chair_optimized()
        for service layer separation (Chapter Phase 2).
        """
        from verenigingen.services.chapter.chapter_board_service import get_chapter_board_service

        return get_chapter_board_service().get_chapter_chair_optimized(self)

    # Chapter no longer uses WebsiteGenerator to avoid Desk form rendering conflicts.
    # WebsiteGenerator was causing child tables to not render for board members because
    # it substituted web views in place of the desk form interface.
    #
    # Public chapter pages are now handled by custom web pages:
    # - Single chapter: /www/chapter.py and /www/chapter.html
    # - Chapter list: /www/chapters.py and /www/chapters.html
    #
    # If new public chapter features are needed, extend the /www/chapter.py handler
    # instead of re-implementing WebsiteGenerator, which will reintroduce the same issues.

    def get_user_permissions_optimized(self):
        """
        Get all user permissions for this chapter using single optimized query.

        EXTRACTED: Moved to ChapterQueryService.get_user_permissions_optimized()
        for service layer separation (Chapter Phase 3).
        """
        from verenigingen.services.chapter.chapter_query_service import get_chapter_query_service

        return get_chapter_query_service().get_user_permissions_optimized(self)

    def get_members_optimized(self):
        """Optimized query to get chapter members with details"""
        try:
            return self.member_manager.get_members(with_details=True)
        except Exception as e:
            frappe.log_error(f"Error getting optimized members for chapter {self.name}: {str(e)}")
            return []

    def get_board_members_optimized(self):
        """Optimized query to get board members with details"""
        try:
            return self.board_manager.get_board_members()
        except Exception as e:
            frappe.log_error(f"Error getting optimized board members for chapter {self.name}: {str(e)}")
            return []

    def get_chapter_head_member_optimized(self):
        """Optimized loading of chapter head member"""
        if not self.chapter_head:
            return None

        try:
            return frappe.get_doc("Member", self.chapter_head)
        except frappe.DoesNotExistError:
            frappe.log_error(f"Chapter head member {self.chapter_head} not found for chapter {self.name}")
            return None
        except Exception as e:
            frappe.log_error(f"Error loading chapter head member {self.chapter_head}: {str(e)}")
            return None

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    def _auto_fix_required_fields(self):
        """
        Auto-fix missing required fields if possible to prevent validation errors.

        EXTRACTED: Moved to ChapterValidationService.auto_fix_required_fields()
        for service layer separation (Chapter Phase 2).
        """
        from verenigingen.services.chapter.chapter_validation_service import get_chapter_validation_service

        get_chapter_validation_service().auto_fix_required_fields(self)

    def _populate_board_document_fields(self):
        """
        Auto-populate uploaded_by and upload_date fields for board documents.

        EXTRACTED: Moved to ChapterBoardService.populate_board_document_fields()
        for service layer separation (Chapter Phase 2).
        """
        from verenigingen.services.chapter.chapter_board_service import get_chapter_board_service

        get_chapter_board_service().populate_board_document_fields(self)

    def _ensure_route(self):
        """Ensure route is set"""
        if not self.route:
            self.route = "chapters/" + frappe.scrub(self.name)

    def _sync_department(self, old_doc=None):
        """
        Synchronize ERPNext Department record with Chapter for native integration.

        EXTRACTED: Moved to DepartmentSyncService.sync_department()
        for service layer separation (Chapter Phase 1).
        """
        from verenigingen.services.chapter.department_sync_service import get_department_sync_service

        get_department_sync_service().sync_department(self, old_doc)

    def _handle_document_changes(self):
        """Handle changes between document versions"""
        old_doc = self.get_doc_before_save()
        if old_doc:
            # Handle board member changes
            self.board_manager.handle_board_member_changes(old_doc)
            self.board_manager.handle_board_member_additions(old_doc)

            # Handle regular member changes
            self.member_manager.handle_member_changes(old_doc)
            self.member_manager.handle_member_additions(old_doc)

    def _clear_manager_caches(self):
        """Clear all manager caches"""
        for manager in self._managers.values():
            if hasattr(manager, "clear_cache"):
                manager.clear_cache()

    def _emit_chapter_change_events(self, old_doc):
        """Emit events for significant chapter changes to trigger background processing"""
        try:
            # Detect board member changes
            self._detect_and_emit_board_changes(old_doc)

            # Detect member changes
            self._detect_and_emit_membership_changes(old_doc)

            # Detect settings changes
            self._detect_and_emit_settings_changes(old_doc)

        except Exception as e:
            frappe.log_error(
                f"Failed to emit chapter change events for {self.name}: {str(e)}",
                "Chapter Event Emission Error",
            )

    def _detect_and_emit_board_changes(self, old_doc):
        """
        Detect and emit board member changes including activation/deactivation.

        EXTRACTED: Moved to ChapterEventService.detect_and_emit_board_changes()
        for service layer separation (Chapter Phase 4).
        """
        from verenigingen.services.chapter.chapter_event_service import ChapterEventService

        ChapterEventService().detect_and_emit_board_changes(self, old_doc)

    def _detect_and_emit_membership_changes(self, old_doc):
        """
        Detect and emit chapter membership changes (joins and leaves).

        EXTRACTED: Moved to ChapterEventService.detect_and_emit_membership_changes()
        for service layer separation (Chapter Phase 4).
        """
        from verenigingen.services.chapter.chapter_event_service import ChapterEventService

        ChapterEventService().detect_and_emit_membership_changes(self, old_doc)

    def _detect_and_emit_settings_changes(self, old_doc):
        """
        Detect and emit chapter settings changes for important fields.

        EXTRACTED: Moved to ChapterEventService.detect_and_emit_settings_changes()
        for service layer separation (Chapter Phase 4).
        """
        from verenigingen.services.chapter.chapter_event_service import ChapterEventService

        ChapterEventService().detect_and_emit_settings_changes(self, old_doc)

    # ========================================================================
    # BACKWARD COMPATIBILITY METHODS
    # ========================================================================

    # Keep some key methods for backward compatibility
    def _add_to_members(self, member_id):
        """Backward compatibility - delegates to MemberManager"""
        return self.member_manager.add_member(member_id)

    # ========================================================================
    # DASHBOARD AND STATISTICS
    # ========================================================================

    def get_chapter_statistics(self):
        """Get comprehensive chapter statistics"""
        try:
            return {
                "board_stats": self.board_manager.get_summary(),
                "member_stats": self.member_manager.get_summary(),
                "communication_stats": self.communication_manager.get_summary(),
                "volunteer_integration_stats": self.volunteer_integration_manager.get_summary(),
                "last_updated": getdate(now()),
            }
        except Exception as e:
            frappe.log_error(f"Error getting statistics for chapter {self.name}: {str(e)}")
            return {
                "board_stats": {},
                "member_stats": {},
                "communication_stats": {},
                "volunteer_integration_stats": {},
                "last_updated": getdate(today()),
            }

    # ========================================================================
    # COST CENTER MANAGEMENT
    # ========================================================================

    def _create_chapter_cost_center(self):
        """
        Create a cost center for this chapter with proper security validation.

        EXTRACTED: Moved to ChapterFinanceService.create_chapter_cost_center()
        for service layer separation (Chapter Phase 1).
        """
        from verenigingen.services.chapter.chapter_finance_service import get_chapter_finance_service

        get_chapter_finance_service().create_chapter_cost_center(self)

    def _get_validated_company(self):
        """
        Get and validate company for cost center creation.

        EXTRACTED: Moved to ChapterFinanceService.get_validated_company()
        for service layer separation (Chapter Phase 1).
        """
        from verenigingen.services.chapter.chapter_finance_service import get_chapter_finance_service

        return get_chapter_finance_service().get_validated_company(self)

    def _get_appropriate_parent_cost_center(self, company):
        """
        Get appropriate parent cost center for the given company.

        EXTRACTED: Moved to ChapterFinanceService.get_appropriate_parent_cost_center()
        for service layer separation (Chapter Phase 1).
        """
        from verenigingen.services.chapter.chapter_finance_service import get_chapter_finance_service

        return get_chapter_finance_service().get_appropriate_parent_cost_center(self, company)

    def _update_chapter_cost_center_name(self):
        """
        Update cost center name when chapter name changes.

        EXTRACTED: Moved to ChapterFinanceService.update_chapter_cost_center_name()
        for service layer separation (Chapter Phase 1).
        """
        from verenigingen.services.chapter.chapter_finance_service import get_chapter_finance_service

        get_chapter_finance_service().update_chapter_cost_center_name(self)


# ============================================================================
# UTILITY FUNCTIONS (Unchanged from original)
# ============================================================================


def get_list_context(context):
    """Get list context for chapter list view"""
    context.allow_guest = True
    context.no_cache = True
    context.show_sidebar = True
    context.title = "All Chapters"
    context.no_breadcrumbs = True
    context.order_by = "creation desc"

    # Get current user's member chapters
    context.user_chapters = []
    if frappe.session.user != "Guest":
        member = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
        if member:
            context.user_chapters = frappe.get_all(
                "Chapter Member", filters={"member": member, "enabled": 1}, pluck="parent"
            )


def get_chapter_permission_query_conditions(user=None):
    """Get permission query conditions for Chapters with board member access.

    EXTRACTED: Moved to ChapterPermissionService.get_permission_query_conditions()
    for service layer separation (Chapter Phase 2 - Permission Extraction).

    This function remains as a compatibility wrapper for the hooks system.
    """
    from verenigingen.services.chapter.chapter_permission_service import get_chapter_permission_service

    return get_chapter_permission_service().get_permission_query_conditions(user)


def has_chapter_permission(doc, ptype="read", user=None):
    """Control document-level access to Chapter.

    EXTRACTED: Moved to ChapterPermissionService.has_chapter_permission()
    for service layer separation (Chapter Phase 2 - Permission Extraction).

    This function remains as a compatibility wrapper for the hooks system.

    Provides row-level security ensuring board members can only access their own chapters.
    Without this, any user with "Verenigingen Chapter Board Member" role could access ALL chapters.
    """
    from verenigingen.services.chapter.chapter_permission_service import get_chapter_permission_service

    return get_chapter_permission_service().has_chapter_permission(doc, ptype, user)


def get_user_accessible_chapters_optimized(user):
    """Single optimized query to get all chapters accessible to a user

    DEPRECATED: Use verenigingen.utils.chapter_utils.get_user_accessible_chapters() instead.
    This function will be removed in a future version.
    """
    import warnings

    warnings.warn(
        "get_user_accessible_chapters_optimized is deprecated. Use verenigingen.utils.chapter_utils.get_user_accessible_chapters()",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        # Single query to get both board and member chapters
        query = """
            SELECT DISTINCT chapter_name FROM (
                SELECT cbm.parent as chapter_name
                FROM `tabChapter Board Member` cbm
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                JOIN `tabMember` m ON v.member = m.name
                WHERE m.user = %s AND cbm.is_active = 1

                UNION

                SELECT cm.parent as chapter_name
                FROM `tabChapter Member` cm
                JOIN `tabMember` m ON cm.member = m.name
                WHERE m.user = %s AND cm.enabled = 1
            ) as accessible_chapters
        """

        result = frappe.db.sql(query, (user, user), as_dict=True)
        return [chapter.chapter_name for chapter in result]

    except Exception as e:
        frappe.log_error(f"Error in optimized chapter access query: {str(e)}")
        return []


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def leave(title, member_id, leave_reason):
    """Leave a chapter"""
    try:
        if not title or not member_id:
            frappe.throw(_("Chapter and Member ID are required"))

        chapter = frappe.get_doc("Chapter", title)
        return chapter.member_manager.remove_member(member_id, leave_reason)

    except frappe.DoesNotExistError:
        frappe.throw(_("Chapter {0} not found").format(title))
    except Exception as e:
        frappe.log_error(f"Error removing member {member_id} from chapter {title}: {str(e)}")
        frappe.throw(_("An error occurred while leaving the chapter"))


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_board_memberships(member_name):
    """Get board memberships for a member.

    Permission check extracted to ChapterPermissionService.can_user_view_member_board_info()
    """
    from verenigingen.services.chapter.chapter_permission_service import get_chapter_permission_service

    try:
        if not member_name:
            return []

        # Check if user has permission to view member information
        if not get_chapter_permission_service().can_user_view_member_board_info(member_name):
            frappe.throw(_("You don't have permission to view this member's board information"))

        # First find the volunteer record for this member
        volunteer_name = frappe.db.get_value("Volunteer", {"member": member_name}, "name")
        if not volunteer_name:
            return []

        CBM = DocType("Chapter Board Member")
        board_memberships = (
            frappe.qb.from_(CBM)
            .select(CBM.parent, CBM.chapter_role)
            .where((CBM.volunteer == volunteer_name) & (CBM.is_active == 1))
        ).run(as_dict=True)

        return board_memberships

    except Exception as e:
        frappe.log_error(f"Error getting board memberships for {member_name}: {str(e)}")
        return []


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def remove_from_board(chapter_name, member_name, end_date=None):
    """Remove a member from the board"""
    try:
        if not chapter_name or not member_name:
            frappe.throw(_("Chapter and Member names are required"))

        chapter = frappe.get_doc("Chapter", chapter_name)
        return chapter.remove_board_member(member_name, end_date)

    except frappe.DoesNotExistError:
        frappe.throw(_("Chapter {0} not found").format(chapter_name))
    except Exception as e:
        frappe.log_error(f"Error removing {member_name} from board of {chapter_name}: {str(e)}")
        frappe.throw(_("An error occurred while removing the board member"))


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_chapter_board_history(chapter_name):
    """Get complete board history for a chapter.

    Permission check extracted to ChapterPermissionService.can_user_view_chapter_board_history()
    """
    from verenigingen.services.chapter.chapter_permission_service import get_chapter_permission_service

    try:
        if not chapter_name:
            frappe.throw(_("Chapter name is required"))

        # Check if user has permission to view chapter board information
        if not get_chapter_permission_service().can_user_view_chapter_board_history(chapter_name):
            frappe.throw(_("You don't have permission to view board history for this chapter"))

        chapter = frappe.get_doc("Chapter", chapter_name)
        return chapter.get_board_members(include_inactive=True)

    except frappe.DoesNotExistError:
        frappe.throw(_("Chapter {0} not found").format(chapter_name))
    except Exception as e:
        frappe.log_error(f"Error getting board history for {chapter_name}: {str(e)}")
        return []


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_chapter_stats(chapter_name):
    """Get statistics for a chapter"""
    try:
        if not chapter_name:
            frappe.throw(_("Chapter name is required"))

        chapter = frappe.get_doc("Chapter", chapter_name)
        return chapter.get_chapter_statistics()

    except frappe.DoesNotExistError:
        frappe.throw(_("Chapter {0} not found").format(chapter_name))
    except Exception as e:
        frappe.log_error(f"Error getting statistics for {chapter_name}: {str(e)}")
        return {}


@frappe.whitelist()
@standard_api(operation_type=OperationType.PUBLIC)
def get_chapters_by_postal_code(postal_code):
    """Get chapters that match a postal code.

    EXTRACTED: Moved to ChapterMatchingService.get_chapters_by_postal_code()
    for service layer separation (Chapter Phase 4 - Matching Extraction).

    This function remains as a compatibility wrapper for the API.
    """
    from verenigingen.services.chapter.chapter_matching_service import get_chapter_matching_service

    return get_chapter_matching_service().get_chapters_by_postal_code(postal_code)


@frappe.whitelist(allow_guest=True)
@standard_api(operation_type=OperationType.MEMBER_DATA)
def suggest_chapters_for_member(member, postal_code=None, state=None, city=None):
    """Suggest appropriate chapters for a member based on location data.

    EXTRACTED: Moved to ChapterMatchingService.suggest_chapters_for_member()
    for service layer separation (Chapter Phase 4 - Matching Extraction).

    This function remains as a compatibility wrapper for the API.
    """
    from verenigingen.services.chapter.chapter_matching_service import get_chapter_matching_service

    return get_chapter_matching_service().suggest_chapters_for_member(member, postal_code, state, city)


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def suggest_chapter_for_member(member_name, postal_code=None, state=None, city=None):
    """Legacy function - calls the new suggest_chapters_for_member"""
    return suggest_chapters_for_member(member_name, postal_code, state, city)


def is_chapter_management_enabled():
    """Check if chapter management is enabled in settings.

    EXTRACTED: Moved to ChapterMatchingService._is_chapter_management_enabled()
    for service layer separation (Chapter Phase 4 - Matching Extraction).

    This function remains as a compatibility wrapper.
    """
    from verenigingen.services.chapter.chapter_matching_service import get_chapter_matching_service

    return get_chapter_matching_service()._is_chapter_management_enabled()


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def assign_member_to_chapter(member, chapter, note=None):
    """Assign a member to a chapter.

    EXTRACTED: Moved to ChapterAssignmentService.assign_member()
    for service layer separation (Chapter Phase 3 - Assignment Extraction).

    This function remains as a compatibility wrapper for the API.
    """
    from verenigingen.services.chapter.chapter_assignment_service import get_chapter_assignment_service

    return get_chapter_assignment_service().assign_member(member, chapter, note)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def join_chapter(member_name, chapter_name, introduction=None, website_url=None):
    """Web method for a member to join a chapter via portal"""
    # Use centralized chapter membership manager for consistency
    from verenigingen.utils.chapter_membership_manager import ChapterMembershipManager

    result = ChapterMembershipManager.join_chapter(
        member_id=member_name,
        chapter_name=chapter_name,
        introduction=introduction,
        website_url=website_url,
        user_email=frappe.session.user,
    )

    return {"success": result.get("success", False), "added": result.get("action") == "added"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def leave_chapter(member_name, chapter_name, leave_reason=None):
    """Web method for a member to leave a chapter via portal"""
    # Use centralized chapter membership manager for consistency
    from verenigingen.utils.chapter_membership_manager import ChapterMembershipManager

    result = ChapterMembershipManager.leave_chapter(
        member_id=member_name,
        chapter_name=chapter_name,
        leave_reason=leave_reason,
        user_email=frappe.session.user,
    )

    return {
        "success": result.get("success", False),
        "removed": result.get("action") in ["removed", "disabled"],
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def assign_member_to_chapter_with_cleanup(member, chapter, note=None):
    """Assign a member to a chapter with automatic cleanup of existing memberships.

    EXTRACTED: Moved to ChapterAssignmentService.assign_with_cleanup()
    for service layer separation (Chapter Phase 3 - Assignment Extraction).

    This function remains as a compatibility wrapper for the API.
    """
    from verenigingen.services.chapter.chapter_assignment_service import get_chapter_assignment_service

    return get_chapter_assignment_service().assign_with_cleanup(member, chapter, note)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_board_role_profile_preview(chapter_name):
    """Get preview of which role profiles would be assigned to chapter board members.

    CONSOLIDATED: Already uses centralized chapter_role_profile_manager (utils/).
    Board role profile logic is centralized - this is just an API wrapper.

    Note: Consider moving chapter_role_profile_manager to services/ in future
    for consistency with other chapter services.
    """
    from verenigingen.utils.chapter_role_profile_manager import determine_role_profile_for_board_member

    if not chapter_name or not frappe.db.exists("Chapter", chapter_name):
        return {"error": "Chapter not found"}

    chapter_doc = frappe.get_doc("Chapter", chapter_name)

    preview = {
        "chapter_name": chapter_name,
        "default_profile": chapter_doc.get("default_board_role_profile"),
        "role_specific_enabled": chapter_doc.get("enable_board_role_specific_profiles", False),
        "role_specific_profiles": {},
        "member_assignments": [],
    }

    # Build role-specific mapping
    if preview["role_specific_enabled"] and chapter_doc.get("board_role_specific_profiles"):
        for row in chapter_doc.board_role_specific_profiles:
            if row.chapter_role and row.role_profile:
                preview["role_specific_profiles"][row.chapter_role] = row.role_profile

    # Preview assignments for current board members
    for member in chapter_doc.board_members or []:
        if member.volunteer and member.is_active:
            assigned_profile = determine_role_profile_for_board_member(chapter_name, member.chapter_role)

            member_info = {
                "volunteer": member.volunteer,
                "volunteer_name": member.volunteer_name,
                "chapter_role": member.chapter_role,
                "assigned_profile": assigned_profile,
                "assignment_source": "none",
            }

            # Determine assignment source
            if assigned_profile:
                if (
                    preview["role_specific_enabled"]
                    and member.chapter_role in preview["role_specific_profiles"]
                ):
                    member_info["assignment_source"] = "role_specific"
                elif assigned_profile == preview["default_profile"]:
                    member_info["assignment_source"] = "default"
                else:
                    member_info["assignment_source"] = "hardcoded_fallback"

            preview["member_assignments"].append(member_info)

    return preview


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def bulk_apply_chapter_board_role_profiles(chapter_name):
    """Apply role profiles to all current chapter board members.

    CONSOLIDATED: Already uses centralized chapter_role_profile_manager (utils/).
    Board role profile logic is centralized - this is just an API wrapper.
    """
    from verenigingen.utils.chapter_role_profile_manager import bulk_assign_chapter_board_role_profiles

    if not chapter_name or not frappe.db.exists("Chapter", chapter_name):
        return {"success": False, "error": "Chapter not found"}

    try:
        result = bulk_assign_chapter_board_role_profiles(chapter_name)
        return result
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Bulk Chapter Board Role Profile Assignment Error")
        return {"success": False, "error": str(e)}
